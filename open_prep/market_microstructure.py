"""Market microstructure metrics (observe-only).

Answers, market-wide: "is this a market where individual-stock setups can
work?" — recorded per outcome row for feature-importance evidence and shown
to users as context. Carries NO scorer weight (see
``outcomes.PASS_THROUGH_FEATURE_KEYS``); promotion into scoring requires the
pre-registered evaluation (regime_study plan, 2026-07).

Metrics (all ex-ante — previous closes only):

- ``market_efficiency_ratio``: Kaufman efficiency ratio on daily closes
  (10-day window), median across the sample. High = multi-day moves run;
  low = the market saws.
- ``intraday_efficiency_ratio``: same idea on 1-hour bars over the last
  ~5 trading days, median across a smaller subsample. High = intraday
  moves follow through (what gap-and-go / breakout setups need).
- ``cs_dispersion``: cross-sectional stdev of 1-day returns across the
  sample (5-day mean, in %). High = stocks move on their own stories;
  low = lockstep/index market.
- ``avg_pair_correlation``: average pairwise correlation of daily returns
  over a 20-day window (via the portfolio-variance identity — O(N*T),
  no N^2 pair loop). High = systemic/macro market.

``market_weather`` is a DISPLAY-ONLY traffic light (GREEN/YELLOW/RED)
derived from percentile ranks of today's values against the trailing 60
trading days, recomputed in-run from the same fetched data (stateless).
Thresholds are fixed-but-arbitrary and not validated.
"""

from __future__ import annotations

import logging
import math
import statistics
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

logger = logging.getLogger("open_prep.market_microstructure")

# Sampling defaults: the sample is drawn from the head of the (market-cap
# ordered) universe list. 100 EOD series carry the daily metrics; the
# intraday ER uses a smaller subsample to bound API calls.
DEFAULT_EOD_SAMPLE = 100
DEFAULT_INTRADAY_SAMPLE = 50
TRAILING_DAYS = 60          # percentile reference window (trading days)
ER_DAILY_WINDOW = 10        # Kaufman ER window on daily closes
ER_INTRADAY_BARS = 35       # ~5 trading days of 1h bars
DISPERSION_SMOOTH_DAYS = 5
CORR_WINDOW = 20            # pairwise-correlation lookback (trading days)
EOD_CALENDAR_DAYS_BACK = 200  # fetch depth to cover trailing windows
MIN_USABLE_SYMBOLS = 30     # below this the snapshot degrades to UNKNOWN

WEATHER_GREEN = "GREEN"
WEATHER_YELLOW = "YELLOW"
WEATHER_RED = "RED"
WEATHER_UNKNOWN = "UNKNOWN"

# Canonical weather wording (emoji, short label, plain-language phrase). Shared
# by the Pine panel generator (scripts/generate_openprep_pine_panel.py) and the
# Slack/Discord/generic alert formatters (open_prep/alerts.py) so every channel
# speaks one language.
WEATHER_LABELS: dict[str, tuple[str, str, str]] = {
    WEATHER_GREEN: ("\U0001F7E2", "Breakout-Wetter", "Bewegungen laufen aktuell durch"),
    WEATHER_YELLOW: ("\U0001F7E1", "Durchwachsen", "gemischtes Bild"),
    WEATHER_RED: ("\U0001F534", "Sägemarkt", "Bewegungen verpuffen (Mean-Reversion)"),
    WEATHER_UNKNOWN: ("⚪", "Unbekannt", "zu wenig Daten"),
}


def weather_badge_label(weather: str | None) -> tuple[str, str]:
    """(emoji, short label) for a weather code — for compact UI like the Pine panel header."""
    emoji, label, _phrase = WEATHER_LABELS.get(
        str(weather or "").upper(), WEATHER_LABELS[WEATHER_UNKNOWN]
    )
    return emoji, label


def weather_summary_line(
    weather: str | None,
    *,
    er_intraday: float | None = None,
    dispersion: float | None = None,
    correlation: float | None = None,
) -> str:
    """One plain-language line shared by alerts and panels, e.g.
    ``🟢 Breakout-Wetter — Bewegungen laufen aktuell durch (ER 0.23, Disp 3.56%, Korr 0.11)``.
    """
    emoji, label, phrase = WEATHER_LABELS.get(
        str(weather or "").upper(), WEATHER_LABELS[WEATHER_UNKNOWN]
    )

    def _f(value: float | None, suffix: str = "") -> str:
        if value is None or not math.isfinite(value):
            return "n/a"
        return f"{value:.2f}{suffix}"

    metrics = f"ER {_f(er_intraday)}, Disp {_f(dispersion, '%')}, Korr {_f(correlation)}"
    return f"{emoji} {label} — {phrase} ({metrics})"

