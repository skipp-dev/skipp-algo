"""Post-open outcome backfill: fetch RTH price data and resolve null PnL fields.

Scans ``artifacts/open_prep/outcomes/`` for records where ``profitable_30m``
is still ``None``, fetches 1-minute OHLCV bars from Databento, calculates
P&L over every requested horizon, and atomically updates the outcome files.

**Horizons (A1, 2026-07-23).** Until A1 exactly one window was measured:
09:30→10:00 ET. Now 30 m / 60 m / 120 m / EOD are measured side by side
(``open_prep.outcomes.OUTCOME_HORIZONS``), each into its own fields
(``pnl_60m_pct`` / ``profitable_60m`` / …). The 30 m fields keep their old
names, their long-only semantics and their role as the record's
"is it resolved?" marker.

**Anchor.** Pre-open capsules are still anchored at the 09:30 open. A
record that carries ``fired_at`` (an intraday real-time signal) is anchored
at ITS fire time instead — an 11:00 signal must not be scored on the
09:30-10:00 span. The anchor actually used is disclosed per record in
``outcome_anchor`` / ``outcome_anchor_et``.

**What the numbers are not.** Every horizon is a cost-free
mark-to-market move: entry = open of the entry bar, exit = close of the
last bar in the window. There is no exit signal, and no fees, spread or
slippage are modelled. The longer the horizon the more that omission
matters, and it matters most on thin micro-caps where the quoted spread
alone can exceed the measured edge. Treat these figures as an upper bound.

Also back-fills the ``FeatureImportanceCollector`` samples so that the
calibration feedback loop has labeled data.

Usage::

    python -m open_prep.outcome_backfill                # last 5 outcome files (CLI default)
    python -m open_prep.outcome_backfill --date 2026-04-18
    python -m open_prep.outcome_backfill --lookback 1   # today only (library default)
    python -m open_prep.outcome_backfill --horizons 30m,eod
    python -m open_prep.outcome_backfill --backfill-horizons   # refill history
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import os
import tempfile
from collections.abc import Sequence
from datetime import date, datetime, timedelta
from datetime import time as dt_time
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo as _ZoneInfo

from smc_core._pytest_canonical_write_guard import (
    guard_against_canonical_repo_write_under_pytest,
)

_ET = _ZoneInfo("America/New_York")
_UTC = _ZoneInfo("UTC")

logger = logging.getLogger("open_prep.outcome_backfill")

# Re-use the canonical outcomes directory.
OUTCOMES_DIR = Path("artifacts/open_prep/outcomes")


def _outcomes_dir() -> Path:
    """Effective outcomes dir, resolved at call time (mirrors ``outcomes._outcomes_dir``).

    Local ``run_open_prep``/backfill runs set ``OPEN_PREP_OUTCOMES_DIR`` (a
    gitignored shadow dir) so they stop writing the CI-committed canonical
    ``artifacts/open_prep/outcomes/`` — a local write there leaves an untracked
    file that collides with the incoming CI commit on the next ``git pull``.
    Falls back to the module-level ``OUTCOMES_DIR`` (which the test-suite
    monkeypatches) when the env var is unset. Resolved at call time because
    ``run_open_prep`` loads ``.env`` only after importing this module."""
    override = os.environ.get("OPEN_PREP_OUTCOMES_DIR", "").strip()
    return Path(override) if override else OUTCOMES_DIR

# RTH session bounds (ET). ``_OPEN_TIME`` is the anchor for pre-open
# capsules; ``_CLOSE_TIME`` terminates the EOD horizon.
_OPEN_TIME = dt_time(9, 30)
_CLOSE_TIME = dt_time(16, 0)
# Window-completeness guards: the entry bar must print within the first
# _MAX_ENTRY_DELAY_MIN minutes and the exit bar must reach _MIN_WINDOW_MIN
# minutes, else the row stays unresolved instead of carrying a truncated
# window mislabelled as the 30-minute outcome. Since A1 the exit floor is
# per horizon (``OutcomeHorizon.min_window_min``); _MIN_WINDOW_MIN remains
# the 30m value and the module-level default.
_MAX_ENTRY_DELAY_MIN = 5
_MIN_WINDOW_MIN = 25
# EOD completeness: the closing bar must actually print near the close, or
# a symbol that stopped trading at lunchtime would get its 13:00 quote
# labelled as the end-of-day outcome.
_EOD_MAX_EXIT_GAP_MIN = 10

# Anchor sources, disclosed per record in ``outcome_anchor``.
_ANCHOR_MARKET_OPEN = "market_open"
_ANCHOR_FIRED_AT = "fired_at"

# Bar-fetch window (ET). Start is 09:29 so the 09:30 edge bar is present.
# The end depends on the requested horizons — see ``_fetch_end_time``.
_FETCH_START_TIME = dt_time(9, 29)
_FETCH_END_TIME_LEGACY = dt_time(10, 1)
_FETCH_END_TIME_FULL_DAY = dt_time(16, 1)

# Consolidated intraday parity source. EQUS.SUMMARY is daily-only and cannot
# resolve the 09:30-10:00 ET outcome window.
_DEFAULT_DATASET = "EQUS.MINI"
_DEFAULT_SCHEMA = "ohlcv-1m"

# Sentinel returned by ``_fetch_bars`` when Databento's historical API
# reports that the requested window lies after the dataset's currently
# available end (HTTP 422 ``data_start_after_available_end``). This is
# NOT a failure: the day's bars simply have not been published yet, and
# the next scheduled run will pick them up. Symbols hitting this are
# counted as ``deferred`` instead of ``failed`` so the workflow does not
# go red on a transient publication lag.
DATA_NOT_YET_PUBLISHED = object()


def _is_data_not_yet_published(exc: BaseException) -> bool:
    """True when *exc* is Databento's 'window not yet published' error.

    Matched on the error-code substring rather than the exception type so
    we don't need a hard import of ``databento`` here (the provider is
    injected and may be mocked in tests).
    """
    return "data_start_after_available_end" in str(exc)


# ── Core backfill ───────────────────────────────────────────────────────────

def _load_pending_dates(lookback_days: int = 1) -> list[date]:
    """Return dates that have at least one unresolved outcome record."""
    outcomes_dir = _outcomes_dir()
    if not outcomes_dir.exists():
        return []
    files = sorted(outcomes_dir.glob("outcomes_*.json"), reverse=True)
    pending: list[date] = []
    loaded = 0
    for path in files:
        if loaded >= lookback_days:
            break
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
            if isinstance(data, list) and any(
                r.get("profitable_30m") is None for r in data
            ):
                # Extract date from filename pattern outcomes_YYYY-MM-DD.json
                stem = path.stem  # outcomes_2026-04-18
                dt_str = stem.replace("outcomes_", "")
                pending.append(date.fromisoformat(dt_str))
            loaded += 1
        except Exception:
            logger.warning("Failed to inspect outcome file: %s", path)
    return sorted(pending)


def _load_outcome_file(run_date: date) -> tuple[Path, list[dict[str, Any]]]:
    """Load a single day's outcome records."""
    path = _outcomes_dir() / f"outcomes_{run_date.isoformat()}.json"
    if not path.exists():
        return path, []
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    return path, data if isinstance(data, list) else []


