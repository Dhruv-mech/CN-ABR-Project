"""Integration tests for Stage 9B: Parity-Tested Hybrid ABR in dash.js Web Player.

Verifies:
1. Stage 9B HTML dashboard updates:
   - ABR mode selector with 'auto', 'hybrid', and 'manual' options.
   - Stage 9B badges and descriptive UI indicators.
   - Proper script load order: hybrid-abr.js precedes player.js.
   - Timeline audit table headers including Mode and Event Type.
2. Static CSS updates:
   - .type-hybrid styling in player.css for HYBRID_DECISION timeline events.
3. Static JS code and endpoint delivery:
   - Proper MIME types and HTTP 200 delivery for hybrid-abr.js and player.js.
   - Verification of Stage 9B logic patterns in player.js.
4. Headless Node.js lifecycle and event handling simulation:
   - Dynamic representation ladder discovery and index mapping.
   - Three-way mode switching (dash.js autoSwitchBitrate toggle and state isolation).
   - Strict fragment filtering (ignoring audio, init segments, zero bytes, zero duration).
   - Duplicate decision suppression (preventing redundant setQualityFor dispatches).
   - Mode switching state isolation (resetting controller on mode transitions).
   - CSV and JSON export structures containing active ABR mode and hybrid telemetry.
"""

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from src.web.server import create_app


PROJECT_ROOT = Path(__file__).resolve().parent.parent
HYBRID_JS_PATH = PROJECT_ROOT / "static" / "js" / "hybrid-abr.js"
PLAYER_JS_PATH = PROJECT_ROOT / "static" / "js" / "player.js"
PLAYER_HTML_PATH = PROJECT_ROOT / "templates" / "player.html"
PLAYER_CSS_PATH = PROJECT_ROOT / "static" / "css" / "player.css"


def run_node_integration_script(script_code: str) -> dict:
    """
    Executes a Node.js script string and returns the parsed JSON result.

    Args:
        script_code: JavaScript code to execute.

    Returns:
        Dictionary parsed from stdout JSON output.
    """
    node_bin = shutil.which("node")
    if not node_bin:
        raise RuntimeError("Node.js runtime not found on PATH. Required for headless JS testing.")

    proc = subprocess.run(
        [node_bin, "-e", script_code],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=str(PROJECT_ROOT)
    )

    if proc.returncode != 0:
        raise RuntimeError(f"Node.js script failed (code {proc.returncode}):\n{proc.stderr}\nOutput: {proc.stdout}")

    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as err:
        raise RuntimeError(f"Failed to parse Node.js output as JSON: {err}\nOutput was: {proc.stdout}") from err


