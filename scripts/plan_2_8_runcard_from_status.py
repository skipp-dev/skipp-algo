"""Plan 2.8 compact status runcard.

An alternative one-page runcard sourced entirely from the
machine-readable JSON emitted by the weekly digest pipeline:

  - ``status_snapshot.json``  (plan_2_8_status_snapshot.py)
  - ``runcard_index.json``    (plan_2_8_runcard_index.py)
  - ``health.json``           (plan_2_8_health.py, optional)

Unlike ``plan_2_8_weekly_runcard.py`` (which concatenates the
per-step markdown artifacts), this helper produces a slim, fixed
layout suitable for chat bots, status channels, and README badges.

All inputs are optional; missing files are rendered as "unknown"
rows. Pure stdlib.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from scripts.smc_atomic_write import atomic_write_text


def _read(path: Path | None) -> dict[str, Any] | None:
    if path is None or not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def render(
    status_snapshot: dict[str, Any] | None,
    runcard_index: dict[str, Any] | None,
    health: dict[str, Any] | None,
    *,
    run_url: str | None = None,
) -> str:
    lines = ["# Plan 2.8 status runcard", ""]

    # Status line.
    status = ((status_snapshot or {}).get("status")
              or (health or {}).get("status")
              or "unknown")
    score = ((status_snapshot or {}).get("score")
             if status_snapshot else (health or {}).get("score"))
    score_txt = f"{score:.2f}" if isinstance(score, (int, float)) else "n/a"
    lines.append(f"_status:_ **{status}**  (score {score_txt})")

    if run_url:
        lines.append(f"_run:_ {run_url}")
    lines.append("")

    # Signals.
    s = (status_snapshot or {}).get("signals", {})
    lines.append("## Signals")
    lines.append("")
    lines.append("| metric | value |")
    lines.append("| --- | --- |")
    lines.append(f"| drift alerts        | {s.get('alerts', 'n/a')} |")
    lines.append(f"| coverage under/total | "
                 f"{s.get('coverage_under', 'n/a')}"
                 f" / {s.get('coverage_total', 'n/a')} |")
    lines.append(f"| runcard present/total | "
                 f"{s.get('runcard_present', 'n/a')}"
                 f" / {s.get('runcard_total', 'n/a')} |")
    lines.append("")

    # Runcard index missing sections.
    rc = (runcard_index or {}).get("sections") or []
    if rc:
        missing = [r for r in rc if not r.get("present")]
        lines.append("## Runcard sections")
        lines.append("")
        if not missing:
            lines.append("All expected sections are present.")
        else:
            lines.append("Missing or empty:")
            lines.append("")
            for r in missing:
                lines.append(f"- {r['section']} (`{r['filename']}`)")
        lines.append("")

    # Health findings.
    if health is not None:
        findings = health.get("findings") or []
        lines.append("## Findings")
        lines.append("")
        if findings:
            for f in findings:
                lines.append(f"- {f}")
        else:
            lines.append("_No findings._")
        lines.append("")

    # Missing-input advisory.
    missing_inputs = []
    if status_snapshot is None:
        missing_inputs.append("status_snapshot")
    if runcard_index is None:
        missing_inputs.append("runcard_index")
    if health is None:
        missing_inputs.append("health")
    if missing_inputs:
        lines.append(f"_missing inputs:_ {', '.join(missing_inputs)}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"

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
        description="Render a compact Plan 2.8 status runcard from "
                    "machine-readable JSON inputs.",
    )
    parser.add_argument("--status-snapshot", type=Path, default=None)
    parser.add_argument("--runcard-index", type=Path, default=None)
    parser.add_argument("--health", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--run-url", default=None)
    args = parser.parse_args(argv)

    body = render(
        _read(args.status_snapshot),
        _read(args.runcard_index),
        _read(args.health),
        run_url=args.run_url,
    )
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(body, args.output)
    print(body, end="")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