def _save_outcome_file(path: Path, records: list[dict[str, Any]]) -> None:
    """Atomically overwrite an outcome JSON file."""
    guard_against_canonical_repo_write_under_pytest(
        path.parent,
        canonical_relative_paths=("artifacts/open_prep/outcomes",),
        caller="_save_outcome_file",
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(records, fh, indent=2, default=str, allow_nan=False)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_path, path)
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _parse_fired_at(raw: Any) -> datetime | None:
    """Parse a ``fired_at`` value into an aware datetime, or ``None``.

    Accepts both shapes the realtime engine emits: an ISO-8601 string
    (``RealtimeSignal.fired_at``) and epoch seconds
    (``RealtimeSignal.fired_epoch``, and ``terminal_export``'s
    ``time.time()``). A naive ISO string is read as UTC — the repo-wide
    convention (``datetime.now(UTC).isoformat()``).
    """
    if raw is None or isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)):
        value = float(raw)
        if not math.isfinite(value) or value <= 0:
            return None
        return datetime.fromtimestamp(value, tz=_UTC)
    text = str(raw).strip()
    if not text:
        return None
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=_UTC)


def _resolve_anchor(fired_at: Any, run_date: date) -> tuple[datetime, str]:
    """Return ``(anchor_dt_et, anchor_source)`` for a record.

    Pre-open capsules keep the 09:30 ET anchor. An intraday real-time
    signal is anchored at its own ``fired_at`` — measuring an 11:00 signal
    on the 09:30-10:00 span would be an outright wrong number, not merely
    an imprecise one.

    Falls back to the open (and says so via the returned source) when
    ``fired_at`` is absent, unparseable, belongs to another date, or lands
    before the open: pre-market bars are outside the fetched window, so a
    07:15 fire cannot be measured from its own timestamp.
    """
    open_dt = datetime.combine(run_date, _OPEN_TIME, tzinfo=_ET)
    parsed = _parse_fired_at(fired_at)
    if parsed is None:
        if fired_at not in (None, ""):
            logger.debug("Unusable fired_at %r — anchoring at the open", fired_at)
        return open_dt, _ANCHOR_MARKET_OPEN
    anchor = parsed.astimezone(_ET)
    if anchor.date() != run_date:
        logger.debug(
            "fired_at %s is not on the record's date %s — anchoring at the open",
            anchor.isoformat(), run_date,
        )
        return open_dt, _ANCHOR_MARKET_OPEN
    if anchor <= open_dt:
        return open_dt, _ANCHOR_MARKET_OPEN
    return anchor, _ANCHOR_FIRED_AT


def _horizon_exit_dt(
    horizon: Any, anchor: datetime, close_dt: datetime,
) -> datetime:
    """Exclusive end of *horizon*'s window (the EOD horizon ends at the close)."""
    if horizon.minutes is None:
        return close_dt
    return anchor + timedelta(minutes=horizon.minutes)


