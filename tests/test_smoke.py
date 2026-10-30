"""
Basic Smoke and Structure Verification Tests.

Uses Python's built-in `unittest` framework (zero third-party dependencies required).
Verifies:
1. Module imports and configuration parameters (including NetworkConfig and BufferConfig)
2. Algorithm stub initialization and basic interface adherence
3. Simulator stub initialization and state updates
4. QoE metrics computation
5. CSV trace loading, validations, and synthetic trace verification
6. Bandwidth lookup interpolation (zero-order hold) and boundary clamping
7. Analytical and dynamic download-time calculations, zero-bandwidth safety, and latency
8. Determinism and simulation reproducibility
9. Stage 3 Playback buffer dynamics, stalls, recovery, capacity capping, and QoE integration
10. Stage 4 Complete ABR algorithms (Throughput-based, Buffer-based BBA, and Proposed Hybrid)
"""

import unittest
import sys
import tempfile
from pathlib import Path

# Ensure 'src' is discoverable on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.config import SimulationConfig, VideoConfig, BufferConfig, QoEConfig, NetworkConfig
from src.algorithms import ThroughputBasedABR, BufferBasedABR, HybridQoEABR
from src.simulator import NetworkSimulator, VideoPlayer, load_trace_from_csv
from src.metrics import QoECalculator


class TestConfig(unittest.TestCase):
    """Verifies that simulation configuration classes initialize properly."""

    def test_default_config_values(self):
        """[Smoke Test 1] Verifies master config video and buffer bounds."""
        config = SimulationConfig()
        # Verify video ladder has at least 3 bitrates and is strictly ascending
        ladder = config.video.bitrate_ladder_kbps
        self.assertGreaterEqual(len(ladder), 3)
        self.assertEqual(ladder, sorted(ladder))
        self.assertTrue(all(r > 0 for r in ladder))

        # Verify buffer thresholds are logical: reservoir < cushion + reservoir <= max_buffer
        self.assertGreater(config.buffer.reservoir_sec, 0.0)
        self.assertGreater(config.buffer.cushion_sec, 0.0)
        self.assertGreaterEqual(
            config.buffer.max_buffer_sec,
            config.buffer.reservoir_sec + config.buffer.cushion_sec
        )

    def test_network_config_defaults(self):
        """Verifies NetworkConfig has valid non-negative latency, timeout, and trace path."""
        config = SimulationConfig()
        self.assertIsInstance(config.network, NetworkConfig)
        self.assertGreaterEqual(config.network.default_latency_sec, 0.0)
        self.assertGreater(config.network.download_timeout_sec, 0.0)
        self.assertTrue(len(config.network.trace_directory) > 0)


class TestAlgorithms(unittest.TestCase):
    """Verifies algorithm starter stubs conform to the BaseABR interface."""

    def setUp(self):
        self.ladder = [300, 750, 1200, 1850, 2850, 4300]
        self.throughput_abr = ThroughputBasedABR(bitrate_ladder_kbps=self.ladder)
        self.buffer_abr = BufferBasedABR(bitrate_ladder_kbps=self.ladder, reservoir_sec=5.0, cushion_sec=10.0)
        self.hybrid_abr = HybridQoEABR(bitrate_ladder_kbps=self.ladder)

    def test_throughput_based_decision(self):
        """[Smoke Test 2] Verifies throughput-based bitrate selection."""
        # When throughput is zero / unknown, pick lowest bitrate
        bitrate = self.throughput_abr.select_bitrate(
            segment_index=0,
            current_buffer_sec=0.0,
            last_throughput_kbps=0.0,
            last_download_time_sec=0.0
        )
        self.assertEqual(bitrate, self.ladder[0])

        # When throughput is high (e.g. 10000 kbps), pick highest bitrate
        bitrate_high = self.throughput_abr.select_bitrate(
            segment_index=1,
            current_buffer_sec=10.0,
            last_throughput_kbps=10000.0,
            last_download_time_sec=0.5
        )
        self.assertEqual(bitrate_high, self.ladder[-1])

    def test_buffer_based_decision(self):
        """[Smoke Test 3] Verifies buffer-based (BBA) bitrate selection."""
        # Buffer below reservoir -> lowest bitrate
        bitrate_low = self.buffer_abr.select_bitrate(
            segment_index=0,
            current_buffer_sec=3.0,
            last_throughput_kbps=5000.0,
            last_download_time_sec=1.0
        )
        self.assertEqual(bitrate_low, self.ladder[0])

        # Buffer above reservoir + cushion (>= 15s) -> highest bitrate
        bitrate_high = self.buffer_abr.select_bitrate(
            segment_index=1,
            current_buffer_sec=16.0,
            last_throughput_kbps=5000.0,
            last_download_time_sec=1.0
        )
        self.assertEqual(bitrate_high, self.ladder[-1])

    def test_hybrid_decision(self):
        """[Smoke Test 4] Verifies hybrid algorithm returns a valid ladder bitrate."""
        bitrate = self.hybrid_abr.select_bitrate(
            segment_index=0,
            current_buffer_sec=8.0,
            last_throughput_kbps=2500.0,
            last_download_time_sec=1.0
        )
        self.assertIn(bitrate, self.ladder)


