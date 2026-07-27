"""G3 bridge: ab_arms paired records × outcome labels → watchdog comparison.

The §G3 gate consumes ``docs/ab/g23_history.jsonl`` via
``scripts.g23_ab_watchdog --input ab_comparison.json``. Before this bridge no
production path ever produced that input: the history sat empty
("awaiting_first_run") while the arm records accumulated unread in
``artifacts/open_prep/ab_arms/``.

Contract pinned here:
  * (n, k) are CUMULATIVE over every labeled day — W3-2 in the watchdog runs
    SPRT on the latest entry alone, so the bridge must aggregate, never emit
    per-day counts.
  * only labels with a resolved ``profitable_30m`` count; coverage of the
    unlabeled remainder is disclosed, never silently dropped.
  * days with ``status != "ok"`` (arm_b_unavailable / error) contribute
    nothing.
  * no treatment observations at all → no comparison file (the watchdog then
    correctly keeps reporting awaiting_first_run).
  * the emitted comparison feeds the REAL watchdog entry-builder unchanged.
"""
from __future__ import annotations

import json
from pathlib import Path

from scripts.g3_bridge_ab_arms import build_cumulative_comparison
from scripts.g3_bridge_ab_arms import main as bridge_main


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _day(ab_dir: Path, day: str, *, status: str = "ok",
         a: list[str] | None = None, b: list[str] | None = None) -> None:
    _write(ab_dir / f"ab_arms_{day}.json", {
        "schema_version": 1, "day": day, "status": status,
        "arm_a_top": a or [], "arm_b_top": b or [],
    })


def _labels(ab_dir: Path, day: str, labels: dict[str, bool | None]) -> None:
    _write(ab_dir / f"labels_{day}.json", {
        "schema_version": 1, "day": day,
        "labels": {s: {"profitable_30m": v, "pnl_30m_pct": None, "source": "test"}
                   for s, v in labels.items()},
    })


def test_cumulative_counts_across_days(tmp_path: Path) -> None:
    ab = tmp_path / "ab_arms"
    _day(ab, "2026-07-27", a=["AA", "AB"], b=["AA", "BB"])
    _labels(ab, "2026-07-27", {"AA": True, "AB": False, "BB": True})
    _day(ab, "2026-07-28", a=["AA"], b=["BB"])
    _labels(ab, "2026-07-28", {"AA": False, "BB": False})

    cmp_ = build_cumulative_comparison(ab_dir=ab)
    assert cmp_ is not None
    sprt = cmp_["sprt"]
    # control (arm A): day1 AA=hit, AB=miss; day2 AA=miss -> n=3, k=1
    assert sprt["control_n"] == 3
    assert sprt["control_hit_rate"] == round(1 / 3, 4)
    # treatment (arm B): day1 AA=hit, BB=hit; day2 BB=miss -> n=3, k=2
    assert sprt["n"] == 3
    assert sprt["k"] == 2
    assert sprt["hit_rate"] == round(2 / 3, 4)
    assert cmp_["days_aggregated"] == 2


def test_non_ok_days_and_unlabeled_symbols_are_disclosed_not_counted(tmp_path: Path) -> None:
    ab = tmp_path / "ab_arms"
    _day(ab, "2026-07-27", a=["AA"], b=["BB", "CC"])
    _labels(ab, "2026-07-27", {"AA": True, "BB": True, "CC": None})  # CC unresolved
    _day(ab, "2026-07-28", status="arm_b_unavailable", a=["AA"], b=[])

    cmp_ = build_cumulative_comparison(ab_dir=ab)
    assert cmp_ is not None
    assert cmp_["sprt"]["n"] == 1  # only BB counts for treatment
    assert cmp_["coverage"]["treatment_unlabeled"] == 1  # CC disclosed
    assert cmp_["coverage"]["days_skipped_not_ok"] == 1


def test_day_without_labels_file_is_skipped_and_disclosed(tmp_path: Path) -> None:
    ab = tmp_path / "ab_arms"
    _day(ab, "2026-07-27", a=["AA"], b=["BB"])  # no labels yet (backfill pending)
    cmp_ = build_cumulative_comparison(ab_dir=ab)
    assert cmp_ is None  # zero treatment observations -> no comparison at all


def test_no_treatment_observations_emits_no_file(tmp_path: Path) -> None:
    ab = tmp_path / "ab_arms"
    out = tmp_path / "cmp.json"
    _day(ab, "2026-07-27", a=["AA"], b=["BB"])
    _labels(ab, "2026-07-27", {"AA": True, "BB": None})
    rc = bridge_main(["--ab-dir", str(ab), "--out", str(out)])
    assert rc == 0
    assert not out.exists()


def test_bridge_output_feeds_the_real_watchdog_entry_builder(tmp_path: Path) -> None:
    """End-to-end compatibility: no bespoke schema drift between the two."""
    from scripts.g23_ab_watchdog import _extract_arm_totals, _make_history_entry

    ab = tmp_path / "ab_arms"
    out = tmp_path / "cmp.json"
    _day(ab, "2026-07-27", a=["AA", "AB"], b=["AA", "BB"])
    _labels(ab, "2026-07-27", {"AA": True, "AB": False, "BB": True})
    rc = bridge_main(["--ab-dir", str(ab), "--out", str(out)])
    assert rc == 0
    comparison = json.loads(out.read_text(encoding="utf-8"))

    control_n, control_k, treatment_n, treatment_k = _extract_arm_totals(comparison)
    assert (control_n, control_k, treatment_n, treatment_k) == (2, 1, 2, 2)

    entry = _make_history_entry(
        comparison, timestamp="2026-07-27T22:30:00+00:00",
        source_path=out, source_commit_sha="deadbeef", source_workflow_run=None,
    )
    assert entry["treatment_n"] == 2
    assert entry["treatment_k"] == 2
    assert entry["control_hit_rate"] == 0.5
    assert entry["treatment_underperformed"] is False