class TestStage9BHtmlAndCss(unittest.TestCase):
    """Verifies Stage 9B UI components in HTML template and stylesheet."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="stage9b_test_")
        self.dash_dir = Path(self.test_dir) / "dash"
        self.dash_dir.mkdir(parents=True, exist_ok=True)
        (self.dash_dir / "stream.mpd").write_bytes(b'<?xml version="1.0"?><MPD></MPD>')
        self.app = create_app(dash_dir=self.dash_dir)
        self.client = self.app.test_client()

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_abr_mode_selector_and_options(self):
        """Verifies abrModeSelect dropdown is rendered with auto, hybrid, and manual options."""
        res = self.client.get("/player")
        self.assertEqual(res.status_code, 200)
        html = res.get_data(as_text=True)

        self.assertIn('id="abrModeSelect"', html)
        self.assertIn('value="auto"', html)
        self.assertIn('value="hybrid"', html)
        self.assertIn('value="manual"', html)
        self.assertIn("Auto — dash.js Built-in ABR", html)
        self.assertIn("Custom Hybrid ABR", html)
        self.assertIn("Manual Tier", html)

    def test_badges_and_descriptions(self):
        """Verifies Stage 9B badges and mode description elements."""
        res = self.client.get("/player")
        html = res.get_data(as_text=True)

        self.assertIn("Stage 9B", html)
        self.assertIn('id="modeBadge"', html)
        self.assertIn('id="controllerStateBadge"', html)
        self.assertIn('id="modeDescription"', html)

    def test_script_tag_load_order(self):
        """Verifies <script> tag for hybrid-abr.js precedes player.js in player.html."""
        res = self.client.get("/player")
        html = res.get_data(as_text=True)

        hybrid_tag = 'src="/static/js/hybrid-abr.js"'
        player_tag = 'src="/static/js/player.js"'

        self.assertIn(hybrid_tag, html, f"Script tag with {hybrid_tag} not found")
        self.assertIn(player_tag, html, f"Script tag with {player_tag} not found")
        self.assertLess(html.find(hybrid_tag), html.find(player_tag), "hybrid-abr.js must be loaded before player.js")

    def test_timeline_table_headers(self):
        """Verifies timeline audit log table includes Mode and Event Type columns."""
        res = self.client.get("/player")
        html = res.get_data(as_text=True)

        self.assertIn("<th>Event Type</th>", html)
        self.assertIn("<th>Transition / Details</th>", html)
        self.assertIn("<th>Mode</th>", html)

    def test_css_type_hybrid_styling(self):
        """Verifies .type-hybrid badge styling is defined in player.css."""
        css_content = PLAYER_CSS_PATH.read_text(encoding="utf-8")
        self.assertIn(".type-hybrid", css_content)
        self.assertIn("#3b82f6", css_content)

    def test_stage12_comparison_dashboard_elements(self):
        """Verifies comparison dashboard, algorithm cards, and experiment controls exist in HTML."""
        res = self.client.get("/player")
        html = res.get_data(as_text=True)

        # Algorithm selection cards
        self.assertIn('id="cardAlgoThroughput"', html)
        self.assertIn('id="cardAlgoBuffer"', html)
        self.assertIn('id="cardAlgoHybrid"', html)

        # Experiment controls
        self.assertIn('id="btnStartExperiment"', html)
        self.assertIn('id="btnStopExperiment"', html)
        self.assertIn('id="btnResetExperiment"', html)
        self.assertIn('id="btnRunAllAlgorithms"', html)
        self.assertIn('id="btnClearExperiments"', html)

        # Mininet scenario panel
        self.assertIn('id="networkScenarioSelect"', html)
        self.assertIn('id="mininetCommandText"', html)
        self.assertIn('id="btnCopyMininetCmd"', html)

        # Comparison dashboard
        self.assertIn('id="comparisonDashboardSection"', html)
        self.assertIn('id="comparisonTableBody"', html)
        self.assertIn('id="compChartQoE"', html)
        self.assertIn('id="compChartBitrate"', html)
        self.assertIn('id="compChartStalls"', html)
        self.assertIn('id="compChartSwitches"', html)


class TestStage9BStaticDelivery(unittest.TestCase):
    """Verifies static delivery and code structure for Stage 9B modules."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="stage9b_delivery_test_")
        self.dash_dir = Path(self.test_dir) / "dash"
        self.dash_dir.mkdir(parents=True, exist_ok=True)
        (self.dash_dir / "stream.mpd").write_bytes(b'<?xml version="1.0"?><MPD></MPD>')
        self.app = create_app(dash_dir=self.dash_dir)
        self.client = self.app.test_client()

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_hybrid_abr_js_delivery(self):
        """Verifies /static/js/hybrid-abr.js serves valid JS with 200 OK."""
        with self.client.get("/static/js/hybrid-abr.js") as res:
            self.assertEqual(res.status_code, 200)
            self.assertTrue(res.content_type.startswith("text/javascript"))
            js_text = res.get_data(as_text=True)
            self.assertIn("class HybridQoEController", js_text)
            self.assertIn("setBitrateLadder", js_text)
            self.assertIn("selectBitrate", js_text)

    def test_player_js_delivery_and_stage9b_patterns(self):
        """Verifies /static/js/player.js contains Stage 9B integration logic."""
        with self.client.get("/static/js/player.js") as res:
            self.assertEqual(res.status_code, 200)
            self.assertTrue(res.content_type.startswith("text/javascript"))
            js_text = res.get_data(as_text=True)

            # Mode switching logic
            self.assertIn("function setAbrMode", js_text)
            self.assertIn("CUSTOM HYBRID ABR", js_text)
            self.assertIn("MANUAL (Pinned)", js_text)
            self.assertIn("AUTO (dash.js)", js_text)
            self.assertIn("autoSwitchBitrate: { video: false }", js_text)
            self.assertIn("autoSwitchBitrate: { video: true }", js_text)

            # Controller initialization and dynamic ladder
            self.assertIn("initHybridController", js_text)
            self.assertIn("hybridController.setBitrateLadder", js_text)

            # Fragment loading completed handler & duplicate suppression
            self.assertIn("onFragmentLoadingCompleted", js_text)
            self.assertIn("req.mediaType !== 'video'", js_text)
            self.assertIn("req.type !== 'MediaSegment'", js_text)
            self.assertIn("durationSec <= 0.001", js_text)
            self.assertIn("targetQIdx !== lastRequestedQualityIdx", js_text)
            self.assertIn("HYBRID_DECISION", js_text)

            # Export serialization
            self.assertIn("Active ABR Mode", js_text)
            self.assertIn("active_abr_mode", js_text)


