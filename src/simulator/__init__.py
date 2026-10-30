"""
Video Streaming and Network Simulator Modules.

Exposes:
- NetworkSimulator: Replays network traces (bandwidth variations over time)
- load_trace_from_csv: Utility to parse and validate CSV bandwidth traces
- VideoPlayer: Simulates playback buffer, chunk downloads, and stalls
- run_experiment: End-to-end ABR experiment simulation engine
- ExperimentResult: Encapsulates segment records and summary metrics
- create_algorithm: Factory to instantiate ABR algorithms
- resolve_trace_path: Helper to resolve trace file locations
- run_batch_evaluation: Runs all algorithms across all traces
- generate_all_visualizations: Generates comparative Matplotlib charts
"""

from .network import NetworkSimulator, load_trace_from_csv
from .player import VideoPlayer
from .experiment import (
    run_experiment,
    ExperimentResult,
    create_algorithm,
    resolve_trace_path,
)
from .batch import run_batch_evaluation, discover_traces
from .visualization import generate_all_visualizations

__all__ = [
    "NetworkSimulator",
    "load_trace_from_csv",
    "VideoPlayer",
    "run_experiment",
    "ExperimentResult",
    "create_algorithm",
    "resolve_trace_path",
    "run_batch_evaluation",
    "discover_traces",
    "generate_all_visualizations",
]
