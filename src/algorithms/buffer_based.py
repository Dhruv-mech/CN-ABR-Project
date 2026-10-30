"""
Buffer-Based ABR Algorithm (BBA).

Core Concept:
Instead of relying on noisy throughput predictions, this Buffer-Based Algorithm
(inspired by BBA-0/BBA-1 and buffer-driven principles like BOLA) makes bitrate
decisions as a function of the client's current playback buffer occupancy:
- Reservoir (0 to r): Low buffer zone. Play at minimum bitrate to avoid stall and build buffer.
- Cushion (r to r + c): Normal operating zone. Linearly maps buffer occupancy to video bitrates.
- Upper Threshold (>= r + c): Healthy buffer zone. Play at maximum bitrate.
- Anti-Oscillation Hysteresis: Implements a deadband margin near tier boundaries to prevent
  annoying quality switching (flickering) when the buffer oscillates slightly.
"""

from typing import List, Optional
from .base import BaseABR


class BufferBasedABR(BaseABR):
    """
    Buffer-Based Adaptation (BBA) policy with anti-oscillation hysteresis.
    """

    def __init__(
        self,
        bitrate_ladder_kbps: Optional[List[int]] = None,
        reservoir_sec: float = 5.0,
        cushion_sec: float = 10.0,
        hysteresis_sec: float = 0.5,
    ):
        """
        Initialize the BufferBasedABR algorithm.

        Args:
            bitrate_ladder_kbps: Available video bitrates in ascending order (kbps).
            reservoir_sec: Minimum buffer below which player stays at lowest bitrate (seconds).
            cushion_sec: Buffer span over which bitrate scales from minimum to maximum (seconds).
            hysteresis_sec: Deadband margin around switching thresholds to prevent flapping.
        """
        super().__init__(name="Buffer-Based (BBA)", bitrate_ladder_kbps=bitrate_ladder_kbps)

        if reservoir_sec < 0:
            raise ValueError(f"Reservoir must be non-negative: {reservoir_sec}")
        if cushion_sec <= 0:
            raise ValueError(f"Cushion must be strictly positive: {cushion_sec}")
        if hysteresis_sec < 0:
            raise ValueError(f"Hysteresis must be non-negative: {hysteresis_sec}")

        self.reservoir_sec = reservoir_sec
        self.cushion_sec = cushion_sec
        self.hysteresis_sec = hysteresis_sec

        # Keep state of last decision
        self.last_selected_bitrate: Optional[int] = None

    def select_bitrate(
        self,
        segment_index: int,
        current_buffer_sec: float,
        last_throughput_kbps: float,
        last_download_time_sec: float,
        last_bitrate_kbps: Optional[int] = None,
    ) -> int:
        """
        Selects bitrate mapped from current buffer occupancy.

        Args:
            segment_index: Index of the chunk to download (0, 1, 2, ...).
            current_buffer_sec: Current playback buffer occupancy in seconds.
            last_throughput_kbps: Throughput observed during previous download (unused by pure BBA).
            last_download_time_sec: Duration taken by previous download.
            last_bitrate_kbps: Bitrate of the previous segment.

        Returns:
            int: Selected bitrate in kbps from self.bitrate_ladder_kbps.
        """
        num_levels = len(self.bitrate_ladder_kbps)
        prev_bitrate = last_bitrate_kbps if last_bitrate_kbps is not None else self.last_selected_bitrate

        # Rule 1: Reservoir threshold (Critical Safety Zone)
        # When buffer is at or below reservoir, force lowest bitrate immediately to prevent rebuffering
        if current_buffer_sec <= self.reservoir_sec:
            selected = self.bitrate_ladder_kbps[0]
            self.last_selected_bitrate = selected
            return selected

        # Rule 2: Upper threshold (Abundant Buffer Zone)
        # When buffer exceeds reservoir + cushion, select maximum bitrate
        max_buffer_threshold = self.reservoir_sec + self.cushion_sec
        if current_buffer_sec >= max_buffer_threshold:
            selected = self.bitrate_ladder_kbps[-1]
            self.last_selected_bitrate = selected
            return selected

        # Rule 3: Linear Mapping inside Cushion Zone
        # Map buffer occupancy linearly to continuous index [0, num_levels - 1]
        buffer_fraction = (current_buffer_sec - self.reservoir_sec) / self.cushion_sec
        target_idx = int(buffer_fraction * (num_levels - 1))
        target_idx = max(0, min(num_levels - 1, target_idx))
        candidate_bitrate = self.bitrate_ladder_kbps[target_idx]

        # Rule 4: Anti-Oscillation Hysteresis
        # If there is a previous bitrate, require buffer to cross threshold + hysteresis before switching
        if prev_bitrate is not None and prev_bitrate in self.bitrate_ladder_kbps:
            prev_idx = self.bitrate_ladder_kbps.index(prev_bitrate)

            if target_idx > prev_idx:
                # Up-switching: ensure buffer has surpassed the step threshold by at least hysteresis_sec
                step_threshold = self.reservoir_sec + (target_idx / (num_levels - 1)) * self.cushion_sec
                if current_buffer_sec < (step_threshold + self.hysteresis_sec):
                    # Stay at previous bitrate to avoid premature up-switch
                    candidate_bitrate = prev_bitrate

            elif target_idx < prev_idx:
                # Down-switching: ensure buffer has dropped below previous threshold by at least hysteresis_sec
                prev_threshold = self.reservoir_sec + (prev_idx / (num_levels - 1)) * self.cushion_sec
                if current_buffer_sec > (prev_threshold - self.hysteresis_sec):
                    # Stay at previous bitrate to avoid premature down-switch
                    candidate_bitrate = prev_bitrate

        self.last_selected_bitrate = candidate_bitrate
        return candidate_bitrate

    def reset(self) -> None:
        """Resets internal state between simulation runs."""
        self.last_selected_bitrate = None
