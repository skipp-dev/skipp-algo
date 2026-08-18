"""Daily quote-reference (previous_close + average_daily_volume) for the
open_prep production candidate universe.

This is the interface Task 1.3's ``DatabentoQuoteSource`` consumes for the
two fields FMP's batch-quote endpoint does NOT return (see Task 0.1's
``docs/databento_quote_row_contract.md``): ``previousClose`` and
``avgVolume``. It is intentionally decoupled from ``services/a0_fast_detector``:

- It does NOT import ``open_prep.a0_stream_state`` internals,
  ``open_prep/a0_stream_state.py``, or ``services/a0_fast_detector/*``.
- It writes its own artifact at its own path (``DEFAULT_OUTPUT_PATH``,
  default ``artifacts/open_prep/latest/quote_reference.json``) -- NOT
  ``services/a0_fast_detector/bootstrap/a0-reference.json`` -- so the
  A0-Fast worker's ``_load_references()`` never sees or loads it.
- Its row shape is a plain ``{previous_close, average_daily_volume,
  as_of_session, source}`` mapping, NOT a ``StreamReference``, and carries
  no ``is_valid_for()``/Databento-purity gate.

Why the split (2026-07-25 decision): A0-Fast's reference is deliberately
Databento-source-pure -- that is an intentional design contract (see
``services/a0_fast_detector/README.md``, "Sicherheitsvertrag": *"Referenzdatei
muss Previous Close und ADV aus Databento enthalten"*), so that its shadow
decisions stay uncontaminated by FMP for the FMP-vs-Databento parity
comparison. This module has a different consumer (the realtime signals
*producer*, via ``DatabentoQuoteSource``) and a different
constraint: ``previous_close``/``average_daily_volume`` are daily values
(not latency-critical -- only the live intraday bars are), and a Databento
``ohlcv-1d`` bar on ``EQUS.MINI`` is RAW/UNADJUSTED for corporate actions,
while FMP's EOD history is split/dividend-adjusted. Rather than bending
A0-Fast's intentionally narrow contract (or mislabeling a Databento-sourced
row as adjusted), this module sources its two fields from FMP's adjusted EOD
history directly and never touches A0-Fast's machinery at all.

Source: ``FMPClient.get_historical_price_eod_full`` ->
``/stable/historical-price-eod/full`` (``open_prep/macro.py:2048``).
``previous_close`` = the last adjusted close strictly before ``as_of_session``;
``average_daily_volume`` = the mean ``volume`` over the trailing
``lookback_sessions`` (default 15) prior sessions. No corporate-action flag
is needed here: FMP's EOD `close` already carries the adjustment, so
`source="fmp:adjusted-eod"` documents the provenance rather than asserting a
separate boolean.

FMP field verification (2026-07-25, no live network access in this
sandbox): the adjustment-carrying field is ``close`` -- NOT ``adjClose``.
Evidence: every existing production call site reading
``/stable/historical-price-eod/full`` rows in this repo
(``open_prep/run_open_prep.py::_fetch_symbol_atr``,
``open_prep/market_microstructure.py::_fetch_eod_closes``) reads ``close``
(plus ``volume``, ``date``, ``high``, ``low``, ``vwap``); ``adjClose`` does
not appear anywhere in this codebase's usage of this endpoint. This is
codebase evidence, not a live-response capture -- the controller should
confirm against a real response on the first live run (see Task 0.2 report).
"""

from __future__ import annotations

import argparse
import json
import logging
import os
from dataclasses import asdict, dataclass, replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from scripts.smc_atomic_write import atomic_write_text

from .macro import FMPClient

logger = logging.getLogger(__name__)

