"""
Proposed QoE-Driven Hybrid ABR Algorithm.

Core Concept:
Combines throughput estimation, prediction error (uncertainty), buffer trajectory,
expected segment download times, and quality switching penalties into a joint decision
framework.

Design Objectives:
1. Throughput Awareness: Uses a smoothed harmonic mean of past throughput samples
   to establish an achievable bandwidth ceiling.
2. Prediction Uncertainty Penalty: Calculates the coefficient of variation (CV) of
   throughput. When the channel is volatile/noisy, the algorithm automatically lowers
   its safety factor to guard against sudden collapses.
3. Buffer-Guided Risk Scaling: Linearly scales the throughput budget according to
   buffer health. In the reservoir zone, it forces the lowest bitrate; in the cushion zone,
   it conservatively throttles quality; and in the healthy zone, it unlocks full capacity.
4. Expected Download Time Feasibility: Estimates whether downloading a candidate chunk
   will finish before the client buffer drains, filtering out high-risk choices.
5. Cautious Step-Up & Asymmetric Switching: Limits quality up-switches to at most one tier
   at a time and requires healthy buffer levels, while allowing rapid multi-tier down-switches
   when network conditions deteriorate.
6. Anti-Flicker QoE Objective: Incorporates a bitrate switching penalty into the candidate
   selection to avoid erratic quality oscillations.
"""

import math
from typing import List, Optional
from .base import BaseABR


