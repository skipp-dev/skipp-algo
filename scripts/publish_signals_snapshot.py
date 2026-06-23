"""Publish the realtime trading-signals snapshot to a rolling bot branch.

The live-overlay daemon only shows trading signals when it can reach the
snapshot ``artifacts/open_prep/latest/latest_realtime_signals.json``. That file
is produced exclusively by ``open_prep/realtime_signals.py`` on the live
trading host (a ``while True`` poll loop that needs ``FMP_API_KEY`` and a recent
``latest_open_prep_run.json``); there is intentionally no CI producer for it.

For the *hosted* daemon (e.g. on Railway) the file therefore has to be
published somewhere the daemon can fetch over https, exactly like the
news/experiment/credential snapshots. This helper is the signals analogue of
the workflow publish steps: run it on the live trading host (cron / after each
engine cycle) and it force-updates a dedicated ``bot/live-signals-snapshot``
branch with the latest snapshot. The daemon then reads it via
``SIGNALS_SNAPSHOT_URL`` (+ optional ``SIGNALS_SNAPSHOT_URL_TOKEN``).

Why a separate bot branch and ``--force-with-lease``:
    * A bare push to ``main`` is blocked by the ``main-governance`` ruleset;
      ``bot/*`` branches are excluded, so we keep this churn off ``main``.
    * The branch holds a single rolling file; history is irrelevant, so each
      run force-updates the tip (with a lease so we never clobber a concurrent
      push blindly).

Design notes:
    * Pure stdlib; no third-party deps, no ``urlopen`` (git does the transport).
    * All git calls go through ``subprocess.run([...], check=True)`` with an
      explicit argument list — never ``shell=True`` — so there is no shell
      injection surface and the repo hygiene gate stays green.
    * Work happens in a throwaway temp directory so the caller's working tree
      is never touched.
    * The token is read from ``GH_TOKEN`` (or ``GITHUB_TOKEN``) in the
      environment and is only ever embedded in the in-process remote URL; it is
      never printed.

Exit codes:
    0 = published (or nothing changed since the last publish)
    1 = configuration error (missing token / missing snapshot file)
    2 = git failure (push rejected, network, etc.)
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

DEFAULT_INPUT = "artifacts/open_prep/latest/latest_realtime_signals.json"
DEFAULT_BRANCH = "bot/live-signals-snapshot"
DEFAULT_REPO = "skippALGO/skipp-algo"
# Path the snapshot lives at *inside* the bot branch. Keep it identical to the
# local layout so SIGNALS_SNAPSHOT_URL mirrors the on-host path 1:1.
DEST_PATH = "artifacts/open_prep/latest/latest_realtime_signals.json"

BOT_NAME = "github-actions[bot]"
BOT_EMAIL = "41898282+github-actions[bot]@users.noreply.github.com"


def _git(
    args: list[str], cwd: Path, *, check: bool = True
) -> subprocess.CompletedProcess[str]:
    """Run a single git subcommand with explicit argv (no shell).

    ``git`` is resolved via :func:`shutil.which` and every argument is a
    plain argv item (including caller-provided branch / repo names from CLI).
    We never invoke a shell, so these values are passed verbatim as arguments
    and do not create shell-injection risk.
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
    """Return True iff ``name`` is a safe git branch name.

    Rejects names that start with ``-`` (would be parsed as a git flag),
    contain control characters, or violate basic git ref rules.
    """
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
    # Each path component must not start with '.' and must not be empty.
    for component in name.split("/"):
        if not component or component.startswith("."):
            return False
    return not any(ch in name for ch in "~^:\\ \t")


def _git_diff_has_changes(cwd: Path) -> bool:
    """Return True when there are staged changes to commit."""
    result = _git(["diff", "--cached", "--quiet"], cwd, check=False)
    # returncode 1 = differences found; >1 = git error (not-a-repo, etc.)
    if result.returncode > 1:
        raise RuntimeError(
            f"git diff --cached failed (rc={result.returncode}): "
            f"{result.stderr.strip()}"
        )
    return result.returncode == 1