DEFAULT_LOOKBACK_SESSIONS = 15
FMP_EOD_SOURCE = "fmp:adjusted-eod"
# ADV provenance for the venue-consistent volume denominator (see
# "Databento-native ADV" section below). Matches the live feed's dataset
# (EQUS.MINI) so cumulative-volume/ADV ratios are subset/subset.
DATABENTO_ADV_SOURCE = "databento:equs-mini-ohlcv-1d"
# _volume_semantics (open_prep/realtime_signals.py) zeroes every ratio when
# avgVolume < 1000 -- a reference row under that floor is unusable, so the
# ADV builder omits such symbols fail-closed instead of emitting dead rows.
MIN_USABLE_ADV_SHARES = 1000.0
DEFAULT_OUTPUT_PATH = Path("artifacts/open_prep/latest") / "quote_reference.json"


# ---------------------------------------------------------------------------
# Universe sourcing (unchanged from the prior scripts/build_a0_reference.py
# implementation -- moved here verbatim per the 2026-07-25 decoupling).
# ---------------------------------------------------------------------------


def extract_candidate_symbols_from_open_prep_run(payload: dict[str, Any]) -> list[str]:
    """Extract the FULL open_prep production candidate universe.

    Mirrors ``open_prep.realtime_signals.RealtimeSignalsMonitor._load_watchlist``'s
    ``DEFAULT_TOP_N=0`` (ALL) merge: ``ranked_v2`` (top-scored) plus overflow
    rows from ``filtered_out_v2`` whose only exclusion reason is
    ``below_top_n_cutoff``, plus any symbol seen in ``enriched_quotes`` not
    already covered. This is the same ~900-symbol universe the realtime
    producer monitors -- NOT the smaller micro-cap A0-Fast shadow list.
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


# ---------------------------------------------------------------------------
# FMP-adjusted-EOD bar parsing
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class FmpAdjustedEodBar:
    """One FMP-adjusted end-of-day session bar for a symbol.

    ``close`` is FMP's split/dividend-adjusted close from
    ``/stable/historical-price-eod/full`` (see module docstring, "FMP field
    verification").
    """

    symbol: str
    session_date: str
    close: float
    volume: int
    source: str = FMP_EOD_SOURCE


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


# ---------------------------------------------------------------------------
# Reference row construction
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class QuoteReferenceRow:
    """One symbol's daily reference: previous_close + average_daily_volume.

    Deliberately NOT a ``StreamReference`` (no ``is_valid_for()``, no
    Databento-purity gate) -- a minimal, source-agnostic-on-the-wire mapping
    that only documents provenance via ``source``.
    """

    previous_close: float
    average_daily_volume: float
    as_of_session: str
    source: str = FMP_EOD_SOURCE


def build_quote_reference_row(
    *,
    symbol: str,
    bars: list[FmpAdjustedEodBar],
    as_of_session: str,
    lookback_sessions: int = DEFAULT_LOOKBACK_SESSIONS,
    source: str = FMP_EOD_SOURCE,
) -> QuoteReferenceRow:
    """Build previous-close and ADV from FMP-adjusted EOD history for one
    symbol.

    ``previous_close`` = the last adjusted close strictly before
    ``as_of_session``. ``average_daily_volume`` = the mean ``volume`` over
    the trailing ``lookback_sessions`` prior sessions. Raises ``ValueError``
    if there isn't enough qualifying (source-pure, positive-close,
    minimum-volume) history -- callers should skip the symbol, never
    fabricate a row.
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
    average_volume = sum(bar.volume for bar in selected) / len(selected)
    return QuoteReferenceRow(
        previous_close=selected[-1].close,
        average_daily_volume=average_volume,
        as_of_session=selected[-1].session_date,
        source=source,
    )


