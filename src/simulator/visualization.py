"""
Visualization Module for QoE-Driven ABR Simulation Results.

Generates comparative performance plots from simulation results using Matplotlib:
1. Average Bitrate Comparison across all traces.
2. Rebuffering Duration / Ratio Comparison across all traces.
3. Composite QoE Score Comparison across all traces.
4. Bitrate Trajectory over Time (on fluctuating trace).
5. Buffer Occupancy over Time (on fluctuating trace).
6. Quality Switching Frequency & Magnitude Comparison.
"""

from pathlib import Path
from typing import List, Dict, Any, Union, Optional

import matplotlib
matplotlib.use("Agg")  # Non-interactive headless backend for automated runs
import matplotlib.pyplot as plt
import numpy as np


ALGORITHM_COLORS = {
    "Throughput-Based": "#1f77b4",  # Steel Blue
    "Buffer-Based (BBA)": "#ff7f0e",  # Safety Orange
    "QoE-Driven Hybrid": "#2ca02c",  # Forest Green
}

# Fallback color palette
FALLBACK_COLORS = ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd"]


def _get_color(algo_name: str, index: int = 0) -> str:
    """Returns consistent color for an algorithm name."""
    for key, color in ALGORITHM_COLORS.items():
        if key.lower() in algo_name.lower():
            return color
    return FALLBACK_COLORS[index % len(FALLBACK_COLORS)]


def plot_bar_metric(
    summary_data: List[Dict[str, Any]],
    metric_key: str,
    metric_label: str,
    output_path: Path,
    unit: str = "",
    title: Optional[str] = None,
) -> Path:
    """
    Generates a grouped bar chart comparing algorithms across traces for a given metric.
    """
    traces = sorted(list({row["trace"] for row in summary_data}))
    algos = sorted(list({row["algorithm"] for row in summary_data}))

    if not traces or not algos:
        raise ValueError("Cannot plot with empty traces or algorithms list.")

    fig, ax = plt.subplots(figsize=(10, 5.5), dpi=150)
    x = np.arange(len(traces))
    width = 0.8 / len(algos)

    for i, algo in enumerate(algos):
        values = []
        for trace in traces:
            matching = [r for r in summary_data if r["trace"] == trace and r["algorithm"] == algo]
            val = float(matching[0].get(metric_key, 0.0)) if matching else 0.0
            values.append(val)

        offset = (i - (len(algos) - 1) / 2.0) * width
        color = _get_color(algo, i)
        clean_name = algo.replace(" (BBA)", "")
        rects = ax.bar(x + offset, values, width, label=clean_name, color=color, alpha=0.9, edgecolor="black", linewidth=0.5)

        # Value labels above bars for readability
        for rect in rects:
            h = rect.get_height()
            if abs(h) > 0.01:
                ax.annotate(
                    f"{h:.1f}" if abs(h) < 100 else f"{int(h)}",
                    xy=(rect.get_x() + rect.get_width() / 2, h),
                    xytext=(0, 3 if h >= 0 else -10),
                    textcoords="offset points",
                    ha="center", va="bottom" if h >= 0 else "top",
                    fontsize=7, rotation=0
                )

    clean_trace_labels = [t.replace("synthetic_", "").replace(".csv", "").replace("_", " ").title() for t in traces]
    ax.set_xticks(x)
    ax.set_xticklabels(clean_trace_labels, rotation=15, ha="right", fontsize=9)
    ylabel_str = f"{metric_label} ({unit})" if unit else metric_label
    ax.set_ylabel(ylabel_str, fontsize=10, fontweight="bold")
    ax.set_title(title or f"{metric_label} Comparison by Network Trace", fontsize=12, fontweight="bold", pad=12)
    ax.legend(loc="best", frameon=True, fontsize=9)
    ax.grid(True, linestyle="--", alpha=0.5, axis="y")

    fig.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path)
    plt.close(fig)
    return output_path


