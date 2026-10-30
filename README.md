# QoE-Driven Adaptive Bitrate (ABR) Video Streaming Project

A Computer Networks project implementing, simulating, and evaluating Adaptive Bitrate (ABR) streaming algorithms with Quality of Experience (QoE) optimization purely in Python on Windows.

---

## 1. Project Background & Core Concepts

In modern video streaming (YouTube, Netflix, Twitch), network throughput fluctuates constantly due to Wi-Fi interference, cellular handoffs, and shared link congestion.

### What is Adaptive Bitrate (ABR)?
Instead of streaming a video at a single fixed quality, the video is sliced into small segments (e.g., 2-second chunks) and encoded at multiple quality tiers (e.g., 300, 750, 1200, 1850, 2850, 4300 kbps). Before downloading each segment, an **ABR algorithm** selects the best bitrate to balance visual clarity against playback freezing.

### What is Quality of Experience (QoE)?
A good streaming experience requires balancing three competing objectives:
1. **High Visual Quality**: Higher video bitrates provide clearer pictures ($\uparrow$ positive utility).
2. **Zero Freezing / Rebuffering**: Video stalls frustrate users heavily ($\downarrow$ heavy penalty).
3. **Smooth Playback Transitions**: Rapid quality switching causes visual flickering ($\downarrow$ switching penalty).

### Standard Academic QoE Formula
$$\text{QoE} = \sum_{k=1}^K q(R_k) - \beta \sum_{k=1}^K T_k - \gamma \sum_{k=1}^{K-1} |q(R_{k+1}) - q(R_k)|$$

Where:
- $q(R_k) = R_k / 1000$ (Bitrate utility in Mbps)
- $T_k$: Freezing / stall duration incurred during segment $k$ (in seconds)
- $|q(R_{k+1}) - q(R_k)|$: Bitrate switch magnitude between consecutive segments (in Mbps)
- $\alpha = 1.0, \beta = 4.3, \gamma = 1.0$ (Default academic weights in `src/config.py`)

---

## 2. Directory Structure

