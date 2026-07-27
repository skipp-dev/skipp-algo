"""Label backfill for the G3 arm records (`labels_<day>.json`).

The paired ab_arms records name the symbols each arm ranked, but only Arm A's
symbols get 30-minute labels through the regular outcome backfill (it labels
the ranked snapshot). Arm-B-only symbols would stay unlabeled — biasing the
paired comparison toward the intersection. This backfill resolves labels for
BOTH arms into a SEPARATE store next to the records, because writing arm-B
shadow rows into ``outcomes_<day>.json`` would contaminate
``compute_hit_rates`` and the FI ledger with rows no served ranking produced.

Contract pinned here: outcomes labels are reused (no double fetch), arm-B-only
symbols are fetched via the provider, unresolved stays ``None`` (pending, not
False), and non-ok days are skipped.
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from open_prep import outcome_backfill as ob


@pytest.fixture()
def dirs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    outcomes = tmp_path / "outcomes"
    ab = tmp_path / "ab_arms"
    outcomes.mkdir()
    ab.mkdir()
    monkeypatch.setenv("OPEN_PREP_OUTCOMES_DIR", str(outcomes))
    monkeypatch.setattr(ob, "AB_ARMS_DIR", ab)
    return {"outcomes": outcomes, "ab": ab}


def _write(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def _arm_record(ab: Path, day: str, *, status: str = "ok",
                a: list[str] | None = None, b: list[str] | None = None) -> None:
    _write(ab / f"ab_arms_{day}.json", {
        "schema_version": 1, "day": day, "status": status,
        "arm_a_top": a or [], "arm_b_top": b or [],
    })


def _outcomes_file(outcomes: Path, day: str, rows: list[dict[str, Any]]) -> None:
    _write(outcomes / f"outcomes_{day}.json", rows)


def test_outcome_labels_are_reused_and_arm_b_only_symbols_fetched(
    dirs: dict[str, Path], monkeypatch: pytest.MonkeyPatch,
) -> None:
    day = "2026-07-27"
    _arm_record(dirs["ab"], day, a=["AA"], b=["AA", "BB"])
    _outcomes_file(dirs["outcomes"], day, [
        {"symbol": "AA", "profitable_30m": True, "pnl_30m_pct": 1.2},
    ])

    fetched: list[list[str]] = []

    def _fake_fetch(provider: Any, symbols: list[str], run_date: date, **_kw: Any) -> Any:
        fetched.append(sorted(symbols))
        return MagicMock(empty=False)

    monkeypatch.setattr(ob, "_fetch_bars", _fake_fetch)
    monkeypatch.setattr(
        ob, "compute_pnl_from_bars",
        lambda bars_df, symbol, run_date, **_kw: {
            "profitable_30m": symbol == "BB", "pnl_30m_pct": 0.5,
        },
    )

    summary = ob.backfill_ab_arm_labels(
        target_dates=[date(2026, 7, 27)], provider=MagicMock(),
    )

    # AA came from outcomes — only BB needed a fetch.
    assert fetched == [["BB"]]
    payload = json.loads((dirs["ab"] / f"labels_{day}.json").read_text(encoding="utf-8"))
    assert payload["labels"]["AA"] == {
        "profitable_30m": True, "pnl_30m_pct": 1.2, "source": "outcomes",
    }
    assert payload["labels"]["BB"]["profitable_30m"] is True
    assert payload["labels"]["BB"]["source"] == "ab_backfill"
    assert summary["resolved"] == 2


def test_unresolved_symbol_stays_pending_none_not_false(
    dirs: dict[str, Path], monkeypatch: pytest.MonkeyPatch,
) -> None:
    day = "2026-07-27"
    _arm_record(dirs["ab"], day, a=[], b=["CC"])
    monkeypatch.setattr(ob, "_fetch_bars", lambda *a, **k: MagicMock(empty=False))
    monkeypatch.setattr(
        ob, "compute_pnl_from_bars", lambda bars_df, symbol, run_date, **_kw: None,
    )

    summary = ob.backfill_ab_arm_labels(
        target_dates=[date(2026, 7, 27)], provider=MagicMock(),
    )
    payload = json.loads((dirs["ab"] / f"labels_{day}.json").read_text(encoding="utf-8"))
    assert payload["labels"]["CC"]["profitable_30m"] is None
    assert "CC" in payload["pending"]
    assert summary["pending"] == 1


def test_non_ok_day_is_skipped_without_writing_labels(
    dirs: dict[str, Path],
) -> None:
    day = "2026-07-27"
    _arm_record(dirs["ab"], day, status="arm_b_unavailable", a=["AA"], b=[])
    summary = ob.backfill_ab_arm_labels(
        target_dates=[date(2026, 7, 27)], provider=MagicMock(),
    )
    assert not (dirs["ab"] / f"labels_{day}.json").exists()
    assert summary["days_skipped"] == 1


def test_outcome_rows_never_gain_arm_b_shadow_entries(
    dirs: dict[str, Path], monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The contamination guard: outcomes_<day>.json stays byte-identical."""
    day = "2026-07-27"
    _arm_record(dirs["ab"], day, a=["AA"], b=["BB"])
    _outcomes_file(dirs["outcomes"], day, [
        {"symbol": "AA", "profitable_30m": False, "pnl_30m_pct": -0.4},
    ])
    before = (dirs["outcomes"] / f"outcomes_{day}.json").read_bytes()

    monkeypatch.setattr(ob, "_fetch_bars", lambda *a, **k: MagicMock(empty=False))
    monkeypatch.setattr(
        ob, "compute_pnl_from_bars",
        lambda bars_df, symbol, run_date, **_kw: {
            "profitable_30m": False, "pnl_30m_pct": -0.1,
        },
    )
    ob.backfill_ab_arm_labels(target_dates=[date(2026, 7, 27)], provider=MagicMock())

    assert (dirs["outcomes"] / f"outcomes_{day}.json").read_bytes() == before