def compute_pnl_from_bars(
    bars_df: Any,
    symbol: str,
    run_date: date,
    *,
    direction: str = "long",
    atr_pct: float | None = None,
    fired_at: Any = None,
    horizons: Sequence[str] | None = None,
) -> dict[str, Any] | None:
    """Calculate per-horizon P&L + triple-barrier label from 1-min OHLCV bars.

    Legacy fields (``profitable_30m``, ``pnl_30m_pct``) stay LONG-only for
    backward compatibility with existing analytics. Direction-aware fields
    (eval-findings B1, 2026-06-11) sign the PnL by the intended trade
    direction so short-side setups (GAP_FADE) stop being mislabeled.

    Horizons (A1, 2026-07-23): every key in *horizons* (default: all of
    ``OUTCOME_HORIZONS``) is measured into its own field quartet. Entry is
    shared — the first bar at/after the anchor — while each horizon gets
    its own exit bar and its own completeness floor. A horizon whose window
    is truncated or runs past the close stays ``None``; it is never filled
    with a shorter window's number.

    Anchor: the 09:30 open for pre-open capsules, ``fired_at`` for intraday
    real-time signals (see :func:`_resolve_anchor`). Disclosed in the
    result as ``outcome_anchor`` / ``outcome_anchor_et``.

    Triple-barrier label (eval-findings B2) stays tied to the PRIMARY (30 m)
    horizon: entry at the anchor bar; profit target at ``entry ± 1×ATR%``,
    stop at ``entry ∓ 0.5×ATR%`` (signs flipped for shorts), time barrier at
    the 30 m mark. Falls back to fixed 1.0%/0.5% barriers when *atr_pct* is
    unusable (``tb_barrier_source`` discloses which was used). Stop wins ties
    when both barriers are touched inside the same 1-min bar (conservative).
    When the 30 m window itself is unresolved, ``label_tb`` is ``None`` too.

    P&L is a cost-free mark-to-market move — no exit signal, no fees, no
    spread, no slippage. See the module docstring.

    Returns the label dict, or ``None`` when no horizon at all could be
    resolved — no bars, no valid entry bar (later than
    ``_MAX_ENTRY_DELAY_MIN``), a non-finite entry price, or every requested
    window truncated below its ``min_window_min`` floor.
    """
    import pandas as pd

    from .outcomes import DEFAULT_HORIZON, HORIZON_KEYS, get_horizon, horizon_fields

    keys = tuple(horizons) if horizons else HORIZON_KEYS
    specs = [get_horizon(key) for key in keys]

    if bars_df is None or bars_df.empty:
        return None

    # Filter to this symbol if the DataFrame contains multiple symbols.
    sym_df = bars_df[bars_df["symbol"] == symbol] if "symbol" in bars_df.columns else bars_df

    if sym_df.empty:
        return None

    # Build timezone-aware ET timestamps for the target window.
    anchor_dt, anchor_source = _resolve_anchor(fired_at, run_date)
    close_dt = datetime.combine(run_date, _CLOSE_TIME, tzinfo=_ET)

    # Databento timestamps are typically in UTC — convert index/column.
    ts_col = None
    for candidate in ("ts_event", "timestamp", "ts_recv"):
        if candidate in sym_df.columns:
            ts_col = candidate
            break

    if ts_col is None and isinstance(sym_df.index, pd.DatetimeIndex):
        sym_df = sym_df.copy()
        sym_df["_ts"] = sym_df.index
        ts_col = "_ts"

    if ts_col is None:
        logger.warning("No timestamp column found for %s", symbol)
        return None

    sym_df = sym_df.copy()
    sym_df["_et"] = pd.to_datetime(sym_df[ts_col], utc=True).dt.tz_convert(_ET)

    # Open bar: first 1-min bar at or after the anchor. Window-completeness
    # guard: the entry bar must print within the first _MAX_ENTRY_DELAY_MIN
    # minutes — otherwise a halted/thin open would get a silently truncated
    # (e.g. 7-minute) return labelled as the 30-minute outcome.
    open_mask = sym_df["_et"] >= anchor_dt
    if not open_mask.any():
        return None
    open_bar = sym_df.loc[open_mask].iloc[0]
    if open_bar["_et"] > anchor_dt + timedelta(minutes=_MAX_ENTRY_DELAY_MIN):
        return None

    entry_price = float(open_bar["open"])
    # A non-finite entry price (e.g. +inf/NaN from a corrupt bar) slips past
    # a bare `<= 0` check and makes pnl_pct NaN, which would still be written
    # as a normal-looking (e.g. profitable_30m=False) outcome. Reject so the
    # record stays unresolved instead of being labelled with NaN.
    if not math.isfinite(entry_price) or entry_price <= 0:
        return None

    # Direction sign (B1): a successful short fade has NEGATIVE raw return
    # but POSITIVE signed PnL.
    sign = -1.0 if str(direction).lower() == "short" else 1.0

    result: dict[str, Any] = {}
    resolved: list[str] = []
    primary_exit_mask = None
    for spec in specs:
        fields = horizon_fields(spec.key)
        for name in fields.values():
            result[name] = None

        exit_dt = _horizon_exit_dt(spec, anchor_dt, close_dt)
        # Exit bar: last 1-min bar before the horizon end and strictly AFTER
        # the entry bar — the fetch window starts at 09:29, so an unbounded
        # mask could pick the 09:29 edge bar as "exit" for a symbol whose
        # first trade printed late (a reversed, pre-market-anchored PnL).
        # Also require min_window_min minutes FROM THE ENTRY BAR (not the
        # anchor) so a late entry can't carry a truncated window as the label.
        exit_mask = (sym_df["_et"] < exit_dt) & (sym_df["_et"] > open_bar["_et"])
        if not exit_mask.any():
            continue
        exit_bar = sym_df.loc[exit_mask].iloc[-1]
        if exit_bar["_et"] < open_bar["_et"] + timedelta(minutes=spec.min_window_min):
            continue
        # EOD only: the closing bar must actually print near the close, or a
        # symbol that stopped trading at lunchtime gets its 13:00 quote
        # labelled as the end-of-day outcome.
        if spec.minutes is None and exit_bar["_et"] < close_dt - timedelta(
            minutes=_EOD_MAX_EXIT_GAP_MIN,
        ):
            continue

        exit_price = float(exit_bar["close"])
        if not math.isfinite(exit_price):
            continue

        pnl_pct = round((exit_price - entry_price) / entry_price * 100, 4)
        pnl_signed = round(pnl_pct * sign, 4)
        result[fields["pnl"]] = pnl_pct
        result[fields["pnl_signed"]] = pnl_signed
        result[fields["profitable"]] = pnl_pct > 0
        result[fields["profitable_directional"]] = pnl_signed > 0
        resolved.append(spec.key)
        if spec.key == DEFAULT_HORIZON:
            primary_exit_mask = exit_mask

    if not resolved:
        return None

    # Triple-barrier walk (B2) over the bars inside the PRIMARY entry→exit
    # window. Left None when the primary horizon itself is unresolved — a
    # barrier label for a window that does not exist would be fabricated.
    label_tb = None
    tb_barrier_source = None
    if primary_exit_mask is not None:
        if atr_pct is not None and math.isfinite(atr_pct) and atr_pct > 0:
            target_pct, stop_pct = atr_pct, 0.5 * atr_pct
            tb_barrier_source = "atr"
        else:
            target_pct, stop_pct = 1.0, 0.5
            tb_barrier_source = "default"
        if sign > 0:
            target_level = entry_price * (1 + target_pct / 100.0)
            stop_level = entry_price * (1 - stop_pct / 100.0)
        else:
            target_level = entry_price * (1 - target_pct / 100.0)
            stop_level = entry_price * (1 + stop_pct / 100.0)

        window = sym_df.loc[open_mask & primary_exit_mask].sort_values("_et")
        for _, bar in window.iterrows():
            bar_high = float(bar["high"])
            bar_low = float(bar["low"])
            if sign > 0:
                if bar_low <= stop_level:
                    label_tb = "stop"
                    break
                if bar_high >= target_level:
                    label_tb = "target"
                    break
            else:
                if bar_high >= stop_level:
                    label_tb = "stop"
                    break
                if bar_low <= target_level:
                    label_tb = "target"
                    break
        if label_tb is None:
            primary_signed = result[horizon_fields(DEFAULT_HORIZON)["pnl_signed"]]
            label_tb = "timeout_win" if primary_signed > 0 else "timeout_loss"

    result["label_tb"] = label_tb
    result["profitable_tb"] = (
        label_tb in ("target", "timeout_win") if label_tb is not None else None
    )
    result["tb_barrier_source"] = tb_barrier_source
    result["outcome_anchor"] = anchor_source
    result["outcome_anchor_et"] = anchor_dt.isoformat()
    result["outcome_horizons_resolved"] = resolved
    return result


