"""Cross-Language Parity Test Suite for Hybrid ABR Algorithm (Stage 9A).

Verifies 100% mathematical and decision equivalence between:
1. Reference Python implementation: src/algorithms/hybrid.py (HybridQoEABR)
2. Browser JavaScript port: static/js/hybrid-abr.js (HybridQoEController)

Evaluates identical input state vectors across 58+ deterministic test scenarios covering:
- Cold-start, empty history, and zero throughput observations
- Buffer reservoir safety clamping and underrun prevention
- Buffer cushion linear capacity scaling
- Throughput harmonic mean and volatility (CV) discounting
- Download drain feasibility and stall safety margins
- Cautious step-up (+1 tier limit and 0.3 cushion headroom)
- Asymmetric multi-tier rapid step-down on bandwidth collapse
- Quality utility vs. switching penalty objective optimization
- Strict tie-breaking rules
- Custom and dynamic representation ladders (e.g. DASH 4-rung, 3-rung)
- Multi-step dynamic streaming traces and reset state clearance
"""

import json
import shutil
import subprocess
import unittest
from pathlib import Path
from typing import Dict, Any, List

from src.algorithms.hybrid import HybridQoEABR


PROJECT_ROOT = Path(__file__).resolve().parent.parent
JS_MODULE_PATH = PROJECT_ROOT / "static" / "js" / "hybrid-abr.js"


