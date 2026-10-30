"""
Batch Experiment Runner Module.

Coordinates automated multi-algorithm, multi-trace comparative evaluations:
- Enumerates all available synthetic bandwidth traces.
- Executes Throughput-based, Buffer-based (BBA), and Hybrid algorithms across each trace.
- Produces a consolidated session summary CSV.
- Automatically generates comparative Matplotlib visualization plots.
"""

import csv
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple, Union

from ..config import SimulationConfig
from .experiment import run_experiment, resolve_trace_path, ExperimentResult
from .visualization import generate_all_visualizations


DEFAULT_ALGORITHMS = ["throughput", "buffer", "hybrid"]


@dataclass
class BatchRunResult:
    """Contains outcomes from an entire batch experiment campaign."""
    summary_data: List[Dict[str, Any]]
    results: List[ExperimentResult]
    consolidated_csv: Path
    plot_files: List[Path]
    successful_runs: int
    failed_runs: int


def discover_traces(trace_dir: Union[str, Path] = "data/traces") -> List[Path]:
    """
    Discovers all CSV trace files in trace_dir, sorted alphabetically.
    """
    p = Path(trace_dir).resolve()
    if not p.is_dir():
        raise FileNotFoundError(f"Trace directory '{p}' does not exist.")
    traces = sorted(list(p.glob("*.csv")))
    if not traces:
        raise FileNotFoundError(f"No CSV trace files found in '{p}'.")
    return traces