def _fetch_end_time(
    horizons: Sequence[str], *, has_intraday_anchor: bool,
) -> dt_time:
    """End of the bar-fetch window for the requested *horizons*.

    Widening the query from 32 minutes to the full session multiplies the
    fetched data volume, so we only do it when something actually needs the
    later bars: any horizon beyond the primary 30 m one, or any pending
    record anchored intraday (a 15:00 signal needs 15:30 bars even for the
    30 m horizon). A pure legacy run keeps the original narrow window.
    """
    from .outcomes import DEFAULT_HORIZON

    if has_intraday_anchor or any(key != DEFAULT_HORIZON for key in horizons):
        return _FETCH_END_TIME_FULL_DAY
    return _FETCH_END_TIME_LEGACY


def _fetch_bars(
    provider: Any,
    symbols: list[str],
    run_date: date,
    *,
    dataset: str = _DEFAULT_DATASET,
    schema: str = _DEFAULT_SCHEMA,
    end_time: dt_time = _FETCH_END_TIME_LEGACY,
) -> Any:
    """Fetch 1-min OHLCV bars from 09:29 ET up to *end_time*.

    ``EQUS.MINI`` / ``ohlcv-1m`` serves the whole session, so the extended
    horizons only need a later ``end`` — see :func:`_fetch_end_time`.

    Returns a pandas DataFrame, ``DATA_NOT_YET_PUBLISHED`` when the
    window is not yet available upstream, or ``None`` on failure.
    """
    # Start at 09:29 to ensure we have the 09:30 edge bar.
    start_dt = datetime.combine(run_date, _FETCH_START_TIME, tzinfo=_ET)
    end_dt = datetime.combine(run_date, end_time, tzinfo=_ET)

    try:
        store = provider.get_range(
            context="outcome_backfill",
            dataset=dataset,
            symbols=symbols,
            schema=schema,
            start=start_dt.isoformat(),
            end=end_dt.isoformat(),
        )
        return store.to_df()
    except Exception as exc:
        if _is_data_not_yet_published(exc):
            logger.info(
                "Bars for %s not yet published upstream "
                "(data_start_after_available_end) — deferring to a "
                "later run.",
                run_date,
            )
            return DATA_NOT_YET_PUBLISHED
        logger.warning(
            "Databento fetch failed for %s (%s): %s",
            run_date,
            ", ".join(symbols[:5]),
            type(exc).__name__,
            exc_info=True,
        )
        return None


def _needs_backfill(
    record: dict[str, Any],
    horizons: Sequence[str],
    *,
    backfill_horizons: bool,
) -> bool:
    """Is *record* still pending for this run?

    Default (unchanged behaviour): a record is pending exactly while its
    primary label ``profitable_30m`` is ``None``. With *backfill_horizons*
    an already-30m-resolved record from before A1 also counts as pending
    while any requested horizon has no label yet — the opt-in that fills
    ``pnl_60m_pct`` & friends into history. It is opt-in because it makes
    the run re-fetch bars for days that are otherwise done.
    """
    from .outcomes import horizon_fields

    if record.get("profitable_30m") is None:
        return True
    if not backfill_horizons:
        return False
    return any(
        record.get(horizon_fields(key)["profitable"]) is None for key in horizons
    )


