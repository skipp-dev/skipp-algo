"""Lint ``configs/plan_2_8_snoozes.json``.

Checks for:
  - top-level schema (``snoozes`` must be a list, optional ``_comment``)
  - per-entry required keys (``tf``)
  - invalid ``expires`` timestamps (not ISO / unparseable)
  - stale entries (``expires`` in the past relative to ``--now``)
  - duplicate ``(tf, family)`` pairs
  - empty string fields

Exits 0 on clean, 1 on any finding (use ``--warn-only`` to always
exit 0 for advisory CI checks). Pure stdlib.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import sys
from pathlib import Path
from typing import Any

from scripts.smc_atomic_write import atomic_write_text


def _parse_iso(ts: str) -> _dt.datetime | None:
    try:
        return _dt.datetime.fromisoformat(
            ts[:-1] + "+00:00" if ts.endswith("Z") else ts,
        )
    except (ValueError, TypeError):
        return None


def lint(
    data: dict[str, Any] | list[Any] | None,
    *,
    now: _dt.datetime | None = None,
) -> dict[str, Any]:
    findings: list[dict[str, Any]] = []
    now_ = now or _dt.datetime.now(tz=_dt.UTC)

    if not isinstance(data, dict):
        findings.append({
            "kind": "schema",
            "detail": "top-level must be an object",
        })
        return {"ok": False, "findings": findings, "counts": {"total": 1}}

    if "snoozes" not in data:
        findings.append({"kind": "schema",
                         "detail": "'snoozes' key missing"})
    entries = data.get("snoozes")
    if not isinstance(entries, list):
        findings.append({"kind": "schema",
                         "detail": "'snoozes' must be a list"})
        return {
            "ok": not findings,
            "findings": findings,
            "counts": {"total": len(findings)},
        }

    seen: dict[tuple[str, str], int] = {}
    for i, entry in enumerate(entries):
        if not isinstance(entry, dict):
            findings.append({
                "kind": "entry_shape",
                "index": i,
                "detail": "entry must be an object",
            })
            continue
        tf = entry.get("tf")
        if not tf or not isinstance(tf, str):
            findings.append({
                "kind": "missing_tf",
                "index": i,
                "detail": "'tf' is required and must be a non-empty string",
            })
            continue
        fam = entry.get("family")
        if fam is not None and (not isinstance(fam, str) or not fam):
            findings.append({
                "kind": "bad_family",
                "index": i,
                "detail": "'family' must be a non-empty string if present",
            })
        key = (tf, fam or "")
        if key in seen:
            findings.append({
                "kind": "duplicate",
                "index": i,
                "detail": f"duplicate of entry at index {seen[key]}: "
                          f"tf={tf} family={fam or '*'}",
            })
        else:
            seen[key] = i
        exp = entry.get("expires")
        if exp is not None:
            parsed = _parse_iso(exp) if isinstance(exp, str) else None
            if parsed is None:
                findings.append({
                    "kind": "bad_expires",
                    "index": i,
                    "detail": f"unparseable 'expires' value: {exp!r}",
                })
            elif parsed <= now_:
                findings.append({
                    "kind": "stale",
                    "index": i,
                    "detail": f"entry expired at {exp}",
                })
    return {
        "ok": not findings,
        "findings": findings,
        "counts": {"total": len(findings)},
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = ["# Plan 2.8 snooze lint"]
    lines.append("")
    if report["ok"]:
        lines.append("Snooze config is clean. No findings.")
        return "\n".join(lines) + "\n"
    lines.append(f"Found **{report['counts']['total']}** issues:")
    lines.append("")
    lines.append("| # | kind | detail |")
    lines.append("|--:|------|--------|")
    for i, f in enumerate(report["findings"], start=1):
        detail = f["detail"].replace("|", "\\|")
        idx = f.get("index")
        idx_s = f" (idx={idx})" if idx is not None else ""
        lines.append(f"| {i} | {f['kind']}{idx_s} | {detail} |")
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
        description="Lint configs/plan_2_8_snoozes.json.",
    )
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--format", choices=("md", "json"), default="md")
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--now", default=None)
    parser.add_argument("--warn-only", action="store_true",
                        help="Always exit 0 even on findings.")
    args = parser.parse_args(argv)

    if not args.config.exists():
        print(f"ERROR: config not found: {args.config}", file=sys.stderr)
        return 1
    try:
        data = json.loads(args.config.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"ERROR: invalid JSON: {exc}", file=sys.stderr)
        return 1

    now_ = None if args.now is None else _parse_iso(args.now)
    report = lint(data, now=now_)
    body = render_markdown(report) if args.format == "md" \
        else json.dumps(report, indent=2) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(body, args.output)
    print(body, end="")
    if not report["ok"] and not args.warn_only:
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
