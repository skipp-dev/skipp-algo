"""Per-event SMC ledger (Amendment A1.A).

Persists every scored event as one JSON-Lines record with a pinned
schema (``EVENT_LEDGER_SCHEMA_VERSION``). The ledger is the shared
foundation for:

* **D2** — tri-axis FVG dashboard wiring (needs per-event context +
  family + outcome).
* **D4** — FVG-Quality recalibration on live samples (needs per-event
  features such as ``gap_size_atr`` / ``hurst`` once enrichers attach
  them via the ``features`` field).
* **future research** — a stable artifact for re-runnable analyses
  without re-executing the harness.

Schema is forward-only and versioned (``EVENT_LEDGER_SCHEMA_VERSION``); readers
accept any version in ``EVENT_LEDGER_COMPATIBLE_VERSIONS``. ``features`` carries
INPUT features; OUTCOME/target labels live under ``outcome_extras`` (schema 1.1
relocated ``label_partial_50`` / ``*_outcome_late`` there — use
:func:`ledger_label` to read a label from either location for back-compat).
The pinned schema is enforced by :func:`validate_event_ledger_record`: the
writer validates ``heuristic_direction_score`` / ``outcome`` / ``raw_score`` at write time
(and serializes with ``allow_nan=False``), and :func:`read_event_ledger` /
:func:`read_event_ledger_dir` offer a fail-closed ``strict=True`` mode for
promotion/governance consumers.

The ledger never *replaces* ``scoring_*.json``; it sits alongside it
in the same pair output directory as ``events_<SYMBOL>_<TIMEFRAME>.jsonl``.
"""

from __future__ import annotations

import contextlib
import json
import logging
import math
import os
import tempfile
from collections.abc import Iterable, Iterator
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from smc_core.schema_version import EVENT_LEDGER_SCHEMA_VERSION  # re-export for back-compat

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class EventLedgerRecord:
    """One persisted scored-event row.

    Required fields mirror :class:`smc_core.scoring.ScoredEvent`; ``outcome``
    is a plain bool label (never a dict). ``features`` holds INPUT features
    (``gap_size_atr``, ``hurst_50``, ``htf_aligned``, …); ``outcome_extras``
    holds additional OUTCOME/target labels (``label_partial_50``,
    ``sweep_trap_outcome_late``, ``reaction_outcome_late``) — the writer keeps
    labels out of ``features`` so a reader never mistakes a target for a feature.
    ``feature_schema_versions`` maps a feature namespace to its generation
    (e.g. ``{"reaction": 1}``) so consumers can tell which feature geometry a
    record used. See :func:`ledger_label` for the transitional label reader.
    """

    schema_version: str
    event_id: str
    symbol: str
    timeframe: str
    family: str
    timestamp: float
    # Schema 1.2: the bias-derived heuristic prior (was ``predicted_prob`` in
    # 1.0/1.1 — that name over-claimed; it is NOT a calibrated probability).
    heuristic_direction_score: float
    outcome: bool
    context: dict[str, str] = field(default_factory=dict)
    raw_score: float | None = None
    raw_score_name: str | None = None
    features: dict[str, Any] = field(default_factory=dict)
    outcome_extras: dict[str, Any] = field(default_factory=dict)
    feature_schema_versions: dict[str, int] = field(default_factory=dict)
    # Schema 1.2: leak-free OUT-OF-SAMPLE calibrated probability, back-filled per
    # event from the walk-forward family calibrator. ``None`` until back-filled
    # (and for events the calibrator never covered — coverage is partial).
    calibrated_prob: float | None = None