```text
CN-ABR-Project/
├── README.md                      # Project documentation, concepts, and evaluation guide
├── main.py                        # Unified CLI entry point (simulations, batch, encode, & server)
├── requirements.txt               # Dependencies (matplotlib, numpy, pytest, Flask)
├── .gitignore                     # Git ignore rules for Python, plots, and CSV logs
│
├── reports/                       # Formal technical evaluation reports (Stage 10 & 11)
│   ├── final_evaluation_report.md # Comprehensive Stage 10/11 academic evaluation report
│   └── submission_checklist.md    # Pre-submission audit checklist & 5-minute faculty demo guide
│
├── media/                         # Raw source video assets
│   └── input.mp4                  # 1080p, 60fps, 30s H.264/AAC benchmark video
│
├── templates/                     # Flask HTML templates (Stage 8B)
│   └── player.html                # Interactive MPEG-DASH streaming player & telemetry dashboard
│
├── static/                        # Web server static files (Stage 7 & 8)
│   ├── css/
│   │   └── player.css             # Dark modern streaming player styles
│   ├── js/
│   │   ├── hybrid-abr.js          # JavaScript port of HybridQoEController (Stage 9A/9B)
│   │   ├── player.js              # dash.js player controller, telemetry listeners, & switch logger
│   │   └── dash.all.min.js        # Cached local fallback for dash.js v4.7.4
│   └── dash/                      # Multi-bitrate MPEG-DASH output stream
│       ├── stream.mpd             # XML Media Presentation Description manifest
│       ├── init-stream0.m4s       # Initialization segment (360p video)
│       ├── init-stream1.m4s       # Initialization segment (480p video)
│       ├── init-stream2.m4s       # Initialization segment (720p video)
│       ├── init-stream3.m4s       # Initialization segment (1080p video)
│       ├── init-stream4.m4s       # Initialization segment (AAC audio)
│       └── chunk-stream*.m4s      # 76 media chunks (15 chunks x 4 video tiers + 16 audio chunks)
│
├── data/
│   └── traces/                    # Bandwidth trace datasets
│       ├── README.md              # Trace scenarios documentation
│       ├── synthetic_stable_high.csv
│       ├── synthetic_stable_low.csv
│       ├── synthetic_fluctuating.csv
│       ├── synthetic_gradual_degradation.csv
│       └── synthetic_sudden_drop_recovery.csv
│
├── src/                           # Core source code
│   ├── __init__.py                # Package declaration
│   ├── config.py                  # Simulation constants (ladder, buffer targets, QoE weights)
│   │
│   ├── algorithms/                # ABR Decision Logic (Stage 4)
│   │   ├── __init__.py
│   │   ├── base.py                # Abstract Base Class (BaseABR)
│   │   ├── throughput_based.py    # Rate-based ABR (Harmonic mean + safety margin)
│   │   ├── buffer_based.py        # Buffer-based ABR (BBA with anti-oscillation hysteresis)
│   │   └── hybrid.py              # Proposed QoE-driven hybrid algorithm (Buffer + Rate + Uncertainty)
│   │
│   ├── simulator/                 # Discrete-Time Streaming Simulator
│   │   ├── __init__.py
│   │   ├── network.py             # CSV trace loader & network condition simulation (Stage 2)
│   │   ├── player.py              # Video playback buffer & stall model (Stage 3 & 6)
│   │   ├── experiment.py          # End-to-end single experiment simulation runner (Stage 5)
│   │   ├── batch.py               # 15-run matrix batch evaluation pipeline (Stage 6)
│   │   └── visualization.py       # Automated Matplotlib comparison chart generation (Stage 6)
│   │
│   ├── media/                     # Video Transcoding & DASH Packaging (Stage 7)
│   │   ├── __init__.py
│   │   └── encode_dash.py         # Multi-representation FFmpeg DASH encoder & validator
│   │
│   ├── web/                       # Flask HTTP Streaming Server (Stage 8A & 8B)
│   │   ├── __init__.py
│   │   └── server.py              # Local HTTP server with CORS, health check, player, & Range support
│   │
│   └── metrics/                   # Performance & Evaluation
│       ├── __init__.py
│       └── qoe.py                 # QoE formulation & session metrics calculator (Stage 6)
│
├── tests/                         # Automated Tests (112 total passing tests)
│   ├── __init__.py
│   ├── test_smoke.py              # Unit tests for config, algorithms, network, player, QoE (42 tests)
│   ├── test_experiment.py         # Integration tests for experiment engine & anti-leakage (10 tests)
│   ├── test_batch.py              # Tests for batch pipeline, metric semantics, and plots (7 tests)
│   ├── test_encode_dash.py        # Unit tests for DASH encoder, ladder selection, & probe (16 tests)
│   ├── test_web_server.py         # Unit tests for Flask DASH server, routes, MIME, player, & security (15 tests)
│   ├── test_hybrid_parity.py      # Cross-language parity suite between Python & JS Hybrid ABR (10 tests)
│   └── test_hybrid_browser_integration.py # Headless browser integration tests for Stage 9B (12 tests)
│
└── results/                       # Simulation outputs (logs, graphs, and CSVs)
    ├── batch_summary.csv          # Consolidated 15-experiment summary table
    ├── batch_runs/                # Individual per-run segment CSVs
    ├── plots/                     # Generated performance comparison figures (PNG)
    │   ├── 1_average_bitrate_comparison.png
    │   ├── 2_rebuffering_comparison.png
    │   ├── 3_qoe_comparison.png
    │   ├── 4_bitrate_over_time_fluctuating.png
    │   ├── 5_buffer_occupancy_fluctuating.png
    │   └── 6_switching_comparison.png
    └── final_evaluation/          # Fresh Stage 10 reproducible batch artifacts
```

---

## 3. Metrics Standardization & Semantics (Stage 6)

In Stage 6, session metrics and accounting were rigorously standardized:

### 1. Startup Delay vs. Playback Rebuffering
- **`startup_delay_sec`**: The initial time spent downloading segment 0 before the player displays the first frame of video.
- **`playback_rebuffer_time_sec`**: Freezing / stall time that occurs *after* playback has already started (due to buffer starvation).
- **`total_rebuffer_time_sec`**: Preserved as `startup_delay_sec + playback_rebuffer_time_sec` for backward compatibility.
- **`rebuffer_ratio`**: Normalized freeze ratio experienced during the active viewing session:
  $$\text{rebuffer\_ratio} = \frac{\text{playback\_rebuffer\_time\_sec}}{\text{total\_playback\_time\_sec} + \text{playback\_rebuffer\_time\_sec}}$$

### 2. Selected vs. Delivered Bitrate
- **`avg_selected_bitrate_kbps`**: The average bitrate requested by the algorithm.
- **`avg_delivered_bitrate_kbps`**: The average bitrate of chunks successfully received before connection timeout.

### 3. Smoothness & Switching
- **`bitrate_switches_count`**: Total number of quality changes between consecutive segments.
- **`total_switch_magnitude_kbps`**: Sum of absolute quality differences $\sum |R_{k+1} - R_k|$.
- **`avg_switch_magnitude_kbps`**: Average step size per switch.

