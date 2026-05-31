"""EV-10 — end-to-end edge pipeline: real bars + structure -> archived verdict.

EV-06b/07/08/09 each shipped one seam of the evidence chain. This module
bolts them into the single command the roadmap was building toward::

    bars + detected SMC structure
        -> family_event_adapter.family_events_from_structure   (EV-07)
        -> family_returns.to_build_spec                        (EV-06b)
        -> build_family_metrics.build_bundle                   (EV-06)
        -> run_promotion_gate.build_report                     (X2)
        -> archive to governance/promotion_decisions/          (EV-09 source)
        -> family_verdict.build_verdict_report                 (EV-08)
        -> verdict_panel.render_verdict_panel                  (EV-09)

It fabricates nothing. Detection happens upstream; every number in the
emitted report traces to a real bar handed in via ``--input``. When the
return series for a family is empty (no triggered setups) that family is
simply absent from the bundle, and the gate/verdict honestly report it as
not measured / not evaluated rather than inventing a metric.

Input JSON (``--input``)::

    {
      "bars": [{"timestamp": <epoch_s>, "high": .., "low": .., "close": ..}, ...],
      "structure": {
        "bos": [...], "orderblocks": [...], "fvg": [...], "liquidity_sweeps": [...]
      },
      "periods_per_year": 252,      # optional
      "cost_bps": 5.0,              # optional
      "as_of": "<ISO-8601 or epoch>" # optional; enables the EV-04 PIT guard
    }

Exit codes mirror ``run_promotion_gate``: 0 all families promoted, 2 at
least one blocked, 1 configuration error.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from governance.family_event_adapter import family_events_from_structure
from governance.family_returns import to_build_spec
from governance.family_verdict import build_verdict_report
from scripts.build_family_metrics import build_bundle
from scripts.run_promotion_gate import (
    DEFAULT_PROMOTION_DECISIONS_ARCHIVE_DIR,
    _archive_report,
    _family_metrics_from_dict,
    _report_exit_code,
    build_report,
)
from scripts.smc_atomic_write import atomic_write_json

_STRUCTURE_KEYS = ("bos", "orderblocks", "fvg", "liquidity_sweeps")


def _coerce_as_of(value: object) -> float | None:
    """Accept an epoch-second number or an ISO-8601 string; return epoch float.

    ``None`` passes through (the PIT guard is then simply not armed). A bad
    value raises ``ValueError`` so the CLI can fail loudly rather than run a
    silently un-guarded pipeline.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError(f"as_of must be a number or ISO string, got {value!r}")
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        parsed = datetime.fromisoformat(value)
        # A naive ISO string is interpreted as UTC, matching the UTC epoch
        # rendering used for the event anchor timestamps in to_build_spec.
        # Using the bare local-time .timestamp() here would shift as_of by
        # the host's UTC offset and silently mis-arm the EV-04 PIT guard.
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.timestamp()
    raise ValueError(f"as_of must be a number or ISO string, got {type(value).__name__}")


def run_pipeline(
    payload: Any,
    *,
    archive_dir: str | Path | None = DEFAULT_PROMOTION_DECISIONS_ARCHIVE_DIR,
    strict_provenance: bool = True,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Run the full edge pipeline on one ``payload`` dict.

    Returns ``{"report", "verdict_report", "archived_path", "events"}`` where
    ``report`` is the promotion-gate report (also archived), ``verdict_report``
    is the honest EV-08 verdict bundle, ``archived_path`` is the timestamped
    archive file (or ``None`` when archiving is disabled), and ``events`` is
    the number of family events the adapter produced.
    """
    if not isinstance(payload, dict):
        raise ValueError(f"input must be a JSON object, got {type(payload).__name__}")

    bars = payload.get("bars")
    if not isinstance(bars, list) or not bars:
        raise ValueError("input.bars must be a non-empty list of OHLC bars")

    structure = payload.get("structure")
    if not isinstance(structure, dict):
        raise ValueError("input.structure must be an object with detected SMC events")
    if not any(structure.get(key) for key in _STRUCTURE_KEYS):
        raise ValueError(
            "input.structure has no events under "
            f"{_STRUCTURE_KEYS!r}; nothing to evaluate"
        )

    periods_per_year = int(payload.get("periods_per_year", 252))
    cost_bps = float(payload.get("cost_bps", 5.0))
    as_of = _coerce_as_of(payload.get("as_of"))

    events = family_events_from_structure(structure, bars)
    spec = to_build_spec(
        events,
        periods_per_year=periods_per_year,
        cost_bps=cost_bps,
        as_of=as_of,
    )
    if not spec.get("families"):
        raise ValueError(
            "no triggered family events produced a return series; "
            "cannot build a metrics bundle (honest empty result)"
        )

    bundle = build_bundle(spec)
    snapshots = [_family_metrics_from_dict(item) for item in bundle]
    report = build_report(snapshots, strict_provenance=strict_provenance, now=now)
    archived_path = _archive_report(report, archive_dir)
    verdict_report = build_verdict_report(report)

    return {
        "report": report,
        "verdict_report": verdict_report,
        "archived_path": archived_path,
        "events": len(events),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "EV-10: run the full edge pipeline (bars + structure -> archived "
            "promotion decision + honest verdict)."
        )
    )
    parser.add_argument(
        "--input",
        type=Path,
        required=True,
        help="Path to the JSON input (bars + structure + optional as_of).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional path to also write the promotion-gate report JSON.",
    )
    parser.add_argument(
        "--archive-dir",
        type=str,
        default=str(DEFAULT_PROMOTION_DECISIONS_ARCHIVE_DIR),
        help="Directory for the timestamped decision archive; '' disables it.",
    )
    parser.add_argument(
        "--no-strict",
        action="store_true",
        help="Disable strict_provenance (legacy behaviour; do not use in prod).",
    )
    args = parser.parse_args(argv)

    archive_dir: str | None = args.archive_dir if args.archive_dir.strip() else None

    try:
        payload = json.loads(args.input.read_text(encoding="utf-8"))
        result = run_pipeline(
            payload,
            archive_dir=archive_dir,
            strict_provenance=not args.no_strict,
        )
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    report = result["report"]
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(report, args.output, indent=2, sort_keys=False)

    archived = result["archived_path"]
    summary = result["verdict_report"].get("summary", {})
    print(
        f"pipeline ok: {result['events']} event(s) -> "
        f"{len(report['decisions'])} decision(s); verdicts {summary}"
    )
    if archived is not None:
        print(f"archived: {archived}")

    return _report_exit_code(report)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
