from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, Sequence, cast

import pandas as pd

from smc_core.ids import bos_id
from scripts.market_structure_features import build_market_structure_feature_frame

SCHEMA_VERSION = "1.0.0"
DEFAULT_WORKBOOK = Path("databento_volatility_production_20260307_114724.xlsx")
DEFAULT_OUTPUT = Path("reports") / "smc_structure_artifact.json"


def _daily_asof_ts(trade_date: Any) -> float:
    parsed = pd.to_datetime(trade_date, errors="coerce")
    if pd.isna(parsed):
        raise ValueError(f"invalid trade_date value: {trade_date}")
    date_value = parsed.date()
    return datetime(date_value.year, date_value.month, date_value.day, tzinfo=UTC).timestamp()


def _normalize_symbol(value: Any) -> str:
    text = str(value).strip().upper()
    if text.startswith("(") and text.endswith(")") and "," in text:
        text = text.strip("() ").split(",", 1)[0].strip().strip("'").strip('"')
    if not text:
        raise ValueError("empty symbol after normalization")
    return text


def _event_from_last_event(symbol: str, last_event: str, asof_ts: float, close_price: float) -> list[dict[str, Any]]:
    normalized = str(last_event).strip().lower()
    if normalized not in {"bos_up", "bos_down", "choch_up", "choch_down"}:
        return []

    kind = cast(Literal["BOS", "CHOCH"], "BOS" if normalized.startswith("bos") else "CHOCH")
    direction = cast(Literal["UP", "DOWN"], "UP" if normalized.endswith("up") else "DOWN")
    event_price = float(close_price)

    return [
        {
            "id": bos_id(
                symbol=symbol,
                timeframe="1D",
                anchor_ts=asof_ts,
                kind=kind,
                dir=direction,
                price=event_price,
            ),
            "time": asof_ts,
            "price": event_price,
            "kind": kind,
            "dir": direction,
        }
    ]


def _coverage_from_structure(structure: dict[str, Any], *, coverage_mode: str) -> dict[str, Any]:
    return {
        "mode": coverage_mode,
        "has_bos": bool(structure.get("bos")),
        "has_orderblocks": bool(structure.get("orderblocks")),
        "has_fvg": bool(structure.get("fvg")),
        "has_liquidity_sweeps": bool(structure.get("liquidity_sweeps")),
    }


def _build_entries(daily_bars: pd.DataFrame) -> list[dict[str, Any]]:
    bars = daily_bars.copy()
    bars["trade_date"] = pd.to_datetime(bars.get("trade_date"), errors="coerce")
    bars["timestamp"] = pd.to_datetime(bars.get("trade_date"), errors="coerce")
    bars["symbol"] = bars.get("symbol", "").astype(str).str.strip().str.upper()
    bars["close"] = pd.to_numeric(bars.get("close"), errors="coerce")
    bars = bars.dropna(subset=["trade_date", "timestamp", "symbol", "close"]).copy()
    if bars.empty:
        raise ValueError("daily_bars sheet has no usable rows")

    features = build_market_structure_feature_frame(
        bars,
        group_keys=["symbol"],
        prefix="structure",
    )
    if features.empty:
        raise ValueError("no structure features could be computed from daily_bars")

    latest_rows = bars.sort_values(["symbol", "trade_date"]).groupby("symbol", as_index=False).tail(1)
    latest_by_symbol = {
        str(row.symbol).strip().upper(): row
        for row in latest_rows[["symbol", "trade_date", "close"]].itertuples(index=False)
    }

    entries: list[dict[str, Any]] = []
    for row in features.itertuples(index=False):
        symbol = _normalize_symbol(getattr(row, "symbol"))
        latest = latest_by_symbol.get(symbol)
        if latest is None:
            continue

        asof_ts = _daily_asof_ts(latest.trade_date)
        last_event_raw = str(getattr(row, "structure_last_event", "none") or "none").strip().lower()
        trend_state_raw = int(getattr(row, "structure_trend_state", 0) or 0)
        trend_state = 1 if trend_state_raw > 0 else -1 if trend_state_raw < 0 else 0

        bos_events = _event_from_last_event(symbol, last_event_raw, asof_ts, float(latest.close))
        coverage = "partial" if bos_events else "none"
        structure_payload = {
            "bos": bos_events,
            "orderblocks": [],
            "fvg": [],
            "liquidity_sweeps": [],
        }

        entries.append(
            {
                "symbol": symbol,
                "timeframe": "1D",
                "asof_ts": asof_ts,
                "coverage": coverage,
                "coverage_detail": _coverage_from_structure(structure_payload, coverage_mode=coverage),
                "event_evidence": {
                    "last_event": last_event_raw if last_event_raw else "none",
                    "trend_state": trend_state,
                },
                "structure": structure_payload,
            }
        )

    entries.sort(key=lambda item: item["symbol"])
    return entries


def build_structure_artifact_payload(*, workbook: Path, generated_at: float | None = None) -> dict[str, Any]:
    if not workbook.exists():
        raise FileNotFoundError(f"workbook not found: {workbook}")

    daily_bars = pd.read_excel(workbook, sheet_name="daily_bars")
    entries = _build_entries(daily_bars)

    has_bos = any(entry["structure"]["bos"] for entry in entries)
    coverage = "partial" if has_bos else "none"

    aggregate_structure = {
        "bos": [item for entry in entries for item in entry["structure"]["bos"]],
        "orderblocks": [item for entry in entries for item in entry["structure"]["orderblocks"]],
        "fvg": [item for entry in entries for item in entry["structure"]["fvg"]],
        "liquidity_sweeps": [item for entry in entries for item in entry["structure"]["liquidity_sweeps"]],
    }

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": float(generated_at) if generated_at is not None else datetime.now(UTC).timestamp(),
        "source": {
            "workbook_path": str(workbook.as_posix()),
            "sheet": "daily_bars",
            "timeframe": "1D",
            "event_logic": "scripts.market_structure_features.build_market_structure_feature_frame",
        },
        "structure_coverage": coverage,
        "coverage": _coverage_from_structure(aggregate_structure, coverage_mode=coverage),
        "entries": entries,
    }


def export_structure_artifact(
    *,
    workbook: Path = DEFAULT_WORKBOOK,
    output: Path = DEFAULT_OUTPUT,
    generated_at: float | None = None,
) -> Path:
    payload = build_structure_artifact_payload(workbook=workbook, generated_at=generated_at)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return output


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Export explicit SMC structure artifact from workbook data.")
    parser.add_argument("--workbook", default=str(DEFAULT_WORKBOOK), help="Workbook path containing daily_bars sheet")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="Output JSON path")
    parser.add_argument("--generated-at", type=float, default=None, help="Optional fixed generated_at timestamp")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    written = export_structure_artifact(
        workbook=Path(args.workbook).expanduser(),
        output=Path(args.output).expanduser(),
        generated_at=args.generated_at,
    )
    print(written)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
