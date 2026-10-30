"""
Quality of Experience (QoE) Metrics Module.

Implements standard QoE formulations used in academic networking research:
  QoE = sum(Quality) - (beta * sum(Rebuffering_Time)) - (gamma * sum(Quality_Switches))

Where:
- Quality: Bitrate utility (bitrate in Mbps: R_k / 1000).
- Rebuffering_Time: Total freeze duration experienced by the viewer (seconds).
- Quality_Switches: Magnitude of bitrate changes between consecutive segments (|R_{k+1} - R_k| in Mbps).
"""

from typing import List, Dict, Any


class QoECalculator:
    """
    Computes session QoE and performance summary statistics.
    """

    def __init__(self, alpha: float = 1.0, beta: float = 4.3, gamma: float = 1.0):
        self.alpha = alpha
        self.beta = beta
        self.gamma = gamma

    def calculate_session_qoe(
        self,
        bitrates_kbps: List[int],
        stall_times_sec: List[float]
    ) -> Dict[str, Any]:
        """
        Computes overall QoE for a streaming session.

        Args:
            bitrates_kbps: Sequence of bitrates selected for each segment.
            stall_times_sec: Sequence of stall durations incurred during each segment.

        Returns:
            Dict[str, Any]: Dictionary containing QoE score and individual components.
        """
        if not bitrates_kbps:
            return {
                "total_qoe": 0.0,
                "avg_bitrate_kbps": 0.0,
                "total_stall_sec": 0.0,
                "bitrate_switches_count": 0,
                "total_switch_magnitude_kbps": 0.0,
                "avg_switch_magnitude_kbps": 0.0,
            }

        # Quality component (scaled to Mbps for standard readable numerical range)
        bitrates_mbps = [b / 1000.0 for b in bitrates_kbps]
        quality_score = self.alpha * sum(bitrates_mbps)

        # Stall penalty
        total_stall_sec = sum(stall_times_sec)
        stall_penalty = self.beta * total_stall_sec

        # Smoothness penalty (bitrate switches)
        switch_magnitudes = [
            abs(bitrates_mbps[i] - bitrates_mbps[i - 1])
            for i in range(1, len(bitrates_mbps))
        ]
        total_switch_magnitude_mbps = sum(switch_magnitudes)
        switch_penalty = self.gamma * total_switch_magnitude_mbps

        total_qoe = quality_score - stall_penalty - switch_penalty

        return {
            "total_qoe": round(total_qoe, 3),
            "avg_bitrate_kbps": round(sum(bitrates_kbps) / len(bitrates_kbps), 1),
            "total_stall_sec": round(total_stall_sec, 3),
            "bitrate_switches_count": sum(1 for m in switch_magnitudes if m > 0.001),
            "total_switch_magnitude_kbps": round(total_switch_magnitude_mbps * 1000.0, 1),
            "avg_switch_magnitude_kbps": round(
                (total_switch_magnitude_mbps / max(1, len(switch_magnitudes))) * 1000.0, 1
            ),
        }
