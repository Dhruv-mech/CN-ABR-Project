"""
Configuration Module for the QoE-Driven ABR Simulation Project.

This file centralizes all tunable parameters for:
- Video encoding ladder (available bitrates)
- Chunk (segment) duration
- Buffer thresholds (reservoir, cushion, max capacity, startup/rebuffer thresholds)
- QoE penalty weights (visual quality vs. rebuffering vs. bitrate switches)
- Network simulation defaults (latency, timeout, trace directories)
"""

from dataclasses import dataclass, field
from typing import List


@dataclass
class VideoConfig:
    """Represents video encoding profiles and chunk segmentation properties."""
    # Standard DASH bitrate ladder in kbps (e.g. 240p to 1080p)
    bitrate_ladder_kbps: List[int] = field(
        default_factory=lambda: [300, 750, 1200, 1850, 2850, 4300]
    )
    # Duration of each video segment in seconds
    segment_duration_sec: float = 2.0
    # Total number of segments in a simulated video stream
    total_segments: int = 100


@dataclass
class BufferConfig:
    """Client playback buffer thresholds used by buffer-based and hybrid algorithms."""
    # Reservoir: minimum buffer below which player stays at lowest bitrate to avoid stall
    reservoir_sec: float = 5.0
    # Cushion: buffer zone where bitrate scales smoothly with buffer level
    cushion_sec: float = 10.0
    # Maximum buffer capacity: prevents excessive downloading when buffer is full
    max_buffer_sec: float = 30.0
    # Initial startup delay (seconds of video to buffer before playback starts)
    startup_threshold_sec: float = 2.0
    # Minimum buffered video required to resume playback after a stall event
    rebuffer_threshold_sec: float = 0.5


@dataclass
class QoEConfig:
    """
    Weights for Quality of Experience (QoE) evaluation.
    
    QoE Formula:
      QoE = (alpha * Quality) - (beta * Rebuffering_Time) - (gamma * Quality_Switches)
    """
    # Weight rewarded for higher video bitrate / quality
    alpha: float = 1.0
    # Penalty weight for video playback stalls / rebuffering duration (in seconds)
    beta: float = 4.3
    # Penalty weight for bitrate oscillations / fluctuations between consecutive segments
    gamma: float = 1.0


@dataclass
class NetworkConfig:
    """Network simulation defaults (latency, download timeouts, and paths)."""
    # Base network propagation latency / RTT in seconds (0.0s default preserves zero-overhead tests)
    default_latency_sec: float = 0.0
    # Maximum download duration allowed for a segment before triggering connection timeout
    download_timeout_sec: float = 30.0
    # Directory where bandwidth trace CSV files reside
    trace_directory: str = "data/traces"


@dataclass
class SimulationConfig:
    """Master configuration binding all simulation subsystems together."""
    video: VideoConfig = field(default_factory=VideoConfig)
    buffer: BufferConfig = field(default_factory=BufferConfig)
    qoe: QoEConfig = field(default_factory=QoEConfig)
    network: NetworkConfig = field(default_factory=NetworkConfig)
    # Throughput safety margin (e.g. 0.85 means conservative estimate at 85% of measured bandwidth)
    throughput_safety_factor: float = 0.85
