"""
Command-Line Interface for QoE-Driven ABR Simulation Experiments.

Usage:
  # Single Experiment Run
  py main.py --algorithm hybrid --trace synthetic_fluctuating.csv --segments 50

  # Batch Evaluation (all 3 algorithms x all 5 traces + comparison plots)
  py main.py --batch

  # List available synthetic traces
  py main.py --list-traces
"""

import sys
import argparse
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.config import SimulationConfig
from src.simulator.experiment import run_experiment, resolve_trace_path, ALGORITHM_MAP
from src.simulator.batch import run_batch_evaluation, discover_traces


def parse_arguments() -> argparse.Namespace:
    """Parses command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Run Adaptive Bitrate (ABR) Video Streaming Experiments on Windows.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    parser.add_argument(
        "-a", "--algorithm",
        type=str,
        default="hybrid",
        help="ABR algorithm to run: 'throughput', 'buffer', or 'hybrid'.",
    )
    parser.add_argument(
        "-t", "--trace",
        type=str,
        default="synthetic_fluctuating.csv",
        help="Filename or path of bandwidth trace CSV (under data/traces/).",
    )
    parser.add_argument(
        "-n", "--segments",
        type=int,
        default=50,
        help="Number of video segments to simulate.",
    )
    parser.add_argument(
        "-o", "--output-dir",
        type=str,
        default="results",
        help="Directory where CSV logs and plots will be saved.",
    )
    parser.add_argument(
        "--run-id",
        type=str,
        default=None,
        help="Optional unique tag for output filenames.",
    )
    parser.add_argument(
        "--batch",
        action="store_true",
        help="Run batch evaluation: all 3 algorithms across all 5 synthetic traces + charts.",
    )
    parser.add_argument(
        "--no-plots",
        action="store_true",
        help="Disable automatic plot generation in batch mode.",
    )
    parser.add_argument(
        "--list-traces",
        action="store_true",
        help="List available synthetic trace files in data/traces/ and exit.",
    )
    parser.add_argument(
        "--encode-dash",
        action="store_true",
        help="Encode source video into multi-bitrate MPEG-DASH stream (Stage 7).",
    )
    parser.add_argument(
        "--input-video",
        type=str,
        default="media/input.mp4",
        help="Path to source video for DASH encoding.",
    )
    parser.add_argument(
        "--dash-output-dir",
        type=str,
        default="static/dash",
        help="Directory to store encoded DASH MPD and segments.",
    )
    parser.add_argument(
        "--dash-preset",
        type=str,
        default="veryfast",
        help="FFmpeg x264 preset for DASH encoding (ultrafast, veryfast, medium).",
    )
    parser.add_argument(
        "--serve",
        action="store_true",
        help="Start the local Flask HTTP server for MPEG-DASH video streaming (Stage 8A).",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=5000,
        help="Port number for the Flask HTTP streaming server (default: 5000).",
    )
    parser.add_argument(
        "--host",
        type=str,
        default="127.0.0.1",
        help="Host address for the Flask HTTP streaming server (default: 127.0.0.1).",
    )

    return parser.parse_args()


def list_available_traces(trace_dir: Path) -> None:
    """Displays available trace files in the console."""
    print(f"\nAvailable synthetic bandwidth traces in '{trace_dir}':")
    if not trace_dir.is_dir():
        print("  (Directory not found)")
        return

    traces = sorted(list(trace_dir.glob("*.csv")))
    if not traces:
        print("  (No CSV traces found)")
        return

    for t in traces:
        print(f"  - {t.name}")
    print()


def print_summary_table(summary: dict) -> None:
    """Prints a formatted summary table of experiment metrics."""
    print("\n" + "=" * 62)
    print("             ABR SIMULATION EXPERIMENT SUMMARY")
    print("=" * 62)

    rows = [
        ("Algorithm", summary.get("algorithm_name", "N/A")),
        ("Trace File", summary.get("trace_name", "N/A")),
        ("Segments Attempted", summary.get("segments_attempted", 0)),
        ("Segments Completed", summary.get("segments_completed", 0)),
        ("Segments Failed", summary.get("segments_failed", 0)),
        ("Average Selected Bitrate", f"{summary.get('avg_selected_bitrate_kbps', 0.0):.1f} kbps"),
        ("Average Delivered Bitrate", f"{summary.get('avg_delivered_bitrate_kbps', 0.0):.1f} kbps"),
        ("Startup Delay", f"{summary.get('startup_delay_sec', 0.0):.3f} s"),
        ("Playback Rebuffer Time", f"{summary.get('playback_rebuffer_time_sec', 0.0):.3f} s"),
        ("Total Stall Time", f"{summary.get('total_rebuffer_time_sec', 0.0):.3f} s"),
        ("Rebuffer Ratio", f"{summary.get('rebuffer_ratio', 0.0) * 100:.2f}%"),
        ("Rebuffering Events", summary.get("rebuffer_events_count", 0)),
        ("Total Active Playback", f"{summary.get('total_playback_time_sec', 0.0):.3f} s"),
        ("Quality Switches Count", summary.get("bitrate_switches_count", 0)),
        ("Total Switch Magnitude", f"{summary.get('total_switch_magnitude_kbps', 0.0):.1f} kbps"),
        ("Avg Switch Magnitude", f"{summary.get('avg_switch_magnitude_kbps', 0.0):.1f} kbps"),
        ("Average Buffer Occupancy", f"{summary.get('avg_buffer_sec', 0.0):.2f} s"),
        ("Total Simulated Time", f"{summary.get('total_simulated_time_sec', 0.0):.3f} s"),
        ("Session QoE Score", f"{summary.get('total_qoe', 0.0):.3f}"),
    ]

    for label, val in rows:
        print(f"  {label:<28} : {val}")
    print("=" * 62)


def main() -> int:
    """Main execution function."""
    args = parse_arguments()

    config = SimulationConfig()
    trace_dir = PROJECT_ROOT / config.network.trace_directory

    if args.list_traces:
        list_available_traces(trace_dir)
        return 0

    # DASH Video Encoding Mode (Stage 7)
    if args.encode_dash:
        from src.media.encode_dash import encode_to_dash
        try:
            print("\n--- Starting MPEG-DASH Video Encoding ---")
            res = encode_to_dash(
                input_path=args.input_video,
                output_dir=args.dash_output_dir,
                segment_duration_sec=2.0,
                preset=args.dash_preset,
            )
            print("\n============================================================")
            print("               DASH ENCODING COMPLETE")
            print("============================================================")
            print(f"  Manifest File          : {res['manifest_path']}")
            print(f"  Video Representations  : {res['representations_count']}")
            print(f"  Init Segments Generated: {res['init_segments_count']}")
            print(f"  Media Chunks Generated : {res['media_segments_count']}")
            print("============================================================\n")
            return 0
        except Exception as e:
            print(f"\nError during DASH encoding: {e}", file=sys.stderr)
            return 1

    # DASH HTTP Streaming Server Mode (Stage 8A)
    if args.serve:
        from src.web.server import run_server
        try:
            run_server(host=args.host, port=args.port, dash_dir=args.dash_output_dir)
            return 0
        except KeyboardInterrupt:
            print("\nServer stopped.")
            return 0
        except Exception as e:
            print(f"\nServer error: {e}", file=sys.stderr)
            return 1

    # Batch Evaluation Mode
    if args.batch:
        if args.segments <= 0:
            print(f"Error: Number of segments must be positive (got {args.segments}).", file=sys.stderr)
            return 1

        batch_result = run_batch_evaluation(
            trace_dir=trace_dir,
            output_dir=args.output_dir,
            num_segments=args.segments,
            config=config,
            generate_plots=not args.no_plots,
        )

        if batch_result.failed_runs > 0:
            print(f"Notice: {batch_result.failed_runs} runs encountered issues.")
            return 1
        return 0

    # Single Experiment Mode
    algo_key = args.algorithm.strip().lower()
    if algo_key not in ALGORITHM_MAP:
        print(f"Error: Unknown algorithm '{args.algorithm}'.", file=sys.stderr)
        print("Choose from: 'throughput', 'buffer', 'hybrid'.", file=sys.stderr)
        return 1

    if args.segments <= 0:
        print(f"Error: Number of segments must be positive (got {args.segments}).", file=sys.stderr)
        return 1

    try:
        resolved_trace = resolve_trace_path(args.trace, trace_dir=trace_dir)
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    print("\n--- Starting ABR Experiment ---")
    print(f"  Algorithm : {args.algorithm.title()}")
    print(f"  Trace     : {resolved_trace.name}")
    print(f"  Segments  : {args.segments}")

    try:
        result = run_experiment(
            algorithm=args.algorithm,
            trace_path=resolved_trace,
            num_segments=args.segments,
            config=config,
        )
    except Exception as e:
        print(f"\nSimulation failed with error: {e}", file=sys.stderr)
        return 2

    seg_csv, sum_csv = result.export_csv(
        output_dir=args.output_dir,
        run_id=args.run_id,
    )

    print_summary_table(result.summary)
    print("\nResult Logs Saved:")
    print(f"  - Segment Log : {seg_csv}")
    print(f"  - Summary Log : {sum_csv}\n")

    return 0


if __name__ == "__main__":
    sys.exit(main())
