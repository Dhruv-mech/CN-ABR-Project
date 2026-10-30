"""
Integration Tests for the ABR Experiment Engine (Stage 5).

Verifies:
1. End-to-end simulation completion using synthetic traces.
2. Uniform experiment interface for all three ABR algorithms.
3. Bitrate ladder compliance for all selected qualities.
4. Completeness and accuracy of segment-level telemetry fields.
5. CSV export and file readback integrity in isolated temporary directories.
6. Error handling for invalid algorithms, missing traces, and non-positive segment counts.
7. Exact simulation reproducibility (determinism).
8. Strict prevention of future-information leakage to ABR algorithms.
9. Safe termination on persistent zero-bandwidth outages without infinite loops.
10. Strict enforcement of client buffer capacity bounds.
"""

import unittest
import sys
import csv
import tempfile
from pathlib import Path
from typing import Optional, List

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.config import SimulationConfig
from src.algorithms.base import BaseABR
from src.simulator.experiment import (
    run_experiment,
    resolve_trace_path,
    create_algorithm,
    ExperimentResult,
)


class LeakageDetectorABR(BaseABR):
    """
    Test spy algorithm verifying that only past/current telemetry is delivered
    and no future trace or simulation objects are leaked.
    """

    def __init__(self, bitrate_ladder_kbps=None):
        super().__init__(name="Leakage-Detector-Spy", bitrate_ladder_kbps=bitrate_ladder_kbps)
        self.call_log: List[dict] = []

    def select_bitrate(
        self,
        segment_index: int,
        current_buffer_sec: float,
        last_throughput_kbps: float,
        last_download_time_sec: float,
        last_bitrate_kbps: Optional[int] = None,
    ) -> int:
        self.call_log.append({
            "segment_index": segment_index,
            "current_buffer_sec": current_buffer_sec,
            "last_throughput_kbps": last_throughput_kbps,
            "last_download_time_sec": last_download_time_sec,
            "last_bitrate_kbps": last_bitrate_kbps,
        })
        return self.bitrate_ladder_kbps[0]


