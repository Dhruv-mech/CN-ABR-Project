"""Unit tests for Stage 6: Batch Evaluation, QoE standardization, and Visualizations.

These tests verify:
1. Metric semantics: startup delay vs playback rebuffering vs total rebuffering.
2. Rebuffer ratio and switch magnitude calculations.
3. Batch runner orchestration across algorithms and network traces.
4. Consolidated CSV output schema and row completeness.
5. Automated generation of all 6 publication-ready comparison plots.
6. Graceful error handling for missing traces or invalid options.
"""

import csv
import os
import shutil
import tempfile
import unittest

from src.config import SimulationConfig, VideoConfig, BufferConfig, QoEConfig, NetworkConfig
from src.simulator.player import VideoPlayer
from src.metrics.qoe import QoECalculator
from src.simulator.experiment import run_experiment, ExperimentResult
from src.simulator.batch import run_batch_evaluation, discover_traces
from src.simulator.visualization import generate_all_visualizations


class TestMetricSemantics(unittest.TestCase):
    """Verifies that metric definitions and calculations strictly align with Stage 6 specifications."""

    def test_startup_delay_vs_playback_rebuffering(self):
        """Verifies that startup delay and playback rebuffering are tracked independently.
        
        Startup delay occurs before initial playback starts.
        Playback rebuffering occurs during underruns after playback has begun.
        """
        player = VideoPlayer()
        
        # Segment 0: 2.0s download time in startup
        player.receive_segment(bitrate_kbps=1000, download_time_sec=2.0, segment_duration_sec=2.0)
        self.assertAlmostEqual(player.startup_delay_sec, 2.0)
        self.assertAlmostEqual(player.playback_rebuffer_time_sec, 0.0)
        self.assertEqual(player.playback_rebuffer_events_count, 0)
        self.assertAlmostEqual(player.total_rebuffer_time_sec, 2.0)  # Preserved backward compatibility
        
        # Now start playback and play 1.0s
        player.play_video(1.0)
        self.assertAlmostEqual(player.buffer_sec, 1.0)
        self.assertAlmostEqual(player.total_playback_time_sec, 1.0)
        
        # Segment 1: download takes 3.0s, but buffer only has 1.0s.
        # This will drain 1.0s of buffer, then stall for 2.0s.
        player.receive_segment(bitrate_kbps=1000, download_time_sec=3.0, segment_duration_sec=2.0)
        
        self.assertAlmostEqual(player.startup_delay_sec, 2.0)
        self.assertAlmostEqual(player.playback_rebuffer_time_sec, 2.0)
        self.assertEqual(player.playback_rebuffer_events_count, 1)
        self.assertAlmostEqual(player.total_rebuffer_time_sec, 4.0)

    def test_rebuffer_ratio_formula(self):
        """Verifies rebuffer_ratio = playback_rebuffer / (playback_time + playback_rebuffer)."""
        player = VideoPlayer()
        # Initial state: 0 / 0 should return 0.0 without division by zero
        self.assertEqual(player.rebuffer_ratio, 0.0)
        
        # Startup 1.0s
        player.receive_segment(bitrate_kbps=1000, download_time_sec=1.0, segment_duration_sec=2.0)
        self.assertEqual(player.rebuffer_ratio, 0.0)  # Startup is not playback rebuffering
        
        # Play 2.0s
        player.play_video(2.0)
        self.assertEqual(player.rebuffer_ratio, 0.0)
        
        # Rebuffer 2.0s during segment 1 (buffer has 0s, download takes 2.0s)
        player.receive_segment(bitrate_kbps=1000, download_time_sec=2.0, segment_duration_sec=2.0)
        # Playback time: 2.0s, Playback rebuffer time: 2.0s
        # rebuffer_ratio = 2.0 / (2.0 + 2.0) = 0.50 (50%)
        self.assertAlmostEqual(player.rebuffer_ratio, 0.50)

    def test_switch_magnitude_in_qoe_calculator(self):
        """Verifies QoECalculator returns total_switch_magnitude_kbps."""
        calc = QoECalculator()
        # Selected bitrates: 500 -> 1000 -> 1000 -> 500
        # Switches: |1000 - 500| = 500, |500 - 1000| = 500
        # Total switches: 2, Total magnitude: 1000 kbps
        res = calc.calculate_session_qoe(
            bitrates_kbps=[500, 1000, 1000, 500],
            stall_times_sec=[0.5, 0.0, 0.0, 0.0],
        )
        self.assertEqual(res["bitrate_switches_count"], 2)
        self.assertEqual(res["total_switch_magnitude_kbps"], 1000.0)


