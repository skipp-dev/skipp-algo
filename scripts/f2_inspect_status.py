"""F2 contextual-arm status inspector (plan §2.3 F2 + §2.4 G2 ops).

Answers the single operator question: "what is the contextual arm
doing right now, and how did it get there?"

Inputs (all optional except --spec):
  --spec             F2 experiment spec JSON.
  --revert-journal   JSONL written by scripts/f2_revert_contextual_weights.py
  --promote-journal  JSONL written by scripts/f2_promote_contextual_weights.py
  --reports-dir      Directory holding f2_promotion_gate_*.json reports.
  --output           Optional path for the JSON digest (default: stdout only).

Output: a schema-pinned JSON object describing
  * spec metadata
  * the live treatment artifact's current status (production / shadow /
    missing) plus its inline revert_history / promote_history lengths
  * the tail of each journal (action + timestamp)
  * the most recent promotion-gate report (date + decision + sprt
    terminal block)

Pure-Python, read-only, no network.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


STATUS_SCHEMA_VERSION = 1
_REPORT_RE = re.compile(r"f2_promotion_gate_(\d{4}-\d{2}-\d{2})\.json$")


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_journal_tail(path: Path | None, *, n: int = 5) -> list[dict[str, Any]]:
    if path is None or not path.exists():
        return []
    out: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out[-n:]


def _journal_summary(entries: list[dict[str, Any]]) -> dict[str, Any]:
    actions: dict[str, int] = {}
    for e in entries:
        a = str(e.get("action", "unknown"))
        actions[a] = actions.get(a, 0) + 1
    return {"len": len(entries), "actions": actions}


def _latest_report(reports_dir: Path | None) -> dict[str, Any] | None:
    if reports_dir is None or not reports_dir.exists():
        return None
    candidates: list[tuple[str, Path]] = []
    for p in reports_dir.iterdir():
        m = _REPORT_RE.search(p.name)
        if m:
            candidates.append((m.group(1), p))
    if not candidates:
        return None
    candidates.sort()
    date, path = candidates[-1]
    try:
        report = _load_json(path)
    except (json.JSONDecodeError, OSError):
        return {"date": date, "path": str(path), "decision": None, "sprt": None}
    return {
        "date": date,
        "path": str(path),
        "decision": report.get("decision"),
        "sprt": report.get("sprt"),
    }


def _artifact_status(artifact_path: Path | None) -> dict[str, Any]:
    if artifact_path is None:
        return {"path": None, "exists": False, "status": None}
    if not artifact_path.exists():
        return {"path": str(artifact_path), "exists": False, "status": None}
    try:
        artifact = _load_json(artifact_path)
    except (json.JSONDecodeError, OSError) as exc:
        return {
            "path": str(artifact_path),
            "exists": True,
            "status": None,
            "error": str(exc),
        }
    if not isinstance(artifact, dict):
        return {
            "path": str(artifact_path),
            "exists": True,
            "status": None,
            "error": "artifact is not a JSON object",
        }
    revert_hist = artifact.get("revert_history") or []
    promote_hist = artifact.get("promote_history") or []
    return {
        "path": str(artifact_path),
        "exists": True,
        "status": artifact.get("status"),
        "revert_history_len": len(revert_hist) if isinstance(revert_hist, list) else 0,
        "promote_history_len": len(promote_hist) if isinstance(promote_hist, list) else 0,
        "last_revert": revert_hist[-1] if isinstance(revert_hist, list) and revert_hist else None,
        "last_promote": promote_hist[-1] if isinstance(promote_hist, list) and promote_hist else None,
    }


def build_status(
    *,
    spec_path: Path,
    revert_journal: Path | None = None,
    promote_journal: Path | None = None,
    reports_dir: Path | None = None,
    tail_n: int = 5,
) -> dict[str, Any]:
    """Compose the operator-readable status dict."""
    if not spec_path.exists():
        raise ValueError(f"spec does not exist: {spec_path}")
    spec = _load_json(spec_path)
    if not isinstance(spec, dict):
        raise ValueError(f"spec {spec_path} must contain a JSON object")
    treatment = (spec.get("arms") or {}).get("treatment") or {}
    artifact_str = treatment.get("calibration_artifact")
    artifact_path = Path(artifact_str) if artifact_str else None

    revert_entries = _read_journal_tail(revert_journal, n=tail_n)
    promote_entries = _read_journal_tail(promote_journal, n=tail_n)

    return {
        "schema_version": STATUS_SCHEMA_VERSION,
        "spec": str(spec_path),
        "experiment": spec.get("name"),
        "artifact": _artifact_status(artifact_path),
        "revert_journal": {
            "path": str(revert_journal) if revert_journal else None,
            "tail": revert_entries,
            **_journal_summary(revert_entries),
        },
        "promote_journal": {
            "path": str(promote_journal) if promote_journal else None,
            "tail": promote_entries,
            **_journal_summary(promote_entries),
        },
        "latest_report": _latest_report(reports_dir),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Inspect the live F2 contextual arm status across spec, artifact, journals and reports."
    )
    parser.add_argument("--spec", type=Path, required=True,
                        help="Path to the F2 experiment spec JSON.")
    parser.add_argument("--revert-journal", type=Path, default=None,
                        help="Path to the revert JSONL journal.")
    parser.add_argument("--promote-journal", type=Path, default=None,
                        help="Path to the promote JSONL journal.")
    parser.add_argument("--reports-dir", type=Path, default=None,
                        help="Directory holding f2_promotion_gate_*.json reports.")
    parser.add_argument("--tail", type=int, default=5,
                        help="How many recent journal entries to include (default: 5).")
    parser.add_argument("--output", type=Path, default=None,
                        help="Optional output path for the JSON digest.")
    args = parser.parse_args(argv)

    try:
        status = build_status(
            spec_path=args.spec,
            revert_journal=args.revert_journal,
            promote_journal=args.promote_journal,
            reports_dir=args.reports_dir,
            tail_n=args.tail,
        )
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    text = json.dumps(status, indent=2)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
