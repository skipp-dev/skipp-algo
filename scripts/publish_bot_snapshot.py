"""Publish selected files to a rolling bot branch without deleting prior state.

The publisher always seeds a temporary work tree from the current remote branch
tip.  A missing branch is bootstrapped from ``main``; any other fetch failure is
fatal.  Before committing, an existing snapshot tree is re-parented to current
``main``.  This prevents both partial replacement of multi-producer state and
unbounded cache-branch history.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from subprocess import CalledProcessError

BOT_NAME = "github-actions[bot]"
BOT_EMAIL = "41898282+github-actions[bot]@users.noreply.github.com"
ZERO_SHA = "0" * 40
_OWNER_REPO = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_BRANCH = re.compile(r"^[A-Za-z0-9._/-]+$")


@dataclass(frozen=True)
class CopySpec:
    source: Path
    destination: PurePosixPath
    required: bool = True


def _redact(text: str, token: str) -> str:
    return text.replace(token, "***") if token else text


def _git(
    args: list[str],
    cwd: Path,
    *,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    git_executable = shutil.which("git") or "git"
    result = subprocess.run(  # noqa: S603 -- validated argv, no shell; git resolved explicitly
        [git_executable, *args],
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
    )
    if check and result.returncode != 0:
        raise CalledProcessError(
            result.returncode,
            result.args,
            output=result.stdout,
            stderr=result.stderr,
        )
    return result


def _branch_is_missing(stderr: str) -> bool:
    message = stderr.lower()
    return "couldn't find remote ref" in message or "could not find remote ref" in message


def _parse_copy(raw: str, *, required: bool) -> CopySpec:
    source_raw, separator, destination_raw = raw.partition("=")
    if not separator or not source_raw or not destination_raw:
        raise argparse.ArgumentTypeError("copy must use SOURCE=DESTINATION")
    destination = PurePosixPath(destination_raw)
    if destination.is_absolute() or ".." in destination.parts or ".git" in destination.parts:
        raise argparse.ArgumentTypeError("destination must be a safe repository-relative path")
    return CopySpec(Path(source_raw), destination, required)


def _copy_into(work: Path, spec: CopySpec) -> bool:
    if not spec.source.is_file():
        if spec.required:
            raise FileNotFoundError(f"required snapshot source missing: {spec.source}")
        return False
    if spec.source.stat().st_size == 0:
        if spec.required:
            raise ValueError(f"required snapshot source is empty: {spec.source}")
        return False
    destination = work.joinpath(*spec.destination.parts)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(spec.source, destination)
    return True


def publish(
    *,
    repo: str,
    branch: str,
    token: str,
    copies: list[CopySpec],
    base_branch: str = "main",
) -> int:
    if not _OWNER_REPO.fullmatch(repo):
        print(f"error: repository must be owner/name, got {repo!r}", file=sys.stderr)
        return 2
    if (
        not _BRANCH.fullmatch(branch)
        or not branch.startswith("bot/")
        or branch.endswith("/")
        or ".." in branch
    ):
        print(f"error: branch must be a valid bot/* name, got {branch!r}", file=sys.stderr)
        return 2
    if not _BRANCH.fullmatch(base_branch) or base_branch.startswith("-") or ".." in base_branch:
        print(f"error: invalid base branch name: {base_branch!r}", file=sys.stderr)
        return 2
    if not token:
        print("error: GH_TOKEN/GITHUB_TOKEN is required", file=sys.stderr)
        return 2
    if not copies:
        print("error: at least one --copy is required", file=sys.stderr)
        return 2

    remote = f"https://x-access-token:{token}@github.com/{repo}.git"
    work = Path(tempfile.mkdtemp(prefix="bot-snapshot-publish-"))
    try:
        _git(["init", "--quiet"], work)
        _git(["config", "user.name", BOT_NAME], work)
        _git(["config", "user.email", BOT_EMAIL], work)
        _git(["remote", "add", "origin", remote], work)

        fetched = _git(["fetch", "--quiet", "--depth", "1", "origin", branch], work, check=False)
        if fetched.returncode == 0:
            expected_sha = _git(["rev-parse", "FETCH_HEAD"], work).stdout.strip()
            has_remote_tip = True
        elif _branch_is_missing(fetched.stderr or ""):
            expected_sha = ZERO_SHA
            has_remote_tip = False
        else:
            raise RuntimeError(f"remote branch fetch failed: {_redact(fetched.stderr.strip(), token)}")

        _git(["fetch", "--quiet", "--depth", "1", "origin", base_branch], work)
        base_sha = _git(["rev-parse", "FETCH_HEAD"], work).stdout.strip()
        seed_sha = expected_sha if has_remote_tip else base_sha
        _git(["checkout", "--quiet", "-B", branch, seed_sha], work)

        destinations: list[str] = []
        for spec in copies:
            if _copy_into(work, spec):
                destinations.append(spec.destination.as_posix())
        if not destinations:
            print("No snapshot sources were present; nothing to publish.")
            return 0

        _git(["add", "-f", "--", *destinations], work)
        diff = _git(["diff", "--cached", "--quiet"], work, check=False)
        if diff.returncode == 0:
            print("No rolling snapshot changes to publish.")
            return 0
        if diff.returncode != 1:
            raise RuntimeError(f"git diff --cached failed with rc={diff.returncode}")

        if has_remote_tip:
            # Keep the complete remote tree in the index, but make the new
            # cache-cursor commit a child of current main rather than the prior
            # cursor. This preserves sibling producer paths without growing an
            # unbounded bot-branch history.
            _git(["reset", "--soft", base_sha], work)
        _git(["commit", "--quiet", "-m", "[skip ci] chore: refresh rolling snapshot"], work)
        remote_ref = f"refs/heads/{branch}"
        lease = f"--force-with-lease={remote_ref}:{expected_sha}"
        _git(["push", lease, "origin", f"HEAD:{remote_ref}"], work)
        print(f"Published {len(destinations)} snapshot file(s) to {branch}.")
        return 0
    except (FileNotFoundError, ValueError, RuntimeError, CalledProcessError) as exc:
        stderr = getattr(exc, "stderr", "") or ""
        detail = stderr.strip() or str(exc)
        print(f"error: snapshot publish failed: {_redact(detail, token)}", file=sys.stderr)
        return 1
    finally:
        shutil.rmtree(work, ignore_errors=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", ""))
    parser.add_argument("--branch", required=True)
    parser.add_argument("--base-branch", default="main")
    parser.add_argument("--copy", action="append", default=[], metavar="SOURCE=DESTINATION")
    parser.add_argument(
        "--copy-if-present",
        action="append",
        default=[],
        metavar="SOURCE=DESTINATION",
    )
    args = parser.parse_args(argv)
    copies = [
        *(_parse_copy(raw, required=True) for raw in args.copy),
        *(_parse_copy(raw, required=False) for raw in args.copy_if_present),
    ]
    token = os.environ.get("GH_TOKEN", "")
    if not token:
        token = os.environ.get("GITHUB_TOKEN", "")
    return publish(
        repo=args.repo,
        branch=args.branch,
        token=token,
        copies=copies,
        base_branch=args.base_branch,
    )


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
