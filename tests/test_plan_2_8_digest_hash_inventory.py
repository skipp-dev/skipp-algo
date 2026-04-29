"""Tests for ``scripts/plan_2_8_digest_hash_inventory.py``."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "plan_2_8_digest_hash_inventory.py"
WEEKLY = REPO / ".github" / "workflows" / "plan-2-8-weekly-digest.yml"


def _load():
    spec = importlib.util.spec_from_file_location(
        "plan_2_8_digest_hash_inventory", SCRIPT,
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plan_2_8_digest_hash_inventory"] = mod
    spec.loader.exec_module(mod)
    return mod


hi = _load()


def test_empty_dir(tmp_path: Path) -> None:
    rep = hi.build(tmp_path)
    assert rep["count"] == 0
    assert rep["entries"] == []


def test_single_file_hash(tmp_path: Path) -> None:
    p = tmp_path / "a.md"
    p.write_bytes(b"hello")
    rep = hi.build(tmp_path)
    assert rep["count"] == 1
    assert rep["entries"][0]["sha256"] == hashlib.sha256(b"hello").hexdigest()
    assert rep["entries"][0]["size"] == 5


def test_sorted_by_name(tmp_path: Path) -> None:
    (tmp_path / "b").write_bytes(b"x")
    (tmp_path / "a").write_bytes(b"y")
    rep = hi.build(tmp_path)
    assert [e["name"] for e in rep["entries"]] == ["a", "b"]


def test_subdirs_ignored(tmp_path: Path) -> None:
    (tmp_path / "a").write_bytes(b"x")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "b").write_bytes(b"y")
    rep = hi.build(tmp_path)
    assert rep["count"] == 1


def test_stable_across_calls(tmp_path: Path) -> None:
    (tmp_path / "a").write_bytes(b"stable")
    a = hi.build(tmp_path)
    b = hi.build(tmp_path)
    assert a == b


def test_markdown_shape(tmp_path: Path) -> None:
    (tmp_path / "a").write_bytes(b"x")
    md = hi.render_markdown(hi.build(tmp_path))
    assert "hash inventory" in md
    assert "sha256" in md


def test_markdown_empty_placeholder(tmp_path: Path) -> None:
    md = hi.render_markdown(hi.build(tmp_path))
    assert "_none_" in md


def test_cli_json(tmp_path: Path) -> None:
    (tmp_path / "a").write_bytes(b"x")
    out = tmp_path / "o.json"
    rc = hi.main([
        "--artifact-dir", str(tmp_path),
        "--format", "json", "--output", str(out),
    ])
    assert rc == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["count"] == 1


def test_cli_missing_dir(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    rc = hi.main(["--artifact-dir", str(tmp_path / "nope")])
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


def test_weekly_has_hash_inventory_steps() -> None:
    pytest.importorskip("yaml")
    wf = _wf(WEEKLY)
    steps = wf["jobs"]["weekly-digest"]["steps"]
    names = [s.get("name", "") for s in steps]
    assert "Plan 2.8 digest hash inventory" in names
    assert "Upload Plan 2.8 digest hash inventory" in names
    step = next(s for s in steps
                if s.get("name") == "Plan 2.8 digest hash inventory")
    assert "plan_2_8_digest_hash_inventory.py" in step["run"]
