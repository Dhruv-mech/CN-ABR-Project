"""
Experiment Runner Module.

Coordinates the end-to-end simulation of Adaptive Bitrate (ABR) streaming:
- Loads network bandwidth traces from CSV.
- Instantiates and binds ABR algorithms, the network simulator, and the video player.
- Simulates segment downloads sequentially without leaking future bandwidth information.
- Records segment-level metrics and produces consolidated session summaries.
- Exports experiment logs to CSV files.
"""

import csv
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple, Union

from ..config import SimulationConfig
from ..algorithms import BaseABR, ThroughputBasedABR, BufferBasedABR, HybridQoEABR
from .network import NetworkSimulator
from .player import VideoPlayer
from ..metrics.qoe import QoECalculator


ALGORITHM_MAP = {
    "throughput": ThroughputBasedABR,
    "throughput-based": ThroughputBasedABR,
    "throughput_based": ThroughputBasedABR,
    "buffer": BufferBasedABR,
    "buffer-based": BufferBasedABR,
    "buffer_based": BufferBasedABR,
    "bba": BufferBasedABR,
    "hybrid": HybridQoEABR,
    "hybrid-qoe": HybridQoEABR,
    "hybrid_qoe": HybridQoEABR,
    "proposed": HybridQoEABR,
}


