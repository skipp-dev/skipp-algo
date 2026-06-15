"""C8/T3 — Live-incubation orchestrator with audit log.

Orchestrates one round of the Phase-B live-incubation pipeline:

1. Load SMC setup records from the latest calibration run.
2. Filter to variants whose track-record-gate verdict is **green** or
   **amber** (red is blocked from live exposure).
3. Build IBKR order intents via the Phase-B-safe adapter
   (``scripts.smc_to_ibkr_adapter``).
4. Apply the live risk limits (``scripts.live_risk_limits``) — if the
   kill-switch fires, emit a single ``halted`` audit record and return
   without submitting any orders.
5. Hand the surviving intents to a caller-supplied ``submit_fn``
   (defaulting to a paper-mode no-op so the runner is safe to invoke
   from CI or a unit test).
6. Append one JSONL audit record per intent.

Design constraints
------------------

* **No IBKR client import at module load time.** The submit function is
  injected so this module can be imported and tested in any
  environment, including the CI sandbox without ``ibapi``.
* **Atomic JSONL append.** The audit file is rewritten atomically
  (temp-file + replace) so a crash mid-run never leaves the audit log
  half-written. Partial-write streaming is intentionally avoided here:
  the per-run record count is small (≤ a few dozen) so a full rewrite
  is both simpler and safer.
* **Deterministic for fixed inputs.** Audit timestamps are pulled from
  a caller-injected clock so the runner can be exercised with snapshot
  tests.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import tempfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
from pathlib import Path
from types import MappingProxyType
from typing import Any

from scripts.execute_ibkr_watchlist import (
    IBKRConnectionConfig,
    IBKROrderIntent,
    place_order_intents,
)
from scripts.execute_ibkr_watchlist import (
    IBKRExecutionConfig as IBKRWatchlistExecutionConfig,
)
from scripts.live_risk_limits import (
    AccountState,
    KillSwitchDecision,
    RiskLimits,
    check_risk_limits,
)
from scripts.smc_to_ibkr_adapter import (
    PHASE_B_RECOMMENDED_SIZE_SCALE,
    IBKRExecutionConfig,
    build_ibkr_intents_from_smc_setups,
)
from smc_integration.earnings_filter import (
    EarningsFilter,
    EarningsFilterDecision,
)

logger = logging.getLogger("scripts.run_smc_live_incubation")

# Track-record-gate verdicts that are allowed to trade live.
_LIVE_TRADABLE_GATE_STATUSES = frozenset({"green", "amber"})

# CLI phase → size_scale default mapping.
_PHASE_DEFAULTS: dict[str, dict[str, Any]] = {
    "paper": {"size_scale": PHASE_B_RECOMMENDED_SIZE_SCALE, "paper_mode": True},
    "live_small": {"size_scale": PHASE_B_RECOMMENDED_SIZE_SCALE, "paper_mode": False},
    "live_full": {"size_scale": 1.0, "paper_mode": False},
}


# ---------------------------------------------------------------------------
# Phase-promotion pass criteria — code-level mirror of
# ``docs/c8_live_incubation_runbook.md`` so the runbook table and the
# code stay in sync.
#
# Promotion remains **manual sign-off only** (no auto-promotion) per
# the runbook contract. These constants merely make the criteria
# machine-checkable: ``tests/test_c8_phase_criteria_runbook_mirror.py``
# parses the runbook markdown and asserts each numeric threshold here
# matches the documented value.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PhasePassCriteria:
    """Numeric thresholds gating *manual* promotion to the next phase.

    All fields are advisory checklists rather than gates; the human
    sign-off is the gate. ``None`` means "no numeric threshold for this
    phase" (e.g. Phase-C sizing is decided by the future Scale-Phase
    backlog).
    """

    phase: str
    min_phase_days: int
    min_trades_closed: int
    max_drift_score_deviation: float | None
    min_drift_score: float | None
    require_drift_verdict_in: tuple[str, ...]
    extra: tuple[str, ...] = ()


# Phase-A — Paper (4 weeks minimum). Runbook §"Phase-A — Paper".
PHASE_A_CRITERIA = PhasePassCriteria(
    phase="paper",
    min_phase_days=28,
    # W9-8 (SMR wave 9): 20 trades gives <9% statistical power to
    # distinguish p=0.544 (null) from p=0.574 (alternative) at α=0.05
    # (one-sided binomial test). A power analysis targeting 80% power
    # at the same effect-size requires n≥45. Raised from 20 → 45.
    min_trades_closed=45,
    max_drift_score_deviation=0.30,
    min_drift_score=0.70,
    require_drift_verdict_in=("pass", "acceptable"),
    extra=(
        "slippage_ks_pvalue_gt_0.05",
        "hit_rate_inside_c3_bootstrap_ci",
        # Stat-review S1 (#2674): the watchdog stack (green/yellow/red via
        # 4-detector consensus in scripts/drift_alert.py) and the
        # incubation drift stack (pass/acceptable/... via drift_score)
        # were previously unreconciled — a variant could machine-pass
        # Phase-A while the watchdog stood RED (stable mean, blown-out
        # tails). This criterion forces the watchdog's aggregate
        # severity into the promotion gate.
        "watchdog_status_not_red",
    ),
)

# Phase-B — Live Small (3-6 months). Runbook §"Phase-B — Live Small".
PHASE_B_CRITERIA = PhasePassCriteria(
    phase="live_small",
    min_phase_days=90,
    min_trades_closed=30,
    max_drift_score_deviation=None,
    min_drift_score=0.50,
    require_drift_verdict_in=("pass", "acceptable"),
    extra=(
        "kill_switch_never_fired",
        "max_dd_live_lt_2x_backtest",
        # C-sprint deep-review MAJOR fix: code-mirror of the runbook
        # contract that ``synthetic_normal`` slippage references are
        # acceptable for Phase-A only and **must** be replaced by
        # ``backtest_samples`` before Phase-B sign-off. Without this
        # mirror, a drift report with ``slippage_ks_reference_type=
        # synthetic_normal`` would not show up in the machine-checkable
        # promotion criteria — only in the runbook prose. See
        # ``compute_live_drift.py`` boundary comment and
        # ``docs/c8_live_incubation_runbook.md`` §"Phase-B — Live Small".
        "slippage_ks_reference_backtest_samples",
        # Watchdog window-coverage gate is also a documented Phase-B
        # criterion ("``window_complete: true`` on the watchdog report").
        # Mirrored here so the runbook-mirror test can pin it.
        "drift_window_complete",
        # Stat-review S1 (#2674): see Phase-A comment — the watchdog
        # aggregate severity must also gate Phase-B promotion.
        "watchdog_status_not_red",
    ),
)

# Phase-C — Live Full. Promotion criteria intentionally absent —
# Kelly-style sizing is tracked under the Scale-Phase backlog and
# requires fresh sign-off whenever the scale fraction changes.
PHASE_C_CRITERIA = PhasePassCriteria(
    phase="live_full",
    min_phase_days=0,
    min_trades_closed=0,
    max_drift_score_deviation=None,
    min_drift_score=None,
    require_drift_verdict_in=(),
    extra=("scale_phase_backlog_owns_kelly_sizing",),
)


PHASE_PASS_CRITERIA: Mapping[str, PhasePassCriteria] = MappingProxyType(
    {
        PHASE_A_CRITERIA.phase: PHASE_A_CRITERIA,
        PHASE_B_CRITERIA.phase: PHASE_B_CRITERIA,
        PHASE_C_CRITERIA.phase: PHASE_C_CRITERIA,
    }
)


SubmitFn = Callable[[Sequence[IBKROrderIntent]], list[dict[str, Any]]]


def _no_op_submit(intents: Sequence[IBKROrderIntent]) -> list[dict[str, Any]]:
    """Default submitter: record an ``audit_only`` action per intent.

    Used for paper-mode dry-runs and tests; no orders are transmitted.
    Pass ``--place-paper-orders`` to swap in :func:`_build_paper_submit_fn`,
    which actually transmits bracket orders to the IBKR *paper* TWS once a
    session is available.
    """
    return [
        {"intent_id": intent.order_ref, "action": "audit_only"} for intent in intents
    ]


def _build_paper_submit_fn(
    *,
    connection_cfg: IBKRConnectionConfig,
    execution_cfg: IBKRWatchlistExecutionConfig,
    place_fn: Callable[..., dict[str, Any]] | None = None,
) -> SubmitFn:
    """Build an opt-in submitter that transmits orders to the IBKR *paper* TWS.

    Wired only by ``--place-paper-orders`` (default off). The returned
    closure delegates to
    :func:`scripts.execute_ibkr_watchlist.place_order_intents`, which
    connects to the paper port, enforces the ``DU*`` paper-account guard
    (``assert_paper_account_if_paper_port``) *before* any order is
    transmitted, places the bracket orders, then disconnects. A live TWS
    bound to the paper port makes that guard fail loud, so this path can
    never reach a real-money account.

    The rich placement result is collapsed into the per-intent audit shape
    the orchestrator consumes (``intent_id`` / ``action`` / ``fill_price``).
    Bracket orders are not synchronously filled, so ``fill_price`` is left
    ``None`` at submit time and reconciliation is left to the executor.

    ``place_fn`` is injectable so tests can exercise the wiring without a
    live TWS session. It is resolved at call time (not captured as a
    default argument) so that monkeypatching
    ``scripts.run_smc_live_incubation.place_order_intents`` reliably
    intercepts the real transmit path.
    """

    def _paper_submit(intents: Sequence[IBKROrderIntent]) -> list[dict[str, Any]]:
        if not intents:
            return []
        submit = place_fn if place_fn is not None else place_order_intents
        placements_total = 0
        for intent in intents:
            call_execution_cfg = execution_cfg
            if intent.exit_mode:
                call_execution_cfg = replace(execution_cfg, exit_mode=intent.exit_mode)
            result = submit(
                [intent],
                connection_cfg=connection_cfg,
                execution_cfg=call_execution_cfg,
            )
            placements_total += len(result.get("placements", []))
        logger.info(
            "paper submit: transmitted %d bracket set(s) for %d intent(s) "
            "on port %d",
            placements_total,
            len(intents),
            connection_cfg.port,
        )
        return [
            {
                "intent_id": intent.order_ref,
                "action": "paper_submitted",
                "fill_price": None,
            }
            for intent in intents
        ]

    return _paper_submit


def _filter_tradable_setups(
    setup_records: Sequence[dict[str, Any]],
    gate_status_by_variant: dict[str, str],
) -> list[dict[str, Any]]:
    """Keep only setups whose variant gate status is green or amber.

    A setup with no variant key (or a variant that is unknown to the
    gate) is treated as **untradable** — we deliberately fail closed
    for the Phase-B incubation.
    """
    out: list[dict[str, Any]] = []
    for record in setup_records:
        variant = record.get("variant")
        if not isinstance(variant, str):
            continue
        status = gate_status_by_variant.get(variant)
        if status in _LIVE_TRADABLE_GATE_STATUSES:
            out.append(record)
    return out


def _utc_iso(now: datetime | None) -> str:
    instant = now if now is not None else datetime.now(UTC)
    if instant.tzinfo is None:
        instant = instant.replace(tzinfo=UTC)
    return instant.astimezone(UTC).isoformat()


def _atomic_append_audit(path: Path, records: list[dict[str, Any]]) -> None:
    """Append ``records`` to a JSONL audit file atomically (rewrite-in-full).

    Note: O(n²) over the lifetime of the file because every call reads
    the prior content and rewrites the whole thing. Acceptable for
    Phase-A/B (≤ a few hundred records over weeks); for Phase-C (full
    size, 90+ days, multi-symbol) switch to a streaming append + nightly
    rotation. See docs/c8_live_incubation_runbook.md.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    existing: list[str] = []
    if path.exists():
        existing = path.read_text(encoding="utf-8").splitlines()
        # Strip trailing blank lines so the append doesn't double-newline.
        while existing and not existing[-1].strip():
            existing.pop()

    fd, tmp_str = tempfile.mkstemp(
        dir=str(path.parent), prefix=path.name + ".", suffix=".tmp"
    )
    tmp_path = Path(tmp_str)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            for line in existing:
                fh.write(line)
                fh.write("\n")
            for record in records:
                fh.write(json.dumps(record, sort_keys=True))
                fh.write("\n")
            # C-sprint deep-review: flush+fsync before os.replace so a
            # crash between buffer-write and disk-sync does not leave
            # a truncated audit JSONL (live-incubation order audit
            # must survive a hard reboot).
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_path, path)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise


def run_live_incubation(
    *,
    setup_records: Sequence[dict[str, Any]],
    gate_status_by_variant: dict[str, str],
    risk_limits: RiskLimits,
    account_state: AccountState,
    execution_cfg: IBKRExecutionConfig,
    audit_path: Path,
    phase: str = "paper",
    size_scale: float = PHASE_B_RECOMMENDED_SIZE_SCALE,
    submit_fn: SubmitFn = _no_op_submit,
    now: datetime | None = None,
    earnings_filter: EarningsFilter | None = None,
) -> dict[str, Any]:
    """Execute one orchestration round and return a structured summary.

    The function never raises on a kill-switch breach: it records the
    decision in the audit log, marks the run as ``halted`` in the
    summary, and returns. Callers (cron, CI) treat ``halted`` as a
    successful no-op rather than a failure.

    When ``earnings_filter`` is supplied (T7.2), each intent is gated
    against the filter on its symbol + the run's UTC trade-date; blocked
    intents are dropped from submission but still produce an audit
    record with ``action="earnings_blocked"`` so the gate decision is
    auditable. Missing WSH JSONL is a no-op (filter returns blocked=False
    with reason WSH_DATA_MISSING) — Phase A must never block on data
    unavailability.
    """
    timestamp = _utc_iso(now)
    kill_decision: KillSwitchDecision = check_risk_limits(
        account_state, risk_limits
    )

    if kill_decision.engaged:
        halt_record = {
            "ts": timestamp,
            "phase": phase,
            "action": "halted",
            "kill_switch_triggered": True,
            "kill_reason": (
                kill_decision.primary_reason.value
                if kill_decision.primary_reason is not None
                else "unknown"
            ),
            "kill_detail": list(kill_decision.detail),
        }
        _atomic_append_audit(audit_path, [halt_record])
        return {
            "phase": phase,
            "halted": True,
            "kill_reason": halt_record["kill_reason"],
            "intents_submitted": 0,
            "audit_records_written": 1,
        }

    tradable = _filter_tradable_setups(setup_records, gate_status_by_variant)
    intents = build_ibkr_intents_from_smc_setups(
        tradable, execution_cfg, size_scale=size_scale
    )

    # Map intent.order_ref → variant FIRST, before the earnings filter
    # mutates ``intents``. Otherwise earnings-blocked intents would lose
    # their variant attribution in the audit log (the variant comes from
    # the *pre-filter* tradable[]↔intents[] zip per the
    # smc_to_ibkr_adapter ordering contract).
    variant_by_order_ref: dict[str, str] = {}
    if len(tradable) == len(intents):
        for setup, intent in zip(tradable, intents, strict=False):
            variant = setup.get("variant")
            if isinstance(variant, str):
                variant_by_order_ref[intent.order_ref] = variant

    # T7.2 — pre-trade earnings filter. Run BEFORE submit_fn so blocked
    # intents never reach IBKR. Decisions are recorded as audit rows so
    # the cron can attribute "missing intent" to a deliberate skip vs a
    # gate fall-out. Trade-date is the UTC calendar date of the run; the
    # filter does its own pre/post window arithmetic.
    earnings_decisions: dict[str, EarningsFilterDecision] = {}
    if earnings_filter is not None:
        trade_date_iso = (
            now.astimezone(UTC).date().isoformat()
            if now is not None
            else datetime.now(UTC).date().isoformat()
        )
        allowed: list[IBKROrderIntent] = []
        for intent in intents:
            decision = earnings_filter.decide(
                symbol=intent.symbol, trade_date=trade_date_iso
            )
            earnings_decisions[intent.order_ref] = decision
            if not decision.blocked:
                allowed.append(intent)
        intents = allowed

    submission_results = submit_fn(intents)
    submission_by_intent = {
        result.get("intent_id"): result for result in submission_results
    }

    audit_records: list[dict[str, Any]] = []
    # First, emit one audit row per earnings-blocked intent (those were
    # filtered out of ``intents`` above and therefore never seen by
    # ``submit_fn``). Variant key still resolved from variant_by_order_ref.
    for order_ref, decision in earnings_decisions.items():
        if not decision.blocked:
            continue
        audit_records.append(
            {
                "ts": timestamp,
                "phase": phase,
                "intent_id": order_ref,
                "variant": variant_by_order_ref.get(order_ref, ""),
                "symbol": decision.symbol,
                "action": "earnings_blocked",
                "earnings_filter": decision.as_audit_dict(),
                "kill_switch_triggered": False,
            }
        )
    for intent in intents:
        result = submission_by_intent.get(intent.order_ref, {})
        audit_records.append(
            {
                "ts": timestamp,
                "phase": phase,
                "intent_id": intent.order_ref,
                "variant": variant_by_order_ref.get(intent.order_ref, ""),
                "symbol": intent.symbol,
                "action": str(result.get("action", "unknown")),
                "entry_price": float(intent.entry_limit),
                "stop_loss": float(intent.stop_loss),
                "take_profit": float(intent.take_profit),
                "quantity": int(intent.quantity),
                "size_scale": float(size_scale),
                "fill_price": _coerce_optional_float(result.get("fill_price")),
                "kill_switch_triggered": False,
            }
        )

    _atomic_append_audit(audit_path, audit_records)

    earnings_blocked = sum(
        1 for d in earnings_decisions.values() if d.blocked
    )
    return {
        "phase": phase,
        "halted": False,
        "kill_reason": None,
        "intents_submitted": len(intents),
        "intents_earnings_blocked": earnings_blocked,
        "audit_records_written": len(audit_records),
    }