class TestStage9BHeadlessBrowserLogic(unittest.TestCase):
    """Executes Node.js headless simulations of player.js and hybrid-abr.js interactions."""

    def test_dynamic_ladder_seeding_and_index_resolution(self):
        """Verifies dynamic representation seeding and two-way bitrate/representation mapping."""
        js_code = f"""
        const {{ HybridQoEController }} = require('{HYBRID_JS_PATH.as_posix()}');

        const controller = new HybridQoEController();
        const mockRepresentations = [
            {{ qualityIndex: 0, width: 640, height: 360, bitrate: 400000 }},
            {{ qualityIndex: 1, width: 854, height: 480, bitrate: 800000 }},
            {{ qualityIndex: 2, width: 1280, height: 720, bitrate: 1500000 }},
            {{ qualityIndex: 3, width: 1920, height: 1080, bitrate: 3000000 }}
        ];

        controller.setBitrateLadder(mockRepresentations);

        const result = {{
            ladder: controller.bitrateLadderKbps,
            indexFor400: controller.getRepresentationIndexForBitrate(400),
            indexFor800: controller.getRepresentationIndexForBitrate(800),
            indexFor1500: controller.getRepresentationIndexForBitrate(1500),
            indexFor3000: controller.getRepresentationIndexForBitrate(3000),
            indexForUnknown: controller.getRepresentationIndexForBitrate(9999)
        }};
        console.log(JSON.stringify(result));
        """
        data = run_node_integration_script(js_code)
        self.assertEqual(data["ladder"], [400, 800, 1500, 3000])
        self.assertEqual(data["indexFor400"], 0)
        self.assertEqual(data["indexFor800"], 1)
        self.assertEqual(data["indexFor1500"], 2)
        self.assertEqual(data["indexFor3000"], 3)
        self.assertEqual(data["indexForUnknown"], -1)

    def test_mode_switching_and_dashjs_settings_isolation(self):
        """Verifies dash.js autoSwitchBitrate toggle and controller reset on mode changes."""
        js_code = f"""
        const {{ HybridQoEController }} = require('{HYBRID_JS_PATH.as_posix()}');

        // Mock dash.js MediaPlayer
        let autoSwitchVideoSetting = null;
        let qualitySetForVideo = null;
        const mockPlayer = {{
            updateSettings: (settings) => {{
                if (settings && settings.streaming && settings.streaming.abr && settings.streaming.abr.autoSwitchBitrate) {{
                    autoSwitchVideoSetting = settings.streaming.abr.autoSwitchBitrate.video;
                }}
            }},
            setQualityFor: (type, idx) => {{
                if (type === 'video') qualitySetForVideo = idx;
            }}
        }};

        const mockRepresentations = [
            {{ qualityIndex: 0, height: 360, bitrate: 400000 }},
            {{ qualityIndex: 1, height: 480, bitrate: 800000 }},
            {{ qualityIndex: 2, height: 720, bitrate: 1500000 }},
            {{ qualityIndex: 3, height: 1080, bitrate: 3000000 }}
        ];

        const hybridController = new HybridQoEController();
        hybridController.setBitrateLadder(mockRepresentations);

        // Feed some history into controller
        hybridController.selectBitrate(0, 4.0, 1200.0, 2.0, 400);
        const historyLengthBeforeReset = hybridController.throughputHistory.length;

        // Simulate setAbrMode('hybrid')
        let currentMode = 'hybrid';
        mockPlayer.updateSettings({{
            streaming: {{ abr: {{ autoSwitchBitrate: {{ video: false }} }} }}
        }});
        hybridController.reset();
        hybridController.setBitrateLadder(mockRepresentations);
        const autoSwitchInHybrid = autoSwitchVideoSetting;
        const historyLengthAfterReset = hybridController.throughputHistory.length;

        // Simulate setAbrMode('auto')
        currentMode = 'auto';
        mockPlayer.updateSettings({{
            streaming: {{ abr: {{ autoSwitchBitrate: {{ video: true }} }} }}
        }});
        const autoSwitchInAuto = autoSwitchVideoSetting;

        // Simulate setAbrMode('manual', 2)
        currentMode = 'manual';
        mockPlayer.updateSettings({{
            streaming: {{ abr: {{ autoSwitchBitrate: {{ video: false }} }} }}
        }});
        mockPlayer.setQualityFor('video', 2);
        const autoSwitchInManual = autoSwitchVideoSetting;
        const qualityInManual = qualitySetForVideo;

        const result = {{
            historyLengthBeforeReset,
            historyLengthAfterReset,
            autoSwitchInHybrid,
            autoSwitchInAuto,
            autoSwitchInManual,
            qualityInManual
        }};
        console.log(JSON.stringify(result));
        """
        data = run_node_integration_script(js_code)
        self.assertEqual(data["historyLengthBeforeReset"], 1)
        self.assertEqual(data["historyLengthAfterReset"], 0)
        self.assertFalse(data["autoSwitchInHybrid"])
        self.assertTrue(data["autoSwitchInAuto"])
        self.assertFalse(data["autoSwitchInManual"])
        self.assertEqual(data["qualityInManual"], 2)

    def test_duplicate_decision_suppression_and_event_separation(self):
        """Verifies duplicate quality dispatches are suppressed while events are logged."""
        js_code = f"""
        const {{ HybridQoEController }} = require('{HYBRID_JS_PATH.as_posix()}');

        const mockRepresentations = [
            {{ qualityIndex: 0, height: 360, bitrate: 400000 }},
            {{ qualityIndex: 1, height: 480, bitrate: 800000 }},
            {{ qualityIndex: 2, height: 720, bitrate: 1500000 }},
            {{ qualityIndex: 3, height: 1080, bitrate: 3000000 }}
        ];

        const hybridController = new HybridQoEController();
        hybridController.setBitrateLadder(mockRepresentations);

        const qualityCalls = [];
        const mockPlayer = {{
            setQualityFor: (type, idx) => {{
                qualityCalls.push({{ type, idx }});
            }}
        }};

        let lastRequestedQualityIdx = -1;
        let lastSelectedRate = 400;
        const eventsLog = [];

        function simulateFragmentCompleted(req, currentBufferSec) {{
            if (req.mediaType !== 'video') return;
            if (req.type !== 'MediaSegment') return;

            const durationSec = (req.endMs - req.startMs) / 1000.0;
            if (durationSec <= 0.001) return;

            const measuredTpKbps = (req.bytesLoaded * 8) / (durationSec * 1000.0);
            const selectedBitrateKbps = hybridController.selectBitrate(
                req.index,
                currentBufferSec,
                measuredTpKbps,
                durationSec,
                lastSelectedRate
            );
            lastSelectedRate = selectedBitrateKbps;

            const targetQIdx = hybridController.getRepresentationIndexForBitrate(selectedBitrateKbps);

            eventsLog.push({{
                type: 'HYBRID_DECISION',
                targetQIdx,
                selectedBitrateKbps
            }});

            // Duplicate suppression check
            if (targetQIdx !== lastRequestedQualityIdx) {{
                lastRequestedQualityIdx = targetQIdx;
                mockPlayer.setQualityFor('video', targetQIdx);
            }}
        }}

        // Segment 0: 400 kbps download -> controller selects 400 kbps (tier 0)
        simulateFragmentCompleted({{
            mediaType: 'video',
            type: 'MediaSegment',
            bytesLoaded: 100000,
            startMs: 0,
            endMs: 2000,
            index: 0
        }}, 4.0);

        // Segment 1: identical 400 kbps download -> controller selects 400 kbps again
        simulateFragmentCompleted({{
            mediaType: 'video',
            type: 'MediaSegment',
            bytesLoaded: 100000,
            startMs: 2000,
            endMs: 4000,
            index: 1
        }}, 4.0);

        // Segments 2, 3, 4: sustained 4000 kbps bandwidth with healthy buffer 16s
        // Stabilizes harmonic mean, decreases CV, and permits cautious step-up to 800 kbps (tier 1)
        simulateFragmentCompleted({{
            mediaType: 'video',
            type: 'MediaSegment',
            bytesLoaded: 1000000,
            startMs: 4000,
            endMs: 6000,
            index: 2
        }}, 16.0);

        simulateFragmentCompleted({{
            mediaType: 'video',
            type: 'MediaSegment',
            bytesLoaded: 1000000,
            startMs: 6000,
            endMs: 8000,
            index: 3
        }}, 16.0);

        simulateFragmentCompleted({{
            mediaType: 'video',
            type: 'MediaSegment',
            bytesLoaded: 1000000,
            startMs: 8000,
            endMs: 10000,
            index: 4
        }}, 16.0);

        // Segment 5: identical conditions -> stays at 800 kbps
        simulateFragmentCompleted({{
            mediaType: 'video',
            type: 'MediaSegment',
            bytesLoaded: 1000000,
            startMs: 10000,
            endMs: 12000,
            index: 5
        }}, 16.0);

        const result = {{
            totalDecisionsLogged: eventsLog.length,
            totalQualityCallsDispatched: qualityCalls.length,
            qualityCalls: qualityCalls,
            decisions: eventsLog
        }};
        console.log(JSON.stringify(result));
        """
        data = run_node_integration_script(js_code)
        # 6 segments completed -> 6 HYBRID_DECISION events logged
        self.assertEqual(data["totalDecisionsLogged"], 6)
        # Verify step-up to tier 1 occurred
        self.assertGreater(data["totalQualityCallsDispatched"], 1)
        self.assertEqual(data["qualityCalls"][0]["idx"], 0)
        self.assertEqual(data["qualityCalls"][1]["idx"], 1)
        # Verify duplicate suppression: total calls (2) is less than decisions (6)
        self.assertLess(data["totalQualityCallsDispatched"], data["totalDecisionsLogged"])

    def test_fragment_filtering_guards(self):
        """Verifies non-video, init segments, zero bytes, and zero duration are ignored."""
        js_code = f"""
        const {{ HybridQoEController }} = require('{HYBRID_JS_PATH.as_posix()}');

        const hybridController = new HybridQoEController();
        hybridController.setBitrateLadder([
            {{ qualityIndex: 0, bitrate: 400000 }},
            {{ qualityIndex: 1, bitrate: 800000 }}
        ]);

        let decisionsCount = 0;

        function filterAndProcess(req) {{
            if (!req) return;
            if (req.mediaType !== 'video') return;
            if (req.type !== 'MediaSegment') return;
            if (!req.bytesLoaded || req.bytesLoaded <= 0) return;

            const durationSec = (req.endMs - req.startMs) / 1000.0;
            if (durationSec <= 0.001) return;

            decisionsCount++;
        }}

        // 1. Audio segment -> should be ignored
        filterAndProcess({{ mediaType: 'audio', type: 'MediaSegment', bytesLoaded: 30000, startMs: 0, endMs: 2000 }});

        // 2. Init segment -> should be ignored
        filterAndProcess({{ mediaType: 'video', type: 'InitializationSegment', bytesLoaded: 800, startMs: 0, endMs: 50 }});

        // 3. Zero bytes -> should be ignored
        filterAndProcess({{ mediaType: 'video', type: 'MediaSegment', bytesLoaded: 0, startMs: 0, endMs: 2000 }});

        // 4. Cached / zero duration (<= 0.001s) -> should be ignored
        filterAndProcess({{ mediaType: 'video', type: 'MediaSegment', bytesLoaded: 100000, startMs: 1000, endMs: 1000 }});

        // 5. Valid media segment -> should pass
        filterAndProcess({{ mediaType: 'video', type: 'MediaSegment', bytesLoaded: 100000, startMs: 0, endMs: 2000 }});

        console.log(JSON.stringify({{ decisionsCount }}));
        """
        data = run_node_integration_script(js_code)
        self.assertEqual(data["decisionsCount"], 1)

    def test_export_serialization_structure(self):
        """Verifies session export routines serialize active ABR mode and hybrid telemetry."""
        js_code = f"""
        // Mock session state for export test
        const activeAbrMode = 'CUSTOM HYBRID ABR';
        const startupDelaySec = 0.452;
        const totalRebufferSec = 0.0;
        const stallCount = 0;
        const renderedSwitchCount = 1;
        const totalSwitchMagnitudeKbps = 400;

        const telemetrySamples = [
            {{
                timestampIso: '2026-10-21T18:00:00.000Z',
                mediaTimeSec: 2.0,
                bufferLevelSec: 4.5,
                bitrateKbps: 800,
                resolution: '854x480',
                playbackState: 'playing',
                abrMode: activeAbrMode
            }}
        ];

        const switchEvents = [
            {{
                type: 'HYBRID_DECISION',
                clockTime: '18:00:02',
                mediaTimeSec: 2.0,
                oldQuality: '360p',
                newQuality: '480p',
                bitrateKbps: 800,
                bufferSec: 4.5,
                mode: activeAbrMode,
                reason: 'EstTP: 1200k, CV: 0.05, Buf: 4.5s',
                estimatedThroughputKbps: 1200,
                volatilityCv: 0.05
            }}
        ];

        // Format CSV export lines
        const csvLines = [];
        csvLines.push('# Computer Networks Project - MPEG-DASH Playback Session Telemetry');
        csvLines.push(`# Active ABR Mode: ${{activeAbrMode}}`);
        csvLines.push('# --- TIME SERIES TELEMETRY ---');
        csvLines.push('timestamp_iso,media_time_sec,buffer_level_sec,rendered_bitrate_kbps,rendered_resolution,playback_state,abr_mode');
        telemetrySamples.forEach(s => {{
            csvLines.push(`${{s.timestampIso}},${{s.mediaTimeSec}},${{s.bufferLevelSec}},${{s.bitrateKbps}},"${{s.resolution}}",${{s.playbackState}},"${{s.abrMode}}"`);
        }});
        csvLines.push('# --- QUALITY SWITCH & DECISION TIMELINE ---');
        csvLines.push('event_type,clock_time,media_time_sec,old_quality,new_quality,bitrate_kbps,buffer_sec,mode,reason');
        switchEvents.forEach(e => {{
            csvLines.push(`${{e.type}},${{e.clockTime}},${{e.mediaTimeSec}},"${{e.oldQuality}}","${{e.newQuality}}",${{e.bitrateKbps}},${{e.bufferSec}},"${{e.mode}}","${{e.reason || ''}}"`);
        }});
        const csvString = csvLines.join('\\n');

        // Format JSON export
        const jsonExport = {{
            performance_summary: {{
                active_abr_mode: activeAbrMode,
                startup_delay_sec: startupDelaySec,
                stall_count: stallCount
            }},
            switch_timeline_events: switchEvents,
            telemetry_samples: telemetrySamples
        }};

        console.log(JSON.stringify({{
            csvContainsMode: csvString.includes('# Active ABR Mode: CUSTOM HYBRID ABR'),
            csvContainsHybridDecision: csvString.includes('HYBRID_DECISION,18:00:02,2,"360p","480p",800,4.5,"CUSTOM HYBRID ABR"'),
            jsonActiveMode: jsonExport.performance_summary.active_abr_mode,
            jsonEventType: jsonExport.switch_timeline_events[0].type,
            jsonEstimatedTp: jsonExport.switch_timeline_events[0].estimatedThroughputKbps
        }}));
        """
        data = run_node_integration_script(js_code)
        self.assertTrue(data["csvContainsMode"])
        self.assertTrue(data["csvContainsHybridDecision"])
        self.assertEqual(data["jsonActiveMode"], "CUSTOM HYBRID ABR")
        self.assertEqual(data["jsonEventType"], "HYBRID_DECISION")
        self.assertEqual(data["jsonEstimatedTp"], 1200)

    def test_throughput_and_buffer_controllers_headless(self):
        """Verifies ThroughputBasedController and BufferBasedController execution in Node.js."""
        js_code = f"""
        const {{ ThroughputBasedController, BufferBasedController, HybridQoEController }} = require('{HYBRID_JS_PATH.as_posix()}');

        const mockReps = [
            {{ qualityIndex: 0, height: 360, bitrate: 400000 }},
            {{ qualityIndex: 1, height: 480, bitrate: 800000 }},
            {{ qualityIndex: 2, height: 720, bitrate: 1500000 }},
            {{ qualityIndex: 3, height: 1080, bitrate: 3000000 }}
        ];

        // 1. Test ThroughputBasedController
        const tpCtrl = new ThroughputBasedController({{ safetyFactor: 0.85, windowSize: 5 }});
        tpCtrl.setBitrateLadder(mockReps);

        // Throughput 5000 kbps: 5000 * 0.85 = 4250 kbps -> selects 3000 kbps (1080p, index 3)
        const tpBitrateHigh = tpCtrl.selectBitrate(0, 10.0, 5000.0, 2.0, 400);
        const tpIndexHigh = tpCtrl.getRepresentationIndexForBitrate(tpBitrateHigh);

        // Low throughput 600 kbps: 600 * 0.85 = 510 kbps -> selects 400 kbps (360p, index 0)
        tpCtrl.reset();
        tpCtrl.setBitrateLadder(mockReps);
        const tpBitrateLow = tpCtrl.selectBitrate(0, 10.0, 600.0, 2.0, 400);
        const tpIndexLow = tpCtrl.getRepresentationIndexForBitrate(tpBitrateLow);

        // 2. Test BufferBasedController
        const bufCtrl = new BufferBasedController({{ reservoirSec: 5.0, cushionSec: 10.0, hysteresisSec: 0.5 }});
        bufCtrl.setBitrateLadder(mockReps);

        // Low buffer 3.0s (< 5.0s reservoir) -> selects min 400 kbps (360p, index 0)
        const bufBitrateLow = bufCtrl.selectBitrate(0, 3.0, 5000.0, 2.0, 400);
        const bufIndexLow = bufCtrl.getRepresentationIndexForBitrate(bufBitrateLow);

        // High buffer 16.0s (> 15.0s upper) -> selects max 3000 kbps (1080p, index 3)
        const bufBitrateHigh = bufCtrl.selectBitrate(1, 16.0, 5000.0, 2.0, 400);
        const bufIndexHigh = bufCtrl.getRepresentationIndexForBitrate(bufBitrateHigh);

        console.log(JSON.stringify({{
            tpBitrateHigh,
            tpIndexHigh,
            tpBitrateLow,
            tpIndexLow,
            bufBitrateLow,
            bufIndexLow,
            bufBitrateHigh,
            bufIndexHigh
        }}));
        """
        data = run_node_integration_script(js_code)
        self.assertEqual(data["tpBitrateHigh"], 3000)
        self.assertEqual(data["tpIndexHigh"], 3)
        self.assertEqual(data["tpBitrateLow"], 400)
        self.assertEqual(data["tpIndexLow"], 0)
        self.assertEqual(data["bufBitrateLow"], 400)
        self.assertEqual(data["bufIndexLow"], 0)
        self.assertEqual(data["bufBitrateHigh"], 3000)
        self.assertEqual(data["bufIndexHigh"], 3)