class TestSimulator(unittest.TestCase):
    """Verifies network and video player simulator starter modules."""

    def test_network_simulator(self):
        """[Smoke Test 5] Preserved starter network simulator test."""
        net = NetworkSimulator(trace=[(0.0, 2000.0)])
        bw = net.get_bandwidth_at(0.0)
        self.assertEqual(bw, 2000.0)

        # Download 4000 kilobits at 2000 kbps -> should take 2.0 seconds
        download_time, throughput = net.simulate_segment_download(4000.0)
        self.assertAlmostEqual(download_time, 2.0, places=2)
        self.assertEqual(throughput, 2000.0)

    def test_video_player_buffer(self):
        """[Smoke Test 6] Preserved video player buffer and stall tracking test."""
        player = VideoPlayer(segment_duration_sec=2.0, max_buffer_sec=30.0)
        self.assertEqual(player.buffer_sec, 0.0)

        # First segment arrives after 1.0 second download (stall = 1.0s because buffer was 0)
        stall = player.receive_segment(bitrate_kbps=1200, download_time_sec=1.0)
        self.assertAlmostEqual(stall, 1.0)
        # Buffer should now have 2.0 seconds
        self.assertAlmostEqual(player.buffer_sec, 2.0)

        # Second segment arrives after 0.5s download (no stall, 2.0 - 0.5 + 2.0 = 3.5s)
        stall2 = player.receive_segment(bitrate_kbps=1850, download_time_sec=0.5)
        self.assertEqual(stall2, 0.0)
        self.assertAlmostEqual(player.buffer_sec, 3.5)

    def test_estimate_download_time_normal_and_latency(self):
        """Tests download duration calculation with and without latency."""
        # 3000 kb at 1500 kbps, 0 latency -> 2.0s
        t1 = NetworkSimulator.estimate_download_time(3000.0, 1500.0, latency_sec=0.0)
        self.assertAlmostEqual(t1, 2.0)

        # 3000 kb at 1500 kbps, 0.05s latency -> 2.05s
        t2 = NetworkSimulator.estimate_download_time(3000.0, 1500.0, latency_sec=0.05)
        self.assertAlmostEqual(t2, 2.05)

    def test_estimate_download_time_zero_bandwidth_and_size(self):
        """Tests zero bandwidth safety (no divide by zero) and zero segment size."""
        # Zero segment size with 0.1s latency -> 0.1s
        t_zero_size = NetworkSimulator.estimate_download_time(0.0, 2000.0, latency_sec=0.1)
        self.assertAlmostEqual(t_zero_size, 0.1)

        # Zero bandwidth without timeout cap -> float('inf')
        t_inf = NetworkSimulator.estimate_download_time(2000.0, 0.0, latency_sec=0.0)
        self.assertEqual(t_inf, float("inf"))

        # Zero bandwidth with timeout cap (30.0s) -> 30.0s
        t_timeout = NetworkSimulator.estimate_download_time(2000.0, 0.0, latency_sec=0.0, timeout_sec=30.0)
        self.assertEqual(t_timeout, 30.0)

    def test_estimate_download_time_invalid_inputs(self):
        """Tests that negative sizes or latencies raise ValueError."""
        with self.assertRaises(ValueError):
            NetworkSimulator.estimate_download_time(-100.0, 2000.0)
        with self.assertRaises(ValueError):
            NetworkSimulator.estimate_download_time(100.0, 2000.0, latency_sec=-0.5)

    def test_bandwidth_lookup_rules_and_boundaries(self):
        """Tests step-wise interpolation and edge boundary clamping."""
        # Trace with points at t=0s (1000 kbps), t=2s (3000 kbps), t=5s (5000 kbps)
        net = NetworkSimulator(trace=[(0.0, 1000.0), (2.0, 3000.0), (5.0, 5000.0)])

        # Before first sample (t < 0): clamps to first sample (1000 kbps)
        self.assertEqual(net.get_bandwidth_at(-1.0), 1000.0)

        # Exact sample points
        self.assertEqual(net.get_bandwidth_at(0.0), 1000.0)
        self.assertEqual(net.get_bandwidth_at(2.0), 3000.0)
        self.assertEqual(net.get_bandwidth_at(5.0), 5000.0)

        # Between sample points (zero-order hold): t=1.5s is still in [0s, 2s) -> 1000 kbps
        self.assertEqual(net.get_bandwidth_at(1.5), 1000.0)
        # t=3.8s is in [2s, 5s) -> 3000 kbps
        self.assertEqual(net.get_bandwidth_at(3.8), 3000.0)

        # After last sample (t > 5s): clamps to last sample (5000 kbps)
        self.assertEqual(net.get_bandwidth_at(10.0), 5000.0)

        # Unit conversion check: 3000 kbps == 3.0 Mbps
        self.assertAlmostEqual(net.get_bandwidth_mbps(2.0), 3.0)
        self.assertEqual(net.get_bandwidth_kbps(2.0), 3000.0)

    def test_simulation_reproducibility(self):
        """Tests that replaying with reset produces identical results."""
        trace = [(0.0, 2000.0), (2.0, 1000.0), (5.0, 4000.0)]
        net = NetworkSimulator(trace=trace, latency_sec=0.01)

        # Run 1
        d1_time, d1_tp = net.simulate_segment_download(2000.0)
        d2_time, d2_tp = net.simulate_segment_download(3000.0)
        clock_run1 = net.current_time_sec

        # Reset clock and re-run
        net.reset()
        self.assertEqual(net.current_time_sec, 0.0)
        r1_time, r1_tp = net.simulate_segment_download(2000.0)
        r2_time, r2_tp = net.simulate_segment_download(3000.0)
        clock_run2 = net.current_time_sec

        self.assertEqual(d1_time, r1_time)
        self.assertEqual(d1_tp, r1_tp)
        self.assertEqual(d2_time, r2_time)
        self.assertEqual(d2_tp, r2_tp)
        self.assertEqual(clock_run1, clock_run2)

    def test_dynamic_download_and_zero_bandwidth_timeout(self):
        """Tests piecewise segment download across changing rates and zero-bandwidth timeout."""
        # Outage trace: 0 kbps from t=0s
        net_outage = NetworkSimulator(trace=[(0.0, 0.0)], timeout_sec=15.0)
        dt, tp = net_outage.simulate_segment_download(1000.0)
        self.assertEqual(dt, 15.0)
        self.assertEqual(tp, 0.0)
        self.assertEqual(net_outage.current_time_sec, 15.0)