def _scored_event_to_record(
    event: Any,
    *,
    symbol: str,
    timeframe: str,
) -> EventLedgerRecord:
    """Translate a :class:`ScoredEvent` (or compatible object) to a record.

    Accepts both dataclass instances and dict-shaped objects so callers
    are not forced to import ``ScoredEvent`` for the test surface.
    """
    if isinstance(event, dict):
        get = event.get
    else:
        def get(name: str, default: Any = None) -> Any:
            return getattr(event, name, default)

    context = get("context") or {}
    if not isinstance(context, dict):
        context = {}
    # predicted_prob is mandatory: a missing or None value would silently
    # become 0.0 with the old `float(get(..., 0.0) or 0.0)` shape and make
    # every such row look like a 0% prediction in downstream scoring.
    # Found via SMC bug-hunt v2 phase 5 — schema/contract evolution.
    event_id = get("event_id", "")
    # 1.2: prefer the new name, fall back to the legacy ``predicted_prob`` so an
    # unmigrated ScoredEvent (whose attribute is still ``predicted_prob``) writes
    # cleanly under the new key.
    prob_raw = get("heuristic_direction_score")
    if prob_raw is None:
        prob_raw = get("predicted_prob")
    if prob_raw is None:
        raise ValueError(
            f"event missing heuristic_direction_score/predicted_prob "
            f"(event_id={event_id!r}); explicit float in [0.0, 1.0] required"
        )
    cal_raw = get("calibrated_prob")
    # Schema v1.1: labels are OUTCOMES, not features — relocate any that a caller
    # still emits under ``features`` into ``outcome_extras`` (explicit extras win),
    # and lift ``<ns>_schema_version`` keys into the feature_schema_versions map.
    features, outcome_extras, feature_versions = _partition_features(
        dict(get("features") or {}), dict(get("outcome_extras") or {})
    )
    return EventLedgerRecord(
        schema_version=EVENT_LEDGER_SCHEMA_VERSION,
        event_id=str(event_id),
        symbol=symbol,
        timeframe=timeframe,
        family=str(get("family", "")),
        timestamp=float(get("timestamp", 0.0) or 0.0),
        # predicted_prob / outcome / raw_score are validated at WRITE time so a
        # non-finite prob, an out-of-[0,1] prob, or a non-bool "outcome" (e.g. the
        # string "false", which bool() would flip to True) can never reach the file.
        heuristic_direction_score=_coerce_prob(prob_raw, event_id=event_id),
        outcome=_coerce_outcome(get("outcome", False), event_id=event_id),
        context={str(k): str(v) for k, v in context.items()},
        # PR-quantum-strict-audit: cache the ``get`` result via walrus so
        # mypy --strict can narrow ``Any | None`` -> ``Any`` for the
        # ``float(...)`` / ``str(...)`` call. Two separate ``get`` calls
        # would also be a (theoretical) idempotency hazard if ``context``
        # mutated between them.
        raw_score=(
            _coerce_finite(float(_rs), "raw_score", event_id=event_id)
            if (_rs := get("raw_score")) is not None else None
        ),
        raw_score_name=(
            str(_rsn) if (_rsn := get("raw_score_name")) is not None else None
        ),
        features=features,
        outcome_extras=outcome_extras,
        feature_schema_versions=feature_versions,
        # Optional 1.2 OOS calibrated prob; validated only when a source supplies
        # it (the back-fill pass), else persisted as null.
        calibrated_prob=(
            _coerce_prob(cal_raw, event_id=event_id, label="calibrated_prob")
            if cal_raw is not None else None
        ),
    )


