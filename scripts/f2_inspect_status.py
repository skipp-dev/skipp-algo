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

from scripts.smc_atomic_write import atomic_write_text

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
        "spec_status": spec.get("status", "registered"),
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


def render_one_line(status: dict[str, Any]) -> str:
    """Compress a status dict to a single human-readable line.

    Format::

        f2[<experiment>] artifact=<status> revert=<n> promote=<n> latest=<date>:<decision>

    Designed for ``::notice`` annotations and shell pipelines. Missing
    fields render as ``?``.
    """
    experiment = status.get("experiment") or "?"
    spec_status = status.get("spec_status") or "?"
    artifact = (status.get("artifact") or {}).get("status") or "missing"
    revert_n = (status.get("revert_journal") or {}).get("len", 0)
    promote_n = (status.get("promote_journal") or {}).get("len", 0)
    latest = status.get("latest_report") or {}
    latest_str = (
        f"{latest.get('date', '?')}:{latest.get('decision', '?')}"
        if latest else "none"
    )
    return (
        f"f2[{experiment}] spec_status={spec_status} "
        f"artifact={artifact} "
        f"revert={revert_n} promote={promote_n} latest={latest_str}"
    )


def render_markdown(status: dict[str, Any]) -> str:
    """Render the status dict as a compact operator-readable Markdown
    block. Designed to be pasted into a chat thread or used as the
    ``$GITHUB_STEP_SUMMARY`` body without the surrounding fenced JSON.
    """
    lines: list[str] = []
    experiment = status.get("experiment") or "?"
    spec_status = status.get("spec_status") or "?"
    lines.append(f"# F2 contextual arm — `{experiment}`")
    lines.append("")
    if spec_status != "live":
        lines.append(
            f"> ⚠️ **spec_status = `{spec_status}`** — promote pathway is "
            "disabled by `scripts/f2_run_promotion_gate.py` and "
            "`scripts/f2_promote_contextual_weights.py`. The dual-arm "
            "deltas surfaced below are operational plumbing only and "
            "are NOT a basis for a promote decision until the frozen "
            "treatment artifact (PR #43) and paired Brier-SPRT with "
            "cross-day state (PR #44) land. See "
            "`docs/f2_contextual_promotion_decision_2026-04-21.md`."
        )
        lines.append("")

    artifact = status.get("artifact") or {}
    art_status = artifact.get("status") or "missing"
    lines.append("## Artifact")
    lines.append("")
    lines.append(f"- **status**: `{art_status}`")
    lines.append(f"- **path**: `{artifact.get('path') or '(none)'}`")
    lines.append(f"- **revert_history**: {artifact.get('revert_history_len', 0)} entries")
    lines.append(f"- **promote_history**: {artifact.get('promote_history_len', 0)} entries")
    last_revert = artifact.get("last_revert")
    if last_revert:
        lines.append(
            f"- **last revert**: `{last_revert.get('reverted_at_utc', '?')}` "
            f"from `{last_revert.get('from_status', '?')}`"
        )
    last_promote = artifact.get("last_promote")
    if last_promote:
        lines.append(
            f"- **last promote**: `{last_promote.get('promoted_at_utc', '?')}` "
            f"from `{last_promote.get('from_status', '?')}`"
        )
    lines.append("")

    for kind in ("revert_journal", "promote_journal"):
        j = status.get(kind) or {}
        lines.append(f"## {kind.replace('_', ' ').title()}")
        lines.append("")
        lines.append(f"- **path**: `{j.get('path') or '(none)'}`")
        lines.append(f"- **entries**: {j.get('len', 0)}")
        actions = j.get("actions") or {}
        if actions:
            parts = ", ".join(f"`{k}`={v}" for k, v in sorted(actions.items()))
            lines.append(f"- **actions**: {parts}")
        tail = j.get("tail") or []
        if tail:
            lines.append("- **tail**:")
            for entry in tail:
                ts = entry.get("timestamp_utc", "?")
                action = entry.get("action", "?")
                lines.append(f"  - `{ts}` — `{action}`")
        lines.append("")

    latest = status.get("latest_report")
    lines.append("## Latest promotion-gate report")
    lines.append("")
    if not latest:
        lines.append("_No reports found._")
    else:
        lines.append(f"- **date**: `{latest.get('date', '?')}`")
        lines.append(f"- **decision**: `{latest.get('decision', '?')}`")
        sprt = latest.get("sprt") or {}
        if sprt:
            lines.append(
                f"- **SPRT**: `{sprt.get('decision', '?')}` "
                f"(n={sprt.get('n', '?')}, k={sprt.get('k', '?')}, "
                f"llr={sprt.get('llr', '?')})"
            )
    lines.append("")
    return "\n".join(lines)


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
    parser.add_argument("--quiet", action="store_true",
                        help="Print a single-line summary instead of the full JSON.")
    parser.add_argument("--format", choices=["json", "md"], default="json",
                        help="Stdout format (ignored when --quiet). Default: json.")
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
        atomic_write_text(text + "\n", args.output)
    if args.quiet:
        print(render_one_line(status))
    elif args.format == "md":
        print(render_markdown(status))
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
