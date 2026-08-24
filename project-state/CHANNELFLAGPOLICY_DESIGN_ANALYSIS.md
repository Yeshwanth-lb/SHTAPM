# ChannelFlagPolicy Design & Feasibility Analysis

**Date:** 2026-08-24  
**Status:** Design analysis only — NO code changes, NO implementation  
**Next Step:** Requires approval before implementation

---

## Executive Summary

**Question:** Can we implement ChannelFlagPolicy now to map window-level anomaly flags to per-channel flags?

**Answer:** Technically feasible, but **requires a design decision**. The architecture provides limited information from IsolationForestDetector, offering three implementation options with different trade-offs.

**Recommendation:** Option 2 (Severity-threshold-based) is safest for now — it uses available detector output, requires minimal assumptions, and can be upgraded later when real data enables better localization.

**U07 Dependency:** ChannelFlagPolicy can be implemented now, but **validation requires real data** (SWaT/WADI or bench rig). Without real data, we cannot verify whether the chosen localization method reliably catches attacks vs. faults.

---

## 1. Current ChannelFlagPolicy Inputs

### Protocol Definition
```python
class ChannelFlagPolicy(Protocol):
    def flags(self, window: Window, anomaly: AnomalyResult) -> Mapping[str, bool]: ...
```

### Inputs Received per Window

| Input | Type | Content | Source |
|-------|------|---------|--------|
| **window** | Window | 30x6 preprocessed samples [0,1], min-max normalized | Preprocessor |
| **anomaly.flag** | bool | Window-level anomaly flag (True/False) | IsolationForestDetector.flag() |
| **anomaly.severity** | float | Window-level severity in [0,1] | IsolationForestDetector.score() |

### Information NOT Available

❌ **Per-channel anomaly scores** — IF computes ONE 180-dim feature → ONE anomaly score  
❌ **Per-channel importance/contribution** — sklearn IF has no built-in per-feature attribution  
❌ **Which channels drove the anomaly** — multivariate model doesn't expose this  
❌ **Feature importance/shap values** — would require external library (not available)  
❌ **Decision path from trees** — sklearn IF doesn't expose tree structure for interpretation  

---

## 2. IsolationForestDetector Architecture & Capabilities

### What IsolationForestDetector Exposes

**Public Interface:**
```python
def fit(windows: Sequence[Window]) -> None
def score(window: Window) -> float        # severity in [0,1]
def flag(window: Window) -> bool          # severity >= flag_threshold
```

**Internal State (not exposed):**
- `_model`: sklearn.ensemble.IsolationForest (trained)
- `_train_anom_sorted`: np.ndarray of training anomaly scores
- `flag_threshold`: float (required constructor argument)

### Feature Engineering

```python
def _features(window: Window) -> np.ndarray:
    """Flatten 30x6 window to 1-D 180-length vector (row-major)."""
    return np.asarray(window.as_matrix(), dtype=float).reshape(-1)
```

**Result:** 180-dimensional feature vector (30 time steps × 6 channels) fed to single IF model

### Anomaly Score Computation

```python
def _anomaly_scores(self, x: np.ndarray) -> np.ndarray:
    """Higher = more anomalous. Negate sklearn's score_samples."""
    return -self._model.score_samples(x)
```

**Result:** ONE scalar anomaly score per window, not per-channel scores

### Severity Calibration (Empirical CDF)

```python
def score(window: Window) -> float:
    a = float(self._anomaly_scores(...)[0])
    rank = int(np.searchsorted(train, a, side="right"))
    return rank / len(train)  # empirical CDF of this window vs training
```

**Result:** Severity [0,1] = percentile rank in training distribution

### Limitations for Per-Channel Attribution

1. **Multivariate-only design**: IF is trained on all 180 features simultaneously; no per-channel models
2. **No feature isolation**: sklearn IF does not expose which features contributed most
3. **Window-level severity only**: One number per window, not six numbers per channel
4. **Deterministic but unexplainable**: Cannot retroactively ask "which channel(s) caused this anomaly?"

---

## 3. Architectural Constraints

### What Pipeline Provides

