"""Tests for ``scripts/plan_2_8_digest_smallest_files.py``."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "plan_2_8_digest_smallest_files.py"
WEEKLY = REPO / ".github" / "workflows" / "plan-2-8-weekly-digest.yml"


def _load():
    spec = importlib.util.spec_from_file_location(
        "plan_2_8_digest_smallest_files", SCRIPT,
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plan_2_8_digest_smallest_files"] = mod
    spec.loader.exec_module(mod)
    return mod


sf = _load()


def test_empty_dir(tmp_path: Path) -> None:
    rep = sf.build(tmp_path, 10)
    assert rep["count"] == 0


def test_ascending_order(tmp_path: Path) -> None:
    (tmp_path / "small").write_bytes(b"x")
    (tmp_path / "big").write_bytes(b"xxxxxxxx")
    (tmp_path / "mid").write_bytes(b"xxx")
    rep = sf.build(tmp_path, 10)
    sizes = [e["size"] for e in rep["entries"]]
    assert sizes == sorted(sizes)


def test_bottom_n_truncation(tmp_path: Path) -> None:
    for i, n in enumerate(range(1, 6)):
        (tmp_path / f"f{i}").write_bytes(b"x" * n)
    rep = sf.build(tmp_path, 2)
    assert rep["count"] == 2
    assert rep["entries"][0]["size"] == 1


def test_tie_breaks_by_name(tmp_path: Path) -> None:
    (tmp_path / "b").write_bytes(b"xx")
    (tmp_path / "a").write_bytes(b"xx")
    rep = sf.build(tmp_path, 10)
    assert [e["name"] for e in rep["entries"]] == ["a", "b"]


def test_subdirs_ignored(tmp_path: Path) -> None:
    (tmp_path / "a").write_bytes(b"x")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "b").write_bytes(b"xxx")
    rep = sf.build(tmp_path, 10)
    assert rep["count"] == 1


def test_zero_bottom_n_returns_all(tmp_path: Path) -> None:
    (tmp_path / "a").write_bytes(b"x")
    (tmp_path / "b").write_bytes(b"xx")
    rep = sf.build(tmp_path, 0)
    assert rep["count"] == 2


def test_markdown_shape(tmp_path: Path) -> None:
    (tmp_path / "a").write_bytes(b"x")
    md = sf.render_markdown(sf.build(tmp_path, 10))
    assert "smallest files" in md


def test_markdown_empty_placeholder(tmp_path: Path) -> None:
    md = sf.render_markdown(sf.build(tmp_path, 10))
    assert "_none_" in md


def test_cli_json(tmp_path: Path) -> None:
    (tmp_path / "a").write_bytes(b"x")
    out = tmp_path / "o.json"
    rc = sf.main([
        "--artifact-dir", str(tmp_path), "--bottom-n", "5",
        "--format", "json", "--output", str(out),
    ])
    assert rc == 0
    assert json.loads(out.read_text(encoding="utf-8"))["count"] == 1


def test_cli_missing_dir(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    rc = sf.main(["--artifact-dir", str(tmp_path / "nope")])
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


def test_weekly_has_smallest_files_steps() -> None:
    pytest.importorskip("yaml")
    wf = _wf(WEEKLY)
    steps = wf["jobs"]["weekly-digest"]["steps"]
    names = [s.get("name", "") for s in steps]
    assert "Plan 2.8 digest smallest files" in names
    assert "Upload Plan 2.8 digest smallest files" in names
    step = next(s for s in steps
                if s.get("name") == "Plan 2.8 digest smallest files")
    assert "plan_2_8_digest_smallest_files.py" in step["run"]