class TestTraceCSV(unittest.TestCase):
    """Verifies CSV trace loading, validation, and synthetic trace files."""

    def test_load_all_synthetic_traces(self):
        """Verifies that all 5 generated synthetic trace files load cleanly and validate."""
        trace_files = [
            "synthetic_stable_high.csv",
            "synthetic_stable_low.csv",
            "synthetic_fluctuating.csv",
            "synthetic_gradual_degradation.csv",
            "synthetic_sudden_drop_recovery.csv",
        ]
        trace_dir = PROJECT_ROOT / "data" / "traces"

        for filename in trace_files:
            file_path = trace_dir / filename
            self.assertTrue(file_path.is_file(), f"Missing synthetic trace file: {filename}")
            samples = load_trace_from_csv(file_path)
            self.assertGreater(len(samples), 50, f"Trace {filename} has too few samples")

            # Verify strictly increasing timestamps and positive bandwidth
            for i in range(1, len(samples)):
                self.assertGreater(samples[i][0], samples[i - 1][0], f"Timestamps not strictly increasing in {filename}")
                self.assertGreater(samples[i][1], 0.0, f"Bandwidth should be positive in {filename}")

    def test_csv_missing_file(self):
        """Verifies FileNotFoundError when CSV does not exist."""
        with self.assertRaises(FileNotFoundError):
            load_trace_from_csv(PROJECT_ROOT / "data" / "traces" / "non_existent_file.csv")

    def test_csv_empty_file(self):
        """Verifies ValueError when CSV is empty."""
        with tempfile.NamedTemporaryFile("w", delete=False, suffix=".csv") as tmp:
            tmp_path = Path(tmp.name)
        try:
            with self.assertRaises(ValueError):
                load_trace_from_csv(tmp_path)
        finally:
            tmp_path.unlink(missing_ok=True)

    def test_csv_missing_columns(self):
        """Verifies ValueError when required columns are absent."""
        content = "wrong_time,wrong_bw\n0.0,5.0\n1.0,4.5\n"
        with tempfile.NamedTemporaryFile("w", delete=False, suffix=".csv") as tmp:
            tmp.write(content)
            tmp_path = Path(tmp.name)
        try:
            with self.assertRaises(ValueError) as ctx:
                load_trace_from_csv(tmp_path)
            self.assertIn("Missing required CSV columns", str(ctx.exception))
        finally:
            tmp_path.unlink(missing_ok=True)

    def test_csv_invalid_non_numeric(self):
        """Verifies ValueError on non-numeric cell."""
        content = "timestamp_sec,bandwidth_mbps\n0.0,5.0\n1.0,corrupted_text\n"
        with tempfile.NamedTemporaryFile("w", delete=False, suffix=".csv") as tmp:
            tmp.write(content)
            tmp_path = Path(tmp.name)
        try:
            with self.assertRaises(ValueError) as ctx:
                load_trace_from_csv(tmp_path)
            self.assertIn("Invalid non-numeric value", str(ctx.exception))
        finally:
            tmp_path.unlink(missing_ok=True)

    def test_csv_negative_bandwidth(self):
        """Verifies ValueError when bandwidth is negative."""
        content = "timestamp_sec,bandwidth_mbps\n0.0,5.0\n1.0,-2.5\n"
        with tempfile.NamedTemporaryFile("w", delete=False, suffix=".csv") as tmp:
            tmp.write(content)
            tmp_path = Path(tmp.name)
        try:
            with self.assertRaises(ValueError) as ctx:
                load_trace_from_csv(tmp_path)
            self.assertIn("Negative bandwidth", str(ctx.exception))
        finally:
            tmp_path.unlink(missing_ok=True)

    def test_csv_non_increasing_timestamps(self):
        """Verifies ValueError when timestamps are equal or decreasing."""
        content = "timestamp_sec,bandwidth_mbps\n0.0,5.0\n2.0,4.0\n2.0,3.5\n"
        with tempfile.NamedTemporaryFile("w", delete=False, suffix=".csv") as tmp:
            tmp.write(content)
            tmp_path = Path(tmp.name)
        try:
            with self.assertRaises(ValueError) as ctx:
                load_trace_from_csv(tmp_path)
            self.assertIn("strictly increasing", str(ctx.exception))
        finally:
            tmp_path.unlink(missing_ok=True)

    def test_csv_negative_timestamps(self):
        """Verifies ValueError when timestamp is negative."""
        content = "timestamp_sec,bandwidth_mbps\n-1.0,5.0\n0.0,4.0\n"
        with tempfile.NamedTemporaryFile("w", delete=False, suffix=".csv") as tmp:
            tmp.write(content)
            tmp_path = Path(tmp.name)
        try:
            with self.assertRaises(ValueError) as ctx:
                load_trace_from_csv(tmp_path)
            self.assertIn("Negative timestamp", str(ctx.exception))
        finally:
            tmp_path.unlink(missing_ok=True)


