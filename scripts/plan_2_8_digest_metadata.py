"""Plan 2.8 digest metadata emitter.

Captures generator-side metadata so weekly outputs are
self-describing. Reports Python version, OS platform, an ISO
UTC timestamp, and the size + mtime of each Plan-2.8 script in
``--scripts-dir``.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import platform
from pathlib import Path
from typing import Any

from scripts.smc_atomic_write import atomic_write_text


def collect(
    scripts_dir: Path,
    *,
    now: _dt.datetime | None = None,
) -> dict[str, Any]:
    now_ = now or _dt.datetime.now(tz=_dt.UTC)
    entries: list[dict[str, Any]] = []
    if scripts_dir.is_dir():
        for p in sorted(scripts_dir.glob("plan_2_8_*.py")):
            st = p.stat()
            entries.append({
                "name":  p.name,
                "size":  st.st_size,
                "mtime": _dt.datetime.fromtimestamp(
                    st.st_mtime, tz=_dt.UTC,
                ).strftime("%Y-%m-%dT%H:%M:%SZ"),
            })
    return {
        "schema_version": 1,
        "captured_at":    now_.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "python":         platform.python_version(),
        "platform":       platform.platform(),
        "scripts_count":  len(entries),
        "scripts":        entries,
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Plan 2.8 digest metadata",
        "",
        f"- captured_at:   {report['captured_at']}",
        f"- python:        {report['python']}",
        f"- platform:      {report['platform']}",
        f"- scripts_count: {report['scripts_count']}",
        "",
    ]
    return "\n".join(lines) + "\n"

# F-V6-A1.1 (2026-05-02): bootstrap root logging so the logger.info(...)
# progress messages this entry point emits actually surface in CI logs
# (default WARNING-only handler would drop them). Extends F-V5-A1-2 / #2012
# from the priority entry-point set to plan_2_8 aggregators + showcase.
try:
    from scripts._logging_init import init_cli_logging
except ImportError:  # script-style invocation: `python scripts/X.py`
    import sys as _v6a11_sys
    from pathlib import Path as _v6a11_Path

    _v6a11_sys.path.insert(0, str(_v6a11_Path(__file__).resolve().parents[1]))
    from scripts._logging_init import init_cli_logging  # type: ignore[no-redef]




def main(argv: list[str] | None = None) -> int:
    init_cli_logging()  # F-V6-A1.1 (2026-05-02)
    parser = argparse.ArgumentParser(
        description="Capture Plan 2.8 digest-generator metadata.",
    )
    parser.add_argument("--scripts-dir", type=Path, default=Path("scripts"))
    parser.add_argument("--format", choices=("md", "json"), default="json")
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args(argv)

    report = collect(args.scripts_dir)
    body = render_markdown(report) if args.format == "md" \
        else json.dumps(report, indent=2) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(body, args.output)
    print(body, end="")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
