"""Tests for ``scripts/plan_2_8_digest_size_budget.py``."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "plan_2_8_digest_size_budget.py"
WEEKLY = REPO / ".github" / "workflows" / "plan-2-8-weekly-digest.yml"


def _load():
    spec = importlib.util.spec_from_file_location("plan_2_8_digest_size_budget", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plan_2_8_digest_size_budget"] = mod
    spec.loader.exec_module(mod)
    return mod


sb = _load()


def test_scan_empty_dir(tmp_path: Path) -> None:
    rep = sb.scan(tmp_path, max_bytes=1000)
    assert rep["counts"] == {"files": 0, "breaches": 0}


def test_scan_no_breaches(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_bytes(b"x" * 100)
    rep = sb.scan(tmp_path, max_bytes=1000)
    assert rep["counts"]["files"] == 1
    assert rep["counts"]["breaches"] == 0


def test_scan_breach_reported(tmp_path: Path) -> None:
    (tmp_path / "big.bin").write_bytes(b"x" * 2000)
    rep = sb.scan(tmp_path, max_bytes=1000)
    assert rep["counts"]["breaches"] == 1
    assert rep["breaches"][0]["path"] == "big.bin"


def test_scan_at_limit_is_ok(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_bytes(b"x" * 1000)
    rep = sb.scan(tmp_path, max_bytes=1000)
    assert rep["counts"]["breaches"] == 0


def test_scan_recurses(tmp_path: Path) -> None:
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "f.txt").write_bytes(b"x" * 500)
    rep = sb.scan(tmp_path, max_bytes=100)
    assert any(e["path"] == "sub/f.txt" for e in rep["breaches"])


def test_scan_respects_skip_names(tmp_path: Path) -> None:
    (tmp_path / "keep.txt").write_bytes(b"x" * 2000)
    (tmp_path / "skip.txt").write_bytes(b"x" * 5000)
    rep = sb.scan(tmp_path, max_bytes=1000, skip_names=("skip.txt",))
    paths = [e["path"] for e in rep["breaches"]]
    assert paths == ["keep.txt"]


def test_scan_rejects_negative_max() -> None:
    with pytest.raises(ValueError):
        sb.scan(Path("/tmp"), max_bytes=-1)


def test_render_markdown_clean() -> None:
    md = sb.render_markdown({
        "counts":    {"files": 0, "breaches": 0},
        "max_bytes": 1000,
        "breaches":  [],
    })
    assert "All files within budget" in md


def test_render_markdown_with_breaches() -> None:
    md = sb.render_markdown({
        "counts":    {"files": 1, "breaches": 1},
        "max_bytes": 1000,
        "breaches":  [{"path": "big.bin", "size": 5000}],
    })
    assert "| `big.bin` | 5000 |" in md


def test_cli_no_breach_success(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_bytes(b"x" * 10)
    rc = sb.main([
        "--artifact-dir", str(tmp_path),
        "--max-bytes", "1000",
        "--fail-on-breach",
    ])
    assert rc == 0


def test_cli_fail_on_breach(tmp_path: Path) -> None:
    (tmp_path / "big.bin").write_bytes(b"x" * 2000)
    rc = sb.main([
        "--artifact-dir", str(tmp_path),
        "--max-bytes", "1000",
        "--fail-on-breach",
    ])
    assert rc == 1


def test_cli_md_output(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_bytes(b"hi")
    out = tmp_path / "b.md"
    rc = sb.main([
        "--artifact-dir", str(tmp_path),
        "--max-bytes", "1000",
        "--output", str(out),
    ])
    assert rc == 0
    assert "size budget" in out.read_text(encoding="utf-8")


def test_cli_negative_max_rejected(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    rc = sb.main([
        "--artifact-dir", str(tmp_path),
        "--max-bytes", "-1",
    ])
    assert rc == 1
    assert "non-negative" in capsys.readouterr().err


def test_cli_missing_dir(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    rc = sb.main([
        "--artifact-dir", str(tmp_path / "nope"),
    ])
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


def test_weekly_has_size_budget_steps() -> None:
    pytest.importorskip("yaml")
    wf = _wf(WEEKLY)
    steps = wf["jobs"]["weekly-digest"]["steps"]
    names = [s.get("name", "") for s in steps]
    assert "Plan 2.8 digest size budget" in names
    assert "Upload Plan 2.8 digest size budget" in names
    step = next(s for s in steps
                if s.get("name") == "Plan 2.8 digest size budget")
    assert "plan_2_8_digest_size_budget.py" in step["run"]
    assert "1048576" in step["run"]
