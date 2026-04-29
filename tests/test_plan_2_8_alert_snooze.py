"""Tests for ``scripts/plan_2_8_alert_snooze.py``."""

from __future__ import annotations

import datetime as _dt
import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "plan_2_8_alert_snooze.py"


def _load():
    spec = importlib.util.spec_from_file_location("plan_2_8_alert_snooze", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plan_2_8_alert_snooze"] = mod
    spec.loader.exec_module(mod)
    return mod


sn = _load()


def _alert(tf: str, family: str, delta: float = 0.10) -> dict:
    return {"tf": tf, "family": family, "delta_pp": delta,
            "hr_prev": 0.40, "hr_latest": 0.40 + delta}


def _digest(alerts: list[dict]) -> dict:
    return {"status": "ok", "alerts": alerts, "coverage": {}, "thresholds": {}}


NOW = _dt.datetime(2026, 4, 21, tzinfo=_dt.UTC)


def test_snooze_removes_matching_alert_and_records_reason() -> None:
    digest = _digest([_alert("5m", "FVG"), _alert("15m", "FVG")])
    config = {"snoozes": [{"tf": "5m", "family": "FVG",
                           "reason": "known ranging regime"}]}
    out = sn.apply_snooze(digest, config, now=NOW)
    assert [a["tf"] for a in out["alerts"]] == ["15m"]
    assert len(out["snoozed"]) == 1
    assert out["snoozed"][0]["tf"] == "5m"
    assert out["snoozed"][0]["snooze_reason"] == "known ranging regime"


def test_snooze_matches_by_tf_only_when_family_absent() -> None:
    digest = _digest([_alert("5m", "FVG"), _alert("5m", "OB"),
                      _alert("15m", "FVG")])
    config = {"snoozes": [{"tf": "5m"}]}
    out = sn.apply_snooze(digest, config, now=NOW)
    assert [a["tf"] for a in out["alerts"]] == ["15m"]
    assert len(out["snoozed"]) == 2


def test_snooze_expired_entry_is_ignored() -> None:
    digest = _digest([_alert("5m", "FVG")])
    config = {"snoozes": [{"tf": "5m", "family": "FVG",
                           "expires": "2026-04-01T00:00:00Z"}]}
    out = sn.apply_snooze(digest, config, now=NOW)
    assert len(out["alerts"]) == 1
    assert out["snoozed"] == []


def test_snooze_unexpired_entry_is_applied() -> None:
    digest = _digest([_alert("5m", "FVG")])
    config = {"snoozes": [{"tf": "5m", "family": "FVG",
                           "expires": "2026-05-01T00:00:00Z"}]}
    out = sn.apply_snooze(digest, config, now=NOW)
    assert out["alerts"] == []
    assert out["snoozed"][0]["snooze_expires"] == "2026-05-01T00:00:00Z"


def test_snooze_invalid_expires_treated_as_inactive() -> None:
    digest = _digest([_alert("5m", "FVG")])
    config = {"snoozes": [{"tf": "5m", "family": "FVG",
                           "expires": "not-a-date"}]}
    out = sn.apply_snooze(digest, config, now=NOW)
    assert len(out["alerts"]) == 1
    assert out["snoozed"] == []


def test_snooze_without_alerts_is_identity() -> None:
    digest = _digest([])
    out = sn.apply_snooze(digest, {"snoozes": [{"tf": "5m"}]}, now=NOW)
    assert out["alerts"] == []
    assert out["snoozed"] == []


def test_snooze_empty_config_is_noop() -> None:
    digest = _digest([_alert("5m", "FVG")])
    out = sn.apply_snooze(digest, {}, now=NOW)
    assert out["alerts"] == digest["alerts"]
    assert out["snoozed"] == []


def test_snooze_does_not_mutate_input() -> None:
    digest = _digest([_alert("5m", "FVG")])
    original = json.loads(json.dumps(digest))
    sn.apply_snooze(digest, {"snoozes": [{"tf": "5m"}]}, now=NOW)
    assert digest == original
    assert "snoozed" not in digest


def test_cli_writes_output_file(tmp_path: Path) -> None:
    digest_path = tmp_path / "d.json"
    digest_path.write_text(json.dumps(_digest([_alert("5m", "FVG")])),
                           encoding="utf-8")
    snooze_path = tmp_path / "s.json"
    snooze_path.write_text(json.dumps(
        {"snoozes": [{"tf": "5m", "family": "FVG", "reason": "noise"}]}
    ), encoding="utf-8")
    out = tmp_path / "out.json"
    rc = sn.main([
        "--digest",  str(digest_path),
        "--snooze",  str(snooze_path),
        "--output",  str(out),
    ])
    assert rc == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["alerts"] == []
    assert payload["snoozed"][0]["snooze_reason"] == "noise"


def test_cli_missing_file_exits_one(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    rc = sn.main([
        "--digest", str(tmp_path / "no.json"),
        "--snooze", str(tmp_path / "no.json"),
    ])
    assert rc == 1
    assert "ERROR:" in capsys.readouterr().err