def _coerce_optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


# ── CLI entry point ────────────────────────────────────────────────


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="run_smc_live_incubation",
        description=(
            "Phase-B live-incubation orchestrator. "
            "Reads SMC setups + track-record-gate verdicts, applies "
            "live risk limits, and writes an audit JSONL. "
            "Default behaviour is dry-run (no actual IBKR submission)."
        ),
    )
    parser.add_argument(
        "--phase",
        choices=sorted(_PHASE_DEFAULTS),
        default="paper",
        help="Trading phase. paper = dry-run, live_small = 10%% size, live_full = full size.",
    )
    parser.add_argument(
        "--setups",
        type=Path,
        required=True,
        help="JSON file with a list of SMC setup records.",
    )
    parser.add_argument(
        "--gate-statuses",
        type=Path,
        required=True,
        help='JSON file mapping {"variant_key": "green|amber|red"}.',
    )
    parser.add_argument(
        "--audit-output",
        type=Path,
        required=True,
        help="JSONL audit-log destination (atomically rewritten).",
    )
    parser.add_argument(
        "--size-scale",
        type=float,
        default=None,
        help="Override the phase default size scale.",
    )
    parser.add_argument(
        "--account-state-json",
        type=Path,
        default=None,
        help=(
            "JSON file with the live AccountState snapshot. REQUIRED for "
            "phase=live_small or live_full so the kill-switch evaluates "
            "real equity / drawdown / P&L history. Optional for "
            "phase=paper, where a zero-AccountState is acceptable for "
            "dry-runs and CI."
        ),
    )
    parser.add_argument(
        "--risk-limits-json",
        type=Path,
        default=Path("configs/live_risk_limits.json"),
        help=(
            "JSON file with the kill-switch RiskLimits thresholds (max "
            "daily loss, drawdown, open positions, consecutive losses, "
            "gross exposure). Defaults to the version-controlled "
            "configs/live_risk_limits.json. REQUIRED to exist for "
            "phase=live_small or live_full; for phase=paper a missing file "
            "falls back to the in-code RiskLimits() defaults for CI/dry-runs."
        ),
    )
    parser.add_argument(
        "--wsh-events-jsonl",
        type=Path,
        default=None,
        help=(
            "Path to a daily WSH events JSONL artefact (T7.1). When "
            "present and the file exists, the T7.2 EarningsFilter is "
            "applied to gate intents whose symbol has an earnings event "
            "inside the configured pre/post window. Missing file is a "
            "no-op (Phase A never blocks on data unavailability)."
        ),
    )
    parser.add_argument(
        "--earnings-pre-window-days",
        type=int,
        default=1,
        help="Calendar days before trade-date to block earnings (default: 1).",
    )
    parser.add_argument(
        "--earnings-post-window-days",
        type=int,
        default=1,
        help="Calendar days after trade-date to block earnings (default: 1).",
    )
    parser.add_argument(
        "--phase-eval-report",
        type=Path,
        default=None,
        help=(
            "JSON report produced by scripts/evaluate_phase_criteria.py. "
            "REQUIRED for phase=live_small (must be a passing 'paper' "
            "evaluation) and phase=live_full (must be a passing "
            "'live_small' evaluation). Stat-review F1 (2026-06-10): the "
            "PhasePassCriteria checklist is machine-evaluated, not prose; "
            "a live phase without a fresh passing report refuses to run. "
            "Promotion remains manual sign-off — this gate is necessary, "
            "not sufficient."
        ),
    )
    parser.add_argument(
        "--place-paper-orders",
        action="store_true",
        help=(
            "Opt-in: actually transmit bracket orders to the IBKR *paper* "
            "TWS (port 7497) instead of the default audit-only dry-run. "
            "Only valid with --phase paper; the DU* paper-account guard is "
            "enforced before any order is sent and live phases are refused "
            "outright. Default off — no orders are placed."
        ),
    )
    return parser


