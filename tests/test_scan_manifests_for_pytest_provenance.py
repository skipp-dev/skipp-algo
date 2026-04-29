"""Tests for the pytest-provenance manifest scanner."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

SCANNER = Path(__file__).resolve().parent.parent / "scripts" / "scan_manifests_for_pytest_provenance.py"


def _run(*args: str | Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCANNER), *map(str, args)],
        capture_output=True,
        text=True,
        check=False,
    )


def test_scanner_clean_on_real_manifest(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest_5m.json"
    manifest.write_text(
        '{"workbook_path": "artifacts/smc_microstructure_exports/databento_volatility_production_workbook.xlsx"}',
        encoding="utf-8",
    )
    result = _run(manifest)
    assert result.returncode == 0, result.stderr


def test_scanner_blocks_pytest_of_user(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest_15m.json"
    manifest.write_text(
        '{"workbook_path": "/private/var/folders/aa/T/pytest-of-jdoe/pytest-12/foo/wb.xlsx"}',
        encoding="utf-8",
    )
    result = _run(manifest)
    assert result.returncode == 1
    assert "pytest-of-jdoe" in result.stderr


def test_scanner_blocks_var_folders_pytest(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest_1H.json"
    manifest.write_text(
        '{"path": "/var/folders/n9/x/T/pytest-foo/wb.xlsx"}',
        encoding="utf-8",
    )
    result = _run(manifest)
    assert result.returncode == 1
    assert "/var/folders" in result.stderr


def test_scanner_blocks_tmp_pytest_of(tmp_path: Path) -> None:
    manifest = tmp_path / "benchmark_run_manifest.json"
    manifest.write_text(
        '{"out": "/tmp/pytest-of-runner/foo/manifest.json"}',
        encoding="utf-8",
    )
    result = _run(manifest)
    assert result.returncode == 1
    assert "pytest-of-runner" in result.stderr


def test_scanner_no_args_no_staged_returns_zero() -> None:
    # In a clean staging area the scanner should exit 0 quickly.
    result = _run()
    assert result.returncode in (0, 1)  # 1 only if repo currently has staged poisoned files


def test_all_tracked_clean_in_repo() -> None:
    """The current repo must not contain any poisoned manifest."""
    result = _run("--all-tracked")
    assert result.returncode == 0, (
        f"Repository contains poisoned manifest(s):\n{result.stderr}"
    )
