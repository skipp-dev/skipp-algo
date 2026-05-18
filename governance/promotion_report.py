"""Shared PromotionGate report contract for producers and UI consumers."""
from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

DEFAULT_PROMOTION_DECISIONS_PATH = Path("artifacts") / "promotion_decisions.json"
REPORT_SCHEMA_VERSION = 1


def load_decisions_from_report(
    path: str | Path = DEFAULT_PROMOTION_DECISIONS_PATH,
) -> list[Mapping[str, object]]:
    """Load the list of decision dicts from a W1.b promotion-gate report.

    The report is the JSON document written by ``scripts.run_promotion_gate``.
    Schema is validated minimally (must be a dict with a ``decisions`` list);
    per-decision validation is intentionally left to downstream consumers.
    """
    report_path = Path(path)
    raw = json.loads(report_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or "decisions" not in raw:
        raise ValueError(
            f"promotion-gate report {report_path} must be a dict with a 'decisions' "
            f"key (got {type(raw).__name__})"
        )
    decisions = raw["decisions"]
    if not isinstance(decisions, list):
        raise ValueError(
            f"promotion-gate report {report_path} 'decisions' must be a list "
            f"(got {type(decisions).__name__})"
        )
    return [dict(d) for d in decisions]


__all__ = [
    "DEFAULT_PROMOTION_DECISIONS_PATH",
    "REPORT_SCHEMA_VERSION",
    "load_decisions_from_report",
]
