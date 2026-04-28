"""Tests for ``scripts/plan_2_8_snooze_expiry_report.py`` + #72 wiring."""

from __future__ import annotations

import datetime as _dt
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "plan_2_8_snooze_expiry_report.py"
WEEKLY = REPO / ".github" / "workflows" / "plan-2-8-weekly-digest.yml"


def _load():
    spec = importlib.util.spec_from_file_location("plan_2_8_snooze_expiry_report", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plan_2_8_snooze_expiry_report"] = mod
    spec.loader.exec_module(mod)
    return mod


rep_mod = _load()


TODAY = _dt.date(2026, 4, 22)


def _e(expires: str | None, tf: str = "5m", fam: str = "HR",
       reason: str = "noisy") -> dict[str, Any]:
    out: dict[str, Any] = {"tf": tf, "family": fam, "reason": reason}
    if expires is not None:
        out["expires"] = expires
    return out


def test_categorise_expired() -> None:
    rep = rep_mod.categorise([_e("2026-04-01")], today=TODAY)
    assert rep["counts"]["expired"] == 1
    assert rep["counts"]["active"] == 0


def test_categorise_expiring_within_window() -> None:
    rep = rep_mod.categorise(
        [_e("2026-04-25")], within_days=14, today=TODAY,
    )
    assert rep["counts"]["expiring"] == 1


def test_categorise_active_outside_window() -> None:
    rep = rep_mod.categorise(
        [_e("2026-08-01")], within_days=14, today=TODAY,
    )
    assert rep["counts"]["active"] == 1


def test_categorise_permanent_when_no_expires() -> None:
    rep = rep_mod.categorise([_e(None)], today=TODAY)
    assert rep["counts"]["permanent"] == 1


def test_categorise_malformed_date() -> None:
    rep = rep_mod.categorise([_e("not-a-date")], today=TODAY)
    assert rep["counts"]["malformed"] == 1


def test_categorise_all_buckets() -> None:
    entries = [
        _e("2026-04-01"),    # expired
        _e("2026-04-25"),    # expiring
        _e("2026-08-01"),    # active
        _e(None),            # permanent
        _e("garbage"),       # malformed
    ]
    rep = rep_mod.categorise(entries, within_days=14, today=TODAY)
    assert rep["counts"] == {
        "expired": 1, "expiring": 1, "active": 1,
        "permanent": 1, "malformed": 1, "total": 5,
    }


def test_today_boundary_is_expiring_not_expired() -> None:
    rep = rep_mod.categorise([_e("2026-04-22")], today=TODAY)
    # today == expires  -> expiring (not expired)
    assert rep["counts"]["expired"] == 0
    assert rep["counts"]["expiring"] == 1


def test_render_markdown_with_sections() -> None:
    entries = [
        _e("2026-04-01", tf="5m", fam="HR"),
        _e("2026-04-25", tf="15m", fam="FVG"),
    ]
    md = rep_mod.render_markdown(
        rep_mod.categorise(entries, within_days=14, today=TODAY),
    )
    assert "## Expired (1)" in md
    assert "## Expiring (1)" in md
    assert "2026-04-01" in md
    assert "FVG" in md


def test_render_markdown_empty_buckets() -> None:
    md = rep_mod.render_markdown(
        rep_mod.categorise([], today=TODAY),
    )
    assert "## Expired (0)" in md
    assert "_none_" in md


def _seed(tmp: Path, entries: list[dict[str, Any]]) -> Path:
    cfg = tmp / "s.json"
    cfg.write_text(
        json.dumps({"_comment": "t", "snoozes": entries}),
        encoding="utf-8",
    )
    return cfg


def test_cli_json(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    cfg = _seed(tmp_path, [_e("2026-04-01")])
    rc = rep_mod.main([
        "--config", str(cfg), "--format", "json",
    ])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["counts"]["total"] == 1


def test_cli_md_output(tmp_path: Path) -> None:
    cfg = _seed(tmp_path, [_e("2026-04-01")])
    out = tmp_path / "r.md"
    rc = rep_mod.main([
        "--config", str(cfg), "--output", str(out),
    ])
    assert rc == 0
    assert "Plan 2.8 snooze expiry report" in out.read_text(encoding="utf-8")


def test_cli_fail_on_expired(tmp_path: Path) -> None:
    cfg = _seed(tmp_path, [_e("2026-04-01")])
    rc = rep_mod.main([
        "--config", str(cfg), "--fail-on-expired",
    ])
    assert rc == 1


def test_cli_fail_on_expired_passes_when_clean(tmp_path: Path) -> None:
    cfg = _seed(tmp_path, [_e("2026-08-01")])
    rc = rep_mod.main([
        "--config", str(cfg), "--fail-on-expired",
    ])
    assert rc == 0


def test_cli_missing_config(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    rc = rep_mod.main(["--config", str(tmp_path / "nope.json")])
    assert rc == 1
    assert "config not found" in capsys.readouterr().err


def test_cli_malformed_json_reports_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    cfg = tmp_path / "bad.json"
    cfg.write_text("not-json", encoding="utf-8")
    rc = rep_mod.main(["--config", str(cfg)])
    assert rc == 1
    assert "not valid JSON" in capsys.readouterr().err


def test_cli_handles_top_level_list_shape(tmp_path: Path) -> None:
    # If the config is just a bare list, helper returns 0 with empty buckets.
    cfg = tmp_path / "s.json"
    cfg.write_text(json.dumps([]), encoding="utf-8")
    rc = rep_mod.main(["--config", str(cfg), "--format", "json"])
    assert rc == 0


# ---- weekly wiring pin tests --------------------------------------------

def _wf(path: Path) -> dict[str, Any]:
    import yaml  # type: ignore[import-not-found]
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {
        "on": data.get("on", data.get(True)),
        **{k: v for k, v in data.items() if k not in ("on", True)},
    }


def test_weekly_has_history_csv_step() -> None:
    pytest.importorskip("yaml")
    wf = _wf(WEEKLY)
    steps = wf["jobs"]["weekly-digest"]["steps"]
    names = [s.get("name", "") for s in steps]
    assert "Plan 2.8 history CSV export (last 365 days)" in names
    assert "Upload Plan 2.8 history CSV" in names
    step = next(s for s in steps
                if s.get("name") == "Plan 2.8 history CSV export (last 365 days)")
    assert "plan_2_8_history_export.py" in step["run"]
    assert "--lookback-days 365" in step["run"]


def test_weekly_has_runbook_link_check_step() -> None:
    pytest.importorskip("yaml")
    wf = _wf(WEEKLY)
    steps = wf["jobs"]["weekly-digest"]["steps"]
    names = [s.get("name", "") for s in steps]
    assert "Plan 2.8 runbook link check" in names
    step = next(s for s in steps
                if s.get("name") == "Plan 2.8 runbook link check")
    assert "plan_2_8_runbook_link_check.py" in step["run"]