def publish(input_path: Path, branch: str, repo: str, token: str) -> int:
    """Publish ``input_path`` to ``branch`` on ``repo``. Returns an exit code."""
    if not input_path.is_file():
        print(f"error: signals snapshot not found: {input_path}", file=sys.stderr)
        return 1
    if not _is_valid_owner_repo(repo):
        print(f"error: repo must be owner/name with valid characters, got {repo!r}", file=sys.stderr)
        return 1
    if not _is_valid_branch(branch):
        print(f"error: invalid branch name: {branch!r}", file=sys.stderr)
        return 1

    remote = f"https://x-access-token:{token}@github.com/{repo}.git"
    work = Path(tempfile.mkdtemp(prefix="signals-snapshot-"))
    try:
        _git(["init", "--quiet"], work)
        _git(["config", "user.name", BOT_NAME], work)
        _git(["config", "user.email", BOT_EMAIL], work)
        _git(["remote", "add", "origin", remote], work)

        # Seed from the existing branch tip when it exists so --force-with-lease
        # has a real base and an unchanged snapshot becomes a no-op commit.
        fetched = _git(
            ["fetch", "--quiet", "--depth", "1", "origin", branch], work, check=False
        )
        has_remote_tip = fetched.returncode == 0
        if has_remote_tip:
            _git(["checkout", "--quiet", "-B", branch, "FETCH_HEAD"], work)
        else:
            # A missing remote ref is the normal first-publish case; anything else
            # (auth/network) silently discards the existing tip, so surface it.
            stderr = (fetched.stderr or "").strip()
            if stderr and "find remote ref" not in stderr.lower():
                print(
                    f"warning: initial fetch failed; seeding empty branch: "
                    f"{_redact_token(stderr, token)}",
                    file=sys.stderr,
                )
            _git(["checkout", "--quiet", "-B", branch], work)

        dest = work / DEST_PATH
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            data = input_path.read_bytes()
        except PermissionError:
            print(f"error: cannot read input file: {input_path}", file=sys.stderr)
            return 1
        try:
            dest.write_bytes(data)
        except PermissionError:
            print(f"error: cannot write destination file: {dest}", file=sys.stderr)
            return 1

        _git(["add", "-f", DEST_PATH], work)
        if not _git_diff_has_changes(work):
            print("No signals snapshot changes to publish.")
            return 0

        _git(
            ["commit", "--quiet", "-m", "[skip ci] chore: refresh signals snapshot"],
            work,
        )
        if has_remote_tip:
            push_args = [
                "push",
                f"--force-with-lease=refs/heads/{branch}",
                "origin",
                f"HEAD:refs/heads/{branch}",
            ]
        else:
            # First publish: use an all-zeros expected SHA so the push only
            # succeeds if the remote branch genuinely does not exist yet.
            # This prevents silently clobbering a branch created between our
            # fetch and push (race window on concurrent first-publishes).
            _ZERO_SHA = "0" * 40
            push_args = [
                "push",
                f"--force-with-lease=refs/heads/{branch}:{_ZERO_SHA}",
                "origin",
                f"HEAD:refs/heads/{branch}",
            ]
        _git(
            push_args,
            work,
        )
        print(f"Published signals snapshot to {branch}.")
        return 0
    except subprocess.CalledProcessError as exc:
        detail = _redact_token((exc.stderr or exc.stdout or "").strip(), token)
        if detail:
            print(
                f"error: git command failed (exit {exc.returncode}): {detail}",
                file=sys.stderr,
            )
        else:
            print(f"error: git command failed (exit {exc.returncode})", file=sys.stderr)
        return 2
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    finally:
        shutil.rmtree(work, ignore_errors=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        default=DEFAULT_INPUT,
        help=f"Path to the local signals snapshot (default: {DEFAULT_INPUT}).",
    )
    parser.add_argument(
        "--branch",
        default=DEFAULT_BRANCH,
        help=f"Rolling bot branch to publish to (default: {DEFAULT_BRANCH}).",
    )
    parser.add_argument(
        "--repo",
        default=DEFAULT_REPO,
        help=f"owner/name of the GitHub repository (default: {DEFAULT_REPO}).",
    )
    args = parser.parse_args(argv)

    token = os.environ.get("GH_TOKEN", "")
    if not token:
        token = os.environ.get("GITHUB_TOKEN", "")
    if not token:
        print(
            "error: GH_TOKEN (or GITHUB_TOKEN) must be set with push rights to "
            "the bot snapshot branch.",
            file=sys.stderr,
        )
        return 1

    return publish(Path(args.input), args.branch, args.repo, token)


if __name__ == "__main__":
    raise SystemExit(main())