# Known FMP screener leakage: mutual funds/ETF tickers that survive the
# is_etf/is_fund filters (e.g. VTSAX). Five-letter X-suffix is the classic
# US mutual-fund ticker convention.
_ETF_TICKERS = frozenset({
    "VGT", "XLK", "IVW", "IEMG", "SGOV", "BIL", "SPY", "QQQ", "IWM", "GLD",
    "TLT", "HYG", "LQD", "EFA", "EEM", "VTI", "VOO", "SPYG", "JEPQ",
})


def _is_fundish(symbol: str) -> bool:
    sym = str(symbol).strip().upper()
    return (len(sym) == 5 and sym.endswith("X")) or sym in _ETF_TICKERS


@dataclass
class MicrostructureSnapshot:
    """Immutable snapshot of market-microstructure context for one run."""

    market_efficiency_ratio: float | None
    intraday_efficiency_ratio: float | None
    cs_dispersion: float | None
    avg_pair_correlation: float | None
    market_weather: str
    percentiles: dict[str, float | None] = field(default_factory=dict)
    reasons: list[str] = field(default_factory=list)
    sample_size: int = 0
    intraday_sample_size: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "market_efficiency_ratio": self.market_efficiency_ratio,
            "intraday_efficiency_ratio": self.intraday_efficiency_ratio,
            "cs_dispersion": self.cs_dispersion,
            "avg_pair_correlation": self.avg_pair_correlation,
            "market_weather": self.market_weather,
            "percentiles": dict(self.percentiles),
            "reasons": list(self.reasons),
            "sample_size": self.sample_size,
            "intraday_sample_size": self.intraday_sample_size,
        }

    def to_log_line(self) -> str:
        def f(v: float | None) -> str:
            return f"{v:.3f}" if v is not None else "n/a"

        return (
            f"weather={self.market_weather} er_daily={f(self.market_efficiency_ratio)} "
            f"er_1h={f(self.intraday_efficiency_ratio)} disp={f(self.cs_dispersion)} "
            f"corr={f(self.avg_pair_correlation)} (n={self.sample_size})"
        )


def _unknown_snapshot(reason: str) -> MicrostructureSnapshot:
    return MicrostructureSnapshot(
        market_efficiency_ratio=None,
        intraday_efficiency_ratio=None,
        cs_dispersion=None,
        avg_pair_correlation=None,
        market_weather=WEATHER_UNKNOWN,
        reasons=[reason],
    )


def _kaufman_er(closes: list[float], window: int) -> float | None:
    """|net move| / sum(|bar moves|) over the last ``window`` steps."""
    if len(closes) < window + 1:
        return None
    seg = closes[-(window + 1):]
    path = sum(abs(seg[i] - seg[i - 1]) for i in range(1, len(seg)))
    if path <= 0:
        return None
    return abs(seg[-1] - seg[0]) / path


def _percentile_rank(history: list[float], value: float) -> float | None:
    """Share of trailing values strictly below ``value`` (0..100)."""
    if not history or not math.isfinite(value):
        return None
    finite_history = [h for h in history if math.isfinite(h)]
    if not finite_history:
        return None
    below = sum(1 for h in finite_history if h < value)
    return 100.0 * below / len(finite_history)


def _sample_symbols(symbols: list[str], limit: int) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for sym in symbols:
        s = str(sym).strip().upper()
        if not s or s in seen or s == "BRK-A" or _is_fundish(s):
            continue
        seen.add(s)
        out.append(s)
        if len(out) >= limit:
            break
    return out


def _fetch_eod_closes(client: Any, symbol: str, date_from: date, date_to: date) -> dict[str, float]:
    """{date_str: close}; empty dict on any failure (fail-soft)."""
    try:
        rows = client.get_historical_price_eod_full(symbol, date_from=date_from, date_to=date_to)
    except Exception:
        return {}
    if not isinstance(rows, list):
        return {}
    out: dict[str, float] = {}
    for r in rows:
        d, c = r.get("date"), r.get("close")
        if d and c is not None:
            try:
                out[str(d)] = float(c)
            except (TypeError, ValueError):
                continue
    return out