def build_quote_reference_for_universe(
    symbols: list[str],
    bars_by_symbol: dict[str, list[FmpAdjustedEodBar]],
    *,
    as_of_session: str,
    lookback_sessions: int = DEFAULT_LOOKBACK_SESSIONS,
) -> tuple[dict[str, QuoteReferenceRow], list[str]]:
    """Build a :class:`QuoteReferenceRow` for every symbol with sufficient,
    source-pure, adjusted FMP EOD history.

    Returns ``(rows_by_symbol, skipped_symbols)``. Skipped symbols lack
    enough qualifying history and are OMITTED rather than fabricated with a
    zero/garbage row.
    """
    rows: dict[str, QuoteReferenceRow] = {}
    skipped: list[str] = []
    for symbol in symbols:
        normalized = symbol.strip().upper()
        bars = bars_by_symbol.get(normalized, [])
        try:
            row = build_quote_reference_row(
                symbol=normalized,
                bars=bars,
                as_of_session=as_of_session,
                lookback_sessions=lookback_sessions,
            )
        except ValueError as exc:
            logger.info("Skipping %s from quote reference: %s", normalized, exc)
            skipped.append(normalized)
            continue
        rows[normalized] = row
    return rows, skipped


def write_quote_reference_file(rows: dict[str, QuoteReferenceRow], path: Path | str = DEFAULT_OUTPUT_PATH) -> None:
    """Write ``rows`` to the artifact JSON shape:
    ``{symbol: {previous_close, average_daily_volume, as_of_session, source}}``
    -- own path, own schema; never touches ``A0_FAST_REFERENCE_FILE``."""
    output_path = Path(path)
    payload = {symbol: asdict(row) for symbol, row in sorted(rows.items())}
    serialized = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True)
    atomic_write_text(serialized, output_path)


# ---------------------------------------------------------------------------
# Databento-native ADV (venue-consistent volume denominator)
#
# Live-verified 2026-07-28: EQUS.MINI is a venue SUBSET -- over 29 common
# sessions across eight liquid symbols its daily volume was only 2.6-4.9%
# of FMP's consolidated volume. With the FMP consolidated ADV as denominator,
# every databento-path volume_ratio ((volume/avgVolume)/expected_fraction) is
# depressed by roughly 20-38x: the volume
# regime reads >=80% of symbols as thin (HOLIDAY_SUSPECT -> all signals
# suspended) and the A0/A1/A2 volume-pace gates never fire. The fix is a
# venue-consistent denominator: average_daily_volume from EQUS.MINI
# ohlcv-1d history (subset/subset), while previous_close STAYS FMP's
# split/dividend-adjusted close (Databento daily bars are unadjusted --
# the very reason FMP was chosen for the price side, see module docstring).
# Known limitation: a split inside the lookback window skews the subset ADV
# for the affected sessions (raw volumes, no adjustment) -- bounded (~2x for
# a handful of symbol-days) versus the structural 20-38x mismatch this fixes.
# ---------------------------------------------------------------------------


def databento_daily_df_to_volume_rows(frame: Any) -> list[dict[str, Any]]:
    """Convert ``Historical.timeseries.get_range(...).to_df()`` output into
    ``{symbol, session_date, volume}`` rows.

    Layout verified live 2026-07-28: the frame is indexed by ``ts_event`` =
    00:00:00 UTC of the session date itself (weekend/holiday rows simply
    absent), with ``symbol`` and raw (unscaled) ``volume`` columns. Duck-typed
    iteration -- no pandas import needed here; malformed/negative rows are
    dropped rather than raising."""
    rows: list[dict[str, Any]] = []
    for ts_event, symbol_raw, volume_raw in zip(
        frame.index, frame["symbol"], frame["volume"], strict=True
    ):
        symbol = str(symbol_raw or "").strip().upper()
        if not symbol:
            continue
        try:
            volume = int(volume_raw)
        except (TypeError, ValueError):
            continue
        if volume < 0:
            continue
        session_date = str(ts_event.date().isoformat())
        rows.append({"symbol": symbol, "session_date": session_date, "volume": volume})
    return rows