def _account_state_from_json(path: Path) -> AccountState:
    """Construct an :class:`AccountState` from a JSON file.

    Required keys mirror the dataclass field set; ``last_n_pnls`` is
    optional and defaults to an empty tuple.
    """
    blob = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(blob, dict):
        raise ValueError(f"--account-state-json must be a JSON object, got {type(blob).__name__}")
    required = {
        "as_of",
        "equity",
        "starting_equity_today",
        "high_water_mark",
        "open_positions",
        "gross_exposure_pct",
    }
    missing = required - blob.keys()
    if missing:
        raise ValueError(
            f"--account-state-json missing required keys: {sorted(missing)!r}"
        )
    as_of_raw = blob["as_of"]
    # Copilot pass-3 fix: enforce strict ISO ``YYYY-MM-DD`` for
    # ``as_of`` (no time component). ``datetime.fromisoformat`` would
    # silently accept ``"2026-04-26T13:30:00+00:00"`` here, masking
    # operator confusion about which day's account state was supplied.
    if not isinstance(as_of_raw, str):
        raise ValueError(
            "--account-state-json: AccountState.as_of must be an ISO date "
            f"string (YYYY-MM-DD), got {type(as_of_raw).__name__}"
        )
    try:
        as_of = date.fromisoformat(as_of_raw)
    except ValueError as exc:
        raise ValueError(
            f"--account-state-json: AccountState.as_of must be an ISO date "
            f"string (YYYY-MM-DD), got {as_of_raw!r}"
        ) from exc
    # Copilot pass-4 fix: ``last_n_pnls`` is documented as optional, but
    # ``blob.get("last_n_pnls", ())`` falls through to ``None`` when the
    # JSON key is present and explicitly ``null``, which then raises a
    # raw ``TypeError`` from ``float(x) for x in None``. Validate the
    # type at the boundary so a malformed file produces a clear
    # remediation message instead of a stack trace.
    raw_pnls = blob.get("last_n_pnls")
    if raw_pnls is None:
        last_n: tuple[float, ...] = ()
    elif not isinstance(raw_pnls, (list, tuple)):
        raise ValueError(
            "--account-state-json: AccountState.last_n_pnls must be a "
            f"list/tuple of numbers (or omitted), got {type(raw_pnls).__name__}"
        )
    else:
        try:
            last_n = tuple(float(x) for x in raw_pnls)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "--account-state-json: AccountState.last_n_pnls entries must "
                f"all be numeric, got {raw_pnls!r}"
            ) from exc
    return AccountState(
        as_of=as_of,
        equity=float(blob["equity"]),
        starting_equity_today=float(blob["starting_equity_today"]),
        high_water_mark=float(blob["high_water_mark"]),
        open_positions=int(blob["open_positions"]),
        gross_exposure_pct=float(blob["gross_exposure_pct"]),
        last_n_pnls=last_n,
    )