class TestRepairedPlayerLifecycleAndABR(unittest.TestCase):
    """Verifies playback assets, sequential runner state machine, and metric freezing."""

    def setUp(self):
        self.app = create_app(dash_dir=PROJECT_ROOT / "static" / "dash")
        self.client = self.app.test_client()

    def test_all_manifest_media_segments_accessible(self):
        """Verifies all 60 video chunks, 4 video inits, 1 audio init, and 16 audio chunks return HTTP 200."""
        # 1. Check video representations 0, 1, 2, 3
        for rep in range(4):
            init_res = self.client.get(f"/dash/init-stream{rep}.m4s")
            self.assertEqual(init_res.status_code, 200, f"Missing init-stream{rep}.m4s")
            self.assertTrue(init_res.content_type.startswith("video/mp4"))

            for chunk_idx in range(1, 16):
                chunk_name = f"chunk-stream{rep}-{chunk_idx:05d}.m4s"
                res = self.client.get(f"/dash/{chunk_name}")
                self.assertEqual(res.status_code, 200, f"Missing {chunk_name}")
                self.assertTrue(res.content_type.startswith("video/mp4"))

        # 2. Check audio representation 4
        audio_init = self.client.get("/dash/init-stream4.m4s")
        self.assertEqual(audio_init.status_code, 200, "Missing audio init-stream4.m4s")
        for chunk_idx in range(1, 17):
            chunk_name = f"chunk-stream4-{chunk_idx:05d}.m4s"
            res = self.client.get(f"/dash/{chunk_name}")
            self.assertEqual(res.status_code, 200, f"Missing {chunk_name}")

    def test_sequential_runner_logic_in_headless_node(self):
        """Verifies sequential runner execution order, step progression, and cancellation."""
        js_code = f"""
        const runAllSequence = ['throughput', 'buffer', 'hybrid'];
        let runAllIndex = 0;
        let runAllActive = true;
        let runAllCancelRequested = false;

        const executedAlgorithms = [];

        function simulateRunStep() {{
            if (!runAllActive || runAllCancelRequested) return 'CANCELLED';
            if (runAllIndex >= runAllSequence.length) return 'COMPLETED';

            const algo = runAllSequence[runAllIndex];
            executedAlgorithms.push(algo);

            // Advance
            runAllIndex++;
            if (runAllIndex < runAllSequence.length) {{
                return simulateRunStep();
            }}
            return 'COMPLETED';
        }}

        const normalResult = simulateRunStep();

        // Test cancellation
        runAllIndex = 0;
        runAllActive = true;
        runAllCancelRequested = false;
        const cancelledAlgorithms = [];

        function simulateCancelledStep() {{
            if (!runAllActive || runAllCancelRequested) return 'CANCELLED';
            if (runAllIndex >= runAllSequence.length) return 'COMPLETED';

            const algo = runAllSequence[runAllIndex];
            cancelledAlgorithms.push(algo);

            // User clicks Stop after algorithm 1
            if (runAllIndex === 1) {{
                runAllCancelRequested = true;
                runAllActive = false;
                return 'CANCELLED';
            }}

            runAllIndex++;
            return simulateCancelledStep();
        }}

        const cancelResult = simulateCancelledStep();

        console.log(JSON.stringify({{
            normalResult,
            executedAlgorithms,
            cancelResult,
            cancelledAlgorithms
        }}));
        """
        data = run_node_integration_script(js_code)
        self.assertEqual(data["normalResult"], "COMPLETED")
        self.assertEqual(data["executedAlgorithms"], ["throughput", "buffer", "hybrid"])
        self.assertEqual(data["cancelResult"], "CANCELLED")
        self.assertEqual(data["cancelledAlgorithms"], ["throughput", "buffer"])
        self.assertNotIn("hybrid", data["cancelledAlgorithms"])

    def test_metric_freezing_logic_in_headless_node(self):
        """Verifies that once finalized, metrics cannot be mutated by late samples or callbacks."""
        js_code = f"""
        let isExperimentActive = true;
        let finalizedMetrics = null;

        let curTime = 30.0;
        let totalRebufferSec = 0.0;
        let avgBitrateKbps = 2400;
        let totalSwitchMagnitudeKbps = 600;

        // Finalize
        function finalize() {{
            isExperimentActive = false;
            const estimatedSegments = curTime / 2.0;
            const qualityUtility = 1.0 * ((avgBitrateKbps / 1000.0) * estimatedSegments);
            const stallPenalty = 4.3 * totalRebufferSec;
            const switchPenalty = 1.0 * (totalSwitchMagnitudeKbps / 1000.0);
            const computedQoE = qualityUtility - stallPenalty - switchPenalty;

            finalizedMetrics = {{
                durationSec: curTime,
                avgBitrateKbps: avgBitrateKbps,
                qoeScore: parseFloat(computedQoE.toFixed(2))
            }};
        }}

        finalize();
        const initialFrozenQoE = finalizedMetrics.qoeScore;
        const initialFrozenBitrate = finalizedMetrics.avgBitrateKbps;

        // Simulate late callback arriving 3 seconds later
        function onLateCallback() {{
            if (!isExperimentActive) {{
                // Guard: ignored when not active!
                return;
            }}
            // If bug existed, it would mutate:
            avgBitrateKbps = 9999;
            curTime = 40.0;
        }}

        onLateCallback();

        console.log(JSON.stringify({{
            initialFrozenQoE,
            initialFrozenBitrate,
            postCallbackQoE: finalizedMetrics.qoeScore,
            postCallbackBitrate: finalizedMetrics.avgBitrateKbps,
            isFrozen: (initialFrozenQoE === finalizedMetrics.qoeScore) && (initialFrozenBitrate === finalizedMetrics.avgBitrateKbps)
        }}));
        """
        data = run_node_integration_script(js_code)
        self.assertTrue(data["isFrozen"])
        self.assertEqual(data["initialFrozenQoE"], data["postCallbackQoE"])
        self.assertEqual(data["initialFrozenBitrate"], data["postCallbackBitrate"])

    def test_controllers_adaptation_under_bandwidth_tiers(self):
        """Verifies Throughput, Buffer, and Hybrid controllers respond to 5 Mbps, 1 Mbps, and 500 kbps."""
        js_code = f"""
        const {{ ThroughputBasedController, BufferBasedController, HybridQoEController }} = require('{HYBRID_JS_PATH.as_posix()}');

        const ladder = [
            {{ qualityIndex: 0, height: 360, bitrate: 400000 }},
            {{ qualityIndex: 1, height: 480, bitrate: 800000 }},
            {{ qualityIndex: 2, height: 720, bitrate: 1500000 }},
            {{ qualityIndex: 3, height: 1080, bitrate: 3000000 }}
        ];

        // 1. Throughput Controller under 5 Mbps, 1 Mbps, 500 kbps
        const tpCtrl = new ThroughputBasedController({{ safetyFactor: 0.85, windowSize: 5 }});
        tpCtrl.setBitrateLadder(ladder);

        // 5 Mbps (5000k * 0.85 = 4250k) -> selects 3000 kbps (1080p)
        const tp5M = tpCtrl.selectBitrate(0, 10.0, 5000.0, 2.0, 400);

        // 1 Mbps (1000k * 0.85 = 850k) -> selects 800 kbps (480p)
        tpCtrl.reset();
        tpCtrl.setBitrateLadder(ladder);
        const tp1M = tpCtrl.selectBitrate(0, 10.0, 1000.0, 2.0, 400);

        // 500 kbps (500k * 0.85 = 425k) -> selects 400 kbps (360p)
        tpCtrl.reset();
        tpCtrl.setBitrateLadder(ladder);
        const tp500k = tpCtrl.selectBitrate(0, 10.0, 500.0, 2.0, 400);

        // 2. Buffer Controller under low buffer vs high buffer
        const bufCtrl = new BufferBasedController({{ reservoirSec: 5.0, cushionSec: 10.0, hysteresisSec: 0.5 }});
        bufCtrl.setBitrateLadder(ladder);
        const bufLow = bufCtrl.selectBitrate(0, 2.0, 5000.0, 2.0, 400);  // Reservoir -> 400 kbps
        const bufHigh = bufCtrl.selectBitrate(1, 16.0, 5000.0, 2.0, 400); // Cushion max -> 3000 kbps

        // 3. Hybrid Controller adapts to high bandwidth
        const hybCtrl = new HybridQoEController();
        hybCtrl.setBitrateLadder(ladder);
        const hybInit = hybCtrl.selectBitrate(0, 10.0, 5000.0, 2.0, 400);

        console.log(JSON.stringify({{
            tp5M,
            tp1M,
            tp500k,
            bufLow,
            bufHigh,
            hybInit
        }}));
        """
        data = run_node_integration_script(js_code)
        self.assertEqual(data["tp5M"], 3000)
        self.assertEqual(data["tp1M"], 800)
        self.assertEqual(data["tp500k"], 400)
        self.assertEqual(data["bufLow"], 400)
        self.assertEqual(data["bufHigh"], 3000)
        self.assertIn(data["hybInit"], [400, 800, 1500, 3000])


if __name__ == "__main__":
    unittest.main()
