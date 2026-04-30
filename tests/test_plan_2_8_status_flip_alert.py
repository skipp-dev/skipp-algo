"""Tests for ``scripts/plan_2_8_status_flip_alert.py``."""

from __future__ import annotations

import datetime as _dt
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "plan_2_8_status_flip_alert.py"
WEEKLY = REPO / ".github" / "workflows" / "plan-2-8-weekly-digest.yml"


def _load():
    spec = importlib.util.spec_from_file_location("plan_2_8_status_flip_alert", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plan_2_8_status_flip_alert"] = mod
    spec.loader.exec_module(mod)
    return mod


fa = _load()


NOW = _dt.datetime(2026, 4, 21, 12, 0, tzinfo=_dt.UTC)


def _rec(days_ago: int, status: str, **extra: Any) -> dict[str, Any]:
    ts = (NOW - _dt.timedelta(days=days_ago)).strftime(
        "%Y-%m-%dT%H:%M:%S%z",
    )
    out = {"captured_at": ts, "status": status}
    out.update(extra)
    return out


def test_no_flips_all_identical() -> None:
    records = [_rec(14, "green"), _rec(7, "green"), _rec(0, "green")]
    flips = fa.detect_flips(records, weeks=12, now=NOW)
    assert flips == []


def test_detects_simple_flip() -> None:
    records = [_rec(14, "green"), _rec(7, "amber"), _rec(0, "green")]
    flips = fa.detect_flips(records, weeks=12, now=NOW)
    assert len(flips) == 2
    assert flips[0]["from"] == "green" and flips[0]["to"] == "amber"
    assert flips[1]["from"] == "amber" and flips[1]["to"] == "green"


def test_respects_window_cutoff() -> None:
    records = [
        _rec(200, "green"),
        _rec(100, "amber"),
        _rec(14, "green"),
        _rec(7, "amber"),
    ]
    flips = fa.detect_flips(records, weeks=4, now=NOW)
    assert len(flips) == 1
    assert flips[0]["from"] == "green" and flips[0]["to"] == "amber"


def test_weeks_zero_uses_all_records() -> None:
    records = [_rec(500, "green"), _rec(200, "amber")]
    flips = fa.detect_flips(records, weeks=0, now=NOW)
    assert len(flips) == 1


def test_rejects_invalid_status() -> None:
    records = [_rec(1, "bogus"), _rec(0, "amber")]
    flips = fa.detect_flips(records, weeks=12, now=NOW)
    assert flips == []  # first record dropped, nothing to compare


def test_handles_malformed_timestamp_in_window_mode() -> None:
    records = [
        {"captured_at": "not-a-date", "status": "green"},
        _rec(1, "amber"),
    ]
    flips = fa.detect_flips(records, weeks=4, now=NOW)
    assert flips == []


def test_negative_weeks_rejected() -> None:
    with pytest.raises(ValueError):
        fa.detect_flips([], weeks=-1, now=NOW)


def test_case_normalised_status() -> None:
    records = [_rec(7, "GREEN"), _rec(0, "Amber")]
    flips = fa.detect_flips(records, weeks=12, now=NOW)
    assert len(flips) == 1


def test_carries_to_run_url() -> None:
    records = [_rec(7, "green"), _rec(0, "amber", run_url="https://x")]
    flips = fa.detect_flips(records, weeks=12, now=NOW)
    assert flips[0]["to_run_url"] == "https://x"


def test_render_markdown_empty() -> None:
    md = fa.render_markdown([], weeks=12)
    assert "No status flips detected" in md
    assert "last 12 wk" in md


def test_render_markdown_with_flips() -> None:
    flips = [{
        "from": "green", "to": "amber",
        "from_at": "t1", "to_at": "t2",
        "to_run_url": "https://x",
    }]
    md = fa.render_markdown(flips, weeks=4)
    assert "| green | amber | t2 | [run](https://x) |" in md


def _seed(tmp: Path, records: list[dict[str, Any]]) -> Path:
    p = tmp / "l.jsonl"
    p.write_text("\n".join(json.dumps(r) for r in records) + "\n",
                 encoding="utf-8")
    return p


def test_cli_md_output(tmp_path: Path) -> None:
    p = _seed(tmp_path, [_rec(7, "green"), _rec(0, "amber")])
    out = tmp_path / "f.md"
    rc = fa.main([
        "--ledger", str(p), "--output", str(out), "--weeks", "0",
    ])
    assert rc == 0
    assert "green | amber" in out.read_text(encoding="utf-8")


def test_cli_fail_on_flip(tmp_path: Path) -> None:
    p = _seed(tmp_path, [_rec(7, "green"), _rec(0, "amber")])
    rc = fa.main([
        "--ledger", str(p), "--weeks", "0", "--fail-on-flip",
    ])
    assert rc == 1


def test_cli_no_flip_success(tmp_path: Path) -> None:
    p = _seed(tmp_path, [_rec(7, "green"), _rec(0, "green")])
    rc = fa.main([
        "--ledger", str(p), "--weeks", "0", "--fail-on-flip",
    ])
    assert rc == 0


def test_cli_missing_ledger(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    rc = fa.main([
        "--ledger", str(tmp_path / "nope.jsonl"), "--weeks", "4",
    ])
    assert rc == 1
    assert "ledger not found" in capsys.readouterr().err


# ---- weekly wiring pin tests --------------------------------------------

def _wf(path: Path) -> dict[str, Any]:
    import yaml  # type: ignore[import-not-found]
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {
        "on": data.get("on", data.get(True)),
        **{k: v for k, v in data.items() if k not in ("on", True)},
    }


def test_weekly_has_flip_alert_steps() -> None:
    pytest.importorskip("yaml")
    wf = _wf(WEEKLY)
    steps = wf["jobs"]["weekly-digest"]["steps"]
    names = [s.get("name", "") for s in steps]
    assert "Plan 2.8 status ledger flip alert" in names
    assert "Upload Plan 2.8 status flip alert" in names
    step = next(s for s in steps
                if s.get("name") == "Plan 2.8 status ledger flip alert")
    assert "plan_2_8_status_flip_alert.py" in step["run"]
    assert "--weeks  12" in step["run"]