class TestPlayerBufferModel(unittest.TestCase):
    """Verifies Stage 3 playback buffer dynamics, stalls, and statistics."""

    def test_buffer_increases_after_completed_segment(self):
        """Verifies that buffer increases by segment duration upon completion."""
        player = VideoPlayer(segment_duration_sec=2.0, max_buffer_sec=30.0)
        self.assertEqual(player.buffer_sec, 0.0)

        # Download segment taking 1.0s -> initial buffer should be 2.0s
        player.receive_segment(bitrate_kbps=1000, download_time_sec=1.0)
        self.assertAlmostEqual(player.buffer_sec, 2.0)

        # Download another segment taking 0.2s -> buffer = 2.0 - 0.2 + 2.0 = 3.8s
        player.receive_segment(bitrate_kbps=1000, download_time_sec=0.2)
        self.assertAlmostEqual(player.buffer_sec, 3.8)

    def test_buffer_decreases_during_playback(self):
        """Verifies buffer drain and playback time increment during play_video."""
        player = VideoPlayer(segment_duration_sec=2.0, max_buffer_sec=30.0)
        # Pre-fill buffer with 5.0s
        player.receive_segment(bitrate_kbps=1000, download_time_sec=1.0, segment_duration_sec=5.0)
        self.assertAlmostEqual(player.buffer_sec, 5.0)

        # Play 2.5 seconds
        stall = player.play_video(2.5)
        self.assertEqual(stall, 0.0)
        self.assertAlmostEqual(player.buffer_sec, 2.5)
        self.assertAlmostEqual(player.total_playback_time_sec, 2.5)

    def test_playback_without_stalls_on_fast_network(self):
        """Verifies continuous smooth playback when network bandwidth exceeds video bitrates."""
        net = NetworkSimulator(trace=[(0.0, 10000.0)])  # 10 Mbps stable
        player = VideoPlayer(segment_duration_sec=2.0, max_buffer_sec=30.0)

        # Download 5 segments of 1200 kbps (2400 kb each -> 0.24s download time)
        for _ in range(5):
            res = player.download_segment_from_network(net, bitrate_kbps=1200)
            self.assertTrue(res["download_success"])

        # After startup on segment 1, segments 2..5 should have 0 stall
        summary = player.get_session_summary()
        self.assertEqual(summary["segments_completed"], 5)
        # Only initial startup caused initial delay; all subsequent stalls are 0.0
        post_startup_stalls = summary["stall_times_sec"][1:]
        self.assertTrue(all(s == 0.0 for s in post_startup_stalls))
        self.assertGreater(player.buffer_sec, 5.0)

    def test_startup_delay_recording(self):
        """Verifies startup delay tracking before video begins playing."""
        player = VideoPlayer(segment_duration_sec=2.0, startup_threshold_sec=2.0)
        self.assertFalse(player.is_playing)

        # First segment takes 1.75s to download
        stall = player.receive_segment(bitrate_kbps=1500, download_time_sec=1.75)
        self.assertAlmostEqual(stall, 1.75)
        self.assertAlmostEqual(player.startup_delay_sec, 1.75)
        self.assertTrue(player.is_playing)

    def test_stall_caused_by_sudden_bandwidth_drop(self):
        """Verifies buffer underrun detection when download time exceeds available buffer."""
        player = VideoPlayer(segment_duration_sec=2.0, max_buffer_sec=30.0)
        # Segment 1 (initial startup): 1.0s download -> buffer = 2.0s
        player.receive_segment(bitrate_kbps=1000, download_time_sec=1.0)
        self.assertAlmostEqual(player.buffer_sec, 2.0)

        # Segment 2: Network plunges, download takes 5.0s (buffer had only 2.0s)
        stall = player.receive_segment(bitrate_kbps=1000, download_time_sec=5.0)
        # Stall must equal download_time - buffer = 5.0 - 2.0 = 3.0s
        self.assertAlmostEqual(stall, 3.0)
        # Buffer drained to 0, then received 2.0s from new segment
        self.assertAlmostEqual(player.buffer_sec, 2.0)
        self.assertAlmostEqual(player.total_rebuffer_time_sec, 1.0 + 3.0)
        self.assertEqual(player.rebuffer_events_count, 2)

    def test_recovery_after_stall(self):
        """Verifies playback resumes and is_stalled clears after receiving sufficient content."""
        player = VideoPlayer(segment_duration_sec=2.0, rebuffer_threshold_sec=1.0)
        player.receive_segment(bitrate_kbps=1000, download_time_sec=1.0)  # startup

        # Exhaust buffer completely
        stall = player.play_video(3.0)  # buffer had 2.0, stalls 1.0
        self.assertEqual(stall, 1.0)
        self.assertTrue(player.is_stalled)
        self.assertEqual(player.buffer_sec, 0.0)

        # Next segment arrives (duration 2.0s >= rebuffer_threshold 1.0s)
        player.receive_segment(bitrate_kbps=1000, download_time_sec=0.2)
        self.assertFalse(player.is_stalled)
        self.assertGreaterEqual(player.buffer_sec, 1.0)

    def test_maximum_buffer_capacity(self):
        """Verifies that buffer occupancy never exceeds max_buffer_sec."""
        max_cap = 10.0
        player = VideoPlayer(segment_duration_sec=2.0, max_buffer_sec=max_cap)

        # Rapidly download 10 segments of 2.0s each with negligible download time
        for _ in range(10):
            player.receive_segment(bitrate_kbps=500, download_time_sec=0.01)

        self.assertLessEqual(player.buffer_sec, max_cap)
        self.assertAlmostEqual(player.buffer_sec, max_cap)

    def test_zero_bandwidth_timeout_handling(self):
        """Verifies graceful handling of zero bandwidth without infinite loops or bad state."""
        # Trace with 0 kbps bandwidth
        net_zero = NetworkSimulator(trace=[(0.0, 0.0)], timeout_sec=10.0)
        player = VideoPlayer(segment_duration_sec=2.0)

        # Attempt to download segment over dead network
        res = player.download_segment_from_network(net_zero, bitrate_kbps=1000)
        self.assertFalse(res["download_success"])
        self.assertEqual(res["download_time_sec"], 10.0)
        self.assertEqual(res["effective_throughput_kbps"], 0.0)
        # Buffer remains 0.0s because no segment arrived
        self.assertEqual(player.buffer_sec, 0.0)

    def test_invalid_inputs_and_boundary_conditions(self):
        """Verifies ValueError on negative or nonsensical input parameters."""
        with self.assertRaises(ValueError):
            VideoPlayer(segment_duration_sec=-2.0)
        with self.assertRaises(ValueError):
            VideoPlayer(max_buffer_sec=-10.0)
        with self.assertRaises(ValueError):
            VideoPlayer(startup_threshold_sec=-1.0)

        player = VideoPlayer()
        with self.assertRaises(ValueError):
            player.receive_segment(bitrate_kbps=-500, download_time_sec=1.0)
        with self.assertRaises(ValueError):
            player.receive_segment(bitrate_kbps=500, download_time_sec=-1.0)
        with self.assertRaises(ValueError):
            player.play_video(-2.0)

    def test_session_summary_and_qoe_integration(self):
        """Verifies session summary outputs and direct ingestion by QoECalculator."""
        player = VideoPlayer(segment_duration_sec=2.0)
        # Simulate 3 segments
        player.receive_segment(bitrate_kbps=1200, download_time_sec=1.0)
        player.receive_segment(bitrate_kbps=1850, download_time_sec=0.5)
        player.receive_segment(bitrate_kbps=2850, download_time_sec=0.8)

        summary = player.get_session_summary()
        self.assertEqual(summary["segments_completed"], 3)
        self.assertEqual(summary["bitrates_kbps"], [1200, 1850, 2850])
        self.assertEqual(len(summary["stall_times_sec"]), 3)

        # Test direct feeding to QoECalculator
        bitrates, stalls = player.get_qoe_inputs()
        qoe_calc = QoECalculator(alpha=1.0, beta=4.3, gamma=1.0)
        qoe_res = qoe_calc.calculate_session_qoe(bitrates, stalls)

        self.assertIn("total_qoe", qoe_res)
        self.assertGreater(qoe_res["avg_bitrate_kbps"], 1000.0)