def compute_databento_adv(
    volume_rows: list[dict[str, Any]],
    *,
    as_of_session: str,
    lookback_sessions: int = DEFAULT_LOOKBACK_SESSIONS,
) -> dict[str, float]:
    """Mean EQUS.MINI daily volume over the trailing ``lookback_sessions``
    sessions STRICTLY before ``as_of_session`` -- the same windowing contract
    as :func:`build_quote_reference_row`, so the two ADV sources are drop-in
    interchangeable. Symbols with insufficient history or a subset ADV below
    ``MIN_USABLE_ADV_SHARES`` are omitted (fail-closed, never fabricated)."""
    if lookback_sessions <= 0:
        raise ValueError("lookback_sessions must be positive")
    as_of = date.fromisoformat(as_of_session)
    volumes_by_symbol: dict[str, list[tuple[str, int]]] = {}
    for row in volume_rows:
        symbol = str(row.get("symbol") or "").strip().upper()
        session_date = str(row.get("session_date") or "")
        if not symbol or not session_date:
            continue
        try:
            if date.fromisoformat(session_date) >= as_of:
                continue
            volume = int(row.get("volume", -1))
        except (TypeError, ValueError):
            continue
        if volume < 0:
            continue
        volumes_by_symbol.setdefault(symbol, []).append((session_date, volume))

    adv_by_symbol: dict[str, float] = {}
    for symbol, dated_volumes in volumes_by_symbol.items():
        if len(dated_volumes) < lookback_sessions:
            continue
        selected = sorted(dated_volumes)[-lookback_sessions:]
        adv = sum(volume for _, volume in selected) / len(selected)
        if adv < MIN_USABLE_ADV_SHARES:
            continue
        adv_by_symbol[symbol] = adv
    return adv_by_symbol


def apply_databento_adv(
    rows_by_symbol: dict[str, QuoteReferenceRow],
    adv_by_symbol: dict[str, float],
) -> tuple[dict[str, QuoteReferenceRow], list[str]]:
    """Replace each FMP-built row's ``average_daily_volume`` with the
    databento subset ADV, recording both provenances in ``source``.

    Symbols without a databento ADV are DROPPED (returned as skipped), never
    left carrying the consolidated-ADV row -- a silent consolidated fallback
    would re-break the volume gates by roughly 20-38x for those symbols."""
    merged: dict[str, QuoteReferenceRow] = {}
    skipped: list[str] = []
    for symbol, row in rows_by_symbol.items():
        adv = adv_by_symbol.get(symbol)
        if adv is None:
            skipped.append(symbol)
            continue
        merged[symbol] = replace(
            row,
            average_daily_volume=float(adv),
            source=f"{row.source}+adv={DATABENTO_ADV_SOURCE}",
        )
    return merged, sorted(skipped)


def fetch_databento_daily_volume_rows(
    symbols: list[str],
    *,
    as_of_session: str,
    lookback_sessions: int = DEFAULT_LOOKBACK_SESSIONS,
    api_key: str | None = None,
    client: Any = None,
) -> list[dict[str, Any]]:
    """Fetch EQUS.MINI ``ohlcv-1d`` history for ``symbols`` and return
    ``{symbol, session_date, volume}`` rows.

    ``client`` is injectable for tests; production passes ``api_key`` and a
    ``databento.Historical`` client is constructed locally (local import so
    the FMP-only path and non-databento consumers never need the SDK).
    The calendar window mirrors ``main()``'s FMP ``date_from`` arithmetic:
    ``lookback_sessions * 4`` days (>= 30) absorbs weekends/holidays; the
    strictly-before-``as_of`` cut happens in :func:`compute_databento_adv`.
    Cost: verified 2026-07-28 -- ~900 symbols x ~40 days of 1d bars priced
    at $0.00 via ``metadata.get_cost``."""
    if client is None:
        import databento as db  # deferred: only the databento ADV path needs the SDK

        client = db.Historical(api_key)
    # F-V4-E1: route through the canonical retry helper — ~900 symbols x
    # >=30 days in one stream, and a single transient TLS reset /
    # RemoteDisconnected otherwise kills the whole daily rebuild while the
    # workflow keeps last-good silently (Grenzgänger-Sweep D2, 2026-08-18:
    # this was the only raw get_range call outside the guard's old glob).
    from databento_client import _databento_get_range_with_retry  # deferred with the SDK

    as_of = date.fromisoformat(as_of_session)
    start = as_of - timedelta(days=max(lookback_sessions * 4, 30))
    store = _databento_get_range_with_retry(
        client,
        context="quote_reference_adv",
        dataset="EQUS.MINI",
        schema="ohlcv-1d",
        symbols=list(symbols),
        stype_in="raw_symbol",
        start=start.isoformat(),
        end=as_of_session,
    )
    return databento_daily_df_to_volume_rows(store.to_df())