def backfill_outcomes(
    *,
    target_dates: list[date] | None = None,
    lookback_days: int = 1,
    provider: Any | None = None,
    dataset: str = _DEFAULT_DATASET,
    dry_run: bool = False,
    horizons: Sequence[str] | None = None,
    backfill_horizons: bool = False,
) -> dict[str, Any]:
    """Main entry point: resolve null outcomes for the given dates.

    Parameters
    ----------
    target_dates
        Explicit list of dates to backfill. If ``None``, scans the last
        ``lookback_days`` outcome files for unresolved records.
    lookback_days
        How many recent outcome files to scan when ``target_dates`` is
        not provided.
    provider
        A ``MarketDataProvider`` instance. If ``None``, instantiates a
        ``DabentoProvider`` from the environment.
    dataset
        Databento dataset identifier.
    dry_run
        If ``True``, compute PnL but do not write files.
    horizons
        Which measurement windows to fill (default: all of
        ``OUTCOME_HORIZONS``). The primary ``30m`` horizon is always
        included — it doubles as the record's resolved marker.
    backfill_horizons
        Opt-in: also re-measure records that already have a 30m label but
        are missing one of the longer horizons (records written before
        A1). Off by default so the routine daily run neither re-fetches
        history nor rewrites settled files.

    Returns
    -------
    dict
        Summary with counts of resolved, partial, skipped, failed records.
        ``partial`` counts rows where a longer horizon resolved but the
        30m one could not (e.g. a 15:20 signal, whose 30m window runs past
        the close) — those rows are written but stay pending for 30m.
    """
    from .outcomes import DEFAULT_HORIZON, HORIZON_KEYS, horizon_fields

    keys = tuple(horizons) if horizons else HORIZON_KEYS
    if DEFAULT_HORIZON not in keys:
        keys = (DEFAULT_HORIZON, *keys)

    if provider is None:
        from databento_provider import DabentoProvider
        provider = DabentoProvider()

    dates = target_dates or _load_pending_dates(lookback_days)
    if not dates:
        logger.info("No pending outcome dates to backfill.")
        return {
            "resolved": 0, "partial": 0, "skipped": 0, "failed": 0,
            "deferred": 0, "dates_processed": 0,
        }

    total_resolved = 0
    total_partial = 0
    total_skipped = 0
    total_failed = 0
    total_deferred = 0

    for run_date in dates:
        path, records = _load_outcome_file(run_date)
        if not records:
            logger.info("No records for %s, skipping.", run_date)
            continue

        pending = [
            r for r in records
            if _needs_backfill(r, keys, backfill_horizons=backfill_horizons)
        ]
        # Collect symbols that need backfill.
        pending_symbols = [r["symbol"] for r in pending if r.get("symbol")]
        if not pending_symbols:
            logger.info("All outcomes already resolved for %s.", run_date)
            total_skipped += len(records)
            continue

        # Fetch bars for all pending symbols in one batch. Intraday-anchored
        # rows need bars past 10:01 even for the 30m horizon.
        bars_df = _fetch_bars(
            provider, pending_symbols, run_date, dataset=dataset,
            end_time=_fetch_end_time(
                keys,
                has_intraday_anchor=any(r.get("fired_at") for r in pending),
            ),
        )

        if bars_df is DATA_NOT_YET_PUBLISHED:
            # Transient: the day's bars are not published yet. Leave the
            # records unresolved so the next scheduled run retries them.
            # Still account for the rest of the file so the summary stays
            # accurate (Copilot finding on #2677): already-resolved rows
            # count as skipped, structurally-invalid unresolved rows
            # (missing symbol) as failed.
            total_deferred += len(pending_symbols)
            total_skipped += sum(
                1 for r in records if r.get("profitable_30m") is not None
            )
            total_failed += sum(
                1
                for r in records
                if r.get("profitable_30m") is None and not r.get("symbol")
            )
            continue

        updated = False
        for rec in records:
            if not _needs_backfill(rec, keys, backfill_horizons=backfill_horizons):
                total_skipped += 1
                continue

            symbol = rec.get("symbol")
            if not symbol:
                total_failed += 1
                continue

            _atr_raw = rec.get("atr_pct")
            try:
                _atr_val = float(_atr_raw) if _atr_raw is not None else None
            except (TypeError, ValueError):
                _atr_val = None
            result = compute_pnl_from_bars(
                bars_df,
                symbol,
                run_date,
                direction=str(rec.get("direction") or "long"),
                atr_pct=_atr_val,
                fired_at=rec.get("fired_at"),
                horizons=keys,
            )
            if result is None:
                logger.debug("No bar data for %s on %s", symbol, run_date)
                total_failed += 1
                continue

            # Per-horizon labels. Unresolved horizons write back None, never
            # a substitute value — the reader must be able to tell "measured
            # flat" from "not measurable".
            for key in keys:
                for name in horizon_fields(key).values():
                    rec[name] = result[name]
            # Triple-barrier labels (eval B1/B2) + anchor disclosure.
            rec["label_tb"] = result["label_tb"]
            rec["profitable_tb"] = result["profitable_tb"]
            rec["tb_barrier_source"] = result["tb_barrier_source"]
            rec["outcome_anchor"] = result["outcome_anchor"]
            rec["outcome_anchor_et"] = result["outcome_anchor_et"]
            if rec["profitable_30m"] is None:
                total_partial += 1
            else:
                total_resolved += 1
            updated = True

        if updated and not dry_run:
            _save_outcome_file(path, records)
            logger.info(
                "Updated %s: %d resolved, %d failed",
                path.name,
                sum(1 for r in records if r.get("profitable_30m") is not None),
                sum(1 for r in records if r.get("profitable_30m") is None),
            )

    summary = {
        "resolved": total_resolved,
        "partial": total_partial,
        "skipped": total_skipped,
        "failed": total_failed,
        "unresolved_no_bars": total_failed,  # alias of "failed" (unresolved on EVERY horizon: no-bars, missing-symbol, truncated-window — rows resolved on a longer horizon only are counted in "partial" since A1); WP-D1 survivorship, summary-only (not in the run log)
        "deferred": total_deferred,
        "dates_processed": len(dates),
    }
    logger.info("Backfill complete: %s", summary)
    return summary


# ── Feature importance backfill ─────────────────────────────────────────────