def _fetch_intraday_er(client: Any, symbol: str) -> float | None:
    """Kaufman ER over the most recent ~5 trading days of 1h closes."""
    try:
        rows = client.get_intraday_chart(symbol, interval="1hour")
    except Exception:
        return None
    if not isinstance(rows, list) or len(rows) < ER_INTRADAY_BARS + 1:
        return None
    closes: list[float] = []
    for r in reversed(rows):  # newest-first -> chronological
        c = r.get("close")
        if c is None:
            continue
        try:
            closes.append(float(c))
        except (TypeError, ValueError):
            continue
    return _kaufman_er(closes, ER_INTRADAY_BARS)


def _avg_pair_correlation(window_returns: dict[str, list[float]]) -> float | None:
    """Average pairwise correlation via the portfolio-variance identity.

    For standardized series x_i and their cross-sectional mean s(t):
    Var(s) = 1/N + (N-1)/N * rho_bar  =>  rho_bar = (N*Var(s) - 1) / (N - 1)
    """
    standardized: list[list[float]] = []
    for series in window_returns.values():
        if len(series) < CORR_WINDOW:
            continue
        mu = statistics.fmean(series)
        sd = statistics.pstdev(series)
        if sd <= 0:
            continue
        standardized.append([(v - mu) / sd for v in series])
    n = len(standardized)
    if n < MIN_USABLE_SYMBOLS:
        return None
    t_len = min(len(s) for s in standardized)
    mean_series = [
        statistics.fmean(s[t] for s in standardized) for t in range(t_len)
    ]
    var_s = statistics.pstdev(mean_series) ** 2
    rho = (n * var_s - 1.0) / (n - 1.0)
    return max(-1.0, min(1.0, rho))


