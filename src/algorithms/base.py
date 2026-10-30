"""
Base ABR Algorithm Interface.

All ABR implementations (Throughput-based, Buffer-based, Hybrid)
must inherit from BaseABR and implement the `select_bitrate` method.
"""

from abc import ABC, abstractmethod
from typing import List, Optional


class BaseABR(ABC):
    """
    Abstract base class establishing a uniform interface for ABR algorithms.
    
    Attributes:
        name (str): Identifier for reporting and graphing.
        bitrate_ladder_kbps (List[int]): Sorted list of available video bitrates.
    """

    def __init__(self, name: str, bitrate_ladder_kbps: Optional[List[int]] = None):
        self.name = name
        self.bitrate_ladder_kbps = sorted(
            bitrate_ladder_kbps if bitrate_ladder_kbps is not None else [300, 750, 1200, 1850, 2850, 4300]
        )

    @abstractmethod
    def select_bitrate(
        self,
        segment_index: int,
        current_buffer_sec: float,
        last_throughput_kbps: float,
        last_download_time_sec: float,
        last_bitrate_kbps: Optional[int] = None
    ) -> int:
        """
        Determines the bitrate to request for the next video segment.

        Args:
            segment_index: Sequential index of the segment to download (0, 1, 2, ...).
            current_buffer_sec: Seconds of playable video currently stored in the client buffer.
            last_throughput_kbps: Bandwidth observed while downloading the previous segment.
            last_download_time_sec: Duration in seconds taken to download the previous segment.
            last_bitrate_kbps: Bitrate selected for the previous segment.

        Returns:
            int: The chosen bitrate in kbps from self.bitrate_ladder_kbps.
        """
        pass

    def reset(self) -> None:
        """Resets any internal history or state variables between simulation runs."""
        pass
