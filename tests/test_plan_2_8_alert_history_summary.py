"""Tests for ``scripts/plan_2_8_alert_history_summary.py``."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "plan_2_8_alert_history_summary.py"


def _load():
    spec = importlib.util.spec_from_file_location(
        "plan_2_8_alert_history_summary", SCRIPT,
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plan_2_8_alert_history_summary"] = mod
    spec.loader.exec_module(mod)
    return mod


mod = _load()


def _rec(captured: str, tf: str, fam: str, delta: float = 0.1) -> dict:
    return {"captured_at": captured, "tf": tf, "family": fam,
            "delta_pp": delta, "hr_prev": 0.5, "hr_latest": 0.5 + delta}


def _write(p: Path, recs: list[dict]) -> None:
    p.write_text("\n".join(json.dumps(r) for r in recs) + "\n",
                 encoding="utf-8")


def test_summarize_empty() -> None:
    r = mod.summarize([])
    assert r["status"] == "empty"
    assert r["top"] == []


def test_summarize_ranks_by_count() -> None:
    recs = [
        _rec("2026-04-05T00:00:00Z", "5m", "FVG"),
        _rec("2026-04-12T00:00:00Z", "5m", "FVG"),
        _rec("2026-04-19T00:00:00Z", "5m", "FVG"),
        _rec("2026-04-19T00:00:00Z", "1H", "OB"),
    ]
    import datetime as _dt
    r = mod.summarize(
        recs,
        lookback_days=30,
        now=_dt.datetime(2026, 4, 21, tzinfo=_dt.UTC),
    )
    assert r["top"][0]["family"] == "FVG"
    assert r["top"][0]["count"] == 3
    assert r["top"][1]["family"] == "OB"


def test_summarize_respects_lookback() -> None:
    recs = [
        _rec("2025-01-01T00:00:00Z", "5m", "FVG"),
        _rec("2026-04-19T00:00:00Z", "5m", "FVG"),
    ]
    import datetime as _dt
    r = mod.summarize(
        recs, lookback_days=30,
        now=_dt.datetime(2026, 4, 21, tzinfo=_dt.UTC),
    )
    assert r["top"][0]["count"] == 1
    assert r["records_in_window"] == 1


def test_ignores_malformed_rows() -> None:
    recs = [
        {"tf": "5m"},  # no captured_at
        {"captured_at": "not-a-ts", "tf": "5m", "family": "FVG"},
        _rec("2026-04-19T00:00:00Z", "5m", "FVG"),
    ]
    import datetime as _dt
    r = mod.summarize(
        recs, lookback_days=30,
        now=_dt.datetime(2026, 4, 21, tzinfo=_dt.UTC),
    )
    assert r["records_in_window"] == 1


def test_max_abs_delta_tracked_across_records() -> None:
    recs = [
        _rec("2026-04-05T00:00:00Z", "5m", "FVG", 0.05),
        _rec("2026-04-12T00:00:00Z", "5m", "FVG", -0.20),
        _rec("2026-04-19T00:00:00Z", "5m", "FVG", 0.10),
    ]
    import datetime as _dt
    r = mod.summarize(
        recs, lookback_days=30,
        now=_dt.datetime(2026, 4, 21, tzinfo=_dt.UTC),
    )
    top = r["top"][0]
    assert top["max_abs_delta_pp"] == 0.20
    assert top["last_delta_pp"] == 0.10


def test_render_markdown_empty_and_populated() -> None:
    md_empty = mod.render_markdown(mod.summarize([]))
    assert "No alerts in the selected window." in md_empty
    import datetime as _dt
    r = mod.summarize(
        [_rec("2026-04-19T00:00:00Z", "5m", "FVG", 0.12)],
        lookback_days=30,
        now=_dt.datetime(2026, 4, 21, tzinfo=_dt.UTC),
    )
    md = mod.render_markdown(r)
    assert "Plan 2.8 alert-history summary" in md
    assert "| 5m | FVG |" in md


def test_cli_json(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    log = tmp_path / "alerts.jsonl"
    _write(log, [_rec("2026-04-19T00:00:00Z", "5m", "FVG", 0.12)])
    rc = mod.main([
        "--log", str(log), "--lookback-days", "30",
        "--now", "2026-04-21T00:00:00Z", "--format", "json",
    ])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["top"][0]["family"] == "FVG"


def test_cli_missing_log(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    rc = mod.main(["--log", str(tmp_path / "no.jsonl")])
    assert rc == 1
    assert "alert log not found" in capsys.readouterr().err


def test_cli_output_file(tmp_path: Path) -> None:
    log = tmp_path / "a.jsonl"
    _write(log, [_rec("2026-04-19T00:00:00Z", "5m", "FVG", 0.12)])
    out = tmp_path / "r.md"
    rc = mod.main([
        "--log", str(log), "--now", "2026-04-21T00:00:00Z",
        "--output", str(out),
    ])
    assert rc == 0
    assert out.exists()
    assert "Plan 2.8 alert-history summary" in out.read_text(encoding="utf-8")