def _resolve_risk_limits(phase: str, path: Path | None) -> RiskLimits:
    """Resolve the kill-switch :class:`RiskLimits` for a run.

    The thresholds live in a version-controlled JSON file
    (``configs/live_risk_limits.json`` by default) rather than being
    hard-coded here, so a change to the kill-switch is an auditable diff
    (F4). A live phase MUST resolve an existing file — a deleted/renamed
    config fails loud instead of silently reverting to the in-code
    defaults; ``phase=paper`` tolerates a missing file (CI / dry-runs) and
    falls back to ``RiskLimits()``.
    """
    if path is not None and path.exists():
        return RiskLimits.from_json(path)
    if phase in ("live_small", "live_full"):
        raise SystemExit(
            f"phase={phase!r} requires --risk-limits-json to point at an "
            f"existing kill-switch config (default "
            f"configs/live_risk_limits.json); got {str(path)!r} which does "
            "not exist. Refusing to fall back to in-code RiskLimits() "
            "defaults for a non-paper phase."
        )
    return RiskLimits()


def main(argv: Sequence[str] | None = None) -> int:
    # F-V4-A1b: configure root logging so logger.info / logging.* calls actually
    # surface on stdout when this script is invoked from a GitHub Actions workflow.
    # Without this, the pipeline runs silently and runner-side eviction or
    # mid-pipeline errors are impossible to triage. Also flush eagerly so partial
    # logs survive runner shutdown signals. Self-contained imports to avoid
    # disturbing module-level import order.
    import logging as _v4a1b_logging
    import sys as _v4a1b_sys
    import time as _v4a1b_time
    _v4a1b_logging.basicConfig(
        level=_v4a1b_logging.INFO,
        format="%(asctime)sZ %(levelname)s %(name)s %(message)s",
        stream=_v4a1b_sys.stderr,
        force=True,
    )
    _v4a1b_logging.Formatter.converter = _v4a1b_time.gmtime
    try:
        _v4a1b_sys.stdout.reconfigure(line_buffering=True)  # type: ignore[attr-defined]
        _v4a1b_sys.stderr.reconfigure(line_buffering=True)  # type: ignore[attr-defined]
    except (AttributeError, OSError):
        pass


    args = _build_parser().parse_args(argv)
    phase_defaults = _PHASE_DEFAULTS[args.phase]
    size_scale = (
        args.size_scale
        if args.size_scale is not None
        else float(phase_defaults["size_scale"])
    )

    # Opt-in paper execution is paper-only by construction: a live phase
    # that also passes --place-paper-orders is refused before any disk or
    # network I/O so the flag can never transmit real-money orders.
    if args.place_paper_orders and args.phase != "paper":
        raise SystemExit(
            "--place-paper-orders is only supported for --phase paper "
            f"(got --phase {args.phase!r}). This flag intentionally cannot "
            "transmit live orders; refusing to run."
        )

    setup_records = json.loads(args.setups.read_text(encoding="utf-8"))
    gate_statuses = json.loads(args.gate_statuses.read_text(encoding="utf-8"))

    risk_limits = _resolve_risk_limits(args.phase, args.risk_limits_json)

    # C-sprint deep-review C8 MINOR fix: a default-zero AccountState is
    # safe for paper-mode dry-runs but DANGEROUS for any phase that
    # actually submits orders — the kill-switch evaluates against
    # equity / drawdown / P&L history, all of which are zero in the
    # default and can therefore mask a legitimate halt condition. Force
    # the operator to supply a real snapshot for the live phases.
    if args.phase in ("live_small", "live_full") and args.account_state_json is None:
        raise SystemExit(
            f"phase={args.phase!r} requires --account-state-json with "
            "the current live AccountState (equity, drawdown, P&L "
            "history). Refusing to default to a zero-AccountState for "
            "a non-paper phase — the kill-switch would silently no-op."
        )
    # Stat-review F1/F6 (2026-06-10): live phases additionally require a
    # fresh, PASSING machine evaluation of the prior phase's
    # PhasePassCriteria. Imported lazily so paper-mode CI never touches
    # the evaluator module.
    if args.phase in ("live_small", "live_full"):
        if args.phase_eval_report is None:
            raise SystemExit(
                f"phase={args.phase!r} requires --phase-eval-report "
                "(produced by scripts/evaluate_phase_criteria.py) proving "
                "the prior phase's pass criteria are machine-verified. "
                "Refusing to run a live phase on prose criteria alone."
            )
        from scripts.evaluate_phase_criteria import load_and_validate_eval_report

        # W8-3 (stat-review wave 8): a live phase with an empty gate_statuses
        # map has no variant to bind the eval report to, which silently
        # neutralises the W3-3 cross-variant substitution guard below —
        # list({}) → [] → None → membership check skipped entirely. A live
        # run with zero gated variants is itself nonsensical; fail closed
        # rather than authorise on an unbound eval report.
        if not gate_statuses:
            raise SystemExit(
                f"phase={args.phase!r} requires a non-empty --gate-statuses "
                "map: a live phase must declare the variant(s) being traded "
                "so the eval report can be bound to them (W3-3). "
                "Refusing to run a live phase with zero gated variants."
            )

        # W3-3 (stat-review wave 3): bind the eval report to the variants
        # actually being traded, preventing cross-variant substitution.
        # gate_statuses is keyed by variant name; the report's variant
        # must be one of them (exact match for the common single-variant
        # case, membership for multi-variant runs).
        load_and_validate_eval_report(
            args.phase_eval_report,
            target_phase=args.phase,
            expected_variants=list(gate_statuses),  # W8-3: guaranteed non-empty
        )
    if args.account_state_json is not None:
        account_state = _account_state_from_json(args.account_state_json)
    else:
        account_state = AccountState(
            as_of=datetime.now(UTC).date(),
            equity=0.0,
            starting_equity_today=0.0,
            high_water_mark=0.0,
            open_positions=0,
            gross_exposure_pct=0.0,
            last_n_pnls=(),
        )
    execution_cfg = IBKRExecutionConfig(paper_mode=bool(phase_defaults["paper_mode"]))

    # Default to the audit-only no-op submitter. Only when the operator
    # explicitly opts in (guarded to --phase paper above) do we build a
    # submitter that actually transmits bracket orders to the paper TWS;
    # the DU* paper-account guard inside place_order_intents fails loud if
    # a live TWS is bound to the paper port.
    submit_fn: SubmitFn = _no_op_submit
    if args.place_paper_orders:
        submit_fn = _build_paper_submit_fn(
            connection_cfg=IBKRConnectionConfig(),
            execution_cfg=IBKRWatchlistExecutionConfig(),
        )

    earnings_filter: EarningsFilter | None = None
    if args.wsh_events_jsonl is not None:
        earnings_filter = EarningsFilter(
            events_jsonl=args.wsh_events_jsonl,
            pre_window_days=int(args.earnings_pre_window_days),
            post_window_days=int(args.earnings_post_window_days),
        )

    summary = run_live_incubation(
        setup_records=setup_records,
        gate_status_by_variant=gate_statuses,
        risk_limits=risk_limits,
        account_state=account_state,
        execution_cfg=execution_cfg,
        audit_path=args.audit_output,
        phase=args.phase,
        size_scale=size_scale,
        earnings_filter=earnings_filter,
        submit_fn=submit_fn,
    )
    print(json.dumps(summary, sort_keys=True))
    return 0


__all__ = [
    "main",
    "run_live_incubation",
]


if __name__ == "__main__":  # pragma: no cover - script entry point
    raise SystemExit(main())
