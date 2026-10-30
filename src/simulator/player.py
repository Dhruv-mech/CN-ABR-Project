"""
Video Player Buffer Simulator Module.

Models a client-side video playback buffer:
- Tracks current buffer occupancy (in seconds) and caps at max_buffer_sec.
- Simulates real-time video consumption while playback is active.
- Replenishes buffer as new segments arrive.
- Correctly detects and records startup delay, stalls (rebuffering events),
  active playback time, and download duration.
- Resumes playback according to configurable startup and rebuffer thresholds.
- Integrates seamlessly with NetworkSimulator and QoECalculator.
"""

from typing import List, Dict, Any, Optional, Tuple, TYPE_CHECKING
if TYPE_CHECKING:
    from .network import NetworkSimulator
    from ..config import BufferConfig


class VideoPlayer:
    """
    Simulates playback buffer dynamics for segmented video streaming.
    """

    def __init__(
        self,
        segment_duration_sec: float = 2.0,
        max_buffer_sec: float = 30.0,
        startup_threshold_sec: float = 2.0,
        rebuffer_threshold_sec: float = 0.5,
        config: Optional["BufferConfig"] = None,
    ):
        """
        Initialize the VideoPlayer buffer model.

        Args:
            segment_duration_sec: Playable length of each video chunk (seconds).
            max_buffer_sec: Maximum buffer storage capacity (seconds).
            startup_threshold_sec: Seconds of video required to start initial playback.
            rebuffer_threshold_sec: Seconds of video required to resume playback after stall.
            config: Optional BufferConfig instance to override parameters.
        """
        if config is not None:
            self.max_buffer_sec = config.max_buffer_sec
            self.startup_threshold_sec = config.startup_threshold_sec
            self.rebuffer_threshold_sec = getattr(config, "rebuffer_threshold_sec", 0.5)
        else:
            self.max_buffer_sec = max_buffer_sec
            self.startup_threshold_sec = startup_threshold_sec
            self.rebuffer_threshold_sec = rebuffer_threshold_sec

        self.segment_duration_sec = segment_duration_sec

        # Validation of timing parameters
        if self.segment_duration_sec < 0:
            raise ValueError(f"Segment duration cannot be negative: {self.segment_duration_sec}")
        if self.max_buffer_sec <= 0:
            raise ValueError(f"Max buffer capacity must be positive: {self.max_buffer_sec}")
        if self.startup_threshold_sec < 0:
            raise ValueError(f"Startup threshold cannot be negative: {self.startup_threshold_sec}")
        if self.rebuffer_threshold_sec < 0:
            raise ValueError(f"Rebuffer threshold cannot be negative: {self.rebuffer_threshold_sec}")

        # Dynamic state variables
        self.buffer_sec: float = 0.0
        self.is_playing: bool = False
        self.is_stalled: bool = False

        # Session metrics
        self.startup_delay_sec: float = 0.0
        self.total_rebuffer_time_sec: float = 0.0
        self.playback_rebuffer_time_sec: float = 0.0
        self.rebuffer_events_count: int = 0
        self.playback_rebuffer_events_count: int = 0
        self.total_playback_time_sec: float = 0.0
        self.total_download_time_sec: float = 0.0

        self.history: List[Dict[str, Any]] = []

    def receive_segment(
        self,
        bitrate_kbps: int,
        download_time_sec: float,
        segment_duration_sec: Optional[float] = None,
        success: bool = True,
    ) -> float:
        """
        Updates buffer state and playback time after a segment download.

        Args:
            bitrate_kbps: Bitrate of downloaded segment (in kbps).
            download_time_sec: Wall-clock time spent downloading the segment (seconds).
            segment_duration_sec: Optional duration of this specific segment (seconds).
            success: Whether download succeeded (False if timed out with 0 throughput).

        Returns:
            float: Stall (rebuffering) duration caused during this segment download (in seconds).
        """
        if bitrate_kbps < 0:
            raise ValueError(f"Bitrate cannot be negative: {bitrate_kbps}")
        if download_time_sec < 0:
            raise ValueError(f"Download time cannot be negative: {download_time_sec}")

        dur = segment_duration_sec if segment_duration_sec is not None else self.segment_duration_sec
        if dur < 0:
            raise ValueError(f"Segment duration cannot be negative: {dur}")

        self.total_download_time_sec += download_time_sec
        buffer_before = self.buffer_sec
        stall_time = 0.0
        play_time = 0.0

        if not self.is_playing:
            # Startup phase: initial buffering before video starts playing
            stall_time = download_time_sec
            self.startup_delay_sec += download_time_sec
            self.total_rebuffer_time_sec += download_time_sec
            self.rebuffer_events_count += 1
        else:
            # Active playback phase: video plays as long as buffer has content
            if download_time_sec <= self.buffer_sec:
                play_time = download_time_sec
                self.buffer_sec -= download_time_sec
                stall_time = 0.0
            else:
                play_time = self.buffer_sec
                stall_time = download_time_sec - self.buffer_sec
                self.buffer_sec = 0.0
                self.total_rebuffer_time_sec += stall_time
                self.playback_rebuffer_time_sec += stall_time
                if stall_time > 0.0:
                    self.rebuffer_events_count += 1
                    self.playback_rebuffer_events_count += 1
                    self.is_stalled = True

        self.total_playback_time_sec += play_time

        if success:
            # Add newly arrived playable content, respecting max_buffer_sec
            self.buffer_sec = min(self.buffer_sec + dur, self.max_buffer_sec)

            # Check if startup buffering is complete
            if not self.is_playing and self.buffer_sec >= self.startup_threshold_sec:
                self.is_playing = True

            # Check if recovery threshold after stall is met
            if self.is_playing and self.is_stalled and self.buffer_sec >= self.rebuffer_threshold_sec:
                self.is_stalled = False

        self.history.append({
            "segment_index": len(self.history),
            "bitrate_kbps": bitrate_kbps,
            "download_time_sec": download_time_sec,
            "buffer_before_sec": buffer_before,
            "buffer_after_sec": self.buffer_sec,
            "play_time_sec": play_time,
            "stall_sec": stall_time,
            "download_success": success,
        })

        return stall_time

    def play_video(self, duration_sec: float) -> float:
        """
        Consumes buffered video during active playback without a concurrent download.

        Args:
            duration_sec: Desired playback duration in seconds.

        Returns:
            float: Stall duration incurred if buffer is exhausted (in seconds).
        """
        if duration_sec < 0:
            raise ValueError(f"Playback duration cannot be negative: {duration_sec}")
        if duration_sec == 0.0:
            return 0.0

        if self.buffer_sec >= duration_sec:
            self.buffer_sec -= duration_sec
            self.total_playback_time_sec += duration_sec
            return 0.0

        # Buffer underrun
        played = self.buffer_sec
        stalled = duration_sec - self.buffer_sec
        self.buffer_sec = 0.0
        self.total_playback_time_sec += played
        self.total_rebuffer_time_sec += stalled
        self.playback_rebuffer_time_sec += stalled
        self.rebuffer_events_count += 1
        self.playback_rebuffer_events_count += 1
        self.is_stalled = True
        return stalled

    def download_segment_from_network(
        self,
        network: "NetworkSimulator",
        bitrate_kbps: int,
        segment_duration_sec: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Downloads a video chunk using NetworkSimulator and updates the player buffer.

        Calculates chunk size in kilobits (bitrate_kbps * duration), simulates transit,
        updates buffer, and detects stalls.

        Args:
            network: Instance of NetworkSimulator.
            bitrate_kbps: Video bitrate requested for this chunk.
            segment_duration_sec: Duration of chunk (defaults to self.segment_duration_sec).

        Returns:
            Dict[str, Any]: Download and buffer outcome dictionary.
        """
        dur = segment_duration_sec if segment_duration_sec is not None else self.segment_duration_sec
        segment_size_kb = bitrate_kbps * dur

        # Simulate network download
        download_time_sec, effective_tp = network.simulate_segment_download(segment_size_kb)

        # Detect connection timeout or zero-bandwidth failure
        is_success = not (download_time_sec >= network.timeout_sec and effective_tp <= 0.0)

        stall_sec = self.receive_segment(
            bitrate_kbps=bitrate_kbps,
            download_time_sec=download_time_sec,
            segment_duration_sec=dur,
            success=is_success,
        )

        return {
            "segment_index": len(self.history) - 1,
            "bitrate_kbps": bitrate_kbps,
            "segment_size_kb": segment_size_kb,
            "download_time_sec": download_time_sec,
            "effective_throughput_kbps": effective_tp,
            "buffer_sec": self.buffer_sec,
            "stall_sec": stall_sec,
            "download_success": is_success,
        }

    @property
    def rebuffer_ratio(self) -> float:
        """Ratio of playback rebuffering time to total playback and rebuffering time."""
        denom = self.total_playback_time_sec + self.playback_rebuffer_time_sec
        return round(self.playback_rebuffer_time_sec / denom, 4) if denom > 0 else 0.0

    def get_session_summary(self) -> Dict[str, Any]:
        """
        Summarizes session metrics for evaluation and reporting.

        Returns:
            Dict[str, Any]: Aggregated performance statistics.
        """
        bitrates = [entry["bitrate_kbps"] for entry in self.history if entry.get("download_success", True)]
        stalls = [entry["stall_sec"] for entry in self.history]
        buffer_levels = [entry["buffer_after_sec"] for entry in self.history]
        avg_buffer = (sum(buffer_levels) / len(buffer_levels)) if buffer_levels else 0.0
        denom = self.total_playback_time_sec + self.playback_rebuffer_time_sec
        rebuf_ratio = round(self.playback_rebuffer_time_sec / denom, 4) if denom > 0 else 0.0

        return {
            "bitrates_kbps": bitrates,
            "stall_times_sec": stalls,
            "total_playback_time_sec": round(self.total_playback_time_sec, 3),
            "total_rebuffer_time_sec": round(self.total_rebuffer_time_sec, 3),
            "playback_rebuffer_time_sec": round(self.playback_rebuffer_time_sec, 3),
            "startup_delay_sec": round(self.startup_delay_sec, 3),
            "rebuffer_events_count": self.rebuffer_events_count,
            "playback_rebuffer_events_count": self.playback_rebuffer_events_count,
            "rebuffer_ratio": rebuf_ratio,
            "avg_buffer_sec": round(avg_buffer, 2),
            "total_download_time_sec": round(self.total_download_time_sec, 3),
            "segments_completed": len(bitrates),
            "history": list(self.history),
        }

    def get_qoe_inputs(self) -> Tuple[List[int], List[float]]:
        """
        Extracts bitrates and stall durations formatted for direct input to QoECalculator.

        Returns:
            Tuple[List[int], List[float]]: (bitrates_kbps, stall_times_sec)
        """
        bitrates = [entry["bitrate_kbps"] for entry in self.history if entry.get("download_success", True)]
        stalls = [entry["stall_sec"] for entry in self.history]
        return bitrates, stalls

    def reset(self) -> None:
        """Resets the player buffer state for a new simulation run."""
        self.buffer_sec = 0.0
        self.is_playing = False
        self.is_stalled = False
        self.startup_delay_sec = 0.0
        self.total_rebuffer_time_sec = 0.0
        self.playback_rebuffer_time_sec = 0.0
        self.rebuffer_events_count = 0
        self.playback_rebuffer_events_count = 0
        self.total_playback_time_sec = 0.0
        self.total_download_time_sec = 0.0
        self.history.clear()
