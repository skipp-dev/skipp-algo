"""Audit pin: ``pytest.skip`` per-file count budget.

Every ``pytest.skip(...)`` call or ``@pytest.mark.skip`` decorator in the
test suite is a test that *isn't* providing assertions. Skips are often
necessary (missing optional dependency, missing artifact in sparse
checkout) but they should never *grow* silently. This pin freezes the
current per-file skip count.

Reductions are encouraged: when a skip site is removed, drop or
decrement the entry here.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
_TESTS_DIR = _REPO_ROOT / "tests"

_SKIP_RE = re.compile(r"@pytest\.mark\.skip\b|pytest\.skip\s*\(")

_FROZEN_FILE_COUNTS: dict[str, int] = {
    "tests/test_c11_resume_anchor.py": 2,
    "tests/test_c9_threshold_finalisation_anchor.py": 1,
    "tests/test_c9_threshold_lock_status.py": 1,
    "tests/test_e2e_smoke_ci.py": 1,
    "tests/test_generate_smc_micro_profiles.py": 2,
    "tests/test_hero_surface_input_map.py": 1,
    "tests/test_performance_report.py": 1,
    "tests/test_pine_boundary_literals.py": 1,
    "tests/test_pine_input_surface.py": 2,
    "tests/test_plan_2_8_digest_symlink_count.py": 1,
    "tests/test_plan_2_8_runbook_link_check.py": 1,
    "tests/test_plan_2_8_runbook_sections.py": 1,
    "tests/test_plan_2_8_weekly_summary_metrics.py": 2,
    "tests/test_plan_2_8_weekly_summary_sha256.py": 1,
    "tests/test_ranking_golden.py": 1,
    "tests/test_scorer_tuning.py": 1,
    "tests/test_scoring_numeric_invariants_property.py": 1,
    "tests/test_six_zero_tripwires_bundle.py": 1,
    "tests/test_smc_schema_version_enforcement.py": 1,
    "tests/test_smc_trust_badges_dashboard.py": 1,
    "tests/test_workflow_live_window_posture.py": 2,
    "tests/test_workflow_pythonpath_for_direct_invoke.py": 1,
    "tests/test_zone_priority_calibration.py": 1,
}

_TOTAL_BUDGET = sum(_FROZEN_FILE_COUNTS.values())


def _count_skips(path: Path) -> int:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):  # pragma: no cover
        return 0
    return sum(1 for line in text.splitlines() if _SKIP_RE.search(line))


def _measured_counts() -> dict[str, int]:
    measured: dict[str, int] = {}
    for path in sorted(_TESTS_DIR.rglob("*.py")):
        # exclude self so docstring/regex literals don't count.
        if path.resolve() == Path(__file__).resolve():
            continue
        n = _count_skips(path)
        if n:
            rel = path.relative_to(_REPO_ROOT).as_posix()
            measured[rel] = n
    return measured


def test_no_pytest_skip_count_increases() -> None:
    measured = _measured_counts()
    over_budget: list[str] = []
    for rel, count in measured.items():
        budget = _FROZEN_FILE_COUNTS.get(rel)
        if budget is None:
            over_budget.append(
                f"{rel}: {count} skip(s) but file not in ledger — add to "
                f"_FROZEN_FILE_COUNTS or remove the skip"
            )
        elif count > budget:
            over_budget.append(
                f"{rel}: {count} skip(s) > budget {budget} — reduce or "
                f"raise budget (and justify in CHANGELOG)"
            )
    assert not over_budget, "pytest.skip count regressed:\n  - " + "\n  - ".join(
        over_budget
    )


def test_no_stale_file_in_ledger() -> None:
    measured = _measured_counts()
    stale: list[str] = []
    for rel in _FROZEN_FILE_COUNTS:
        actual = measured.get(rel, 0)
        if actual == 0:
            stale.append(f"{rel}: ledger=N>0 but file has 0 skip(s) — remove entry")
    assert not stale, "Stale entries in pytest.skip ledger:\n  - " + "\n  - ".join(
        stale
    )


def test_total_budget_matches_inventory() -> None:
    measured_total = sum(_measured_counts().values())
    assert measured_total <= _TOTAL_BUDGET, (
        f"Total pytest.skip count {measured_total} exceeds frozen total "
        f"{_TOTAL_BUDGET}"
    )


@pytest.mark.parametrize("rel", sorted(_FROZEN_FILE_COUNTS.keys()))
def test_ledger_file_exists(rel: str) -> None:
    """Bidirectional sanity: every ledgered path must still exist."""
    assert (_REPO_ROOT / rel).is_file(), (
        f"Ledger references missing test file: {rel}"
    )


def test_tests_inventory_sane() -> None:
    files = list(_TESTS_DIR.rglob("*.py"))
    assert len(files) >= 50, f"tests/ scan only found {len(files)} files"