def write_event_ledger(
    events: Iterable[Any],
    *,
    output_path: Path,
    symbol: str,
    timeframe: str,
) -> int:
    """Write JSONL ledger to ``output_path``. Returns row count.

    Empty input still produces an empty file so downstream consumers can
    rely on the path existing whenever the harness ran.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=output_path.name + ".",
        suffix=".tmp",
        dir=str(output_path.parent),
    )
    count = 0
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            for event in events:
                record = _scored_event_to_record(
                    event, symbol=symbol, timeframe=timeframe
                )
                handle.write(json.dumps(asdict(record), separators=(",", ":"), allow_nan=False))
                handle.write("\n")
                count += 1
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, output_path)
    except Exception:
        with contextlib.suppress(OSError):
            os.unlink(tmp_name)
        raise
    return count


def read_event_ledger(path: Path, *, strict: bool = False) -> Iterator[dict[str, Any]]:
    """Yield records from a JSONL ledger (raw dicts, no class coercion).

    ``strict=False`` (default, LENIENT): malformed JSONL lines (truncated
    writes, partial flushes, disk-full mid-append) MUST NOT abort the
    generator. Audit 2026-05-10 (PR-J2): a bare ``json.loads`` raised
    ``json.JSONDecodeError`` from inside the generator and silently lost every
    subsequent record for every caller (scoring pipelines, F2 calibration, AB
    comparison). Lenient mode logs + skips and continues (partial recovery).

    ``strict=True`` (FAIL-CLOSED): a malformed JSON line OR a record that fails
    :func:`validate_event_ledger_record` raises :class:`EventLedgerSchemaError`.
    Promotion / governance evaluators MUST use this so a corrupt or partial
    corpus can never be silently graded into a verdict.
    """
    with path.open("r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue
            record, warning = _parse_ledger_line(
                line, line_no=line_no, source=str(path), strict=strict
            )
            if warning is not None:
                logger.warning("event_ledger %s", warning)
                continue
            yield record


#: Glob for the per-pair ledgers under a benchmark snapshot tree.
_LEDGER_TREE_GLOB = "*/*/events_*.jsonl"


def read_event_ledger_dir(
    root: Path, *, family: str | None = None, strict: bool = False
) -> tuple[list[dict[str, Any]], list[str]]:
    """Read every ``SYMBOL/TF/events_*.jsonl`` under ``root`` via the central API.

    The single entry point every dir-walking consumer (FVG audits/gates, the
    shadow evaluators) should use instead of a bespoke reader. Returns
    ``(events, warnings)``. ``family`` filters to one event family when given.

    ``strict=False``: malformed lines are skipped and reported in ``warnings``
    (also covers ``root`` missing / no files / unreadable file). ``strict=True``:
    a malformed or off-schema line raises :class:`EventLedgerSchemaError`.
    """
    events: list[dict[str, Any]] = []
    warnings: list[str] = []
    if not root.exists():
        return events, [f"root not found: {root}"]
    files = sorted(root.glob(_LEDGER_TREE_GLOB))
    if not files:
        return events, [f"no events_*.jsonl files under {root}"]
    for path in files:
        try:
            with path.open("r", encoding="utf-8") as handle:
                for line_no, raw in enumerate(handle, start=1):
                    line = raw.strip()
                    if not line:
                        continue
                    record, warning = _parse_ledger_line(
                        line, line_no=line_no, source=str(path), strict=strict
                    )
                    if warning is not None:
                        warnings.append(warning)
                        continue
                    if family is None or record.get("family") == family:
                        events.append(record)
        except OSError as exc:
            warnings.append(f"{path}: {exc}")
    return events, warnings


def ledger_path_for_pair(
    pair_dir: Path, *, symbol: str, timeframe: str
) -> Path:
    """Canonical sibling path next to ``scoring_<sym>_<tf>.json``."""
    return pair_dir / f"events_{symbol}_{timeframe}.jsonl"


# ---------------------------------------------------------------------------
# Schema validation (the "pinned schema" the module docstring promises)
# ---------------------------------------------------------------------------


class EventLedgerSchemaError(ValueError):
    """A ledger record violates the pinned event-ledger schema.

    Subclasses :class:`ValueError` so existing fail-closed handlers in the
    promotion/governance evaluators (which already catch ``ValueError``) treat a
    schema violation as corruption and refuse to grade the corpus.
    """


#: Fields every record must carry to be a valid schema row. The heuristic prior
#: is validated separately (``heuristic_direction_score`` in 1.2, or the legacy
#: ``predicted_prob`` in 1.0/1.1) so both record generations pass — see below.
_REQUIRED_RECORD_FIELDS: tuple[str, ...] = (
    "schema_version",
    "event_id",
    "symbol",
    "timeframe",
    "family",
    "timestamp",
    "outcome",
)

#: The heuristic-prior key by schema generation: 1.2 writes the first, 1.0/1.1
#: wrote the second. A valid record carries exactly one of them.
_HEURISTIC_SCORE_KEYS: tuple[str, ...] = ("heuristic_direction_score", "predicted_prob")

#: Schema versions a reader accepts. 1.0 records (labels under ``features``, no
#: ``feature_schema_versions``) are still valid — :func:`ledger_label` bridges them;
#: 1.0/1.1 carry ``predicted_prob``, 1.2 carries ``heuristic_direction_score`` +
#: optional ``calibrated_prob`` — :func:`ledger_heuristic_score` bridges the rename.
EVENT_LEDGER_COMPATIBLE_VERSIONS: frozenset[str] = frozenset({"1.0", "1.1", "1.2"})

#: Outcome/target labels that belong under ``outcome_extras`` (schema 1.1), never
#: under ``features`` — they are what a model PREDICTS, not an input.
_OUTCOME_LABEL_KEYS: frozenset[str] = frozenset(
    {"label_partial_50", "sweep_trap_outcome_late", "reaction_outcome_late"}
)

#: Suffix marking a per-feature-namespace generation counter inside ``features``
#: (e.g. ``reaction_schema_version``). Lifted into ``feature_schema_versions``.
_FEATURE_VERSION_SUFFIX = "_schema_version"


def _is_real_number(value: Any) -> bool:
    """True for a genuine int/float (bool is NOT a number here)."""
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def validate_event_ledger_record(
    record: Any, *, source: str = "<record>"
) -> dict[str, Any]:
    """Validate one ledger record against the pinned schema; return it or raise.

    Checks object shape, required fields, ``schema_version`` membership in
    :data:`EVENT_LEDGER_COMPATIBLE_VERSIONS`, and the domains that silently
    corrupt downstream scoring/calibration: the heuristic prior finite in
    ``[0, 1]`` (``heuristic_direction_score`` or legacy ``predicted_prob``),
    optional ``calibrated_prob`` null-or-finite-``[0,1]``,
    ``outcome`` a genuine bool, ``timestamp`` finite, ``family`` a
    non-empty string, and ``feature_schema_versions`` (if present) a dict.
    Raises :class:`EventLedgerSchemaError` on any violation.
    """
    if not isinstance(record, dict):
        raise EventLedgerSchemaError(
            f"{source}: expected a JSON object, got {type(record).__name__}"
        )
    missing = [k for k in _REQUIRED_RECORD_FIELDS if k not in record]
    if missing:
        raise EventLedgerSchemaError(
            f"{source}: missing required field(s): {', '.join(missing)}"
        )
    version = record["schema_version"]
    if version not in EVENT_LEDGER_COMPATIBLE_VERSIONS:
        raise EventLedgerSchemaError(
            f"{source}: schema_version {version!r} not in supported "
            f"{sorted(EVENT_LEDGER_COMPATIBLE_VERSIONS)}"
        )
    fsv = record.get("feature_schema_versions")
    if fsv is not None and not isinstance(fsv, dict):
        raise EventLedgerSchemaError(
            f"{source}: feature_schema_versions must be an object, got "
            f"{type(fsv).__name__}"
        )
    score_key = next((k for k in _HEURISTIC_SCORE_KEYS if k in record), None)
    if score_key is None:
        raise EventLedgerSchemaError(
            f"{source}: missing the heuristic-prior field "
            f"(one of {list(_HEURISTIC_SCORE_KEYS)})"
        )
    prob = record[score_key]
    if not _is_real_number(prob) or not math.isfinite(prob) or not (0.0 <= prob <= 1.0):
        raise EventLedgerSchemaError(
            f"{source}: {score_key} {prob!r} is not a finite float in [0.0, 1.0]"
        )
    # 1.2 calibrated_prob is optional; when present (and not null) it must be a
    # finite probability, same domain as the heuristic prior.
    calibrated = record.get("calibrated_prob")
    if calibrated is not None and (
        not _is_real_number(calibrated) or not math.isfinite(calibrated) or not (0.0 <= calibrated <= 1.0)
    ):
        raise EventLedgerSchemaError(
            f"{source}: calibrated_prob {calibrated!r} is not null or a finite float in [0.0, 1.0]"
        )
    outcome = record["outcome"]
    if not isinstance(outcome, bool):
        raise EventLedgerSchemaError(
            f"{source}: outcome {outcome!r} must be a bool, got "
            f"{type(outcome).__name__}"
        )
    timestamp = record["timestamp"]
    if not _is_real_number(timestamp) or not math.isfinite(timestamp):
        raise EventLedgerSchemaError(
            f"{source}: timestamp {timestamp!r} is not a finite number"
        )
    family = record["family"]
    if not isinstance(family, str) or not family:
        raise EventLedgerSchemaError(
            f"{source}: family {family!r} must be a non-empty string"
        )
    return record


def _coerce_prob(value: Any, *, event_id: Any, label: str = "heuristic_direction_score") -> float:
    """Return a finite float in ``[0, 1]`` or raise (write-time enforcement)."""
    prob = float(value)
    if not math.isfinite(prob) or not (0.0 <= prob <= 1.0):
        raise ValueError(
            f"event {label} {value!r} (event_id={event_id!r}) must be a "
            "finite float in [0.0, 1.0]"
        )
    return prob


def _coerce_outcome(value: Any, *, event_id: Any) -> bool:
    """Accept only a genuine bool or an explicit int ``0``/``1``; else raise.

    A plain ``bool(value)`` would flip the string ``"false"`` (and every other
    non-empty string) to ``True`` and silently invert hit-rate/calibration.
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    raise ValueError(
        f"event outcome {value!r} (event_id={event_id!r}) must be a bool "
        f"(or explicit 0/1), not {type(value).__name__}"
    )


