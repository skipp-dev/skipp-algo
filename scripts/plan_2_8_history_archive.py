"""Archive Plan 2.8 daily rollup manifests for trend tracking.

The daily rolling-bench writes a fresh ``plan_2_8_tf_family_rollup.json``
into a per-run output directory; nothing currently walks those forward
in time. This helper takes a rollup file and *appends* a compact
snapshot to a long-running history JSONL so a weekly digest can plot
HR drift per TF×family slice without keeping every artifact directory.

The history file is append-only JSONL. Each line is one snapshot:

    {
      "captured_at": "2026-04-21T07:35:12Z",
      "scoring_root": "out/2026-04-21",
      "files_scanned": 12,
      "per_tf": {
        "5m": {"n_events": 312, "hit_rate": 0.471,
               "families": {"FVG": {"n_events": 120, "hit_rate": 0.46}}},
        ...
      }
    }

Snapshots are deduped on ``(captured_at, scoring_root)`` so reruns are
idempotent.

Exit codes
----------
  0 = snapshot appended (or skipped as duplicate)
  1 = unreadable rollup or unwritable history
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import sys
from pathlib import Path
from typing import Any


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            # Tolerate corrupt lines: skip them, do not raise.
            continue
    return out


def _project(rollup: dict[str, Any]) -> dict[str, Any]:
    """Pick the trendable subset out of a rollup manifest."""
    per_tf_in = rollup.get("per_tf") or {}
    per_tf_out: dict[str, Any] = {}
    for tf, slot in per_tf_in.items():
        slot = slot or {}
        per_tf_out[str(tf)] = {
            "n_events": int(slot.get("n_events") or 0),
            "hit_rate": float(slot.get("hit_rate") or 0.0),
            "families": {
                str(fam): {
                    "n_events": int((f or {}).get("n_events") or 0),
                    "hit_rate": float((f or {}).get("hit_rate") or 0.0),
                }
                for fam, f in (slot.get("families") or {}).items()
            },
        }
    return {
        "scoring_root": str(rollup.get("scoring_root") or ""),
        "files_scanned": int(rollup.get("files_scanned") or 0),
        "per_tf": per_tf_out,
    }


def append_snapshot(
    *,
    rollup: dict[str, Any],
    history_path: Path,
    captured_at: str | None = None,
) -> dict[str, Any]:
    """Append a compact snapshot to ``history_path`` (JSONL).

    Idempotent on ``(captured_at, scoring_root)``. Returns a small
    result dict including ``appended`` (bool) and the snapshot itself.
    """
    # Caller-supplied capture time preferred; archival time is a disclosed
    # substitute so backfilled snapshots are distinguishable from
    # measured-at-capture ones (audit #2670 W12).
    if captured_at:
        captured_at_source = "original"
    else:
        captured_at = _dt.datetime.now(_dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        captured_at_source = "archival_backfill"
    snapshot = {
        "captured_at": captured_at,
        "captured_at_source": captured_at_source,
        **_project(rollup),
    }

    existing = _read_jsonl(history_path)
    seen = {(e.get("captured_at"), e.get("scoring_root")) for e in existing}
    key = (snapshot["captured_at"], snapshot["scoring_root"])

    if key in seen:
        return {"appended": False, "snapshot": snapshot, "history_size": len(existing)}

    history_path.parent.mkdir(parents=True, exist_ok=True)
    with history_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(snapshot) + "\n")
    return {"appended": True, "snapshot": snapshot, "history_size": len(existing) + 1}

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
        description="Append a Plan 2.8 rollup snapshot to a long-running history.",
    )
    parser.add_argument("--rollup", type=Path, required=True,
                        help="Path to plan_2_8_tf_family_rollup.json")
    parser.add_argument("--history", type=Path, required=True,
                        help="Append-only JSONL history file.")
    parser.add_argument("--captured-at", default=None,
                        help="Override captured_at (default: now in UTC).")
    args = parser.parse_args(argv)

    try:
        rollup = json.loads(args.rollup.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        print(f"ERROR: unreadable rollup {args.rollup}: {exc}", file=sys.stderr)
        return 1

    try:
        result = append_snapshot(
            rollup=rollup, history_path=args.history,
            captured_at=args.captured_at,
        )
    except OSError as exc:
        print(f"ERROR: unwritable history {args.history}: {exc}", file=sys.stderr)
        return 1

    if result["appended"]:
        print(f"appended snapshot for {result['snapshot']['scoring_root']!r} "
              f"to {args.history} (history size: {result['history_size']})")
    else:
        print(f"snapshot for {result['snapshot']['scoring_root']!r} at "
              f"{result['snapshot']['captured_at']} already in history; skipped")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