class TestBatchEvaluationPipeline(unittest.TestCase):
    """Verifies batch execution, CSV outputs, and schema conformity."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="cn_abr_batch_test_")

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_discover_traces(self):
        """Verifies discover_traces finds all 5 synthetic trace files."""
        traces = discover_traces("data/traces")
        self.assertGreaterEqual(len(traces), 5)
        names = [t.name for t in traces]
        expected_stems = [
            "stable_high",
            "stable_low",
            "fluctuating",
            "gradual_degradation",
            "sudden_drop_recovery",
        ]
        for stem in expected_stems:
            self.assertTrue(any(stem in name for name in names), f"Expected trace {stem} not discovered")

    def test_run_batch_evaluation_generates_summary_and_csvs(self):
        """Verifies running batch evaluation creates consolidated summary and run logs."""
        output_dir = os.path.join(self.test_dir, "batch_out")
        
        # Run a fast batch with 3 segments across all traces
        result = run_batch_evaluation(
            trace_dir="data/traces",
            output_dir=output_dir,
            num_segments=3,
            generate_plots=False,
        )
        
        summary_csv = result.consolidated_csv
        runs_data = result.results
        
        # 3 algorithms * 5 traces = 15 runs
        self.assertEqual(len(runs_data), 15)
        self.assertTrue(os.path.isfile(summary_csv))
        
        # Check rows in CSV
        with open(summary_csv, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        
        self.assertEqual(len(rows), 15)
        
        # Verify required column headers are all present
        expected_columns = {
            "trace_name",
            "algorithm",
            "segments_completed",
            "segments_failed",
            "completion_rate",
            "avg_selected_bitrate_kbps",
            "avg_delivered_bitrate_kbps",
            "startup_delay_sec",
            "playback_rebuffer_time_sec",
            "total_rebuffer_time_sec",
            "playback_rebuffer_events_count",
            "rebuffer_ratio",
            "bitrate_switches_count",
            "total_switch_magnitude_kbps",
            "avg_buffer_occupancy_sec",
            "min_buffer_occupancy_sec",
            "total_session_time_sec",
            "qoe_score",
        }
        for col in expected_columns:
            self.assertIn(col, reader.fieldnames, f"Missing required column: {col}")

        # Check that individual segment CSVs exist (15 segment logs + 15 run summary logs = 30 files)
        batch_runs_dir = os.path.join(output_dir, "batch_runs")
        self.assertTrue(os.path.isdir(batch_runs_dir))
        run_csvs = os.listdir(batch_runs_dir)
        self.assertEqual(len([f for f in run_csvs if f.endswith("_segments.csv")]), 15)
        self.assertEqual(len(run_csvs), 30)

    def test_error_handling_empty_or_missing_trace_dir(self):
        """Verifies FileNotFoundError when trace directory is invalid."""
        with self.assertRaises(FileNotFoundError):
            run_batch_evaluation(trace_dir="nonexistent_trace_dir_12345", output_dir=self.test_dir)


class TestVisualizationGeneration(unittest.TestCase):
    """Verifies that all 6 Matplotlib comparison charts are generated as valid PNGs."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="cn_abr_plots_test_")

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_generate_all_plots(self):
        """Verifies generate_all_plots produces all 6 PNG files with valid PNG signatures."""
        output_dir = os.path.join(self.test_dir, "batch_plots_test")
        
        # Run batch with 3 segments and generate plots
        result = run_batch_evaluation(
            trace_dir="data/traces",
            output_dir=output_dir,
            num_segments=3,
            generate_plots=True,
        )
        
        plots_generated = result.plot_files
        self.assertEqual(len(plots_generated), 6)
        
        expected_files = [
            "1_average_bitrate_comparison.png",
            "2_rebuffering_comparison.png",
            "3_qoe_comparison.png",
            "4_bitrate_over_time_fluctuating.png",
            "5_buffer_occupancy_fluctuating.png",
            "6_switching_comparison.png",
        ]
        
        for fname in expected_files:
            plot_path = os.path.join(output_dir, "plots", fname)
            self.assertTrue(os.path.isfile(plot_path), f"Expected plot file missing: {plot_path}")
            # Verify file is not 0 bytes
            size = os.path.getsize(plot_path)
            self.assertGreater(size, 1000, f"Plot file {fname} is suspiciously small: {size} bytes")
            # Verify PNG header (\x89PNG\r\n\x1a\n)
            with open(plot_path, "rb") as f:
                header = f.read(8)
                self.assertEqual(header, b"\x89PNG\r\n\x1a\n", f"{fname} is not a valid PNG")


if __name__ == "__main__":
    unittest.main()
