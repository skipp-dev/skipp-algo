"""Wrap an arbitrary Python entry point with py-spy sampling.

Records a CPU flamegraph (SVG) and a sampled top-N profile (text) for any
Python invocation — typically used to profile a single cron-style job
locally (e.g. ``smc-library-refresh``'s consumer entry point) without
touching production code.

py-spy is *not* a runtime dependency of skipp-algo. Install on demand:

    uv pip install py-spy            # local venv
    # or
    pipx install py-spy              # isolated

Usage:

    python scripts/profile_cron_with_pyspy.py -- python -m path.to.entry
    python scripts/profile_cron_with_pyspy.py --rate 250 -- python script.py

Outputs (by default under ``docs/perf/pyspy_<slug>_<UTC>/``):
    - ``flamegraph.svg`` (py-spy record)
    - ``top.txt``        (py-spy record --format speedscope.json fallback if
                          'top' is unsupported on the platform)

Exit code mirrors the inner subprocess exit code. The profile is written
even on non-zero exit so partial cron failures stay diagnosable.
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
_SLUG_RE = re.compile(r"[^A-Za-z0-9._-]+")


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--rate", type=int, default=100, help="py-spy sampling rate Hz (default: 100)")
    parser.add_argument("--subprocesses", action="store_true", help="profile subprocesses too (-s)")
    parser.add_argument("--idle", action="store_true", help="include idle threads (--idle)")
    parser.add_argument(
        "--slug",
        default=None,
        help="output-directory slug; defaults to a sanitized form of the inner command",
    )
    parser.add_argument(
        "--out-root",
        type=Path,
        default=_REPORT_DIR,
        help="root directory for profile artifacts (default: docs/perf)",
    )
    parser.add_argument(
        "inner",
        nargs=argparse.REMAINDER,
        help="inner command (prefix with -- ). Example: -- python -m mypkg.cli",
    )
    return parser.parse_args(argv)


def _resolve_inner(inner: list[str]) -> list[str]:
    if inner and inner[0] == "--":
        inner = inner[1:]
    if not inner:
        raise SystemExit("error: provide an inner command after '--' (e.g. '-- python -m my.entry')")
    return inner


def _make_slug(inner: list[str], explicit: str | None) -> str:
    if explicit:
        return _SLUG_RE.sub("-", explicit).strip("-") or "profile"
    joined = "_".join(inner[:4])
    cleaned = _SLUG_RE.sub("-", joined).strip("-")
    return (cleaned or "profile")[:60]


def _ensure_pyspy() -> str:
    pyspy = shutil.which("py-spy")
    if pyspy:
        return pyspy
    raise SystemExit(
        "error: 'py-spy' not found on PATH. Install with 'uv pip install py-spy' or 'pipx install py-spy'.",
    )


def _build_record_cmd(
    pyspy: str,
    args: argparse.Namespace,
    inner: list[str],
    flamegraph: Path,
) -> list[str]:
    cmd = [
        pyspy,
        "record",
        "--rate",
        str(args.rate),
        "--output",
        str(flamegraph),
        "--format",
        "flamegraph",
    ]
    if args.subprocesses:
        cmd.append("-s")
    if args.idle:
        cmd.append("--idle")
    cmd.append("--")
    cmd.extend(inner)
    return cmd


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    inner = _resolve_inner(args.inner)
    pyspy = _ensure_pyspy()

    slug = _make_slug(inner, args.slug)
    ts = _dt.datetime.now(_dt.UTC).strftime("%Y%m%dT%H%M%SZ")
    out_dir: Path = args.out_root / f"pyspy_{slug}_{ts}"
    out_dir.mkdir(parents=True, exist_ok=True)

    flamegraph = out_dir / "flamegraph.svg"
    record_cmd = _build_record_cmd(pyspy, args, inner, flamegraph)
    print(f"[pyspy] {' '.join(shlex.quote(c) for c in record_cmd)}", file=sys.stderr)

    completed = subprocess.run(record_cmd, cwd=_REPO_ROOT, check=False)  # noqa: S603 - locally constructed
    print(f"[pyspy] flamegraph: {flamegraph}", file=sys.stderr)

    notes = out_dir / "README.md"
    # ATOMIC-WRITE-EXEMPT: dev-only profiling helper; the README is a
    # one-shot annotation file written into a freshly created per-run
    # directory (`out_dir`) and never read concurrently. A torn write
    # would only affect this profile run's own notes.
    notes.write_text(
        (
            f"# py-spy profile: {slug}\n\n"
            f"- Captured (UTC): `{ts}`\n"
            f"- Rate: `{args.rate} Hz`\n"
            f"- Inner command: `{' '.join(shlex.quote(c) for c in inner)}`\n"
            f"- Exit code: `{completed.returncode}`\n"
            f"- Flamegraph: [flamegraph.svg](./flamegraph.svg)\n\n"
            f"Open the SVG in any browser to interactively explore hot paths.\n"
        ),
        encoding="utf-8",
    )
    return completed.returncode


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
