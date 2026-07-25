"""Bootstrap generator for the A0-Fast reference file (previous_close + ADV).

Today's committed ``services/a0_fast_detector/bootstrap/a0-reference.json``
has ~900 rows but is scoped to the micro-cap symbol population the current
bootstrap process targets, NOT the runtime-monitored ``A0_FAST_SYMBOLS``
shadow subset (a much smaller explicit list -- see
``services/a0_fast_detector/README.md``). This module extends reference
construction to the FULL liquid open_prep production candidate universe (the
~900 symbols ``DEFAULT_TOP_N=0`` (ALL) monitors) instead of the
micro-cap-only symbol source.

previous_close and average_daily_volume are sourced from FMP's adjusted
end-of-day history (``FMPClient.get_historical_price_eod_full`` ->
``/stable/historical-price-eod/full``), NOT from Databento daily bars.

Rationale (2026-07-25 decision, "Option A"): a Databento ``ohlcv-1d`` bar on
EQUS.MINI is RAW/UNADJUSTED for corporate actions, so the original
Databento-sourced implementation of this module labeling it
``corporate_action_adjusted=True`` was factually wrong. prev_close and ADV
are daily values (not latency-critical -- only the live intraday bars are),
and FMP's EOD history carries split/dividend-*adjusted* prices, so FMP is the
correct, honestly-labeled source for these two fields. Only the live
intraday bars remain Databento.

FMP field verification (2026-07-25, no live network access in this
sandbox): the FMP response row's adjustment-carrying field is ``close`` --
NOT ``adjClose``. Evidence: every existing production call site reading
``/stable/historical-price-eod/full`` rows in this repo
(``open_prep/run_open_prep.py::_fetch_symbol_atr``,
``open_prep/market_microstructure.py::_fetch_eod_closes``) reads ``close``
(plus ``volume``, ``date``, ``high``, ``low``, ``vwap``); ``adjClose`` does
not appear anywhere in this codebase's usage of this endpoint. This is
codebase evidence, not a live-response capture -- the controller should
confirm against a real response on the first live run (see Task 0.2 report,
"FMP field verification").

This module:

1. Extracts the candidate symbol list from a ``latest_open_prep_run.json``
   payload (mirroring ``open_prep.realtime_signals._load_watchlist``'s
   ``DEFAULT_TOP_N=0`` merge of ``ranked_v2`` + ``below_top_n_cutoff``
   overflow + ``enriched_quotes``) -- UNCHANGED symbol-sourcing logic.
2. Reshapes an ``FMPClient.get_historical_price_eod_full()`` response (per
   symbol) into :class:`FmpAdjustedEodBar` rows.
3. Builds a :class:`open_prep.a0_stream_state.StreamReference` per symbol
   from FMP-sourced, source-pure, adjusted EOD history and writes the
   reference JSON file in the exact list-of-objects shape
   ``services/a0_fast_detector/worker.py::_load_references`` consumes --
   UNCHANGED wire format.

Symbols with insufficient or missing qualifying history are SKIPPED, never
fabricated.

KNOWN OPEN CONFLICT (flagged, NOT resolved by this module -- see Task 0.2
report "Concerns"): ``open_prep.a0_stream_state.StreamReference.is_valid_for()``
hard-requires ``source.strip().lower().startswith("databento")``, and
``services/a0_fast_detector/worker.py::_load_references`` calls it on EVERY
row at load time, raising for the whole file if any row fails. An honestly
FMP-labeled reference (``source="fmp:adjusted-eod"``) will therefore
currently FAIL to load in the deployed A0-Fast worker as-is. This module
does not touch ``a0_stream_state.py`` / ``worker.py`` -- both are outside
this task's authorized scope, and resolving the Databento-only purity gate
(vs. an FMP-daily + Databento-live split source model) is a controller
decision, not something to silently paper over here.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from open_prep.a0_stream_state import StreamReference

logger = logging.getLogger(__name__)

DEFAULT_LOOKBACK_SESSIONS = 15
DEFAULT_CORPORATE_ACTION_VERSION = "fmp-adjusted-eod-v1"
DEFAULT_REFERENCE_VERSION_PREFIX = "fmp-bootstrap"
FMP_EOD_SOURCE = "fmp:adjusted-eod"


@dataclass(frozen=True, slots=True)
class FmpAdjustedEodBar:
    """One FMP-adjusted end-of-day session bar for a symbol.

    ``close`` is FMP's split/dividend-adjusted close from
    ``/stable/historical-price-eod/full`` (see module docstring, "FMP field
    verification" -- codebase-evidence based, not a live-captured response).
    """

    symbol: str
    session_date: str
    close: float
    volume: int
    source: str = FMP_EOD_SOURCE


def extract_candidate_symbols_from_open_prep_run(payload: dict[str, Any]) -> list[str]:
    """Extract the FULL open_prep production candidate universe.

    Mirrors ``open_prep.realtime_signals.RealtimeSignalsMonitor._load_watchlist``'s
    ``DEFAULT_TOP_N=0`` (ALL) merge: ``ranked_v2`` (top-scored) plus overflow
    rows from ``filtered_out_v2`` whose only exclusion reason is
    ``below_top_n_cutoff``, plus any symbol seen in ``enriched_quotes`` not
    already covered. This is the same ~900-symbol universe the realtime
    producer monitors -- NOT the smaller micro-cap shadow list.
    """
    seen: set[str] = set()
    symbols: list[str] = []

    def _add(symbol_raw: Any) -> None:
        symbol = str(symbol_raw or "").strip().upper()
        if symbol and symbol not in seen:
            seen.add(symbol)
            symbols.append(symbol)

    for row in payload.get("ranked_v2") or []:
        _add(row.get("symbol"))

    for row in payload.get("filtered_out_v2") or []:
        reasons = row.get("filter_reasons") or []
        if "below_top_n_cutoff" not in reasons:
            continue  # truly filtered out (e.g. price/volume floor) -- not part of the monitored universe
        _add(row.get("symbol"))

    for row in payload.get("enriched_quotes") or []:
        _add(row.get("symbol"))

    return symbols


def fmp_eod_response_to_bars(
    symbol: str,
    response: list[dict[str, Any]] | dict[str, Any],
    *,
    source: str = FMP_EOD_SOURCE,
) -> list[FmpAdjustedEodBar]:
    """Parse an ``FMPClient.get_historical_price_eod_full()`` response for one
    symbol into :class:`FmpAdjustedEodBar` rows.

    Accepts both response shapes ``get_historical_price_eod_full`` can
    return: a bare list of row dicts, or ``{"historical": [...]}`` -- the
    same dict-unwrap every other call site in this repo applies (see
    ``open_prep/run_open_prep.py::_fetch_symbol_atr``,
    ``open_prep/market_microstructure.py``). Rows missing ``date``/``close``/
    ``volume``, or with an unparseable date, are dropped rather than raising
    -- callers see a shorter history and the reference builder fails closed
    (insufficient-history) if too much is missing.
    """
    normalized_symbol = symbol.strip().upper()
    if isinstance(response, dict):
        rows = response.get("historical")
        rows = rows if isinstance(rows, list) else []
    elif isinstance(response, list):
        rows = response
    else:
        rows = []

    bars: list[FmpAdjustedEodBar] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        session_date = str(row.get("date") or "").strip()[:10]
        if not session_date:
            continue
        try:
            date.fromisoformat(session_date)
        except ValueError:
            continue
        close_raw = row.get("close")
        volume_raw = row.get("volume")
        if close_raw is None or volume_raw is None:
            continue
        try:
            close = float(close_raw)
            volume = int(float(volume_raw))
        except (TypeError, ValueError):
            continue
        bars.append(
            FmpAdjustedEodBar(
                symbol=normalized_symbol,
                session_date=session_date,
                close=close,
                volume=volume,
                source=source,
            )
        )
    return bars


def build_fmp_reference(
    *,
    symbol: str,
    bars: list[FmpAdjustedEodBar],
    as_of_session: str,
    lookback_sessions: int,
    reference_version: str,
    corporate_action_version: str,
) -> StreamReference:
    """Build previous-close and ADV from FMP-adjusted EOD history.

    Mirrors the validation shape of
    ``open_prep.a0_reference.build_databento_reference`` (strictly-prior
    sessions only, exact lookback window, source-purity + positive-close +
    minimum-volume gates) but is source-pure FMP instead of Databento.
    Deliberately a SEPARATE function from ``build_databento_reference``,
    which asserts a Databento-only source and stays as-is for its own
    (still Databento-sourced, still tested in ``tests/test_a0_reference.py``)
    use elsewhere -- this module does not modify that function.
    """
    normalized_symbol = symbol.strip().upper()
    as_of = date.fromisoformat(as_of_session)
    eligible = sorted(
        (
            bar
            for bar in bars
            if bar.symbol.strip().upper() == normalized_symbol and date.fromisoformat(bar.session_date) < as_of
        ),
        key=lambda bar: bar.session_date,
    )
    if lookback_sessions <= 0:
        raise ValueError("lookback_sessions must be positive")
    if len(eligible) < lookback_sessions:
        raise ValueError("insufficient FMP adjusted-EOD history")
    selected = eligible[-lookback_sessions:]
    if any(not bar.source.strip().lower().startswith("fmp") for bar in selected):
        raise ValueError("reference history is not source-pure FMP")
    if any(bar.close <= 0 or bar.volume < 1000 for bar in selected):
        raise ValueError("reference history contains invalid close or volume")
    if not reference_version or not corporate_action_version:
        raise ValueError("reference and corporate-action versions are required")
    average_volume = sum(bar.volume for bar in selected) / len(selected)
    return StreamReference(
        symbol=normalized_symbol,
        previous_close=selected[-1].close,
        average_daily_volume=average_volume,
        source=FMP_EOD_SOURCE,
        as_of_session=selected[-1].session_date,
        lookback_sessions=lookback_sessions,
        reference_version=reference_version,
        corporate_action_version=corporate_action_version,
    )


def build_reference_for_universe(
    symbols: list[str],
    bars_by_symbol: dict[str, list[FmpAdjustedEodBar]],
    *,
    as_of_session: str,
    reference_version: str,
    lookback_sessions: int = DEFAULT_LOOKBACK_SESSIONS,
    corporate_action_version: str = DEFAULT_CORPORATE_ACTION_VERSION,
) -> tuple[list[StreamReference], list[str]]:
    """Build a :class:`StreamReference` for every symbol with sufficient,
    source-pure, adjusted FMP EOD history.

    Returns ``(references, skipped_symbols)``. Skipped symbols lack enough
    qualifying history and are OMITTED rather than fabricated with a
    zero/garbage reference.
    """
    references: list[StreamReference] = []
    skipped: list[str] = []
    for symbol in symbols:
        normalized = symbol.strip().upper()
        bars = bars_by_symbol.get(normalized, [])
        try:
            reference = build_fmp_reference(
                symbol=normalized,
                bars=bars,
                as_of_session=as_of_session,
                lookback_sessions=lookback_sessions,
                reference_version=reference_version,
                corporate_action_version=corporate_action_version,
            )
        except ValueError as exc:
            logger.info("Skipping %s from A0 reference: %s", normalized, exc)
            skipped.append(normalized)
            continue
        references.append(reference)
    return references, skipped


def write_reference_file(references: list[StreamReference], path: Path) -> None:
    """Write references to the JSON list-of-objects shape
    ``services/a0_fast_detector/worker.py::_load_references`` consumes
    (a JSON array of ``StreamReference`` rows, NOT a symbol-keyed dict)."""
    payload = [asdict(reference) for reference in sorted(references, key=lambda ref: ref.symbol)]
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True), encoding="utf-8")
    tmp_path.replace(path)


def _reference_version(as_of_session: str) -> str:
    return f"{DEFAULT_REFERENCE_VERSION_PREFIX}-{as_of_session.replace('-', '')}"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Build the A0-Fast reference file (previous_close + ADV) for the full "
            "open_prep production candidate universe from FMP-adjusted EOD history."
        )
    )
    parser.add_argument(
        "--open-prep-run",
        required=True,
        help="Path to a latest_open_prep_run.json snapshot to source the candidate universe from.",
    )
    parser.add_argument(
        "--lookback-sessions",
        type=int,
        default=DEFAULT_LOOKBACK_SESSIONS,
        help="Number of prior completed sessions to average ADV over.",
    )
    parser.add_argument(
        "--as-of-session",
        default=None,
        help="ISO session date the reference is built as-of (default: today, US/Eastern).",
    )
    parser.add_argument(
        "--max-workers",
        type=int,
        default=10,
        help="Parallel FMP fetch workers (FMP Ultimate: 3000 req/min; a daily 1x run over ~900 symbols is well within budget).",
    )
    parser.add_argument("--output", required=True, help="Output path for the reference JSON file.")
    return parser


def main() -> int:
    """Live orchestration entrypoint. NOT exercised by unit tests -- requires
    FMP_API_KEY and live FMP calls. See Task 0.2 controller-verification:
    generate + spot-check previous_close against FMP for liquid names on a
    real trading day."""
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO").upper())
    load_dotenv()
    args = _build_parser().parse_args()

    fmp_api_key = os.getenv("FMP_API_KEY")
    if not fmp_api_key:
        print(json.dumps({"error": "FMP_API_KEY missing"}, indent=2, ensure_ascii=True))
        return 2

    from concurrent.futures import ThreadPoolExecutor, as_completed
    from zoneinfo import ZoneInfo

    from open_prep.macro import FMPClient

    as_of_session = args.as_of_session or datetime.now(ZoneInfo("America/New_York")).date().isoformat()
    as_of = date.fromisoformat(as_of_session)
    # Calendar-day buffer for `lookback_sessions` trading sessions, generous
    # enough to absorb weekends/holidays (matches the x4 heuristic
    # `databento_volatility_screener.list_recent_trading_days` uses).
    date_from = as_of - timedelta(days=max(args.lookback_sessions * 4, 30))

    run_payload = json.loads(Path(args.open_prep_run).expanduser().read_text(encoding="utf-8"))
    symbols = extract_candidate_symbols_from_open_prep_run(run_payload)
    if not symbols:
        print(json.dumps({"error": "no candidate symbols extracted from open_prep run"}, indent=2))
        return 2

    client = FMPClient.from_env()
    bars_by_symbol: dict[str, list[FmpAdjustedEodBar]] = {}

    def _fetch_one(symbol: str) -> tuple[str, list[FmpAdjustedEodBar]]:
        try:
            response = client.get_historical_price_eod_full(symbol, date_from, as_of)
        except Exception as exc:  # fail-soft: this symbol is skipped downstream, not the whole run
            logger.warning("FMP EOD fetch failed for %s: %s", symbol, exc)
            return symbol, []
        return symbol, fmp_eod_response_to_bars(symbol, response)

    with ThreadPoolExecutor(max_workers=max(1, args.max_workers)) as pool:
        futures = {pool.submit(_fetch_one, symbol): symbol for symbol in symbols}
        for future in as_completed(futures):
            symbol, bars = future.result()
            bars_by_symbol[symbol] = bars

    references, skipped = build_reference_for_universe(
        symbols,
        bars_by_symbol,
        as_of_session=as_of_session,
        reference_version=_reference_version(as_of_session),
        lookback_sessions=args.lookback_sessions,
    )
    write_reference_file(references, Path(args.output).expanduser())

    print(
        json.dumps(
            {
                "as_of_session": as_of_session,
                "candidate_symbols": len(symbols),
                "references_written": len(references),
                "skipped_symbols": len(skipped),
                "output": str(Path(args.output).expanduser()),
                "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
            },
            indent=2,
            ensure_ascii=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