def compute_microstructure_snapshot(
    *,
    client: Any,
    symbols: list[str],
    eod_sample: int = DEFAULT_EOD_SAMPLE,
    intraday_sample: int = DEFAULT_INTRADAY_SAMPLE,
    max_workers: int = 8,
) -> MicrostructureSnapshot:
    """Compute today's market-microstructure snapshot (fail-soft).

    ``client`` needs ``get_historical_price_eod_full`` and
    ``get_intraday_chart`` (both on ``open_prep.macro.FMPClient``).
    ``symbols`` should be market-cap ordered (universe list); the sample is
    drawn from its head after filtering funds/ETFs.
    """
    sample = _sample_symbols(symbols, eod_sample)
    if len(sample) < MIN_USABLE_SYMBOLS:
        return _unknown_snapshot(f"sample too small ({len(sample)} symbols)")

    today = date.today()
    date_from = today - timedelta(days=EOD_CALENDAR_DAYS_BACK)

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        eod_results = list(pool.map(
            lambda s: (s, _fetch_eod_closes(client, s, date_from, today)), sample
        ))
    closes_by_sym = {s: c for s, c in eod_results if len(c) >= CORR_WINDOW + ER_DAILY_WINDOW + 10}
    if len(closes_by_sym) < MIN_USABLE_SYMBOLS:
        return _unknown_snapshot(
            f"too few usable EOD series ({len(closes_by_sym)}/{len(sample)})"
        )

    # Trading-day calendar: dates present in >= 60% of usable series.
    date_counts: dict[str, int] = {}
    for series in closes_by_sym.values():
        for d in series:
            date_counts[d] = date_counts.get(d, 0) + 1
    threshold = 0.6 * len(closes_by_sym)
    calendar = sorted(d for d, n in date_counts.items() if n >= threshold)
    # Need TRAILING_DAYS of metric history + the longest lookback on top.
    need = TRAILING_DAYS + CORR_WINDOW + DISPERSION_SMOOTH_DAYS + 2
    if len(calendar) < need:
        return _unknown_snapshot(f"calendar too short ({len(calendar)} days, need {need})")

    # Per-symbol close/return aligned to the calendar (None where missing).
    aligned: dict[str, list[float | None]] = {}
    returns: dict[str, list[float | None]] = {}
    for sym, series in closes_by_sym.items():
        row = [series.get(d) for d in calendar]
        ret: list[float | None] = [None]
        for i in range(1, len(row)):
            a, b = row[i - 1], row[i]
            ret.append((b / a - 1.0) if (a and b and a > 0) else None)
        aligned[sym] = row
        returns[sym] = ret

    # --- daily metric series over the trailing window (+ today) ------------
    idx_range = range(len(calendar) - (TRAILING_DAYS + 1), len(calendar))

    def dispersion_raw(i: int) -> float | None:
        vals = [r[i] for r in returns.values() if r[i] is not None]
        if len(vals) < MIN_USABLE_SYMBOLS:
            return None
        return statistics.pstdev(vals) * 100.0

    disp_raw_cache: dict[int, float | None] = {}

    def dispersion_smoothed(i: int) -> float | None:
        vals = []
        for j in range(i - DISPERSION_SMOOTH_DAYS + 1, i + 1):
            if j not in disp_raw_cache:
                disp_raw_cache[j] = dispersion_raw(j)
            if disp_raw_cache[j] is not None:
                vals.append(disp_raw_cache[j])
        return statistics.fmean(vals) if len(vals) >= 3 else None

    def er_daily(i: int) -> float | None:
        vals = []
        for row in aligned.values():
            seg = row[: i + 1]
            closes = [c for c in seg if c is not None]
            er = _kaufman_er(closes, ER_DAILY_WINDOW)
            if er is not None:
                vals.append(er)
        return statistics.median(vals) if len(vals) >= MIN_USABLE_SYMBOLS else None

    def corr20(i: int) -> float | None:
        window: dict[str, list[float]] = {}
        for sym, ret in returns.items():
            seg = [v for v in ret[i - CORR_WINDOW + 1: i + 1] if v is not None]
            if len(seg) == CORR_WINDOW:
                window[sym] = seg
        return _avg_pair_correlation(window)

    series: dict[str, list[float]] = {"er": [], "disp": [], "corr": []}
    todays: dict[str, float | None] = {"er": None, "disp": None, "corr": None}
    idx_list = list(idx_range)
    for pos, i in enumerate(idx_list):
        is_today = pos == len(idx_list) - 1
        for key, fn in (("er", er_daily), ("disp", dispersion_smoothed), ("corr", corr20)):
            v = fn(i)
            if is_today:
                todays[key] = v
            elif v is not None:
                series[key].append(v)

    # --- intraday ER (today's value only; accumulated for later analysis) --
    intraday_syms = sample[:intraday_sample]
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        er_1h_vals = [v for v in pool.map(lambda s: _fetch_intraday_er(client, s), intraday_syms)
                      if v is not None]
    er_1h = statistics.median(er_1h_vals) if len(er_1h_vals) >= 20 else None

    # --- percentiles + weather ---------------------------------------------
    percentiles = {
        "market_efficiency_ratio": (
            _percentile_rank(series["er"], todays["er"]) if todays["er"] is not None else None
        ),
        "cs_dispersion": (
            _percentile_rank(series["disp"], todays["disp"]) if todays["disp"] is not None else None
        ),
        "avg_pair_correlation": (
            _percentile_rank(series["corr"], todays["corr"]) if todays["corr"] is not None else None
        ),
    }

    reasons: list[str] = []
    pct_vals = list(percentiles.values())
    if any(p is None for p in pct_vals):
        weather = WEATHER_UNKNOWN
        reasons.append("insufficient history for percentile ranks")
    else:
        # Favorable: moves run (high ER), stocks differentiate (high
        # dispersion), low lockstep (low correlation). Display-only score.
        score = (
            percentiles["market_efficiency_ratio"]
            + percentiles["cs_dispersion"]
            + (100.0 - percentiles["avg_pair_correlation"])
        ) / 3.0
        if score >= 60.0:
            weather = WEATHER_GREEN
        elif score <= 40.0:
            weather = WEATHER_RED
        else:
            weather = WEATHER_YELLOW
        reasons.append(
            f"weather score {score:.0f}/100 "
            f"(ER p{percentiles['market_efficiency_ratio']:.0f}, "
            f"Disp p{percentiles['cs_dispersion']:.0f}, "
            f"Corr p{percentiles['avg_pair_correlation']:.0f})"
        )

    def _round(v: float | None, nd: int = 4) -> float | None:
        if v is None or not math.isfinite(v):
            return None
        return round(v, nd)

    return MicrostructureSnapshot(
        market_efficiency_ratio=_round(todays["er"]),
        intraday_efficiency_ratio=_round(er_1h),
        cs_dispersion=_round(todays["disp"]),
        avg_pair_correlation=_round(todays["corr"]),
        market_weather=weather,
        percentiles={k: _round(v, 1) for k, v in percentiles.items()},
        reasons=reasons,
        sample_size=len(closes_by_sym),
        intraday_sample_size=len(er_1h_vals),
    )
