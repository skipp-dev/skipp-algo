from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Sequence

import pandas as pd

from scripts.databento_production_workbook import resolve_production_workbook_path
from scripts.explicit_structure_from_bars import build_full_structure_from_bars

SCHEMA_VERSION = "1.0.0"
DEFAULT_WORKBOOK = Path("artifacts/smc_microstructure_exports/databento_volatility_production_workbook.xlsx")
DEFAULT_OUTPUT = Path("reports") / "smc_structure_artifact.json"


def _normalize_symbol(value: Any) -> str:
    text = str(value).strip().upper()
    if text.startswith("(") and text.endswith(")") and "," in text:
        text = text.strip("() ").split(",", 1)[0].strip().strip("'").strip('"')
    if not text:
        raise ValueError("empty symbol after normalization")
    return text


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

    entries: list[dict[str, Any]] = []
    for symbol in sorted({_normalize_symbol(item) for item in bars["symbol"].tolist()}):
        symbol_bars = bars.loc[bars["symbol"].eq(symbol)].copy()
        if symbol_bars.empty:
            continue
        structure_payload = build_full_structure_from_bars(symbol_bars, symbol=symbol, timeframe="1D")
        last_ts = pd.to_datetime(symbol_bars["timestamp"], errors="coerce", utc=True).dropna().max()
        asof_ts = float(pd.Timestamp(last_ts).timestamp()) if pd.notna(last_ts) else datetime.now(UTC).timestamp()

        last_event_raw = "none"
        trend_state = 0
        if structure_payload["bos"]:
            last = structure_payload["bos"][-1]
            kind = str(last.get("kind", "BOS")).upper()
            direction = str(last.get("dir", "UP")).upper()
            trend_state = 1 if direction == "UP" else -1
            if kind == "CHOCH" and direction == "UP":
                last_event_raw = "choch_up"
            elif kind == "CHOCH" and direction == "DOWN":
                last_event_raw = "choch_down"
            elif direction == "UP":
                last_event_raw = "bos_up"
            else:
                last_event_raw = "bos_down"

        has_any = any(bool(structure_payload[key]) for key in ("bos", "orderblocks", "fvg", "liquidity_sweeps"))
        has_all = all(bool(structure_payload[key]) for key in ("bos", "orderblocks", "fvg", "liquidity_sweeps"))
        coverage = "full" if has_all else "partial" if has_any else "none"

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
    workbook = resolve_production_workbook_path(workbook=workbook, repo_root=Path(__file__).resolve().parents[1])

    daily_bars = pd.read_excel(workbook, sheet_name="daily_bars")
    entries = _build_entries(daily_bars)

    aggregate_structure = {
        "bos": [item for entry in entries for item in entry["structure"]["bos"]],
        "orderblocks": [item for entry in entries for item in entry["structure"]["orderblocks"]],
        "fvg": [item for entry in entries for item in entry["structure"]["fvg"]],
        "liquidity_sweeps": [item for entry in entries for item in entry["structure"]["liquidity_sweeps"]],
    }
    has_any = any(bool(aggregate_structure[key]) for key in ("bos", "orderblocks", "fvg", "liquidity_sweeps"))
    has_all = all(bool(aggregate_structure[key]) for key in ("bos", "orderblocks", "fvg", "liquidity_sweeps"))
    coverage = "full" if has_all else "partial" if has_any else "none"

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": float(generated_at) if generated_at is not None else datetime.now(UTC).timestamp(),
        "source": {
            "workbook_path": str(workbook.as_posix()),
            "sheet": "daily_bars",
            "timeframe": "1D",
            "event_logic": "scripts.explicit_structure_from_bars.build_full_structure_from_bars",
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
