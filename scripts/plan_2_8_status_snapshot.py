"""Plan 2.8 status snapshot.

Reads the machine-readable outputs produced elsewhere in the digest
pipeline and collapses them into a single one-line JSON payload
suitable for status dashboards and CI badges:

  - `health.json`         (scripts/plan_2_8_health.py)
  - `runcard_index.json`  (scripts/plan_2_8_runcard_index.py)
  - `coverage.json`       (scripts/plan_2_8_coverage.py --format json)
  - `digest.json`         (scripts/plan_2_8_trend_digest.py --format json)

Missing or unparseable inputs are tolerated silently and surfaced
as ``inputs_seen[key] = false``. Pure stdlib.
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


def snapshot(
    health: dict[str, Any] | None,
    runcard_index: dict[str, Any] | None,
    coverage: dict[str, Any] | None,
    digest: dict[str, Any] | None,
) -> dict[str, Any]:
    status = (health or {}).get("status")
    score = (health or {}).get("score")
    alerts = (digest or {}).get("alerts") or []
    cov_counts = (coverage or {}).get("counts") or {}
    rc_counts = (runcard_index or {}).get("counts") or {}

    return {
        "schema_version": 1,
        "status":         status,
        "score":          score,
        "signals": {
            "alerts":           len(alerts),
            "coverage_under":   cov_counts.get("under", 0),
            "coverage_total":   cov_counts.get("total", 0),
            "runcard_present":  rc_counts.get("present", 0),
            "runcard_total":    rc_counts.get("total", 0),
        },
        "inputs_seen": {
            "health":        health is not None,
            "runcard_index": runcard_index is not None,
            "coverage":      coverage is not None,
            "digest":        digest is not None,
        },
    }


def render_markdown(report: dict[str, Any]) -> str:
    s = report["signals"]
    status = report["status"] or "unknown"
    score = report["score"]
    score_txt = f"{score:.2f}" if isinstance(score, (int, float)) else "n/a"
    lines = [
        "# Plan 2.8 status snapshot",
        "",
        f"- status:           **{status}** (score {score_txt})",
        f"- drift alerts:     {s['alerts']}",
        f"- coverage:         {s['coverage_under']} under / "
        f"{s['coverage_total']} total",
        f"- runcard sections: {s['runcard_present']}/{s['runcard_total']}",
    ]
    missing = [k for k, v in report["inputs_seen"].items() if not v]
    if missing:
        lines.append("")
        lines.append(f"_missing inputs:_ {', '.join(sorted(missing))}")
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
        description="Emit a one-line Plan 2.8 status snapshot JSON.",
    )
    parser.add_argument("--health", type=Path, default=None)
    parser.add_argument("--runcard-index", type=Path, default=None)
    parser.add_argument("--coverage", type=Path, default=None)
    parser.add_argument("--digest", type=Path, default=None)
    parser.add_argument("--format", choices=("md", "json"), default="json")
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args(argv)

    report = snapshot(
        _read(args.health),
        _read(args.runcard_index),
        _read(args.coverage),
        _read(args.digest),
    )
    body = render_markdown(report) if args.format == "md" \
        else json.dumps(report) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(body, args.output)
    print(body, end="")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
