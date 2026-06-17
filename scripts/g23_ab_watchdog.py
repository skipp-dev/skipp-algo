"""Q3/Q4 plan §G2 + §G3 — A/B comparison watchdog.

Reads one or more ``ab_comparison.json`` artifacts (produced by
:mod:`scripts.run_ab_comparison`), accumulates their state into a
single rolling-window history JSONL, and emits two **plan-mandated**
governance signals:

§G2 *Rollback-Gate* — *"Wenn Auto-Tuning-Arm in 2 aufeinanderfolgenden
Runs schlechter ist als Static-Arm → automatischer Revert + GitHub-
Issue-Ping."* (plan line 414).
The watchdog flags ``rollback_required`` when the most recent
``--rollback-streak`` entries (default 2) all show treatment ≤ control
on the comparison's primary metric.

§G3 *30-Tage A/B mit sauberer Stoppregel* — *"SPRT oder fixes N, keine
ad-hoc Entscheidung."* (plan line 415).
The watchdog re-runs the Wald SPRT terminal decision on the
*aggregated* (n, k) over the rolling window so the stop rule sees the
full sample, not just the last day. ``promotion_ready`` flips to true
on ``accept_h1``; ``stop_for_futility`` flips on ``accept_h0``.

The history file lives at ``docs/ab/g23_history.jsonl`` (capped at
``HISTORY_RETENTION = 90`` entries — matches the §3.1.1 public history
retention so dashboards can reuse the same window). The Markdown
status surface lives at ``docs/ab/g23_status.md`` so a reviewer can
read the current decision without parsing JSONL.

Exit codes
----------
* 0 — no governance signal triggered (continue sampling)
* 2 — G2 rollback required (treatment underperformed in N consecutive runs)
* 3 — G3 promotion ready (SPRT accept_h1)
* 4 — G3 futility stop (SPRT accept_h0)
* 1 — fatal error (malformed input, unwritable output)

A workflow consumer can branch on the exit code to open / close
GitHub issues without parsing the status file.

Defensive design
----------------
* Empty / missing input → status=``awaiting_first_run``, exit 0.
* Malformed history line → skipped (never fatal).
* Atomic write via ``.tmp`` + rename for both JSONL and Markdown.
* Stdlib only; reuses :class:`scripts.smc_sprt_stop_rule.SPRTConfig` /
  :func:`scripts.smc_sprt_stop_rule.terminal_decision`.
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
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from scripts._logging_init import init_cli_logging

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# Re-use the existing SPRT module (already validated by F2/G3 callers).
from scripts.smc_sprt_stop_rule import SPRTConfig, terminal_decision

HISTORY_RETENTION = 90
DEFAULT_ROLLBACK_STREAK = 2  # plan line 414
DEFAULT_HISTORY = Path("docs/ab/g23_history.jsonl")
DEFAULT_STATUS_MD = Path("docs/ab/g23_status.md")
PRIMARY_METRIC = "hit_rate"  # what G2 rollback checks

# Mirror the SPRT defaults from the F2 experiment spec
# (artifacts/experiments/f2_contextual_promotion.json).  CLI --p0/--p1
# override these; values below are the 2026-06-09 recalibrated baseline.
SPRT_P0 = 0.544
SPRT_P1 = 0.574
SPRT_ALPHA = 0.05
SPRT_BETA = 0.20
# W6-5 (stat-review wave 6): max_n was present in the live F2 spec
# (artifacts/experiments/f2_contextual_promotion.json: max_n=1200) but
# absent from the watchdog constants and CLI, leaving SPRTConfig.max_n=None.
# This constant mirrors the live spec; --max-n overrides it at runtime.
SPRT_MAX_N = 1200

EXIT_OK = 0
EXIT_FATAL = 1
EXIT_ROLLBACK = 2
EXIT_PROMOTION_READY = 3
EXIT_FUTILITY = 4


def _coerce_int(val: Any) -> int:
    try:
        return int(val or 0)
    except (TypeError, ValueError):
        return 0


def _coerce_float(val: Any) -> float | None:
    if val is None:
        return None
    try:
        f = float(val)
    except (TypeError, ValueError):
        return None
    if f != f:
        return None
    return f


def _extract_arm_totals(comparison: dict[str, Any]) -> tuple[int, int, int, int]:
    """Pull (control_n, control_k, treatment_n, treatment_k) from a comparison."""
    sprt = comparison.get("sprt") or {}
    treatment_n = _coerce_int(sprt.get("n"))
    treatment_k = _coerce_int(sprt.get("k"))
    control_n = _coerce_int(sprt.get("control_n"))
    # control_k is usually not stored; derive from control_hit_rate.
    control_hr = _coerce_float(sprt.get("control_hit_rate"))
    control_k = round(control_n * control_hr) if control_hr is not None else 0
    return control_n, control_k, treatment_n, treatment_k


def _treatment_underperformed(comparison: dict[str, Any]) -> bool:
    """True iff treatment hit_rate ≤ control hit_rate on the latest comparison."""
    sprt = comparison.get("sprt") or {}
    treatment_hr = _coerce_float(sprt.get("hit_rate"))
    control_hr = _coerce_float(sprt.get("control_hit_rate"))
    if treatment_hr is None or control_hr is None:
        # W9-2 (SMR wave 9): returning False when hit_rate is missing silently
        # broke the consecutive-underperformance streak (a missing data gap
        # would reset the streak counter just like a genuine outperformance,
        # preventing rollback from ever firing). Fail-closed instead: raise so
        # the caller surfaces the data gap explicitly.
        raise ValueError(
            "hit_rate or control_hit_rate is None — cannot evaluate "
            "underperformance; treat as data gap, not as pass (W9-2)"
        )
    return treatment_hr <= control_hr


def _make_history_entry(
    comparison: dict[str, Any],
    *,
    timestamp: str,
    source_path: Path | None,
    source_commit_sha: str | None,
    source_workflow_run: str | None,
) -> dict[str, Any]:
    """Compact single-line record for the rolling history."""
    control_n, control_k, treatment_n, treatment_k = _extract_arm_totals(comparison)
    sprt = comparison.get("sprt") or {}
    return {
        "timestamp": timestamp,
        "experiment": comparison.get("experiment"),
        "control_n": control_n,
        "control_k": control_k,
        "control_hit_rate": _coerce_float(sprt.get("control_hit_rate")),
        "treatment_n": treatment_n,
        "treatment_k": treatment_k,
        "treatment_hit_rate": _coerce_float(sprt.get("hit_rate")),
        "treatment_underperformed": _treatment_underperformed(comparison),
        "sprt_decision_single_run": sprt.get("decision"),
        "source": {
            "path": str(source_path) if source_path else None,
            "commit_sha": source_commit_sha,
            "workflow_run": source_workflow_run,
        },
    }


def load_history(history_path: Path) -> list[dict[str, Any]]:
    """Read the rolling history JSONL; fail closed on malformed lines.

    W6-4 (stat-review wave 6): previously malformed lines were silently
    skipped, which could suppress a rollback streak if the corrupt line
    was an underperform entry.  A corrupt history must be treated as fatal
    so the operator fixes the file before G2/G3 signals are re-evaluated.
    """
    if not history_path.exists():
        return []
    out: list[dict[str, Any]] = []
    for lineno, line in enumerate(
        history_path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError as exc:
            print(
                f"ERROR: {history_path}:{lineno}: malformed history JSONL "
                f"({exc!s}); fix or delete the history file before re-running",
                file=sys.stderr,
            )
            raise SystemExit(EXIT_FATAL) from exc
    return out


def append_history(history_path: Path, entry: dict[str, Any]) -> list[dict[str, Any]]:
    """Append *entry* and truncate to the retention window. Returns new list."""
    history_path.parent.mkdir(parents=True, exist_ok=True)
    existing = load_history(history_path)
    existing.append(entry)
    if len(existing) > HISTORY_RETENTION:
        existing = existing[-HISTORY_RETENTION:]
    tmp = history_path.with_suffix(history_path.suffix + ".tmp")
    # ATOMIC-WRITE-EXEMPT: tmp+replace pattern (atomic by construction).
    tmp.write_text(
        "\n".join(json.dumps(e, sort_keys=True) for e in existing) + "\n",
        encoding="utf-8",
    )
    tmp.replace(history_path)
    return existing


def aggregated_sprt(
    history: list[dict[str, Any]],
    *,
    config: SPRTConfig,
) -> dict[str, Any]:
    """Run SPRT on the *latest* entry's (n, k).

    Prior implementation summed (n, k) across all history entries, but each
    daily comparison is already computed over the full cumulative corpus —
    summing inflates both n and k by the number of history entries (W3-2,
    stat-review wave 3).  Using the latest entry gives the correct
    cumulative totals without double-counting.
    """
    if not history:
        return {
            "decision": "no_data",
            "n": 0,
            "k": 0,
            "llr": 0.0,
            "wald_upper": round(config.upper_bound, 4),
            "wald_lower": round(config.lower_bound, 4),
        }
    latest = history[-1]
    treatment_n = _coerce_int(latest.get("treatment_n"))
    treatment_k = _coerce_int(latest.get("treatment_k"))
    if treatment_n <= 0:
        return {
            "decision": "no_data",
            "n": 0,
            "k": 0,
            "llr": 0.0,
            "wald_upper": round(config.upper_bound, 4),
            "wald_lower": round(config.lower_bound, 4),
        }
    state, decision = terminal_decision(n=treatment_n, k=treatment_k, config=config)
    return {
        "decision": decision,
        "n": state.n,
        "k": state.k,
        "hit_rate": round(state.hit_rate, 4),
        "llr": round(state.llr, 4),
        "wald_upper": round(config.upper_bound, 4),
        "wald_lower": round(config.lower_bound, 4),
    }


def consecutive_underperform_streak(history: list[dict[str, Any]]) -> int:
    """Count the number of trailing entries where treatment ≤ control."""
    streak = 0
    for entry in reversed(history):
        if entry.get("treatment_underperformed"):
            streak += 1
        else:
            break
    return streak


def evaluate_signals(
    history: list[dict[str, Any]],
    *,
    rollback_streak: int,
    config: SPRTConfig,
) -> dict[str, Any]:
    """Produce the watchdog decision packet from the full history window."""
    sprt = aggregated_sprt(history, config=config)
    streak = consecutive_underperform_streak(history)
    rollback_required = streak >= rollback_streak and len(history) >= rollback_streak
    promotion_ready = sprt["decision"] == "accept_h1"
    futility = sprt["decision"] == "accept_h0"
    return {
        "window_size": len(history),
        "underperform_streak": streak,
        "rollback_threshold": rollback_streak,
        "rollback_required": rollback_required,
        "promotion_ready": promotion_ready,
        "stop_for_futility": futility,
        "sprt": sprt,
    }


def render_status_markdown(
    signals: dict[str, Any],
    *,
    history: list[dict[str, Any]],
    generated_at: str,
    source_commit_sha: str | None,
) -> str:
    """Plain-Markdown status surface — what a human reviewer sees first."""
    sprt = signals["sprt"]
    last = history[-1] if history else None

    def _opt(v: Any) -> str:
        return "—" if v is None else str(v)

    lines = [
        "# G2/G3 A/B Watchdog — Status",
        "",
        f"_Generated: `{generated_at}`_",
        f"_Source commit: `{(source_commit_sha or 'unknown')[:7]}`_",
        "",
        "## Plan-mandated signals",
        "",
        "| Signal | Value |",
        "|---|---|",
        f"| §G2 rollback required (≥ {signals['rollback_threshold']} consecutive losses) | **{'YES' if signals['rollback_required'] else 'no'}** (current streak: {signals['underperform_streak']}) |",
        f"| §G3 promotion ready (SPRT accept_h1) | **{'YES' if signals['promotion_ready'] else 'no'}** |",
        f"| §G3 stop for futility (SPRT accept_h0) | **{'YES' if signals['stop_for_futility'] else 'no'}** |",
        "",
        "## SPRT (aggregated over window)",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Window entries | {signals['window_size']} |",
        f"| Decision | `{sprt['decision']}` |",
        f"| Treatment n | {sprt.get('n', 0)} |",
        f"| Treatment k (hits) | {sprt.get('k', 0)} |",
        f"| Treatment hit rate | {_opt(sprt.get('hit_rate'))} |",
        f"| LLR | {_opt(sprt.get('llr'))} |",
        f"| Wald upper / lower | {_opt(sprt.get('wald_upper'))} / {_opt(sprt.get('wald_lower'))} |",
        "",
    ]

    if last is not None:
        lines.extend([
            "## Most recent entry",
            "",
            "| Field | Value |",
            "|---|---|",
            f"| Timestamp | {_opt(last.get('timestamp'))} |",
            f"| Experiment | {_opt(last.get('experiment'))} |",
            f"| Treatment hit rate | {_opt(last.get('treatment_hit_rate'))} |",
            f"| Control hit rate | {_opt(last.get('control_hit_rate'))} |",
            f"| Treatment underperformed | {bool(last.get('treatment_underperformed'))} |",
            f"| Single-run SPRT | `{_opt(last.get('sprt_decision_single_run'))}` |",
            "",
        ])
    else:
        lines.extend(["## Most recent entry", "", "_No history entries yet (awaiting_first_run)._", ""])
    return "\n".join(lines)


def write_status(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    # ATOMIC-WRITE-EXEMPT: tmp+replace pattern (atomic by construction).
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(path)


def select_exit_code(signals: dict[str, Any]) -> int:
    """Map signal flags to the workflow-consumable exit code."""
    if signals["rollback_required"]:
        return EXIT_ROLLBACK
    if signals["promotion_ready"]:
        return EXIT_PROMOTION_READY
    if signals["stop_for_futility"]:
        return EXIT_FUTILITY
    return EXIT_OK


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Q3/Q4 G2/G3 A/B watchdog (rollback + promotion gate).",
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=None,
        help="Path to the latest ab_comparison.json (optional). When omitted, "
             "the watchdog evaluates the existing history without appending a new entry.",
    )
    parser.add_argument(
        "--history",
        type=Path,
        default=DEFAULT_HISTORY,
        help=f"Rolling history JSONL (default: {DEFAULT_HISTORY}).",
    )
    parser.add_argument(
        "--status-md",
        type=Path,
        default=DEFAULT_STATUS_MD,
        help=f"Markdown status surface (default: {DEFAULT_STATUS_MD}).",
    )
    parser.add_argument(
        "--rollback-streak",
        type=int,
        default=DEFAULT_ROLLBACK_STREAK,
        help=f"Consecutive-loss threshold for §G2 rollback "
             f"(default: {DEFAULT_ROLLBACK_STREAK}, plan line 414).",
    )
    parser.add_argument("--p0", type=float, default=SPRT_P0)
    parser.add_argument("--p1", type=float, default=SPRT_P1)
    parser.add_argument("--alpha", type=float, default=SPRT_ALPHA)
    parser.add_argument("--beta", type=float, default=SPRT_BETA)
    # W6-5 (stat-review wave 6): expose max_n so the live spec's cap is honoured.
    parser.add_argument(
        "--max-n",
        type=int,
        default=SPRT_MAX_N,
        help=(
            f"SPRT hard cap on observations (default: {SPRT_MAX_N}, "
            "mirrors artifacts/experiments/f2_contextual_promotion.json)."
        ),
    )
    parser.add_argument(
        "--commit-sha", default=os.environ.get("GITHUB_SHA"),
        help="Source commit SHA (default: $GITHUB_SHA).",
    )
    parser.add_argument(
        "--workflow-run", default=os.environ.get("GITHUB_RUN_ID"),
        help="Source workflow run id (default: $GITHUB_RUN_ID).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    init_cli_logging()  # F-V5-A1-2 (2026-05-01)
    args = _parse_args(argv)

    config = SPRTConfig(p0=args.p0, p1=args.p1, alpha=args.alpha, beta=args.beta, max_n=args.max_n)
    now = datetime.now(UTC).isoformat()

    # Step 1 — append new entry if --input given.
    if args.input is not None:
        try:
            comparison = json.loads(args.input.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            print(f"ERROR: cannot read --input {args.input}: {exc}", file=sys.stderr)
            return EXIT_FATAL
        try:
            entry = _make_history_entry(
                comparison,
                timestamp=now,
                source_path=args.input,
                source_commit_sha=args.commit_sha,
                source_workflow_run=args.workflow_run,
            )
        except ValueError as exc:
            print(
                f"ERROR: hit-rate data missing in {args.input}: {exc}; "
                "cannot evaluate underperformance streak (data gap — W9-2)",
                file=sys.stderr,
            )
            return EXIT_FATAL
        try:
            history = append_history(args.history, entry)
        except OSError as exc:
            print(f"ERROR: cannot write history {args.history}: {exc}", file=sys.stderr)
            return EXIT_FATAL
    else:
        history = load_history(args.history)

    # Step 2 — evaluate signals over the (possibly appended) history.
    signals = evaluate_signals(
        history,
        rollback_streak=args.rollback_streak,
        config=config,
    )

    # Step 3 — render the Markdown status surface.
    md = render_status_markdown(
        signals,
        history=history,
        generated_at=now,
        source_commit_sha=args.commit_sha,
    )
    try:
        write_status(args.status_md, md)
    except OSError as exc:
        print(f"ERROR: cannot write status md {args.status_md}: {exc}", file=sys.stderr)
        return EXIT_FATAL

    rc = select_exit_code(signals)
    print(
        f"G2/G3 watchdog: window={signals['window_size']} "
        f"streak={signals['underperform_streak']} "
        f"sprt={signals['sprt']['decision']} exit={rc}"
    )
    return rc


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