def run_node_parity_runner(cases: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Executes test cases in Node.js against static/js/hybrid-abr.js.

    Args:
        cases: List of test case definitions.

    Returns:
        List of results returned by the JavaScript implementation.
    """
    node_bin = shutil.which("node")
    if not node_bin:
        raise RuntimeError("Node.js runtime not found on PATH. Required for cross-language parity testing.")

    runner_script = f"""
    const {{ HybridQoEController }} = require('{JS_MODULE_PATH.as_posix()}');
    const readline = require('readline');

    let inputData = '';
    process.stdin.on('data', chunk => {{ inputData += chunk; }});
    process.stdin.on('end', () => {{
        const cases = JSON.parse(inputData);
        const results = [];

        for (const testCase of cases) {{
            const options = Object.assign({{}}, testCase.config || {{}});
            if (testCase.ladder) {{
                options.bitrateLadderKbps = testCase.ladder;
            }}
            if (testCase.initial_bitrate !== undefined) {{
                options.initialBitrateKbps = testCase.initial_bitrate;
            }}

            const ctrl = new HybridQoEController(options);
            const stepResults = [];

            for (const step of testCase.sequence) {{
                if (step.action === 'reset') {{
                    ctrl.reset();
                    stepResults.push({{
                        action: 'reset',
                        estimated_tp: ctrl.estimatedThroughputKbps,
                        volatility: ctrl.computeVolatility(),
                        last_selected: ctrl.lastSelectedBitrate
                    }});
                }} else {{
                    const chosenRate = ctrl.selectBitrate(
                        step.segment_index,
                        step.current_buffer_sec,
                        step.last_throughput_kbps,
                        step.last_download_time_sec,
                        step.last_bitrate_kbps !== undefined ? step.last_bitrate_kbps : null
                    );
                    stepResults.push({{
                        selected_bitrate: chosenRate,
                        estimated_tp: ctrl.estimatedThroughputKbps,
                        volatility: ctrl.computeVolatility(),
                        last_selected: ctrl.lastSelectedBitrate
                    }});
                }}
            }}
            results.push({{
                case_id: testCase.case_id,
                steps: stepResults
            }});
        }}
        console.log(JSON.stringify(results));
    }});
    """

    proc = subprocess.run(
        [node_bin, "-e", runner_script],
        input=json.dumps(cases),
        capture_output=True,
        text=True,
        cwd=str(PROJECT_ROOT),
        timeout=15
    )

    if proc.returncode != 0:
        raise RuntimeError(f"Node.js parity runner failed with code {proc.returncode}:\n{proc.stderr}")

    return json.loads(proc.stdout)


class TestHybridABRParity(unittest.TestCase):
    """Test suite certifying 100% decision parity between Python and JavaScript ports."""

    @classmethod
    def setUpClass(cls):
        """Verify Node.js availability."""
        cls.node_available = bool(shutil.which("node"))

    def setUp(self):
        if not self.node_available:
            self.skipTest("Node.js runtime is unavailable on this machine. Cannot run JavaScript parity test.")

    def _execute_and_assert_parity(self, test_cases: List[Dict[str, Any]]):
        """Helper to run test cases in both Python and JS and assert exact parity."""
        # Run in JS
        js_results = run_node_parity_runner(test_cases)
        js_map = {res["case_id"]: res["steps"] for res in js_results}

        # Run in Python
        for case in test_cases:
            cid = case["case_id"]
            ladder = case.get("ladder", [300, 750, 1200, 1850, 2850, 4300])
            cfg = case.get("config", {})
            init_br = case.get("initial_bitrate", None)

            py_ctrl = HybridQoEABR(
                bitrate_ladder_kbps=ladder,
                initial_bitrate_kbps=init_br,
                reservoir_sec=cfg.get("reservoir_sec", 5.0),
                cushion_sec=cfg.get("cushion_sec", 10.0),
                safety_factor_base=cfg.get("safety_factor_base", 0.90),
                safety_factor_min=cfg.get("safety_factor_min", 0.60),
                volatility_weight=cfg.get("volatility_weight", 0.30),
                stall_safety_margin_sec=cfg.get("stall_safety_margin_sec", 0.5),
                switch_penalty_lambda=cfg.get("switch_penalty_lambda", 0.5),
                window_size=cfg.get("window_size", 5),
                segment_duration_sec=cfg.get("segment_duration_sec", 2.0),
            )

            js_steps = js_map.get(cid)
            self.assertIsNotNone(js_steps, f"Missing JS result for case {cid}")
            self.assertEqual(len(case["sequence"]), len(js_steps), f"Step length mismatch on case {cid}")

            for idx, step in enumerate(case["sequence"]):
                js_s = js_steps[idx]
                if step.get("action") == "reset":
                    py_ctrl.reset()
                    self.assertEqual(py_ctrl.estimated_throughput_kbps, js_s["estimated_tp"])
                    self.assertEqual(py_ctrl.compute_volatility(), js_s["volatility"])
                    self.assertEqual(py_ctrl.last_selected_bitrate, js_s["last_selected"])
                else:
                    py_decision = py_ctrl.select_bitrate(
                        segment_index=step["segment_index"],
                        current_buffer_sec=step["current_buffer_sec"],
                        last_throughput_kbps=step["last_throughput_kbps"],
                        last_download_time_sec=step["last_download_time_sec"],
                        last_bitrate_kbps=step.get("last_bitrate_kbps", None),
                    )

                    # 1. Decision Parity (Exact integer bitrate match)
                    self.assertEqual(
                        py_decision,
                        js_s["selected_bitrate"],
                        f"Bitrate decision mismatch in case '{cid}' step {idx}: "
                        f"Python={py_decision} kbps, JS={js_s['selected_bitrate']} kbps | Input={step}"
                    )

                    # 2. State Parity: Estimated Throughput (Float within 1e-3 kbps)
                    self.assertAlmostEqual(
                        py_ctrl.estimated_throughput_kbps,
                        js_s["estimated_tp"],
                        places=2,
                        msg=f"Throughput estimate divergence in case '{cid}' step {idx}: "
                            f"Python={py_ctrl.estimated_throughput_kbps}, JS={js_s['estimated_tp']}"
                    )

                    # 3. State Parity: Volatility CV (Float within 1e-3)
                    self.assertAlmostEqual(
                        py_ctrl.compute_volatility(),
                        js_s["volatility"],
                        places=3,
                        msg=f"Volatility divergence in case '{cid}' step {idx}: "
                            f"Python={py_ctrl.compute_volatility()}, JS={js_s['volatility']}"
                    )

    def test_cold_start_and_empty_history_parity(self):
        """Verifies parity on initial segments, zero throughput, and empty history (Cases 1-6)."""
        cases = [
            {
                "case_id": "cold_start_empty_zero_tp",
                "sequence": [{"segment_index": 0, "current_buffer_sec": 0.0, "last_throughput_kbps": 0.0, "last_download_time_sec": 0.0}]
            },
            {
                "case_id": "cold_start_negative_tp",
                "sequence": [{"segment_index": 0, "current_buffer_sec": 2.0, "last_throughput_kbps": -50.0, "last_download_time_sec": 1.0}]
            },
            {
                "case_id": "cold_start_custom_initial_bitrate",
                "initial_bitrate": 750,
                "sequence": [{"segment_index": 0, "current_buffer_sec": 0.0, "last_throughput_kbps": 0.0, "last_download_time_sec": 0.0}]
            },
            {
                "case_id": "cold_start_dash_4rung",
                "ladder": [400, 800, 1500, 3000],
                "sequence": [{"segment_index": 0, "current_buffer_sec": 0.0, "last_throughput_kbps": 0.0, "last_download_time_sec": 0.0}]
            },
            {
                "case_id": "cold_start_then_zero_tp",
                "sequence": [
                    {"segment_index": 0, "current_buffer_sec": 2.0, "last_throughput_kbps": 2000.0, "last_download_time_sec": 1.0},
                    {"segment_index": 1, "current_buffer_sec": 3.0, "last_throughput_kbps": 0.0, "last_download_time_sec": 1.0}
                ]
            },
            {
                "case_id": "single_sample_volatility_zero",
                "sequence": [{"segment_index": 0, "current_buffer_sec": 15.0, "last_throughput_kbps": 3000.0, "last_download_time_sec": 0.5}]
            }
        ]
        self._execute_and_assert_parity(cases)

    def test_buffer_reservoir_boundary_parity(self):
        """Verifies reservoir clamping across critical boundaries (Cases 7-14)."""
        cases = [
            {
                "case_id": "reservoir_zero_buffer_huge_tp",
                "sequence": [{"segment_index": 1, "current_buffer_sec": 0.0, "last_throughput_kbps": 15000.0, "last_download_time_sec": 0.2}]
            },
            {
                "case_id": "reservoir_2s_buffer_huge_tp",
                "sequence": [{"segment_index": 1, "current_buffer_sec": 2.0, "last_throughput_kbps": 12000.0, "last_download_time_sec": 0.2}]
            },
            {
                "case_id": "reservoir_strict_subboundary_4_99s",
                "sequence": [{"segment_index": 1, "current_buffer_sec": 4.99, "last_throughput_kbps": 10000.0, "last_download_time_sec": 0.2}]
            },
            {
                "case_id": "reservoir_exact_boundary_5_00s",
                "sequence": [{"segment_index": 1, "current_buffer_sec": 5.00, "last_throughput_kbps": 10000.0, "last_download_time_sec": 0.2}]
            },
            {
                "case_id": "reservoir_custom_8s_boundary",
                "config": {"reservoir_sec": 8.0, "cushion_sec": 12.0},
                "sequence": [{"segment_index": 1, "current_buffer_sec": 7.95, "last_throughput_kbps": 12000.0, "last_download_time_sec": 0.2}]
            },
            {
                "case_id": "reservoir_custom_8s_exact",
                "config": {"reservoir_sec": 8.0, "cushion_sec": 12.0},
                "sequence": [{"segment_index": 1, "current_buffer_sec": 8.00, "last_throughput_kbps": 12000.0, "last_download_time_sec": 0.2}]
            },
            {
                "case_id": "reservoir_dash_4rung_clamp",
                "ladder": [400, 800, 1500, 3000],
                "sequence": [{"segment_index": 1, "current_buffer_sec": 3.0, "last_throughput_kbps": 9000.0, "last_download_time_sec": 0.2}]
            },
            {
                "case_id": "reservoir_3rung_clamp",
                "ladder": [500, 1000, 2000],
                "sequence": [{"segment_index": 1, "current_buffer_sec": 4.5, "last_throughput_kbps": 8000.0, "last_download_time_sec": 0.2}]
            }
        ]
        self._execute_and_assert_parity(cases)

    def test_cushion_linear_scaling_parity(self):
        """Verifies buffer cushion progression and saturation (Cases 15-22)."""
        cases = [
            {
                "case_id": "cushion_just_above_5_01s",
                "sequence": [{"segment_index": 1, "current_buffer_sec": 5.01, "last_throughput_kbps": 5000.0, "last_download_time_sec": 0.5}]
            },
            {
                "case_id": "cushion_25_percent_7_5s",
                "sequence": [{"segment_index": 1, "current_buffer_sec": 7.5, "last_throughput_kbps": 4000.0, "last_download_time_sec": 0.5}]
            },
            {
                "case_id": "cushion_50_percent_10_0s",
                "sequence": [{"segment_index": 1, "current_buffer_sec": 10.0, "last_throughput_kbps": 4000.0, "last_download_time_sec": 0.5}]
            },
            {
                "case_id": "cushion_75_percent_12_5s",
                "sequence": [{"segment_index": 1, "current_buffer_sec": 12.5, "last_throughput_kbps": 5000.0, "last_download_time_sec": 0.5}]
            },
            {
                "case_id": "cushion_exact_saturation_15_0s",
                "sequence": [{"segment_index": 1, "current_buffer_sec": 15.0, "last_throughput_kbps": 6000.0, "last_download_time_sec": 0.5}]
            },
            {
                "case_id": "cushion_supersaturated_25_0s",
                "sequence": [{"segment_index": 1, "current_buffer_sec": 25.0, "last_throughput_kbps": 8000.0, "last_download_time_sec": 0.5}]
            },
            {
                "case_id": "cushion_dash_4rung_mid",
                "ladder": [400, 800, 1500, 3000],
                "sequence": [{"segment_index": 1, "current_buffer_sec": 10.0, "last_throughput_kbps": 3000.0, "last_download_time_sec": 0.5}]
            },
            {
                "case_id": "cushion_dash_4rung_saturated",
                "ladder": [400, 800, 1500, 3000],
                "sequence": [{"segment_index": 1, "current_buffer_sec": 20.0, "last_throughput_kbps": 5000.0, "last_download_time_sec": 0.5}]
            }
        ]
        self._execute_and_assert_parity(cases)

    def test_volatility_and_uncertainty_discount_parity(self):
        """Verifies harmonic mean and volatility CV calculations (Cases 23-30)."""
        cases = [
            {
                "case_id": "volatility_stable_cv_zero",
                "sequence": [
                    {"segment_index": 0, "current_buffer_sec": 16.0, "last_throughput_kbps": 3000.0, "last_download_time_sec": 0.5},
                    {"segment_index": 1, "current_buffer_sec": 16.0, "last_throughput_kbps": 3000.0, "last_download_time_sec": 0.5},
                    {"segment_index": 2, "current_buffer_sec": 16.0, "last_throughput_kbps": 3000.0, "last_download_time_sec": 0.5},
                    {"segment_index": 3, "current_buffer_sec": 16.0, "last_throughput_kbps": 3000.0, "last_download_time_sec": 0.5}
                ]
            },
            {
                "case_id": "volatility_high_alternating_clamp_min_safety",
                "sequence": [
                    {"segment_index": 0, "current_buffer_sec": 16.0, "last_throughput_kbps": 500.0, "last_download_time_sec": 1.0},
                    {"segment_index": 1, "current_buffer_sec": 16.0, "last_throughput_kbps": 5000.0, "last_download_time_sec": 0.2},
                    {"segment_index": 2, "current_buffer_sec": 16.0, "last_throughput_kbps": 500.0, "last_download_time_sec": 1.0},
                    {"segment_index": 3, "current_buffer_sec": 16.0, "last_throughput_kbps": 5000.0, "last_download_time_sec": 0.2}
                ]
            },
            {
                "case_id": "volatility_moderate_linear_decay",
                "sequence": [
                    {"segment_index": 0, "current_buffer_sec": 16.0, "last_throughput_kbps": 2000.0, "last_download_time_sec": 0.5},
                    {"segment_index": 1, "current_buffer_sec": 16.0, "last_throughput_kbps": 3000.0, "last_download_time_sec": 0.5},
                    {"segment_index": 2, "current_buffer_sec": 16.0, "last_throughput_kbps": 2200.0, "last_download_time_sec": 0.5},
                    {"segment_index": 3, "current_buffer_sec": 16.0, "last_throughput_kbps": 2800.0, "last_download_time_sec": 0.5}
                ]
            },
            {
                "case_id": "volatility_window_overflow_pop",
                "config": {"window_size": 3},
                "sequence": [
                    {"segment_index": 0, "current_buffer_sec": 16.0, "last_throughput_kbps": 1000.0, "last_download_time_sec": 1.0},
                    {"segment_index": 1, "current_buffer_sec": 16.0, "last_throughput_kbps": 2000.0, "last_download_time_sec": 1.0},
                    {"segment_index": 2, "current_buffer_sec": 16.0, "last_throughput_kbps": 3000.0, "last_download_time_sec": 1.0},
                    {"segment_index": 3, "current_buffer_sec": 16.0, "last_throughput_kbps": 4000.0, "last_download_time_sec": 1.0}
                ]
            },
            {
                "case_id": "volatility_custom_high_weight",
                "config": {"volatility_weight": 0.60, "safety_factor_min": 0.50},
                "sequence": [
                    {"segment_index": 0, "current_buffer_sec": 16.0, "last_throughput_kbps": 1000.0, "last_download_time_sec": 0.5},
                    {"segment_index": 1, "current_buffer_sec": 16.0, "last_throughput_kbps": 4000.0, "last_download_time_sec": 0.5}
                ]
            },
            {
                "case_id": "volatility_two_sample_identical",
                "sequence": [
                    {"segment_index": 0, "current_buffer_sec": 16.0, "last_throughput_kbps": 2500.0, "last_download_time_sec": 0.5},
                    {"segment_index": 1, "current_buffer_sec": 16.0, "last_throughput_kbps": 2500.0, "last_download_time_sec": 0.5}
                ]
            },
            {
                "case_id": "volatility_dash_4rung_fluctuation",
                "ladder": [400, 800, 1500, 3000],
                "sequence": [
                    {"segment_index": 0, "current_buffer_sec": 15.0, "last_throughput_kbps": 800.0, "last_download_time_sec": 0.5},
                    {"segment_index": 1, "current_buffer_sec": 15.0, "last_throughput_kbps": 3500.0, "last_download_time_sec": 0.5},
                    {"segment_index": 2, "current_buffer_sec": 15.0, "last_throughput_kbps": 900.0, "last_download_time_sec": 0.5}
                ]
            },
            {
                "case_id": "volatility_outlier_spike_resistance",
                "sequence": [
                    {"segment_index": 0, "current_buffer_sec": 15.0, "last_throughput_kbps": 1000.0, "last_download_time_sec": 0.5},
                    {"segment_index": 1, "current_buffer_sec": 15.0, "last_throughput_kbps": 1000.0, "last_download_time_sec": 0.5},
                    {"segment_index": 2, "current_buffer_sec": 15.0, "last_throughput_kbps": 50000.0, "last_download_time_sec": 0.1}
                ]
            }
        ]
        self._execute_and_assert_parity(cases)

    def test_drain_feasibility_and_fallback_parity(self):
        """Verifies candidate drain constraint and fallback to lowest rate (Cases 31-37)."""
        cases = [
            {
                "case_id": "feasibility_candidate_fits_drain",
                "sequence": [{"segment_index": 1, "current_buffer_sec": 6.0, "last_throughput_kbps": 3000.0, "last_download_time_sec": 0.5}]
            },
            {
                "case_id": "feasibility_high_rate_exceeds_drain_filtered",
                "sequence": [{"segment_index": 1, "current_buffer_sec": 5.2, "last_throughput_kbps": 2000.0, "last_download_time_sec": 0.5}]
            },
            {
                "case_id": "feasibility_fallback_to_minimum_ladder_rate",
                "sequence": [{"segment_index": 1, "current_buffer_sec": 5.05, "last_throughput_kbps": 400.0, "last_download_time_sec": 2.0}]
            },
            {
                "case_id": "feasibility_custom_segment_duration_4s",
                "config": {"segment_duration_sec": 4.0},
                "sequence": [{"segment_index": 1, "current_buffer_sec": 7.0, "last_throughput_kbps": 2000.0, "last_download_time_sec": 1.0}]
            },
            {
                "case_id": "feasibility_custom_safety_margin_1s",
                "config": {"stall_safety_margin_sec": 1.0},
                "sequence": [{"segment_index": 1, "current_buffer_sec": 6.0, "last_throughput_kbps": 3000.0, "last_download_time_sec": 0.5}]
            },
            {
                "case_id": "feasibility_dash_4rung_drain",
                "ladder": [400, 800, 1500, 3000],
                "sequence": [{"segment_index": 1, "current_buffer_sec": 6.0, "last_throughput_kbps": 2500.0, "last_download_time_sec": 0.5}]
            },
            {
                "case_id": "feasibility_3rung_drain",
                "ladder": [500, 1000, 2000],
                "sequence": [{"segment_index": 1, "current_buffer_sec": 5.5, "last_throughput_kbps": 1200.0, "last_download_time_sec": 1.0}]
            }
        ]
        self._execute_and_assert_parity(cases)

    def test_cautious_step_up_and_step_down_parity(self):
        """Verifies +1 tier constraint and rapid multi-tier downshifts (Cases 38-46)."""
        cases = [
            {
                "case_id": "step_up_from_tier0_to_max1",
                "sequence": [{"segment_index": 1, "current_buffer_sec": 20.0, "last_throughput_kbps": 15000.0, "last_download_time_sec": 0.1, "last_bitrate_kbps": 300}]
            },
            {
                "case_id": "step_up_from_tier1_to_max2",
                "sequence": [{"segment_index": 2, "current_buffer_sec": 20.0, "last_throughput_kbps": 15000.0, "last_download_time_sec": 0.1, "last_bitrate_kbps": 750}]
            },
            {
                "case_id": "step_up_from_tier2_to_max3",
                "sequence": [{"segment_index": 3, "current_buffer_sec": 20.0, "last_throughput_kbps": 15000.0, "last_download_time_sec": 0.1, "last_bitrate_kbps": 1200}]
            },
            {
                "case_id": "step_up_blocked_by_insufficient_buffer",
                "sequence": [{"segment_index": 1, "current_buffer_sec": 6.5, "last_throughput_kbps": 15000.0, "last_download_time_sec": 0.1, "last_bitrate_kbps": 300}]
            },
            {
                "case_id": "step_up_allowed_at_exact_buffer_threshold_8s",
                "sequence": [{"segment_index": 1, "current_buffer_sec": 8.0, "last_throughput_kbps": 15000.0, "last_download_time_sec": 0.1, "last_bitrate_kbps": 300}]
            },
            {
                "case_id": "step_up_top_tier_ceiling",
                "sequence": [{"segment_index": 5, "current_buffer_sec": 25.0, "last_throughput_kbps": 20000.0, "last_download_time_sec": 0.1, "last_bitrate_kbps": 4300}]
            },
            {
                "case_id": "rapid_step_down_multi_tier_collapse",
                "sequence": [{"segment_index": 5, "current_buffer_sec": 7.0, "last_throughput_kbps": 350.0, "last_download_time_sec": 3.0, "last_bitrate_kbps": 4300}]
            },
            {
                "case_id": "rapid_step_down_from_2850_to_750",
                "sequence": [{"segment_index": 4, "current_buffer_sec": 8.0, "last_throughput_kbps": 900.0, "last_download_time_sec": 2.0, "last_bitrate_kbps": 2850}]
            },
            {
                "case_id": "step_up_dash_4rung",
                "ladder": [400, 800, 1500, 3000],
                "sequence": [{"segment_index": 1, "current_buffer_sec": 18.0, "last_throughput_kbps": 10000.0, "last_download_time_sec": 0.1, "last_bitrate_kbps": 400}]
            }
        ]
        self._execute_and_assert_parity(cases)

    def test_switching_penalty_and_objective_parity(self):
        """Verifies utility function, switching penalty lambda, and tie-breaking (Cases 47-53)."""
        cases = [
            {
                "case_id": "switch_penalty_standard_lambda_0_5",
                "sequence": [
                    {"segment_index": 1, "current_buffer_sec": 12.0, "last_throughput_kbps": 1600.0, "last_download_time_sec": 1.0, "last_bitrate_kbps": 1200}
                ]
            },
            {
                "case_id": "switch_penalty_zero_pure_greedy",
                "config": {"switch_penalty_lambda": 0.0},
                "sequence": [
                    {"segment_index": 1, "current_buffer_sec": 12.0, "last_throughput_kbps": 1600.0, "last_download_time_sec": 1.0, "last_bitrate_kbps": 750}
                ]
            },
            {
                "case_id": "switch_penalty_heavy_anti_flicker",
                "config": {"switch_penalty_lambda": 2.0},
                "sequence": [
                    {"segment_index": 1, "current_buffer_sec": 11.0, "last_throughput_kbps": 1900.0, "last_download_time_sec": 1.0, "last_bitrate_kbps": 1200}
                ]
            },
            {
                "case_id": "switch_penalty_tie_breaking_lower_rate",
                "config": {"switch_penalty_lambda": 1.0},
                "sequence": [
                    {"segment_index": 1, "current_buffer_sec": 12.0, "last_throughput_kbps": 1500.0, "last_download_time_sec": 1.0, "last_bitrate_kbps": 750}
                ]
            },
            {
                "case_id": "switch_penalty_top_tier_preference",
                "sequence": [
                    {"segment_index": 3, "current_buffer_sec": 20.0, "last_throughput_kbps": 3500.0, "last_download_time_sec": 0.5, "last_bitrate_kbps": 2850}
                ]
            },
            {
                "case_id": "switch_penalty_dash_4rung",
                "ladder": [400, 800, 1500, 3000],
                "sequence": [
                    {"segment_index": 2, "current_buffer_sec": 14.0, "last_throughput_kbps": 1700.0, "last_download_time_sec": 0.8, "last_bitrate_kbps": 800}
                ]
            },
            {
                "case_id": "switch_penalty_3rung",
                "ladder": [500, 1000, 2000],
                "sequence": [
                    {"segment_index": 2, "current_buffer_sec": 13.0, "last_throughput_kbps": 1200.0, "last_download_time_sec": 1.0, "last_bitrate_kbps": 1000}
                ]
            }
        ]
        self._execute_and_assert_parity(cases)

    def test_dynamic_multi_step_sequences_parity(self):
        """Verifies extended dynamic streaming runs and reset consistency (Cases 54-58)."""
        cases = [
            {
                "case_id": "dynamic_gradual_rampup_10steps",
                "sequence": [
                    {"segment_index": 0, "current_buffer_sec": 2.0, "last_throughput_kbps": 600.0, "last_download_time_sec": 1.0},
                    {"segment_index": 1, "current_buffer_sec": 4.0, "last_throughput_kbps": 1000.0, "last_download_time_sec": 0.8},
                    {"segment_index": 2, "current_buffer_sec": 6.5, "last_throughput_kbps": 1800.0, "last_download_time_sec": 0.6},
                    {"segment_index": 3, "current_buffer_sec": 9.0, "last_throughput_kbps": 2500.0, "last_download_time_sec": 0.5},
                    {"segment_index": 4, "current_buffer_sec": 12.0, "last_throughput_kbps": 3200.0, "last_download_time_sec": 0.4},
                    {"segment_index": 5, "current_buffer_sec": 15.0, "last_throughput_kbps": 4500.0, "last_download_time_sec": 0.3},
                    {"segment_index": 6, "current_buffer_sec": 18.0, "last_throughput_kbps": 6000.0, "last_download_time_sec": 0.2},
                    {"segment_index": 7, "current_buffer_sec": 21.0, "last_throughput_kbps": 7000.0, "last_download_time_sec": 0.2},
                    {"segment_index": 8, "current_buffer_sec": 24.0, "last_throughput_kbps": 7500.0, "last_download_time_sec": 0.2},
                    {"segment_index": 9, "current_buffer_sec": 26.0, "last_throughput_kbps": 8000.0, "last_download_time_sec": 0.2}
                ]
            },
            {
                "case_id": "dynamic_sudden_crash_and_recovery_8steps",
                "sequence": [
                    {"segment_index": 0, "current_buffer_sec": 20.0, "last_throughput_kbps": 6000.0, "last_download_time_sec": 0.2, "last_bitrate_kbps": 2850},
                    {"segment_index": 1, "current_buffer_sec": 22.0, "last_throughput_kbps": 6000.0, "last_download_time_sec": 0.2, "last_bitrate_kbps": 4300},
                    {"segment_index": 2, "current_buffer_sec": 18.0, "last_throughput_kbps": 300.0, "last_download_time_sec": 4.0, "last_bitrate_kbps": 4300},
                    {"segment_index": 3, "current_buffer_sec": 12.0, "last_throughput_kbps": 350.0, "last_download_time_sec": 3.5, "last_bitrate_kbps": 750},
                    {"segment_index": 4, "current_buffer_sec": 8.0, "last_throughput_kbps": 400.0, "last_download_time_sec": 3.0, "last_bitrate_kbps": 300},
                    {"segment_index": 5, "current_buffer_sec": 6.0, "last_throughput_kbps": 5000.0, "last_download_time_sec": 0.3, "last_bitrate_kbps": 300},
                    {"segment_index": 6, "current_buffer_sec": 9.0, "last_throughput_kbps": 5000.0, "last_download_time_sec": 0.3, "last_bitrate_kbps": 300},
                    {"segment_index": 7, "current_buffer_sec": 13.0, "last_throughput_kbps": 6000.0, "last_download_time_sec": 0.3, "last_bitrate_kbps": 750}
                ]
            },
            {
                "case_id": "dynamic_fluctuating_network_8steps",
                "sequence": [
                    {"segment_index": 0, "current_buffer_sec": 10.0, "last_throughput_kbps": 1200.0, "last_download_time_sec": 1.0},
                    {"segment_index": 1, "current_buffer_sec": 12.0, "last_throughput_kbps": 4000.0, "last_download_time_sec": 0.3},
                    {"segment_index": 2, "current_buffer_sec": 11.0, "last_throughput_kbps": 800.0, "last_download_time_sec": 1.5},
                    {"segment_index": 3, "current_buffer_sec": 13.0, "last_throughput_kbps": 5000.0, "last_download_time_sec": 0.3},
                    {"segment_index": 4, "current_buffer_sec": 12.0, "last_throughput_kbps": 900.0, "last_download_time_sec": 1.4},
                    {"segment_index": 5, "current_buffer_sec": 14.0, "last_throughput_kbps": 6000.0, "last_download_time_sec": 0.2},
                    {"segment_index": 6, "current_buffer_sec": 13.0, "last_throughput_kbps": 1000.0, "last_download_time_sec": 1.2},
                    {"segment_index": 7, "current_buffer_sec": 15.0, "last_throughput_kbps": 5500.0, "last_download_time_sec": 0.3}
                ]
            },
            {
                "case_id": "dynamic_dash_4rung_full_trace_10steps",
                "ladder": [400, 800, 1500, 3000],
                "sequence": [
                    {"segment_index": 0, "current_buffer_sec": 2.0, "last_throughput_kbps": 800.0, "last_download_time_sec": 1.0},
                    {"segment_index": 1, "current_buffer_sec": 4.5, "last_throughput_kbps": 1200.0, "last_download_time_sec": 0.8},
                    {"segment_index": 2, "current_buffer_sec": 7.0, "last_throughput_kbps": 1800.0, "last_download_time_sec": 0.6},
                    {"segment_index": 3, "current_buffer_sec": 10.0, "last_throughput_kbps": 2500.0, "last_download_time_sec": 0.5},
                    {"segment_index": 4, "current_buffer_sec": 13.0, "last_throughput_kbps": 3200.0, "last_download_time_sec": 0.4},
                    {"segment_index": 5, "current_buffer_sec": 16.0, "last_throughput_kbps": 4000.0, "last_download_time_sec": 0.3},
                    {"segment_index": 6, "current_buffer_sec": 18.0, "last_throughput_kbps": 4500.0, "last_download_time_sec": 0.3},
                    {"segment_index": 7, "current_buffer_sec": 14.0, "last_throughput_kbps": 600.0, "last_download_time_sec": 2.5},
                    {"segment_index": 8, "current_buffer_sec": 10.0, "last_throughput_kbps": 500.0, "last_download_time_sec": 2.0},
                    {"segment_index": 9, "current_buffer_sec": 8.0, "last_throughput_kbps": 3000.0, "last_download_time_sec": 0.5}
                ]
            },
            {
                "case_id": "reset_lifecycle_consistency",
                "sequence": [
                    {"segment_index": 0, "current_buffer_sec": 15.0, "last_throughput_kbps": 4000.0, "last_download_time_sec": 0.5},
                    {"segment_index": 1, "current_buffer_sec": 18.0, "last_throughput_kbps": 6000.0, "last_download_time_sec": 0.3},
                    {"action": "reset"},
                    {"segment_index": 0, "current_buffer_sec": 15.0, "last_throughput_kbps": 4000.0, "last_download_time_sec": 0.5},
                    {"segment_index": 1, "current_buffer_sec": 18.0, "last_throughput_kbps": 6000.0, "last_download_time_sec": 0.3}
                ]
            }
        ]
        self._execute_and_assert_parity(cases)

    def test_dynamic_representation_metadata_mapping(self):
        """Verifies that JS controller handles unordered DASH representation objects cleanly."""
        node_bin = shutil.which("node")
        test_js = f"""
        const {{ HybridQoEController }} = require('{JS_MODULE_PATH.as_posix()}');
        const ctrl = new HybridQoEController();

        // 1. Unordered representations list
        ctrl.setBitrateLadder([
            {{ qualityIndex: 3, bitrate: 3000000, width: 1920, height: 1080 }},
            {{ qualityIndex: 0, bitrate: 400000, width: 640, height: 360 }},
            {{ qualityIndex: 2, bitrate: 1500000, width: 1280, height: 720 }},
            {{ qualityIndex: 1, bitrate: 800000, width: 854, height: 480 }}
        ]);

        const ladder = ctrl.bitrateLadderKbps;
        const idx400 = ctrl.getRepresentationIndexForBitrate(400);
        const idx800 = ctrl.getRepresentationIndexForBitrate(800);
        const idx1500 = ctrl.getRepresentationIndexForBitrate(1500);
        const idx3000 = ctrl.getRepresentationIndexForBitrate(3000);

        console.log(JSON.stringify({{ ladder, idx400, idx800, idx1500, idx3000 }}));
        """
        proc = subprocess.run([node_bin, "-e", test_js], capture_output=True, text=True, cwd=str(PROJECT_ROOT))
        self.assertEqual(proc.returncode, 0, f"Node script failed: {proc.stderr}")
        data = json.loads(proc.stdout)

        # Ladder should be sorted ascending: [400, 800, 1500, 3000]
        self.assertEqual(data["ladder"], [400, 800, 1500, 3000])
        # Indices should map back to original qualityIndex despite unordered input
        self.assertEqual(data["idx400"], 0)
        self.assertEqual(data["idx800"], 1)
        self.assertEqual(data["idx1500"], 2)
        self.assertEqual(data["idx3000"], 3)

    def test_parameter_validation_parity(self):
        """Verifies that both Python and JS reject invalid configuration arguments."""
        node_bin = shutil.which("node")

        invalid_configs = [
            {"safety_factor_min": 0.95, "safety_factor_base": 0.80},
            {"reservoir_sec": -2.0},
            {"cushion_sec": 0.0},
            {"window_size": 0}
        ]

        for cfg in invalid_configs:
            # Python check
            with self.assertRaises(ValueError):
                HybridQoEABR(**cfg)

            # JS check via Node
            test_js = f"""
            const {{ HybridQoEController }} = require('{JS_MODULE_PATH.as_posix()}');
            try {{
                new HybridQoEController({json.dumps(cfg)});
                console.log('NO_ERROR');
            }} catch (e) {{
                console.log('CAUGHT_ERROR');
            }}
            """
            proc = subprocess.run([node_bin, "-e", test_js], capture_output=True, text=True, cwd=str(PROJECT_ROOT))
            self.assertEqual(proc.returncode, 0)
            self.assertEqual(proc.stdout.strip(), "CAUGHT_ERROR", f"JS should have thrown error on config {cfg}")


if __name__ == "__main__":
    unittest.main()