---

## 4. Batch Evaluation & Empirical Findings (Stage 6)

The batch evaluation pipeline runs a full $3 \times 5 = 15$ experiment matrix (3 algorithms across 5 synthetic traces for 30 segments each).

### Summary Table (`results/batch_summary.csv`)

| Trace | Algorithm | Avg Delivered Bitrate (kbps) | Startup Delay (s) | Playback Rebuffer (s) | Rebuffer Ratio | Switches | Switch Magnitude (kbps) | Avg Buffer (s) | QoE Score |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Fluctuating** | Throughput | 2331.7 | 0.194 | 0.000 | 0.00% | 6 | 6,550 | 9.85 | **62.57** |
| | Buffer (BBA) | 2471.7 | 0.194 | 0.000 | 0.00% | 10 | 16,250 | 12.56 | 57.07 |
| | Proposed Hybrid | 1758.3 | 0.194 | 0.000 | 0.00% | 10 | 7,500 | 17.04 | 44.42 |
| **Gradual Degradation** | Throughput | 3731.7 | 0.086 | 0.000 | 0.00% | 2 | 5,450 | 11.12 | **106.13** |
| | Buffer (BBA) | 3311.7 | 0.086 | 0.000 | 0.00% | 5 | 4,000 | 18.28 | 94.98 |
| | Proposed Hybrid | 3185.0 | 0.086 | 0.000 | 0.00% | 6 | 5,450 | 18.61 | 89.73 |
| **Stable High** | Throughput | 4166.7 | 0.100 | 0.000 | 0.00% | 1 | 4,000 | 10.61 | **120.57** |
| | Buffer (BBA) | 3281.7 | 0.100 | 0.000 | 0.00% | 4 | 4,000 | 18.15 | 94.02 |
| | Proposed Hybrid | 3281.7 | 0.100 | 0.000 | 0.00% | 5 | 4,000 | 18.16 | 94.02 |
| **Stable Low** | Throughput | 420.0 | 0.667 | 0.000 | 0.00% | 2 | 900 | 13.93 | 8.83 |
| | Buffer (BBA) | 720.0 | 0.667 | 0.000 | 0.00% | 5 | 2,250 | 8.03 | **16.48** |
| | Proposed Hybrid | 450.0 | 0.667 | 0.000 | 0.00% | 2 | 900 | 15.94 | 9.73 |
| **Sudden Drop & Recovery** | Throughput | 3230.0 | 0.100 | **3.500** | **6.35%** | 5 | 8,000 | 6.83 | 73.42 |
| | Buffer (BBA) | 3200.0 | 0.100 | **0.000** | **0.00%** | 5 | 6,450 | 16.68 | **89.12** |
| | Proposed Hybrid | 3163.3 | 0.100 | **0.000** | **0.00%** | 6 | 7,550 | 16.83 | **86.92** |

---

## 5. Visualizations (`results/plots/`)

Stage 6 automatically creates 6 publication-ready figures:

1. **`1_average_bitrate_comparison.png`**: Grouped bar chart comparing delivered bitrates across all 5 traces.
2. **`2_rebuffering_comparison.png`**: Highlights stall resistance; shows Throughput-based rebuffering on sudden drop while BBA and Hybrid maintain 0.0s stalls.
3. **`3_qoe_comparison.png`**: Composite QoE benchmark across all scenarios.
4. **`4_bitrate_over_time_fluctuating.png`**: Segment-by-segment bitrate trajectory showing quality changes on fluctuating bandwidth.
5. **`5_buffer_occupancy_fluctuating.png`**: Client buffer occupancy over time with Reservoir ($5\text{s}$) and Cushion Target ($15\text{s}$) reference lines.
6. **`6_switching_comparison.png`**: Switching frequency comparison across algorithms.

---

## 6. Real MPEG-DASH Video Encoding (Stage 7)

### What is MPEG-DASH?
**MPEG-DASH** (Dynamic Adaptive Streaming over HTTP, ISO/IEC 23009-1) is the international industry standard for multimedia streaming:
1. The video is pre-encoded into multiple bitrate representations (360p, 480p, 720p, 1080p).
2. Each stream is segmented into short, independent chunks (2.0 seconds long).
3. An XML manifest file called the **Media Presentation Description (`.mpd`)** indexes all representations and segment URLs.
4. The client's JavaScript video player (such as **dash.js**) reads the `.mpd`, continuously estimates network conditions, and dynamically requests chunks from the appropriate bitrate tier.

