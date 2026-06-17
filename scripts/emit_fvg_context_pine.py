"""Q3/Q4 plan §D2 — FVG per-Context Pine emitter (writer side).

Walks one or more event-ledger directories (``events_<sym>_<tf>.jsonl``,
written by :mod:`smc_core.event_ledger`), pulls the FVG-only records,
normalises their ``session`` / ``htf_bias`` / ``vol_regime`` / ``hit``
fields, then runs them through:

* :func:`smc_core.benchmark.stratified_fvg_report` — tri-axis bucketing
  with a per-bucket ``min_events`` floor (defaults to 12 per the plan),
  and
* :func:`smc_core.fvg_pine_emit.emit_fvg_pine_constants` — deterministic
  Pine ``export const string`` declarations.

The output is written atomically to a tracked Pine snippet file
(default: ``pine/generated/fvg_context_health.pine``) that the
``SMC_Dashboard.pine`` ``FVG Status`` row can read once the dashboard
wiring is added in a follow-up PR (touching the ~1865-line dashboard
needs its own TradingView compile-only preflight cycle).

The script is **defensive on missing inputs**: with no ledger files
discovered (or every bucket below the floor), it writes a deterministic
``status: awaiting_first_run`` Pine stub instead of failing — so the
scheduled CI workflow stays green on a clean checkout and the dashboard
gracefully shows "insufficient" cells until enough live data accumulates.

Outputs:
* ``pine/generated/fvg_context_health.pine`` — the Pine snippet, with
  a leading status comment (``// FVG_CONTEXT_HEALTH_STATUS = "ok" |
  "awaiting_first_run"``) so a human / Pine consumer can branch on it.
* ``pine/generated/fvg_context_health.json`` — the source-of-truth
  JSON snapshot of the underlying ``stratified_fvg_report`` so reviewers
  can audit the numbers without re-running the script.

Exit codes:
* 0 — Pine snippet written (even when the corpus was empty)
* 1 — fatal error (cannot write output, malformed ledger record)
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# F-V5-A1-2 / F-CI-O1 (2026-05-01) + F-V?-? (2026-05-03): bootstrap repo
# root onto sys.path BEFORE the first-party `from scripts._logging_init`
# import so this file works under both `python -m scripts.X` and
# `python scripts/X.py`. The unconditional `sys.path.insert` (literal
# `sys` name, NOT an alias) also satisfies
# tests/test_workflow_invoked_scripts_import_order.py which detects
# the mutation via AST chain `sys.path.insert` — aliased forms
# (`_v5a12_sys.path.insert`) are not detected and were considered
# late-bootstrap, flagging the early bootstrap import as out-of-order.
import os as _bootstrap_os
import sys as _bootstrap_sys_mod

sys = _bootstrap_sys_mod

_BOOTSTRAP_ROOT = _bootstrap_os.path.dirname(_bootstrap_os.path.dirname(_bootstrap_os.path.abspath(__file__)))
if _BOOTSTRAP_ROOT not in sys.path:
    sys.path.insert(0, _BOOTSTRAP_ROOT)

import argparse
import json
import os
import sys
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from scripts._logging_init import init_cli_logging

# --- Path bootstrap so the script works both as `-m` and as a file ---
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from smc_core.benchmark import stratified_fvg_report
from smc_core.event_ledger import read_event_ledger
from smc_core.fvg_pine_emit import emit_fvg_pine_constants

PINE_HEADER = "//@version=6"
PINE_STATUS_KEY = "FVG_CONTEXT_HEALTH_STATUS"
DEFAULT_OUTPUT = Path("pine/generated/fvg_context_health.pine")
DEFAULT_JSON_SIDECAR_SUFFIX = ".json"
DEFAULT_SEARCH_DIR = Path("artifacts/reports")
LEDGER_GLOB = "events_*_*.jsonl"
DEFAULT_MIN_EVENTS = 12  # plan §D2 floor


def _discover_ledger_paths(search_dir: Path) -> list[Path]:
    """Return all ``events_<sym>_<tf>.jsonl`` files under *search_dir*.

    Returns an empty list when the directory is missing — the caller
    treats that as the ``awaiting_first_run`` case.
    """
    if not search_dir.is_dir():
        return []
    return sorted(search_dir.rglob(LEDGER_GLOB))


def _normalise_event(record: dict[str, Any]) -> dict[str, Any] | None:
    """Pull the four fields :func:`stratified_fvg_report` needs.

    The ledger writer puts context fields under either the top level
    or under a nested ``context`` block depending on the producer
    version — we accept either source so the script keeps working as
    enrichers migrate.

    Returns ``None`` only when the record cannot supply a usable
    ``hit`` flag (anything else falls back to ``"UNKNOWN"`` — matching
    :func:`stratified_fvg_report`'s own defensive policy).
    """
    if not isinstance(record, dict):
        return None
    if record.get("family") != "FVG":
        return None

    context = record.get("context") or {}
    if not isinstance(context, dict):
        context = {}

    def _ctx_value(key: str) -> Any:
        if key in record:
            return record[key]
        return context.get(key)

    hit_raw = record.get("hit")
    if hit_raw is None:
        # Some ledger versions tuck the outcome under ``outcome`` or
        # ``label_outcome`` — best-effort only; if we still can't find
        # a hit signal, drop the record rather than guessing.
        for alt in ("outcome", "label_outcome"):
            if alt in record:
                hit_raw = record[alt]
                break
    if hit_raw is None:
        return None

    return {
        "hit": bool(hit_raw),
        "session": _ctx_value("session"),
        "htf_bias": _ctx_value("htf_bias"),
        "vol_regime": _ctx_value("vol_regime"),
    }


def collect_fvg_events(ledger_paths: Iterable[Path]) -> list[dict[str, Any]]:
    """Read all FVG records from the supplied ledgers, normalised."""
    events: list[dict[str, Any]] = []
    for path in ledger_paths:
        for record in read_event_ledger(path):
            normalised = _normalise_event(record)
            if normalised is not None:
                events.append(normalised)
    return events


def build_pine_snippet(
    report: dict[str, Any] | None,
    *,
    generated_at: str,
    source_commit_sha: str | None,
    source_workflow_run: str | None,
    ledger_count: int,
) -> str:
    """Render the deterministic Pine snippet for *report*.

    A ``None`` (or empty) report yields an ``awaiting_first_run`` stub
    that still parses as Pine and exposes a single status string the
    dashboard can branch on.
    """
    status = "ok"
    total_events = 0
    if report is None or report.get("total_events", 0) == 0:
        status = "awaiting_first_run"
    else:
        total_events = int(report.get("total_events", 0) or 0)

    header_lines = [
        PINE_HEADER,
        '// AUTOGENERATED by scripts/emit_fvg_context_pine.py — DO NOT EDIT BY HAND.',
        '// Q3/Q4 plan §D2 — FVG per-Context health snapshot for SMC_Dashboard.pine.',
        f"// generated_at: {generated_at}",
        f"// source_commit_sha: {source_commit_sha or 'unknown'}",
        f"// source_workflow_run: {source_workflow_run or 'unknown'}",
        f"// ledger_files_consumed: {ledger_count}",
        f"// total_events: {total_events}",
        '',
        f'export const string {PINE_STATUS_KEY} = "{status}"',
    ]

    if status == "awaiting_first_run":
        header_lines.extend([
            '',
            '// No FVG events available yet — the FVG Status row should show',
            '// "insufficient" cells until the first scheduled benchmark run',
            '// populates this file.',
        ])
        return "\n".join(header_lines) + "\n"

    body_lines = emit_fvg_pine_constants(report)
    return "\n".join([*header_lines, '', *body_lines]) + "\n"


def write_outputs(
    snippet: str,
    report: dict[str, Any] | None,
    output_path: Path,
) -> Path:
    """Atomically write the Pine snippet + a JSON sidecar.

    The sidecar lives next to *output_path* with a ``.json`` suffix
    (e.g. ``pine/generated/fvg_context_health.json``) so reviewers can
    audit the underlying tri-axis report without re-running the script.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = output_path.with_suffix(output_path.suffix + ".tmp")
    # ATOMIC-WRITE-EXEMPT: tmp+replace pattern (atomic by construction).
    tmp_path.write_text(snippet, encoding="utf-8")
    tmp_path.replace(output_path)

    sidecar_path = output_path.with_suffix(DEFAULT_JSON_SIDECAR_SUFFIX)
    sidecar_payload = report if report is not None else {"status": "awaiting_first_run"}
    tmp_sidecar = sidecar_path.with_suffix(sidecar_path.suffix + ".tmp")
    # ATOMIC-WRITE-EXEMPT: tmp+replace pattern (atomic by construction).
    tmp_sidecar.write_text(
        json.dumps(sidecar_payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    tmp_sidecar.replace(sidecar_path)
    return sidecar_path


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Emit pine/generated/fvg_context_health.pine (Q3/Q4 §D2).",
    )
    parser.add_argument(
        "--ledger",
        type=Path,
        action="append",
        default=None,
        help="Explicit JSONL ledger path (repeatable). Overrides --search-dir.",
    )
    parser.add_argument(
        "--search-dir",
        type=Path,
        default=DEFAULT_SEARCH_DIR,
        help=f"Directory to scan for {LEDGER_GLOB} when --ledger is omitted "
             f"(default: {DEFAULT_SEARCH_DIR}).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"Destination Pine file (default: {DEFAULT_OUTPUT}).",
    )
    parser.add_argument(
        "--min-events",
        type=int,
        default=DEFAULT_MIN_EVENTS,
        help="Per-bucket floor; below this the bucket renders as 'insufficient'. "
             f"Default: {DEFAULT_MIN_EVENTS} (plan §D2).",
    )
    parser.add_argument(
        "--commit-sha",
        default=os.environ.get("GITHUB_SHA"),
        help="Source commit SHA (default: $GITHUB_SHA).",
    )
    parser.add_argument(
        "--workflow-run",
        default=os.environ.get("GITHUB_RUN_ID"),
        help="Source workflow run id (default: $GITHUB_RUN_ID).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    init_cli_logging()  # F-V5-A1-2 (2026-05-01)
    args = _parse_args(argv)

    ledger_paths: list[Path]
    ledger_paths = [Path(p) for p in args.ledger] if args.ledger else _discover_ledger_paths(args.search_dir)

    try:
        events = collect_fvg_events(ledger_paths)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"ERROR: cannot read ledger input: {exc}", file=sys.stderr)
        return 1

    report = stratified_fvg_report(events, min_events=args.min_events) if events else None

    snippet = build_pine_snippet(
        report,
        generated_at=datetime.now(UTC).isoformat(),
        source_commit_sha=args.commit_sha,
        source_workflow_run=args.workflow_run,
        ledger_count=len(ledger_paths),
    )

    try:
        sidecar = write_outputs(snippet, report, args.output)
    except OSError as exc:
        print(f"ERROR: cannot write Pine snippet to {args.output}: {exc}", file=sys.stderr)
        return 1

    n_events = report.get("total_events", 0) if report else 0
    n_actionable = report.get("actionable_bucket_count", 0) if report else 0
    print(
        f"FVG context Pine snippet: ledgers={len(ledger_paths)} events={n_events} "
        f"actionable_buckets={n_actionable} pine={args.output} sidecar={sidecar}"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        logger.warning("Interrupted by user (SIGINT/KeyboardInterrupt).")
        raise SystemExit(130) from None
    except SystemExit:
        raise
    except Exception:
        logger.critical("Fatal error in %s", __name__, exc_info=True)
        raise SystemExit(1) from None
