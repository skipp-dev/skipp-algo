"""Pin the pytest canonical-write guard on the outcome-ledger writers.

Root cause (2026-06-11): two full-pipeline tests in ``tests/test_open_prep.py``
called ``generate_open_prep_result(..., now_utc=2026-02-23)`` without stubbing
the persistence tail. ``store_daily_outcomes`` resolves the *relative*
``OUTCOMES_DIR`` against the pytest cwd (= repo root) and silently rewrote the
TRACKED artefact ``artifacts/open_prep/outcomes/outcomes_2026-02-23.json`` on
every local test run. The polluted artefact was committed to main twice
(#2687, then again with vix9d fields after #2688/#2692), and the backfill
automation (#1926) even "resolved" labels for the synthetic NVDA record,
contaminating hit-rate statistics.

These tests pin the fail-loud guard so the next unredirected writer fails
instead of polluting.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from open_prep import outcome_backfill, outcomes
from smc_core._pytest_canonical_write_guard import REPO_ROOT


def _record(symbol: str = "NVDA") -> dict:
    return {
        "symbol": symbol,
        "gap_pct": 2.0,
        "rvol": 1.5,
        "score": 4.0,
        "gap_bucket_label": "small",
        "rvol_bucket_label": "normal",
        "profitable_30m": None,
        "pnl_30m_pct": None,
    }


def test_store_daily_outcomes_blocks_canonical_dir_under_pytest() -> None:
    """Unredirected OUTCOMES_DIR must fail loudly, not pollute the repo."""
    assert outcomes.OUTCOMES_DIR == Path("artifacts/open_prep/outcomes"), (
        "Precondition: this test must observe the canonical (unredirected) "
        "OUTCOMES_DIR. If a fixture redirected it globally, fix the fixture "
        "scope instead of this assertion."
    )
    with pytest.raises(RuntimeError, match="store_daily_outcomes"):
        outcomes.store_daily_outcomes(date(2026, 2, 23), [_record()])


def test_store_daily_outcomes_allows_redirected_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(outcomes, "OUTCOMES_DIR", tmp_path)
    path = outcomes.store_daily_outcomes(date(2026, 2, 23), [_record()])
    assert path.parent == tmp_path
    assert json.loads(path.read_text(encoding="utf-8"))[0]["symbol"] == "NVDA"


def test_backfill_save_blocks_canonical_dir_under_pytest() -> None:
    canonical = outcome_backfill.OUTCOMES_DIR / "outcomes_2026-02-23.json"
    with pytest.raises(RuntimeError, match="_save_outcome_file"):
        outcome_backfill._save_outcome_file(canonical, [_record()])


def test_backfill_save_allows_redirected_dir(tmp_path: Path) -> None:
    target = tmp_path / "outcomes_2026-02-23.json"
    outcome_backfill._save_outcome_file(target, [_record()])
    assert json.loads(target.read_text(encoding="utf-8"))[0]["symbol"] == "NVDA"


def test_synthetic_2026_02_23_artifact_stays_deleted() -> None:
    """The 2026-02-23 outcomes file was synthetic from birth (single NVDA
    row with gap_pct=0.0/rvol=0.0 matching the mocked fixture in
    tests/test_open_prep.py, created by a test run and committed in
    6c0ced38). It was deleted in this PR; if it ever reappears, a test is
    leaking writes into the canonical artefact tree again.
    """
    leaked = REPO_ROOT / "artifacts/open_prep/outcomes/outcomes_2026-02-23.json"
    assert not leaked.exists(), (
        f"{leaked} reappeared — a test is writing into the canonical "
        "outcomes tree again. Find the unredirected writer; do NOT commit "
        "this file."
    )