### Encoding Architecture & Implementation (`src/media/encode_dash.py`)
1. **ffprobe Inspection**: Probes source resolution (1920x1080), frame rate (60 fps), duration (30s), and audio codec (AAC).
2. **Anti-Upscaling Ladder Selection**:
   - `Representation 0`: 360p (640x360 @ 400 kbps, max 440 kbps, bufsize 800 kbps)
   - `Representation 1`: 480p (854x480 @ 800 kbps, max 880 kbps, bufsize 1600 kbps)
   - `Representation 2`: 720p (1280x720 @ 1500 kbps, max 1650 kbps, bufsize 3000 kbps)
   - `Representation 3`: 1080p (1920x1080 @ 3000 kbps, max 3300 kbps, bufsize 6000 kbps)
   - `Representation 4`: Audio (48 kHz stereo AAC @ 128 kbps)
3. **GOP & Keyframe Alignment**:
   - For a 2.0-second chunk duration at 60 fps, the GOP interval is strictly set to $60 \times 2 = 120$ frames (`-g 120 -keyint_min 120 -sc_threshold 0`).
   - Every representation has instantaneous decoder refresh (IDR) keyframes aligned at the exact same presentation timestamps, enabling seamless bitrate switching without visual artifacts or decoder stalls.

```powershell
# Run the DASH encoder
py -m src.media.encode_dash --input media/input.mp4 --output static/dash --segment-duration 2
```

---

## 7. Interactive MPEG-DASH Browser Player (Stage 8A & 8B)

The project includes a complete browser-based video streaming demonstration powered by **Flask** and **dash.js v4.7.4**.

### Player Architecture & Features (Stage 8B & 8C)
- **Modern Streaming Dashboard UI**: Sleek, dark-mode streaming player with high-contrast status cards, buffer occupancy progress bars, and real-time telemetry.
- **Dynamic Representation Discovery**: When the stream initializes, the player queries dash.js for available representations (`player.getBitrateInfoListFor('video')`) and dynamically populates the quality selection dropdown (360p, 480p, 720p, 1080p).
- **Auto vs. Fixed Quality Switching**:
  - **Auto**: Enables dynamic dash.js ABR adaptation (`player.updateSettings({ streaming: { abr: { autoSwitchBitrate: { video: true } } } })`).
  - **Manual Tier**: Disables auto ABR and locks playback to the user's chosen representation (`player.setQualityFor('video', index)`).
- **Live Playback Telemetry**:
  - **Active Resolution**: Real rendered video dimensions (e.g. `1280x720`).
  - **Delivered Bitrate**: Active representation bandwidth (e.g. `1.50 Mbps`).
  - **Buffer Level**: Real-time buffer occupancy in seconds via `player.getBufferLength('video')`.
  - **Playback State**: Badged indicators for `Playing`, `Paused`, `Buffering`, `Ended`, and `Error`.

### Live Visualizations (Stage 8C)
- **HTML5 Canvas Telemetry Charts**: Dependency-free, crisp Retina-scaled time series charts updated every 500 ms:
  - **Bitrate & Quality Over Time**: Displays active bitrate trajectory across playback time, overlaid with dashed reference lines for each encoding tier (360p, 480p, 720p, 1080p).
  - **Buffer Occupancy Over Time**: Displays real-time client buffer length in seconds with a safety reference threshold guideline at 10.0s.
  - Interactive tabs switch cleanly between charts with dedicated legend indicators.

### Session Statistics & Metric Definitions (Stage 8C)
- **Startup Delay**: Elapsed time between the user's initial play request (`loadstart` / `play`) and the first presented video frame (`playing`). **Explicitly separated from playback rebuffering** (initial loading is never counted as a stall).
- **Playback Time**: Total active media render time in seconds.
- **Stall Count & Total Rebuffer Duration**: Number of freezing events and cumulative stall duration occurring strictly **post-startup** during active playback.
- **Rebuffer Ratio**:
  $$\text{Rebuffer Ratio} = \frac{T_{\text{rebuffer}}}{T_{\text{playback}} + T_{\text{rebuffer}}}$$
- **Time-Weighted Average Bitrate**: Average bandwidth of segments delivered during active playback.
- **Switch Count & Cumulative Switch Magnitude**: Count of confirmed quality transitions and total bitrate step change $\sum |\Delta R_k|$ in kbps.
- **Academic Session QoE Score**: Real-time calculation matching the project's standard formula:
  $$\text{QoE} = \alpha \sum \frac{R_k}{1000} - \beta \sum T_k - \gamma \sum \frac{|\Delta R_k|}{1000} \quad (\alpha=1.0, \beta=4.3, \gamma=1.0)$$

