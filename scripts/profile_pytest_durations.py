"""Profile the pytest suite and emit a top-N slow-test report.

Runs pytest with ``--durations=N --durations-min=0`` (collection + run),
captures the trailing duration table, and writes a Markdown report under
``docs/perf/pytest_durations_<UTC-date>.md``. Designed for opt-in local /
manual-CI profiling — not wired into any production workflow.

Usage:
    python scripts/profile_pytest_durations.py                  # top 20
    python scripts/profile_pytest_durations.py --top 50         # top 50
    python scripts/profile_pytest_durations.py --xdist          # add -n auto
    python scripts/profile_pytest_durations.py --pytest-args "-k smc"

Exit code mirrors the underlying pytest exit code (0 = pass, !=0 = fail).
The report is written regardless of pass/fail so flaky-and-slow tests
remain visible.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_REPORT_DIR = _REPO_ROOT / "docs" / "perf"
_DURATIONS_HEADER_RE = re.compile(r"^=+\s*slowest\s+\d+\s+durations?\s*=+\s*$", re.IGNORECASE)
_DURATIONS_FOOTER_RE = re.compile(r"^=+\s*(short test summary|passed|failed|errors?|warnings?)", re.IGNORECASE)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--top", type=int, default=20, help="number of slowest tests to capture (default: 20)")
    parser.add_argument("--xdist", action="store_true", help="run with -n auto --dist=worksteal (matches CI)")
    parser.add_argument(
        "--pytest-args",
        default="",
        help="extra args passed verbatim to pytest (e.g. '-k smc')",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="output Markdown path; default: docs/perf/pytest_durations_<UTC-date>.md",
    )
    return parser.parse_args(argv)


def _build_pytest_cmd(args: argparse.Namespace) -> list[str]:
    cmd = [
        sys.executable,
        "-m",
        "pytest",
        "-q",
        f"--durations={args.top}",
        "--durations-min=0",
    ]
    if args.xdist:
        cmd += ["-n", "auto", "--dist=worksteal"]
    if args.pytest_args:
        cmd += shlex.split(args.pytest_args)
    return cmd


def _extract_durations_block(stdout: str) -> list[str]:
    lines = stdout.splitlines()
    block: list[str] = []
    in_block = False
    for line in lines:
        if not in_block and _DURATIONS_HEADER_RE.match(line.strip()):
            in_block = True
            block.append(line)
            continue
        if in_block:
            if _DURATIONS_FOOTER_RE.match(line.strip()):
                break
            block.append(line)
    return block


def _render_report(cmd: list[str], block: list[str], exit_code: int, top: int) -> str:
    now = _dt.datetime.now(_dt.UTC).isoformat(timespec="seconds")
    cmd_str = " ".join(shlex.quote(part) for part in cmd)
    block_text = "\n".join(block).strip() or "_(no durations block captured)_"
    return (
        f"# pytest durations baseline\n\n"
        f"- Captured (UTC): `{now}`\n"
        f"- Top N: `{top}`\n"
        f"- pytest exit code: `{exit_code}`\n"
        f"- Command: `{cmd_str}`\n\n"
        f"## Slowest tests\n\n"
        f"```\n{block_text}\n```\n\n"
        f"> Regenerate with `python scripts/profile_pytest_durations.py`.\n"
    )


def _default_output_path() -> Path:
    today = _dt.datetime.now(_dt.UTC).strftime("%Y%m%d")
    return _REPORT_DIR / f"pytest_durations_{today}.md"


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    if shutil.which("pytest") is None and not (_REPO_ROOT / ".venv").exists():
        print("error: neither 'pytest' on PATH nor a local .venv found", file=sys.stderr)
        return 2

    cmd = _build_pytest_cmd(args)
    print(f"[profile] running: {' '.join(shlex.quote(c) for c in cmd)}", file=sys.stderr)
    completed = subprocess.run(  # noqa: S603 - args are fully constructed locally
        cmd,
        cwd=_REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    block = _extract_durations_block(completed.stdout + "\n" + completed.stderr)
    report = _render_report(cmd, block, completed.returncode, args.top)

    out_path = args.output or _default_output_path()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    # ATOMIC-WRITE-EXEMPT: dev-only profiling helper writes a single
    # human-readable durations report per invocation; no concurrent
    # reader, a torn write would only affect this run's own report.
    out_path.write_text(report, encoding="utf-8")
    print(f"[profile] wrote {out_path}", file=sys.stderr)
    print(f"[profile] pytest exit code: {completed.returncode}", file=sys.stderr)
    return completed.returncode


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