def plot_time_series(
    segment_logs_by_algo: Dict[str, List[Dict[str, Any]]],
    y_key: str,
    y_label: str,
    title: str,
    output_path: Path,
    unit: str = "",
    reference_lines: Optional[Dict[str, float]] = None,
) -> Path:
    """
    Plots segment-by-segment time series for multiple algorithms on a specific trace.
    """
    fig, ax = plt.subplots(figsize=(10, 5), dpi=150)

    for i, (algo, segments) in enumerate(segment_logs_by_algo.items()):
        if not segments:
            continue
        x_vals = [s.get("segment_index", idx) for idx, s in enumerate(segments)]
        y_vals = [float(s.get(y_key, 0.0)) for s in segments]
        color = _get_color(algo, i)
        clean_name = algo.replace(" (BBA)", "")
        ax.plot(x_vals, y_vals, label=clean_name, color=color, linewidth=1.8, marker="o", markersize=3, alpha=0.85)

    if reference_lines:
        for label, y_ref in reference_lines.items():
            ax.axhline(y=y_ref, color="red", linestyle="--", linewidth=1.2, alpha=0.7, label=label)

    ax.set_xlabel("Segment Index", fontsize=10, fontweight="bold")
    ylabel_str = f"{y_label} ({unit})" if unit else y_label
    ax.set_ylabel(ylabel_str, fontsize=10, fontweight="bold")
    ax.set_title(title, fontsize=12, fontweight="bold", pad=12)
    ax.legend(loc="best", frameon=True, fontsize=9)
    ax.grid(True, linestyle="--", alpha=0.5)

    fig.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path)
    plt.close(fig)
    return output_path


def generate_all_visualizations(
    summary_data: List[Dict[str, Any]],
    fluctuating_segment_logs: Dict[str, List[Dict[str, Any]]],
    plots_dir: Union[str, Path] = "results/plots",
) -> List[Path]:
    """
    Generates the complete set of required comparison charts.

    Returns:
        List[Path]: Paths of all generated PNG chart files.
    """
    p_dir = Path(plots_dir).resolve()
    p_dir.mkdir(parents=True, exist_ok=True)
    generated: List[Path] = []

    # 1. Average Delivered Bitrate Comparison
    chart1 = p_dir / "1_average_bitrate_comparison.png"
    plot_bar_metric(
        summary_data=summary_data,
        metric_key="avg_delivered_bitrate_kbps",
        metric_label="Average Delivered Bitrate",
        unit="kbps",
        title="Average Delivered Bitrate Comparison Across Traces",
        output_path=chart1,
    )
    generated.append(chart1)

    # 2. Rebuffering Comparison
    chart2 = p_dir / "2_rebuffering_comparison.png"
    plot_bar_metric(
        summary_data=summary_data,
        metric_key="playback_rebuffer_time_sec",
        metric_label="Playback Rebuffering Time",
        unit="seconds",
        title="Playback Rebuffering Duration Comparison",
        output_path=chart2,
    )
    generated.append(chart2)

    # 3. Composite QoE Score Comparison
    chart3 = p_dir / "3_qoe_comparison.png"
    plot_bar_metric(
        summary_data=summary_data,
        metric_key="total_qoe",
        metric_label="Session QoE Score",
        unit="QoE Index",
        title="Composite Quality of Experience (QoE) Comparison",
        output_path=chart3,
    )
    generated.append(chart3)

    # 4. Bitrate Trajectory over Time (Fluctuating Trace)
    chart4 = p_dir / "4_bitrate_over_time_fluctuating.png"
    plot_time_series(
        segment_logs_by_algo=fluctuating_segment_logs,
        y_key="selected_bitrate_kbps",
        y_label="Selected Bitrate",
        unit="kbps",
        title="Bitrate Trajectory over Time (Fluctuating Trace)",
        output_path=chart4,
    )
    generated.append(chart4)

    # 5. Buffer Occupancy over Time (Fluctuating Trace)
    chart5 = p_dir / "5_buffer_occupancy_fluctuating.png"
    plot_time_series(
        segment_logs_by_algo=fluctuating_segment_logs,
        y_key="buffer_after_sec",
        y_label="Buffer Occupancy",
        unit="seconds",
        title="Client Buffer Occupancy Dynamics (Fluctuating Trace)",
        output_path=chart5,
        reference_lines={"Reservoir (5s)": 5.0, "Cushion Target (15s)": 15.0},
    )
    generated.append(chart5)

    # 6. Quality Switching Comparison
    chart6 = p_dir / "6_switching_comparison.png"
    plot_bar_metric(
        summary_data=summary_data,
        metric_key="bitrate_switches_count",
        metric_label="Bitrate Switches Count",
        unit="switches",
        title="Quality Switching Frequency Comparison",
        output_path=chart6,
    )
    generated.append(chart6)

    return generated