### Quality Switch Timeline: Decisions vs. Outcomes
- Clearly separates:
  1. **Requested Decisions** (`dashjs.MediaPlayer.events.QUALITY_CHANGE_REQUESTED`): Triggered when an ABR rule or manual user action initiates a representation switch.
  2. **Rendered Outcomes** (`dashjs.MediaPlayer.events.QUALITY_CHANGE_RENDERED`): Triggered only when the new chunk begins displaying on screen, recording old vs new quality, switch magnitude, and buffer level at render time.

### Browser Session Data Export
- Direct client-side export to **CSV** and **JSON** formats via dedicated buttons on the player dashboard:
  - **CSV Export** (`cn_abr_browser_session_<timestamp>.csv`): Contains session metadata header, time-series telemetry rows (`timestamp_iso, media_time_sec, buffer_level_sec, rendered_bitrate_kbps, rendered_resolution, playback_state, abr_mode`), and switch events.
  - **JSON Export** (`cn_abr_browser_session_<timestamp>.json`): Structured hierarchical object containing session metadata, performance summary, switch timeline events, and raw telemetry samples.
  - Completely independent from simulation engine logs.
- **Resilient Delivery**: Loads pinned dash.js v4.7.4 from CDN with an automatic fallback to the local cached script (`static/js/dash.all.min.js`) if internet access is unavailable.

---

## 8. Custom Hybrid ABR Algorithm in dash.js Web Player (Stage 9A & 9B)

Stage 9 ports our proposed QoE-driven Hybrid ABR algorithm to modern client-side JavaScript (`static/js/hybrid-abr.js`) and fully integrates it into the interactive `dash.js` browser player (`templates/player.html`, `static/js/player.js`).

### 1. Parity-Tested JavaScript Port (`static/js/hybrid-abr.js`)
- Fully autonomous `HybridQoEController` reproducing the mathematical decision dynamics of the reference Python `HybridQoEABR`:
  - **Throughput Estimation**: Harmonic mean over a sliding window ($N=5$) of past segment downloads.
  - **Volatility Awareness**: Sample coefficient of variation ($\text{CV} = \sigma / \mu$) discounting the base safety factor ($\alpha_{\text{base}} = 0.90 \to \alpha_{\text{eff}} \ge 0.60$).
  - **Buffer Headroom**: Linear capacity scaling between Reservoir ($5.0\text{s}$) and Cushion Target ($15.0\text{s}$).
  - **Drain Feasibility**: Strictly rejects representations whose expected download time exceeds available buffer minus safety margin ($0.5\text{s}$).
  - **Cautious Step-Up & Rapid Step-Down**: Enforces $\le +1$ tier step-up with $30\%$ cushion headroom requirement, while allowing rapid multi-tier down-switching during throughput collapse.
  - **Objective Function**: Balances normalized quality utility against switching penalties ($\lambda=0.5$).
- **Certified 100% Parity**: Validated against Python over 58 deterministic state vectors with 0 decision mismatches (`tests/test_hybrid_parity.py`).

### 2. Three Mutually Exclusive Adaptation Policies (Stage 9B)
The player dashboard features an **ABR Controller Mode** selector (`#abrModeSelect`):
1. **Auto — dash.js Built-in ABR**:
   - Enables dash.js native internal adaptation rules (`streaming.abr.autoSwitchBitrate.video: true`).
   - Serves as the real-world baseline.
2. **Custom Hybrid ABR (Stage 9 Policy)**:
   - Disables dash.js built-in ABR rules (`streaming.abr.autoSwitchBitrate.video: false`).
   - Listens to `FRAGMENT_LOADING_COMPLETED` events for video media chunks.
   - Computes segment throughput strictly from past completed downloads ($T_{k-1}$), queries buffer occupancy ($B_{k-1}$), and dispatches the optimal representation via `player.setQualityFor('video', index)`.
   - Isolates controller state (`reset()`) upon mode transition to prevent cross-run contamination.
3. **Manual Tier (User-Pinned Quality)**:
   - Disables auto ABR and locks playback strictly to user-selected representation index (360p, 480p, 720p, or 1080p).

