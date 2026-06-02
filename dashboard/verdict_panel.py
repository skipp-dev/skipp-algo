"""EV-09 verdict panel: decision-first panel over the REAL decision archive.

The existing :mod:`dashboard.decision_first_panel` collapses one promotion
report into a card per family, but it says only ``PROMOTED`` / ``BLOCKED`` —
the *gate's* answer. A reviewer skimming a green light can misread it as
"edge proven", which is exactly the HARKing trap EV-01/EV-08 exist to close.

EV-09 renders the **honest verdict** (``governance.family_verdict``, EV-08)
on top of the decision-first card, sourced from the **real** timestamped
archive in ``governance/promotion_decisions/`` (the per-run history written
by ``scripts/run_promotion_gate.py``). It adds two things and fabricates
nothing:

  1. ``load_latest_report`` / ``walkforward_histories`` — read the real
     archive directory (latest report for the cards; the full chronological
     metric series per family for the sparkline).
  2. a verdict line per card so the panel shows
     ``edge_supported`` / ``no_edge`` / ``inconclusive`` / ``not_evaluated``
     beside the gate's promoted flag — never letting a promoted-but-
     unproven family read as a supported edge.

When the archive is empty (the current real state: no gate run has ever been
recorded) the loaders return ``None`` / ``{}`` and the panel renders an
explicit "no decisions archived yet" notice rather than fabricating a green
board.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from dashboard.decision_first_panel import build_card, render_card
from governance.family_verdict import FamilyVerdict, build_verdicts

# The real per-run archive (mirror of run_promotion_gate's archive dir).
DEFAULT_ARCHIVE_DIR = Path("governance") / "promotion_decisions"

# Metric whose chronological series feeds the per-family sparkline. The
# walk-forward Brier is the calibration signal the decision-first panel was
# designed around; fall back to None-skipping when a report lacks it.
_SPARKLINE_METRIC = "walkforward_brier"

VERDICT_GLYPH: dict[str, str] = {
    "edge_supported": "[EDGE]",
    "no_edge": "[NO-EDGE]",
    "inconclusive": "[INCONCLUSIVE]",
    "not_evaluated": "[N/A]",
}

_NO_DECISIONS_NOTICE = "(no decisions archived yet)"


def _archived_report_paths(archive_dir: Path) -> list[Path]:
    """Lexicographically-sorted archived report paths (chronological).

    The archive filenames are ``promotion_decisions_<UTC_STAMP>.json`` whose
    stamps sort lexicographically into chronological order.
    """
    if not archive_dir.exists():
        return []
    return sorted(archive_dir.glob("promotion_decisions_*.json"))


def _load_report(path: Path) -> Mapping[str, object] | None:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(raw, dict) or "decisions" not in raw:
        return None
    return raw


def load_latest_report(
    archive_dir: str | Path = DEFAULT_ARCHIVE_DIR,
) -> Mapping[str, object] | None:
    """Return the most recent valid archived report, or ``None`` if empty.

    Honest by construction: an empty archive yields ``None`` rather than a
    synthesized report.
    """
    for path in reversed(_archived_report_paths(Path(archive_dir))):
        report = _load_report(path)
        if report is not None:
            return report
    return None


def walkforward_histories(
    archive_dir: str | Path = DEFAULT_ARCHIVE_DIR,
    *,
    metric: str = _SPARKLINE_METRIC,
) -> dict[str, list[float]]:
    """Per-family chronological series of *metric* across the real archive.

    Reports are read oldest-to-newest; only finite numeric values present in
    a decision's ``metrics`` are appended, so a family with no measured value
    in a given run simply contributes no point (no fabricated zeros).
    """
    histories: dict[str, list[float]] = {}
    for path in _archived_report_paths(Path(archive_dir)):
        report = _load_report(path)
        if report is None:
            continue
        decisions = report.get("decisions")
        if not isinstance(decisions, list):
            continue
        for decision in decisions:
            if not isinstance(decision, Mapping):
                continue
            family = decision.get("family")
            metrics = decision.get("metrics")
            if not isinstance(family, str) or not isinstance(metrics, Mapping):
                continue
            value = metrics.get(metric)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                fvalue = float(value)
                if fvalue == fvalue and abs(fvalue) != float("inf"):  # finite
                    histories.setdefault(family, []).append(fvalue)
    return histories


@dataclass(frozen=True)
class VerdictCard:
    """A decision-first card augmented with the honest EV-08 verdict."""

    family: str
    verdict: str
    decision_card: str
    verdict_line: str


def _verdict_line(verdict: FamilyVerdict) -> str:
    glyph = VERDICT_GLYPH.get(verdict["verdict"], f"[{verdict['verdict'].upper()}]")
    metric = verdict["primary_metric"]
    value = verdict["primary_metric_value"]
    value_text = f"{value:.4f}" if value is not None else "unmeasured"
    observed_n = verdict["observed_n"]
    n_text = "n/a" if observed_n is None else str(observed_n)
    return (
        f"    verdict: {glyph} {verdict['verdict']} "
        f"(primary {metric}={value_text}, n={n_text}/{verdict['min_sample_n']})"
    )


def build_verdict_card(
    verdict: FamilyVerdict,
    decision: Mapping[str, object] | None,
    *,
    walkforward_history: Sequence[float] | None = None,
) -> VerdictCard:
    """Combine an EV-08 verdict with its decision-first card.

    When no gate decision exists for the family the card body is the verdict
    line alone (the family is ``not_evaluated``), keeping the honest "no
    evidence" state visible instead of dropping the family.
    """
    if decision is None:
        decision_card = f"[{verdict['verdict'].upper()}]  {verdict['family']:6s}                 NOT EVALUATED"
    else:
        decision_card = render_card(
            build_card(decision, walkforward_history=walkforward_history)
        )
    return VerdictCard(
        family=verdict["family"],
        verdict=verdict["verdict"],
        decision_card=decision_card,
        verdict_line=_verdict_line(verdict),
    )


def render_verdict_card(card: VerdictCard) -> str:
    return f"{card.decision_card}\n{card.verdict_line}"


def render_verdict_panel(
    report: Mapping[str, object] | None,
    *,
    archive_dir: str | Path = DEFAULT_ARCHIVE_DIR,
    hypotheses_path: Path | None = None,
) -> str:
    """Render the honest verdict panel for *report* over the real archive.

    ``report`` is typically :func:`load_latest_report`'s output. When it is
    ``None`` (empty archive) an explicit notice is returned. Sparklines use
    the chronological metric series from the same archive.
    """
    if report is None:
        return _NO_DECISIONS_NOTICE

    verdicts = build_verdicts(report, hypotheses_path=hypotheses_path)
    decisions = report.get("decisions")
    decision_by_family: dict[str, Mapping[str, object]] = {}
    if isinstance(decisions, list):
        for decision in decisions:
            if isinstance(decision, Mapping) and "family" in decision:
                decision_by_family[str(decision["family"])] = decision

    histories = walkforward_histories(archive_dir)

    blocks: list[str] = []
    for verdict in verdicts:
        family = verdict["family"]
        decision = decision_by_family.get(family)
        card = build_verdict_card(
            verdict,
            decision,
            walkforward_history=histories.get(family, []),
        )
        blocks.append(render_verdict_card(card))
    return "\n\n".join(blocks)


def render_panel_from_archive(
    archive_dir: str | Path = DEFAULT_ARCHIVE_DIR,
    *,
    hypotheses_path: Path | None = None,
) -> str:
    """Convenience: load the latest archived report and render its verdicts."""
    report = load_latest_report(archive_dir)
    return render_verdict_panel(
        report, archive_dir=archive_dir, hypotheses_path=hypotheses_path
    )


__all__ = [
    "DEFAULT_ARCHIVE_DIR",
    "VERDICT_GLYPH",
    "VerdictCard",
    "build_verdict_card",
    "load_latest_report",
    "render_panel_from_archive",
    "render_verdict_card",
    "render_verdict_panel",
    "walkforward_histories",
]