# ---------------------------------------------------------------------------
# Loader / serving interface -- what Task 1.3's DatabentoQuoteSource consumes
# ---------------------------------------------------------------------------


class QuoteReference:
    """Loads the quote-reference artifact and serves per-symbol lookups.

    This is the interface Task 1.3's ``DatabentoQuoteSource`` is expected to
    consume for ``previousClose``/``avgVolume``. Independent of A0-Fast: no
    ``is_valid_for()``, no Databento-purity gate, no dependency on
    ``open_prep.a0_stream_state`` or ``open_prep.a0_reference``.
    """

    def __init__(self, rows_by_symbol: dict[str, QuoteReferenceRow]) -> None:
        self._rows_by_symbol = rows_by_symbol
        # Set by load() so reload() can re-read the same artifact after the
        # out-of-band daily rebuild; None for a directly-constructed instance.
        self._source_path: Path | None = None

    @classmethod
    def load(cls, path: Path | str = DEFAULT_OUTPUT_PATH) -> QuoteReference:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("quote reference artifact must be a JSON object keyed by symbol")
        rows_by_symbol: dict[str, QuoteReferenceRow] = {}
        for symbol_raw, row_raw in payload.items():
            if not isinstance(row_raw, dict):
                continue
            symbol = str(symbol_raw).strip().upper()
            if not symbol:
                continue
            rows_by_symbol[symbol] = QuoteReferenceRow(
                previous_close=float(row_raw.get("previous_close") or 0.0),
                average_daily_volume=float(row_raw.get("average_daily_volume") or 0.0),
                as_of_session=str(row_raw.get("as_of_session") or ""),
                source=str(row_raw.get("source") or ""),
            )
        instance = cls(rows_by_symbol)
        instance._source_path = Path(path)
        return instance

    def reload(self) -> QuoteReference:
        """Re-read the artifact from the path this instance was loaded from,
        returning a fresh :class:`QuoteReference` with the new session's
        previous_close/ADV (rewritten out-of-band by
        ``python -m open_prep.quote_reference``). Raises ``ValueError`` if this
        instance was constructed directly rather than via :meth:`load` (no
        path to reload from)."""
        if self._source_path is None:
            raise ValueError("QuoteReference has no source path to reload from")
        return QuoteReference.load(self._source_path)

    def get(self, symbol: str) -> QuoteReferenceRow | None:
        return self._rows_by_symbol.get(symbol.strip().upper())

    def previous_close(self, symbol: str) -> float | None:
        row = self.get(symbol)
        return row.previous_close if row is not None else None

    def average_daily_volume(self, symbol: str) -> float | None:
        row = self.get(symbol)
        return row.average_daily_volume if row is not None else None

    def __contains__(self, symbol: str) -> bool:
        return symbol.strip().upper() in self._rows_by_symbol

    def __len__(self) -> int:
        return len(self._rows_by_symbol)


# ---------------------------------------------------------------------------
# Live orchestration CLI (not exercised by unit tests -- requires FMP_API_KEY
# and live FMP calls; see Task 0.2 controller-verification).
# ---------------------------------------------------------------------------


