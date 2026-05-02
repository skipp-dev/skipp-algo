"""Plan 2.8 digest schema validator.

Lightweight, dependency-free validator for the digest JSON payload
produced by the weekly workflow. Checks required keys and value
types without depending on ``jsonschema``.

Expected shape::

    {
      "schema_version": 1,
      "captured_at":    "<iso8601>",
      "scoring_root":   "<string>",
      "alerts": [
        {
          "tf":            "<string>",
          "family":        "<string>",
          "hit_rate_pct":  <number>,
          "delta_pp":      <number>,
          "events":        <integer>,
          "severity":      "<string>"
        }
      ]
    }

Unknown keys are allowed. ``alerts`` may be empty. Pure stdlib.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from scripts.smc_atomic_write import atomic_write_text

TOP_REQUIRED: dict[str, tuple[type, ...]] = {
    "schema_version": (int,),
    "captured_at":    (str,),
    "scoring_root":   (str,),
    "alerts":         (list,),
}

ALERT_REQUIRED: dict[str, tuple[type, ...]] = {
    "tf":           (str,),
    "family":       (str,),
    "hit_rate_pct": (int, float),
    "delta_pp":     (int, float),
    "events":       (int,),
    "severity":     (str,),
}


def _check_types(
    payload: dict[str, Any],
    spec: dict[str, tuple[type, ...]],
    where: str,
) -> list[dict[str, Any]]:
    problems: list[dict[str, Any]] = []
    for key, types in spec.items():
        if key not in payload:
            problems.append({
                "where": where, "key": key, "issue": "missing",
            })
            continue
        value = payload[key]
        if isinstance(value, bool) and bool not in types:
            # bools are ints; reject unless the spec explicitly allows bool
            problems.append({
                "where": where, "key": key,
                "issue": "wrong_type",
                "expected": "/".join(t.__name__ for t in types),
                "actual":   "bool",
            })
            continue
        if not isinstance(value, types):
            problems.append({
                "where": where, "key": key,
                "issue": "wrong_type",
                "expected": "/".join(t.__name__ for t in types),
                "actual":   type(value).__name__,
            })
    return problems


def validate(digest: Any) -> dict[str, Any]:
    problems: list[dict[str, Any]] = []
    if not isinstance(digest, dict):
        return {
            "schema_version": 1,
            "valid":          False,
            "counts":         {"errors": 1, "alerts": 0},
            "errors": [{
                "where": "<root>", "key": "<root>",
                "issue": "wrong_type",
                "expected": "dict",
                "actual":   type(digest).__name__,
            }],
        }

    problems.extend(_check_types(digest, TOP_REQUIRED, "<root>"))

    alerts = digest.get("alerts")
    alerts_count = 0
    if isinstance(alerts, list):
        alerts_count = len(alerts)
        for idx, alert in enumerate(alerts):
            where = f"alerts[{idx}]"
            if not isinstance(alert, dict):
                problems.append({
                    "where": where, "key": "<alert>",
                    "issue": "wrong_type",
                    "expected": "dict",
                    "actual":   type(alert).__name__,
                })
                continue
            problems.extend(_check_types(alert, ALERT_REQUIRED, where))

    return {
        "schema_version": 1,
        "valid":          not problems,
        "counts":         {"errors": len(problems), "alerts": alerts_count},
        "errors":         problems,
    }


def render_markdown(report: dict[str, Any]) -> str:
    c = report["counts"]
    lines = [
        "# Plan 2.8 digest schema report",
        "",
        f"- valid:   {str(report['valid']).lower()}",
        f"- errors:  {c['errors']}",
        f"- alerts:  {c['alerts']}",
        "",
    ]
    if report["errors"]:
        lines.append("| where | key | issue | expected | actual |")
        lines.append("| --- | --- | --- | --- | --- |")
        for err in report["errors"]:
            lines.append(
                f"| `{err['where']}` | `{err['key']}` | {err['issue']} | "
                f"{err.get('expected', '-')} | {err.get('actual', '-')} |"
            )
    else:
        lines.append("_Digest payload matches expected schema._")
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
        description="Validate the Plan 2.8 digest JSON payload.",
    )
    parser.add_argument("--digest", type=Path, required=True)
    parser.add_argument("--format", choices=("md", "json"), default="md")
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--fail-on-invalid", action="store_true")
    args = parser.parse_args(argv)

    if not args.digest.exists():
        print(f"ERROR: digest not found: {args.digest}", file=sys.stderr)
        return 1
    try:
        payload = json.loads(args.digest.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"ERROR: digest is not valid JSON: {exc}", file=sys.stderr)
        return 1

    report = validate(payload)
    body = render_markdown(report) if args.format == "md" \
        else json.dumps(report, indent=2) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(body, args.output)
    print(body, end="")
    if args.fail_on_invalid and not report["valid"]:
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
