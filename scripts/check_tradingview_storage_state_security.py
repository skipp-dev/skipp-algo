"""Guard against committing plaintext TradingView Playwright auth state.

TradingView Playwright ``storage-state.json`` files contain cookies,
localStorage and IndexedDB-derived auth material. They are useful as local or
CI secrets, but they must never become tracked repository content or release
artifacts.

This script scans tracked files (``git ls-files``) by default and fails if a
tracked file looks like a plaintext Playwright storage-state artifact in the
TradingView auth locations.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

SENSITIVE_AUTH_PREFIXES = (
    Path("automation/tradingview/auth"),
    Path("playwright/.auth"),
)

SENSITIVE_STORAGE_STATE_NAMES = {
    "storage-state.json",
    "storage_state.json",
}


@dataclass(frozen=True)
class StorageStateViolation:
    """Path/reason container for concise CLI output."""

    path: Path
    reason: str


def _normalise_relative(path: Path) -> Path:
    return Path(*path.as_posix().split("/"))


def _is_under(path: Path, prefix: Path) -> bool:
    try:
        path.relative_to(prefix)
    except ValueError:
        return False
    return True


def is_sensitive_storage_state_path(path: Path) -> bool:
    """Return True for TradingView/Playwright auth-state file locations."""

    rel = _normalise_relative(path)
    if rel.name not in SENSITIVE_STORAGE_STATE_NAMES:
        return False
    return any(_is_under(rel, prefix) for prefix in SENSITIVE_AUTH_PREFIXES)


def looks_like_plaintext_playwright_storage_state(path: Path) -> bool:
    """Return True if ``path`` has Playwright storage-state JSON shape."""

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return False

    if not isinstance(data, dict):
        return False

    cookies = data.get("cookies")
    origins = data.get("origins")
    if isinstance(cookies, list) and isinstance(origins, list):
        return True

    # Persistent-profile validated files can carry auth metadata in addition
    # to the Playwright fields. Keep this branch explicit so empty/anonymous
    # files are still treated as auth-state artifacts if they live in the
    # sensitive location.
    meta = data.get("meta")
    return isinstance(meta, dict) and any(str(key).startswith("authValidated") for key in meta)


def git_tracked_files(repo_root: Path = REPO_ROOT) -> list[Path]:
    """Return paths tracked by git, relative to ``repo_root``."""

    completed = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=False,
    )
    raw = completed.stdout.split(b"\0")
    return [Path(item.decode("utf-8")) for item in raw if item]


def find_storage_state_violations(
    paths: Iterable[Path],
    *,
    repo_root: Path = REPO_ROOT,
) -> list[StorageStateViolation]:
    """Return tracked plaintext auth-state violations for ``paths``."""

    violations: list[StorageStateViolation] = []
    for rel in paths:
        rel = _normalise_relative(rel)
        if not is_sensitive_storage_state_path(rel):
            continue
        full = repo_root / rel
        if full.exists() and looks_like_plaintext_playwright_storage_state(full):
            violations.append(StorageStateViolation(rel, "plaintext Playwright storage-state JSON is tracked"))
        else:
            violations.append(StorageStateViolation(rel, "sensitive storage-state path is tracked"))
    return violations


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=REPO_ROOT,
        help="Repository root to scan (default: current script's repository).",
    )
    args = parser.parse_args(argv)

    repo_root = args.repo_root.resolve()
    violations = find_storage_state_violations(git_tracked_files(repo_root), repo_root=repo_root)
    if not violations:
        print("TradingView storage-state security check passed: no tracked plaintext auth-state files.")
        return 0

    print("TradingView storage-state security check failed:", file=sys.stderr)
    for violation in violations:
        print(f"- {violation.path}: {violation.reason}", file=sys.stderr)
    print(
        "Remove the file from git, rotate the TradingView session, and keep auth state in ignored local files or encrypted CI secrets only.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
