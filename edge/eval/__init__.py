"""Hardware-free P2 evaluation harness (NOT production, NOT acceptance).

Diagnostic tooling to observe how the real :class:`IsolationForestDetector`
behaves on the current hardware-free simulator + synthetic §12.4 injections. It
exists to LEARN the detector's behaviour, not to satisfy any P2 acceptance
criterion. It is deliberately kept out of the production P2 pipeline and out of
the default test collection (``edge/eval`` is not on pytest ``testpaths``).

All injection magnitudes/durations and the flag threshold used here are
EVALUATION FIXTURES ONLY — arbitrary diagnostic values, NOT project
specifications. Real detection accuracy, cross-sensor spoof behaviour, and any
O3/O10 metric remain dataset-gated (SWaT/WADI/TEP, U07).
"""
