"""Validate the integrity of a Plan 2.8 history JSONL.

Checks performed (all non-destructive):

  * every non-blank line parses as JSON
  * every snapshot has a parseable ISO ``captured_at``
  * ``(captured_at, scoring_root)`` is unique
  * ``per_tf`` is a mapping (when present)

Exits ``0`` on a clean file, ``1`` on validation errors. The intent
is to give the rolling bench an early-warning signal if the archiver
or rotator ever start producing malformed snapshots, without
mutating the file.

Pure stdlib.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any


def _parse_iso(ts: str) -> _dt.datetime:
    if ts.endswith("Z"):
        ts = ts[:-1] + "+00:00"
    return _dt.datetime.fromisoformat(ts)


def validate(history_path: Path) -> dict[str, Any]:
    """Return ``{ok, snapshots, errors:[{line, kind, detail}], duplicates}``."""
    if not history_path.exists():
        raise ValueError(f"history not found: {history_path}")

    errors: list[dict[str, Any]] = []
    keys: list[tuple[str, str]] = []
    snapshots = 0

    for lineno, raw in enumerate(
        history_path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        line = raw.strip()
        if not line:
            continue
        try:
            snap = json.loads(line)
        except json.JSONDecodeError as exc:
            errors.append({"line": lineno, "kind": "json", "detail": str(exc)})
            continue
        if not isinstance(snap, dict):
            errors.append({"line": lineno, "kind": "shape",
                           "detail": "snapshot is not a JSON object"})
            continue
        snapshots += 1
        captured_at = snap.get("captured_at")
        if not isinstance(captured_at, str) or not captured_at:
            errors.append({"line": lineno, "kind": "captured_at",
                           "detail": "missing or non-string captured_at"})
        else:
            try:
                _parse_iso(captured_at)
            except ValueError as exc:
                errors.append({"line": lineno, "kind": "captured_at",
                               "detail": f"unparseable timestamp: {exc}"})
        scoring_root = snap.get("scoring_root")
        if not isinstance(scoring_root, str) or not scoring_root:
            errors.append({"line": lineno, "kind": "scoring_root",
                           "detail": "missing or non-string scoring_root"})
        per_tf = snap.get("per_tf")
        if per_tf is not None and not isinstance(per_tf, dict):
            errors.append({"line": lineno, "kind": "per_tf",
                           "detail": "per_tf must be an object"})
        if isinstance(captured_at, str) and isinstance(scoring_root, str):
            keys.append((captured_at, scoring_root))

    counts = Counter(keys)
    duplicates = sorted(k for k, v in counts.items() if v > 1)
    for k in duplicates:
        errors.append({"line": -1, "kind": "duplicate",
                       "detail": f"{k[0]} / {k[1]}"})

    return {
        "ok": not errors,
        "snapshots": snapshots,
        "errors": errors,
        "duplicates": [{"captured_at": k[0], "scoring_root": k[1]}
                       for k in duplicates],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate a Plan 2.8 history JSONL for shape and uniqueness.",
    )
    parser.add_argument("--history", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=None,
                        help="Write the JSON report to this path.")
    parser.add_argument("--quiet", action="store_true",
                        help="Suppress stdout report; only set the exit code.")
    args = parser.parse_args(argv)

    try:
        report = validate(args.history)
    except (ValueError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    body = json.dumps(report, indent=2) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(body, encoding="utf-8")
    if not args.quiet:
        print(body, end="")
    return 0 if report["ok"] else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