def backfill_feature_importance(
    lookback_days: int = 7,
) -> int:
    """Re-scan outcome files and update feature importance JSONL samples.

    Returns the number of labeled samples written.
    """
    from .outcomes import (
        FEATURE_KEYS,
        FEATURE_TO_WEIGHT_KEY,
        FeatureImportanceCollector,
        _load_outcomes_range,
    )

    records = _load_outcomes_range(lookback_days)
    labeled = [r for r in records if r.get("profitable_30m") is not None]
    if not labeled:
        return 0

    # c10b era-gate (2026-06-11): legacy outcome records — written before
    # prepare_outcome_snapshot() persisted the weighted score components —
    # carry NO *_component keys. Defaulting those to 0.0 fabricated
    # all-zero feature vectors for every FI report since 2026-04-30.
    # Skip records without the full component schema instead of laundering
    # absence into measurements.
    component_complete = [
        r for r in labeled
        if all(r.get(key) is not None for key in FEATURE_TO_WEIGHT_KEY)
    ]
    skipped = len(labeled) - len(component_complete)
    if skipped:
        logger.warning(
            "FI backfill: skipped %d/%d labeled records without persisted "
            "score components (legacy pre-fix outcome files)",
            skipped,
            len(labeled),
        )
    if not component_complete:
        return 0

    collector = FeatureImportanceCollector()
    for rec in component_complete:
        breakdown: dict[str, float] = {}
        for key in FEATURE_KEYS:
            # The era gate above only requires the WEIGHTED component keys.
            # Pass-through features added later (e.g. news_directional_score,
            # 2026-07-08) are absent from older in-era records — skip them
            # instead of fabricating 0.0, which would launder "not measured"
            # into "measured neutral" (the exact failure the gate exists for).
            if rec.get(key) is None:
                continue
            breakdown[key] = float(rec[key] or 0.0)
        # Direction-signed label (B1 parity, 2026-07-13): the FI → FDR →
        # weight-tuning chain trains on the TRADE-INTENT outcome, matching
        # compute_hit_rates — the legacy long-only label sign-inverts short
        # setups (GAP_FADE). Fall back for records predating the directional
        # fields; the reader-side directional-era gate excludes pre-cutover
        # FI samples so two label semantics never mix in one training set.
        label = rec.get("profitable_30m_directional")
        if label is None:
            label = rec["profitable_30m"]
        pnl_for_fi = rec.get("pnl_30m_pct_signed")
        if pnl_for_fi is None:
            pnl_for_fi = rec.get("pnl_30m_pct", 0.0)
        collector.record(
            symbol=rec.get("symbol", ""),
            score_breakdown=breakdown,
            total_score=float(rec.get("score", 0.0) or 0.0),
            confidence_tier=rec.get("confidence_tier", "STANDARD"),
            profitable_30m=label,
            pnl_30m_pct=float(pnl_for_fi or 0.0),
            run_date=rec.get("date"),
        )

    count = collector.sample_count
    if count > 0:
        collector.flush_to_disk()

    return count


# ── CLI ─────────────────────────────────────────────────────────────────────

def _horizon_list(raw: str) -> list[str]:
    """argparse type for ``--horizons``: a comma-separated horizon key list.

    Rejects unknown keys, and rejects dropping the primary ``30m`` horizon —
    ``profitable_30m`` is the record's resolved-marker, so a run without it
    would silently change what "resolved" means.
    """
    from .outcomes import DEFAULT_HORIZON, HORIZON_KEYS

    keys = [part.strip() for part in str(raw).split(",") if part.strip()]
    unknown = [key for key in keys if key not in HORIZON_KEYS]
    if unknown:
        raise argparse.ArgumentTypeError(
            f"unknown horizon(s): {', '.join(unknown)} "
            f"(known: {', '.join(HORIZON_KEYS)})",
        )
    if DEFAULT_HORIZON not in keys:
        raise argparse.ArgumentTypeError(
            f"the primary horizon {DEFAULT_HORIZON!r} cannot be dropped",
        )
    return keys