def _coerce_finite(value: float, field_name: str, *, event_id: Any) -> float:
    """Return ``value`` if finite; else raise (rejects NaN/Infinity at write)."""
    if not math.isfinite(value):
        raise ValueError(
            f"event {field_name} {value!r} (event_id={event_id!r}) must be finite"
        )
    return value


def _partition_features(
    features: dict[str, Any], outcome_extras: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any], dict[str, int]]:
    """Split a caller's ``features`` into (features, outcome_extras, versions).

    Schema 1.1: outcome labels are moved out of ``features`` into
    ``outcome_extras`` (an explicit ``outcome_extras`` value for the same key
    wins), and ``<ns>_schema_version`` counters are lifted into a
    ``{namespace: version}`` map. Version keys stay in ``features`` too so 1.0
    consumers that read ``features["reaction_schema_version"]`` keep working.
    """
    clean: dict[str, Any] = {}
    extras: dict[str, Any] = dict(outcome_extras)
    versions: dict[str, int] = {}
    for key, value in features.items():
        if key in _OUTCOME_LABEL_KEYS:
            extras.setdefault(key, value)
            continue
        clean[key] = value
        if key.endswith(_FEATURE_VERSION_SUFFIX) and isinstance(value, int) and not isinstance(value, bool):
            namespace = key[: -len(_FEATURE_VERSION_SUFFIX)]
            if namespace:
                versions[namespace] = value
    return clean, extras, versions