class TestDetailedABRAlgorithms(unittest.TestCase):
    """Verifies complete Stage 4 implementations for all 3 ABR algorithms."""

    def setUp(self):
        self.ladder = [300, 750, 1200, 1850, 2850, 4300]
        self.throughput_abr = ThroughputBasedABR(bitrate_ladder_kbps=self.ladder, safety_factor=0.85)
        self.buffer_abr = BufferBasedABR(
            bitrate_ladder_kbps=self.ladder,
            reservoir_sec=5.0,
            cushion_sec=10.0,
            hysteresis_sec=0.5,
        )
        self.hybrid_abr = HybridQoEABR(
            bitrate_ladder_kbps=self.ladder,
            reservoir_sec=5.0,
            cushion_sec=10.0,
        )

    def test_throughput_based_moving_average_and_safety(self):
        """Verifies harmonic mean estimation and conservative safety margin."""
        abr = ThroughputBasedABR(bitrate_ladder_kbps=self.ladder, safety_factor=0.85, window_size=3)

        # Feed three throughput measurements: 3000, 3000, 3000 kbps -> harmonic mean is 3000
        abr.select_bitrate(0, 10.0, 3000.0, 1.0)
        abr.select_bitrate(1, 10.0, 3000.0, 1.0)
        abr.select_bitrate(2, 10.0, 3000.0, 1.0)

        self.assertAlmostEqual(abr.current_estimate_kbps, 3000.0)
        # Safe budget = 3000 * 0.85 = 2550 kbps. Highest rate <= 2550 is 1850 kbps
        rate = abr.select_bitrate(3, 10.0, 3000.0, 1.0)
        self.assertEqual(rate, 1850)

    def test_throughput_based_missing_samples_and_reset(self):
        """Verifies safe fallback on initial/missing samples and clean reset behavior."""
        abr = ThroughputBasedABR(bitrate_ladder_kbps=self.ladder, initial_bitrate_kbps=300)
        # Initial call with 0 throughput returns default initial rate
        self.assertEqual(abr.select_bitrate(0, 0.0, 0.0, 0.0), 300)

        # Feed 10000 kbps
        abr.select_bitrate(1, 5.0, 10000.0, 0.5)
        self.assertGreater(abr.current_estimate_kbps, 5000.0)

        # Resetting clears history and estimate
        abr.reset()
        self.assertEqual(abr.current_estimate_kbps, 0.0)
        self.assertEqual(len(abr.throughput_history), 0)
        self.assertEqual(abr.select_bitrate(0, 0.0, 0.0, 0.0), 300)

    def test_throughput_based_sudden_drop_and_recovery(self):
        """Verifies rapid down-switching upon bandwidth collapse and recovery."""
        abr = ThroughputBasedABR(bitrate_ladder_kbps=self.ladder, window_size=2)
        abr.select_bitrate(0, 10.0, 5000.0, 1.0)
        abr.select_bitrate(1, 10.0, 5000.0, 1.0)

        # Network suddenly plunges to 400 kbps
        rate_dropped = abr.select_bitrate(2, 5.0, 400.0, 3.0)
        self.assertLessEqual(rate_dropped, 750)

        # Another low sample seals the low estimate
        rate_low = abr.select_bitrate(3, 3.0, 400.0, 3.0)
        self.assertEqual(rate_low, 300)

    def test_buffer_based_cushion_interpolation_and_extremes(self):
        """Verifies BBA reservoir clamp, cushion progression, and upper threshold."""
        abr = BufferBasedABR(bitrate_ladder_kbps=self.ladder, reservoir_sec=5.0, cushion_sec=10.0)

        # In reservoir (<= 5s): lowest bitrate
        self.assertEqual(abr.select_bitrate(0, 2.0, 5000.0, 1.0), 300)
        self.assertEqual(abr.select_bitrate(1, 5.0, 5000.0, 1.0), 300)

        # In cushion (5s to 15s): scales up
        rate_mid = abr.select_bitrate(2, 10.0, 5000.0, 1.0)
        self.assertIn(rate_mid, [1200, 1850])

        # Above upper threshold (>= 15s): highest bitrate
        self.assertEqual(abr.select_bitrate(3, 15.0, 5000.0, 1.0), 4300)
        self.assertEqual(abr.select_bitrate(4, 25.0, 5000.0, 1.0), 4300)

    def test_buffer_based_anti_oscillation_hysteresis(self):
        """Verifies that hysteresis prevents quality flickering near threshold boundaries."""
        abr = BufferBasedABR(
            bitrate_ladder_kbps=self.ladder,
            reservoir_sec=5.0,
            cushion_sec=10.0,
            hysteresis_sec=0.8,
        )

        # Buffer at 9.0s -> selects intermediate tier (e.g. 1200)
        rate1 = abr.select_bitrate(0, 9.0, 3000.0, 1.0)

        # Buffer fluctuates slightly upward to 9.2s with previous bitrate set to rate1
        # Hysteresis requires exceeding step boundary + 0.8s, so it should stay at rate1
        rate2 = abr.select_bitrate(1, 9.2, 3000.0, 1.0, last_bitrate_kbps=rate1)
        self.assertEqual(rate1, rate2)

    def test_hybrid_volatility_damping(self):
        """Verifies that high throughput volatility decreases the effective safety factor."""
        abr_stable = HybridQoEABR(bitrate_ladder_kbps=self.ladder)
        # Feed stable samples around 3000 kbps
        for _ in range(4):
            abr_stable.select_bitrate(0, 16.0, 3000.0, 1.0)
        cv_stable = abr_stable.compute_volatility()
        self.assertLess(cv_stable, 0.05)

        abr_volatile = HybridQoEABR(bitrate_ladder_kbps=self.ladder)
        # Feed alternating samples 1000 and 5000 kbps
        abr_volatile.select_bitrate(0, 16.0, 1000.0, 1.0)
        abr_volatile.select_bitrate(1, 16.0, 5000.0, 1.0)
        abr_volatile.select_bitrate(2, 16.0, 1000.0, 1.0)
        abr_volatile.select_bitrate(3, 16.0, 5000.0, 1.0)
        cv_volatile = abr_volatile.compute_volatility()

        self.assertGreater(cv_volatile, 0.4)
        self.assertGreater(cv_volatile, cv_stable)

    def test_hybrid_reservoir_protection_and_buffer_scaling(self):
        """Verifies that Hybrid drops to lowest bitrate in reservoir regardless of throughput."""
        abr = HybridQoEABR(bitrate_ladder_kbps=self.ladder, reservoir_sec=5.0, cushion_sec=10.0)

        # High throughput (10000 kbps), but buffer is dangerously low (3.0s <= 5.0s)
        rate = abr.select_bitrate(0, 3.0, 10000.0, 1.0)
        self.assertEqual(rate, 300)

        # Buffer improves into cushion (12.0s) -> can safely select higher quality
        rate_safe = abr.select_bitrate(1, 12.0, 10000.0, 0.2)
        self.assertGreater(rate_safe, 300)

    def test_hybrid_cautious_step_up_constraint(self):
        """Verifies that Hybrid only steps up by at most one tier at a time."""
        abr = HybridQoEABR(bitrate_ladder_kbps=self.ladder, reservoir_sec=5.0, cushion_sec=10.0)
        # Previous bitrate was lowest (300 kbps, index 0)
        # Huge throughput jump (15000 kbps) and healthy buffer (20s)
        selected = abr.select_bitrate(
            segment_index=1,
            current_buffer_sec=20.0,
            last_throughput_kbps=15000.0,
            last_download_time_sec=0.1,
            last_bitrate_kbps=300,
        )
        # Must step up by at most 1 tier (to 750 kbps, index 1)
        self.assertEqual(selected, 750)

    def test_hybrid_fast_step_down_on_sudden_drop(self):
        """Verifies that Hybrid can drop multiple tiers immediately when bandwidth collapses."""
        abr = HybridQoEABR(bitrate_ladder_kbps=self.ladder, reservoir_sec=5.0)
        # Previous bitrate was top tier (4300 kbps), but bandwidth collapses to 350 kbps
        selected = abr.select_bitrate(
            segment_index=5,
            current_buffer_sec=7.0,
            last_throughput_kbps=350.0,
            last_download_time_sec=3.0,
            last_bitrate_kbps=4300,
        )
        # Multi-tier drop to 300 kbps to save buffer
        self.assertEqual(selected, 300)

    def test_all_algorithms_valid_ladder_selection(self):
        """Verifies that all three algorithms strictly select valid configured bitrates."""
        algorithms = [self.throughput_abr, self.buffer_abr, self.hybrid_abr]
        test_buffers = [0.0, 1.0, 5.0, 7.5, 12.0, 15.0, 30.0]
        test_throughputs = [0.0, 200.0, 1200.0, 4000.0, 12000.0]

        for alg in algorithms:
            alg.reset()
            for seg_idx, (b, tp) in enumerate(zip(test_buffers, test_throughputs)):
                bitrate = alg.select_bitrate(
                    segment_index=seg_idx,
                    current_buffer_sec=b,
                    last_throughput_kbps=tp,
                    last_download_time_sec=1.0,
                )
                self.assertIn(
                    bitrate,
                    self.ladder,
                    f"Algorithm {alg.name} returned invalid bitrate: {bitrate}"
                )


class TestMetrics(unittest.TestCase):
    """Verifies QoE calculations."""

    def test_qoe_calculation(self):
        """[Smoke Test 7] Preserved QoE session metrics test."""
        qoe_calc = QoECalculator(alpha=1.0, beta=4.3, gamma=1.0)
        # 3 segments at 1000 kbps (1.0 Mbps), 0 stall, no switches
        res = qoe_calc.calculate_session_qoe(
            bitrates_kbps=[1000, 1000, 1000],
            stall_times_sec=[0.0, 0.0, 0.0]
        )
        # Total quality = 1.0 + 1.0 + 1.0 = 3.0, 0 penalties -> QoE = 3.0
        self.assertAlmostEqual(res["total_qoe"], 3.0)
        self.assertEqual(res["total_stall_sec"], 0.0)
        self.assertEqual(res["bitrate_switches_count"], 0)


if __name__ == "__main__":
    unittest.main()