def build_parser() -> argparse.ArgumentParser:
    from .outcomes import HORIZON_KEYS

    parser = argparse.ArgumentParser(
        description="Backfill post-open outcomes for Signal Replay.",
    )
    parser.add_argument(
        "--date",
        type=str,
        default=None,
        help="Specific date to backfill (YYYY-MM-DD). Default: scan recent files.",
    )
    parser.add_argument(
        "--horizons",
        type=_horizon_list,
        default=list(HORIZON_KEYS),
        help=(
            "Comma-separated measurement windows to fill "
            f"(default: {','.join(HORIZON_KEYS)}). '30m' is mandatory. "
            "Restricting to '30m' also narrows the Databento query back to "
            "the legacy 09:29-10:01 window."
        ),
    )
    parser.add_argument(
        "--backfill-horizons",
        action="store_true",
        help=(
            "Also re-measure records that already carry a 30m label but no "
            "longer-horizon labels (files written before A1). Off by default "
            "— it re-fetches bars for days that are otherwise settled."
        ),
    )
    parser.add_argument(
        "--lookback",
        type=int,
        default=5,
        help="Number of recent outcome files to scan for unresolved records (default: 5).",
    )
    parser.add_argument(
        "--dataset",
        type=str,
        default=_DEFAULT_DATASET,
        help=f"Databento dataset (default: {_DEFAULT_DATASET}).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Compute PnL without writing files.",
    )
    parser.add_argument(
        "--feature-importance",
        action="store_true",
        help="Also backfill feature importance samples from resolved outcomes.",
    )
    parser.add_argument(
        "--require-progress",
        action="store_true",
        help=(
            "Exit 3 when the run made zero progress (resolved, "
            "failed, skipped AND deferred all == 0). "
            "Use this in scheduled workflows that should never "
            "silently no-op (audit finding F-09)."
        ),
    )
    parser.add_argument(
        "--ab-arm-labels",
        action="store_true",
        help=(
            "Also resolve 30m labels for the §G3 A/B arm records into "
            "artifacts/open_prep/ab_arms/labels_<day>.json (separate store — "
            "never into outcomes_<day>.json). See backfill_ab_arm_labels."
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Backfill outcomes and return a process exit code.

    Returns:
        ``0`` for normal runs — including runs with per-symbol failures,
        as long as at least one record was resolved (or nothing failed).
        Per-symbol failures are expected for delisted/halted symbols and
        are preserved in the JSON run log instead of failing the run.
        ``2`` only when the run made zero progress while failing
        (``resolved == 0 and failed > 0``) — loud non-zero exit so a
        scheduled workflow surfaces a systemic failure instead of
        silently succeeding (ENG-WS4-01 DoD: 'Fehlfaelle sind sichtbar
        und nicht still').
        ``3`` when ``--require-progress`` is set and the run made no
        progress at all (F-09 tripwire).
    """
    parser = build_parser()
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
    )
    # Install the same secret-scrubbing log filter the other unattended
    # entrypoints use (run_open_prep.py, streamlit_terminal.py). This module's
    # exception logging (e.g. "Databento fetch failed ... %s", exc) can echo a
    # provider URL/key in the raw message; the redaction net must be armed here
    # too. Local import keeps line-pinned sites above stable.
    from open_prep.log_redaction import apply_global_log_redaction
    apply_global_log_redaction()

    target_dates: list[date] | None = None
    if args.date:
        target_dates = [date.fromisoformat(args.date)]

    summary = backfill_outcomes(
        target_dates=target_dates,
        lookback_days=args.lookback,
        dataset=args.dataset,
        dry_run=args.dry_run,
        horizons=args.horizons,
        backfill_horizons=args.backfill_horizons,
    )

    print(
        f"Backfill complete: {summary['resolved']} resolved, "
        f"{summary.get('partial', 0)} partial (longer horizons only), "
        f"{summary['skipped']} skipped, {summary['failed']} failed, "
        f"{summary.get('deferred', 0)} deferred "
        f"across {summary['dates_processed']} date(s)."
    )

    fi_written = 0
    if args.feature_importance and summary["resolved"] > 0:
        fi_written = backfill_feature_importance(lookback_days=args.lookback)
        print(f"Feature importance: {fi_written} labeled samples written.")

    if args.ab_arm_labels and not args.dry_run:
        ab_summary = backfill_ab_arm_labels(
            target_dates=target_dates, lookback_days=args.lookback,
            dataset=args.dataset,
        )
        print(
            f"AB-arm labels: {ab_summary['resolved']} resolved "
            f"({ab_summary['from_outcomes']} from outcomes, "
            f"{ab_summary['fetched']} fetched), {ab_summary['pending']} pending "
            f"across {ab_summary['days_processed']} day(s)."
        )

    # ── Persist run log (ENG-WS4-01 DoD: 'Ergebnisse sind persistiert
    # und nachvollziehbar'). One JSON file per run, atomically written.
    if not args.dry_run:
        log_path = _write_backfill_run_log(
            summary=summary,
            feature_importance_samples=fi_written if args.feature_importance else None,
            cli_args={
                "date": args.date,
                "lookback": args.lookback,
                "dataset": args.dataset,
                "feature_importance": bool(args.feature_importance),
                "horizons": list(args.horizons),
                "backfill_horizons": bool(args.backfill_horizons),
            },
        )
        print(f"Run log: {log_path}")

    # Exit non-zero only when the backfill made no progress at all
    # (resolved == 0 AND failed > 0). Per-symbol "failed" counts are
    # normal and expected — they capture data gaps for delisted /
    # halted / missing-bar-data symbols and would otherwise turn the
    # workflow permanently red on any single legacy bad row. The exact
    # counts are still preserved in the JSON run log for inspection
    # and the FI report's `insufficient_labels` state.
    # Note: "deferred" symbols (bars not yet published upstream —
    # Databento 422 data_start_after_available_end) intentionally do NOT
    # count as failures: the next scheduled run retries them naturally.
    resolved = int(summary.get("resolved") or 0)
    failed = int(summary.get("failed") or 0)
    skipped = int(summary.get("skipped") or 0)
    deferred = int(summary.get("deferred") or 0)
    # A "partial" row DID get measured (on a longer horizon) — it is
    # progress, not a systemic failure, so it counts alongside `resolved`.
    partial = int(summary.get("partial") or 0)
    if resolved == 0 and partial == 0 and failed > 0:
        return 2
    # F-09: opt-in tripwire for scheduled workflows. The default
    # behaviour (no-op runs are tolerated) stays unchanged so ad-hoc
    # / dry-run invocations don't break. A deferred-only run made
    # contact with the upstream API, so it counts as progress.
    if args.require_progress and (
        resolved + partial + failed + skipped + deferred
    ) == 0:
        print(
            "::error::--require-progress was set but the run made "
            "no progress (resolved=0, failed=0, skipped=0, deferred=0)."
        )
        return 3
    return 0


# ── Run-log persistence (ENG-WS4-01) ────────────────────────────────────────

BACKFILL_RUN_LOG_DIR = Path("artifacts/open_prep/outcome_backfill")


def _write_backfill_run_log(
    *,
    summary: dict[str, Any],
    feature_importance_samples: int | None,
    cli_args: dict[str, Any],
    log_dir: Path | None = None,
) -> Path:
    """Atomically write a per-run JSON log of the backfill outcome.

    The log is timestamped to the second so concurrent invocations stay
    distinct. A small ``latest.json`` pointer is also written so a
    workflow can grab the last result without scanning the directory.
    """
    target_dir = log_dir if log_dir is not None else BACKFILL_RUN_LOG_DIR
    target_dir.mkdir(parents=True, exist_ok=True)

    now = datetime.now(_ET)
    record = {
        "run_id": now.strftime("%Y%m%dT%H%M%S"),
        "started_at_et": now.isoformat(),
        "resolved": int(summary.get("resolved") or 0),
        "partial": int(summary.get("partial") or 0),
        "skipped": int(summary.get("skipped") or 0),
        "failed": int(summary.get("failed") or 0),
        "deferred": int(summary.get("deferred") or 0),
        "dates_processed": int(summary.get("dates_processed") or 0),
        "feature_importance_samples": (
            int(feature_importance_samples) if feature_importance_samples is not None else None
        ),
        "status": (
            "failed" if int(summary.get("failed") or 0) > 0
            else "deferred" if int(summary.get("deferred") or 0) > 0
            else "ok"
        ),
        "cli_args": cli_args,
    }

    out_path = target_dir / f"backfill_{record['run_id']}.json"
    _atomic_write_json(out_path, record)

    latest_path = target_dir / "latest.json"
    _atomic_write_json(latest_path, record)

    return out_path


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, sort_keys=True)
            fh.write("\n")
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


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


# ── §G3 arm-label backfill (2026-07-27) ──────────────────────────────
#
# Appended below every line-pinned site so the ledgers stay stable.

AB_ARMS_DIR = Path("artifacts/open_prep/ab_arms")


def backfill_ab_arm_labels(
    *,
    target_dates: list[date] | None = None,
    lookback_days: int = 3,
    provider: Any | None = None,
    dataset: str = _DEFAULT_DATASET,
) -> dict[str, Any]:
    """Resolve 30-minute labels for BOTH §G3 arms into ``labels_<day>.json``.

    The paired ``ab_arms_<day>.json`` records name the symbols each arm
    ranked, but only Arm A's symbols receive labels through the regular
    outcome backfill (it labels the served ranked snapshot). Arm-B-only
    symbols would stay unlabeled, biasing the paired comparison toward the
    intersection. This routine labels the union of both arms into a
    SEPARATE store next to the records — deliberately NOT into
    ``outcomes_<day>.json``, because arm-B shadow rows there would
    contaminate ``compute_hit_rates`` and the FI ledger with rows no served
    ranking produced (pinned by
    ``tests/test_ab_arm_label_backfill.py::test_outcome_rows_never_gain_arm_b_shadow_entries``).

    Labels already resolved in the day's outcome file are REUSED (same
    30-minute mark-to-market semantics, no double fetch); only the
    remainder is measured from provider bars, anchored at the 09:30 open
    exactly like a pre-open capsule (``fired_at=None`` →
    :func:`_resolve_anchor` fallback). Unresolvable symbols stay ``None``
    ("pending"), never ``False`` — a re-run resolves them idempotently.

    Consumed by ``scripts/g3_bridge_ab_arms.py``, which folds every labeled
    day into the cumulative comparison the §G2/§G3 watchdog appends to
    ``docs/ab/g23_history.jsonl``.
    """
    from open_prep.candidate_weights import _atomic_write_json

    if target_dates is None:
        dates: list[date] = []
        for record_path in sorted(AB_ARMS_DIR.glob("ab_arms_*.json"))[-max(lookback_days, 1):]:
            try:
                dates.append(date.fromisoformat(record_path.stem.removeprefix("ab_arms_")))
            except ValueError:
                logger.warning("Unparseable ab_arms record name: %s", record_path.name)
        target_dates = dates

    summary = {
        "days_processed": 0, "days_skipped": 0,
        "resolved": 0, "pending": 0, "from_outcomes": 0, "fetched": 0,
    }
    lazy_provider = provider

    for run_date in target_dates:
        day = run_date.isoformat()
        record_path = AB_ARMS_DIR / f"ab_arms_{day}.json"
        try:
            record = json.loads(record_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            summary["days_skipped"] += 1
            continue
        if not isinstance(record, dict) or record.get("status") != "ok":
            summary["days_skipped"] += 1
            continue

        symbols: list[str] = []
        for arm_key in ("arm_a_top", "arm_b_top"):
            for symbol in record.get(arm_key) or []:
                if isinstance(symbol, str) and symbol and symbol not in symbols:
                    symbols.append(symbol)

        labels_path = AB_ARMS_DIR / f"labels_{day}.json"
        labels: dict[str, dict[str, Any]] = {}
        try:
            prior = json.loads(labels_path.read_text(encoding="utf-8"))
            if isinstance(prior, dict) and isinstance(prior.get("labels"), dict):
                labels = {
                    s: entry for s, entry in prior["labels"].items()
                    if isinstance(entry, dict) and entry.get("profitable_30m") is not None
                }
        except (OSError, ValueError):
            pass

        _path, outcome_rows = _load_outcome_file(run_date)
        outcome_labels = {
            str(row.get("symbol")): row for row in outcome_rows
            if isinstance(row, dict) and row.get("profitable_30m") is not None
        }
        for symbol in symbols:
            if symbol in labels:
                continue
            row = outcome_labels.get(symbol)
            if row is not None:
                labels[symbol] = {
                    "profitable_30m": bool(row["profitable_30m"]),
                    "pnl_30m_pct": row.get("pnl_30m_pct"),
                    "source": "outcomes",
                }
                summary["from_outcomes"] += 1

        missing = [s for s in symbols if s not in labels]
        if missing:
            if lazy_provider is None:
                from databento_provider import DabentoProvider
                lazy_provider = DabentoProvider()
            bars_df = _fetch_bars(lazy_provider, missing, run_date, dataset=dataset)
            if bars_df is None or bars_df is DATA_NOT_YET_PUBLISHED:
                logger.info("ab-arm labels %s: bars unavailable for %s", day, missing)
            else:
                for symbol in missing:
                    result = compute_pnl_from_bars(bars_df, symbol, run_date)
                    if result is not None and result.get("profitable_30m") is not None:
                        labels[symbol] = {
                            "profitable_30m": bool(result["profitable_30m"]),
                            "pnl_30m_pct": result.get("pnl_30m_pct"),
                            "source": "ab_backfill",
                        }
                        summary["fetched"] += 1

        pending = [s for s in symbols if s not in labels]
        payload = {
            "schema_version": 1,
            "day": day,
            "labels": {
                **labels,
                **{s: {"profitable_30m": None, "pnl_30m_pct": None, "source": "pending"}
                   for s in pending},
            },
            "pending": pending,
        }
        _atomic_write_json(labels_path, payload)
        summary["days_processed"] += 1
        summary["resolved"] += len(labels)
        summary["pending"] += len(pending)

    return summary
