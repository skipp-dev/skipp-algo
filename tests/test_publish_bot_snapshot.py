from __future__ import annotations

import subprocess
from pathlib import Path, PurePosixPath

from scripts import publish_bot_snapshot as publisher


def _result(args: list[str], *, rc: int = 0, stdout: str = "", stderr: str = ""):
    return subprocess.CompletedProcess(["git", *args], rc, stdout, stderr)


def test_parse_copy_rejects_destination_escape() -> None:
    try:
        publisher._parse_copy("source=../outside", required=True)
    except Exception as exc:
        assert "safe repository-relative" in str(exc)
    else:  # pragma: no cover - assertion branch
        raise AssertionError("destination escape was accepted")


def test_publisher_rejects_non_bot_branch(tmp_path) -> None:
    source = tmp_path / "snapshot.json"
    source.write_text("{}\n", encoding="utf-8")
    rc = publisher.publish(
        repo="owner/repo",
        branch="main",
        token="secret-token",
        copies=[publisher.CopySpec(source, PurePosixPath("artifacts/state.json"))],
    )
    assert rc == 2


def test_transient_branch_fetch_failure_aborts_without_push(monkeypatch, tmp_path) -> None:
    source = tmp_path / "snapshot.json"
    source.write_text("{}\n", encoding="utf-8")
    calls: list[list[str]] = []

    def fake_git(args: list[str], cwd: Path, *, check: bool = True):
        calls.append(args)
        if args[:4] == ["fetch", "--quiet", "--depth", "1"]:
            return _result(args, rc=128, stderr="fatal: unable to access remote")
        return _result(args)

    monkeypatch.setattr(publisher, "_git", fake_git)
    rc = publisher.publish(
        repo="owner/repo",
        branch="bot/state",
        token="secret-token",
        copies=[publisher.CopySpec(source, PurePosixPath("artifacts/state.json"))],
    )

    assert rc == 1
    assert not any(call and call[0] == "push" for call in calls)


def test_missing_branch_bootstraps_with_zero_sha_lease(monkeypatch, tmp_path) -> None:
    source = tmp_path / "snapshot.json"
    source.write_text("{}\n", encoding="utf-8")
    calls: list[list[str]] = []
    fetch_count = 0

    def fake_git(args: list[str], cwd: Path, *, check: bool = True):
        nonlocal fetch_count
        calls.append(args)
        if args[:4] == ["fetch", "--quiet", "--depth", "1"]:
            fetch_count += 1
            if fetch_count == 1:
                return _result(args, rc=128, stderr="fatal: couldn't find remote ref bot/state")
        if args[:3] == ["diff", "--cached", "--quiet"]:
            return _result(args, rc=1)
        return _result(args)

    monkeypatch.setattr(publisher, "_git", fake_git)
    rc = publisher.publish(
        repo="owner/repo",
        branch="bot/state",
        token="secret-token",
        copies=[publisher.CopySpec(source, PurePosixPath("artifacts/state.json"))],
    )

    assert rc == 0
    push = next(call for call in calls if call and call[0] == "push")
    assert f"--force-with-lease=refs/heads/bot/state:{publisher.ZERO_SHA}" in push


def test_existing_branch_uses_fetched_tip_as_explicit_lease(monkeypatch, tmp_path) -> None:
    source = tmp_path / "snapshot.json"
    source.write_text("{}\n", encoding="utf-8")
    calls: list[list[str]] = []
    remote_sha = "a" * 40

    rev_parse_count = 0

    def fake_git(args: list[str], cwd: Path, *, check: bool = True):
        nonlocal rev_parse_count
        calls.append(args)
        if args == ["rev-parse", "FETCH_HEAD"]:
            rev_parse_count += 1
            sha = remote_sha if rev_parse_count == 1 else "b" * 40
            return _result(args, stdout=f"{sha}\n")
        if args[:3] == ["diff", "--cached", "--quiet"]:
            return _result(args, rc=1)
        return _result(args)

    monkeypatch.setattr(publisher, "_git", fake_git)
    rc = publisher.publish(
        repo="owner/repo",
        branch="bot/state",
        token="secret-token",
        copies=[publisher.CopySpec(source, PurePosixPath("artifacts/state.json"))],
    )

    assert rc == 0
    assert ["reset", "--soft", "b" * 40] in calls
    push = next(call for call in calls if call and call[0] == "push")
    assert f"--force-with-lease=refs/heads/bot/state:{remote_sha}" in push
