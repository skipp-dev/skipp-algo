"""C13/T1.2 — IBKR adapter smoke harness (Paper Gateway round-trip).

Validates the full ``SMC setup -> IBKROrderIntent -> IBKR Paper Gateway``
hand-off without requiring a live IBKR connection in CI. Two modes:

``--mock`` (default, CI-safe)
    Synthesise SMC setups, route them through
    :func:`scripts.smc_to_ibkr_adapter.build_ibkr_intents_from_smc_setups`,
    verify each intent satisfies the frozen Phase-A risk limits in
    ``configs/live_risk_limits.json`` (commit dd275e6f), record the
    payloads to ``cache/live/smoke_<YYYY-MM-DD>.jsonl`` for an audit
    trail, and print a summary. No socket is opened.

``--live``
    Connect to the IBKR Paper Gateway on ``localhost:7497`` via
    ``ib_insync``, place each intent as a *limit* order, wait for an
    ack, then immediately cancel. Pure round-trip — no real fills.

The frozen risk-limits file is the single source of truth for Phase-A:
positional caps, gross-exposure ceilings, and the killswitch-on-breach
flag are all read from there. Modifying that file is a separate
governed action.

Pure stdlib + the existing adapter; ``ib_insync`` is imported lazily
only when ``--live`` is requested so CI does not pull it.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import tempfile
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from scripts.smc_to_ibkr_adapter import (
    PHASE_B_RECOMMENDED_SIZE_SCALE,
    IBKRExecutionConfig,
    build_ibkr_intents_from_smc_setups,
)
import contextlib

logger = logging.getLogger("smoke_smc_to_ibkr_adapter")

DEFAULT_RISK_LIMITS_PATH = Path("configs/live_risk_limits.json")
DEFAULT_AUDIT_DIR = Path("cache/live")
DEFAULT_PAPER_HOST = "127.0.0.1"
DEFAULT_PAPER_PORT = 7497  # IBKR Paper Gateway
DEFAULT_CLIENT_ID = 71  # Reserved for SMC live incubation


# ---------------------------------------------------------------------------
# Frozen risk-limits loader
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RiskLimitsSnapshot:
    """Subset of ``configs/live_risk_limits.json`` consumed at the gate."""

    max_open_positions: int
    max_gross_exposure_pct: float
    flatten_on_breach: bool
    manual_halt: bool
    frozen_at: str

    @classmethod
    def load(cls, path: Path) -> RiskLimitsSnapshot:
        with path.open("r", encoding="utf-8") as fh:
            payload = json.load(fh)
        return cls(
            max_open_positions=int(payload["max_open_positions"]),
            max_gross_exposure_pct=float(payload["max_gross_exposure_pct"]),
            flatten_on_breach=bool(payload.get("flatten_on_breach", True)),
            manual_halt=bool(payload.get("manual_halt", False)),
            frozen_at=str(payload.get("frozen_at", "")),
        )


# ---------------------------------------------------------------------------
# Synthetic setups (Phase-A canonical fixture)
# ---------------------------------------------------------------------------


def synthesise_setups(trade_date: date | None = None) -> list[dict[str, Any]]:
    """Return one canonical setup per family — covers the Phase-A taxonomy."""
    when = trade_date or datetime.now(UTC).date()
    return [
        {
            "symbol": "AAPL",
            "entry": 200.00,
            "stop_loss": 198.00,
            "take_profit": 204.00,
            "quantity": 10,
            "trade_date": when,
            "level_tag": "BOS_megacap",
            "watchlist_rank": 1,
            "premarket_last": 199.50,
            "gap_pct": 0.0025,
        },
        {
            "symbol": "MSFT",
            "entry": 420.00,
            "stop_loss": 416.00,
            "take_profit": 428.00,
            "quantity": 5,
            "trade_date": when,
            "level_tag": "OB_megacap",
            "watchlist_rank": 2,
            "premarket_last": 419.20,
            "gap_pct": 0.0019,
        },
    ]


# ---------------------------------------------------------------------------
# Risk-limits gate
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RiskCheckResult:
    """Outcome of validating a batch of intents against frozen risk limits."""

    ok: bool
    rejections: tuple[str, ...]
    open_positions: int
    gross_exposure_pct: float


def check_intents_against_limits(
    intents: Sequence[Any],
    limits: RiskLimitsSnapshot,
    *,
    account_equity_usd: float,
) -> RiskCheckResult:
    """Validate intent batch against ``max_open_positions`` and gross exposure.

    A trip on ``manual_halt`` rejects the entire batch — that is the
    explicit kill-switch contract and the only field that overrides
    everything else.
    """
    rejections: list[str] = []
    if limits.manual_halt:
        rejections.append("manual_halt is engaged; rejecting entire batch")
        return RiskCheckResult(False, tuple(rejections), 0, 0.0)
    if account_equity_usd <= 0:
        raise ValueError("account_equity_usd must be positive for exposure check")

    open_positions = len(intents)
    if open_positions > limits.max_open_positions:
        rejections.append(f"open_positions={open_positions} exceeds max_open_positions={limits.max_open_positions}")

    gross_usd = sum(abs(int(i.quantity)) * float(i.entry_limit) for i in intents)
    gross_pct = (gross_usd / account_equity_usd) * 100.0
    if gross_pct > limits.max_gross_exposure_pct:
        rejections.append(
            f"gross_exposure_pct={gross_pct:.2f} exceeds max_gross_exposure_pct={limits.max_gross_exposure_pct:.2f}"
        )

    return RiskCheckResult(
        ok=not rejections,
        rejections=tuple(rejections),
        open_positions=open_positions,
        gross_exposure_pct=gross_pct,
    )


# ---------------------------------------------------------------------------
# Audit trail
# ---------------------------------------------------------------------------


def _intent_to_dict(intent: Any) -> dict[str, Any]:
    """Serialise an :class:`IBKROrderIntent` for JSONL audit."""
    raw = asdict(intent) if hasattr(intent, "__dataclass_fields__") else dict(intent)
    # ``trade_date`` is a ``datetime.date`` → ISO for JSON.
    if isinstance(raw.get("trade_date"), date):
        raw["trade_date"] = raw["trade_date"].isoformat()
    return raw


def _atomic_append_jsonl(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            # ATOMIC-WRITE-EXEMPT: append-by-write (smoke audit, single-shot).
            if path.exists():
                fh.write(path.read_text(encoding="utf-8"))
                if not fh.tell() or not _ends_with_newline(path):
                    fh.write("\n") if fh.tell() else None
            for row in rows:
                fh.write(json.dumps(row, sort_keys=True))
                fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_name, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp_name)
        raise


def _ends_with_newline(path: Path) -> bool:
    try:
        with path.open("rb") as fh:
            fh.seek(-1, os.SEEK_END)
            return fh.read(1) == b"\n"
    except OSError:
        return True


# ---------------------------------------------------------------------------
# Mock-mode runner
# ---------------------------------------------------------------------------


def run_mock(
    *,
    setups: Sequence[Mapping[str, Any]],
    risk_limits: RiskLimitsSnapshot,
    account_equity_usd: float,
    size_scale: float,
    audit_path: Path | None,
) -> dict[str, Any]:
    """Execute the synthetic round-trip without contacting IBKR."""
    exec_cfg = IBKRExecutionConfig(
        host=DEFAULT_PAPER_HOST,
        paper_mode=True,
        client_id=DEFAULT_CLIENT_ID,
    )
    intents = build_ibkr_intents_from_smc_setups(setups, exec_cfg, size_scale=size_scale)
    risk = check_intents_against_limits(intents, risk_limits, account_equity_usd=account_equity_usd)
    audit_rows = [
        {
            "ts": datetime.now(UTC).isoformat(),
            "mode": "mock",
            "size_scale": size_scale,
            "risk_ok": risk.ok,
            "risk_rejections": list(risk.rejections),
            "intent": _intent_to_dict(intent),
        }
        for intent in intents
    ]
    if audit_path is not None and audit_rows:
        _atomic_append_jsonl(audit_path, audit_rows)
    return {
        "mode": "mock",
        "intent_count": len(intents),
        "risk_ok": risk.ok,
        "risk_rejections": list(risk.rejections),
        "open_positions": risk.open_positions,
        "gross_exposure_pct": risk.gross_exposure_pct,
        "frozen_at": risk_limits.frozen_at,
        "size_scale": size_scale,
        "audit_path": str(audit_path) if audit_path else None,
    }


# ---------------------------------------------------------------------------
# Live-mode runner (lazy ib_insync import)
# ---------------------------------------------------------------------------


def run_live(
    *,
    setups: Sequence[Mapping[str, Any]],
    risk_limits: RiskLimitsSnapshot,
    account_equity_usd: float,
    size_scale: float,
    host: str,
    port: int,
    client_id: int,
    timeout_seconds: float = 10.0,
) -> dict[str, Any]:
    """Place + cancel each intent on the IBKR Paper Gateway."""
    try:
        from ib_insync import IB, LimitOrder, Stock  # type: ignore[import-untyped]
    except ImportError as exc:  # pragma: no cover - exercised only in live mode
        raise RuntimeError(
            "ib_insync is required for --live mode; install with "
            "`pip install ib_insync` and ensure IBKR Paper Gateway is running."
        ) from exc

    exec_cfg = IBKRExecutionConfig(host=host, paper_mode=(port == DEFAULT_PAPER_PORT), client_id=client_id)
    intents = build_ibkr_intents_from_smc_setups(setups, exec_cfg, size_scale=size_scale)
    risk = check_intents_against_limits(intents, risk_limits, account_equity_usd=account_equity_usd)
    if not risk.ok:
        return {
            "mode": "live",
            "submitted": False,
            "risk_ok": False,
            "risk_rejections": list(risk.rejections),
        }

    ib = IB()
    placed: list[dict[str, Any]] = []
    try:
        ib.connect(host, port, clientId=client_id, timeout=timeout_seconds)
        for intent in intents:
            contract = Stock(intent.symbol, "SMART", "USD")
            order = LimitOrder("BUY", int(intent.quantity), float(intent.entry_limit), tif=intent.tif)
            trade = ib.placeOrder(contract, order)
            ib.sleep(1.0)  # wait for ack
            try:
                ib.cancelOrder(order)
            finally:
                placed.append(
                    {
                        "symbol": intent.symbol,
                        "order_id": getattr(order, "orderId", None),
                        "status": getattr(trade.orderStatus, "status", None),
                    }
                )
    finally:
        try:
            ib.disconnect()
        except Exception:  # pragma: no cover - cleanup best-effort
            logger.warning("ib.disconnect raised", exc_info=True)
    return {
        "mode": "live",
        "submitted": True,
        "risk_ok": True,
        "intent_count": len(intents),
        "round_trips": placed,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--mode",
        choices=("mock", "live"),
        default="mock",
        help="Smoke mode (default: mock; CI-safe).",
    )
    p.add_argument(
        "--risk-limits",
        type=Path,
        default=DEFAULT_RISK_LIMITS_PATH,
        help="Path to the frozen Phase-A risk-limits JSON.",
    )
    p.add_argument(
        "--account-equity-usd",
        type=float,
        default=10_000.0,
        help="Account equity used for gross-exposure %% calculation (mock-only).",
    )
    p.add_argument(
        "--size-scale",
        type=float,
        default=PHASE_B_RECOMMENDED_SIZE_SCALE,
        help="Size scaling factor (default: 0.10 — Phase-B recommended).",
    )
    p.add_argument(
        "--audit-path",
        type=Path,
        default=None,
        help=("Audit JSONL output path. Defaults to cache/live/smoke_<today>.jsonl in mock mode."),
    )
    p.add_argument("--host", default=DEFAULT_PAPER_HOST)
    p.add_argument("--port", type=int, default=DEFAULT_PAPER_PORT)
    p.add_argument("--client-id", type=int, default=DEFAULT_CLIENT_ID)
    return p


def main(argv: Sequence[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = _build_parser().parse_args(argv)
    risk_limits = RiskLimitsSnapshot.load(args.risk_limits)
    setups = synthesise_setups()
    if args.mode == "mock":
        audit_path = args.audit_path or (DEFAULT_AUDIT_DIR / f"smoke_{datetime.now(UTC).date().isoformat()}.jsonl")
        result = run_mock(
            setups=setups,
            risk_limits=risk_limits,
            account_equity_usd=args.account_equity_usd,
            size_scale=args.size_scale,
            audit_path=audit_path,
        )
    else:
        result = run_live(
            setups=setups,
            risk_limits=risk_limits,
            account_equity_usd=args.account_equity_usd,
            size_scale=args.size_scale,
            host=args.host,
            port=args.port,
            client_id=args.client_id,
        )
    print(json.dumps(result, indent=2, sort_keys=True))
    if not result.get("risk_ok", True):
        return 2
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
