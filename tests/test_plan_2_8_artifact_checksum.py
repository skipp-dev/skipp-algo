"""Tests for ``scripts/plan_2_8_artifact_checksum.py``."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "plan_2_8_artifact_checksum.py"
WEEKLY = REPO / ".github" / "workflows" / "plan-2-8-weekly-digest.yml"


def _load():
    spec = importlib.util.spec_from_file_location("plan_2_8_artifact_checksum", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plan_2_8_artifact_checksum"] = mod
    spec.loader.exec_module(mod)
    return mod


cs = _load()


def test_compute_empty_dir(tmp_path: Path) -> None:
    rep = cs.compute(tmp_path)
    assert rep["counts"] == {"files": 0, "total_size": 0}
    assert rep["entries"] == []


def test_compute_hashes_files(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_bytes(b"hello")
    expected = hashlib.sha256(b"hello").hexdigest()
    rep = cs.compute(tmp_path)
    assert rep["counts"]["files"] == 1
    assert rep["entries"][0]["sha256"] == expected
    assert rep["entries"][0]["size"] == 5


def test_compute_sorts_entries(tmp_path: Path) -> None:
    (tmp_path / "b.txt").write_bytes(b"x")
    (tmp_path / "a.txt").write_bytes(b"y")
    rep = cs.compute(tmp_path)
    assert [e["path"] for e in rep["entries"]] == ["a.txt", "b.txt"]


def test_compute_recurses(tmp_path: Path) -> None:
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "c.txt").write_bytes(b"z")
    rep = cs.compute(tmp_path)
    assert any(e["path"] == "sub/c.txt" for e in rep["entries"])


def test_compute_respects_skip_names(tmp_path: Path) -> None:
    (tmp_path / "keep.txt").write_bytes(b"1")
    (tmp_path / "drop.txt").write_bytes(b"2")
    rep = cs.compute(tmp_path, skip_names=("drop.txt",))
    paths = [e["path"] for e in rep["entries"]]
    assert paths == ["keep.txt"]


def test_render_markdown_empty() -> None:
    md = cs.render_markdown(cs.compute(Path("/nonexistent/xyzzy")))
    assert "No artifacts present" in md


def test_render_markdown_with_files(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_bytes(b"hi")
    md = cs.render_markdown(cs.compute(tmp_path))
    assert "| `a.txt` | 2 |" in md


def test_cli_writes_both_outputs(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_bytes(b"hi")
    j = tmp_path / "c.json"
    m = tmp_path / "c.md"
    rc = cs.main([
        "--artifact-dir", str(tmp_path),
        "--json-output", str(j), "--md-output", str(m),
        "--skip", "c.json,c.md",
    ])
    assert rc == 0
    payload = json.loads(j.read_text(encoding="utf-8"))
    assert payload["counts"]["files"] == 1
    assert "a.txt" in m.read_text(encoding="utf-8")


def test_cli_stdout_when_no_outputs(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    (tmp_path / "a.txt").write_bytes(b"hi")
    rc = cs.main(["--artifact-dir", str(tmp_path)])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["counts"]["files"] == 1


def test_cli_missing_dir(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    rc = cs.main(["--artifact-dir", str(tmp_path / "nope")])
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


def test_weekly_has_checksum_steps() -> None:
    pytest.importorskip("yaml")
    wf = _wf(WEEKLY)
    steps = wf["jobs"]["weekly-digest"]["steps"]
    names = [s.get("name", "") for s in steps]
    assert "Plan 2.8 artifact checksums" in names
    assert "Upload Plan 2.8 artifact checksums" in names
    step = next(s for s in steps
                if s.get("name") == "Plan 2.8 artifact checksums")
    assert "plan_2_8_artifact_checksum.py" in step["run"]
    assert "checksums.json,checksums.md" in step["run"]