### 3. Key Integration Mechanisms
- **Strict Past-Only Causality**: Decisions for segment $k$ only observe completed download throughput $T_{k-1}$ and client buffer level $B_{k-1}$ at decision time.
- **Duplicate Decision Suppression**: When the controller calculates that the currently requested representation remains optimal, the decision is logged in the timeline (`HYBRID_DECISION`), but redundant `player.setQualityFor()` dispatches are suppressed, preserving dash.js buffer pipelines.
- **Decoupled Decision vs. Outcome Logging**:
  - `HYBRID_DECISION`: Triggered when the hybrid controller selects a quality tier (logging estimated throughput, CV, and buffer).
  - `QUALITY_CHANGE_REQUESTED`: Triggered when a new representation is requested by dash.js.
  - `QUALITY_CHANGE_RENDERED`: Triggered only when the new video representation actively renders to screen.
- **Active Mode Telemetry & Exports**: Client-side CSV and JSON exports serialize the active ABR mode (`abr_mode` column and metadata) and all hybrid decision entries.

---

## 9. Final Experimental Evaluation & Results (Stage 10)

Stage 10 provides a comprehensive, defensible evaluation of the streaming system across both the discrete-event Python simulation and the interactive browser testbed.

A complete formal evaluation report is published at [`reports/final_evaluation_report.md`](reports/final_evaluation_report.md).

### 1. Simulation Batch Findings Across 5 Traces
The reproducible batch evaluation campaign was rerun and preserved under `results/final_evaluation/batch_summary.csv`:

| Trace Scenario | Algorithm | Avg Delivered Bitrate (kbps) | Startup Delay (s) | Playback Rebuffer (s) | Rebuffer Ratio (%) | Switches (Count) | Switch Magnitude (kbps) | Avg Buffer (s) | Academic QoE Score |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Fluctuating** | Throughput-Based | 2331.7 | 0.194 | 0.000 | 0.00% | 6 | 6550.0 | 9.85 | **62.57** |
| | Buffer-Based (BBA) | 2471.7 | 0.194 | 0.000 | 0.00% | 10 | 16250.0 | 12.56 | 57.07 |
| | Proposed Hybrid | 1758.3 | 0.194 | 0.000 | 0.00% | 10 | 7500.0 | 17.04 | 44.42 |
| **Gradual Degradation** | Throughput-Based | 3731.7 | 0.086 | 0.000 | 0.00% | 2 | 5450.0 | 11.12 | **106.13** |
| | Buffer-Based (BBA) | 3311.7 | 0.086 | 0.000 | 0.00% | 5 | 4000.0 | 18.28 | 94.98 |
| | Proposed Hybrid | 3185.0 | 0.086 | 0.000 | 0.00% | 6 | 5450.0 | 18.61 | 89.73 |
| **Stable High** | Throughput-Based | 4166.7 | 0.100 | 0.000 | 0.00% | 1 | 4000.0 | 10.61 | **120.57** |
| | Buffer-Based (BBA) | 3281.7 | 0.100 | 0.000 | 0.00% | 4 | 4000.0 | 18.15 | 94.02 |
| | Proposed Hybrid | 3281.7 | 0.100 | 0.000 | 0.00% | 5 | 4000.0 | 18.16 | 94.02 |
| **Stable Low** | Throughput-Based | 420.0 | 0.667 | 0.000 | 0.00% | 2 | 900.0 | 13.93 | 8.83 |
| | Buffer-Based (BBA) | 720.0 | 0.667 | 0.000 | 0.00% | 5 | 2250.0 | 8.03 | **16.48** |
| | Proposed Hybrid | 450.0 | 0.667 | 0.000 | 0.00% | 2 | 900.0 | 15.94 | 9.73 |
| **Sudden Drop & Recovery** | Throughput-Based | 3230.0 | 0.100 | **3.500** | **6.35%** | 5 | 8000.0 | 6.83 | 73.42 |
| | Buffer-Based (BBA) | 3200.0 | 0.100 | **0.000** | **0.00%** | 5 | 6450.0 | 16.68 | **89.12** |
| | Proposed Hybrid | 3163.3 | 0.100 | **0.000** | **0.00%** | 6 | 7550.0 | 16.83 | **86.92** |