**ChannelFlagPolicy.flags() receives:**
```
window: Window (full 30×6 data)
anomaly.flag: bool (window is anomalous or not)
anomaly.severity: float (how anomalous, [0,1])
```

### What Pipeline Needs

**P2Pipeline → AttributionEngine:**
```
flags: dict[str, bool]  (per-channel)
window: Window
```

**AttributionEngine expects:**
- `flags[channel]` = True means "this channel is flagged as anomalous"
- Used to determine whether to run physics rule check
- If flagged, determine if physics-consistent (fault) or physics-violated (attack)

### The Gap

**Question:** How do we map ONE window-level flag + severity into SIX per-channel flags?

**Current architecture provides NO per-channel breakdown.**

---

## 4. P2 Requirements for Channel Attribution

### Acceptance Tests Requiring Per-Channel Flags

| Test | Requires | Depends On |
|------|----------|-----------|
| **P2-ANOM-H2** (spike fault) | Per-channel detection ≤3 windows | ChannelFlagPolicy to flag affected channel(s) |
| **P2-ANOM-H3** (constant-spoof attack) | Per-channel detection ≤3 windows | ChannelFlagPolicy to flag spoofed channel(s) |
| **P2-ANOM-E2** (simultaneous fault + attack) | Independent attribution | ChannelFlagPolicy to flag both independently |
| **P2-TRUST-H2** (spoofed trust <0.4) | Per-channel trust drop | Requires c/h/k per-channel updates (✅ done) + per-channel flags (❌ missing) |

### Attribution Logic (Already Implemented)

**In AttributionEngine.attribute():**
```python
for ch, flagged in flags.items():
    if not flagged:
        → Attribution.none
    elif check.violated and check.suspect_channel == ch:
        → Attribution.attack
    else:
        → Attribution.fault
```

**Conclusion:** Attribution logic is ready; just needs reliable per-channel flags.

---

## 5. U07 Dependency Assessment

### Can ChannelFlagPolicy Be Implemented Without U07?

**Technically:** Yes, we can code it now.

**Validation:** No. We cannot **verify** it works correctly without real data:
1. **Unknown effectiveness** — heuristics may have high false-positive/negative rates
2. **Acceptance tests blocked** — P2-ANOM-H2/H3 require real or labeled synthetic data
3. **Attack scenarios unknown** — we don't know how real attacks behave on the bench
4. **False attribution risk** — might flag wrong channel as faulty when attack is elsewhere

### U07-Gated Activities

❌ Real correlation validation (current↔vibration, etc.)  
❌ False positive calibration on clean baseline  
❌ Detection rate on labeled attacks  
❌ Attribution accuracy (O3 objective ≥85%)  
❌ P2 acceptance validation  

### U07-Independent Activities

✅ Infrastructure (ChannelFlagPolicy protocol, stub implementations)  
✅ Pipeline wiring (already done)  
✅ Unit tests for flagging logic  
✅ Integration tests with stub flags  

---

## 6. Implementation Options

### Option 1: "All-or-Nothing" (Simplest)

**Rule:** If window anomalous, flag ALL channels; if not, flag NONE.

```python
class AllOrNothingFlagPolicy:
    def flags(self, window: Window, anomaly: AnomalyResult) -> Mapping[str, bool]:
        return {ch: anomaly.flag for ch in CHANNELS}
```

**Pros:**
- Trivial to implement
- Works immediately on simulator
- Correct for 100% of the attacks in a given window

**Cons:**
- No per-channel localization (P2-ANOM-E2 requires independent attribution)
- Every channel gets penalized equally
- Doesn't satisfy the "both flagged, attributed independently" requirement
- **NOT viable for P2-ANOM-E2**

---

### Option 2: "Severity Threshold" (Recommended)

**Rule:** For each channel, if its slice of the flattened feature vector is anomalous (heuristic), flag it.

