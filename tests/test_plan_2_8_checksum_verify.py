"""Tests for ``scripts/plan_2_8_checksum_verify.py``."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "plan_2_8_checksum_verify.py"


def _load():
    spec = importlib.util.spec_from_file_location("plan_2_8_checksum_verify", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plan_2_8_checksum_verify"] = mod
    spec.loader.exec_module(mod)
    return mod


cv = _load()


def _manifest(entries: list[dict[str, Any]]) -> dict[str, Any]:
    return {"schema_version": 1, "entries": entries}


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def test_verify_all_good(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_bytes(b"hi")
    manifest = _manifest([{"path": "a.txt", "size": 2,
                           "sha256": _sha(b"hi")}])
    rep = cv.verify(manifest, tmp_path)
    assert rep["counts"] == {"expected": 1, "missing": 0,
                             "mismatches": 0, "extra": 0}


def test_verify_detects_mismatch(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_bytes(b"hi")
    manifest = _manifest([{"path": "a.txt", "size": 2,
                           "sha256": "0" * 64}])
    rep = cv.verify(manifest, tmp_path)
    assert rep["counts"]["mismatches"] == 1
    assert rep["mismatches"][0]["path"] == "a.txt"


def test_verify_detects_missing(tmp_path: Path) -> None:
    manifest = _manifest([{"path": "gone.txt", "size": 0,
                           "sha256": _sha(b"")}])
    rep = cv.verify(manifest, tmp_path)
    assert rep["missing"] == ["gone.txt"]


def test_verify_detects_extra(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_bytes(b"hi")
    (tmp_path / "new.txt").write_bytes(b"new")
    manifest = _manifest([{"path": "a.txt", "size": 2,
                           "sha256": _sha(b"hi")}])
    rep = cv.verify(manifest, tmp_path)
    assert rep["extra"] == ["new.txt"]


def test_verify_skip_names_omits_extras(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_bytes(b"hi")
    (tmp_path / "checksums.json").write_bytes(b"{}")
    manifest = _manifest([{"path": "a.txt", "size": 2,
                           "sha256": _sha(b"hi")}])
    rep = cv.verify(manifest, tmp_path, skip_names=("checksums.json",))
    assert rep["extra"] == []


def test_verify_ignores_malformed_entries(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_bytes(b"hi")
    manifest = _manifest([
        {"path": "a.txt", "size": 2, "sha256": _sha(b"hi")},
        "garbage",  # not a dict
        {"path": "b.txt"},  # missing sha256
    ])
    rep = cv.verify(manifest, tmp_path)
    assert rep["counts"]["expected"] == 1


def test_render_markdown_clean(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_bytes(b"hi")
    manifest = _manifest([{"path": "a.txt", "size": 2,
                           "sha256": _sha(b"hi")}])
    md = cv.render_markdown(cv.verify(manifest, tmp_path))
    assert "mismatches: 0" in md
    assert "extra:      0" in md


def test_render_markdown_with_findings(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_bytes(b"hi")
    (tmp_path / "new.txt").write_bytes(b"n")
    manifest = _manifest([
        {"path": "a.txt", "size": 2, "sha256": "0" * 64},
        {"path": "gone.txt", "size": 0, "sha256": _sha(b"")},
    ])
    md = cv.render_markdown(cv.verify(manifest, tmp_path))
    assert "## Mismatches" in md
    assert "## Missing" in md
    assert "## Extra" in md


def test_cli_good_run(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_bytes(b"hi")
    manifest_path = tmp_path / "m.json"
    manifest_path.write_text(json.dumps(_manifest([{
        "path": "a.txt", "size": 2, "sha256": _sha(b"hi"),
    }])), encoding="utf-8")
    out = tmp_path / "v.md"
    rc = cv.main([
        "--manifest", str(manifest_path),
        "--artifact-dir", str(tmp_path),
        "--output", str(out),
        "--skip", "m.json,v.md",
        "--fail-on-mismatch", "--fail-on-missing",
    ])
    assert rc == 0


def test_cli_fail_on_mismatch(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_bytes(b"hi")
    manifest_path = tmp_path / "m.json"
    manifest_path.write_text(json.dumps(_manifest([{
        "path": "a.txt", "size": 2, "sha256": "0" * 64,
    }])), encoding="utf-8")
    rc = cv.main([
        "--manifest", str(manifest_path),
        "--artifact-dir", str(tmp_path),
        "--skip", "m.json",
        "--fail-on-mismatch",
    ])
    assert rc == 1


def test_cli_fail_on_missing(tmp_path: Path) -> None:
    manifest_path = tmp_path / "m.json"
    manifest_path.write_text(json.dumps(_manifest([{
        "path": "gone.txt", "size": 0, "sha256": _sha(b""),
    }])), encoding="utf-8")
    rc = cv.main([
        "--manifest", str(manifest_path),
        "--artifact-dir", str(tmp_path),
        "--skip", "m.json",
        "--fail-on-missing",
    ])
    assert rc == 1


def test_cli_missing_manifest(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    rc = cv.main([
        "--manifest", str(tmp_path / "nope.json"),
        "--artifact-dir", str(tmp_path),
    ])
    assert rc == 1
    assert "manifest not found" in capsys.readouterr().err


def test_cli_bad_manifest_json(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    m = tmp_path / "m.json"
    m.write_text("not-json", encoding="utf-8")
    rc = cv.main([
        "--manifest", str(m), "--artifact-dir", str(tmp_path),
    ])
    assert rc == 1
    assert "manifest JSON invalid" in capsys.readouterr().err


def test_cli_manifest_not_object(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    m = tmp_path / "m.json"
    m.write_text("[1,2,3]", encoding="utf-8")
    rc = cv.main([
        "--manifest", str(m), "--artifact-dir", str(tmp_path),
    ])
    assert rc == 1
    assert "JSON object" in capsys.readouterr().err


def test_cli_missing_artifact_dir(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    m = tmp_path / "m.json"
    m.write_text(json.dumps(_manifest([])), encoding="utf-8")
    rc = cv.main([
        "--manifest", str(m),
        "--artifact-dir", str(tmp_path / "nope"),
    ])
    assert rc == 1
    assert "artifact dir not found" in capsys.readouterr().err
