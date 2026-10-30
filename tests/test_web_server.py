"""Unit tests for Stage 8: Flask HTTP Streaming Server & MPEG-DASH Web Player.

Verifies:
1. Health check endpoint reporting manifest and segment availability.
2. Correct MIME types for DASH manifest (application/dash+xml) and segments (video/mp4).
3. Graceful 404 handling with informative hints when manifest or segments are missing.
4. Protection against directory traversal attacks (preventing access outside dash directory).
5. CORS header injection for cross-origin web player access.
6. Player dashboard route (/player and /) delivering expected video hooks and layout.
7. Stage 8C live visualization canvases, session stats, and export DOM elements.
8. Static delivery and content validation for player.css and player.js.
"""

import os
import shutil
import tempfile
import unittest
from pathlib import Path

from src.web.server import create_app, get_mimetype_for_file


class TestWebServer(unittest.TestCase):
    """Test suite for the Flask DASH streaming server."""

    def setUp(self):
        """Create an isolated temporary DASH directory with mock streaming artifacts."""
        self.test_dir = tempfile.mkdtemp(prefix="dash_server_test_")
        self.dash_dir = Path(self.test_dir) / "dash"
        self.dash_dir.mkdir(parents=True, exist_ok=True)

        # Create mock stream.mpd
        self.mock_mpd_content = b'<?xml version="1.0"?><MPD>Mock Manifest</MPD>'
        (self.dash_dir / "stream.mpd").write_bytes(self.mock_mpd_content)

        # Create mock init segment and media chunk
        self.mock_init_content = b"INIT_SEGMENT_MOCK_BYTES"
        self.mock_chunk_content = b"CHUNK_SEGMENT_MOCK_BYTES"
        (self.dash_dir / "init-stream0.m4s").write_bytes(self.mock_init_content)
        (self.dash_dir / "chunk-stream0-00001.m4s").write_bytes(self.mock_chunk_content)

        # Create app configured to test directory
        self.exp_file = Path(self.test_dir) / "experiments.json"
        self.app = create_app(dash_dir=self.dash_dir, experiments_file=self.exp_file)
        self.client = self.app.test_client()

    def tearDown(self):
        """Clean up temporary test directory."""
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_health_endpoint_healthy_state(self):
        """Verifies /health returns 200, status 'healthy', and accurate segment counts."""
        res = self.client.get("/health")
        self.assertEqual(res.status_code, 200)

        data = res.get_json()
        self.assertEqual(data["status"], "healthy")
        self.assertTrue(data["manifest_exists"])
        self.assertEqual(data["manifest_name"], "stream.mpd")
        self.assertEqual(data["init_segments_count"], 1)
        self.assertEqual(data["media_segments_count"], 1)
        self.assertIn("ready for playback", data["message"])

    def test_health_endpoint_degraded_when_manifest_missing(self):
        """Verifies /health reports 'degraded' when stream.mpd does not exist."""
        # Remove stream.mpd
        (self.dash_dir / "stream.mpd").unlink()

        res = self.client.get("/health")
        self.assertEqual(res.status_code, 200)

        data = res.get_json()
        self.assertEqual(data["status"], "degraded")
        self.assertFalse(data["manifest_exists"])
        self.assertIn("DASH manifest not found", data["message"])

    def test_manifest_serving_and_mime_type(self):
        """Verifies manifest is served with 'application/dash+xml' MIME type."""
        with self.client.get("/dash/stream.mpd") as res:
            self.assertEqual(res.status_code, 200)
            self.assertTrue(res.content_type.startswith("application/dash+xml"))
            self.assertEqual(res.data, self.mock_mpd_content)

        # Test static path alias route as well
        with self.client.get("/static/dash/stream.mpd") as res_alias:
            self.assertEqual(res_alias.status_code, 200)
            self.assertTrue(res_alias.content_type.startswith("application/dash+xml"))

    def test_segment_serving_and_mime_type(self):
        """Verifies .m4s segments are served with 'video/mp4' MIME type."""
        # Init segment
        with self.client.get("/dash/init-stream0.m4s") as res_init:
            self.assertEqual(res_init.status_code, 200)
            self.assertTrue(res_init.content_type.startswith("video/mp4"))
            self.assertEqual(res_init.data, self.mock_init_content)

        # Media chunk
        with self.client.get("/dash/chunk-stream0-00001.m4s") as res_chunk:
            self.assertEqual(res_chunk.status_code, 200)
            self.assertTrue(res_chunk.content_type.startswith("video/mp4"))
            self.assertEqual(res_chunk.data, self.mock_chunk_content)

    def test_missing_manifest_returns_404_with_hint(self):
        """Verifies requesting a non-existent manifest returns 404 with helpful encoding instructions."""
        (self.dash_dir / "stream.mpd").unlink()

        res = self.client.get("/dash/stream.mpd")
        self.assertEqual(res.status_code, 404)

        data = res.get_json()
        self.assertIn("not found on server", data["error"])
        self.assertIn("encode_dash", data["hint"])

    def test_missing_segment_returns_404(self):
        """Verifies requesting an unknown chunk returns 404."""
        res = self.client.get("/dash/chunk-stream99-99999.m4s")
        self.assertEqual(res.status_code, 404)
        data = res.get_json()
        self.assertIn("not found", data["error"])

    def test_directory_traversal_protection(self):
        """Verifies attempts to navigate above the DASH directory are rejected (403 Forbidden)."""
        # Create a secret file in parent test directory
        secret_file = Path(self.test_dir) / "secret.txt"
        secret_file.write_text("SENSITIVE_DATA", encoding="utf-8")

        # Attempt to read secret file via path traversal
        res1 = self.client.get("/dash/../secret.txt")
        self.assertEqual(res1.status_code, 403)
        self.assertNotIn(b"SENSITIVE_DATA", res1.data)

        res2 = self.client.get("/dash/../../README.md")
        self.assertEqual(res2.status_code, 403)

    def test_cors_headers_present(self):
        """Verifies Access-Control headers are attached to responses."""
        res = self.client.get("/health")
        self.assertEqual(res.headers.get("Access-Control-Allow-Origin"), "*")
        self.assertIn("Range", res.headers.get("Access-Control-Allow-Headers", ""))

    def test_mimetype_helper(self):
        """Directly tests get_mimetype_for_file logic."""
        self.assertEqual(get_mimetype_for_file("stream.mpd"), "application/dash+xml")
        self.assertEqual(get_mimetype_for_file("STREAM.MPD"), "application/dash+xml")
        self.assertEqual(get_mimetype_for_file("chunk-stream0-00001.m4s"), "video/mp4")
        self.assertEqual(get_mimetype_for_file("init-stream0.m4s"), "video/mp4")
        self.assertEqual(get_mimetype_for_file("video.mp4"), "video/mp4")

    def test_player_route_status_and_elements(self):
        """Verifies /player returns 200 and renders the HTML dashboard with expected DOM hooks."""
        res = self.client.get("/player")
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.content_type.startswith("text/html"))

        html = res.get_data(as_text=True)
        # Core player elements
        self.assertIn('id="videoPlayer"', html)
        self.assertIn('data-manifest="/dash/stream.mpd"', html)
        self.assertIn('id="qualitySelect"', html)
        self.assertIn('id="playbackTime"', html)
        self.assertIn('id="currentResolution"', html)
        self.assertIn('id="currentBitrate"', html)
        self.assertIn('id="bufferLevel"', html)
        self.assertIn('id="bufferBar"', html)
        self.assertIn('id="stateBadge"', html)
        self.assertIn('id="switchLogBody"', html)

    def test_stage8c_visualizations_and_session_stats_elements(self):
        """Verifies /player renders Stage 8C live canvas charts, stats grid, and export buttons."""
        res = self.client.get("/player")
        self.assertEqual(res.status_code, 200)
        html = res.get_data(as_text=True)

        # Stage 8C Live Visualizations
        self.assertIn('id="bitrateChartCanvas"', html)
        self.assertIn('id="bufferChartCanvas"', html)
        self.assertIn('id="tabBitrate"', html)
        self.assertIn('id="tabBuffer"', html)

        # Stage 8C Session Statistics & QoE Grid
        self.assertIn('id="statStartupDelay"', html)
        self.assertIn('id="statPlaybackTime"', html)
        self.assertIn('id="statStallCount"', html)
        self.assertIn('id="statRebufferTime"', html)
        self.assertIn('id="statRebufferRatio"', html)
        self.assertIn('id="statAvgBitrate"', html)
        self.assertIn('id="statSwitchCount"', html)
        self.assertIn('id="statSwitchMagnitude"', html)
        self.assertIn('id="statSessionQoE"', html)

        # Stage 8C Export Actions
        self.assertIn('id="exportCsvBtn"', html)
        self.assertIn('id="exportJsonBtn"', html)

    def test_root_index_renders_player(self):
        """Verifies / (root endpoint) serves the video streaming dashboard."""
        res = self.client.get("/")
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.content_type.startswith("text/html"))
        html = res.get_data(as_text=True)
        self.assertIn('id="videoPlayer"', html)
        self.assertIn('id="bitrateChartCanvas"', html)

    def test_player_references_dashjs_and_assets(self):
        """Verifies player template includes dash.js CDN, local fallback, and custom scripts."""
        res = self.client.get("/player")
        html = res.get_data(as_text=True)
        self.assertIn("dash.all.min.js", html)
        self.assertIn("player.js", html)
        self.assertIn("player.css", html)

    def test_static_assets_served(self):
        """Verifies player.css and player.js static assets are delivered with valid MIME types."""
        with self.client.get("/static/css/player.css") as res_css:
            self.assertEqual(res_css.status_code, 200)
            self.assertTrue(res_css.content_type.startswith("text/css"))

        with self.client.get("/static/js/player.js") as res_js:
            self.assertEqual(res_js.status_code, 200)
            self.assertTrue(res_js.content_type.startswith("text/javascript"))

        with self.client.get("/static/js/hybrid-abr.js") as res_hybrid:
            self.assertEqual(res_hybrid.status_code, 200)
            self.assertTrue(res_hybrid.content_type.startswith("text/javascript"))

    def test_static_assets_contain_stage8c_logic(self):
        """Verifies static JS and CSS contain Stage 8C chart, metrics, and export logic."""
        with self.client.get("/static/js/player.js") as res_js:
            js_text = res_js.get_data(as_text=True)
            self.assertIn("renderBitrateChart", js_text)
            self.assertIn("renderBufferChart", js_text)
            self.assertIn("exportSessionCsv", js_text)
            self.assertIn("exportSessionJson", js_text)
            self.assertIn("QUALITY_CHANGE_REQUESTED", js_text)
            self.assertIn("QUALITY_CHANGE_RENDERED", js_text)

        with self.client.get("/static/css/player.css") as res_css:
            css_text = res_css.get_data(as_text=True)
            self.assertIn(".charts-card", css_text)
            self.assertIn(".session-stats-grid", css_text)
            self.assertIn(".type-requested", css_text)
            self.assertIn(".type-rendered", css_text)

    def test_api_experiments_crud(self):
        """Verifies GET, POST, and DELETE endpoints for persistent experiment tracking."""
        # 1. Initially empty
        res = self.client.get("/api/experiments")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json(), [])

        # 2. Add an experiment
        exp_payload = {
            "algorithm": "hybrid",
            "algorithmName": "QoE-Driven Hybrid ABR",
            "networkScenario": "5 Mbps",
            "durationSec": 30.0,
            "avgBitrateKbps": 2800.0,
            "avgThroughputKbps": 4900.0,
            "avgBufferSec": 11.5,
            "switchCount": 2,
            "stallCount": 0,
            "totalRebufferSec": 0.0,
            "rebufferRatio": 0.0,
            "avgDownloadTimeSec": 0.32,
            "qoeScore": 42.1
        }
        res_post = self.client.post("/api/experiments", json=exp_payload)
        self.assertEqual(res_post.status_code, 201)
        post_data = res_post.get_json()
        self.assertEqual(post_data["status"], "success")
        self.assertEqual(post_data["experiment"]["algorithm"], "hybrid")
        self.assertEqual(post_data["experiment"]["avgBitrateKbps"], 2800.0)

        # 3. GET should return the record
        res_get = self.client.get("/api/experiments")
        self.assertEqual(res_get.status_code, 200)
        records = res_get.get_json()
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["algorithm"], "hybrid")

        # 4. DELETE should clear records
        res_del = self.client.delete("/api/experiments")
        self.assertEqual(res_del.status_code, 200)
        self.assertEqual(res_del.get_json()["status"], "cleared")

        # 5. GET after DELETE should be empty
        res_get2 = self.client.get("/api/experiments")
        self.assertEqual(res_get2.status_code, 200)
        self.assertEqual(res_get2.get_json(), [])

    def test_api_experiments_invalid_post(self):
        """Verifies /api/experiments rejects non-JSON or invalid bodies with 400."""
        res = self.client.post("/api/experiments", data="not json", content_type="text/plain")
        self.assertEqual(res.status_code, 400)


if __name__ == "__main__":
    unittest.main()
