"""
Throughput-Based (Rate-Based) ABR Algorithm.

Core Concept:
Estimates available network throughput using past segment download speeds and
selects the highest bitrate that fits within a conservative fraction (safety factor)
of that estimate.

Features:
- Maintains recent completed-segment throughput measurements in a rolling window.
- Supports Harmonic Mean (standard in ABR research for conservative averaging)
  and Exponential Moving Average (EMA).
- Configurable safety factor (e.g. 0.85) to absorb throughput fluctuations.
- Gracefully handles initial segment (segment 0) and missing/zero throughput measurements.
"""

from typing import List, Optional
from .base import BaseABR


class ThroughputBasedABR(BaseABR):
    """
    Standard throughput-driven ABR policy.
    """

    def __init__(
        self,
        bitrate_ladder_kbps: Optional[List[int]] = None,
        safety_factor: float = 0.85,
        window_size: int = 5,
        estimation_method: str = "harmonic",
        ema_alpha: float = 0.3,
        initial_bitrate_kbps: Optional[int] = None,
    ):
        """
        Initialize the ThroughputBasedABR algorithm.

        Args:
            bitrate_ladder_kbps: Available video bitrates in ascending order (kbps).
            safety_factor: Fraction of estimated throughput to budget (0.0 < safety_factor <= 1.0).
            window_size: Number of recent segment throughput samples to retain.
            estimation_method: 'harmonic' (default, robust against spikes), 'ema', or 'arithmetic'.
            ema_alpha: Weight given to the most recent sample when method is 'ema'.
            initial_bitrate_kbps: Starting bitrate (defaults to lowest ladder rate).
        """
        super().__init__(name="Throughput-Based", bitrate_ladder_kbps=bitrate_ladder_kbps)

        if not (0.0 < safety_factor <= 1.0):
            raise ValueError(f"Safety factor must be in (0.0, 1.0], got {safety_factor}")
        if window_size < 1:
            raise ValueError(f"Window size must be at least 1, got {window_size}")
        if estimation_method not in ("harmonic", "ema", "arithmetic"):
            raise ValueError(f"Unknown estimation method: {estimation_method}")

        self.safety_factor = safety_factor
        self.window_size = window_size
        self.estimation_method = estimation_method
        self.ema_alpha = ema_alpha
        self.initial_bitrate_kbps = (
            initial_bitrate_kbps if initial_bitrate_kbps is not None else self.bitrate_ladder_kbps[0]
        )

        # Internal state
        self.throughput_history: List[float] = []
        self.current_estimate_kbps: float = 0.0

    def update_estimate(self, last_throughput_kbps: float) -> float:
        """
        Updates the internal throughput estimate using the most recent observation.

        Args:
            last_throughput_kbps: Observed throughput of the last completed segment in kbps.

        Returns:
            float: Updated throughput estimate in kbps.
        """
        if last_throughput_kbps <= 0.0:
            return self.current_estimate_kbps

        self.throughput_history.append(last_throughput_kbps)
        if len(self.throughput_history) > self.window_size:
            self.throughput_history.pop(0)

        if self.estimation_method == "harmonic":
            # Harmonic mean = n / sum(1 / x_i)
            # Penalizes optimistic outlier spikes more than arithmetic mean
            sum_reciprocals = sum(1.0 / max(x, 1e-6) for x in self.throughput_history)
            self.current_estimate_kbps = len(self.throughput_history) / sum_reciprocals

        elif self.estimation_method == "ema":
            if self.current_estimate_kbps <= 0.0:
                self.current_estimate_kbps = last_throughput_kbps
            else:
                self.current_estimate_kbps = (
                    self.ema_alpha * last_throughput_kbps + (1.0 - self.ema_alpha) * self.current_estimate_kbps
                )

        elif self.estimation_method == "arithmetic":
            self.current_estimate_kbps = sum(self.throughput_history) / len(self.throughput_history)

        return self.current_estimate_kbps

    def select_bitrate(
        self,
        segment_index: int,
        current_buffer_sec: float,
        last_throughput_kbps: float,
        last_download_time_sec: float,
        last_bitrate_kbps: Optional[int] = None,
    ) -> int:
        """
        Selects the highest available bitrate that fits within the conservative throughput estimate.

        Args:
            segment_index: Index of the chunk to download (0, 1, 2, ...).
            current_buffer_sec: Playback buffer occupancy in seconds.
            last_throughput_kbps: Throughput observed during previous download.
            last_download_time_sec: Duration taken by previous download.
            last_bitrate_kbps: Bitrate of the previous segment.

        Returns:
            int: Selected bitrate in kbps from self.bitrate_ladder_kbps.
        """
        # Step 1: Update throughput estimate if valid observation exists
        if last_throughput_kbps > 0.0:
            self.update_estimate(last_throughput_kbps)

        # Step 2: Handle missing/initial measurements safely
        if self.current_estimate_kbps <= 0.0:
            return self.initial_bitrate_kbps

        # Step 3: Compute conservative safe bandwidth budget
        safe_throughput = self.current_estimate_kbps * self.safety_factor

        # Step 4: Pick the highest bitrate ladder entry <= safe_throughput
        selected = self.bitrate_ladder_kbps[0]
        for rate in self.bitrate_ladder_kbps:
            if rate <= safe_throughput:
                selected = rate
            else:
                break

        return selected

    def reset(self) -> None:
        """Resets estimator history and state variables between simulation runs."""
        self.throughput_history.clear()
        self.current_estimate_kbps = 0.0
