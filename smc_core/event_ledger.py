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
``outcome``; existing fields are never removed without a schema bump.

The ledger never *replaces* ``scoring_*.json``; it sits alongside it
in the same pair output directory as ``events_<SYMBOL>_<TIMEFRAME>.jsonl``.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from smc_core.schema_version import EVENT_LEDGER_SCHEMA_VERSION  # re-export for back-compat


@dataclass(slots=True)
class EventLedgerRecord:
    """One persisted scored-event row.

    Required fields mirror :class:`smc_core.scoring.ScoredEvent`. The
    ``features`` and ``outcome`` dicts are intentionally open-ended so
    upstream enrichers (D4 work) can attach ``gap_size_atr``,
    ``hurst_50``, ``htf_aligned`` etc. without a schema bump.
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
    prob_raw = get("predicted_prob")
    if prob_raw is None:
        raise ValueError(
            f"event missing predicted_prob (event_id={get('event_id', '')!r}); "
            "explicit float in [0.0, 1.0] required"
        )
    return EventLedgerRecord(
        schema_version=EVENT_LEDGER_SCHEMA_VERSION,
        event_id=str(get("event_id", "")),
        symbol=symbol,
        timeframe=timeframe,
        family=str(get("family", "")),
        timestamp=float(get("timestamp", 0.0) or 0.0),
        predicted_prob=float(prob_raw),
        outcome=bool(get("outcome", False)),
        context={str(k): str(v) for k, v in context.items()},
        # PR-quantum-strict-audit: cache the ``get`` result via walrus so
        # mypy --strict can narrow ``Any | None`` -> ``Any`` for the
        # ``float(...)`` / ``str(...)`` call. Two separate ``get`` calls
        # would also be a (theoretical) idempotency hazard if ``context``
        # mutated between them.
        raw_score=(
            float(_rs) if (_rs := get("raw_score")) is not None else None
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
    count = 0
    with output_path.open("w", encoding="utf-8") as handle:
        for event in events:
            record = _scored_event_to_record(
                event, symbol=symbol, timeframe=timeframe
            )
            handle.write(json.dumps(asdict(record), separators=(",", ":")))
            handle.write("\n")
            count += 1
    return count


def read_event_ledger(path: Path) -> Iterator[dict[str, Any]]:
    """Yield records from a JSONL ledger (raw dicts, no class coercion)."""
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            yield json.loads(line)


def ledger_path_for_pair(
    pair_dir: Path, *, symbol: str, timeframe: str
) -> Path:
    """Canonical sibling path next to ``scoring_<sym>_<tf>.json``."""
    return pair_dir / f"events_{symbol}_{timeframe}.jsonl"
