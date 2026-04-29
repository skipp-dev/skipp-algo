#!/usr/bin/env python3
"""Refuse to commit/push manifest files that leaked pytest provenance.

Background: production write-paths (smc_integration/structure_batch.py,
smc_integration/batch.py, smc_core/benchmark.py) have a runtime guard
(see smc_core/_pytest_canonical_write_guard.py and PR #33) that refuses
to overwrite the canonical repo artifact tree while pytest is active.
This script is the static counterpart: even if a guard ever regresses,
no poisoned manifest can land in the repo.

Patterns detected:
  - ``pytest-of-<user>``        — pytest tmp_path provenance
  - ``/var/folders/.../T/pytest`` — macOS pytest tmpdir
  - ``/tmp/pytest-of-``         — Linux pytest tmpdir

Exit codes:
  0 — clean (or no candidate files)
  1 — at least one offending file (paths printed to stderr)

CLI:
  scan_manifests_for_pytest_provenance.py [PATH ...]

If no PATHs are given, scans staged additions/modifications matching
``manifest*.json`` (used by pre-commit). Otherwise scans the given files
verbatim (used by CI against the tracked tree).
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from collections.abc import Iterable
from pathlib import Path

# Match repo-tracked manifests written by snapshot/structure/benchmark code:
#   manifest_5m.json, manifest_15m.json, manifest_1H.json, manifest.json,
#   benchmark_run_manifest.json, library_release_manifest.json, ...
_MANIFEST_RE = re.compile(r"(?:^|/)[A-Za-z0-9_]*manifest(?:_[^/]*)?\.json$")

_POISON_PATTERNS = (
    re.compile(r"pytest-of-[A-Za-z0-9_.-]+"),
    re.compile(r"/var/folders/[^\"']+/T/pytest[^\"']*"),
    re.compile(r"/tmp/pytest-of-[^\"']+"),
)


def _staged_manifest_paths() -> list[Path]:
    """Return staged Added/Modified files matching the manifest pattern."""
    try:
        git_exe = shutil.which("git") or "git"
        out = subprocess.check_output(
            [git_exe, "diff", "--cached", "--name-only", "--diff-filter=AM"],
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return []
    return [Path(line) for line in out.splitlines() if _MANIFEST_RE.search(line)]


def _scan(paths: Iterable[Path]) -> list[tuple[Path, str]]:
    findings: list[tuple[Path, str]] = []
    for path in paths:
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for pattern in _POISON_PATTERNS:
            match = pattern.search(text)
            if match:
                findings.append((path, match.group(0)))
                break
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*", type=Path)
    parser.add_argument(
        "--all-tracked",
        action="store_true",
        help="Scan every tracked *manifest*.json (CI mode).",
    )
    args = parser.parse_args(argv)

    if args.all_tracked:
        try:
            git_exe = shutil.which("git") or "git"
            tracked = subprocess.check_output(
                [git_exe, "ls-files"], text=True
            ).splitlines()
        except (OSError, subprocess.CalledProcessError) as exc:
            print(f"error: git ls-files failed: {exc}", file=sys.stderr)
            return 2
        candidates = [Path(p) for p in tracked if _MANIFEST_RE.search(p)]
    elif args.paths:
        # Pre-commit passes filenames already filtered via 'files:' regex.
        candidates = list(args.paths)
    else:
        candidates = _staged_manifest_paths()

    if not candidates:
        return 0

    findings = _scan(candidates)
    if not findings:
        return 0

    print(
        "ERROR: pytest provenance detected in manifest file(s):",
        file=sys.stderr,
    )
    for path, snippet in findings:
        print(f"  {path}: matched {snippet!r}", file=sys.stderr)
    print(
        "\nThese manifests were almost certainly produced by a test run that "
        "forgot to redirect output_dir to tmp_path. Regenerate the manifest "
        "with the production CLI before committing. See PR #33 / PR #35 / "
        "smc_core/_pytest_canonical_write_guard.py.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
