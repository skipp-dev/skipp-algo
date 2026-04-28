"""Tests for ``scripts/plan_2_8_ledger_stats_json.py``."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "plan_2_8_ledger_stats_json.py"


def _load():
    spec = importlib.util.spec_from_file_location("plan_2_8_ledger_stats_json", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plan_2_8_ledger_stats_json"] = mod
    spec.loader.exec_module(mod)
    return mod


ls = _load()


def test_bucket_by_week() -> None:
    records = [
        {"captured_at": "2026-01-05T12:00:00+00:00", "status": "green"},  # W02
        {"captured_at": "2026-01-06T12:00:00+00:00", "status": "amber"},  # W02
        {"captured_at": "2026-01-12T12:00:00+00:00", "status": "green"},  # W03
    ]
    rep = ls.bucket(records, period="week")
    assert rep["counts"]["buckets"] == 2
    assert rep["buckets"]["2026-W02"] == {
        "green": 1, "amber": 1, "red": 0, "unknown": 0,
    }
    assert rep["buckets"]["2026-W03"]["green"] == 1


def test_bucket_by_month() -> None:
    records = [
        {"captured_at": "2026-01-05T12:00:00+00:00", "status": "green"},
        {"captured_at": "2026-02-01T12:00:00+00:00", "status": "amber"},
        {"captured_at": "2026-02-15T12:00:00+00:00", "status": "amber"},
    ]
    rep = ls.bucket(records, period="month")
    assert set(rep["buckets"].keys()) == {"2026-01", "2026-02"}
    assert rep["buckets"]["2026-02"]["amber"] == 2


def test_unknown_status_bucketed_as_unknown() -> None:
    records = [{"captured_at": "2026-01-05T12:00:00+00:00",
                "status": "bogus"}]
    rep = ls.bucket(records, period="week")
    assert rep["buckets"]["2026-W02"]["unknown"] == 1


def test_bad_timestamp_skipped() -> None:
    records = [
        {"captured_at": "not-a-date", "status": "green"},
        {"captured_at": "2026-01-05T12:00:00+00:00", "status": "green"},
    ]
    rep = ls.bucket(records, period="week")
    assert rep["counts"]["skipped"] == 1
    assert rep["counts"]["buckets"] == 1


def test_missing_status_skipped() -> None:
    rep = ls.bucket(
        [{"captured_at": "2026-01-05T12:00:00+00:00"}],
        period="week",
    )
    assert rep["counts"]["skipped"] == 1


def test_case_normalised_status() -> None:
    rep = ls.bucket([{
        "captured_at": "2026-01-05T12:00:00+00:00", "status": "GREEN",
    }], period="week")
    assert rep["buckets"]["2026-W02"]["green"] == 1


def test_buckets_are_sorted_deterministically() -> None:
    records = [
        {"captured_at": "2026-02-01T12:00:00+00:00", "status": "green"},
        {"captured_at": "2026-01-05T12:00:00+00:00", "status": "green"},
    ]
    rep = ls.bucket(records, period="month")
    assert list(rep["buckets"].keys()) == ["2026-01", "2026-02"]


def test_invalid_period_raises() -> None:
    with pytest.raises(ValueError):
        ls._bucket_key(
            __import__("datetime").datetime(2026, 1, 5),
            period="bogus",
        )


def test_render_markdown_empty() -> None:
    md = ls.render_markdown(ls.bucket([], period="week"))
    assert "No bucketed records" in md


def test_render_markdown_table() -> None:
    records = [{"captured_at": "2026-01-05T12:00:00+00:00",
                "status": "green"}]
    md = ls.render_markdown(ls.bucket(records, period="week"))
    assert "| 2026-W02 | 1 | 0 | 0 | 0 |" in md


def test_cli_json_output(tmp_path: Path) -> None:
    p = tmp_path / "l.jsonl"
    p.write_text(
        json.dumps({"captured_at": "2026-01-05T12:00:00+00:00",
                    "status": "green"}) + "\n",
        encoding="utf-8",
    )
    out = tmp_path / "s.json"
    rc = ls.main([
        "--ledger", str(p), "--format", "json", "--output", str(out),
    ])
    assert rc == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["period"] == "week"


def test_cli_md_format(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    p = tmp_path / "l.jsonl"
    p.write_text(
        json.dumps({"captured_at": "2026-01-05T12:00:00+00:00",
                    "status": "amber"}) + "\n",
        encoding="utf-8",
    )
    rc = ls.main(["--ledger", str(p), "--format", "md"])
    assert rc == 0
    assert "ledger stats" in capsys.readouterr().out


def test_cli_missing_ledger(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    rc = ls.main(["--ledger", str(tmp_path / "nope.jsonl")])
    assert rc == 1
    assert "ledger not found" in capsys.readouterr().err