class HybridQoEABR(BaseABR):
    """
    Proposed QoE-Driven Hybrid ABR policy.
    """

    def __init__(
        self,
        bitrate_ladder_kbps: Optional[List[int]] = None,
        segment_duration_sec: float = 2.0,
        safety_factor_base: float = 0.90,
        safety_factor_min: float = 0.60,
        volatility_weight: float = 0.30,
        reservoir_sec: float = 5.0,
        cushion_sec: float = 10.0,
        stall_safety_margin_sec: float = 0.5,
        switch_penalty_lambda: float = 0.5,
        window_size: int = 5,
        initial_bitrate_kbps: Optional[int] = None,
    ):
        """
        Initialize the HybridQoEABR algorithm.

        Args:
            bitrate_ladder_kbps: Available video bitrates in ascending order (kbps).
            segment_duration_sec: Playable duration of each chunk (seconds).
            safety_factor_base: Baseline fraction of throughput budgeted in stable conditions.
            safety_factor_min: Minimum allowable safety factor during high volatility.
            volatility_weight: Sensitivity penalty scaling factor for throughput volatility.
            reservoir_sec: Buffer threshold below which quality drops to minimum (seconds).
            cushion_sec: Buffer span above reservoir where quality scales up (seconds).
            stall_safety_margin_sec: Safety buffer headroom required for download completion.
            switch_penalty_lambda: Weight penalizing quality changes in the objective function.
            window_size: Number of past throughput measurements tracked.
            initial_bitrate_kbps: Starting bitrate (defaults to lowest ladder rate).
        """
        super().__init__(name="QoE-Driven Hybrid", bitrate_ladder_kbps=bitrate_ladder_kbps)

        if not (0.0 < safety_factor_min <= safety_factor_base <= 1.0):
            raise ValueError("Safety factors must satisfy 0.0 < min <= base <= 1.0")
        if reservoir_sec < 0 or cushion_sec <= 0:
            raise ValueError("Reservoir must be >= 0 and Cushion must be > 0")
        if window_size < 1:
            raise ValueError("Window size must be at least 1")

        self.segment_duration_sec = segment_duration_sec
        self.safety_factor_base = safety_factor_base
        self.safety_factor_min = safety_factor_min
        self.volatility_weight = volatility_weight
        self.reservoir_sec = reservoir_sec
        self.cushion_sec = cushion_sec
        self.stall_safety_margin_sec = stall_safety_margin_sec
        self.switch_penalty_lambda = switch_penalty_lambda
        self.window_size = window_size
        self.initial_bitrate_kbps = (
            initial_bitrate_kbps if initial_bitrate_kbps is not None else self.bitrate_ladder_kbps[0]
        )

        # State tracking
        self.throughput_history: List[float] = []
        self.estimated_throughput_kbps: float = 0.0
        self.last_selected_bitrate: Optional[int] = None

    def update_throughput_state(self, last_throughput_kbps: float) -> None:
        """
        Records the observed throughput sample and updates the harmonic mean estimate.
        """
        if last_throughput_kbps > 0.0:
            self.throughput_history.append(last_throughput_kbps)
            if len(self.throughput_history) > self.window_size:
                self.throughput_history.pop(0)

            # Harmonic mean estimate: conservative against upward outlier spikes
            reciprocals = [1.0 / max(x, 1e-6) for x in self.throughput_history]
            self.estimated_throughput_kbps = len(self.throughput_history) / sum(reciprocals)

    def compute_volatility(self) -> float:
        """
        Computes the coefficient of variation (CV) of throughput measurements.
        CV = std_dev / mean. Returns 0.0 if fewer than 2 samples exist.
        """
        if len(self.throughput_history) < 2:
            return 0.0

        n = len(self.throughput_history)
        mean_tp = sum(self.throughput_history) / n
        if mean_tp <= 1e-6:
            return 0.0

        variance = sum((x - mean_tp) ** 2 for x in self.throughput_history) / n
        std_dev = math.sqrt(variance)
        return std_dev / mean_tp

    def select_bitrate(
        self,
        segment_index: int,
        current_buffer_sec: float,
        last_throughput_kbps: float,
        last_download_time_sec: float,
        last_bitrate_kbps: Optional[int] = None,
    ) -> int:
        """
        Selects the bitrate optimizing visual quality, stall avoidance, and smoothness.

        Args:
            segment_index: Index of the chunk to download (0, 1, 2, ...).
            current_buffer_sec: Current playback buffer occupancy in seconds.
            last_throughput_kbps: Throughput observed during previous download.
            last_download_time_sec: Duration taken by previous download.
            last_bitrate_kbps: Bitrate of the previous segment.

        Returns:
            int: Selected bitrate in kbps from self.bitrate_ladder_kbps.
        """
        prev_bitrate = last_bitrate_kbps if last_bitrate_kbps is not None else self.last_selected_bitrate

        # Step 1: Update throughput history
        if last_throughput_kbps > 0.0:
            self.update_throughput_state(last_throughput_kbps)

        # Step 2: Handle initial segment or zero observations
        if self.estimated_throughput_kbps <= 0.0:
            selected = self.initial_bitrate_kbps
            self.last_selected_bitrate = selected
            return selected

        # Step 3: Critical Stall Protection (Reservoir Check)
        # If buffer is below reservoir, drop to lowest quality to prevent playback freeze
        if current_buffer_sec <= self.reservoir_sec:
            selected = self.bitrate_ladder_kbps[0]
            self.last_selected_bitrate = selected
            return selected

        # Step 4: Volatility and Uncertainty Discount
        # High variation decreases the effective safety factor
        cv = self.compute_volatility()
        effective_safety = max(
            self.safety_factor_min,
            self.safety_factor_base - (self.volatility_weight * cv)
        )
        effective_bandwidth = self.estimated_throughput_kbps * effective_safety

        # Step 5: Buffer-Guided Capacity Scaling
        # Scale bandwidth budget proportionally to cushion occupancy
        target_buffer = self.reservoir_sec + self.cushion_sec
        if current_buffer_sec < target_buffer:
            buffer_factor = (current_buffer_sec - self.reservoir_sec) / self.cushion_sec
            bandwidth_budget = effective_bandwidth * buffer_factor
        else:
            bandwidth_budget = effective_bandwidth

        # Step 6: Filter Feasible Candidate Bitrates
        # Must fit within bandwidth_budget (or fallback to minimum)
        feasible_bitrates: List[int] = []
        for rate in self.bitrate_ladder_kbps:
            # Expected download time check: rate * dur / estimated_tp
            exp_download_time = (rate * self.segment_duration_sec) / max(self.estimated_throughput_kbps, 1.0)
            # Only consider candidate if download time won't exceed buffer
            if rate <= bandwidth_budget and (exp_download_time < (current_buffer_sec - self.stall_safety_margin_sec)):
                feasible_bitrates.append(rate)

        # Fallback: if no bitrate passed budget and feasibility, pick minimum ladder rate
        if not feasible_bitrates:
            feasible_bitrates = [self.bitrate_ladder_kbps[0]]

        # Step 7: Apply Cautious Step-Up Constraint
        # Prevent jumping multiple tiers upward in a single step
        if prev_bitrate is not None and prev_bitrate in self.bitrate_ladder_kbps:
            prev_idx = self.bitrate_ladder_kbps.index(prev_bitrate)
            max_allowed_idx = min(len(self.bitrate_ladder_kbps) - 1, prev_idx + 1)
            max_stepup_bitrate = self.bitrate_ladder_kbps[max_allowed_idx]

            # Require comfortable buffer (> reservoir + 30% cushion) before stepping up
            stepup_buffer_req = self.reservoir_sec + (0.3 * self.cushion_sec)
            constrained_candidates: List[int] = []

            for r in feasible_bitrates:
                if r > prev_bitrate:
                    if r <= max_stepup_bitrate and current_buffer_sec >= stepup_buffer_req:
                        constrained_candidates.append(r)
                else:
                    constrained_candidates.append(r)

            if constrained_candidates:
                feasible_bitrates = constrained_candidates

        # Step 8: Objective Function Evaluation (Quality Utility - Switching Penalty)
        # Select the candidate that maximizes utility while penalizing frequent switches
        best_bitrate = feasible_bitrates[0]
        best_utility = float("-inf")
        ref_bitrate = prev_bitrate if prev_bitrate is not None else self.bitrate_ladder_kbps[0]

        for rate in feasible_bitrates:
            # Quality utility (in Mbps)
            quality_utility = rate / 1000.0
            # Switch magnitude penalty (in Mbps)
            switch_penalty = self.switch_penalty_lambda * (abs(rate - ref_bitrate) / 1000.0)
            score = quality_utility - switch_penalty

            if score > best_utility:
                best_utility = score
                best_bitrate = rate

        self.last_selected_bitrate = best_bitrate
        return best_bitrate

    def reset(self) -> None:
        """Resets estimator history and state variables between simulation runs."""
        self.throughput_history.clear()
        self.estimated_throughput_kbps = 0.0
        self.last_selected_bitrate = None
