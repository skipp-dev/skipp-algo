from __future__ import annotations

import csv
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

DEFAULT_WATCHLIST_CSV = Path("reports/databento_watchlist_top5_pre1530.csv")


def _resolve_repo_root(repo_root: Path | str | None) -> Path:
    if repo_root is None:
        return Path(__file__).resolve().parents[1]
    return Path(repo_root).resolve()


def _resolve_source_csv_path(*, repo_root: Path, source_csv_path: Path | str | None) -> Path:
    if source_csv_path is None:
        return repo_root / DEFAULT_WATCHLIST_CSV
    path = Path(source_csv_path)
    if not path.is_absolute():
        path = repo_root / path
    return path.resolve()


def _load_watchlist_rows(csv_path: Path) -> list[dict[str, str]]:
    if not csv_path.exists():
        raise FileNotFoundError(f"watchlist source not found: {csv_path}")

    with csv_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = [dict(row) for row in reader]

    if not rows:
        raise ValueError(f"watchlist source is empty: {csv_path}")
    return rows


def _select_symbol_row(rows: list[dict[str, str]], symbol: str) -> dict[str, str]:
    wanted = symbol.strip().upper()
    if not wanted:
        raise ValueError("symbol must not be empty")

    matching = [row for row in rows if str(row.get("symbol", "")).strip().upper() == wanted]
    if not matching:
        raise ValueError(f"symbol {wanted} not present in watchlist source")

    # Keep source selection deterministic: latest trade_date, then lowest watchlist_rank.
    def _sort_key(row: dict[str, str]) -> tuple[str, int]:
        trade_date = str(row.get("trade_date", ""))
        raw_rank = str(row.get("watchlist_rank", "")).strip()
        try:
            rank = int(raw_rank)
        except ValueError:
            rank = 10**9
        return (trade_date, -rank)

    latest_trade_date = max(str(row.get("trade_date", "")) for row in matching)
    latest_rows = [row for row in matching if str(row.get("trade_date", "")) == latest_trade_date]
    return sorted(latest_rows, key=_sort_key, reverse=True)[0]


def _asof_ts_from_trade_date(trade_date: str) -> float:
    parsed = datetime.fromisoformat(trade_date).date()
    return datetime(parsed.year, parsed.month, parsed.day, tzinfo=UTC).timestamp()


def _safe_float(value: Any, *, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def discover_repo_source_paths(*, repo_root: Path | str | None = None) -> dict[str, Any]:
    root = _resolve_repo_root(repo_root)
    csv_path = _resolve_source_csv_path(repo_root=root, source_csv_path=None)

    return {
        "integration_entry": "reports/databento_watchlist_top5_pre1530.csv",
        "repo_root": str(root),
        "watchlist_csv": str(csv_path),
        "meta_source": "watchlist_csv",
        "structure_source": "watchlist_csv_partial",
        "structure_capabilities": {
            "bos": False,
            "orderblocks": False,
            "fvg": False,
            "liquidity_sweeps": False,
        },
        "notes": [
            "Current source is symbol/watchlist-centric and does not publish explicit BOS/OB/FVG/sweep events.",
            "Phase-5 integration therefore wires a real repo source with explicit partial-structure output (empty lists).",
        ],
    }


def load_raw_structure_input(
    symbol: str,
    timeframe: str,
    *,
    repo_root: Path | str | None = None,
    source_csv_path: Path | str | None = None,
) -> dict[str, Any]:
    del timeframe
    root = _resolve_repo_root(repo_root)
    csv_path = _resolve_source_csv_path(repo_root=root, source_csv_path=source_csv_path)
    rows = _load_watchlist_rows(csv_path)
    _select_symbol_row(rows, symbol)

    return {
        "bos": [],
        "orderblocks": [],
        "fvg": [],
        "liquidity_sweeps": [],
    }


def load_raw_meta_input(
    symbol: str,
    timeframe: str,
    *,
    repo_root: Path | str | None = None,
    source_csv_path: Path | str | None = None,
) -> dict[str, Any]:
    root = _resolve_repo_root(repo_root)
    csv_path = _resolve_source_csv_path(repo_root=root, source_csv_path=source_csv_path)
    rows = _load_watchlist_rows(csv_path)
    row = _select_symbol_row(rows, symbol)

    trade_date = str(row.get("trade_date", "")).strip()
    if not trade_date:
        raise ValueError("watchlist row is missing trade_date")

    asof_ts = _asof_ts_from_trade_date(trade_date)
    premarket_volume = _safe_float(row.get("premarket_volume"), default=0.0)

    return {
        "symbol": str(row.get("symbol", symbol)).strip().upper(),
        "timeframe": str(timeframe).strip(),
        "asof_ts": asof_ts,
        "volume": {
            "value": {
                "regime": "NORMAL",
                "thin_fraction": 0.0,
            },
            "asof_ts": asof_ts,
            "stale": False,
        },
        "provenance": [
            "repo:reports/databento_watchlist_top5_pre1530.csv",
            f"repo:reports/databento_watchlist_top5_pre1530.csv#symbol={str(row.get('symbol', symbol)).strip().upper()}",
            f"repo:reports/databento_watchlist_top5_pre1530.csv#trade_date={trade_date}",
            f"repo:reports/databento_watchlist_top5_pre1530.csv#premarket_volume={premarket_volume}",
            "smc_integration:partial_structure_only",
        ],
    }
