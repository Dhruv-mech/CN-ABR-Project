/**
 * MPEG-DASH Web Player Controller & Live Telemetry Dashboard (Stage 12)
 * Multi-Algorithm Comparison Dashboard & Live Mininet Testbed Integration
 * 
 * Manages:
 * 1. dash.js MediaPlayer lifecycle with dynamic representation ladder discovery.
 * 2. Three distinct, selectable ABR algorithms + dash.js Auto + Manual pinning:
 *    - Throughput-Based ABR (Harmonic mean estimation over N=5, safety factor 0.85)
 *    - Buffer-Based ABR (BBA) (Reservoir 5.0s, cushion 10.0s, hysteresis 0.5s)
 *    - Custom Hybrid ABR (Stage 9 QoE policy: volatility CV, buffer cushion, stall check, switch penalty)
 * 3. Real-time playback and network metrics (chunk duration, size, measured throughput, Mininet bandwidth).
 * 4. Enhanced buffering visualization (reservoir 5s, cushion 10s guidelines, stall alerts).
 * 5. Experiment state machine (IDLE, RUNNING, STOPPED, RUNNING_ALL) with live timer.
 * 6. Sequential "Run All 3 Algorithms" automated evaluation runner.
 * 7. Quality Switching Timeline separating HYBRID_DECISION, THROUGHPUT_DECISION, BUFFER_DECISION,
 *    QUALITY_CHANGE_REQUESTED, and QUALITY_CHANGE_RENDERED with decision reasoning.
 * 8. Live HTML5 Canvas charts (Bitrate & Buffer Occupancy over time).
 * 9. Persistent comparison dashboard syncing with Flask backend (/api/experiments) and rendering
 *    comparative bar charts (QoE, Bitrate, Stalls, Switches) that survive page refresh.
 * 10. CSV and JSON export with active mode tracking.
 */

