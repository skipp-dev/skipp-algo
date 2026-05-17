"""Sprint C7.1 — Decision-First Panel renderer.

Today's terminal lays per-sprint metrics side-by-side; a reviewer
must scroll across tabs to answer "why isn't family X promoted?".
This panel collapses the answer into a single card per family:

    [TRAFFIC LIGHT]  FAMILY                     PROMOTED / BLOCKED
        top blocker (severity / check):  message
        sparkline of recent walk-forward Brier
        metrics summary

The panel consumes ``Decision`` dicts from
``governance.promotion_gate.PromotionGate.evaluate(...)`` (Sprint X2)
as its only source of truth. To stay independent of an X2 import
order we duck-type the Decision dict (the schema is pinned at
``governance.types.Decision`` with schema_version>=1).

The renderer is a pure text mode; snapshot tests assert this output
verbatim. A streamlit-aware mode can wrap this output later if needed.

Roadmap: docs/IMPROVEMENTS_C2_C12_ROADMAP_2026-04-26.md#c71
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from governance.promotion_report import (
    DEFAULT_PROMOTION_DECISIONS_PATH,
    load_decisions_from_report as _load_decisions_from_report,
)

POSTURE_GLYPH: dict[str, str] = {
    "green": "[GREEN]",
    "yellow": "[YELLOW]",
    "orange": "[ORANGE]",
    "red": "[RED]",
}

_SEVERITY_RANK = {"blocker": 3, "warning": 2, "info": 1}

# Unicode sparkline rendered with eighth-block characters for
# snapshot determinism. Requires a UTF-8 capable terminal/font.
_SPARK_CHARS = "▁▂▃▄▅▆▇█"


def sparkline(values: Sequence[float]) -> str:
    """Render a sequence of floats as a fixed-charset ASCII sparkline.

    Empty input → empty string. Constant input → all-mid characters
    (avoids divide-by-zero). Caller is responsible for windowing.
    """
    if not values:
        return ""
    lo = min(values)
    hi = max(values)
    if hi - lo < 1e-12:
        return _SPARK_CHARS[len(_SPARK_CHARS) // 2] * len(values)
    span = hi - lo
    n = len(_SPARK_CHARS) - 1
    return "".join(
        _SPARK_CHARS[round((v - lo) / span * n)] for v in values
    )


@dataclass(frozen=True)
class FamilyCard:
    family: str
    posture: str
    promoted: bool
    top_blocker: str
    sparkline: str
    metrics_summary: str


def _top_blocker(blockers: Iterable[Mapping[str, object]]) -> str:
    """Highest-severity blocker as 'severity/check: message'; '' on empty."""
    items = list(blockers)
    if not items:
        return ""
    items.sort(key=lambda b: -_SEVERITY_RANK.get(str(b.get("severity", "info")), 0))
    top = items[0]
    return f"{top['severity']}/{top['check']}: {top['message']}"


def _metrics_summary(metrics: Mapping[str, float]) -> str:
    """Stable, comma-separated 'k=v.4f' for the headline metrics."""
    if not metrics:
        return "(no metrics)"
    keys = sorted(metrics)
    return ", ".join(f"{k}={float(metrics[k]):.4f}" for k in keys)


def build_card(
    decision: Mapping[str, object],
    *,
    walkforward_history: Sequence[float] | None = None,
) -> FamilyCard:
    """Construct a ``FamilyCard`` from a ``Decision`` dict + optional history."""
    raw_blockers = decision.get("blockers") or ()
    raw_metrics = decision.get("metrics") or {}
    blockers = list(cast("Iterable[Mapping[str, object]]", raw_blockers))
    metrics = dict(cast("Mapping[str, float]", raw_metrics))
    posture = str(decision.get("posture", "red"))
    family = decision.get("family")
    if family is None:
        raise KeyError("decision is missing required 'family' key")
    return FamilyCard(
        family=str(family),
        posture=posture,
        promoted=bool(decision.get("promoted", False)),
        top_blocker=_top_blocker(blockers),
        sparkline=sparkline(walkforward_history or []),
        metrics_summary=_metrics_summary(metrics),
    )


def render_card(card: FamilyCard) -> str:
    """Return the deterministic 4-line text rendering for one card.

    Snapshot tests assert this output verbatim; do not reorder lines
    without bumping the panel's schema understanding.
    """
    glyph = POSTURE_GLYPH.get(card.posture, f"[{card.posture.upper()}]")
    status = "PROMOTED" if card.promoted else "BLOCKED"
    lines = [
        f"{glyph}  {card.family:6s}                 {status}",
        f"    top: {card.top_blocker}" if card.top_blocker else "    top: (no blockers)",
        f"    sparkline: {card.sparkline}" if card.sparkline else "    sparkline: (no history)",
        f"    metrics: {card.metrics_summary}",
    ]
    return "\n".join(lines)


def render_panel(
    decisions: Sequence[Mapping[str, object]],
    *,
    walkforward_histories: Mapping[str, Sequence[float]] | None = None,
) -> str:
    """Render N decision dicts as a single text panel, one card per family.

    Cards are emitted in input order; callers control sort. A single
    blank line separates cards (the join uses ``"\n\n"``) so snapshots
    remain robust to single-card edits.
    """
    histories = walkforward_histories or {}
    blocks: list[str] = []
    for d in decisions:
        # Defensive: synthesise a family stub for malformed decision dicts
        # so the panel still renders rather than masking the upstream bug.
        decision: Mapping[str, object]
        decision = {**d, "family": "?"} if "family" not in d else d
        family = str(decision["family"])
        history = histories.get(family, [])
        blocks.append(render_card(build_card(decision, walkforward_history=history)))
    return "\n\n".join(blocks)


def load_decisions_from_report(
    path: str | Path = DEFAULT_PROMOTION_DECISIONS_PATH,
) -> list[Mapping[str, object]]:
    """Load the decision list from the shared PromotionGate report contract."""
    return _load_decisions_from_report(path)


__all__ = [
    "DEFAULT_PROMOTION_DECISIONS_PATH",
    "POSTURE_GLYPH",
    "FamilyCard",
    "build_card",
    "load_decisions_from_report",
    "render_card",
    "render_panel",
    "sparkline",
]
