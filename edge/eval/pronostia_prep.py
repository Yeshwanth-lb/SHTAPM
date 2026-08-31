"""PRONOSTIA (FEMTO/IEEE PHM 2012) raw-data preprocessing (P3 · D021/D022/D023).

DATA PREPARATION ONLY. Converts PRONOSTIA's actual on-disk raw CSVs
(``acc_XXXXX.csv`` vibration bursts, ``temp_XXXXX.csv`` continuous
temperature) for ONE bearing run into the D022-approved representation: a
1Hz temperature-clocked sequence with sparse, honestly-flagged vibration
observations. Nothing here trains a model, resolves the four non-covered
channels (pressure/humidity/gas/current -- absent from the output entirely,
never zero-filled or otherwise fabricated), chooses HealthState thresholds
or failure_eta horizon/units, or makes any pump-validation claim -- see
``DECISIONS.md`` D021/D022.

Same status as ``edge/eval/twin_training.py`` and its siblings: not on
pytest ``testpaths``' production path, not wired into any acceptance
criterion, not part of ``edge/pipeline/cycle.py`` or any P2/P3 production
wiring. The real ~1.1GB downloaded dataset is never committed to this repo
and is not required for this module's own tests, which use small synthetic
fixture CSVs matching PRONOSTIA's actual raw format.

D022's three approved representation choices, implemented exactly:
  1. Temperature 10Hz -> 1Hz: 1-second block mean of the real measured
     samples, grouped by their own (hour, minute, second) columns -- no
     assumption of file-boundary continuity.
  2. Vibration burst -> one scalar: RMS of the per-sample Euclidean
     magnitude ``sqrt(horizontal_i^2 + vertical_i^2)`` across a burst's
     samples. No interpolation across the ~10s silent gaps between bursts
     -- a burst contributes a value ONLY at the one-second tick its first
     sample's timestamp falls in.
  3. Missing-vibration indicator: every 1Hz tick without a real burst gets
     ``vibration=0.0`` AND ``vibration_observed=0.0`` (explicit, not a
     proxy for low trust -- ``trust`` is deliberately not used here; see
     D022's own reasoning).

PRONOSTIA's raw CSVs carry no absolute date, only (hour, minute, second[,
sub-second]) -- day-rollover is handled by unwrapping strictly-decreasing
wall-clock jumps within a single bearing run's own file-number order (which
is the dataset's true chronological order), not by any calendar assumption.
Only jumps consistent with a genuine midnight crossing are unwrapped this
way; see ``_unwrap_seconds``.

KNOWN REAL-DATA FINDINGS and their D023-AUTHORIZED TREATMENT (not fixture
artifacts, confirmed against the actual downloaded dataset; the full
17-bearing measurements live in this session's audit record, not
duplicated here):
  - Some bearings' raw CSVs use ';' as the field delimiter instead of ','
    (observed: Bearing1_2, Bearing2_1, Bearing3_1's temp files) -- handled
    transparently by per-file delimiter auto-detection (_detect_delimiter);
    this is a raw-format normalization, not a representation decision.
  - 5 bearings (Bearing2_2, Bearing3_2, Bearing1_3, Bearing2_3, Bearing2_6)
    have ZERO temp_*.csv files -- no temperature data exists for these
    bearings at all. Since Option C's representation uses temperature as
    the defining 1Hz clock, there is no legitimate way to place their
    vibration data. **D023 treatment 1:** these bearings are excluded
    entirely -- ``load_bearing_run`` still raises ``ValueError`` for them
    (no temperature clock to build), now an intentional, authorized
    exclusion rather than an unresolved gap. No alternative clock is
    invented.
  - Across every bearing with temperature data, vibration logging begins a
    few bursts (roughly 10-110s) before temperature logging does -- a
    real startup lag between the two sensor subsystems, not scattered
    internal gaps (temperature coverage, once it begins, is always
    perfectly contiguous). **D023 treatment 2:** vibration bursts whose
    timestamp falls before the first second temperature actually covers
    are silently discarded (never interpolated, never backfilled) --
    applied as a GENERAL rule to every bearing meeting this exact
    condition, not a curated per-bearing list. A burst that falls AFTER
    temperature coverage begins but still has no matching second (a
    genuine internal gap) is NOT covered by this treatment and still
    raises -- none was found empirically, but the strict check remains.
  - Training_set/Learning_set/Bearing1_1 contains two consecutive
    vibration-burst files (acc_02121.csv, acc_02122.csv) with a corrupted,
    non-monotonic timestamp, sandwiched between an otherwise clean
    ~10s-cadence sequence (15:32:49 -> [corrupted pair] -> 15:33:19).
    **D023 treatment 3:** these two files, named exactly, are discarded
    for Bearing1_1 only, before their timestamps ever reach
    ``_unwrap_seconds``. This is a hardcoded, one-bearing, two-file
    exclusion -- it is explicitly NOT a general corrupted-record-detection
    mechanism; any other bearing's non-midnight backward jump still raises
    exactly as before. Bearing1_1 needs BOTH treatment 2 (its own 7
    leading-edge bursts) AND treatment 3 (these 2 files) to load cleanly.

None of these three treatments fabricates, interpolates, or reconstructs
any value -- each only ever removes an observation that cannot be
legitimately placed under the existing D022 representation. See
``DECISIONS.md`` D023 for the full authorization and scope.
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from pathlib import Path

# PRONOSTIA's own file-naming convention (unmodified from the raw dataset).
_ACC_GLOB = "acc_*.csv"
_TEMP_GLOB = "temp_*.csv"
_BEARING_NAME_RE = re.compile(r"^Bearing(\d)_(\d+)$")

# A backward timestamp jump is only ever treated as a genuine midnight
# crossing if the earlier reading is late-in-the-day and the later reading
# is early-in-the-day. Any other backward jump is refused, not guessed --
# see _unwrap_seconds and the module docstring's "known real-data anomaly"
# note.
_MIDNIGHT_ROLLOVER_PREV_LOWER_BOUND = 23 * 3600  # 23:00:00
_MIDNIGHT_ROLLOVER_RAW_UPPER_BOUND = 3600  # 01:00:00

# DECISIONS.md D023 treatment 1: bearings with zero temperature files,
# excluded entirely. Named here only for clear, D023-attributed error
# messages -- the exclusion itself is a structural consequence of having
# no temp_*.csv files at all (see _load_temperature), not a separate check.
ZERO_TEMPERATURE_BEARINGS_D023 = frozenset(
    {"Bearing2_2", "Bearing3_2", "Bearing1_3", "Bearing2_3", "Bearing2_6"}
)

# DECISIONS.md D023 treatment 3: exactly these two files, for Bearing1_1
# ONLY, are discarded due to demonstrably corrupted/non-monotonic
# timestamps. NOT a general corrupted-record detection mechanism -- see
# module docstring.
_BEARING1_1_CORRUPTED_FILES_D023 = frozenset({"acc_02121.csv", "acc_02122.csv"})


@dataclass(frozen=True)
class PronostiaRunSequence:
    """One bearing run's D022-approved representation. Deliberately has NO
    fields for pressure/humidity/gas/current -- see module docstring; this
    is the stop-at-the-boundary output, not a six/seven-channel model
    input. Converting this into a ``len(CHANNELS)+1``-wide model tensor is
    a separate, not-yet-authorized step.
    """

    bearing_id: str  # e.g. "Bearing1_1", parsed from the source directory name
    operating_condition: int  # 1, 2, or 3 -- the first digit of bearing_id
    split: str  # caller-supplied label (e.g. "training"/"test"/"validation_full");
    # never inferred by this module -- see load_bearing_run
    timestamps: tuple[tuple[int, int, int], ...]  # original (hour, minute, second) per tick
    temperature: tuple[float, ...]  # 1Hz block-mean, same length as timestamps
    vibration: tuple[float, ...]  # RMS scalar, or 0.0 where unobserved
    vibration_observed: tuple[float, ...]  # 1.0 where a real burst exists, else 0.0

    def __post_init__(self) -> None:
        n = len(self.timestamps)
        lengths = (len(self.temperature), len(self.vibration), len(self.vibration_observed))
        if any(length != n for length in lengths):
            raise ValueError("timestamps/temperature/vibration/vibration_observed length mismatch")


def _parse_bearing_id(bearing_dir: Path) -> tuple[str, int]:
    match = _BEARING_NAME_RE.match(bearing_dir.name)
    if not match:
        raise ValueError(
            f"directory name {bearing_dir.name!r} does not match PRONOSTIA's "
            "own 'BearingC_N' naming"
        )
    return bearing_dir.name, int(match.group(1))


def _detect_delimiter(sample_line: str) -> str:
    """Real PRONOSTIA files are inconsistently delimited across bearings:
    most use ',', some (observed empirically: Bearing1_2, Bearing2_1,
    Bearing3_1's temp files) use ';'. Never mixed within one file in any
    real file observed. Comma takes priority when both are absent/present
    ambiguously."""
    return ";" if ";" in sample_line and "," not in sample_line else ","


def _read_rows(path: Path) -> list[list[float]]:
    """PRONOSTIA CSVs have no header row -- every row is parsed as floats.
    Delimiter is auto-detected per file (see _detect_delimiter)."""
    with path.open(newline="") as f:
        lines = [line for line in f.read().splitlines() if line.strip()]
    if not lines:
        return []
    delimiter = _detect_delimiter(lines[0])
    return [[float(cell) for cell in row] for row in csv.reader(lines, delimiter=delimiter) if row]


def _unwrap_seconds(hour: float, minute: float, second: float, state: dict) -> int:
    """Convert one (hour, minute, second) reading into monotonically
    non-decreasing elapsed seconds within a run, unwrapping midnight
    rollover. ``state`` carries ``{"day_offset": int, "prev_raw": int | None}``
    across successive calls for the SAME run, in file-chronological order.

    A backward jump is unwrapped as a genuine midnight crossing ONLY when
    the earlier reading is late-in-the-day and the later one is
    early-in-the-day (see the module-level bounds). Any other backward
    jump raises -- known real PRONOSTIA data contains isolated corrupted
    timestamp records (observed empirically: two consecutive vibration
    burst files with a garbage timestamp, surrounded by an otherwise clean,
    monotonic ~10s cadence) that must not be silently misattributed as a
    day boundary, nor silently dropped -- how to handle a corrupted record
    is a genuine open question this module does not decide.
    """
    raw = int(hour) * 3600 + int(minute) * 60 + int(second)
    prev_raw = state["prev_raw"]
    if prev_raw is not None and raw < prev_raw:
        is_plausible_midnight_crossing = (
            prev_raw >= _MIDNIGHT_ROLLOVER_PREV_LOWER_BOUND
            and raw <= _MIDNIGHT_ROLLOVER_RAW_UPPER_BOUND
        )
        if not is_plausible_midnight_crossing:
            raise ValueError(
                f"non-monotonic timestamp jump from {prev_raw}s to {raw}s "
                "within a single run's own file order, and NOT consistent "
                "with a genuine midnight crossing (expected the earlier "
                "reading near 23:xx:xx and the later one near 00:xx:xx) -- "
                "likely a corrupted/anomalous raw timestamp record in the "
                "source data; refusing to silently misattribute it as "
                "day-rollover or otherwise guess a resolution"
            )
        state["day_offset"] += 86400
    state["prev_raw"] = raw
    return state["day_offset"] + raw


def _load_temperature(bearing_dir: Path) -> dict[int, tuple[tuple[int, int, int], float]]:
    """Group every real temperature sample by its own (hour, minute,
    second), 1-second block mean (D022 choice 1). Returns
    ``{elapsed_seconds: ((hour, minute, second), mean_temp)}``.
    """
    files = sorted(bearing_dir.glob(_TEMP_GLOB))
    if not files:
        note = (
            " -- this is one of DECISIONS.md D023's five authorized " "zero-temperature exclusions"
            if bearing_dir.name in ZERO_TEMPERATURE_BEARINGS_D023
            else ""
        )
        raise ValueError(f"no {_TEMP_GLOB} files found in {bearing_dir}{note}")

    state = {"day_offset": 0, "prev_raw": None}
    groups: dict[int, list[float]] = {}
    hms_by_key: dict[int, tuple[int, int, int]] = {}
    for path in files:
        for row in _read_rows(path):
            hour, minute, second = row[0], row[1], row[2]
            value = row[4]
            key = _unwrap_seconds(hour, minute, second, state)
            groups.setdefault(key, []).append(value)
            hms_by_key.setdefault(key, (int(hour), int(minute), int(second)))

    return {key: (hms_by_key[key], sum(values) / len(values)) for key, values in groups.items()}


def _load_vibration(bearing_dir: Path) -> dict[int, float]:
    """One RMS-of-Euclidean-magnitude scalar per real burst (D022 choice
    2), keyed by the elapsed-second its first sample falls in. Raises if
    two bursts land in the same second (not expected empirically; caught
    rather than silently overwritten).

    DECISIONS.md D023 treatment 3: for ``Bearing1_1`` only, the two named
    files in ``_BEARING1_1_CORRUPTED_FILES_D023`` are skipped entirely
    (never read) -- their corrupted timestamps never reach
    ``_unwrap_seconds``. Not a general corrupted-record mechanism.
    """
    files = sorted(bearing_dir.glob(_ACC_GLOB))
    if not files:
        raise ValueError(f"no {_ACC_GLOB} files found in {bearing_dir}")

    is_bearing1_1 = bearing_dir.name == "Bearing1_1"
    state = {"day_offset": 0, "prev_raw": None}
    rms_by_key: dict[int, float] = {}
    for path in files:
        if is_bearing1_1 and path.name in _BEARING1_1_CORRUPTED_FILES_D023:
            continue
        rows = _read_rows(path)
        if not rows:
            raise ValueError(f"{path} contains no samples")
        hour, minute, second = rows[0][0], rows[0][1], rows[0][2]
        key = _unwrap_seconds(hour, minute, second, state)
        magnitudes_sq = [row[4] ** 2 + row[5] ** 2 for row in rows]
        rms = (sum(magnitudes_sq) / len(magnitudes_sq)) ** 0.5
        if key in rms_by_key:
            raise ValueError(
                f"two vibration bursts landed in the same second (elapsed={key}) "
                f"in {bearing_dir}; not expected -- refusing to silently overwrite"
            )
        rms_by_key[key] = rms
    return rms_by_key


def load_bearing_run(bearing_dir: Path, *, split: str) -> PronostiaRunSequence:
    """Load one bearing's raw PRONOSTIA files (``bearing_dir``, e.g.
    ``.../Learning_set/Bearing1_1``) into a ``PronostiaRunSequence``.

    ``split`` is a REQUIRED, caller-supplied label (e.g. "training"/"test"/
    "validation_full") -- this module never infers it from the directory
    path, since PRONOSTIA's own on-disk layout (which of the three
    Training_set/Test_set/Validation_Set zips a bearing came from) is a
    detail of how the dataset happens to be unzipped, not something this
    module hardcodes as a specification. Correct train/test separation is
    therefore the caller's explicit responsibility -- passing the wrong
    ``split`` for a bearing pulled from the wrong source directory is
    exactly the kind of leakage this parameter exists to make visible, not
    silent.

    Deterministic: pure file parsing + arithmetic, no randomness; file
    lists are always explicitly sorted, never relying on OS listing order.

    DECISIONS.md D023 treatments applied here: bearings with zero
    temperature files remain excluded (treatment 1, via ``_load_temperature``'s
    own raise); vibration bursts occurring before temperature coverage
    begins are silently discarded, as a general rule (treatment 2); for
    ``Bearing1_1`` only, its two named corrupted files are never read
    (treatment 3, applied inside ``_load_vibration``). None of the three
    fabricates, interpolates, or reconstructs any value.

    Raises:
        ValueError: if a vibration burst's timestamp falls outside the
            temperature record's coverage AND is not explained by D023
            treatment 2 (i.e. a genuine internal gap after temperature
            coverage begins -- none found empirically, but still refused);
            if two bursts land in the same second; if no ``acc_*.csv``/
            ``temp_*.csv`` files are found (including D023's five
            authorized zero-temperature exclusions); or if ``bearing_dir``'s
            name doesn't match PRONOSTIA's own ``BearingC_N`` convention.
    """
    bearing_id, operating_condition = _parse_bearing_id(bearing_dir)
    temp_by_key = _load_temperature(bearing_dir)
    vibration_by_key = _load_vibration(bearing_dir)

    # D023 treatment 2: discard leading-edge bursts before temperature
    # coverage begins -- a general rule (any bearing meeting this exact
    # condition), not a curated per-bearing list. A burst still missing a
    # matching second AFTER temperature coverage begins is a genuine
    # internal gap, not covered by this treatment, and still raises below.
    first_covered_second = min(temp_by_key)
    vibration_by_key = {k: v for k, v in vibration_by_key.items() if k >= first_covered_second}

    missing = sorted(k for k in vibration_by_key if k not in temp_by_key)
    if missing:
        raise ValueError(
            f"{bearing_dir}: {len(missing)} vibration burst(s) fall outside "
            "the temperature record's coverage (e.g. elapsed second "
            f"{missing[0]}) despite occurring at/after temperature coverage "
            "begins -- a genuine internal gap, not the D023 treatment-2 "
            "leading-edge case; temperature is this representation's "
            "defining 1Hz clock (D022/Option C); a burst with no "
            "corresponding temperature second cannot be placed without "
            "inventing one"
        )

    ordered_keys = sorted(temp_by_key)
    timestamps = tuple(temp_by_key[k][0] for k in ordered_keys)
    temperature = tuple(temp_by_key[k][1] for k in ordered_keys)
    vibration = tuple(vibration_by_key.get(k, 0.0) for k in ordered_keys)
    vibration_observed = tuple(1.0 if k in vibration_by_key else 0.0 for k in ordered_keys)

    return PronostiaRunSequence(
        bearing_id=bearing_id,
        operating_condition=operating_condition,
        split=split,
        timestamps=timestamps,
        temperature=temperature,
        vibration=vibration,
        vibration_observed=vibration_observed,
    )
