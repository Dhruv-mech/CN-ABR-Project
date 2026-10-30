# Synthetic Bandwidth Traces

This directory contains synthetic network traces for evaluating Adaptive Bitrate (ABR) streaming algorithms in a reproducible software environment on Windows.

## Trace Descriptions

| File Name | Scenario | Average Bandwidth | Purpose in ABR Evaluation |
| :--- | :--- | :--- | :--- |
| `synthetic_stable_high.csv` | Fiber / high-speed home broadband | ~6.0 Mbps | Verifies that ABR algorithms can ramp up and sustain top 1080p video bitrates without unnecessary drops. |
| `synthetic_stable_low.csv` | Cellular edge / weak 3G signal | ~0.85 Mbps | Tests whether ABR algorithms stabilize at lower representations without triggering repeated rebuffering. |
| `synthetic_fluctuating.csv` | Congested shared Wi-Fi with bursty cross-traffic | 1.2 to 5.0 Mbps | Tests stability: evaluates whether the algorithm prevents erratic quality switches (visual flickering). |
| `synthetic_gradual_degradation.csv` | Vehicle traveling away from base station | 7.0 $\to$ 0.7 Mbps | Tests proactive down-switching: checks if ABR smoothly steps down before the buffer completely drains. |
| `synthetic_sudden_drop_recovery.csv` | Entering and exiting a highway tunnel | 6.0 $\to$ 0.5 $\to$ 5.5 Mbps | Tests resilience under acute stress: measures how quickly the algorithm detects drops and recovers upon exit. |

## CSV Format & Units

- **Format**: Comma-Separated Values (CSV).
- **Comments**: Lines beginning with `#` are treated as human-readable metadata comments and ignored by the parser.
- **Header**: `timestamp_sec,bandwidth_mbps`
  - `timestamp_sec`: Elapsed simulation time in seconds (float $\ge 0$, strictly increasing).
  - `bandwidth_mbps`: Channel bandwidth at this timestamp in megabits per second (Mbps).
