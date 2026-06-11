"""Regenerate ``requirements.lock`` from ``requirements.txt`` using uv.

Thin wrapper around ``uv pip compile`` that pins the Python version and
output path so the lockfile stays deterministic across contributors.

Usage:
    python scripts/regenerate_requirements_lock.py
    python scripts/regenerate_requirements_lock.py --upgrade        # bump all
    python scripts/regenerate_requirements_lock.py --upgrade-package httpx
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_PYTHON_VERSION = "3.12"
_REQ_IN = "requirements.txt"
_REQ_OUT = "requirements.lock"


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--upgrade", action="store_true", help="bump every pinned package (uv pip compile --upgrade)")
    parser.add_argument(
        "--upgrade-package",
        action="append",
        default=[],
        help="bump only this package (repeatable)",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="exit non-zero if the lockfile would change instead of writing it",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if shutil.which("uv") is None:
        print("error: 'uv' not found on PATH. Install with 'pipx install uv' or 'pip install uv'.", file=sys.stderr)
        return 2

    cmd = [
        "uv",
        "pip",
        "compile",
        _REQ_IN,
        "--output-file",
        _REQ_OUT,
        "--python-version",
        _PYTHON_VERSION,
    ]
    if args.upgrade:
        cmd.append("--upgrade")
    for pkg in args.upgrade_package:
        cmd += ["--upgrade-package", pkg]

    if args.check:
        # uv has no native --check; diff old vs newly compiled.
        existing = (_REPO_ROOT / _REQ_OUT).read_text(encoding="utf-8") if (_REPO_ROOT / _REQ_OUT).exists() else ""
        result = subprocess.run(
            [*cmd, "--quiet"],
            cwd=_REPO_ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            sys.stderr.write(result.stderr)
            return result.returncode
        regenerated = (_REPO_ROOT / _REQ_OUT).read_text(encoding="utf-8")
        if existing != regenerated:
            print("error: requirements.lock is out of date. Re-run without --check to update.", file=sys.stderr)
            # ATOMIC-WRITE-EXEMPT: dev-tooling --check restore of the original lock content after a temp regen overwrote it; not a data write to a downstream consumer.
            (_REPO_ROOT / _REQ_OUT).write_text(existing, encoding="utf-8")
            return 1
        return 0

    print(f"[uv-lock] running: {' '.join(cmd)}", file=sys.stderr)
    return subprocess.run(cmd, cwd=_REPO_ROOT, check=False).returncode


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