def _parse_ledger_line(
    line: str, *, line_no: int, source: str, strict: bool
) -> tuple[dict[str, Any] | None, str | None]:
    """Parse one JSONL line into ``(record, warning)``.

    Shared by :func:`read_event_ledger` and :func:`read_event_ledger_dir` so all
    readers agree on JSON handling and (in strict mode) schema validation.
    ``strict=True`` raises :class:`EventLedgerSchemaError` instead of warning.
    """
    try:
        record = json.loads(line)
    except json.JSONDecodeError as exc:
        if strict:
            raise EventLedgerSchemaError(
                f"{source} line {line_no}: malformed JSON: {exc}"
            ) from exc
        return None, f"{source} line {line_no}: malformed JSON, skipping ({exc})"
    if strict:
        validate_event_ledger_record(record, source=f"{source} line {line_no}")
    return record, None


def ledger_label(record: dict[str, Any], key: str, default: Any = None) -> Any:
    """Read an outcome label from a record, tolerant of schema 1.0 and 1.1.

    Schema 1.1 stores labels under ``outcome_extras``; schema 1.0 stored them
    under ``features``. Prefer ``outcome_extras`` and fall back to ``features``
    so a single call reads both record generations. Consumers of
    ``label_partial_50`` / ``*_outcome_late`` MUST use this instead of reaching
    into ``features`` directly.
    """
    extras = record.get("outcome_extras")
    if isinstance(extras, dict) and key in extras:
        return extras[key]
    feats = record.get("features")
    if isinstance(feats, dict) and key in feats:
        return feats[key]
    return default


def ledger_heuristic_score(record: dict[str, Any], default: Any = None) -> Any:
    """Read the heuristic direction prior, tolerant of schema 1.0/1.1 and 1.2.

    1.2 stores it under ``heuristic_direction_score``; 1.0/1.1 stored the same
    value under the (over-claiming) name ``predicted_prob``. Prefer the new key,
    fall back to the legacy one, so a single call reads both record generations.
    Consumers MUST use this instead of indexing ``record["predicted_prob"]`` so a
    1.2 record (which has no ``predicted_prob`` key) does not ``KeyError``.
    """
    for key in _HEURISTIC_SCORE_KEYS:
        if key in record:
            return record[key]
    return default
