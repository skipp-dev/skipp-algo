"""Tests for ``scripts/plan_2_8_alert_history_heatmap.py``."""

from __future__ import annotations

import datetime as _dt
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "plan_2_8_alert_history_heatmap.py"


def _load():
    spec = importlib.util.spec_from_file_location("plan_2_8_alert_history_heatmap", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plan_2_8_alert_history_heatmap"] = mod
    spec.loader.exec_module(mod)
    return mod


hm = _load()


def _rec(day: str, tf: str, fam: str) -> dict[str, Any]:
    return {
        "captured_at": f"{day}T12:00:00+00:00",
        "tf":          tf,
        "family":      fam,
    }


def test_empty_records_returns_zero_totals() -> None:
    rep = hm.heatmap([])
    assert rep["total"] == 0
    assert rep["tf_family_totals"] == {}
    for wd in hm.WEEKDAYS:
        assert rep["weekday_totals"][wd] == 0


def test_weekday_binning() -> None:
    # 2026-04-20 is Monday; 2026-04-21 is Tuesday.
    recs = [
        _rec("2026-04-20", "5m",  "HR"),
        _rec("2026-04-21", "5m",  "HR"),
        _rec("2026-04-21", "15m", "FVG"),
    ]
    rep = hm.heatmap(recs)
    assert rep["weekday_totals"]["Mon"] == 1
    assert rep["weekday_totals"]["Tue"] == 2
    assert rep["tf_family_totals"]["5m/HR"] == 2
    assert rep["tf_family_totals"]["15m/FVG"] == 1
    assert rep["total"] == 3


def test_lookback_days_floor() -> None:
    recs = [
        _rec("2026-04-20", "5m", "HR"),
        _rec("2026-03-01", "5m", "HR"),  # too old
    ]
    now = _dt.datetime(2026, 4, 22, tzinfo=_dt.UTC)
    rep = hm.heatmap(recs, lookback_days=14, now=now)
    assert rep["total"] == 1
    assert rep["tf_family_totals"]["5m/HR"] == 1


def test_missing_tf_or_family_skipped() -> None:
    recs = [
        {"captured_at": "2026-04-20T12:00:00+00:00", "tf": "", "family": "HR"},
        {"captured_at": "2026-04-20T12:00:00+00:00", "tf": "5m", "family": ""},
        _rec("2026-04-20", "5m", "HR"),
    ]
    rep = hm.heatmap(recs)
    assert rep["total"] == 1


def test_bad_timestamp_skipped() -> None:
    recs = [
        {"captured_at": "not-a-date", "tf": "5m", "family": "HR"},
        _rec("2026-04-20", "5m", "HR"),
    ]
    rep = hm.heatmap(recs)
    assert rep["total"] == 1


def test_render_markdown_populated() -> None:
    recs = [_rec("2026-04-20", "5m", "HR"), _rec("2026-04-21", "5m", "HR")]
    md = hm.render_markdown(hm.heatmap(recs))
    assert "# Plan 2.8 alert-history heatmap" in md
    assert "5m/HR" in md
    assert "| weekday |" in md


def test_render_markdown_empty() -> None:
    md = hm.render_markdown(hm.heatmap([]))
    assert "No alerts in window" in md


def test_cli_json(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    log = tmp_path / "h.jsonl"
    log.write_text(
        "\n".join(json.dumps(_rec(d, "5m", "HR"))
                  for d in ("2026-04-20", "2026-04-21")) + "\n",
        encoding="utf-8",
    )
    rc = hm.main([
        "--log", str(log), "--format", "json",
    ])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["total"] == 2


def test_cli_md_output(tmp_path: Path) -> None:
    log = tmp_path / "h.jsonl"
    log.write_text(json.dumps(_rec("2026-04-20", "5m", "HR")) + "\n",
                   encoding="utf-8")
    out = tmp_path / "heatmap.md"
    rc = hm.main([
        "--log", str(log), "--output", str(out),
    ])
    assert rc == 0
    assert "Plan 2.8 alert-history heatmap" in out.read_text(encoding="utf-8")


def test_cli_missing_log(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    rc = hm.main(["--log", str(tmp_path / "nope.jsonl")])
    assert rc == 1
    assert "alert history log not found" in capsys.readouterr().err


def test_malformed_jsonl_lines_skipped(tmp_path: Path) -> None:
    log = tmp_path / "h.jsonl"
    log.write_text(
        json.dumps(_rec("2026-04-20", "5m", "HR")) + "\n"
        + "not-json\n"
        + "\n"
        + json.dumps(_rec("2026-04-21", "5m", "HR")) + "\n",
        encoding="utf-8",
    )
    rep = hm.heatmap(list(hm._iter_records(log)))
    assert rep["total"] == 2
