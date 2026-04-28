"""Tests for ``scripts/plan_2_8_snooze_admin.py``."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "plan_2_8_snooze_admin.py"


def _load():
    spec = importlib.util.spec_from_file_location("plan_2_8_snooze_admin", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plan_2_8_snooze_admin"] = mod
    spec.loader.exec_module(mod)
    return mod


admin = _load()


def test_add_entry_persists(tmp_path: Path) -> None:
    cfg = tmp_path / "snoozes.json"
    rc = admin.main([
        "--config", str(cfg), "add",
        "--tf", "5m", "--family", "OB",
        "--reason", "low sample", "--expires", "2026-05-01T00:00:00Z",
    ])
    assert rc == 0
    data = json.loads(cfg.read_text(encoding="utf-8"))
    assert data["snoozes"] == [
        {"tf": "5m", "family": "OB", "reason": "low sample",
         "expires": "2026-05-01T00:00:00Z"},
    ]


def test_add_tf_only_entry(tmp_path: Path) -> None:
    cfg = tmp_path / "snoozes.json"
    admin.main(["--config", str(cfg), "add", "--tf", "4H"])
    data = json.loads(cfg.read_text(encoding="utf-8"))
    assert data["snoozes"] == [{"tf": "4H"}]


def test_list_empty(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    cfg = tmp_path / "snoozes.json"
    cfg.write_text(json.dumps({"snoozes": []}), encoding="utf-8")
    rc = admin.main(["--config", str(cfg), "list"])
    assert rc == 0
    assert "(no entries)" in capsys.readouterr().out


def test_list_active_filters_expired(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    cfg = tmp_path / "snoozes.json"
    cfg.write_text(json.dumps({"snoozes": [
        {"tf": "5m", "expires": "2025-01-01T00:00:00Z"},
        {"tf": "1H"},
    ]}), encoding="utf-8")
    rc = admin.main([
        "--config", str(cfg), "list", "--active",
        "--now", "2026-04-21T00:00:00Z", "--json",
    ])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert [e["tf"] for e in out] == ["1H"]


def test_expire_drops_expired_entries(tmp_path: Path) -> None:
    cfg = tmp_path / "snoozes.json"
    cfg.write_text(json.dumps({"snoozes": [
        {"tf": "5m", "expires": "2025-01-01T00:00:00Z"},
        {"tf": "15m", "expires": "2099-01-01T00:00:00Z"},
        {"tf": "1H"},
    ]}), encoding="utf-8")
    rc = admin.main([
        "--config", str(cfg), "expire",
        "--now", "2026-04-21T00:00:00Z",
    ])
    assert rc == 0
    data = json.loads(cfg.read_text(encoding="utf-8"))
    assert [e["tf"] for e in data["snoozes"]] == ["15m", "1H"]


def test_rm_matches_tf_plus_family(tmp_path: Path) -> None:
    cfg = tmp_path / "snoozes.json"
    cfg.write_text(json.dumps({"snoozes": [
        {"tf": "5m", "family": "OB"},
        {"tf": "5m", "family": "FVG"},
        {"tf": "1H"},
    ]}), encoding="utf-8")
    rc = admin.main([
        "--config", str(cfg), "rm",
        "--tf", "5m", "--family", "OB",
    ])
    assert rc == 0
    data = json.loads(cfg.read_text(encoding="utf-8"))
    assert data["snoozes"] == [
        {"tf": "5m", "family": "FVG"},
        {"tf": "1H"},
    ]


def test_rm_tf_only_drops_all_families(tmp_path: Path) -> None:
    cfg = tmp_path / "snoozes.json"
    cfg.write_text(json.dumps({"snoozes": [
        {"tf": "5m", "family": "OB"},
        {"tf": "5m", "family": "FVG"},
        {"tf": "1H"},
    ]}), encoding="utf-8")
    admin.main(["--config", str(cfg), "rm", "--tf", "5m"])
    data = json.loads(cfg.read_text(encoding="utf-8"))
    assert data["snoozes"] == [{"tf": "1H"}]


def test_invalid_config_rejected(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    cfg = tmp_path / "snoozes.json"
    cfg.write_text(json.dumps({"snoozes": "nope"}), encoding="utf-8")
    rc = admin.main(["--config", str(cfg), "list"])
    assert rc == 1
    assert "ERROR" in capsys.readouterr().err


def test_add_preserves_existing_entries(tmp_path: Path) -> None:
    cfg = tmp_path / "snoozes.json"
    cfg.write_text(json.dumps({
        "_comment": "hi",
        "snoozes": [{"tf": "1H"}],
    }), encoding="utf-8")
    admin.main(["--config", str(cfg), "add", "--tf", "5m"])
    data = json.loads(cfg.read_text(encoding="utf-8"))
    assert data["_comment"] == "hi"
    assert [e["tf"] for e in data["snoozes"]] == ["1H", "5m"]


def test_expire_with_no_entries_is_noop(tmp_path: Path) -> None:
    cfg = tmp_path / "snoozes.json"
    rc = admin.main([
        "--config", str(cfg), "expire",
        "--now", "2026-04-21T00:00:00Z",
    ])
    assert rc == 0
    data = json.loads(cfg.read_text(encoding="utf-8"))
    assert data["snoozes"] == []
