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

Schema is forward-only: new fields may be added under ``features`` /
``outcome_extras``; existing fields are never removed without a schema bump.
The pinned schema is enforced by :func:`validate_event_ledger_record`: the
writer validates ``predicted_prob`` / ``outcome`` / ``raw_score`` at write time
(and serializes with ``allow_nan=False``), and :func:`read_event_ledger` offers
a fail-closed ``strict=True`` mode for promotion/governance consumers.

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
    is a plain bool label (never a dict). The ``features`` / ``outcome_extras``
    dicts are the open-ended ones — upstream enrichers (D4 work) attach
    ``gap_size_atr``, ``hurst_50``, ``htf_aligned`` there, no schema bump.
    """

    schema_version: str
    event_id: str
    symbol: str
    timeframe: str
    family: str
    timestamp: float
    predicted_prob: float
    outcome: bool
    context: dict[str, str] = field(default_factory=dict)
    raw_score: float | None = None
    raw_score_name: str | None = None
    features: dict[str, Any] = field(default_factory=dict)
    outcome_extras: dict[str, Any] = field(default_factory=dict)


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
    prob_raw = get("predicted_prob")
    if prob_raw is None:
        raise ValueError(
            f"event missing predicted_prob (event_id={event_id!r}); "
            "explicit float in [0.0, 1.0] required"
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
        predicted_prob=_coerce_prob(prob_raw, event_id=event_id),
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
        features=dict(get("features") or {}),
        outcome_extras=dict(get("outcome_extras") or {}),
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
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                if strict:
                    raise EventLedgerSchemaError(
                        f"{path}:{line_no}: malformed JSON: {exc}"
                    ) from exc
                logger.warning(
                    "event_ledger %s line %d: malformed JSON, skipping (%s)",
                    path,
                    line_no,
                    exc,
                )
                continue
            if strict:
                validate_event_ledger_record(record, source=f"{path}:{line_no}")
            yield record


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


#: Fields every record must carry to be a valid schema row.
_REQUIRED_RECORD_FIELDS: tuple[str, ...] = (
    "schema_version",
    "event_id",
    "symbol",
    "timeframe",
    "family",
    "timestamp",
    "predicted_prob",
    "outcome",
)


def _is_real_number(value: Any) -> bool:
    """True for a genuine int/float (bool is NOT a number here)."""
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def validate_event_ledger_record(
    record: Any, *, source: str = "<record>"
) -> dict[str, Any]:
    """Validate one ledger record against the pinned schema; return it or raise.

    Checks object shape, required fields, ``schema_version`` equality with the
    pinned :data:`EVENT_LEDGER_SCHEMA_VERSION`, and the domains that silently
    corrupt downstream scoring/calibration: ``predicted_prob`` finite in
    ``[0, 1]``, ``outcome`` a genuine bool, ``timestamp`` finite, ``family`` a
    non-empty string. Raises :class:`EventLedgerSchemaError` on any violation.
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
    if version != EVENT_LEDGER_SCHEMA_VERSION:
        raise EventLedgerSchemaError(
            f"{source}: schema_version {version!r} != pinned "
            f"{EVENT_LEDGER_SCHEMA_VERSION!r}"
        )
    prob = record["predicted_prob"]
    if not _is_real_number(prob) or not math.isfinite(prob) or not (0.0 <= prob <= 1.0):
        raise EventLedgerSchemaError(
            f"{source}: predicted_prob {prob!r} is not a finite float in [0.0, 1.0]"
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


def _coerce_prob(value: Any, *, event_id: Any) -> float:
    """Return a finite float in ``[0, 1]`` or raise (write-time enforcement)."""
    prob = float(value)
    if not math.isfinite(prob) or not (0.0 <= prob <= 1.0):
        raise ValueError(
            f"event predicted_prob {value!r} (event_id={event_id!r}) must be a "
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
