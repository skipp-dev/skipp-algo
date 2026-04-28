"""Tests for ``scripts/plan_2_8_digest_missing_artifacts.py``."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "plan_2_8_digest_missing_artifacts.py"
WEEKLY = REPO / ".github" / "workflows" / "plan-2-8-weekly-digest.yml"


def _load():
    spec = importlib.util.spec_from_file_location(
        "plan_2_8_digest_missing_artifacts", SCRIPT,
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plan_2_8_digest_missing_artifacts"] = mod
    spec.loader.exec_module(mod)
    return mod


ma = _load()


def test_empty_dir_reports_all_missing(tmp_path: Path) -> None:
    rep = ma.scan(tmp_path)
    assert len(rep["missing"]) == len(ma.REQUIRED)
    assert rep["extra"] == []


def test_present_file_not_in_missing(tmp_path: Path) -> None:
    (tmp_path / "status_ledger.jsonl").write_text("x", encoding="utf-8")
    rep = ma.scan(tmp_path)
    assert "status_ledger.jsonl" not in rep["missing"]


def test_extra_file_detected(tmp_path: Path) -> None:
    (tmp_path / "stray.md").write_text("x", encoding="utf-8")
    rep = ma.scan(tmp_path)
    assert "stray.md" in rep["extra"]


def test_required_is_sorted_tuple() -> None:
    assert isinstance(ma.REQUIRED, tuple)
    assert "status_ledger.jsonl" in ma.REQUIRED
    assert "weekly_summary.md" in ma.REQUIRED


def test_subdirectories_not_counted(tmp_path: Path) -> None:
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "status_ledger.jsonl").write_text("x", encoding="utf-8")
    rep = ma.scan(tmp_path)
    assert "status_ledger.jsonl" in rep["missing"]


def test_markdown_shape(tmp_path: Path) -> None:
    md = ma.render_markdown(ma.scan(tmp_path))
    assert "missing artifacts" in md
    assert "required:" in md


def test_markdown_none_placeholder(tmp_path: Path) -> None:
    for name in ma.REQUIRED:
        (tmp_path / name).write_text("x", encoding="utf-8")
    md = ma.render_markdown(ma.scan(tmp_path))
    assert "_(none)_" in md


def test_cli_fail_on_missing(tmp_path: Path) -> None:
    rc = ma.main([
        "--artifact-dir", str(tmp_path), "--fail-on-missing",
    ])
    assert rc == 1


def test_cli_fail_on_missing_clean(tmp_path: Path) -> None:
    for name in ma.REQUIRED:
        (tmp_path / name).write_text("x", encoding="utf-8")
    rc = ma.main([
        "--artifact-dir", str(tmp_path), "--fail-on-missing",
    ])
    assert rc == 0


def test_cli_json(tmp_path: Path) -> None:
    out = tmp_path / "o.json"
    rc = ma.main([
        "--artifact-dir", str(tmp_path),
        "--format", "json", "--output", str(out),
    ])
    assert rc == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["present_count"] == 0


def test_cli_missing_dir(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    rc = ma.main(["--artifact-dir", str(tmp_path / "nope")])
    assert rc == 1
    assert "artifact dir not found" in capsys.readouterr().err


# ---- weekly wiring pin tests --------------------------------------------

def _wf(path: Path) -> dict[str, Any]:
    import yaml  # type: ignore[import-not-found]
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {
        "on": data.get("on", data.get(True)),
        **{k: v for k, v in data.items() if k not in ("on", True)},
    }


def test_weekly_has_missing_artifacts_steps() -> None:
    pytest.importorskip("yaml")
    wf = _wf(WEEKLY)
    steps = wf["jobs"]["weekly-digest"]["steps"]
    names = [s.get("name", "") for s in steps]
    assert "Plan 2.8 digest missing artifacts" in names
    assert "Upload Plan 2.8 digest missing artifacts" in names
    step = next(s for s in steps
                if s.get("name") == "Plan 2.8 digest missing artifacts")
    assert "plan_2_8_digest_missing_artifacts.py" in step["run"]
