/**
 * Proposed QoE-Driven Hybrid ABR Algorithm (JavaScript Port)
 * 
 * Ported faithfully from Python reference implementation:
 * src/algorithms/hybrid.py
 * 
 * Core Concept:
 * Combines throughput estimation, prediction error (uncertainty), buffer trajectory,
 * expected segment download times, and quality switching penalties into a joint decision
 * framework.
 * 
 * Universal module: Works in Node.js (CommonJS) and browser (window.HybridQoEController).
 * Independent of DOM and dash.js.
 */

(function (root, factory) {
    if (typeof module === 'object' && module.exports) {
        // Node.js / CommonJS
        module.exports = factory();
    } else if (typeof define === 'function' && define.amd) {
        // AMD
        define([], factory);
    } else {
        // Browser Global
        const exported = factory();
        root.HybridQoEController = exported.HybridQoEController;
        root.ThroughputBasedController = exported.ThroughputBasedController;
        root.BufferBasedController = exported.BufferBasedController;
    }
}(typeof self !== 'undefined' ? self : this, function () {
    'use strict';

    /**
     * Helper to read option allowing both camelCase and snake_case keys.
     */
    function getOption(options, camelKey, snakeKey, defaultValue) {
        if (options[camelKey] !== undefined) return options[camelKey];
        if (options[snakeKey] !== undefined) return options[snakeKey];
        return defaultValue;
    }

    class HybridQoEController {
        /**
         * Initialize the HybridQoEController algorithm.
         * Accepts both camelCase and snake_case configuration keys for seamless parity.
         * 
         * @param {Object} [options={}] Configuration options matching Python HybridQoEABR.
         */
        constructor(options = {}) {
            const rawLadder = getOption(
                options,
                'bitrateLadderKbps',
                'bitrate_ladder_kbps',
                [300, 750, 1200, 1850, 2850, 4300]
            );
            this.bitrateLadderKbps = [...rawLadder].sort((a, b) => a - b);

            this.segmentDurationSec = Number(getOption(options, 'segmentDurationSec', 'segment_duration_sec', 2.0));
            this.safetyFactorBase = Number(getOption(options, 'safetyFactorBase', 'safety_factor_base', 0.90));
            this.safetyFactorMin = Number(getOption(options, 'safetyFactorMin', 'safety_factor_min', 0.60));
            this.volatilityWeight = Number(getOption(options, 'volatilityWeight', 'volatility_weight', 0.30));
            this.reservoirSec = Number(getOption(options, 'reservoirSec', 'reservoir_sec', 5.0));
            this.cushionSec = Number(getOption(options, 'cushionSec', 'cushion_sec', 10.0));
            this.stallSafetyMarginSec = Number(getOption(options, 'stallSafetyMarginSec', 'stall_safety_margin_sec', 0.5));
            this.switchPenaltyLambda = Number(getOption(options, 'switchPenaltyLambda', 'switch_penalty_lambda', 0.5));
            this.windowSize = Number(getOption(options, 'windowSize', 'window_size', 5));

            const rawInit = getOption(options, 'initialBitrateKbps', 'initial_bitrate_kbps', null);
            this.initialBitrateKbps = rawInit !== null && rawInit !== undefined
                ? Number(rawInit)
                : this.bitrateLadderKbps[0];

            // Parameter validation matching Python
            if (!(0.0 < this.safetyFactorMin && this.safetyFactorMin <= this.safetyFactorBase && this.safetyFactorBase <= 1.0)) {
                throw new Error("Safety factors must satisfy 0.0 < min <= base <= 1.0");
            }
            if (this.reservoirSec < 0 || this.cushionSec <= 0) {
                throw new Error("Reservoir must be >= 0 and Cushion must be > 0");
            }
            if (this.windowSize < 1) {
                throw new Error("Window size must be at least 1");
            }

            // Internal State tracking
            this.throughputHistory = [];
            this.estimatedThroughputKbps = 0.0;
            this.lastSelectedBitrate = null;
            this.representations = [];
        }

        /**
         * Sets the representation ladder dynamically from DASH stream metadata.
         * 
         * @param {Array<number|Object>} reps Array of bitrates in kbps or representation objects.
         */
        setBitrateLadder(reps) {
            if (!Array.isArray(reps) || reps.length === 0) return;

            if (typeof reps[0] === 'number') {
                this.bitrateLadderKbps = [...reps].sort((a, b) => a - b);
                this.representations = this.bitrateLadderKbps.map((rate, idx) => ({
                    qualityIndex: idx,
                    bitrateKbps: rate,
                    bitrate: rate * 1000
                }));
            } else {
                // Array of representation objects: [{ qualityIndex: 0, bitrate: 400000, width: 640, height: 360 }, ...]
                this.representations = [...reps].sort((a, b) => a.bitrate - b.bitrate);
                this.bitrateLadderKbps = this.representations.map(r => Math.round(r.bitrate / 1000));
            }

            if (!this.bitrateLadderKbps.includes(this.initialBitrateKbps)) {
                this.initialBitrateKbps = this.bitrateLadderKbps[0];
            }
        }

        /**
         * Records the observed throughput sample and updates the harmonic mean estimate.
         * 
         * @param {number} lastThroughputKbps Observed throughput of the last completed segment in kbps.
         */
        updateThroughputState(lastThroughputKbps) {
            if (lastThroughputKbps > 0.0) {
                this.throughputHistory.push(lastThroughputKbps);
                if (this.throughputHistory.length > this.windowSize) {
                    this.throughputHistory.shift();
                }

                // Harmonic mean estimate: conservative against upward outlier spikes
                let sumReciprocals = 0.0;
                for (let i = 0; i < this.throughputHistory.length; i++) {
                    const x = Math.max(this.throughputHistory[i], 1e-6);
                    sumReciprocals += 1.0 / x;
                }
                this.estimatedThroughputKbps = this.throughputHistory.length / sumReciprocals;
            }
        }

        /**
         * Computes the coefficient of variation (CV) of throughput measurements.
         * CV = std_dev / mean. Returns 0.0 if fewer than 2 samples exist.
         * 
         * @returns {number} Coefficient of variation.
         */
        computeVolatility() {
            if (this.throughputHistory.length < 2) {
                return 0.0;
            }

            const n = this.throughputHistory.length;
            let sum = 0.0;
            for (let i = 0; i < n; i++) {
                sum += this.throughputHistory[i];
            }
            const meanTp = sum / n;
            if (meanTp <= 1e-6) {
                return 0.0;
            }

            let sumSqDiff = 0.0;
            for (let i = 0; i < n; i++) {
                sumSqDiff += Math.pow(this.throughputHistory[i] - meanTp, 2);
            }
            const variance = sumSqDiff / n;
            const stdDev = Math.sqrt(variance);
            return stdDev / meanTp;
        }

        /**
         * Selects the bitrate optimizing visual quality, stall avoidance, and smoothness.
         * Exactly matches Python HybridQoEABR.select_bitrate.
         * 
         * @param {number} segmentIndex Sequential index of the chunk to download (0, 1, 2, ...).
         * @param {number} currentBufferSec Current playback buffer occupancy in seconds.
         * @param {number} lastThroughputKbps Throughput observed during previous download (kbps).
         * @param {number} lastDownloadTimeSec Duration taken by previous download (seconds).
         * @param {number|null} [lastBitrateKbps=null] Bitrate of the previous segment in kbps.
         * @returns {number} Selected bitrate in kbps from this.bitrateLadderKbps.
         */
        selectBitrate(segmentIndex, currentBufferSec, lastThroughputKbps, lastDownloadTimeSec, lastBitrateKbps = null) {
            const prevBitrate = lastBitrateKbps !== null && lastBitrateKbps !== undefined
                ? Number(lastBitrateKbps)
                : this.lastSelectedBitrate;

            // Step 1: Update throughput history
            if (lastThroughputKbps > 0.0) {
                this.updateThroughputState(lastThroughputKbps);
            }

            // Step 2: Handle initial segment or zero observations
            if (this.estimatedThroughputKbps <= 0.0) {
                const selected = this.initialBitrateKbps;
                this.lastSelectedBitrate = selected;
                return selected;
            }

            // Step 3: Critical Stall Protection (Reservoir Check)
            // If buffer is below reservoir, drop to lowest quality to prevent playback freeze
            if (currentBufferSec <= this.reservoirSec) {
                const selected = this.bitrateLadderKbps[0];
                this.lastSelectedBitrate = selected;
                return selected;
            }

            // Step 4: Volatility and Uncertainty Discount
            // High variation decreases the effective safety factor
            const cv = this.computeVolatility();
            const effectiveSafety = Math.max(
                this.safetyFactorMin,
                this.safetyFactorBase - (this.volatilityWeight * cv)
            );
            const effectiveBandwidth = this.estimatedThroughputKbps * effectiveSafety;

            // Step 5: Buffer-Guided Capacity Scaling
            // Scale bandwidth budget proportionally to cushion occupancy
            const targetBuffer = this.reservoirSec + this.cushionSec;
            let bandwidthBudget;
            if (currentBufferSec < targetBuffer) {
                const bufferFactor = (currentBufferSec - this.reservoirSec) / this.cushionSec;
                bandwidthBudget = effectiveBandwidth * bufferFactor;
            } else {
                bandwidthBudget = effectiveBandwidth;
            }

            // Step 6: Filter Feasible Candidate Bitrates
            // Must fit within bandwidthBudget and drain constraint
            let feasibleBitrates = [];
            const estTpSafe = Math.max(this.estimatedThroughputKbps, 1.0);
            const maxAllowedDownloadTime = currentBufferSec - this.stallSafetyMarginSec;

            for (let i = 0; i < this.bitrateLadderKbps.length; i++) {
                const rate = this.bitrateLadderKbps[i];
                const expDownloadTime = (rate * this.segmentDurationSec) / estTpSafe;
                if (rate <= bandwidthBudget && expDownloadTime < maxAllowedDownloadTime) {
                    feasibleBitrates.push(rate);
                }
            }

            // Fallback: if no bitrate passed budget and feasibility, pick minimum ladder rate
            if (feasibleBitrates.length === 0) {
                feasibleBitrates = [this.bitrateLadderKbps[0]];
            }

            // Step 7: Apply Cautious Step-Up Constraint
            // Prevent jumping multiple tiers upward in a single step
            if (prevBitrate !== null && prevBitrate !== undefined && this.bitrateLadderKbps.includes(prevBitrate)) {
                const prevIdx = this.bitrateLadderKbps.indexOf(prevBitrate);
                const maxAllowedIdx = Math.min(this.bitrateLadderKbps.length - 1, prevIdx + 1);
                const maxStepupBitrate = this.bitrateLadderKbps[maxAllowedIdx];

                // Require comfortable buffer (> reservoir + 30% cushion) before stepping up
                const stepupBufferReq = this.reservoirSec + (0.3 * this.cushionSec);
                const constrainedCandidates = [];

                for (let i = 0; i < feasibleBitrates.length; i++) {
                    const r = feasibleBitrates[i];
                    if (r > prevBitrate) {
                        if (r <= maxStepupBitrate && currentBufferSec >= stepupBufferReq) {
                            constrainedCandidates.push(r);
                        }
                    } else {
                        constrainedCandidates.push(r);
                    }
                }

                if (constrainedCandidates.length > 0) {
                    feasibleBitrates = constrainedCandidates;
                }
            }

            // Step 8: Objective Function Evaluation (Quality Utility - Switching Penalty)
            // Select the candidate that maximizes utility while penalizing frequent switches
            let bestBitrate = feasibleBitrates[0];
            let bestUtility = -Infinity;
            const refBitrate = (prevBitrate !== null && prevBitrate !== undefined)
                ? prevBitrate
                : this.bitrateLadderKbps[0];

            for (let i = 0; i < feasibleBitrates.length; i++) {
                const rate = feasibleBitrates[i];
                // Quality utility (in Mbps)
                const qualityUtility = rate / 1000.0;
                // Switch magnitude penalty (in Mbps)
                const switchPenalty = this.switchPenaltyLambda * (Math.abs(rate - refBitrate) / 1000.0);
                const score = qualityUtility - switchPenalty;

                // Strict inequality: earlier (lower) candidate wins ties across ascending ladder
                if (score > bestUtility) {
                    bestUtility = score;
                    bestBitrate = rate;
                }
            }

            this.lastSelectedBitrate = bestBitrate;
            this.lastReason = `EstTP: ${Math.round(this.estimatedThroughputKbps)}k, CV: ${cv.toFixed(2)}, Buf: ${currentBufferSec.toFixed(1)}s -> Selected ${bestBitrate}k`;
            return bestBitrate;
        }

        /**
         * Resolves the selected bitrate to the corresponding DASH representation index.
         * 
         * @param {number} bitrateKbps 
         * @returns {number} Representation index.
         */
        getRepresentationIndexForBitrate(bitrateKbps) {
            if (this.representations.length > 0) {
                const match = this.representations.find(r => {
                    const rKbps = r.bitrateKbps !== undefined ? r.bitrateKbps : Math.round(r.bitrate / 1000);
                    return rKbps === bitrateKbps;
                });
                if (match && match.qualityIndex !== undefined) {
                    return match.qualityIndex;
                }
            }
            return this.bitrateLadderKbps.indexOf(bitrateKbps);
        }

        /**
         * Resets estimator history and state variables between simulation runs.
         */
        reset() {
            this.throughputHistory = [];
            this.estimatedThroughputKbps = 0.0;
            this.lastSelectedBitrate = null;
            this.lastReason = '';
        }
    }

    /**
     * Throughput-Based ABR Algorithm (JavaScript Port)
     * 
     * Ported from Python reference: src/algorithms/throughput_based.py
     * Uses smoothed harmonic mean of past completed segment throughputs
     * scaled by a safety factor (default: 0.85).
     */
    class ThroughputBasedController {
        constructor(options = {}) {
            const rawLadder = getOption(
                options,
                'bitrateLadderKbps',
                'bitrate_ladder_kbps',
                [300, 750, 1200, 1850, 2850, 4300]
            );
            this.bitrateLadderKbps = [...rawLadder].sort((a, b) => a - b);
            this.safetyFactor = Number(getOption(options, 'safetyFactor', 'safety_factor', 0.85));
            this.windowSize = Number(getOption(options, 'windowSize', 'window_size', 5));
            this.estimationMethod = getOption(options, 'estimationMethod', 'estimation_method', 'harmonic');

            const rawInit = getOption(options, 'initialBitrateKbps', 'initial_bitrate_kbps', null);
            this.initialBitrateKbps = rawInit !== null && rawInit !== undefined
                ? Number(rawInit)
                : this.bitrateLadderKbps[0];

            this.throughputHistory = [];
            this.estimatedThroughputKbps = 0.0;
            this.lastSelectedBitrate = null;
            this.lastReason = '';
            this.representations = [];
        }

        setBitrateLadder(reps) {
            if (!Array.isArray(reps) || reps.length === 0) return;
            if (typeof reps[0] === 'number') {
                this.bitrateLadderKbps = [...reps].sort((a, b) => a - b);
                this.representations = this.bitrateLadderKbps.map((rate, idx) => ({
                    qualityIndex: idx,
                    bitrateKbps: rate,
                    bitrate: rate * 1000
                }));
            } else {
                this.representations = [...reps].sort((a, b) => a.bitrate - b.bitrate);
                this.bitrateLadderKbps = this.representations.map(r => Math.round(r.bitrate / 1000));
            }
            if (!this.bitrateLadderKbps.includes(this.initialBitrateKbps)) {
                this.initialBitrateKbps = this.bitrateLadderKbps[0];
            }
        }

        updateEstimate(lastThroughputKbps) {
            if (lastThroughputKbps > 0.0) {
                this.throughputHistory.push(lastThroughputKbps);
                if (this.throughputHistory.length > this.windowSize) {
                    this.throughputHistory.shift();
                }
                let sumReciprocals = 0.0;
                for (let i = 0; i < this.throughputHistory.length; i++) {
                    const x = Math.max(this.throughputHistory[i], 1e-6);
                    sumReciprocals += 1.0 / x;
                }
                this.estimatedThroughputKbps = this.throughputHistory.length / sumReciprocals;
            }
        }

        selectBitrate(segmentIndex, currentBufferSec, lastThroughputKbps, lastDownloadTimeSec, lastBitrateKbps) {
            if (lastThroughputKbps !== undefined && lastThroughputKbps !== null && lastThroughputKbps > 0.0) {
                this.updateEstimate(lastThroughputKbps);
            }

            if (this.estimatedThroughputKbps <= 0.0) {
                const initRate = this.initialBitrateKbps;
                this.lastSelectedBitrate = initRate;
                this.lastReason = `Cold-start or no throughput estimate: lowest tier (${initRate}k)`;
                return initRate;
            }

            const budget = this.estimatedThroughputKbps * this.safetyFactor;
            let selected = this.bitrateLadderKbps[0];
            for (let i = 0; i < this.bitrateLadderKbps.length; i++) {
                if (this.bitrateLadderKbps[i] <= budget) {
                    selected = this.bitrateLadderKbps[i];
                } else {
                    break;
                }
            }

            this.lastSelectedBitrate = selected;
            this.lastReason = `EstTP: ${Math.round(this.estimatedThroughputKbps)}k, Budget: ${Math.round(budget)}k (${Math.round(this.safetyFactor * 100)}%) -> Selected ${selected}k`;
            return selected;
        }

        getRepresentationIndexForBitrate(bitrateKbps) {
            if (this.representations.length > 0) {
                const match = this.representations.find(r => {
                    const rKbps = r.bitrateKbps !== undefined ? r.bitrateKbps : Math.round(r.bitrate / 1000);
                    return rKbps === bitrateKbps;
                });
                if (match && match.qualityIndex !== undefined) {
                    return match.qualityIndex;
                }
            }
            return this.bitrateLadderKbps.indexOf(bitrateKbps);
        }

        reset() {
            this.throughputHistory = [];
            this.estimatedThroughputKbps = 0.0;
            this.lastSelectedBitrate = null;
            this.lastReason = '';
        }
    }

    /**
     * Buffer-Based ABR Algorithm (JavaScript Port)
     * 
     * Ported from Python reference: src/algorithms/buffer_based.py
     * Uses reservoir (5s) and cushion (10s) piecewise mapping with hysteresis.
     */
    class BufferBasedController {
        constructor(options = {}) {
            const rawLadder = getOption(
                options,
                'bitrateLadderKbps',
                'bitrate_ladder_kbps',
                [300, 750, 1200, 1850, 2850, 4300]
            );
            this.bitrateLadderKbps = [...rawLadder].sort((a, b) => a - b);
            this.reservoirSec = Number(getOption(options, 'reservoirSec', 'reservoir_sec', 5.0));
            this.cushionSec = Number(getOption(options, 'cushionSec', 'cushion_sec', 10.0));
            this.hysteresisSec = Number(getOption(options, 'hysteresisSec', 'hysteresis_sec', 0.5));

            this.lastSelectedBitrate = null;
            this.lastReason = '';
            this.representations = [];
        }

        setBitrateLadder(reps) {
            if (!Array.isArray(reps) || reps.length === 0) return;
            if (typeof reps[0] === 'number') {
                this.bitrateLadderKbps = [...reps].sort((a, b) => a - b);
                this.representations = this.bitrateLadderKbps.map((rate, idx) => ({
                    qualityIndex: idx,
                    bitrateKbps: rate,
                    bitrate: rate * 1000
                }));
            } else {
                this.representations = [...reps].sort((a, b) => a.bitrate - b.bitrate);
                this.bitrateLadderKbps = this.representations.map(r => Math.round(r.bitrate / 1000));
            }
        }

        selectBitrate(segmentIndex, currentBufferSec, lastThroughputKbps, lastDownloadTimeSec, lastBitrateKbps) {
            const numLevels = this.bitrateLadderKbps.length;
            const prevBitrate = (lastBitrateKbps !== undefined && lastBitrateKbps !== null)
                ? lastBitrateKbps
                : this.lastSelectedBitrate;

            // Rule 1: Reservoir threshold (Critical Safety Zone)
            if (currentBufferSec <= this.reservoirSec) {
                const selected = this.bitrateLadderKbps[0];
                this.lastSelectedBitrate = selected;
                this.lastReason = `Buffer: ${currentBufferSec.toFixed(1)}s <= ${this.reservoirSec}s reservoir -> Lowest ${selected}k`;
                return selected;
            }

            // Rule 2: Upper threshold (Abundant Buffer Zone)
            const maxThreshold = this.reservoirSec + this.cushionSec;
            if (currentBufferSec >= maxThreshold) {
                const selected = this.bitrateLadderKbps[numLevels - 1];
                this.lastSelectedBitrate = selected;
                this.lastReason = `Buffer: ${currentBufferSec.toFixed(1)}s >= ${maxThreshold}s target -> Top ${selected}k`;
                return selected;
            }

            // Rule 3: Linear Mapping inside Cushion Zone
            const bufferFraction = (currentBufferSec - this.reservoirSec) / this.cushionSec;
            let targetIdx = Math.floor(bufferFraction * (numLevels - 1));
            targetIdx = Math.max(0, Math.min(numLevels - 1, targetIdx));
            let candidateBitrate = this.bitrateLadderKbps[targetIdx];
            let reason = `Buffer: ${currentBufferSec.toFixed(1)}s in cushion [${this.reservoirSec}-${maxThreshold}s] -> Tier ${targetIdx} (${candidateBitrate}k)`;

            // Rule 4: Anti-Oscillation Hysteresis
            if (prevBitrate !== null && prevBitrate !== undefined && this.bitrateLadderKbps.includes(prevBitrate)) {
                const prevIdx = this.bitrateLadderKbps.indexOf(prevBitrate);
                if (targetIdx > prevIdx) {
                    const stepThreshold = this.reservoirSec + (targetIdx / (numLevels - 1)) * this.cushionSec;
                    if (currentBufferSec < (stepThreshold + this.hysteresisSec)) {
                        candidateBitrate = prevBitrate;
                        reason = `Buffer: ${currentBufferSec.toFixed(1)}s < up-switch threshold + hyst (${(stepThreshold + this.hysteresisSec).toFixed(1)}s) -> Hold ${prevBitrate}k`;
                    }
                } else if (targetIdx < prevIdx) {
                    const prevThreshold = this.reservoirSec + (prevIdx / (numLevels - 1)) * this.cushionSec;
                    if (currentBufferSec > (prevThreshold - this.hysteresisSec)) {
                        candidateBitrate = prevBitrate;
                        reason = `Buffer: ${currentBufferSec.toFixed(1)}s > down-switch threshold - hyst (${(prevThreshold - this.hysteresisSec).toFixed(1)}s) -> Hold ${prevBitrate}k`;
                    }
                }
            }

            this.lastSelectedBitrate = candidateBitrate;
            this.lastReason = reason;
            return candidateBitrate;
        }

        getRepresentationIndexForBitrate(bitrateKbps) {
            if (this.representations.length > 0) {
                const match = this.representations.find(r => {
                    const rKbps = r.bitrateKbps !== undefined ? r.bitrateKbps : Math.round(r.bitrate / 1000);
                    return rKbps === bitrateKbps;
                });
                if (match && match.qualityIndex !== undefined) {
                    return match.qualityIndex;
                }
            }
            return this.bitrateLadderKbps.indexOf(bitrateKbps);
        }

        reset() {
            this.lastSelectedBitrate = null;
            this.lastReason = '';
        }
    }

    return { HybridQoEController, ThroughputBasedController, BufferBasedController };
}));