class TestExperimentEngine(unittest.TestCase):
    """Integration test suite for the ABR experiment engine."""

    def setUp(self):
        self.config = SimulationConfig()
        self.trace_file = PROJECT_ROOT / "data" / "traces" / "synthetic_stable_high.csv"
        self.fluctuating_trace = PROJECT_ROOT / "data" / "traces" / "synthetic_fluctuating.csv"

    def test_simulation_completes_valid_trace(self):
        """Verifies that an experiment runs and completes the requested segment count."""
        res = run_experiment(
            algorithm="hybrid",
            trace_path=self.trace_file,
            num_segments=10,
            config=self.config,
        )
        self.assertIsInstance(res, ExperimentResult)
        self.assertEqual(len(res.segments), 10)
        self.assertEqual(res.summary["segments_attempted"], 10)
        self.assertEqual(res.summary["segments_completed"], 10)
        self.assertGreater(res.summary["avg_bitrate_kbps"], 0)
        self.assertGreater(res.summary["total_playback_time_sec"], 0)

    def test_all_three_algorithms_run_through_same_interface(self):
        """Verifies that 'throughput', 'buffer', and 'hybrid' run uniformly."""
        algorithms = ["throughput", "buffer", "hybrid"]
        for algo_name in algorithms:
            res = run_experiment(
                algorithm=algo_name,
                trace_path=self.fluctuating_trace,
                num_segments=8,
                config=self.config,
            )
            self.assertEqual(len(res.segments), 8)
            self.assertEqual(res.summary["segments_completed"], 8)
            self.assertIn("total_qoe", res.summary)

    def test_all_selected_bitrates_belong_to_ladder(self):
        """Verifies that all chosen bitrates belong to the configured ladder."""
        ladder = self.config.video.bitrate_ladder_kbps
        for algo in ["throughput", "buffer", "hybrid"]:
            res = run_experiment(
                algorithm=algo,
                trace_path=self.fluctuating_trace,
                num_segments=10,
                config=self.config,
            )
            for seg in res.segments:
                self.assertIn(
                    seg["selected_bitrate_kbps"],
                    ladder,
                    f"Selected bitrate {seg['selected_bitrate_kbps']} not in ladder: {ladder}"
                )

    def test_segment_records_expected_fields(self):
        """Verifies that segment telemetry dictionaries contain all required fields."""
        expected_fields = {
            "segment_index",
            "request_start_time_sec",
            "download_completion_time_sec",
            "algorithm_name",
            "trace_name",
            "selected_bitrate_kbps",
            "segment_duration_sec",
            "segment_size_kb",
            "segment_size_bytes",
            "download_time_sec",
            "actual_throughput_kbps",
            "estimated_throughput_kbps",
            "buffer_before_sec",
            "buffer_after_sec",
            "stall_sec",
            "download_success",
            "is_timeout",
        }
        res = run_experiment(
            algorithm="hybrid",
            trace_path=self.trace_file,
            num_segments=5,
            config=self.config,
        )
        for seg in res.segments:
            self.assertTrue(
                expected_fields.issubset(set(seg.keys())),
                f"Missing fields: {expected_fields - set(seg.keys())}"
            )
            self.assertEqual(
                seg["segment_size_bytes"],
                int(seg["segment_size_kb"] * 1000 / 8)
            )

    def test_csv_export_and_readback(self):
        """Verifies exporting CSV logs to a temporary directory and reading them back."""
        res = run_experiment(
            algorithm="throughput",
            trace_path=self.trace_file,
            num_segments=5,
            config=self.config,
        )

        with tempfile.TemporaryDirectory() as tmp_dir:
            seg_csv, sum_csv = res.export_csv(output_dir=tmp_dir, run_id="testrun")
            self.assertTrue(seg_csv.is_file(), f"Segment CSV not created: {seg_csv}")
            self.assertTrue(sum_csv.is_file(), f"Summary CSV not created: {sum_csv}")

            # Read back segment log
            with open(seg_csv, mode="r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                rows = list(reader)
                self.assertEqual(len(rows), 5)
                self.assertEqual(int(rows[0]["segment_index"]), 0)
                self.assertIn("selected_bitrate_kbps", rows[0])

            # Read back summary log
            with open(sum_csv, mode="r", encoding="utf-8") as f:
                reader = csv.reader(f)
                summary_data = dict(list(reader))
                self.assertIn("metric", summary_data)
                self.assertIn("total_qoe", summary_data)
                self.assertIn("avg_bitrate_kbps", summary_data)

    def test_invalid_inputs_handled(self):
        """Verifies readable exceptions on invalid algorithm names, missing traces, and segment counts."""
        # Invalid algorithm name
        with self.assertRaises(ValueError) as ctx:
            run_experiment("non_existent_algo", self.trace_file, num_segments=5)
        self.assertIn("Invalid algorithm", str(ctx.exception))

        # Missing trace file
        with self.assertRaises(FileNotFoundError) as ctx:
            run_experiment("hybrid", "missing_phantom_trace.csv", num_segments=5)
        self.assertIn("Trace file not found", str(ctx.exception))

        # Invalid segment count
        with self.assertRaises(ValueError) as ctx:
            run_experiment("hybrid", self.trace_file, num_segments=-10)
        self.assertIn("positive integer", str(ctx.exception))

    def test_reproducibility_deterministic(self):
        """Verifies that two identical experiment runs produce identical results."""
        run1 = run_experiment("hybrid", self.fluctuating_trace, num_segments=15, config=self.config)
        run2 = run_experiment("hybrid", self.fluctuating_trace, num_segments=15, config=self.config)

        self.assertEqual(len(run1.segments), len(run2.segments))
        for s1, s2 in zip(run1.segments, run2.segments):
            self.assertEqual(s1["selected_bitrate_kbps"], s2["selected_bitrate_kbps"])
            self.assertEqual(s1["download_time_sec"], s2["download_time_sec"])
            self.assertEqual(s1["buffer_after_sec"], s2["buffer_after_sec"])
            self.assertEqual(s1["stall_sec"], s2["stall_sec"])

        self.assertEqual(run1.summary["total_qoe"], run2.summary["total_qoe"])
        self.assertEqual(run1.summary["avg_bitrate_kbps"], run2.summary["avg_bitrate_kbps"])

    def test_no_future_information_leakage(self):
        """
        Verifies that the ABR algorithm only receives past/current telemetry
        and cannot access future segment or trace data.
        """
        spy = LeakageDetectorABR(bitrate_ladder_kbps=self.config.video.bitrate_ladder_kbps)
        run_experiment(
            algorithm=spy,
            trace_path=self.fluctuating_trace,
            num_segments=5,
            config=self.config,
        )

        self.assertEqual(len(spy.call_log), 5)
        # Check segment 0 call: no prior throughput exists
        self.assertEqual(spy.call_log[0]["segment_index"], 0)
        self.assertEqual(spy.call_log[0]["last_throughput_kbps"], 0.0)
        self.assertIsNone(spy.call_log[0]["last_bitrate_kbps"])

        # Check subsequent calls: last_throughput_kbps is strictly non-negative and sequential
        for i in range(1, len(spy.call_log)):
            self.assertEqual(spy.call_log[i]["segment_index"], i)
            self.assertGreaterEqual(spy.call_log[i]["last_throughput_kbps"], 0.0)

    def test_zero_bandwidth_and_outage_terminates_safely(self):
        """Verifies safe termination without infinite loops on persistent zero-bandwidth outages."""
        with tempfile.NamedTemporaryFile("w", delete=False, suffix=".csv") as tmp:
            tmp.write("timestamp_sec,bandwidth_mbps\n0.0,0.0\n10.0,0.0\n")
            tmp_path = Path(tmp.name)

        try:
            # Set small timeout to test termination quickly
            cfg = SimulationConfig()
            cfg.network.download_timeout_sec = 2.0
            res = run_experiment(
                algorithm="hybrid",
                trace_path=tmp_path,
                num_segments=10,
                config=cfg,
                max_consecutive_timeouts=3,
            )
            # Should break after max_consecutive_timeouts (3)
            self.assertLessEqual(len(res.segments), 3)
            self.assertGreater(res.summary["timeout_count"], 0)
            # Buffer remains 0 because no segments downloaded successfully
            self.assertEqual(res.segments[-1]["buffer_after_sec"], 0.0)
        finally:
            tmp_path.unlink(missing_ok=True)

    def test_player_buffer_within_bounds(self):
        """Verifies that client buffer occupancy stays between 0 and max_buffer_sec."""
        max_buf = self.config.buffer.max_buffer_sec
        res = run_experiment(
            algorithm="hybrid",
            trace_path=self.trace_file,
            num_segments=25,
            config=self.config,
        )
        for s in res.segments:
            self.assertGreaterEqual(s["buffer_after_sec"], 0.0)
            self.assertLessEqual(s["buffer_after_sec"], max_buf)


if __name__ == "__main__":
    unittest.main()
