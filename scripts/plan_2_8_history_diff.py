"""Diff two snapshots inside a Plan 2.8 history JSONL.

The weekly trend digest already produces an aggregate "prev vs latest"
verdict. This helper is the manual triage counterpart: pick any two
snapshots (by ``captured_at`` or by index) and print a per-TF /
per-family hit-rate delta. Useful when an incident review wants to
isolate the change from a specific deploy or data-quality event.

Pure stdlib, no mutation of the input file.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from scripts.smc_atomic_write import atomic_write_text


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise ValueError(f"history not found: {path}")
    out: list[dict[str, Any]] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            # Skip corrupt rows: they're already flagged by validate.
            continue
    return out


def _select(snaps: list[dict[str, Any]], *,
            captured_at: str | None, index: int | None) -> dict[str, Any]:
    if captured_at is not None:
        for s in snaps:
            if s.get("captured_at") == captured_at:
                return s
        raise ValueError(f"no snapshot with captured_at={captured_at!r}")
    if index is not None:
        # Allow negative indexing, but clamp.
        if index < -len(snaps) or index >= len(snaps):
            raise ValueError(f"index {index} out of range for {len(snaps)} snapshots")
        return snaps[index]
    raise ValueError("either captured_at or index must be supplied")


def diff_snapshots(prev: dict[str, Any], latest: dict[str, Any]) -> dict[str, Any]:
    """Return a per-TF and per-family HR-delta diff between two snapshots."""
    prev_tfs: dict[str, Any] = prev.get("per_tf") or {}
    latest_tfs: dict[str, Any] = latest.get("per_tf") or {}
    tfs = sorted(set(prev_tfs) | set(latest_tfs))

    per_tf: list[dict[str, Any]] = []
    per_family: list[dict[str, Any]] = []
    for tf in tfs:
        p = prev_tfs.get(tf) or {}
        lat = latest_tfs.get(tf) or {}
        hr_p = p.get("hit_rate")
        hr_l = lat.get("hit_rate")
        delta = None if (hr_p is None or hr_l is None) else hr_l - hr_p
        per_tf.append({
            "tf": tf,
            "hr_prev":   hr_p,
            "hr_latest": hr_l,
            "delta_pp":  delta,
            "n_prev":   p.get("n_events"),
            "n_latest": lat.get("n_events"),
        })
        fams = sorted(set(p.get("families") or {}) | set(lat.get("families") or {}))
        for fam in fams:
            fp = (p.get("families") or {}).get(fam) or {}
            fl = (lat.get("families") or {}).get(fam) or {}
            fhr_p = fp.get("hit_rate")
            fhr_l = fl.get("hit_rate")
            fdelta = None if (fhr_p is None or fhr_l is None) else fhr_l - fhr_p
            per_family.append({
                "tf": tf, "family": fam,
                "hr_prev":   fhr_p,
                "hr_latest": fhr_l,
                "delta_pp":  fdelta,
                "n_prev":   fp.get("n_events"),
                "n_latest": fl.get("n_events"),
            })

    return {
        "schema_version": 1,
        "prev":   {"captured_at": prev.get("captured_at"),
                   "scoring_root": prev.get("scoring_root")},
        "latest": {"captured_at": latest.get("captured_at"),
                   "scoring_root": latest.get("scoring_root")},
        "per_tf": per_tf,
        "per_family": per_family,
    }


def render_markdown(diff: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# Plan 2.8 history snapshot diff")
    lines.append("")
    lines.append(f"- prev:   `{diff['prev']['captured_at']}` "
                 f"(`{diff['prev']['scoring_root']}`)")
    lines.append(f"- latest: `{diff['latest']['captured_at']}` "
                 f"(`{diff['latest']['scoring_root']}`)")
    lines.append("")
    lines.append("## Per-TF")
    lines.append("")
    lines.append("| tf | n_prev | n_latest | hr_prev | hr_latest | delta_pp |")
    lines.append("|----|-------:|---------:|--------:|----------:|---------:|")
    for r in diff["per_tf"]:
        lines.append(
            f"| {r['tf']} | {r['n_prev']} | {r['n_latest']} | "
            f"{r['hr_prev']} | {r['hr_latest']} | "
            f"{'' if r['delta_pp'] is None else f'{r['delta_pp']:+.3f}'} |"
        )
    lines.append("")
    lines.append("## Per-TF x family")
    lines.append("")
    lines.append("| tf | family | n_prev | n_latest | hr_prev | hr_latest | delta_pp |")
    lines.append("|----|--------|-------:|---------:|--------:|----------:|---------:|")
    for r in diff["per_family"]:
        lines.append(
            f"| {r['tf']} | {r['family']} | {r['n_prev']} | {r['n_latest']} | "
            f"{r['hr_prev']} | {r['hr_latest']} | "
            f"{'' if r['delta_pp'] is None else f'{r['delta_pp']:+.3f}'} |"
        )
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
        description="Diff two snapshots inside a Plan 2.8 history JSONL.",
    )
    parser.add_argument("--history", type=Path, required=True)
    parser.add_argument("--prev-captured-at", type=str, default=None)
    parser.add_argument("--latest-captured-at", type=str, default=None)
    parser.add_argument("--prev-index", type=int, default=None,
                        help="0-based index into the JSONL (negatives allowed).")
    parser.add_argument("--latest-index", type=int, default=None,
                        help="0-based index into the JSONL (negatives allowed).")
    parser.add_argument("--format", choices=("md", "json"), default="md")
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args(argv)

    if args.prev_captured_at is None and args.prev_index is None:
        args.prev_index = -2
    if args.latest_captured_at is None and args.latest_index is None:
        args.latest_index = -1

    try:
        snaps = _read_jsonl(args.history)
        if len(snaps) < 2:
            print("ERROR: need at least 2 snapshots to diff", file=sys.stderr)
            return 1
        prev = _select(snaps,
                       captured_at=args.prev_captured_at,
                       index=args.prev_index)
        latest = _select(snaps,
                         captured_at=args.latest_captured_at,
                         index=args.latest_index)
    except (ValueError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    diff = diff_snapshots(prev, latest)
    body = render_markdown(diff) if args.format == "md" \
        else json.dumps(diff, indent=2) + "\n"

    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(body, args.output)
    print(body, end="")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