### 2. Evidence-Based Observations
- **Stall Resistance Under Abrupt Collapse**: When available bandwidth drops from 5000 kbps to 200 kbps, Throughput-Based ABR experiences estimation lag and incurs **3.500s of playback rebuffering** (6.35% rebuffer ratio). In contrast, both **Buffer-Based ABR** and the **Proposed Hybrid ABR** achieve **0.000s rebuffering** (0.00% rebuffer ratio) through buffer drain checks and emergency down-switching.
- **Oscillation Suppression Under Volatility**: In fluctuating bandwidth, Hybrid detects volatility ($CV \approx 0.35-0.45$) and scales back effective bandwidth headroom, cutting cumulative switch magnitude down to 7,500 kbps (over $53\%$ smoother than BBA's 16,250 kbps).
- **Benign Channel Saturation**: In stable high-bandwidth networks, Throughput-Based ABR reaches the top 4300 kbps tier with 1 switch, yielding the highest QoE score ($120.57$).

### 3. Metric Consistency & Non-Comparability Notice
Simulation and browser metrics cannot be merged into a single table:
- **Bitrate Ladders Differ**: Simulator uses 6 synthetic tiers `[300..4300]` kbps; browser player uses 4 FFmpeg-encoded tiers `[400..3000]` kbps.
- **Startup Delay vs. Stall Accounting**: Simulator counts segment 0 fetch time as startup delay and includes it in total stall penalties for legacy compatibility. The browser player strictly separates initial loading from post-startup freezes.
- **Network Dynamics**: Simulator uses deterministic piecewise-linear trace replays; browser runs over real HTTP network sockets subject to browser event loop scheduling and OS TCP stacks.

### 4. Reproducible Browser Evaluation Protocol
To evaluate adaptation behavior in the browser player:
1. Start the Flask server: `py main.py --serve`.
2. Open Chrome/Edge at `http://127.0.0.1:5000/player`.
3. Open DevTools (`F12`), check **Disable Cache** under the Network tab.
4. For each mode (`Auto`, `Custom Hybrid ABR`, `Manual Tier`):
   - Hard reload (`Ctrl+F5`) between runs to isolate session state.
   - Select the target adaptation mode.
   - Apply any optional DevTools throttling profile. Note: Chrome DevTools throttling uses token-bucket limiting and does not replay dynamic CSV trace schedules.
   - Play the 30-second benchmark stream.
   - Inspect the **Quality Switch Timeline** to verify decisions (`HYBRID_DECISION`) vs. rendered outcomes (`QUALITY_CHANGE_RENDERED`).
   - Export session telemetry via the **CSV** and **JSON** dashboard buttons.

---

## 10. How to Run (Windows / PowerShell)

### Run Single ABR Simulation Experiment
```powershell
py main.py --algorithm hybrid --trace synthetic_fluctuating.csv --segments 20
```

### Run Batch Evaluation (All 15 Experiments + Plots)
```powershell
py main.py --batch --segments 30 --output-dir results/final_evaluation
```

### Encode Source Video to MPEG-DASH
```powershell
py main.py --encode-dash
```

### Start Local Streaming Server & Player
```powershell
py main.py --serve
```

Once running, open your web browser (Google Chrome or Microsoft Edge recommended) and navigate to:
```text
http://127.0.0.1:5000/player
```

### Run All Automated Unit Tests
```powershell
py -m unittest discover -s tests -v
```

---

## 11. Test Suite Status

```text
Ran 116 tests in 2.702s
OK
```
- `tests/test_smoke.py`: 42 tests covering config, math, traces, buffer dynamics, and algorithm behavior.
- `tests/test_experiment.py`: 10 tests verifying the experiment engine, CSV serialization, and anti-leakage protection.
- `tests/test_batch.py`: 7 tests verifying batch runner matrix execution, CSV schema conformity, metric semantics, and plot generation.
- `tests/test_encode_dash.py`: 16 tests verifying DASH binary discovery, source probing, ladder filtering, command construction, error handling, and manifest verification.
- `tests/test_web_server.py`: 17 tests verifying Flask server health checks, manifest serving, segment delivery, MIME types, player page DOM elements, Stage 8C live canvas charts & stats grid, export buttons, static assets (`hybrid-abr.js`), persistent comparison API (`/api/experiments` GET/POST/DELETE), and directory traversal defense.
- `tests/test_hybrid_parity.py`: 10 tests certifying 100% mathematical and decision parity between the Python reference `HybridQoEABR` and JavaScript `HybridQoEController` across 58+ deterministic state vectors.
- `tests/test_hybrid_browser_integration.py`: 14 tests verifying Stage 9B mode selector DOM elements, comparison dashboard UI elements, style badge classes, script load order, dynamic ladder discovery, dash.js settings isolation, fragment filtering, duplicate suppression, telemetry export structures, and headless Node.js execution of all 3 algorithms (`ThroughputBasedController`, `BufferBasedController`, `HybridQoEController`).

---

## 12. Interactive Multi-Algorithm Comparison Dashboard & Mininet Testbed (Stage 12)

Stage 12 transforms the streaming testbed into a college-demonstration-ready, interactive ABR comparison platform with live Mininet network control and persistent evaluation analytics.

### 1. Three Distinct, Live-Selectable ABR Algorithms in Browser
The dashboard provides interactive selection cards and seamless policy switching between three distinct algorithms running on real segment downloads:
1. **Algorithm A: Throughput-Based ABR**
   - Estimates available network bandwidth using the **Harmonic Mean** of recent completed segments ($N=5$).
   - Budgets safe bandwidth with a safety factor $\alpha = 0.85$:
     $$R_k \le 0.85 \times \widehat{T}_k$$
   - Selects the highest representation tier fitting within this budget. Reactive to sudden capacity shifts.
2. **Algorithm B: Buffer-Based ABR (BBA)**
   - Ignores throughput spikes and adapts quality strictly as a piecewise function of client buffer occupancy:
     - **Reservoir ($B_{\text{res}} = 5.0\text{s}$)**: Forces lowest tier (360p) immediately to protect against stall.
     - **Cushion ($B_{\text{cush}} = 10.0\text{s}$)**: Linearly interpolates quality across the ladder up to $B_{\text{res}} + B_{\text{cush}} = 15.0\text{s}$.
     - **Upper Threshold ($15.0\text{s}$)**: Locks to highest tier (1080p).
     - **Hysteresis Band ($0.5\text{s}$)**: Requires buffer to cross step threshold $\pm 0.5\text{s}$ before switching to suppress oscillation.
3. **Algorithm C: QoE-Driven Hybrid ABR**
   - Synthesizes throughput harmonic mean with sample volatility discounting ($\text{CV} = \sigma / \mu$):
     $$\alpha_{\text{eff}} = \max(0.60, 0.90 - 0.30 \times \text{CV})$$
   - Scales capacity across the cushion, performs buffer drain feasibility checks ($B - \frac{S(R)}{\widehat{T}} > 0.5\text{s}$) to prevent stalls, and applies a switching penalty ($\lambda = 0.5$) to balance quality utility against visual flicker.

### 2. Live Mininet Network Testbed Integration
- **Topology Architecture**:
  ```text
  Browser (Client) ──> Gateway ──> Mininet h1 ──> Switch s1 ──> Mininet h2 ──> Flask DASH Server
  ```
- **Interactive Bandwidth Presets & Command Helper**:
  The dashboard features a live scenario selector that updates with exact copyable Mininet commands:
  - **5 Mbps** (High Capacity / 1080p target):
    `py s1.linksTo(h2)[0].intf2.config(bw=5)`
  - **1 Mbps** (Constrained Capacity / 480p target):
    `py s1.linksTo(h2)[0].intf2.config(bw=1)`
  - **500 kbps** (Severe Bottleneck / 360p target):
    `py s1.linksTo(h2)[0].intf2.config(bw=0.5)`
  - **Fluctuating** (Dynamic Bandwidth Profile):
    `py s1.linksTo(h2)[0].intf2.config(bw=1)` then toggle `bw=5`
  - A convenient **Copy** button copies the command directly to your clipboard for terminal execution.

### 3. Experiment Engine & Automated Evaluation
- **Experiment Controls**:
  - `Start Experiment`: Begins metric recording, starts elapsed timer, and initiates video playback.
  - `Stop Experiment`: Pauses playback, calculates final QoE metrics, posts summary to backend `/api/experiments`, and updates comparison tables/charts.
  - `Reset`: Seeks video to 0:00, clears active telemetry samples, and resets controller state without deleting stored comparisons.
  - `Run All 3 Algorithms`: Automated sequential batch runner evaluating Throughput $\to$ Buffer $\to$ Hybrid sequentially, logging each completed run automatically.
  - `Clear Results`: Calls `DELETE /api/experiments` to wipe comparison records.

### 4. Persistent Comparison Analytics & Side-by-Side Visual Charts
- **Flask REST API Persistence**:
  - `GET /api/experiments`: Retrieves completed experiment records from `results/browser_experiments.json`.
  - `POST /api/experiments`: Validates and appends completed experiment summary.
  - `DELETE /api/experiments`: Atomically clears comparison records.
  - **Survives page reloads and server restarts**.
- **Real-Time Comparative Canvas Charts**:
  - Four side-by-side bar charts rendering comparative results across all runs:
    1. **Academic QoE Score** (Higher is better)
    2. **Average Delivered Bitrate (kbps)**
    3. **Total Stall Duration (seconds)**
    4. **Quality Switches (Stability)**
  - Color-coded by algorithm (Blue = Throughput, Amber = Buffer, Green = Hybrid).

---