def run_batch_evaluation(
    algorithms: Optional[List[str]] = None,
    trace_dir: Union[str, Path] = "data/traces",
    output_dir: Union[str, Path] = "results",
    num_segments: Optional[int] = 30,
    config: Optional[SimulationConfig] = None,
    generate_plots: bool = True,
) -> BatchRunResult:
    """
    Executes all requested algorithms against all discovered traces.

    Args:
        algorithms: List of algorithm names (defaults to ['throughput', 'buffer', 'hybrid']).
        trace_dir: Directory containing CSV traces.
        output_dir: Directory where batch results and plots will be stored.
        num_segments: Number of chunks per run (default: 30 for balanced trace coverage).
        config: Optional custom SimulationConfig.
        generate_plots: Whether to generate PNG comparison plots.

    Returns:
        BatchRunResult: Consolidated outputs and artifact locations.
    """
    algos = algorithms if algorithms is not None else list(DEFAULT_ALGORITHMS)
    traces = discover_traces(trace_dir)
    sim_config = config if config is not None else SimulationConfig()

    out_root = Path(output_dir).resolve()
    batch_runs_dir = out_root / "batch_runs"
    plots_dir = out_root / "plots"
    batch_runs_dir.mkdir(parents=True, exist_ok=True)
    plots_dir.mkdir(parents=True, exist_ok=True)

    summary_records: List[Dict[str, Any]] = []
    completed_results: List[ExperimentResult] = []
    fluctuating_segment_logs: Dict[str, List[Dict[str, Any]]] = {}

    successful_count = 0
    failed_count = 0

    print(f"\n=======================================================")
    print(f"      STARTING BATCH ABR EXPERIMENTAL EVALUATION       ")
    print(f"=======================================================")
    print(f"  Algorithms ({len(algos)}) : {', '.join(algos)}")
    print(f"  Traces ({len(traces)})     : {', '.join(t.name for t in traces)}")
    print(f"  Total Experiments : {len(algos) * len(traces)}")
    print(f"  Segments per run  : {num_segments}")
    print(f"-------------------------------------------------------\n")

    for trace_idx, trace_file in enumerate(traces, 1):
        print(f"[{trace_idx}/{len(traces)}] Evaluating Trace: {trace_file.name}")

        for algo_name in algos:
            print(f"   -> Running {algo_name.title()}... ", end="", flush=True)

            try:
                res = run_experiment(
                    algorithm=algo_name,
                    trace_path=trace_file,
                    num_segments=num_segments,
                    config=sim_config,
                )

                # Export individual segment log into batch_runs
                seg_csv, _ = res.export_csv(output_dir=batch_runs_dir, run_id="batch")

                # If this is the fluctuating trace, capture segment logs for time-series charts
                if "fluctuating" in trace_file.name.lower():
                    fluctuating_segment_logs[res.algorithm_name] = res.segments

                # Calculate min buffer occupancy from segment records
                min_buf = min([s.get("buffer_after_sec", 0.0) for s in res.segments]) if res.segments else 0.0
                attempted = res.summary["segments_attempted"]
                completed = res.summary["segments_completed"]
                completion_rate = round(completed / attempted, 4) if attempted > 0 else 0.0

                # Standardized summary row
                row = {
                    "algorithm": res.summary["algorithm_name"],
                    "trace": trace_file.name,
                    "trace_name": trace_file.name,
                    "segments_attempted": attempted,
                    "segments_completed": completed,
                    "segments_failed": res.summary["segments_failed"],
                    "completion_rate": completion_rate,
                    "avg_selected_bitrate_kbps": res.summary["avg_selected_bitrate_kbps"],
                    "avg_delivered_bitrate_kbps": res.summary["avg_delivered_bitrate_kbps"],
                    "startup_delay_sec": res.summary["startup_delay_sec"],
                    "playback_rebuffer_time_sec": res.summary["playback_rebuffer_time_sec"],
                    "total_rebuffer_time_sec": res.summary["total_rebuffer_time_sec"],
                    "rebuffer_ratio": res.summary["rebuffer_ratio"],
                    "rebuffer_events_count": res.summary["rebuffer_events_count"],
                    "playback_rebuffer_events_count": res.summary["playback_rebuffer_events_count"],
                    "bitrate_switches_count": res.summary["bitrate_switches_count"],
                    "total_switch_magnitude_kbps": res.summary["total_switch_magnitude_kbps"],
                    "avg_switch_magnitude_kbps": res.summary["avg_switch_magnitude_kbps"],
                    "avg_buffer_sec": res.summary["avg_buffer_sec"],
                    "avg_buffer_occupancy_sec": res.summary["avg_buffer_sec"],
                    "min_buffer_occupancy_sec": round(min_buf, 2),
                    "total_playback_time_sec": res.summary["total_playback_time_sec"],
                    "total_download_time_sec": res.summary["total_download_time_sec"],
                    "total_simulated_time_sec": res.summary["total_simulated_time_sec"],
                    "total_session_time_sec": res.summary["total_simulated_time_sec"],
                    "timeout_count": res.summary["timeout_count"],
                    "total_qoe": res.summary["total_qoe"],
                    "qoe_score": res.summary["total_qoe"],
                    "run_status": "COMPLETED",
                }

                summary_records.append(row)
                completed_results.append(res)
                successful_count += 1
                print(f"OK (QoE: {row['total_qoe']:.2f}, AvgBitrate: {row['avg_delivered_bitrate_kbps']:.1f} kbps)")

            except Exception as e:
                failed_count += 1
                print(f"FAILED ({e})")
                failed_row = {
                    "algorithm": algo_name,
                    "trace": trace_file.name,
                    "run_status": f"FAILED: {e}",
                }
                summary_records.append(failed_row)

    # Export consolidated summary CSV
    consolidated_csv = out_root / "batch_summary.csv"
    if summary_records:
        fieldnames = list(summary_records[0].keys())
        with open(consolidated_csv, mode="w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(summary_records)

    # Generate visualization charts if requested
    plot_files: List[Path] = []
    if generate_plots and successful_count > 0:
        print("\n--- Generating Comparison Charts ---")
        try:
            plot_files = generate_all_visualizations(
                summary_data=summary_records,
                fluctuating_segment_logs=fluctuating_segment_logs,
                plots_dir=plots_dir,
            )
            for p in plot_files:
                print(f"  [Plot] {p.name}")
        except Exception as e:
            print(f"Warning: Failed to generate visualization charts: {e}", file=sys.stderr)

    print(f"\n=======================================================")
    print(f"             BATCH EVALUATION COMPLETE                 ")
    print(f"=======================================================")
    print(f"  Successful Experiments : {successful_count} / {len(algos) * len(traces)}")
    print(f"  Failed Experiments     : {failed_count}")
    print(f"  Summary CSV Location   : {consolidated_csv}")
    print(f"  Plots Output Directory : {plots_dir}")
    print(f"=======================================================\n")

    return BatchRunResult(
        summary_data=summary_records,
        results=completed_results,
        consolidated_csv=consolidated_csv,
        plot_files=plot_files,
        successful_runs=successful_count,
        failed_runs=failed_count,
    )
