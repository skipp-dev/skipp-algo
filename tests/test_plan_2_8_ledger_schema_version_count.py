"""Tests for ``plan_2_8_ledger_schema_version_count.py``."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "plan_2_8_ledger_schema_version_count.py"
WEEKLY = REPO / ".github" / "workflows" / "plan-2-8-weekly-digest.yml"


def _load():
    spec = importlib.util.spec_from_file_location(
        "plan_2_8_ledger_schema_version_count", SCRIPT,
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plan_2_8_ledger_schema_version_count"] = mod
    spec.loader.exec_module(mod)
    return mod


sv = _load()


def test_empty() -> None:
    assert sv.compute([])["schema_version_count"] == 0


def test_versions() -> None:
    rs = [
        {"status": "green", "schema_version": 1},
        {"status": "amber", "schema_version": 1},
        {"status": "red", "schema_version": 2},
    ]
    assert sv.compute(rs)["schema_version_count"] == 2


def test_missing_version() -> None:
    rs = [{"status": "green"}, {"status": "amber", "schema_version": 1}]
    assert sv.compute(rs)["schema_version_count"] == 1


def test_markdown_shape() -> None:
    body = sv.render_markdown(sv.compute([]))
    assert "schema_version_count" in body


def test_cli_json(tmp_path: Path) -> None:
    p = tmp_path / "l.jsonl"
    p.write_text(
        json.dumps({"status": "green", "schema_version": 1}) + "\n",
        encoding="utf-8",
    )
    out = tmp_path / "o.json"
    code = sv.main([
        "--ledger", str(p), "--format", "json", "--output", str(out),
    ])
    assert code == 0
    assert json.loads(
        out.read_text(encoding="utf-8"))["schema_version_count"] == 1


def test_cli_missing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    code = sv.main(["--ledger", str(tmp_path / "nope.jsonl")])
    assert code == 1
    assert "ledger not found" in capsys.readouterr().err


def _wf(path: Path) -> dict[str, Any]:
    import yaml  # type: ignore[import-not-found]
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {
        "on": data.get("on", data.get(True)),
        **{k: v for k, v in data.items() if k not in ("on", True)},
    }


def test_weekly_has_sv_steps() -> None:
    pytest.importorskip("yaml")
    data = _wf(WEEKLY)
    steps = data["jobs"]["weekly-digest"]["steps"]
    names = [s.get("name", "") for s in steps]
    assert "Plan 2.8 ledger schema version count" in names
    assert "Upload Plan 2.8 ledger schema version count" in names
    step = next(
        s for s in steps
        if s.get("name") == "Plan 2.8 ledger schema version count"
    )
    assert "plan_2_8_ledger_schema_version_count.py" in step["run"]
