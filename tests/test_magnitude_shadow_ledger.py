"""Unit tests for the ADR-0023 Stage-1 shadow-ledger runner."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import run_magnitude_shadow_ledger as shadow


def _result(
    *,
    passes: bool = False,
    min_sample_pass: bool = True,
    auc_floor_pass: bool = True,
    auc_ci_pass: bool = True,
    resolution_pass: bool = True,
    n_oos: int = 100,
    mag_auc: float = 0.58,
) -> dict:
    return {
        "n_oos": n_oos,
        "mag_auc": mag_auc,
        "auc_ci_low": 0.54,
        "baseline_resolution": 0.01,
        "perm_null_p95": 0.005,
        "perm_p_value": 0.02,
        "passes": passes,
        "min_sample_pass": min_sample_pass,
        "auc_floor_pass": auc_floor_pass,
        "auc_ci_pass": auc_ci_pass,
        "resolution_pass": resolution_pass,
    }


def _report(results: dict[str, dict], *, seed: int = 230_022) -> dict:
    return {
        "seed": seed,
        "families_measured": sorted(results),
        "families_passed": sorted(f for f, r in results.items() if r["passes"]),
        "results": results,
    }


# --------------------------------------------------------------------------- #
# classify_family
# --------------------------------------------------------------------------- #
def test_classify_pass() -> None:
    status, reasons = shadow.classify_family(_result(passes=True))
    assert status == "PASS"
    assert reasons == []


def test_classify_inconclusive_takes_priority_over_fail() -> None:
    # Too-thin sample is inconclusive even if other sub-checks also fail.
    status, reasons = shadow.classify_family(
        _result(min_sample_pass=False, auc_floor_pass=False)
    )
    assert status == "INCONCLUSIVE"
    assert reasons == ["n_oos_below_min"]


def test_classify_fail_collects_all_reasons() -> None:
    status, reasons = shadow.classify_family(
        _result(
            passes=False,
            auc_floor_pass=False,
            auc_ci_pass=False,
            resolution_pass=False,
        )
    )
    assert status == "FAIL"
    assert reasons == ["auc_floor", "auc_ci", "resolution_null"]


# --------------------------------------------------------------------------- #
# build_ledger_rows
# --------------------------------------------------------------------------- #
def test_build_rows_tags_roles_and_sorts() -> None:
    report = _report(
        {
            "OB": _result(),
            "BOS": _result(passes=True, mag_auc=0.62),
            "FVG": _result(),
            "SWEEP": _result(passes=True, mag_auc=0.66),
        }
    )
    rows = shadow.build_ledger_rows(report, date="2026-06-06", events_hash="abc")
    assert [r["family"] for r in rows] == ["BOS", "FVG", "OB", "SWEEP"]
    roles = {r["family"]: r["role"] for r in rows}
    assert roles == {
        "BOS": "candidate",
        "SWEEP": "candidate",
        "FVG": "control",
        "OB": "control",
    }
    bos = next(r for r in rows if r["family"] == "BOS")
    assert bos["status"] == "PASS"
    assert bos["passes"] is True
    assert bos["magnitude_auc"] == 0.62
    assert bos["seed"] == 230_022
    assert set(bos) == set(shadow.LEDGER_COLUMNS)


# --------------------------------------------------------------------------- #
# load_ledger / merge_rows
# --------------------------------------------------------------------------- #
def test_load_ledger_missing_file_is_empty(tmp_path: Path) -> None:
    assert shadow.load_ledger(str(tmp_path / "nope.jsonl")) == []


def test_load_ledger_skips_malformed_lines(tmp_path: Path) -> None:
    path = tmp_path / "led.jsonl"
    path.write_text(
        '{"date": "2026-06-01", "family": "BOS"}\n'
        "not json\n"
        "\n"
        '{"date": "2026-06-02", "family": "SWEEP"}\n',
        encoding="utf-8",
    )
    rows = shadow.load_ledger(str(path))
    assert [r["family"] for r in rows] == ["BOS", "SWEEP"]


def test_merge_idempotent_on_date_family_hash() -> None:
    old = {"date": "2026-06-06", "family": "BOS", "events_hash": "h1", "status": "FAIL"}
    new = {"date": "2026-06-06", "family": "BOS", "events_hash": "h1", "status": "PASS"}
    merged = shadow.merge_rows([old], [new])
    assert len(merged) == 1
    assert merged[0]["status"] == "PASS"  # latest wins


def test_merge_keeps_distinct_keys_sorted() -> None:
    rows = shadow.merge_rows(
        [{"date": "2026-06-06", "family": "SWEEP", "events_hash": "h"}],
        [
            {"date": "2026-06-06", "family": "BOS", "events_hash": "h"},
            {"date": "2026-06-05", "family": "OB", "events_hash": "h"},
        ],
    )
    assert [(r["date"], r["family"]) for r in rows] == [
        ("2026-06-05", "OB"),
        ("2026-06-06", "BOS"),
        ("2026-06-06", "SWEEP"),
    ]


def test_merge_different_hash_same_day_keeps_both() -> None:
    rows = shadow.merge_rows(
        [{"date": "2026-06-06", "family": "BOS", "events_hash": "h1"}],
        [{"date": "2026-06-06", "family": "BOS", "events_hash": "h2"}],
    )
    assert len(rows) == 2


# --------------------------------------------------------------------------- #
# events_content_hash
# --------------------------------------------------------------------------- #
def test_events_hash_is_stable_and_order_sensitive() -> None:
    a = [{"family": "BOS", "x": 1}, {"family": "SWEEP", "x": 2}]
    assert shadow.events_content_hash(a) == shadow.events_content_hash(list(a))
    assert shadow.events_content_hash(a) != shadow.events_content_hash(a[::-1])


# --------------------------------------------------------------------------- #
# append_shadow_ledger
# --------------------------------------------------------------------------- #
def test_append_writes_and_is_idempotent(tmp_path: Path) -> None:
    ledger = str(tmp_path / "gov" / "shadow.jsonl")
    report = _report(
        {"BOS": _result(passes=True), "FVG": _result()}
    )
    first = shadow.append_shadow_ledger(
        report, ledger_path=ledger, date="2026-06-06", events_hash="h1"
    )
    assert {r["family"] for r in first} == {"BOS", "FVG"}

    on_disk = shadow.load_ledger(ledger)
    assert len(on_disk) == 2

    # Re-running the same day/data must not duplicate rows.
    shadow.append_shadow_ledger(
        report, ledger_path=ledger, date="2026-06-06", events_hash="h1"
    )
    assert len(shadow.load_ledger(ledger)) == 2

    # A new day appends without dropping history.
    shadow.append_shadow_ledger(
        report, ledger_path=ledger, date="2026-06-07", events_hash="h2"
    )
    rows = shadow.load_ledger(ledger)
    assert len(rows) == 4
    assert {r["date"] for r in rows} == {"2026-06-06", "2026-06-07"}


def test_append_emits_valid_jsonl(tmp_path: Path) -> None:
    ledger = tmp_path / "shadow.jsonl"
    shadow.append_shadow_ledger(
        _report({"BOS": _result(passes=True)}),
        ledger_path=str(ledger),
        date="2026-06-06",
        events_hash="h1",
    )
    for line in ledger.read_text(encoding="utf-8").splitlines():
        json.loads(line)  # must not raise


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #
def test_main_writes_ledger_and_returns_exit_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    events_path = tmp_path / "events.json"
    events_path.write_text(json.dumps([{"family": "BOS", "x": 1}]), encoding="utf-8")
    ledger = tmp_path / "shadow.jsonl"

    monkeypatch.setattr(
        shadow,
        "build_report",
        lambda events, **kw: _report({"BOS": _result(passes=True)}),
    )
    code = shadow.main(
        [str(events_path), "--ledger", str(ledger), "--date", "2026-06-06"]
    )
    assert code == 0
    rows = shadow.load_ledger(str(ledger))
    assert [r["family"] for r in rows] == ["BOS"]
    assert rows[0]["status"] == "PASS"


def test_main_empty_events_is_usage_error(tmp_path: Path) -> None:
    events_path = tmp_path / "events.json"
    events_path.write_text("[]", encoding="utf-8")
    assert shadow.main([str(events_path), "--ledger", str(tmp_path / "l.jsonl")]) == 1