def _reference_as_of(as_of_session: str | None) -> str:
    if as_of_session:
        return as_of_session
    from zoneinfo import ZoneInfo

    return datetime.now(ZoneInfo("America/New_York")).date().isoformat()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Build the producer's quote-reference artifact (previous_close + ADV) for the full "
            "open_prep production candidate universe from FMP-adjusted EOD history. Fully "
            "decoupled from services/a0_fast_detector."
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
    parser.add_argument(
        "--output", default=str(DEFAULT_OUTPUT_PATH), help="Output path for the quote-reference JSON artifact."
    )
    parser.add_argument(
        "--fmp-output",
        help=(
            "Optional second artifact containing the unmodified FMP 15-session ADV. "
            "Written before a Databento ADV overlay so the active FMP producer can "
            "use an explicit same-source denominator without a second API fetch."
        ),
    )
    parser.add_argument(
        "--adv-source",
        choices=("fmp", "databento"),
        default="fmp",
        help=(
            "ADV denominator source. 'databento' replaces the FMP consolidated ADV with the "
            "EQUS.MINI ohlcv-1d subset ADV (venue-consistent with the live feed's cumulative "
            "volume -- see the Databento-native ADV section); requires DATABENTO_API_KEY. "
            "previous_close stays FMP-adjusted either way."
        ),
    )
    return parser


def main() -> int:
    """Live orchestration entrypoint. NOT exercised by unit tests -- requires
    FMP_API_KEY and live FMP calls. See Task 0.2 controller-verification."""
    from dotenv import load_dotenv

    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO").upper())
    load_dotenv()
    args = _build_parser().parse_args()

    fmp_api_key = os.getenv("FMP_API_KEY")
    if not fmp_api_key:
        print(json.dumps({"error": "FMP_API_KEY missing"}, indent=2, ensure_ascii=True))
        return 2
    databento_api_key = os.getenv("DATABENTO_API_KEY")
    if args.adv_source == "databento" and not databento_api_key:
        # Fail loud, not soft: silently keeping the FMP consolidated ADV would
        # re-break the databento volume gates 20-38x (see DATABENTO_ADV_SOURCE).
        print(json.dumps({"error": "DATABENTO_API_KEY missing (required for --adv-source databento)"}, indent=2))
        return 2

    from concurrent.futures import ThreadPoolExecutor, as_completed

    as_of_session = _reference_as_of(args.as_of_session)
    as_of = date.fromisoformat(as_of_session)
    # Calendar-day buffer for `lookback_sessions` trading sessions, generous
    # enough to absorb weekends/holidays.
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

    rows_by_symbol, skipped = build_quote_reference_for_universe(
        symbols,
        bars_by_symbol,
        as_of_session=as_of_session,
        lookback_sessions=args.lookback_sessions,
    )

    if args.fmp_output:
        write_quote_reference_file(rows_by_symbol, args.fmp_output)

    skipped_adv: list[str] = []
    if args.adv_source == "databento":
        # Any fetch failure propagates and fails the build (exit != 0): the
        # workflow's fail-soft branch then keeps the LAST-GOOD artifact on the
        # bot branch rather than publishing a consolidated-ADV reference.
        volume_rows = fetch_databento_daily_volume_rows(
            list(rows_by_symbol.keys()),
            as_of_session=as_of_session,
            lookback_sessions=args.lookback_sessions,
            api_key=databento_api_key,
        )
        adv_by_symbol = compute_databento_adv(
            volume_rows, as_of_session=as_of_session, lookback_sessions=args.lookback_sessions
        )
        rows_by_symbol, skipped_adv = apply_databento_adv(rows_by_symbol, adv_by_symbol)

    write_quote_reference_file(rows_by_symbol, args.output)

    print(
        json.dumps(
            {
                "as_of_session": as_of_session,
                "adv_source": args.adv_source,
                "candidate_symbols": len(symbols),
                "references_written": len(rows_by_symbol),
                "skipped_symbols": len(skipped),
                "skipped_adv_symbols": len(skipped_adv),
                "output": str(Path(args.output).expanduser()),
                "fmp_output": str(Path(args.fmp_output).expanduser()) if args.fmp_output else None,
                "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
            },
            indent=2,
            ensure_ascii=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