@dataclass
class ExperimentResult:
    """Encapsulates the complete output of an ABR simulation run."""
    algorithm_name: str
    trace_name: str
    segments: List[Dict[str, Any]]
    summary: Dict[str, Any]
    config: SimulationConfig

    def export_csv(
        self,
        output_dir: Union[str, Path] = "results",
        run_id: Optional[str] = None
    ) -> Tuple[Path, Path]:
        """
        Exports segment-level logs and session summary to CSV files.

        Args:
            output_dir: Directory where CSV files will be saved.
            run_id: Optional identifier tag for the filenames.

        Returns:
            Tuple[Path, Path]: (segment_csv_path, summary_csv_path)
        """
        out_path = Path(output_dir).resolve()
        out_path.mkdir(parents=True, exist_ok=True)

        clean_algo = self.algorithm_name.lower().replace(" ", "_").replace("-", "_")
        clean_trace = Path(self.trace_name).stem
        tag = f"_{run_id}" if run_id else f"_{int(time.time())}"

        seg_file = out_path / f"{clean_algo}_{clean_trace}{tag}_segments.csv"
        sum_file = out_path / f"{clean_algo}_{clean_trace}{tag}_summary.csv"

        # Export segment-level records
        if self.segments:
            fieldnames = list(self.segments[0].keys())
            with open(seg_file, mode="w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(self.segments)
        else:
            with open(seg_file, mode="w", newline="", encoding="utf-8") as f:
                f.write("# No segments recorded\n")

        # Export session summary
        with open(sum_file, mode="w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["metric", "value"])
            for k, v in self.summary.items():
                writer.writerow([k, v])

        return seg_file, sum_file


def resolve_trace_path(trace_name_or_path: Union[str, Path], trace_dir: Union[str, Path] = "data/traces") -> Path:
    """
    Locates a trace file either by relative/absolute path or filename within trace_dir.

    Args:
        trace_name_or_path: Filename (e.g. 'synthetic_stable_high.csv') or path.
        trace_dir: Default directory where traces reside.

    Returns:
        Path: Resolved existing file path.

    Raises:
        FileNotFoundError: If the trace file cannot be found.
    """
    candidate = Path(trace_name_or_path)
    if candidate.is_file():
        return candidate.resolve()

    dir_candidate = Path(trace_dir) / candidate.name
    if dir_candidate.is_file():
        return dir_candidate.resolve()

    # Try appending .csv if omitted
    if not candidate.suffix:
        dir_csv = Path(trace_dir) / f"{candidate.name}.csv"
        if dir_csv.is_file():
            return dir_csv.resolve()

    available = []
    if Path(trace_dir).is_dir():
        available = [p.name for p in Path(trace_dir).glob("*.csv")]

    raise FileNotFoundError(
        f"Trace file not found: '{trace_name_or_path}'. "
        f"Available traces in '{trace_dir}': {available}"
    )


def create_algorithm(
    algorithm_name: str,
    config: SimulationConfig
) -> BaseABR:
    """
    Instantiates the requested ABR algorithm using simulation configuration parameters.

    Args:
        algorithm_name: 'throughput', 'buffer', or 'hybrid' (and common aliases).
        config: SimulationConfig containing bitrate ladders and threshold settings.

    Returns:
        BaseABR: An initialized ABR algorithm instance.

    Raises:
        ValueError: If algorithm_name is unrecognized.
    """
    key = algorithm_name.strip().lower()
    if key not in ALGORITHM_MAP:
        valid_keys = ["throughput", "buffer", "hybrid"]
        raise ValueError(
            f"Invalid algorithm '{algorithm_name}'. Choose from: {valid_keys}"
        )

    algo_cls = ALGORITHM_MAP[key]

    if algo_cls is ThroughputBasedABR:
        return ThroughputBasedABR(
            bitrate_ladder_kbps=config.video.bitrate_ladder_kbps,
            safety_factor=config.throughput_safety_factor,
        )
    elif algo_cls is BufferBasedABR:
        return BufferBasedABR(
            bitrate_ladder_kbps=config.video.bitrate_ladder_kbps,
            reservoir_sec=config.buffer.reservoir_sec,
            cushion_sec=config.buffer.cushion_sec,
        )
    elif algo_cls is HybridQoEABR:
        return HybridQoEABR(
            bitrate_ladder_kbps=config.video.bitrate_ladder_kbps,
            segment_duration_sec=config.video.segment_duration_sec,
            reservoir_sec=config.buffer.reservoir_sec,
            cushion_sec=config.buffer.cushion_sec,
        )

    raise ValueError(f"Unsupported algorithm class: {algo_cls}")


def run_experiment(
    algorithm: Union[str, BaseABR],
    trace_path: Union[str, Path],
    num_segments: Optional[int] = None,
    config: Optional[SimulationConfig] = None,
    max_consecutive_timeouts: int = 5,
) -> ExperimentResult:
    """
    Executes a complete ABR video streaming simulation experiment.

    Strictly enforces NO FUTURE-INFORMATION LEAKAGE:
    The algorithm is passed only current buffer occupancy and past completed
    segment throughput. It never inspects future network conditions.

    Args:
        algorithm: Algorithm name ('throughput', 'buffer', 'hybrid') or BaseABR instance.
        trace_path: Path or filename of the CSV bandwidth trace.
        num_segments: Number of video segments to download (defaults to config.video.total_segments).
        config: SimulationConfig instance (defaults to default SimulationConfig).
        max_consecutive_timeouts: Terminal safety cap for consecutive network timeouts.

    Returns:
        ExperimentResult: Complete record of segment events and summary statistics.

    Raises:
        FileNotFoundError: If trace file is missing.
        ValueError: If parameters are invalid.
    """
    sim_config = config if config is not None else SimulationConfig()

    resolved_trace = resolve_trace_path(trace_path, trace_dir=sim_config.network.trace_directory)

    # Instantiate algorithm if string provided
    if isinstance(algorithm, str):
        abr = create_algorithm(algorithm, sim_config)
    elif isinstance(algorithm, BaseABR):
        abr = algorithm
        abr.reset()
    else:
        raise ValueError(f"Algorithm must be a string name or BaseABR instance, got: {type(algorithm)}")

    total_segments = num_segments if num_segments is not None else sim_config.video.total_segments
    if total_segments <= 0:
        raise ValueError(f"num_segments must be a positive integer, got: {total_segments}")

    # Instantiate network simulator and video player
    network = NetworkSimulator.from_csv(
        resolved_trace,
        latency_sec=sim_config.network.default_latency_sec,
        timeout_sec=sim_config.network.download_timeout_sec,
    )
    player = VideoPlayer(
        segment_duration_sec=sim_config.video.segment_duration_sec,
        max_buffer_sec=sim_config.buffer.max_buffer_sec,
        startup_threshold_sec=sim_config.buffer.startup_threshold_sec,
        rebuffer_threshold_sec=sim_config.buffer.rebuffer_threshold_sec,
    )
    qoe_calc = QoECalculator(
        alpha=sim_config.qoe.alpha,
        beta=sim_config.qoe.beta,
        gamma=sim_config.qoe.gamma,
    )

    segment_duration = sim_config.video.segment_duration_sec
    segment_records: List[Dict[str, Any]] = []

    last_throughput_kbps = 0.0
    last_download_time_sec = 0.0
    last_bitrate_kbps: Optional[int] = None
    consecutive_timeouts = 0

    # Simulation loop
    for seg_idx in range(total_segments):
        buffer_before = player.buffer_sec
        request_start_time = network.current_time_sec

        # 1. Algorithm decision (Only past and current information provided!)
        selected_bitrate = abr.select_bitrate(
            segment_index=seg_idx,
            current_buffer_sec=buffer_before,
            last_throughput_kbps=last_throughput_kbps,
            last_download_time_sec=last_download_time_sec,
            last_bitrate_kbps=last_bitrate_kbps,
        )

        # Validate decision belongs to ladder
        if selected_bitrate not in sim_config.video.bitrate_ladder_kbps:
            raise ValueError(
                f"Algorithm '{abr.name}' selected bitrate {selected_bitrate} kbps "
                f"which is not in configured ladder: {sim_config.video.bitrate_ladder_kbps}"
            )

        # Retrieve estimated throughput from algorithm if available (for logging)
        estimated_tp = getattr(abr, "current_estimate_kbps", None)
        if estimated_tp is None:
            estimated_tp = getattr(abr, "estimated_throughput_kbps", None)

        # 2. Segment sizing & Network transit
        segment_size_kb = selected_bitrate * segment_duration
        segment_size_bytes = int(segment_size_kb * 1000 / 8)

        download_time_sec, actual_tp_kbps = network.simulate_segment_download(segment_size_kb)
        download_completion_time = network.current_time_sec

        # Determine if download timed out or failed
        is_timeout = (download_time_sec >= network.timeout_sec and actual_tp_kbps <= 0.0)
        is_success = not is_timeout

        if is_timeout:
            consecutive_timeouts += 1
        else:
            consecutive_timeouts = 0

        # 3. Client buffer & playback update
        stall_sec = player.receive_segment(
            bitrate_kbps=selected_bitrate,
            download_time_sec=download_time_sec,
            segment_duration_sec=segment_duration,
            success=is_success,
        )
        buffer_after = player.buffer_sec

        # 4. Record segment telemetry
        segment_records.append({
            "segment_index": seg_idx,
            "request_start_time_sec": round(request_start_time, 3),
            "download_completion_time_sec": round(download_completion_time, 3),
            "algorithm_name": abr.name,
            "trace_name": resolved_trace.name,
            "selected_bitrate_kbps": selected_bitrate,
            "segment_duration_sec": segment_duration,
            "segment_size_kb": segment_size_kb,
            "segment_size_bytes": segment_size_bytes,
            "download_time_sec": round(download_time_sec, 3),
            "actual_throughput_kbps": round(actual_tp_kbps, 1),
            "estimated_throughput_kbps": (
                round(estimated_tp, 1) if estimated_tp is not None and estimated_tp > 0 else ""
            ),
            "buffer_before_sec": round(buffer_before, 3),
            "buffer_after_sec": round(buffer_after, 3),
            "stall_sec": round(stall_sec, 3),
            "download_success": is_success,
            "is_timeout": is_timeout,
        })

        # 5. Update state for next chunk
        last_throughput_kbps = actual_tp_kbps if is_success else 0.0
        last_download_time_sec = download_time_sec
        last_bitrate_kbps = selected_bitrate

        # Terminal condition check: persistent network outage
        if consecutive_timeouts >= max_consecutive_timeouts:
            break

    # Compile session summary
    successful_segments = [s for s in segment_records if s["download_success"]]
    failed_segments_count = len(segment_records) - len(successful_segments)

    # Distinguish selected bitrate vs delivered bitrate
    all_selected_bitrates = [s["selected_bitrate_kbps"] for s in segment_records]
    delivered_bitrates = [s["selected_bitrate_kbps"] for s in successful_segments]

    avg_selected_bitrate = (
        round(sum(all_selected_bitrates) / len(all_selected_bitrates), 1)
        if all_selected_bitrates else 0.0
    )
    avg_delivered_bitrate = (
        round(sum(delivered_bitrates) / len(delivered_bitrates), 1)
        if delivered_bitrates else 0.0
    )

    stalls_for_qoe = [s["stall_sec"] for s in segment_records]
    qoe_metrics = qoe_calc.calculate_session_qoe(delivered_bitrates, stalls_for_qoe)

    avg_buf = (
        sum(s["buffer_after_sec"] for s in segment_records) / len(segment_records)
        if segment_records else 0.0
    )

    playback_rebuf = player.playback_rebuffer_time_sec
    play_time = player.total_playback_time_sec
    rebuf_denom = play_time + playback_rebuf
    rebuffer_ratio = round(playback_rebuf / rebuf_denom, 4) if rebuf_denom > 0 else 0.0

    summary = {
        "algorithm_name": abr.name,
        "trace_name": resolved_trace.name,
        "segments_attempted": len(segment_records),
        "segments_completed": len(successful_segments),
        "segments_failed": failed_segments_count,
        "avg_selected_bitrate_kbps": avg_selected_bitrate,
        "avg_delivered_bitrate_kbps": avg_delivered_bitrate,
        "avg_bitrate_kbps": avg_delivered_bitrate,  # backward compatibility alias
        "startup_delay_sec": round(player.startup_delay_sec, 3),
        "playback_rebuffer_time_sec": round(playback_rebuf, 3),
        "total_rebuffer_time_sec": round(player.total_rebuffer_time_sec, 3),
        "rebuffer_ratio": rebuffer_ratio,
        "rebuffer_events_count": player.rebuffer_events_count,
        "playback_rebuffer_events_count": player.playback_rebuffer_events_count,
        "bitrate_switches_count": qoe_metrics["bitrate_switches_count"],
        "total_switch_magnitude_kbps": qoe_metrics.get("total_switch_magnitude_kbps", 0.0),
        "avg_switch_magnitude_kbps": qoe_metrics["avg_switch_magnitude_kbps"],
        "avg_buffer_sec": round(avg_buf, 2),
        "total_playback_time_sec": round(play_time, 3),
        "total_download_time_sec": round(sum(s["download_time_sec"] for s in segment_records), 3),
        "total_simulated_time_sec": round(network.current_time_sec, 3),
        "timeout_count": sum(1 for s in segment_records if s["is_timeout"]),
        "total_qoe": qoe_metrics["total_qoe"],
    }

    return ExperimentResult(
        algorithm_name=abr.name,
        trace_name=resolved_trace.name,
        segments=segment_records,
        summary=summary,
        config=sim_config,
    )