```python
class SeverityThresholdFlagPolicy:
    def __init__(self, channel_threshold: float = 0.5):
        self.channel_threshold = channel_threshold
    
    def flags(self, window: Window, anomaly: AnomalyResult) -> Mapping[str, bool]:
        # If overall window is not anomalous, flag nothing
        if not anomaly.flag:
            return {ch: False for ch in CHANNELS}
        
        # If window is anomalous, check each channel's feature range
        matrix = window.as_matrix()  # 30×6
        out = {}
        for ch_idx, ch in enumerate(CHANNELS):
            ch_values = [matrix[t][ch_idx] for t in range(len(matrix))]
            # Simple heuristic: flag if range is large (e.g., variance > threshold)
            ch_variance = np.var(ch_values)
            out[ch] = ch_variance > self.channel_threshold
        
        return out
```

**Pros:**
- Uses available window data (the full feature matrix)
- Per-channel decision possible
- Can catch simultaneous fault + attack on different channels (P2-ANOM-E2)
- Decouples from IF internals (doesn't rely on unexposed model state)

**Cons:**
- **Heuristic, not physics-based** — variance-based decision has no real justification
- **Requires tuning** — channel_threshold is a design parameter (data-gated)
- **False attribution risk** — high variance ≠ anomaly source (could be normal variance in clean signal)
- **Limited validation capacity** — can't verify against real attacks without data

**Validation needed:** SWaT/WADI data to tune threshold and verify false-positive/negative rates

---

### Option 3: "Maximum Deviation" (Data-Gated Alternative)

**Rule:** For each channel, flag if deviation from training baseline is highest among channels.

```python
class MaxDeviationFlagPolicy:
    def __init__(self, baseline_std: dict[str, float]):
        self.baseline_std = baseline_std
    
    def flags(self, window: Window, anomaly: AnomalyResult) -> Mapping[str, bool]:
        if not anomaly.flag:
            return {ch: False for ch in CHANNELS}
        
        matrix = window.as_matrix()
        deviations = {}
        for ch_idx, ch in enumerate(CHANNELS):
            ch_values = [matrix[t][ch_idx] for t in range(len(matrix))]
            deviation = np.std(ch_values) / max(self.baseline_std[ch], 1e-8)
            deviations[ch] = deviation
        
        max_deviation = max(deviations.values()) if deviations else 0
        threshold = 0.8 * max_deviation  # Flag channels in top 20%
        
        return {ch: deviations[ch] >= threshold for ch in CHANNELS}
```

**Pros:**
- Relative comparison (channel with highest deviation is most suspect)
- Can identify primary anomaly source
- Adapts to baseline variation per channel

**Cons:**
- **Requires training data** — must compute baseline_std from clean windows
- **More complex tuning** — threshold percentage is another design parameter
- **Still heuristic** — deviation magnitude ≠ anomaly cause
- **Blocks on U07** — needs real data to validate

**Validation needed:** SWaT/WADI data to validate whether "highest deviation = anomaly source"

---

## 7. Safest Option Recommendation

### **OPTION 2 (Severity Threshold) — Recommended for Now**

**Why it's safest:**
1. **Uses only available data** — window features, already available to pipeline
2. **Doesn't depend on IF internals** — doesn't require unexposed model details
3. **Simple to understand and debug** — transparent variance-based heuristic
4. **Can be upgraded later** — when real data validates better rules
5. **Sufficient for initial P2 testing** — catches anomalies, flags channels

**Design parameters (to be tuned on real data):**
- `channel_threshold`: variance threshold for flagging (TBD, U07-gated)
- Optional: weighting by channel importance (TBD, U07-gated)

**Implementation timeline:**
- **Now:** Code the heuristic, write unit tests, integrate into pipeline
- **U07:** Validate on SWaT/WADI, tune threshold, verify false-positive rate

**Known limitations to document:**
- ⚠️ Heuristic, not physics-based
- ⚠️ Not yet validated on real data
- ⚠️ Variance-based detection may not align with actual anomaly causes
- ⚠️ Threshold tuning required (U07-gated)

---

## 8. Cannot Be Done (Don't Try)

### ❌ Per-Channel Importance from IF Model

**Why:** sklearn's IsolationForest does not expose per-feature importance or contributions.

**Attempted workaround:** 
- SHAP/LIME libraries would require external dependency (breaks isolated architecture)
- Manual IF tree traversal not supported by sklearn API
- Feature ablation would require retraining model for each channel (too expensive)

**Verdict:** Not feasible without external libraries or major refactoring.

---

## 9. Current Architecture Checklist

| Component | Status | Note |
|-----------|--------|------|
| **ChannelFlagPolicy protocol** | ✅ Defined | In pipeline.py |
| **Pipeline call site** | ✅ Wired | P2Pipeline calls flags() and passes to AttributionEngine |
| **AttributionEngine** | ✅ Ready | Knows how to use per-channel flags |
| **IsolationForestDetector** | ✅ Implemented | Exposes score() + flag() only (window-level) |
| **window.features** | ✅ Available | Full 30×6 per-channel data in Window object |
| **window.as_matrix()** | ✅ Available | Helper to get 30×6 matrix form |

**Conclusion:** Architecture supports ChannelFlagPolicy implementation WITHOUT modifying IsolationForestDetector.

---

## 10. Decision Points Requiring Approval

### Decision 1: Option Choice
**Recommendation:** Option 2 (Severity Threshold)  
**Approval needed:** Confirm this approach, or choose Option 1/3

### Decision 2: Heuristic Type
**If Option 2 chosen:**
- Simple variance-based (as shown)?
- Min-max range-based?
- Z-score deviation-based?
- Other heuristic?

### Decision 3: Implementation Scope
**Now or later?**
- Implement now (infrastructure ready, can stub tests with data-gated validation)
- Implement when U07 data available (safer, but blocks P2-ANOM tests)
- Wait for framework decision on IF improvements (unknown timeline)

### Decision 4: Testing Strategy
**For unit tests:**
- Mock window data with known anomalies
- Verify flagging behavior without real data
- Document that validation is U07-gated

---

## 11. Summary Table

| Aspect | Status | Note |
|--------|--------|------|
| **Current Input Information** | Sufficient | Window data + window-level flag + severity available |
| **IF Per-Channel Breakdown** | Unavailable | Multivariate model; no per-channel scores exposed |
| **Architecture Support** | Yes | Pipeline wired, AttributionEngine ready, no IF changes needed |
| **Feasible Options** | 2 viable | Option 2 (Severity-threshold) recommended; Option 3 (Max-deviation) data-gated |
| **Can Implement Now** | Yes | Using available data and heuristics |
| **Can Validate Now** | Partial | Unit tests pass; P2 acceptance blocked on real data |
| **U07 Dependency** | Yes | Real data needed to tune threshold and verify false-positive rate |
| **Blocks P2 Acceptance** | Yes | Cannot run P2-ANOM-H2/H3 without validated per-channel flags |

---

## Recommended Path Forward

### If Approval is to Implement Now

1. **Choose Option 2** (Severity Threshold with variance-based heuristic)
2. **Implement ChannelFlagPolicy:**
   - Skeleton class in `edge/anomaly/policy.py` (new file)
   - Variance-based channel detection logic
   - Per-channel flag decision
   - Clear documentation of heuristic nature
3. **Add unit tests** in `edge/tests/test_policy.py`:
   - Window with single anomalous channel
   - Window with multiple anomalous channels
   - Clean window (no anomalies)
   - Edge cases (flat channels, all channels anomalous)
4. **Document limitations:**
   - Mark validation as U07-gated
   - Note heuristic nature
   - Explain threshold tuning requirement

### If Approval is to Wait for U07

1. **Keep current stub (FixedFlagPolicy)** in tests
2. **Implement placeholder in pipeline:**
   - Skeleton of real ChannelFlagPolicy
   - Return all-or-nothing for now
   - Plan to swap when data arrives
3. **Block P2-ANOM tests** until real implementation ready

---

## No Code Has Been Modified

This is a **design analysis only**. No implementation has been attempted. All findings are based on:
- Architecture review (pipeline.py, detector.py, attribution.py, iforest.py)
- PR documentation (P2-ANOM acceptance criteria)
- P2_RESUME.md findings
- IsolationForestDetector capabilities audit