(function () {
    'use strict';

    // =========================================================================
    // DOM Element References
    // =========================================================================

    // Navigation & Core Video
    const video = document.getElementById('videoPlayer');
    const abrModeSelect = document.getElementById('abrModeSelect');
    const qualitySelect = document.getElementById('qualitySelect');
    const modeDescription = document.getElementById('modeDescription');
    const stateBadge = document.getElementById('stateBadge');
    const stateDot = document.getElementById('stateDot');
    const stateText = document.getElementById('stateText');
    const modeBadge = document.getElementById('modeBadge');
    const currentRes = document.getElementById('currentResolution');
    const currentBitrate = document.getElementById('currentBitrate');
    const bufferLevel = document.getElementById('bufferLevel');
    const bufferBar = document.getElementById('bufferBar');
    const playbackTime = document.getElementById('playbackTime');
    const alertBox = document.getElementById('alertBox');
    const alertMsg = document.getElementById('alertMsg');

    // Algorithm Selection Cards
    const cardAlgoThroughput = document.getElementById('cardAlgoThroughput');
    const cardAlgoBuffer = document.getElementById('cardAlgoBuffer');
    const cardAlgoHybrid = document.getElementById('cardAlgoHybrid');
    const statusAlgoThroughput = document.getElementById('statusAlgoThroughput');
    const statusAlgoBuffer = document.getElementById('statusAlgoBuffer');
    const statusAlgoHybrid = document.getElementById('statusAlgoHybrid');
    const currentAlgoBadge = document.getElementById('currentAlgoBadge');

    // Experiment Controls Bar
    const btnStartExperiment = document.getElementById('btnStartExperiment');
    const btnStopExperiment = document.getElementById('btnStopExperiment');
    const btnResetExperiment = document.getElementById('btnResetExperiment');
    const btnRunAllAlgorithms = document.getElementById('btnRunAllAlgorithms');
    const btnClearExperiments = document.getElementById('btnClearExperiments');
    const expStatusBadge = document.getElementById('expStatusBadge');
    const expStatusText = document.getElementById('expStatusText');
    const expTimer = document.getElementById('expTimer');
    const runAllProgress = document.getElementById('runAllProgress');
    const statsFinalizedBadge = document.getElementById('statsFinalizedBadge');

    // Mininet & Network Controls
    const networkScenarioSelect = document.getElementById('networkScenarioSelect');
    const mininetCommandText = document.getElementById('mininetCommandText');
    const btnCopyMininetCmd = document.getElementById('btnCopyMininetCmd');
    const statDownloadTime = document.getElementById('statDownloadTime');
    const statChunkSize = document.getElementById('statChunkSize');
    const statChunkThroughput = document.getElementById('statChunkThroughput');

    // Enhanced Buffering Visualizer
    const bufferNumericText = document.getElementById('bufferNumericText');
    const bufferStatusTag = document.getElementById('bufferStatusTag');

    // Session Statistics & QoE
    const statStartupDelay = document.getElementById('statStartupDelay');
    const statPlaybackTime = document.getElementById('statPlaybackTime');
    const statStallCount = document.getElementById('statStallCount');
    const statRebufferTime = document.getElementById('statRebufferTime');
    const statRebufferRatio = document.getElementById('statRebufferRatio');
    const statAvgBitrate = document.getElementById('statAvgBitrate');
    const statSwitchCount = document.getElementById('statSwitchCount');
    const statSwitchMagnitude = document.getElementById('statSwitchMagnitude');
    const statSessionQoE = document.getElementById('statSessionQoE');

    // Export Buttons
    const exportCsvBtn = document.getElementById('exportCsvBtn');
    const exportJsonBtn = document.getElementById('exportJsonBtn');

    // Quality Switch Timeline & Log
    const switchCountBadge = document.getElementById('switchCountBadge');
    const switchLogBody = document.getElementById('switchLogBody');
    const emptyLogMsg = document.getElementById('emptyLogMsg');
    const clearLogBtn = document.getElementById('clearLogBtn');

    // Real-Time Playback Charts
    const tabBitrate = document.getElementById('tabBitrate');
    const tabBuffer = document.getElementById('tabBuffer');
    const bitrateCanvas = document.getElementById('bitrateChartCanvas');
    const bufferCanvas = document.getElementById('bufferChartCanvas');
    const bitrateLegend = document.getElementById('bitrateLegend');
    const bufferLegend = document.getElementById('bufferLegend');

    // Persistent Comparison Dashboard
    const comparisonCountBadge = document.getElementById('comparisonCountBadge');
    const comparisonTableBody = document.getElementById('comparisonTableBody');
    const emptyComparisonMsg = document.getElementById('emptyComparisonMsg');
    const compChartQoE = document.getElementById('compChartQoE');
    const compChartBitrate = document.getElementById('compChartBitrate');
    const compChartStalls = document.getElementById('compChartStalls');
    const compChartSwitches = document.getElementById('compChartSwitches');

    // =========================================================================
    // Constants & Configuration
    // =========================================================================
    const MAX_SAMPLES = 600;
    const SAMPLING_INTERVAL_MS = 500;
    const QOE_ALPHA = 1.0;
    const QOE_BETA = 4.3;
    const QOE_GAMMA = 1.0;

    // Mininet Command Mapping
    const MININET_COMMANDS = {
        '5 Mbps': 'py s1.linksTo(h2)[0].intf2.config(bw=5)',
        '1 Mbps': 'py s1.linksTo(h2)[0].intf2.config(bw=1)',
        '500 kbps': 'py s1.linksTo(h2)[0].intf2.config(bw=0.5)',
        'Fluctuating': 'py s1.linksTo(h2)[0].intf2.config(bw=1) # Then toggle bw=5',
        'Custom': 'py s1.linksTo(h2)[0].intf2.config(bw=<bandwidth_mbps>)'
    };

    // =========================================================================
    // Player & Controller State
    // =========================================================================
    let player = null;
    let videoBitrates = [];
    let currentAbrMode = 'hybrid'; // 'throughput' | 'buffer' | 'hybrid' | 'auto' | 'manual'
    let lastRequestedQualityIdx = -1;
    let tickerInterval = null;

    // ABR Algorithm Controllers
    let throughputController = null;
    let bufferController = null;
    let hybridController = null;

    // Experiment State Machine
    let experimentState = 'IDLE'; // 'IDLE' | 'INITIALIZING' | 'RUNNING' | 'FINALIZING' | 'COMPLETED' | 'CANCELLED' | 'STOPPED' | 'FAILED'
    let isExperimentActive = false;
    let finalizedMetrics = null;
    let currentExperimentId = null;
    let experimentStartTime = null;
    let experimentTimerInterval = null;
    let activeNetworkScenario = '5 Mbps';

    // Sequential "Run All" State
    let runAllActive = false;
    let runAllSequence = ['throughput', 'buffer', 'hybrid'];
    let runAllIndex = 0;
    let runAllCancelRequested = false;

    // Active Run Metrics Tracking
    let startupStartTime = null;
    let startupDelaySec = null;
    let hasStartedPlayback = false;

    let isRebuffering = false;
    let rebufferStartTime = null;
    let totalRebufferSec = 0.0;
    let stallCount = 0;

    let renderedSwitchCount = 0;
    let totalSwitchMagnitudeKbps = 0.0;
    let lastRenderedQuality = -1;
    let lastRenderedBitrateKbps = 0.0;

    // Network Segment Accumulators
    let totalDownloadedBytes = 0;
    let totalDownloadTimeSec = 0.0;
    let downloadedChunksCount = 0;

    // Telemetry Collections
    const telemetrySamples = [];
    const switchEvents = [];

    // Active Chart Tab ('bitrate' | 'buffer')
    let activeChart = 'bitrate';

    // Stored Persistent Comparison Experiments
    let storedExperiments = [];

    // =========================================================================
    // Formatting Helpers
    // =========================================================================
    function formatTime(seconds) {
        if (!seconds || isNaN(seconds) || seconds < 0) return '00:00';
        const mins = Math.floor(seconds / 60);
        const secs = Math.floor(seconds % 60);
        return `${mins.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`;
    }

    function formatBitrate(bps) {
        if (!bps || isNaN(bps) || bps <= 0) return '0 kbps';
        if (bps >= 1000000) {
            return `${(bps / 1000000).toFixed(2)} Mbps`;
        }
        return `${Math.round(bps / 1000)} kbps`;
    }

    function setPlaybackState(state, text) {
        if (stateBadge && stateText) {
            stateBadge.className = `badge badge-${state}`;
            stateText.textContent = text;
        }
    }

    function setExperimentState(state, text) {
        experimentState = state;
        if (expStatusBadge && expStatusText) {
            expStatusBadge.className = `exp-badge exp-badge-${state.toLowerCase()}`;
            expStatusText.textContent = text || state;
        }
    }

    function showError(message) {
        if (alertMsg && alertBox) {
            alertMsg.textContent = message;
            alertBox.style.display = 'block';
            setPlaybackState('buffering', 'Error');
        }
    }

    function clearError() {
        if (alertBox) alertBox.style.display = 'none';
    }

    function getModeDisplayName(mode = currentAbrMode) {
        if (mode === 'throughput') return 'THROUGHPUT-BASED ABR';
        if (mode === 'buffer') return 'BUFFER-BASED ABR (BBA)';
        if (mode === 'hybrid') return 'CUSTOM HYBRID ABR';
        if (mode === 'manual') return 'MANUAL (Pinned)';
        return 'AUTO (dash.js)';
    }

    function getAlgorithmTitle(mode) {
        if (mode === 'throughput') return 'Throughput-Based ABR';
        if (mode === 'buffer') return 'Buffer-Based ABR (BBA)';
        if (mode === 'hybrid') return 'QoE-Driven Hybrid ABR';
        if (mode === 'manual') return 'Manual Pinned Quality';
        return 'dash.js Built-in Auto';
    }

    // =========================================================================
    // Algorithm Controllers Initialization
    // =========================================================================
    function initHybridController() {
        if (typeof HybridQoEController !== 'undefined') {
            hybridController = new HybridQoEController({
                segmentDurationSec: 2.0,
                safetyFactorBase: 0.90,
                safetyFactorMin: 0.60,
                volatilityWeight: 0.30,
                reservoirSec: 5.0,
                cushionSec: 10.0,
                stallSafetyMarginSec: 0.5,
                switchPenaltyLambda: 0.5,
                windowSize: 5
            });
            if (videoBitrates && videoBitrates.length > 0) {
                hybridController.setBitrateLadder(videoBitrates);
            }
        }
    }

    function initThroughputController() {
        if (typeof ThroughputBasedController !== 'undefined') {
            throughputController = new ThroughputBasedController({
                safetyFactor: 0.85,
                windowSize: 5
            });
            if (videoBitrates && videoBitrates.length > 0) {
                throughputController.setBitrateLadder(videoBitrates);
            }
        }
    }

    function initBufferController() {
        if (typeof BufferBasedController !== 'undefined') {
            bufferController = new BufferBasedController({
                reservoirSec: 5.0,
                cushionSec: 10.0,
                hysteresisSec: 0.5
            });
            if (videoBitrates && videoBitrates.length > 0) {
                bufferController.setBitrateLadder(videoBitrates);
            }
        }
    }

    function initAllControllers() {
        initHybridController();
        initThroughputController();
        initBufferController();
    }

    // =========================================================================
    // ABR Mode & Algorithm Switching
    // =========================================================================
    function setAbrMode(mode, targetManualQuality = null) {
        currentAbrMode = mode;
        if (abrModeSelect) abrModeSelect.value = mode;
        lastRequestedQualityIdx = -1;

        // Synchronize Algorithm Selection Cards UI
        if (cardAlgoThroughput && cardAlgoBuffer && cardAlgoHybrid) {
            cardAlgoThroughput.classList.toggle('active', mode === 'throughput');
            cardAlgoBuffer.classList.toggle('active', mode === 'buffer');
            cardAlgoHybrid.classList.toggle('active', mode === 'hybrid');

            if (statusAlgoThroughput) {
                statusAlgoThroughput.textContent = mode === 'throughput' ? 'Active' : 'Select';
                statusAlgoThroughput.classList.toggle('active', mode === 'throughput');
            }
            if (statusAlgoBuffer) {
                statusAlgoBuffer.textContent = mode === 'buffer' ? 'Active' : 'Select';
                statusAlgoBuffer.classList.toggle('active', mode === 'buffer');
            }
            if (statusAlgoHybrid) {
                statusAlgoHybrid.textContent = mode === 'hybrid' ? 'Active' : 'Select';
                statusAlgoHybrid.classList.toggle('active', mode === 'hybrid');
            }
            if (currentAlgoBadge) {
                currentAlgoBadge.textContent = `${getAlgorithmTitle(mode)} Active`;
            }
        }

        // Apply mode behaviors
        if (mode === 'throughput') {
            if (modeBadge) modeBadge.textContent = 'THROUGHPUT-BASED ABR';
            if (modeDescription) {
                modeDescription.innerHTML = '<strong>Throughput-Based ABR:</strong> Adapts bitrate using the harmonic mean of recent segment throughputs with safety headroom (SF=0.85).';
            }
            if (qualitySelect) qualitySelect.value = 'auto';
            if (player) {
                player.updateSettings({
                    streaming: { abr: { autoSwitchBitrate: { video: false } } }
                });
            }
            if (throughputController) {
                throughputController.reset();
                if (videoBitrates.length > 0) throughputController.setBitrateLadder(videoBitrates);
            }
        } else if (mode === 'buffer') {
            if (modeBadge) modeBadge.textContent = 'BUFFER-BASED ABR (BBA)';
            if (modeDescription) {
                modeDescription.innerHTML = '<strong>Buffer-Based ABR (BBA):</strong> Adapts bitrate strictly as a function of client playback buffer occupancy (5s Reservoir, 10s Cushion).';
            }
            if (qualitySelect) qualitySelect.value = 'auto';
            if (player) {
                player.updateSettings({
                    streaming: { abr: { autoSwitchBitrate: { video: false } } }
                });
            }
            if (bufferController) {
                bufferController.reset();
                if (videoBitrates.length > 0) bufferController.setBitrateLadder(videoBitrates);
            }
        } else if (mode === 'hybrid') {
            if (modeBadge) modeBadge.textContent = 'CUSTOM HYBRID ABR';
            if (modeDescription) {
                modeDescription.innerHTML = '<strong>Custom Hybrid ABR:</strong> Quality is dynamically driven by our QoE hybrid algorithm based on live throughput, volatility, buffer, and switching penalty.';
            }
            if (qualitySelect) qualitySelect.value = 'auto';
            if (player) {
                player.updateSettings({
                    streaming: { abr: { autoSwitchBitrate: { video: false } } }
                });
            }
            if (hybridController) {
                hybridController.reset();
                if (videoBitrates.length > 0) hybridController.setBitrateLadder(videoBitrates);
            }
        } else if (mode === 'auto') {
            if (modeBadge) modeBadge.textContent = 'AUTO (dash.js)';
            if (modeDescription) {
                modeDescription.innerHTML = '<strong>Auto:</strong> dash.js manages video quality using its default internal ABR rules.';
            }
            if (qualitySelect) qualitySelect.value = 'auto';
            if (player) {
                player.updateSettings({
                    streaming: { abr: { autoSwitchBitrate: { video: true } } }
                });
            }
        } else if (mode === 'manual') {
            if (modeBadge) modeBadge.textContent = 'MANUAL (Pinned)';
            if (modeDescription) {
                modeDescription.innerHTML = '<strong>Manual Tier:</strong> Video quality is locked to user selection.';
            }
            if (player) {
                player.updateSettings({
                    streaming: { abr: { autoSwitchBitrate: { video: false } } }
                });
                if (targetManualQuality !== null && targetManualQuality !== undefined) {
                    const qIdx = parseInt(targetManualQuality, 10);
                    if (!isNaN(qIdx)) {
                        player.setQualityFor('video', qIdx);
                        lastRequestedQualityIdx = qIdx;
                        if (qualitySelect) qualitySelect.value = qIdx.toString();
                    }
                }
            }
        }
    }

    // =========================================================================
    // dash.js Player Initialization & Lifecycle
    // =========================================================================
    function initPlayer() {
        if (typeof dashjs === 'undefined') {
            showError('dash.js library could not be loaded. Ensure network connectivity to CDN or local fallback.');
            return;
        }

        const manifestUrl = video ? (video.getAttribute('data-manifest') || '/dash/stream.mpd') : '/dash/stream.mpd';

        try {
            // Instantiate all ABR controllers
            initAllControllers();

            player = dashjs.MediaPlayer().create();
            player.initialize(video, manifestUrl, false);

            player.updateSettings({
                streaming: {
                    abr: {
                        autoSwitchBitrate: {
                            video: false, // Default to custom controller
                            audio: true
                        }
                    },
                    buffer: {
                        stableBufferTime: 10,
                        bufferTimeAtTopQuality: 10,
                        bufferToKeep: 4
                    }
                }
            });

            if (typeof window !== 'undefined') {
                window.__dashPlayer = player;
            }

            // Set default algorithm to Hybrid QoE
            setAbrMode('hybrid');

            // Lifecycle Bindings
            player.on(dashjs.MediaPlayer.events.STREAM_INITIALIZED, onStreamInitialized);
            player.on(dashjs.MediaPlayer.events.MANIFEST_LOADED, onManifestLoaded);
            player.on(dashjs.MediaPlayer.events.QUALITY_CHANGE_REQUESTED, onQualityChangeRequested);
            player.on(dashjs.MediaPlayer.events.QUALITY_CHANGE_RENDERED, onQualityChangeRendered);
            player.on(dashjs.MediaPlayer.events.FRAGMENT_LOADING_COMPLETED, onFragmentLoadingCompleted);
            player.on(dashjs.MediaPlayer.events.PLAYBACK_ENDED, onPlaybackEnded);
            player.on(dashjs.MediaPlayer.events.ERROR, onPlayerError);

            // Native Video Element Lifecycle Bindings
            bindVideoLifecycle();

            // Telemetry Sampling Interval
            if (tickerInterval) clearInterval(tickerInterval);
            tickerInterval = setInterval(sampleTelemetry, SAMPLING_INTERVAL_MS);

            // UI Listeners
            initModeControls();
            initExperimentControls();
            initNetworkControls();
            initChartControls();
            initExportControls();

            if (clearLogBtn) {
                clearLogBtn.addEventListener('click', clearSwitchLog);
            }

            // Window resize for canvas charts
            window.addEventListener('resize', debounce(function () {
                redrawCharts();
                renderAllComparisonCharts();
            }, 150));

            // Load existing persistent experiment comparisons from server
            fetchAndRenderExperiments();

            setPlaybackState('ready', 'Ready');
        } catch (err) {
            showError(`Failed to initialize player: ${err.message}`);
        }
    }

    function bindVideoLifecycle() {
        if (!video) return;

        const onStartRequest = function () {
            if (startupStartTime === null && !hasStartedPlayback) {
                startupStartTime = performance.now();
            }
        };
        video.addEventListener('play', onStartRequest);
        video.addEventListener('loadstart', onStartRequest);

        video.addEventListener('playing', function () {
            if (!hasStartedPlayback && startupStartTime !== null) {
                startupDelaySec = Math.max(0, (performance.now() - startupStartTime) / 1000.0);
                hasStartedPlayback = true;
                if (statStartupDelay) {
                    statStartupDelay.textContent = `${startupDelaySec.toFixed(2)}s`;
                }
            }

            if (isRebuffering && rebufferStartTime !== null) {
                const stallDuration = Math.max(0, (performance.now() - rebufferStartTime) / 1000.0);
                totalRebufferSec += stallDuration;
                stallCount += 1;
                isRebuffering = false;
                rebufferStartTime = null;
            }

            setPlaybackState('playing', 'Playing');
            updateSessionStatistics();
        });

        video.addEventListener('waiting', function () {
            if (hasStartedPlayback && !video.paused && !video.seeking && !isRebuffering) {
                isRebuffering = true;
                rebufferStartTime = performance.now();
                setPlaybackState('buffering', 'Buffering');
            }
        });

        video.addEventListener('pause', function () {
            const cur = video.currentTime || 0;
            const dur = video.duration || 30.0;
            if (cur >= dur - 0.15 || cur >= 29.85) {
                onPlaybackEnded();
            } else if (!video.ended) {
                setPlaybackState('paused', 'Paused');
            }
        });

        video.addEventListener('ended', function () {
            onPlaybackEnded();
        });

        video.addEventListener('timeupdate', function () {
            updatePlaybackMetrics();
            const cur = video.currentTime || 0;
            const dur = video.duration || 30.0;
            if (cur >= dur - 0.15 || cur >= 29.85) {
                onPlaybackEnded();
            }
        });
    }

    function onPlaybackEnded() {
        setPlaybackState('ready', 'Ended');
        if (video && !video.paused) {
            video.pause();
        }
        if (isExperimentActive) {
            onExperimentFinished(true, 'COMPLETED');
        }
    }

    function onStreamInitialized() {
        clearError();
        videoBitrates = player.getBitrateInfoListFor('video') || [];

        // Bind dynamic representations to all 3 custom controllers
        if (hybridController && videoBitrates.length > 0) {
            hybridController.setBitrateLadder(videoBitrates);
        }
        if (throughputController && videoBitrates.length > 0) {
            throughputController.setBitrateLadder(videoBitrates);
        }
        if (bufferController && videoBitrates.length > 0) {
            bufferController.setBitrateLadder(videoBitrates);
        }

        populateQualitySelector();
    }

    function onManifestLoaded() {
        clearError();
    }

    function populateQualitySelector() {
        if (!player || !qualitySelect) return;

        if (videoBitrates.length === 0) {
            videoBitrates = player.getBitrateInfoListFor('video') || [];
        }
        if (videoBitrates.length === 0) return;

        const currentVal = qualitySelect.value;
        qualitySelect.innerHTML = '';

        const autoOpt = document.createElement('option');
        autoOpt.value = 'auto';
        autoOpt.textContent = 'Auto (Managed by Active ABR Mode)';
        qualitySelect.appendChild(autoOpt);

        videoBitrates.sort((a, b) => a.qualityIndex - b.qualityIndex);

        videoBitrates.forEach((info) => {
            const opt = document.createElement('option');
            opt.value = info.qualityIndex.toString();
            opt.textContent = `${info.height}p (${formatBitrate(info.bitrate)})`;
            qualitySelect.appendChild(opt);
        });

        if (currentAbrMode === 'manual' && currentVal !== 'auto') {
            qualitySelect.value = currentVal;
        } else {
            qualitySelect.value = 'auto';
        }
    }

    // =========================================================================
    // Fragment Download Completed & Multi-Algorithm Adaptation Decisions
    // =========================================================================
    function onFragmentLoadingCompleted(e) {
        if (!e || !e.request) return;
        const req = e.request;

        // 1. Filter: video media segments only (ignore init segments and audio)
        if (req.mediaType !== 'video') return;
        if (req.type !== 'MediaSegment') return;

        // 2. Measure actual downloaded bytes and duration
        let bytesLoaded = req.bytesLoaded;
        if ((!bytesLoaded || bytesLoaded <= 0) && e.response) {
            bytesLoaded = e.response.byteLength || e.response.length || 0;
        }
        if (!bytesLoaded || bytesLoaded <= 0) return;

        const startMs = req.requestStartDate ? req.requestStartDate.getTime() : 0;
        const endMs = req.requestEndDate ? req.requestEndDate.getTime() : 0;
        const durationSec = (endMs > startMs) ? (endMs - startMs) / 1000.0 : 0.0;
        if (durationSec <= 0.001) return;

        const measuredTpKbps = (bytesLoaded * 8) / (durationSec * 1000.0);
        const currentBufferSec = getBufferSec();

        // Update real-time network telemetry
        if (statDownloadTime) statDownloadTime.textContent = `${(durationSec * 1000).toFixed(0)} ms`;
        if (statChunkSize) statChunkSize.textContent = `${Math.round(bytesLoaded / 1024)} KB`;
        if (statChunkThroughput) statChunkThroughput.textContent = formatBitrate(measuredTpKbps * 1000);

        // Accumulate experiment network metrics
        totalDownloadedBytes += bytesLoaded;
        totalDownloadTimeSec += durationSec;
        downloadedChunksCount += 1;

        // Auto mode lets dash.js decide; Manual locks to user selection
        if (currentAbrMode === 'auto' || currentAbrMode === 'manual' || !player) return;

        // 3. Resolve active bitrate and segment index
        const currentQIdx = player.getQualityFor('video');
        const currentRep = videoBitrates.find(b => b.qualityIndex === currentQIdx);
        const currentBitrateKbps = currentRep ? Math.round(currentRep.bitrate / 1000) : null;
        const segIdx = req.index !== undefined ? req.index : telemetrySamples.length;

        let selectedBitrateKbps = null;
        let targetQIdx = 0;
        let eventType = 'HYBRID_DECISION';
        let reason = '';

        // 4. Query active algorithm
        if (currentAbrMode === 'throughput' && throughputController) {
            selectedBitrateKbps = throughputController.selectBitrate(
                segIdx,
                currentBufferSec,
                measuredTpKbps,
                durationSec,
                currentBitrateKbps
            );
            targetQIdx = throughputController.getRepresentationIndexForBitrate(selectedBitrateKbps);
            eventType = 'THROUGHPUT_DECISION';
            reason = throughputController.lastDecisionReason || `Throughput: ${Math.round(measuredTpKbps)}k, Buf: ${currentBufferSec.toFixed(1)}s`;
        } else if (currentAbrMode === 'buffer' && bufferController) {
            selectedBitrateKbps = bufferController.selectBitrate(
                segIdx,
                currentBufferSec,
                measuredTpKbps,
                durationSec,
                currentBitrateKbps
            );
            targetQIdx = bufferController.getRepresentationIndexForBitrate(selectedBitrateKbps);
            eventType = 'BUFFER_DECISION';
            reason = bufferController.lastDecisionReason || `Buffer: ${currentBufferSec.toFixed(1)}s (Reservoir: 5s, Cushion: 10s)`;
        } else if (currentAbrMode === 'hybrid' && hybridController) {
            selectedBitrateKbps = hybridController.selectBitrate(
                segIdx,
                currentBufferSec,
                measuredTpKbps,
                durationSec,
                currentBitrateKbps
            );
            targetQIdx = hybridController.getRepresentationIndexForBitrate(selectedBitrateKbps);
            eventType = 'HYBRID_DECISION';
            const estTp = hybridController.estimatedThroughputKbps;
            const cv = hybridController.computeVolatility();
            reason = `EstTP: ${Math.round(estTp)}k, CV: ${cv.toFixed(2)}, Buf: ${currentBufferSec.toFixed(1)}s`;
        }

        if (selectedBitrateKbps === null) return;

        // 5. Map to DASH representation
        const targetRep = videoBitrates.find(b => b.qualityIndex === targetQIdx) || {
            qualityIndex: targetQIdx,
            height: targetQIdx,
            bitrate: selectedBitrateKbps * 1000
        };

        // 6. Record decision in audit timeline
        recordAlgorithmDecision({
            type: eventType,
            clockTime: new Date().toTimeString().split(' ')[0],
            mediaTimeSec: video ? (video.currentTime || 0) : 0,
            oldQuality: currentRep ? `${currentRep.height}p` : 'None',
            newQuality: `${targetRep.height}p`,
            bitrateKbps: selectedBitrateKbps,
            bufferSec: currentBufferSec,
            mode: getModeDisplayName(),
            reason: reason
        });

        // 7. Structured Diagnostic Output (Issue 4 requirement)
        console.log('[ABR DIAGNOSTIC]', JSON.stringify({
            experimentId: currentExperimentId || 'live',
            algorithm: currentAbrMode,
            segmentIndex: segIdx,
            bufferBeforeDecisionSec: parseFloat(currentBufferSec.toFixed(2)),
            measuredThroughputKbps: Math.round(measuredTpKbps),
            previousQuality: currentRep ? `${currentRep.height}p` : 'None',
            newQuality: `${targetRep.height}p`,
            selectedBitrateKbps: selectedBitrateKbps,
            downloadDurationSec: parseFloat(durationSec.toFixed(3)),
            bytesLoaded: bytesLoaded,
            decisionRationale: reason,
            applied: true
        }));

        // 8. Duplicate Decision Suppression: Only dispatch if target differs from last requested
        if (targetQIdx !== lastRequestedQualityIdx) {
            lastRequestedQualityIdx = targetQIdx;
            player.setQualityFor('video', targetQIdx);
        }
    }

    function recordAlgorithmDecision(data) {
        switchEvents.push(data);
        renderTimelineRow(data);
    }

    function onQualityChangeRequested(e) {
        if (!e || e.mediaType !== 'video') return;

        const reqIdx = e.newQuality;
        const oldIdx = e.oldQuality !== undefined ? e.oldQuality : lastRenderedQuality;

        if (videoBitrates.length === 0 && player) {
            videoBitrates = player.getBitrateInfoListFor('video') || [];
        }

        const rep = videoBitrates.find(b => b.qualityIndex === reqIdx);
        const oldRep = videoBitrates.find(b => b.qualityIndex === oldIdx);

        const modeStr = getModeDisplayName();
        const reasonStr = e.reason ? (typeof e.reason === 'string' ? e.reason : 'ABR Rule') : `${modeStr} Rule`;

        const eventData = {
            type: 'QUALITY_CHANGE_REQUESTED',
            clockTime: new Date().toTimeString().split(' ')[0],
            mediaTimeSec: video ? (video.currentTime || 0) : 0,
            oldQuality: oldRep ? `${oldRep.height}p` : (oldIdx >= 0 ? `Tier ${oldIdx}` : 'None'),
            newQuality: rep ? `${rep.height}p` : `Tier ${reqIdx}`,
            bitrateKbps: rep ? Math.round(rep.bitrate / 1000) : 0,
            bufferSec: getBufferSec(),
            mode: modeStr,
            reason: reasonStr
        };

        switchEvents.push(eventData);
        renderTimelineRow(eventData);
    }

    function onQualityChangeRendered(e) {
        if (!e || e.mediaType !== 'video') return;

        const oldQuality = e.oldQuality !== undefined ? e.oldQuality : lastRenderedQuality;
        const newQuality = e.newQuality;

        if (videoBitrates.length === 0 && player) {
            videoBitrates = player.getBitrateInfoListFor('video') || [];
        }

        const rep = videoBitrates.find(b => b.qualityIndex === newQuality);
        const oldRep = videoBitrates.find(b => b.qualityIndex === oldQuality);
        if (!rep) return;

        const newBitrateKbps = Math.round(rep.bitrate / 1000);

        if (lastRenderedBitrateKbps > 0 && lastRenderedQuality !== newQuality) {
            const mag = Math.abs(newBitrateKbps - lastRenderedBitrateKbps);
            totalSwitchMagnitudeKbps += mag;
            renderedSwitchCount++;
        } else if (lastRenderedQuality === -1) {
            renderedSwitchCount = 1;
        }

        lastRenderedQuality = newQuality;
        lastRenderedBitrateKbps = newBitrateKbps;

        if (currentRes) currentRes.textContent = `${rep.width}x${rep.height}`;
        if (currentBitrate) currentBitrate.textContent = formatBitrate(rep.bitrate);

        const modeStr = getModeDisplayName();

        const eventData = {
            type: 'QUALITY_CHANGE_RENDERED',
            clockTime: new Date().toTimeString().split(' ')[0],
            mediaTimeSec: video ? (video.currentTime || 0) : 0,
            oldQuality: oldRep ? `${oldRep.height}p` : (oldQuality >= 0 ? `Tier ${oldQuality}` : 'Initial'),
            newQuality: `${rep.height}p`,
            bitrateKbps: newBitrateKbps,
            bufferSec: getBufferSec(),
            mode: modeStr,
            reason: 'Rendered'
        };

        switchEvents.push(eventData);
        renderTimelineRow(eventData);
        updateSessionStatistics();
    }

    function renderTimelineRow(data) {
        if (!switchLogBody) return;
        if (emptyLogMsg) emptyLogMsg.style.display = 'none';

        if (switchCountBadge) {
            switchCountBadge.textContent = `${renderedSwitchCount} switch${renderedSwitchCount === 1 ? '' : 'es'}`;
        }

        let typeBadge = '';
        if (data.type === 'HYBRID_DECISION') {
            typeBadge = '<span class="event-type-badge type-hybrid">Hybrid Decision</span>';
        } else if (data.type === 'THROUGHPUT_DECISION') {
            typeBadge = '<span class="event-type-badge type-throughput">Throughput Decision</span>';
        } else if (data.type === 'BUFFER_DECISION') {
            typeBadge = '<span class="event-type-badge type-buffer">Buffer Decision</span>';
        } else if (data.type === 'QUALITY_CHANGE_RENDERED' || data.type === 'rendered') {
            typeBadge = '<span class="event-type-badge type-rendered">Rendered</span>';
        } else {
            typeBadge = '<span class="event-type-badge type-requested">Requested</span>';
        }

        let transitionPill = '';
        if (data.type === 'HYBRID_DECISION' || data.type === 'THROUGHPUT_DECISION' || data.type === 'BUFFER_DECISION') {
            transitionPill = `<span class="switch-pill switch-init">${data.newQuality} (${data.bitrateKbps}k) &mdash; ${data.reason}</span>`;
        } else if (data.oldQuality === 'None' || data.oldQuality === 'Initial') {
            transitionPill = `<span class="switch-pill switch-init">${data.newQuality} (${data.bitrateKbps} kbps)</span>`;
        } else {
            transitionPill = `<span class="switch-pill switch-up">${data.oldQuality} &rarr; ${data.newQuality}</span>`;
        }

        const row = document.createElement('tr');
        row.innerHTML = `
            <td>${data.clockTime}</td>
            <td>${formatTime(data.mediaTimeSec)}</td>
            <td>${typeBadge}</td>
            <td>${transitionPill}</td>
            <td>${data.bufferSec.toFixed(1)}s</td>
            <td>${data.mode}</td>
        `;

        switchLogBody.insertBefore(row, switchLogBody.firstChild);
    }

    function clearSwitchLog() {
        if (switchLogBody) switchLogBody.innerHTML = '';
        if (emptyLogMsg) emptyLogMsg.style.display = 'block';
        switchEvents.length = 0;
        renderedSwitchCount = 0;
        totalSwitchMagnitudeKbps = 0.0;
        if (switchCountBadge) switchCountBadge.textContent = '0 switches';
        updateSessionStatistics();
    }

    function getBufferSec() {
        if (!player) return 0.0;
        try {
            const buf = player.getBufferLength('video');
            return (buf !== null && !isNaN(buf)) ? Math.max(0, buf) : 0.0;
        } catch (e) {
            return 0.0;
        }
    }

    function updatePlaybackMetrics() {
        if (!video || !playbackTime) return;
        const cur = video.currentTime || 0;
        const dur = video.duration || 30.0;
        playbackTime.textContent = `${formatTime(cur)} / ${formatTime(dur)}`;
    }

    // =========================================================================
    // Real-Time Telemetry Sampling & Visual Buffering Indicators
    // =========================================================================
    function sampleTelemetry() {
        if (!player || !video) return;

        const curTime = video.currentTime || 0;
        const bufSec = getBufferSec();

        // Update real-time buffer progress bar and label
        if (bufferLevel) bufferLevel.textContent = `${bufSec.toFixed(2)}s`;
        if (bufferNumericText) bufferNumericText.textContent = `${bufSec.toFixed(2)}s`;
        if (bufferBar) {
            const percent = Math.min(100, (bufSec / 30.0) * 100);
            bufferBar.style.width = `${percent}%`;
        }

        // Buffer status indicator tag & warnings
        if (bufferStatusTag) {
            if (bufSec < 5.0) {
                bufferStatusTag.textContent = 'Low (< 5s Reservoir)';
                bufferStatusTag.className = 'buffer-status-tag critical';
            } else if (bufSec < 10.0) {
                bufferStatusTag.textContent = 'Adequate Cushion';
                bufferStatusTag.className = 'buffer-status-tag warning';
            } else {
                bufferStatusTag.textContent = 'Safe Buffer';
                bufferStatusTag.className = 'buffer-status-tag';
            }
        }

        // Active state string
        let stateStr = 'ready';
        if (isRebuffering) stateStr = 'buffering';
        else if (video.paused && video.currentTime > 0) stateStr = 'paused';
        else if (!video.paused && video.currentTime > 0) stateStr = 'playing';

        const modeStr = getModeDisplayName();

        // If experiment is NOT active, do not collect experiment telemetry or recompute stats
        if (!isExperimentActive) {
            if (finalizedMetrics) {
                renderFinalizedSessionStats(finalizedMetrics);
            }
            return;
        }

        // Record telemetry sample
        const sample = {
            timestampIso: new Date().toISOString(),
            mediaTimeSec: parseFloat(curTime.toFixed(2)),
            bufferLevelSec: parseFloat(bufSec.toFixed(2)),
            bitrateKbps: lastRenderedBitrateKbps,
            resolution: currentRes ? currentRes.textContent : '--',
            playbackState: stateStr,
            abrMode: modeStr
        };

        if (telemetrySamples.length >= MAX_SAMPLES) {
            telemetrySamples.shift();
        }
        telemetrySamples.push(sample);

        updateSessionStatistics();
        redrawCharts();
    }

    function renderFinalizedSessionStats(m) {
        if (!m) return;
        if (statsFinalizedBadge) statsFinalizedBadge.style.display = 'inline-block';
        if (statStartupDelay) statStartupDelay.textContent = m.startupDelaySec > 0 ? `${m.startupDelaySec.toFixed(2)}s` : 'N/A';
        if (statPlaybackTime) statPlaybackTime.textContent = `${m.durationSec.toFixed(1)}s`;
        if (statStallCount) statStallCount.textContent = m.stallCount.toString();
        if (statRebufferTime) statRebufferTime.textContent = `${m.totalRebufferSec.toFixed(2)}s`;
        if (statRebufferRatio) statRebufferRatio.textContent = `${m.rebufferRatio.toFixed(2)}%`;
        if (statAvgBitrate) statAvgBitrate.textContent = m.avgBitrateKbps > 0 ? `${m.avgBitrateKbps} kbps` : '--';
        if (statSwitchCount) statSwitchCount.textContent = m.switchCount.toString();
        if (statSwitchMagnitude) statSwitchMagnitude.textContent = `${Math.round(totalSwitchMagnitudeKbps)} kbps`;
        if (statSessionQoE) {
            statSessionQoE.textContent = m.qoeScore.toFixed(2);
            statSessionQoE.style.color = m.qoeScore < 0 ? 'var(--accent-red)' : '#93c5fd';
        }
    }

    function updateSessionStatistics() {
        const curTime = video ? (video.currentTime || 0) : 0;

        if (statStartupDelay) {
            statStartupDelay.textContent = startupDelaySec !== null ? `${startupDelaySec.toFixed(2)}s` : 'N/A';
        }
        if (statPlaybackTime) {
            statPlaybackTime.textContent = `${curTime.toFixed(1)}s`;
        }
        if (statStallCount) {
            statStallCount.textContent = stallCount.toString();
        }

        let currentTotalRebuffer = totalRebufferSec;
        if (isRebuffering && rebufferStartTime !== null) {
            currentTotalRebuffer += (performance.now() - rebufferStartTime) / 1000.0;
        }

        if (statRebufferTime) {
            statRebufferTime.textContent = `${currentTotalRebuffer.toFixed(2)}s`;
        }

        const totalSessionTime = curTime + currentTotalRebuffer;
        const ratio = totalSessionTime > 0 ? (currentTotalRebuffer / totalSessionTime) : 0.0;
        if (statRebufferRatio) {
            statRebufferRatio.textContent = `${(ratio * 100).toFixed(2)}%`;
        }

        const playingSamples = telemetrySamples.filter(s => s.bitrateKbps > 0);
        let avgBitrateKbps = 0;
        if (playingSamples.length > 0) {
            const sumBitrate = playingSamples.reduce((acc, s) => acc + s.bitrateKbps, 0);
            avgBitrateKbps = Math.round(sumBitrate / playingSamples.length);
        } else if (lastRenderedBitrateKbps > 0) {
            avgBitrateKbps = lastRenderedBitrateKbps;
        }

        if (statAvgBitrate) {
            statAvgBitrate.textContent = avgBitrateKbps > 0 ? `${avgBitrateKbps} kbps` : '--';
        }

        if (statSwitchCount) {
            statSwitchCount.textContent = renderedSwitchCount.toString();
        }
        if (statSwitchMagnitude) {
            statSwitchMagnitude.textContent = `${Math.round(totalSwitchMagnitudeKbps)} kbps`;
        }

        // Academic QoE Calculation
        const estimatedSegments = Math.max(1, curTime / 2.0);
        const qualityUtility = QOE_ALPHA * ((avgBitrateKbps / 1000.0) * estimatedSegments);
        const stallPenalty = QOE_BETA * currentTotalRebuffer;
        const switchPenalty = QOE_GAMMA * (totalSwitchMagnitudeKbps / 1000.0);

        const computedQoE = (curTime > 0 || currentTotalRebuffer > 0)
            ? (qualityUtility - stallPenalty - switchPenalty)
            : 0.0;

        if (statSessionQoE) {
            statSessionQoE.textContent = computedQoE.toFixed(2);
            statSessionQoE.style.color = computedQoE < 0 ? 'var(--accent-red)' : '#93c5fd';
        }
    }

    // =========================================================================
    // Experiment State Machine & Automated Evaluation Controls
    // =========================================================================
    function initExperimentControls() {
        if (btnStartExperiment) {
            btnStartExperiment.addEventListener('click', () => startExperiment());
        }
        if (btnStopExperiment) {
            btnStopExperiment.addEventListener('click', () => stopExperiment(false));
        }
        if (btnResetExperiment) {
            btnResetExperiment.addEventListener('click', () => resetExperiment());
        }
        if (btnRunAllAlgorithms) {
            btnRunAllAlgorithms.addEventListener('click', () => startRunAllSequence());
        }
        if (btnClearExperiments) {
            btnClearExperiments.addEventListener('click', () => clearAllStoredExperiments());
        }
    }

    function resetPlayerMediaSource() {
        return new Promise((resolve) => {
            if (!player) return resolve();
            if (video) {
                video.pause();
                try { video.currentTime = 0; } catch (e) {}
            }

            let done = false;
            const onInit = function () {
                if (!done) {
                    done = true;
                    player.off(dashjs.MediaPlayer.events.STREAM_INITIALIZED, onInit);
                    resolve();
                }
            };
            player.on(dashjs.MediaPlayer.events.STREAM_INITIALIZED, onInit);

            const manifestUrl = video ? (video.getAttribute('data-manifest') || '/dash/stream.mpd') : '/dash/stream.mpd';
            player.attachSource(manifestUrl);

            setTimeout(() => {
                if (!done) {
                    done = true;
                    player.off(dashjs.MediaPlayer.events.STREAM_INITIALIZED, onInit);
                    resolve();
                }
            }, 1000);
        });
    }

    async function prepareCleanRun() {
        // Reset session counters and telemetry
        hasStartedPlayback = false;
        startupStartTime = null;
        startupDelaySec = null;
        isRebuffering = false;
        rebufferStartTime = null;
        totalRebufferSec = 0.0;
        stallCount = 0;
        renderedSwitchCount = 0;
        totalSwitchMagnitudeKbps = 0.0;
        lastRenderedQuality = -1;
        lastRenderedBitrateKbps = 0.0;
        lastRequestedQualityIdx = -1;

        totalDownloadedBytes = 0;
        totalDownloadTimeSec = 0.0;
        downloadedChunksCount = 0;

        telemetrySamples.length = 0;
        finalizedMetrics = null;
        if (statsFinalizedBadge) statsFinalizedBadge.style.display = 'none';

        clearSwitchLog();

        // Reset active controller history
        if (throughputController) throughputController.reset();
        if (bufferController) bufferController.reset();
        if (hybridController) hybridController.reset();

        if (videoBitrates && videoBitrates.length > 0) {
            if (throughputController) throughputController.setBitrateLadder(videoBitrates);
            if (bufferController) bufferController.setBitrateLadder(videoBitrates);
            if (hybridController) hybridController.setBitrateLadder(videoBitrates);
        }

        // Cleanly reset MediaSource
        await resetPlayerMediaSource();

        // Reset UI metrics
        if (statStartupDelay) statStartupDelay.textContent = 'N/A';
        if (statPlaybackTime) statPlaybackTime.textContent = '0.0s';
        if (statStallCount) statStallCount.textContent = '0';
        if (statRebufferTime) statRebufferTime.textContent = '0.00s';
        if (statRebufferRatio) statRebufferRatio.textContent = '0.00%';
        if (statAvgBitrate) statAvgBitrate.textContent = '--';
        if (statSwitchCount) statSwitchCount.textContent = '0';
        if (statSwitchMagnitude) statSwitchMagnitude.textContent = '0 kbps';
        if (statSessionQoE) statSessionQoE.textContent = '0.00';
        if (expTimer) expTimer.textContent = '00:00 / 00:30';

        setPlaybackState('ready', 'Ready');
        clearError();
        redrawCharts();
    }

    function startExperiment() {
        if (isExperimentActive) return; // Prevent overlapping runs

        isExperimentActive = true;
        finalizedMetrics = null;
        currentExperimentId = `exp-${Date.now()}`;
        experimentStartTime = performance.now();

        const badgeText = runAllActive
            ? `RUNNING (${runAllIndex + 1}/3: ${getAlgorithmTitle(currentAbrMode)})`
            : 'RUNNING';
        setExperimentState('RUNNING', badgeText);

        if (btnStartExperiment) btnStartExperiment.disabled = true;
        if (btnRunAllAlgorithms) btnRunAllAlgorithms.disabled = true;
        if (btnStopExperiment) btnStopExperiment.disabled = false;

        // Reset network chunk counters for this run
        totalDownloadedBytes = 0;
        totalDownloadTimeSec = 0.0;
        downloadedChunksCount = 0;

        // Start experiment timer (updates display)
        if (experimentTimerInterval) clearInterval(experimentTimerInterval);
        experimentTimerInterval = setInterval(updateExperimentTimer, 250);

        // Begin playback
        if (video) {
            video.play().catch(e => {
                console.log('Autoplay handled, falling back to muted play:', e);
                video.muted = true;
                video.play().catch(err => console.error('Play error:', err));
            });
        }
    }

    function updateExperimentTimer() {
        if (!expTimer) return;
        const curMedia = video ? (video.currentTime || 0) : 0;
        const maxSec = (video && video.duration) ? video.duration : 30.0;
        expTimer.textContent = `${formatTime(curMedia)} / ${formatTime(maxSec)}`;

        // Watchdog timeout check (90s wall clock safety only)
        if (experimentStartTime !== null) {
            const wallElapsed = (performance.now() - experimentStartTime) / 1000.0;
            if (wallElapsed > 90.0) {
                console.warn('Watchdog timeout reached (90s) - stopping experiment');
                onExperimentFinished(false, 'TIMEOUT');
            }
        }
    }

    async function onExperimentFinished(isCompleted, reason = 'STOPPED') {
        if (experimentTimerInterval) {
            clearInterval(experimentTimerInterval);
            experimentTimerInterval = null;
        }

        if (video && !video.paused) {
            video.pause();
        }

        if (!isExperimentActive) {
            return;
        }

        // Finalize metrics exactly once
        isExperimentActive = false;
        const finalState = isCompleted ? 'COMPLETED' : reason;
        setExperimentState(finalState, finalState);

        const curTime = video ? (video.currentTime || 0) : 0;
        let currentTotalRebuffer = totalRebufferSec;
        if (isRebuffering && rebufferStartTime !== null) {
            currentTotalRebuffer += (performance.now() - rebufferStartTime) / 1000.0;
        }

        const playingSamples = telemetrySamples.filter(s => s.bitrateKbps > 0);
        let avgBitrateKbps = 0;
        if (playingSamples.length > 0) {
            const sumBitrate = playingSamples.reduce((acc, s) => acc + s.bitrateKbps, 0);
            avgBitrateKbps = Math.round(sumBitrate / playingSamples.length);
        } else if (lastRenderedBitrateKbps > 0) {
            avgBitrateKbps = lastRenderedBitrateKbps;
        }

        const bufferSamples = telemetrySamples.map(s => s.bufferLevelSec);
        const avgBufferSec = bufferSamples.length > 0
            ? bufferSamples.reduce((a, b) => a + b, 0) / bufferSamples.length
            : getBufferSec();

        const totalSessionTime = curTime + currentTotalRebuffer;
        const ratio = totalSessionTime > 0 ? (currentTotalRebuffer / totalSessionTime) : 0.0;

        const avgMeasuredTpKbps = totalDownloadTimeSec > 0
            ? (totalDownloadedBytes * 8) / (totalDownloadTimeSec * 1000.0)
            : 0.0;

        const avgChunkDownloadTime = downloadedChunksCount > 0
            ? totalDownloadTimeSec / downloadedChunksCount
            : 0.0;

        const estimatedSegments = Math.max(1, curTime / 2.0);
        const qualityUtility = QOE_ALPHA * ((avgBitrateKbps / 1000.0) * estimatedSegments);
        const stallPenalty = QOE_BETA * currentTotalRebuffer;
        const switchPenalty = QOE_GAMMA * (totalSwitchMagnitudeKbps / 1000.0);
        const computedQoE = (curTime > 0 || currentTotalRebuffer > 0)
            ? (qualityUtility - stallPenalty - switchPenalty)
            : 0.0;

        finalizedMetrics = {
            id: currentExperimentId || `exp-${Date.now()}`,
            algorithm: currentAbrMode,
            algorithmName: getAlgorithmTitle(currentAbrMode),
            networkScenario: activeNetworkScenario,
            startTime: new Date(Date.now() - (curTime * 1000)).toISOString(),
            endTime: new Date().toISOString(),
            durationSec: parseFloat(curTime.toFixed(2)),
            avgBitrateKbps: avgBitrateKbps,
            avgThroughputKbps: Math.round(avgMeasuredTpKbps),
            avgBufferSec: parseFloat(avgBufferSec.toFixed(2)),
            switchCount: renderedSwitchCount,
            stallCount: stallCount,
            totalRebufferSec: parseFloat(currentTotalRebuffer.toFixed(2)),
            rebufferRatio: parseFloat((ratio * 100).toFixed(2)),
            avgDownloadTimeSec: parseFloat(avgChunkDownloadTime.toFixed(3)),
            qoeScore: parseFloat(computedQoE.toFixed(2)),
            startupDelaySec: startupDelaySec !== null ? parseFloat(startupDelaySec.toFixed(2)) : 0.0,
            timestamp: new Date().toISOString()
        };

        // Render frozen statistics in UI
        renderFinalizedSessionStats(finalizedMetrics);

        // Post to Flask backend API
        try {
            const response = await fetch('/api/experiments', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(finalizedMetrics)
            });

            if (response.ok) {
                await fetchAndRenderExperiments();
            }
        } catch (err) {
            console.error('Failed to post experiment record:', err);
        }

        // Handle Run All sequence progression
        if (runAllActive) {
            if (runAllCancelRequested) {
                runAllActive = false;
                setExperimentState('CANCELLED', 'EVALUATION CANCELLED');
                if (runAllProgress) runAllProgress.style.display = 'none';
                if (btnStartExperiment) btnStartExperiment.disabled = false;
                if (btnRunAllAlgorithms) btnRunAllAlgorithms.disabled = false;
                if (btnStopExperiment) btnStopExperiment.disabled = true;
                return;
            }

            runAllIndex += 1;
            if (runAllIndex < runAllSequence.length) {
                setTimeout(() => {
                    if (runAllActive && !runAllCancelRequested) {
                        executeRunAllStep();
                    }
                }, 1000);
            } else {
                runAllActive = false;
                setExperimentState('COMPLETED', 'EVALUATION COMPLETE');
                if (runAllProgress) {
                    runAllProgress.textContent = 'All 3 Evaluated';
                    runAllProgress.style.display = 'inline-flex';
                }
                if (btnStartExperiment) btnStartExperiment.disabled = false;
                if (btnRunAllAlgorithms) btnRunAllAlgorithms.disabled = false;
                if (btnStopExperiment) btnStopExperiment.disabled = true;
            }
        } else {
            if (btnStartExperiment) btnStartExperiment.disabled = false;
            if (btnRunAllAlgorithms) btnRunAllAlgorithms.disabled = false;
            if (btnStopExperiment) btnStopExperiment.disabled = true;
        }
    }

    async function startRunAllSequence() {
        if (runAllActive || isExperimentActive) return; // Prevent duplicate overlap

        runAllActive = true;
        runAllIndex = 0;
        runAllCancelRequested = false;

        if (btnStartExperiment) btnStartExperiment.disabled = true;
        if (btnRunAllAlgorithms) btnRunAllAlgorithms.disabled = true;
        if (btnStopExperiment) btnStopExperiment.disabled = false;

        executeRunAllStep();
    }

    async function executeRunAllStep() {
        if (!runAllActive || runAllCancelRequested) {
            runAllActive = false;
            setExperimentState('CANCELLED', 'EVALUATION CANCELLED');
            if (runAllProgress) runAllProgress.style.display = 'none';
            if (btnStartExperiment) btnStartExperiment.disabled = false;
            if (btnRunAllAlgorithms) btnRunAllAlgorithms.disabled = false;
            if (btnStopExperiment) btnStopExperiment.disabled = true;
            return;
        }

        if (runAllIndex >= runAllSequence.length) {
            runAllActive = false;
            setExperimentState('COMPLETED', 'EVALUATION COMPLETE');
            if (runAllProgress) {
                runAllProgress.textContent = 'All 3 Evaluated';
                runAllProgress.style.display = 'inline-flex';
            }
            if (btnStartExperiment) btnStartExperiment.disabled = false;
            if (btnRunAllAlgorithms) btnRunAllAlgorithms.disabled = false;
            if (btnStopExperiment) btnStopExperiment.disabled = true;
            return;
        }

        const algo = runAllSequence[runAllIndex];
        const algoTitle = getAlgorithmTitle(algo);

        // Update progress badge
        if (runAllProgress) {
            runAllProgress.textContent = `Algorithm ${runAllIndex + 1} of 3: ${algoTitle}`;
            runAllProgress.style.display = 'inline-flex';
        }

        setAbrMode(algo);
        await prepareCleanRun();

        startExperiment();
    }

    function stopExperiment(isAutoFromRunAll = false) {
        if (runAllActive) {
            runAllCancelRequested = true;
            runAllActive = false;
            if (runAllProgress) runAllProgress.style.display = 'none';
        }

        onExperimentFinished(false, 'STOPPED');
    }

    async function resetExperiment() {
        if (runAllActive) {
            runAllActive = false;
            runAllCancelRequested = true;
            if (runAllProgress) runAllProgress.style.display = 'none';
        }

        if (experimentTimerInterval) {
            clearInterval(experimentTimerInterval);
            experimentTimerInterval = null;
        }

        isExperimentActive = false;
        finalizedMetrics = null;

        if (video) {
            video.pause();
            try { video.currentTime = 0; } catch (e) {}
        }

        setExperimentState('IDLE', 'IDLE');
        await prepareCleanRun();

        if (btnStartExperiment) btnStartExperiment.disabled = false;
        if (btnRunAllAlgorithms) btnRunAllAlgorithms.disabled = false;
        if (btnStopExperiment) btnStopExperiment.disabled = true;
    }

    // =========================================================================
    // Persistent Comparison API & Chart Visualizations
    // =========================================================================
    async function fetchAndRenderExperiments() {
        try {
            const res = await fetch('/api/experiments');
            if (!res.ok) return;
            const data = await res.json();
            storedExperiments = Array.isArray(data) ? data : [];

            renderComparisonTable(storedExperiments);
            renderAllComparisonCharts(storedExperiments);
        } catch (e) {
            console.error('Failed to fetch experiments:', e);
        }
    }

    function renderComparisonTable(experiments) {
        if (!comparisonTableBody) return;
        comparisonTableBody.innerHTML = '';

        if (!experiments || experiments.length === 0) {
            if (emptyComparisonMsg) emptyComparisonMsg.style.display = 'block';
            if (comparisonCountBadge) comparisonCountBadge.textContent = '0 Runs Recorded';
            return;
        }

        if (emptyComparisonMsg) emptyComparisonMsg.style.display = 'none';
        if (comparisonCountBadge) {
            comparisonCountBadge.textContent = `${experiments.length} Run${experiments.length === 1 ? '' : 's'} Recorded`;
        }

        experiments.forEach((exp, idx) => {
            const row = document.createElement('tr');

            let algoBadgeClass = 'pill-blue';
            if (exp.algorithm === 'buffer') algoBadgeClass = 'pill-amber';
            else if (exp.algorithm === 'hybrid') algoBadgeClass = 'pill-green';

            const timeStr = exp.timestamp ? new Date(exp.timestamp).toLocaleTimeString() : '--';

            row.innerHTML = `
                <td><strong>#${idx + 1}</strong></td>
                <td>${timeStr}</td>
                <td><span class="algo-pill ${algoBadgeClass}">${exp.algorithmName || exp.algorithm}</span></td>
                <td>${exp.networkScenario || 'Default'}</td>
                <td><strong>${exp.avgBitrateKbps || 0} kbps</strong></td>
                <td>${(exp.avgBufferSec || 0).toFixed(1)}s</td>
                <td>${exp.stallCount || 0}</td>
                <td>${(exp.totalRebufferSec || 0).toFixed(2)}s</td>
                <td>${(exp.rebufferRatio || 0).toFixed(1)}%</td>
                <td>${exp.switchCount || 0}</td>
                <td style="font-weight: 700; color: ${exp.qoeScore >= 0 ? '#6ee7b7' : '#fca5a5'};">
                    ${(exp.qoeScore || 0).toFixed(2)}
                </td>
            `;

            comparisonTableBody.appendChild(row);
        });
    }

    async function clearAllStoredExperiments() {
        if (!confirm('Clear all stored comparison experiment records?')) return;
        try {
            const res = await fetch('/api/experiments', { method: 'DELETE' });
            if (res.ok) {
                storedExperiments = [];
                renderComparisonTable([]);
                renderAllComparisonCharts([]);
            }
        } catch (e) {
            console.error('Failed to clear experiments:', e);
        }
    }

    function renderAllComparisonCharts(experiments = storedExperiments) {
        if (compChartQoE) renderBarChart(compChartQoE, experiments, 'qoeScore', 'Score', true);
        if (compChartBitrate) renderBarChart(compChartBitrate, experiments, 'avgBitrateKbps', 'kbps', false);
        if (compChartStalls) renderBarChart(compChartStalls, experiments, 'totalRebufferSec', 'sec', false);
        if (compChartSwitches) renderBarChart(compChartSwitches, experiments, 'switchCount', 'switches', false);
    }

    function renderBarChart(canvas, data, field, unit, allowNegative) {
        const { ctx, width, height } = setupCanvas(canvas);

        const padLeft = 45;
        const padRight = 15;
        const padTop = 15;
        const padBottom = 25;
        const chartW = width - padLeft - padRight;
        const chartH = height - padTop - padBottom;

        if (!data || data.length === 0) {
            ctx.fillStyle = '#6b7280';
            ctx.textAlign = 'center';
            ctx.font = '11px -apple-system, sans-serif';
            ctx.fillText('No experiment runs to compare yet', width / 2, height / 2);
            return;
        }

        const values = data.map(d => parseFloat(d[field]) || 0);
        let maxVal = Math.max(...values, 1);
        let minVal = allowNegative ? Math.min(...values, 0) : 0;

        if (maxVal === minVal) maxVal += 1;

        // Draw horizontal baseline
        ctx.strokeStyle = '#374151';
        ctx.lineWidth = 1;
        ctx.beginPath();
        const zeroY = padTop + chartH - ((0 - minVal) / (maxVal - minVal)) * chartH;
        ctx.moveTo(padLeft, zeroY);
        ctx.lineTo(padLeft + chartW, zeroY);
        ctx.stroke();

        // Bar layout
        const barCount = data.length;
        const barWidth = Math.max(12, Math.min(36, (chartW / barCount) * 0.65));
        const barSpacing = chartW / barCount;

        data.forEach((d, i) => {
            const val = parseFloat(d[field]) || 0;
            const x = padLeft + (i * barSpacing) + (barSpacing - barWidth) / 2;

            const y = padTop + chartH - ((val - minVal) / (maxVal - minVal)) * chartH;
            const barH = zeroY - y;

            // Bar color by algorithm
            let barColor = '#3b82f6'; // Throughput
            if (d.algorithm === 'buffer') barColor = '#f59e0b'; // Buffer
            else if (d.algorithm === 'hybrid') barColor = '#10b981'; // Hybrid

            ctx.fillStyle = barColor;
            if (barH >= 0) {
                ctx.fillRect(x, y, barWidth, barH);
            } else {
                ctx.fillRect(x, zeroY, barWidth, Math.abs(barH));
            }

            // Top value label
            ctx.fillStyle = '#d1d5db';
            ctx.textAlign = 'center';
            ctx.font = '9px monospace';
            const labelY = barH >= 0 ? y - 4 : zeroY + Math.abs(barH) + 10;
            ctx.fillText(val.toFixed(1), x + barWidth / 2, labelY);

            // Bottom X-axis label
            ctx.fillStyle = '#9ca3af';
            ctx.fillText(`#${i + 1}`, x + barWidth / 2, padTop + chartH + 12);
        });
    }

    // =========================================================================
    // Mininet Scenario Selector & Command Copy Helper
    // =========================================================================
    function initNetworkControls() {
        if (networkScenarioSelect) {
            networkScenarioSelect.addEventListener('change', function () {
                activeNetworkScenario = this.value;
                const cmd = MININET_COMMANDS[this.value] || MININET_COMMANDS['Custom'];
                if (mininetCommandText) mininetCommandText.textContent = cmd;
            });
        }

        if (btnCopyMininetCmd && mininetCommandText) {
            btnCopyMininetCmd.addEventListener('click', function () {
                const text = mininetCommandText.textContent;
                navigator.clipboard.writeText(text).then(() => {
                    btnCopyMininetCmd.textContent = 'Copied!';
                    setTimeout(() => {
                        btnCopyMininetCmd.textContent = 'Copy';
                    }, 1500);
                }).catch(err => {
                    console.error('Clipboard copy failed:', err);
                });
            });
        }
    }

    // =========================================================================
    // Mode UI Selection Listeners
    // =========================================================================
    function initModeControls() {
        // Algorithm Cards clicks
        if (cardAlgoThroughput) {
            cardAlgoThroughput.addEventListener('click', () => setAbrMode('throughput'));
        }
        if (cardAlgoBuffer) {
            cardAlgoBuffer.addEventListener('click', () => setAbrMode('buffer'));
        }
        if (cardAlgoHybrid) {
            cardAlgoHybrid.addEventListener('click', () => setAbrMode('hybrid'));
        }

        // Dropdown changes
        if (abrModeSelect) {
            abrModeSelect.addEventListener('change', function () {
                const newMode = this.value;
                if (newMode === 'manual') {
                    let targetQ = parseInt(qualitySelect.value, 10);
                    if (isNaN(targetQ) && videoBitrates.length > 0) {
                        targetQ = videoBitrates[0].qualityIndex;
                    }
                    setAbrMode('manual', targetQ);
                } else {
                    setAbrMode(newMode);
                }
            });
        }

        if (qualitySelect) {
            qualitySelect.addEventListener('change', function () {
                const val = this.value;
                if (val === 'auto') {
                    setAbrMode(currentAbrMode === 'manual' ? 'hybrid' : currentAbrMode);
                } else {
                    setAbrMode('manual', parseInt(val, 10));
                }
            });
        }
    }

    // =========================================================================
    // Real-Time Playback Charts (Bitrate & Buffer Occupancy)
    // =========================================================================
    function initChartControls() {
        if (!tabBitrate || !tabBuffer || !bitrateCanvas || !bufferCanvas) return;

        tabBitrate.addEventListener('click', function () {
            activeChart = 'bitrate';
            tabBitrate.classList.add('active');
            tabBuffer.classList.remove('active');
            bitrateCanvas.style.display = 'block';
            bufferCanvas.style.display = 'none';
            if (bitrateLegend) bitrateLegend.style.display = 'flex';
            if (bufferLegend) bufferLegend.style.display = 'none';
            redrawCharts();
        });

        tabBuffer.addEventListener('click', function () {
            activeChart = 'buffer';
            tabBuffer.classList.add('active');
            tabBitrate.classList.remove('active');
            bufferCanvas.style.display = 'block';
            bitrateCanvas.style.display = 'none';
            if (bufferLegend) bufferLegend.style.display = 'flex';
            if (bitrateLegend) bitrateLegend.style.display = 'none';
            redrawCharts();
        });
    }

    function redrawCharts() {
        if (activeChart === 'bitrate' && bitrateCanvas && bitrateCanvas.style.display !== 'none') {
            renderBitrateChart(bitrateCanvas);
        } else if (activeChart === 'buffer' && bufferCanvas && bufferCanvas.style.display !== 'none') {
            renderBufferChart(bufferCanvas);
        }
    }

    function setupCanvas(canvas) {
        const dpr = window.devicePixelRatio || 1;
        const rect = canvas.getBoundingClientRect();
        const width = Math.max(200, Math.floor(rect.width));
        const height = Math.max(120, Math.floor(rect.height || 190));

        if (canvas.width !== width * dpr || canvas.height !== height * dpr) {
            canvas.width = width * dpr;
            canvas.height = height * dpr;
        }

        const ctx = canvas.getContext('2d');
        ctx.resetTransform();
        ctx.scale(dpr, dpr);
        ctx.clearRect(0, 0, width, height);

        return { ctx, width, height };
    }

    function renderBitrateChart(canvas) {
        const { ctx, width, height } = setupCanvas(canvas);

        const padLeft = 70;
        const padRight = 20;
        const padTop = 15;
        const padBottom = 25;
        const chartW = width - padLeft - padRight;
        const chartH = height - padTop - padBottom;

        const maxBitrate = 3200;
        const maxTime = Math.max(30, (video && video.duration) ? video.duration : 30);

        const tiers = [
            { name: '360p', kbps: 400 },
            { name: '480p', kbps: 800 },
            { name: '720p', kbps: 1500 },
            { name: '1080p', kbps: 3000 }
        ];

        ctx.textAlign = 'right';
        ctx.textBaseline = 'middle';
        ctx.font = '10px -apple-system, sans-serif';

        tiers.forEach(tier => {
            const y = padTop + chartH - (tier.kbps / maxBitrate) * chartH;
            ctx.strokeStyle = '#2d3748';
            ctx.setLineDash([3, 3]);
            ctx.beginPath();
            ctx.moveTo(padLeft, y);
            ctx.lineTo(padLeft + chartW, y);
            ctx.stroke();

            ctx.fillStyle = '#9ca3af';
            ctx.fillText(`${tier.name} (${tier.kbps}k)`, padLeft - 6, y);
        });

        ctx.setLineDash([]);
        ctx.strokeStyle = '#374151';
        ctx.beginPath();
        ctx.moveTo(padLeft, padTop + chartH);
        ctx.lineTo(padLeft + chartW, padTop + chartH);
        ctx.stroke();

        ctx.textAlign = 'center';
        ctx.textBaseline = 'top';
        for (let t = 0; t <= maxTime; t += 5) {
            const x = padLeft + (t / maxTime) * chartW;
            ctx.fillStyle = '#6b7280';
            ctx.fillText(`${t}s`, x, padTop + chartH + 5);

            ctx.strokeStyle = '#1f2937';
            ctx.beginPath();
            ctx.moveTo(x, padTop);
            ctx.lineTo(x, padTop + chartH);
            ctx.stroke();
        }

        if (telemetrySamples.length < 2) {
            ctx.fillStyle = '#6b7280';
            ctx.textAlign = 'center';
            ctx.fillText('Awaiting playback telemetry...', padLeft + chartW / 2, padTop + chartH / 2);
            return;
        }

        const pts = telemetrySamples.map(s => ({
            x: padLeft + Math.min(1.0, Math.max(0, s.mediaTimeSec / maxTime)) * chartW,
            y: padTop + chartH - Math.min(1.0, Math.max(0, s.bitrateKbps / maxBitrate)) * chartH
        }));

        const grad = ctx.createLinearGradient(0, padTop, 0, padTop + chartH);
        grad.addColorStop(0, 'rgba(59, 130, 246, 0.35)');
        grad.addColorStop(1, 'rgba(59, 130, 246, 0.02)');

        ctx.beginPath();
        ctx.moveTo(pts[0].x, padTop + chartH);
        pts.forEach(p => ctx.lineTo(p.x, p.y));
        ctx.lineTo(pts[pts.length - 1].x, padTop + chartH);
        ctx.closePath();
        ctx.fillStyle = grad;
        ctx.fill();

        ctx.beginPath();
        ctx.moveTo(pts[0].x, pts[0].y);
        for (let i = 1; i < pts.length; i++) {
            ctx.lineTo(pts[i].x, pts[i].y);
        }
        ctx.strokeStyle = '#3b82f6';
        ctx.lineWidth = 2;
        ctx.stroke();

        const lastPt = pts[pts.length - 1];
        ctx.beginPath();
        ctx.arc(lastPt.x, lastPt.y, 4, 0, Math.PI * 2);
        ctx.fillStyle = '#93c5fd';
        ctx.fill();
        ctx.strokeStyle = '#1d4ed8';
        ctx.stroke();
    }

    function renderBufferChart(canvas) {
        const { ctx, width, height } = setupCanvas(canvas);

        const padLeft = 50;
        const padRight = 20;
        const padTop = 15;
        const padBottom = 25;
        const chartW = width - padLeft - padRight;
        const chartH = height - padTop - padBottom;

        const maxBufferSec = 25.0;
        const targetBufferSec = 10.0;
        const maxTime = Math.max(30, (video && video.duration) ? video.duration : 30);

        ctx.textAlign = 'right';
        ctx.textBaseline = 'middle';
        ctx.font = '10px -apple-system, sans-serif';

        for (let b = 0; b <= maxBufferSec; b += 5) {
            const y = padTop + chartH - (b / maxBufferSec) * chartH;
            ctx.strokeStyle = (b === targetBufferSec) ? 'rgba(245, 158, 11, 0.4)' : '#2d3748';
            ctx.setLineDash((b === targetBufferSec) ? [4, 4] : [2, 3]);
            ctx.beginPath();
            ctx.moveTo(padLeft, y);
            ctx.lineTo(padLeft + chartW, y);
            ctx.stroke();

            ctx.fillStyle = (b === targetBufferSec) ? '#fde68a' : '#9ca3af';
            ctx.fillText(`${b}s`, padLeft - 6, y);
        }

        ctx.setLineDash([]);
        ctx.strokeStyle = '#374151';
        ctx.beginPath();
        ctx.moveTo(padLeft, padTop + chartH);
        ctx.lineTo(padLeft + chartW, padTop + chartH);
        ctx.stroke();

        ctx.textAlign = 'center';
        ctx.textBaseline = 'top';
        for (let t = 0; t <= maxTime; t += 5) {
            const x = padLeft + (t / maxTime) * chartW;
            ctx.fillStyle = '#6b7280';
            ctx.fillText(`${t}s`, x, padTop + chartH + 5);

            ctx.strokeStyle = '#1f2937';
            ctx.beginPath();
            ctx.moveTo(x, padTop);
            ctx.lineTo(x, padTop + chartH);
            ctx.stroke();
        }

        if (telemetrySamples.length < 2) {
            ctx.fillStyle = '#6b7280';
            ctx.textAlign = 'center';
            ctx.fillText('Awaiting buffer telemetry...', padLeft + chartW / 2, padTop + chartH / 2);
            return;
        }

        const pts = telemetrySamples.map(s => ({
            x: padLeft + Math.min(1.0, Math.max(0, s.mediaTimeSec / maxTime)) * chartW,
            y: padTop + chartH - Math.min(1.0, Math.max(0, s.bufferLevelSec / maxBufferSec)) * chartH
        }));

        const grad = ctx.createLinearGradient(0, padTop, 0, padTop + chartH);
        grad.addColorStop(0, 'rgba(16, 185, 129, 0.35)');
        grad.addColorStop(1, 'rgba(16, 185, 129, 0.02)');

        ctx.beginPath();
        ctx.moveTo(pts[0].x, padTop + chartH);
        pts.forEach(p => ctx.lineTo(p.x, p.y));
        ctx.lineTo(pts[pts.length - 1].x, padTop + chartH);
        ctx.closePath();
        ctx.fillStyle = grad;
        ctx.fill();

        ctx.beginPath();
        ctx.moveTo(pts[0].x, pts[0].y);
        for (let i = 1; i < pts.length; i++) {
            ctx.lineTo(pts[i].x, pts[i].y);
        }
        ctx.strokeStyle = '#10b981';
        ctx.lineWidth = 2;
        ctx.stroke();

        const lastPt = pts[pts.length - 1];
        ctx.beginPath();
        ctx.arc(lastPt.x, lastPt.y, 4, 0, Math.PI * 2);
        ctx.fillStyle = '#6ee7b7';
        ctx.fill();
        ctx.strokeStyle = '#047857';
        ctx.stroke();
    }

    // =========================================================================
    // CSV and JSON Telemetry Exports
    // =========================================================================
    function initExportControls() {
        if (exportCsvBtn) {
            exportCsvBtn.addEventListener('click', exportSessionCsv);
        }
        if (exportJsonBtn) {
            exportJsonBtn.addEventListener('click', exportSessionJson);
        }
    }

    function exportSessionCsv() {
        if (telemetrySamples.length === 0) {
            alert('No telemetry collected yet. Start playback before exporting.');
            return;
        }

        const lines = [];
        const timestamp = new Date().toISOString().replace(/[:.]/g, '-');
        const modeStr = getModeDisplayName();

        lines.push('# Computer Networks Project - MPEG-DASH Playback Session Telemetry');
        lines.push(`# Exported: ${new Date().toISOString()}`);
        lines.push(`# Active ABR Mode: ${modeStr}`);
        lines.push(`# Mininet Scenario: ${activeNetworkScenario}`);
        lines.push(`# Startup Delay (s): ${startupDelaySec !== null ? startupDelaySec.toFixed(3) : 'N/A'}`);
        lines.push(`# Total Playback Time (s): ${video ? video.currentTime.toFixed(2) : 0}`);
        lines.push(`# Stall Count: ${stallCount}`);
        lines.push(`# Total Rebuffer Time (s): ${totalRebufferSec.toFixed(3)}`);
        lines.push(`# Switch Count (Rendered): ${renderedSwitchCount}`);
        lines.push(`# Cumulative Switch Magnitude (kbps): ${Math.round(totalSwitchMagnitudeKbps)}`);
        lines.push(`# Session QoE Score: ${statSessionQoE ? statSessionQoE.textContent : '0.00'}`);
        lines.push('');

        lines.push('# --- TIME SERIES TELEMETRY ---');
        lines.push('timestamp_iso,media_time_sec,buffer_level_sec,rendered_bitrate_kbps,rendered_resolution,playback_state,abr_mode');
        telemetrySamples.forEach(s => {
            lines.push(`${s.timestampIso},${s.mediaTimeSec},${s.bufferLevelSec},${s.bitrateKbps},"${s.resolution}",${s.playbackState},"${s.abrMode}"`);
        });

        lines.push('');
        lines.push('# --- QUALITY SWITCH & DECISION TIMELINE ---');
        lines.push('event_type,clock_time,media_time_sec,old_quality,new_quality,bitrate_kbps,buffer_sec,mode,reason');
        switchEvents.forEach(e => {
            lines.push(`${e.type},${e.clockTime},${e.mediaTimeSec},"${e.oldQuality}","${e.newQuality}",${e.bitrateKbps},${e.bufferSec},"${e.mode}","${e.reason || ''}"`);
        });

        const csvContent = lines.join('\n');
        downloadBlob(csvContent, `cn_abr_browser_session_${timestamp}.csv`, 'text/csv;charset=utf-8;');
    }

    function exportSessionJson() {
        if (telemetrySamples.length === 0) {
            alert('No telemetry collected yet. Start playback before exporting.');
            return;
        }

        const timestamp = new Date().toISOString();
        const modeStr = getModeDisplayName();

        const exportData = {
            session_metadata: {
                timestamp: timestamp,
                manifest_url: video ? (video.getAttribute('data-manifest') || '/dash/stream.mpd') : '/dash/stream.mpd',
                video_duration_sec: video ? video.duration : 30.0,
                active_network_scenario: activeNetworkScenario,
                user_agent: navigator.userAgent
            },
            performance_summary: {
                active_abr_mode: modeStr,
                startup_delay_sec: startupDelaySec,
                total_playback_time_sec: video ? parseFloat(video.currentTime.toFixed(2)) : 0.0,
                stall_count: stallCount,
                total_rebuffer_sec: parseFloat(totalRebufferSec.toFixed(3)),
                rebuffer_ratio: statRebufferRatio ? statRebufferRatio.textContent : '0.00%',
                average_bitrate_kbps: statAvgBitrate ? parseInt(statAvgBitrate.textContent, 10) || 0 : 0,
                switch_count_rendered: renderedSwitchCount,
                total_switch_magnitude_kbps: Math.round(totalSwitchMagnitudeKbps),
                session_qoe_score: statSessionQoE ? parseFloat(statSessionQoE.textContent) : 0.0
            },
            switch_timeline_events: switchEvents,
            telemetry_samples: telemetrySamples
        };

        const jsonContent = JSON.stringify(exportData, null, 2);
        const fileTimestamp = timestamp.replace(/[:.]/g, '-');
        downloadBlob(jsonContent, `cn_abr_browser_session_${fileTimestamp}.json`, 'application/json');
    }

    function downloadBlob(content, filename, mimeType) {
        const blob = new Blob([content], { type: mimeType });
        const url = URL.createObjectURL(blob);
        const link = document.createElement('a');
        link.href = url;
        link.download = filename;
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
        URL.revokeObjectURL(url);
    }

    function debounce(func, wait) {
        let timeout;
        return function (...args) {
            clearTimeout(timeout);
            timeout = setTimeout(() => func.apply(this, args), wait);
        };
    }

    function onPlayerError(e) {
        const msg = e && e.error ? (e.error.message || JSON.stringify(e.error)) : 'Unknown DASH error occurred.';
        showError(`DASH Playback Error: ${msg}`);
    }

    // =========================================================================
    // DOM Readiness Entrypoint
    // =========================================================================
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initPlayer);
    } else {
        initPlayer();
    }
})();
