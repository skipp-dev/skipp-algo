"""Pin: ``smc_enrichment_value_analysis.lift`` keeps its temporal-numerical
audit anchor comment, so future reviewers can grep for ``N-1
(TEMPORAL_NUMERICAL_AUDIT_2026-04-24)`` and land directly on the
epsilon-guard rationale.

Audit follow-up to :file:`docs/reviews/2026-04-24-system-review.md` finding
**I-1** (Klasse #7, "Float ``==0.0``"): the code site is already correctly
guarded with ``abs(self.baseline_mean_pnl) < 1e-12``, but the comment
anchor is the durable signal that this was a deliberate audit-driven
choice. Without the anchor, a routine "remove dead comments" pass could
silently drop the rationale and a later reviewer might "simplify" the
guard back to ``== 0.0``.
"""
from __future__ import annotations

from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_TARGET = _REPO_ROOT / "scripts" / "smc_enrichment_value_analysis.py"
_ANCHOR = "N-1 (TEMPORAL_NUMERICAL_AUDIT_2026-04-24)"
_GUARD_FRAGMENT = "abs(self.baseline_mean_pnl) < 1e-12"


def test_target_file_exists() -> None:
    assert _TARGET.is_file(), f"missing pin target: {_TARGET}"


def test_audit_anchor_comment_present() -> None:
    text = _TARGET.read_text(encoding="utf-8")
    assert _ANCHOR in text, (
        f"expected audit anchor comment {_ANCHOR!r} in {_TARGET.name} "
        "(rationale for epsilon-guard on baseline_mean_pnl). Audit finding "
        "I-1 (Klasse #7). Do not remove the comment without re-reviewing "
        "the guard logic."
    )


def test_epsilon_guard_still_in_place() -> None:
    text = _TARGET.read_text(encoding="utf-8")
    assert _GUARD_FRAGMENT in text, (
        f"expected epsilon-guard fragment {_GUARD_FRAGMENT!r} in "
        f"{_TARGET.name} — without it, near-zero baseline_mean_pnl values "
        "(e.g. 1e-17) would produce massive outlier lift values. Audit "
        "finding I-1 (Klasse #7)."
    )
