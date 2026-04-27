"""C11 Wiederaufnahme-Anker — fires when the C8-Phase-B live stream is
available but the C11 online-learning-loop module is still absent.

Background
----------
``docs/SPRINT_ROADMAP_C2_C9_CONSOLIDATED_2026-04-26.md`` §"C11-Skip-
Begründung" defers C11 (online-learning-loop for family-Brier-decay)
until after C8-Phase-B sign-off because the loop calibrates against
the live stream and would otherwise overfit to synthetic / paper data.

The C-sprint deep review found that — unlike C9 (which has
``test_c9_threshold_finalisation_anchor.py``) and C12 (which has
``test_c12_trigger_phase_b_alignment.py``) — there was **no machine-
checkable trigger** that reminds the team to resume C11 once the
precondition is met. A roadmap-prose deferral that isn't pinned by a
test slowly disappears from the team's awareness as files churn.

Behaviour
---------
* Today (C12 trigger BLOCKED / UNEVALUABLE) this test is a no-op pass.
* Once at least one family has reached Phase-B (C12 trigger flips to
  GREEN, i.e. ≥ ``MIN_LIVE_DAYS`` live days and ≥ ``MIN_LIVE_TRADES``
  closed live trades with an acceptable drift verdict) **and** no
  ``c11/`` module / package has been added to the repo, this test
  fails with a remediation message pointing at the roadmap section.

The anchor is intentionally cheap: pure-stdlib, parses the trigger
report via :func:`scripts.check_c12_trigger.evaluate_trigger` (which
has its own offline fast-path) and inspects the repo tree.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.check_c12_trigger import evaluate_trigger

REPO_ROOT = Path(__file__).resolve().parent.parent

# Candidate locations that would hold a C11 implementation. Any of
# these existing as a real Python module / package satisfies the
# anchor — a future contributor can land C11 wherever it fits best.
_C11_CANDIDATES = (
    REPO_ROOT / "c11",
    REPO_ROOT / "ml" / "online_learning",
    REPO_ROOT / "ml" / "c11",
    REPO_ROOT / "scripts" / "c11_online_brier_decay.py",
)


def _c11_implementation_present() -> bool:
    for path in _C11_CANDIDATES:
        if path.is_dir() and (path / "__init__.py").exists():
            return True
        if path.is_file() and path.suffix == ".py":
            return True
    return False


def test_c11_anchor_fires_when_phase_b_live_and_no_implementation() -> None:
    """The anchor: as soon as Phase-B becomes evaluable (C12 trigger
    GREEN) and no ``c11/``-equivalent module exists, this test fails
    so the team is forced to either land C11 or update the roadmap.
    """
    result = evaluate_trigger()
    if result.status == "GREEN" and not _c11_implementation_present():
        pytest.fail(
            "C8-Phase-B live stream is now sufficient (C12 trigger is "
            "GREEN with ≥ 1 qualifying family) but no C11 online-"
            "learning-loop implementation was found in any of: "
            f"{[str(p.relative_to(REPO_ROOT)) for p in _C11_CANDIDATES]}. "
            "Per docs/SPRINT_ROADMAP_C2_C9_CONSOLIDATED_2026-04-26.md "
            "§'C11-Skip-Begründung', C11 was deferred precisely until "
            "this point. Either land the family-Brier-decay loop or "
            "amend the roadmap with a fresh deferral justification."
        )


def test_c11_anchor_passes_silently_while_trigger_not_green() -> None:
    """Today the C12 trigger is BLOCKED / UNEVALUABLE, so the anchor
    must remain a no-op pass regardless of repo state.
    """
    result = evaluate_trigger()
    if result.status != "GREEN":
        return  # Dormant — assertion holds trivially.
    pytest.skip(
        "C12 trigger is GREEN; the actual C11 resume anchor test runs."
    )


def test_c11_skip_section_still_in_roadmap() -> None:
    """The roadmap deferral text must remain anchored. If someone
    deletes the §'C11-Skip-Begründung' section without landing C11,
    fail loud — the deferral context is the only audit trail.
    """
    roadmap = (
        REPO_ROOT
        / "docs"
        / "SPRINT_ROADMAP_C2_C9_CONSOLIDATED_2026-04-26.md"
    )
    if not roadmap.exists():
        pytest.skip("Consolidated roadmap doc not present in this checkout.")
    text = roadmap.read_text(encoding="utf-8")
    assert "C11-Skip-Begründung" in text or "C11-Skip" in text, (
        "Consolidated roadmap no longer contains the C11-Skip section. "
        "Either restore the deferral context or land a C11 module — "
        "the roadmap is the only audit trail for why C11 was skipped."
    )
