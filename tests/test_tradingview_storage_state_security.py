"""TradingView Playwright storage-state security guard tests."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import scripts.check_tradingview_storage_state_security as guard
from scripts.check_tradingview_storage_state_security import (
    find_storage_state_violations,
    git_tracked_files,
    is_sensitive_storage_state_path,
    looks_like_plaintext_playwright_storage_state,
)

_REPO_ROOT = Path(__file__).resolve().parent.parent


def _write_storage_state(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "cookies": [{"name": "sessionid", "value": "secret", "domain": ".tradingview.com"}],
                "origins": [
                    {
                        "origin": "https://www.tradingview.com",
                        "localStorage": [{"name": "tv-user", "value": "secret"}],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )


def test_sensitive_storage_state_path_detection() -> None:
    assert is_sensitive_storage_state_path(Path("automation/tradingview/auth/storage-state.json"))
    assert is_sensitive_storage_state_path(Path("playwright/.auth/storage_state.json"))
    assert not is_sensitive_storage_state_path(Path("automation/tradingview/reports/preflight.json"))
    assert not is_sensitive_storage_state_path(Path("docs/examples/storage-state.json"))


def test_plaintext_playwright_storage_state_shape_detected(tmp_path: Path) -> None:
    candidate = tmp_path / "storage-state.json"
    _write_storage_state(candidate)
    assert looks_like_plaintext_playwright_storage_state(candidate)


def test_sensitive_tracked_storage_state_is_reported(tmp_path: Path) -> None:
    rel = Path("automation/tradingview/auth/storage-state.json")
    _write_storage_state(tmp_path / rel)
    violations = find_storage_state_violations([rel], repo_root=tmp_path)
    assert [(v.path, v.reason) for v in violations] == [
        (rel, "plaintext Playwright storage-state JSON is tracked")
    ]


def test_current_repo_has_no_tracked_storage_state_secret() -> None:
    violations = find_storage_state_violations(git_tracked_files(_REPO_ROOT), repo_root=_REPO_ROOT)
    assert violations == []


def test_gitignore_blocks_local_tradingview_auth_artifacts() -> None:
    gitignore = (_REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "automation/tradingview/auth/storage-state.json" in gitignore
    assert "automation/tradingview/auth/chromium-profile/" in gitignore
    assert "playwright/.auth/" in gitignore


def test_cli_main_passes_without_violations(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys) -> None:
    monkeypatch.setattr(guard, "git_tracked_files", lambda repo_root: [Path("README.md")])
    assert guard.main(["--repo-root", str(tmp_path)]) == 0
    captured = capsys.readouterr()
    assert "security check passed" in captured.out


def test_cli_main_fails_for_tracked_storage_state(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys,
) -> None:
    rel = Path("automation/tradingview/auth/storage-state.json")
    _write_storage_state(tmp_path / rel)
    monkeypatch.setattr(guard, "git_tracked_files", lambda repo_root: [rel])

    assert guard.main(["--repo-root", str(tmp_path)]) == 1
    captured = capsys.readouterr()
    assert "storage-state security check failed" in captured.err
    assert str(rel).replace("\\", "/") in captured.err.replace("\\", "/")
