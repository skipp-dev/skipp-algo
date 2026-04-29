"""Tests for ``scripts/plan_2_8_digest_artifact_catalog.py``."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "plan_2_8_digest_artifact_catalog.py"
WEEKLY = REPO / ".github" / "workflows" / "plan-2-8-weekly-digest.yml"


def _load():
    spec = importlib.util.spec_from_file_location(
        "plan_2_8_digest_artifact_catalog", SCRIPT,
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plan_2_8_digest_artifact_catalog"] = mod
    spec.loader.exec_module(mod)
    return mod


ac = _load()


def _populate(dir_: Path, files: list[str]) -> None:
    dir_.mkdir(parents=True, exist_ok=True)
    for name in files:
        (dir_ / name).write_text("x", encoding="utf-8")


def test_known_files_recognised(tmp_path: Path) -> None:
    _populate(tmp_path, ["trend.md", "downtime.md", "checksums.json"])
    rep = ac.scan(tmp_path)
    assert rep["counts"]["known"] == 3
    assert rep["counts"]["unknown"] == 0
    for e in rep["known"]:
        assert e["description"]


def test_unknown_files_flagged(tmp_path: Path) -> None:
    _populate(tmp_path, ["trend.md", "mystery.bin"])
    rep = ac.scan(tmp_path)
    assert rep["counts"]["known"] == 1
    assert rep["counts"]["unknown"] == 1
    assert rep["unknown"][0]["name"] == "mystery.bin"


def test_missing_dir(tmp_path: Path) -> None:
    rep = ac.scan(tmp_path / "nope")
    assert rep["counts"]["total"] == 0


def test_subdirectories_ignored(tmp_path: Path) -> None:
    _populate(tmp_path, ["trend.md"])
    (tmp_path / "nested").mkdir()
    (tmp_path / "nested" / "x.md").write_text("x", encoding="utf-8")
    rep = ac.scan(tmp_path)
    assert rep["counts"]["total"] == 1


def test_markdown_has_known_table(tmp_path: Path) -> None:
    _populate(tmp_path, ["trend.md"])
    out = ac.render_markdown(ac.scan(tmp_path))
    assert "| file | size | description |" in out
    assert "`trend.md`" in out


def test_markdown_shows_unknown_section(tmp_path: Path) -> None:
    _populate(tmp_path, ["mystery.bin"])
    out = ac.render_markdown(ac.scan(tmp_path))
    assert "## Unknown" in out
    assert "`mystery.bin`" in out


def test_cli_fail_on_unknown(tmp_path: Path) -> None:
    _populate(tmp_path, ["mystery.bin"])
    rc = ac.main([
        "--artifact-dir", str(tmp_path),
        "--fail-on-unknown",
    ])
    assert rc == 1


def test_cli_fail_on_unknown_clean(tmp_path: Path) -> None:
    _populate(tmp_path, ["trend.md"])
    rc = ac.main([
        "--artifact-dir", str(tmp_path),
        "--fail-on-unknown",
    ])
    assert rc == 0


def test_cli_json(tmp_path: Path) -> None:
    _populate(tmp_path, ["trend.md"])
    out = tmp_path / "cat.json"
    rc = ac.main([
        "--artifact-dir", str(tmp_path),
        "--format", "json",
        "--output", str(out),
    ])
    assert rc == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["counts"]["known"] == 1


def test_cli_missing_dir(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    rc = ac.main(["--artifact-dir", str(tmp_path / "nope")])
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


def test_weekly_has_catalog_steps() -> None:
    pytest.importorskip("yaml")
    wf = _wf(WEEKLY)
    steps = wf["jobs"]["weekly-digest"]["steps"]
    names = [s.get("name", "") for s in steps]
    assert "Plan 2.8 digest artifact catalog" in names
    assert "Upload Plan 2.8 digest artifact catalog" in names
    step = next(s for s in steps
                if s.get("name") == "Plan 2.8 digest artifact catalog")
    assert "plan_2_8_digest_artifact_catalog.py" in step["run"]
