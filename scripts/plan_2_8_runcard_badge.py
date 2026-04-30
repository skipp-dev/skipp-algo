"""Plan 2.8 shields.io status badge emitter.

Reads a status snapshot JSON (produced by
``scripts/plan_2_8_status_snapshot.py``) and emits a shields.io
"endpoint badge" JSON payload. Also accepts a bare rollout-health
JSON if no snapshot is available.

Output shape (shields.io endpoint schema)::

    {
      "schemaVersion": 1,
      "label":   "plan 2.8",
      "message": "<status>",
      "color":   "brightgreen" | "yellow" | "red" | "lightgrey"
    }

Pure stdlib.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from scripts.smc_atomic_write import atomic_write_text

COLOR_MAP: dict[str, str] = {
    "green":   "brightgreen",
    "amber":   "yellow",
    "red":     "red",
    "unknown": "lightgrey",
}


def _resolve_status(payload: Any) -> str:
    if not isinstance(payload, dict):
        return "unknown"
    # Status-snapshot shape: {"status": "green"|"amber"|"red", ...}
    status = payload.get("status")
    if isinstance(status, str) and status:
        return status.lower()
    # Fall back to bare health shape: {"rollup": "green", ...}
    rollup = payload.get("rollup")
    if isinstance(rollup, str) and rollup:
        return rollup.lower()
    return "unknown"


def build(payload: Any, *, label: str = "plan 2.8") -> dict[str, Any]:
    status = _resolve_status(payload)
    color = COLOR_MAP.get(status, "lightgrey")
    return {
        "schemaVersion": 1,
        "label":         label,
        "message":       status,
        "color":         color,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Emit a shields.io endpoint badge JSON for Plan 2.8.",
    )
    parser.add_argument("--input", type=Path, required=True,
                        help="status-snapshot JSON or bare health JSON")
    parser.add_argument("--label", default="plan 2.8")
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args(argv)

    if not args.input.exists():
        print(f"ERROR: input not found: {args.input}", file=sys.stderr)
        return 1
    try:
        payload = json.loads(args.input.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"ERROR: input is not valid JSON: {exc}", file=sys.stderr)
        return 1

    badge = build(payload, label=args.label)
    body = json.dumps(badge, indent=2) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(body, args.output)
    print(body, end="")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
