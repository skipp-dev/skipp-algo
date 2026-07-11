"""Truth-audit #5 follow-up: durable universe-snapshot store publisher/restorer.

Covers the non-git logic (validation, accumulation file collection, no-op /
no-token paths). The git plumbing mirrors publish_signals_snapshot verbatim and
is exercised by its own suite; here we pin the universe-specific behaviour.
"""
from __future__ import annotations

import json
from pathlib import Path

import scripts.publish_universe_snapshots as mod


def _write_snap(store: Path, day: str) -> None:
    store.mkdir(parents=True, exist_ok=True)
    (store / f"{day}.json").write_text(
        json.dumps({"trade_date": day, "symbols": ["AAPL"]}), encoding="utf-8"
    )


def test_snapshot_files_collects_json_sorted(tmp_path: Path) -> None:
    store = tmp_path / "universe"
    _write_snap(store, "2026-07-02")
    _write_snap(store, "2026-07-01")
    (store / "notes.txt").write_text("x", encoding="utf-8")  # ignored
    names = [p.name for p in mod._snapshot_files(store)]
    assert names == ["2026-07-01.json", "2026-07-02.json"]


def test_snapshot_files_missing_dir_is_empty(tmp_path: Path) -> None:
    assert mod._snapshot_files(tmp_path / "nope") == []


def test_publish_no_local_snapshots_is_noop(tmp_path: Path, capsys) -> None:
    rc = mod.publish(tmp_path / "empty", "bot/live-universe-snapshot", "skippALGO/skipp-algo", "tok")
    assert rc == 0
    assert "nothing to publish" in capsys.readouterr().out.lower()


def test_publish_rejects_bad_repo(tmp_path: Path, capsys) -> None:
    _write_snap(tmp_path / "u", "2026-07-01")
    rc = mod.publish(tmp_path / "u", "bot/live-universe-snapshot", "no-slash", "tok")
    assert rc == 1
    assert "owner/name" in capsys.readouterr().err


def test_publish_rejects_bad_branch(tmp_path: Path, capsys) -> None:
    _write_snap(tmp_path / "u", "2026-07-01")
    rc = mod.publish(tmp_path / "u", "-evil", "skippALGO/skipp-algo", "tok")
    assert rc == 1
    assert "invalid branch" in capsys.readouterr().err


def test_restore_rejects_bad_branch(tmp_path: Path, capsys) -> None:
    rc = mod.restore(tmp_path / "u", "..bad", "skippALGO/skipp-algo", "tok")
    assert rc == 1


def test_main_requires_token(monkeypatch, capsys) -> None:
    monkeypatch.delenv("GH_PAT", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    rc = mod.main(["publish"])
    assert rc == 2
    assert "no token" in capsys.readouterr().err.lower()


def test_branch_and_repo_validators() -> None:
    assert mod._is_valid_owner_repo("skippALGO/skipp-algo") is True
    assert mod._is_valid_owner_repo("no-slash") is False
    assert mod._is_valid_branch("bot/live-universe-snapshot") is True
    assert mod._is_valid_branch("-flag") is False
    assert mod._is_valid_branch("a..b") is False
