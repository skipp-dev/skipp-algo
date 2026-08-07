"""Publish / restore the point-in-time universe snapshot store to a rolling bot branch.

Truth-audit #5 follow-up (2026-07-11): the survivorship-bias guard in
``databento_universe`` persists one ``artifacts/universe/<trade_date>.json``
per day and replays it for historical runs — but ``artifacts/universe/`` is
ephemeral in CI, so nothing ever survives to replay. This makes the store
durable using the same rolling ``bot/*`` snapshot-branch pattern approved by
ADR-0024 (as ``smc-live-news-refresh`` / ``publish_signals_snapshot``):

* ``publish`` seeds a work tree from the existing ``bot/live-universe-snapshot``
  branch (which holds ALL prior per-day snapshots), copies the local
  ``artifacts/universe/*.json`` on top (ACCUMULATING — same-date files are
  refreshed, new dates added), and ``--force-with-lease`` pushes the union
  back. The daily production export calls this after it persists today's
  snapshot.
* ``restore`` fetches that branch into the local ``artifacts/universe/`` so a
  historical backfill run can replay each day's point-in-time membership. The
  production export calls this before it resolves the universe.

Why a ``bot/*`` branch + ``--force-with-lease`` (per ADR-0024): the store must
persist across otherwise-ephemeral CI runs, its history is irrelevant (we only
need the file set), and the branch lives in the ``bot/*`` namespace that the
never-force-push-``main`` policy explicitly carves out. Unlike the single-file
signals cursor this store ACCUMULATES; seeding from the branch tip before each
publish keeps prior snapshots.

The git plumbing (argv-only, no shell; owner/repo + branch validation; token
redaction) mirrors ``publish_signals_snapshot`` verbatim.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

DEFAULT_BRANCH = "bot/live-universe-snapshot"
DEFAULT_REPO = "skipp-dev/skipp-algo"
# Directory the per-day snapshots live in, identical inside the bot branch and
# on-host so the layout mirrors 1:1.
STORE_DIR = "artifacts/universe"

BOT_NAME = "github-actions[bot]"
BOT_EMAIL = "41898282+github-actions[bot]@users.noreply.github.com"
_ZERO_SHA = "0" * 40


def _git(
    args: list[str], cwd: Path, *, check: bool = True
) -> subprocess.CompletedProcess[str]:
    """Run a single git subcommand with explicit argv (no shell).

    ``git`` is resolved via :func:`shutil.which` and every argument is a plain
    argv item, so caller-provided branch/repo names are passed verbatim and
    create no shell-injection risk.
    """
    git_exe = shutil.which("git") or "git"
    return subprocess.run(  # noqa: S603 -- hardcoded git argv resolved via shutil.which (no shell, no user input)
        [git_exe, *args], cwd=cwd, check=check, capture_output=True, text=True
    )


def _redact_token(text: str, token: str) -> str:
    if not text or not token:
        return text
    return text.replace(token, "***")


def _is_valid_owner_repo(repo: str) -> bool:
    """Return True iff ``repo`` is a valid ``owner/name`` GitHub identifier."""
    owner, sep, name = repo.partition("/")
    if sep != "/" or not owner or not name:
        return False
    if len(owner) > 39 or len(name) > 100:
        return False
    if not owner[0].isascii() or not owner[0].isalnum():
        return False
    if owner.endswith("-") or "--" in owner:
        return False
    if not all(ch.isascii() and (ch.isalnum() or ch == "-") for ch in owner):
        return False
    return all(ch.isascii() and (ch.isalnum() or ch in "._-") for ch in name)


def _is_valid_branch(name: str) -> bool:
    """Return True iff ``name`` is a safe git branch name."""
    if not name or name.startswith("-"):
        return False
    if ".." in name or name.endswith(".") or name.endswith("/"):
        return False
    if name.startswith("/"):
        return False
    if any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in name):
        return False
    if "@{" in name or name == "@":
        return False
    for component in name.split("/"):
        if not component or component.startswith("."):
            return False
    return not any(ch in name for ch in "~^:\\ \t")


def _git_diff_has_changes(cwd: Path) -> bool:
    """Return True when there are staged changes to commit."""
    result = _git(["diff", "--cached", "--quiet"], cwd, check=False)
    if result.returncode > 1:
        raise RuntimeError(
            f"git diff --cached failed (rc={result.returncode}): {result.stderr.strip()}"
        )
    return result.returncode == 1


def _snapshot_files(store: Path) -> list[Path]:
    """Return the per-day snapshot JSON files under ``store`` (sorted)."""
    if not store.is_dir():
        return []
    return sorted(p for p in store.glob("*.json") if p.is_file())


def _seed_work_tree(work: Path, branch: str, remote: str, token: str) -> bool:
    """Init a work tree seeded from the branch tip. Returns has_remote_tip."""
    _git(["init", "--quiet"], work)
    _git(["config", "user.name", BOT_NAME], work)
    _git(["config", "user.email", BOT_EMAIL], work)
    _git(["remote", "add", "origin", remote], work)
    fetched = _git(
        ["fetch", "--quiet", "--depth", "1", "origin", branch], work, check=False
    )
    has_remote_tip = fetched.returncode == 0
    if has_remote_tip:
        _git(["checkout", "--quiet", "-B", branch, "FETCH_HEAD"], work)
    else:
        stderr = (fetched.stderr or "").strip()
        if stderr and "find remote ref" not in stderr.lower():
            print(
                f"warning: initial fetch failed; seeding empty branch: "
                f"{_redact_token(stderr, token)}",
                file=sys.stderr,
            )
        _git(["checkout", "--quiet", "-B", branch], work)
    return has_remote_tip


def publish(store: Path, branch: str, repo: str, token: str) -> int:
    """Publish every snapshot under ``store`` to ``branch`` (accumulating)."""
    if not _is_valid_owner_repo(repo):
        print(f"error: repo must be owner/name, got {repo!r}", file=sys.stderr)
        return 1
    if not _is_valid_branch(branch):
        print(f"error: invalid branch name: {branch!r}", file=sys.stderr)
        return 1
    local_files = _snapshot_files(store)
    if not local_files:
        print(f"No universe snapshots under {store}; nothing to publish.")
        return 0

    remote = f"https://x-access-token:{token}@github.com/{repo}.git"
    work = Path(tempfile.mkdtemp(prefix="universe-snapshot-"))
    try:
        has_remote_tip = _seed_work_tree(work, branch, remote, token)
        dest_dir = work / STORE_DIR
        dest_dir.mkdir(parents=True, exist_ok=True)
        # ACCUMULATE: copy local snapshots on top of the seeded branch files.
        for src in local_files:
            (dest_dir / src.name).write_bytes(src.read_bytes())

        _git(["add", "-f", STORE_DIR], work)
        if not _git_diff_has_changes(work):
            print("No universe-snapshot changes to publish.")
            return 0
        _git(
            ["commit", "--quiet", "-m", "[skip ci] chore: refresh universe snapshot store"],
            work,
        )
        lease = (
            f"--force-with-lease=refs/heads/{branch}"
            if has_remote_tip
            else f"--force-with-lease=refs/heads/{branch}:{_ZERO_SHA}"
        )
        _git(["push", lease, "origin", f"HEAD:refs/heads/{branch}"], work)
        print(f"Published {len(local_files)} universe snapshot(s) to {branch}.")
        return 0
    except subprocess.CalledProcessError as exc:
        print(
            f"error: git failed (rc={exc.returncode}): "
            f"{_redact_token((exc.stderr or '').strip(), token)}",
            file=sys.stderr,
        )
        return 1
    finally:
        shutil.rmtree(work, ignore_errors=True)


def restore(store: Path, branch: str, repo: str, token: str) -> int:
    """Fetch ``branch`` and copy its snapshots into local ``store``."""
    if not _is_valid_owner_repo(repo):
        print(f"error: repo must be owner/name, got {repo!r}", file=sys.stderr)
        return 1
    if not _is_valid_branch(branch):
        print(f"error: invalid branch name: {branch!r}", file=sys.stderr)
        return 1

    remote = f"https://x-access-token:{token}@github.com/{repo}.git"
    work = Path(tempfile.mkdtemp(prefix="universe-restore-"))
    try:
        _git(["init", "--quiet"], work)
        _git(["remote", "add", "origin", remote], work)
        fetched = _git(
            ["fetch", "--quiet", "--depth", "1", "origin", branch], work, check=False
        )
        if fetched.returncode != 0:
            stderr = (fetched.stderr or "").strip()
            if "find remote ref" in stderr.lower():
                print(f"No {branch} yet; starting with an empty universe store.")
                return 0
            print(
                f"error: fetch failed: {_redact_token(stderr, token)}",
                file=sys.stderr,
            )
            return 1
        _git(["checkout", "--quiet", "FETCH_HEAD"], work)
        src_dir = work / STORE_DIR
        restored = 0
        store.mkdir(parents=True, exist_ok=True)
        for src in _snapshot_files(src_dir):
            (store / src.name).write_bytes(src.read_bytes())
            restored += 1
        print(f"Restored {restored} universe snapshot(s) from {branch} into {store}.")
        return 0
    except subprocess.CalledProcessError as exc:
        print(
            f"error: git failed (rc={exc.returncode}): "
            f"{_redact_token((exc.stderr or '').strip(), token)}",
            file=sys.stderr,
        )
        return 1
    finally:
        shutil.rmtree(work, ignore_errors=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("publish", "restore"))
    parser.add_argument("--store", default=STORE_DIR, help="Local snapshot dir.")
    parser.add_argument("--branch", default=DEFAULT_BRANCH)
    parser.add_argument("--repo", default=DEFAULT_REPO)
    parser.add_argument(
        "--token",
        default="",
        help="GitHub token (or set GH_PAT / GITHUB_TOKEN in the environment).",
    )
    args = parser.parse_args(argv)

    import os

    token = args.token or os.environ.get("GH_PAT") or os.environ.get("GITHUB_TOKEN") or ""
    if not token:
        print("error: no token (pass --token or set GH_PAT/GITHUB_TOKEN).", file=sys.stderr)
        return 2
    store = Path(args.store)
    if args.mode == "publish":
        return publish(store, args.branch, args.repo, token)
    return restore(store, args.branch, args.repo, token)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
