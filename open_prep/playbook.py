"""Professional news-trading playbook engine.

Implements the 6-step professional workflow:
1. Recency & Surprise  — Is the news new?
2. Materiality          — How material is it?
3. Setup Selection      — Gap&Go / Gap Fade / Post-News Drift / No Trade
4. Microstructure       — Liquidity & execution guardrails
5. Risk Management      — Max loss, invalidation, no-trade zones
6. Attribution Schema   — Event type → setup → outcome tracking

Each ranked candidate receives a ``PlaybookResult`` with concrete,
rule-based trade instructions derived from news classification, market
regime, and microstructure analysis.
"""
from __future__ import annotations

import logging
import math
import re
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

from .utils import to_float as _to_float

logger = logging.getLogger("open_prep.playbook")

# ═══════════════════════════════════════════════════════════════════
# 1) NEWS EVENT CLASSIFICATION
# ═══════════════════════════════════════════════════════════════════

# --- Event classes ---
EVENT_SCHEDULED = "SCHEDULED"       # Earnings, CPI, FOMC, FDA dates, etc.
EVENT_UNSCHEDULED = "UNSCHEDULED"   # M&A, profit warning, CEO exit, etc.
EVENT_STRUCTURAL = "STRUCTURAL"     # Analyst revisions, regulatory, product cycles
EVENT_UNKNOWN = "UNKNOWN"

# --- Event labels (granular) ---
_SCHEDULED_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("earnings",       re.compile(r"\b(earnings|eps|revenue|quarterly results?|q[1-4])\b", re.I)),
    ("guidance",       re.compile(r"\b(guidance|outlook|forecast|projection)\b", re.I)),
    ("macro_cpi",      re.compile(r"\b(cpi|inflation|consumer price)\b", re.I)),
    ("macro_nfp",      re.compile(r"\b(nonfarm|non-farm|payrolls?|jobs report)\b", re.I)),
    ("macro_fomc",     re.compile(r"\b(fomc|fed\s+rate|federal reserve|interest rate decision)\b", re.I)),
    ("macro_gdp",      re.compile(r"\b(gdp|gross domestic)\b", re.I)),
    ("fda",            re.compile(r"\b(fda|pdufa|approval|clearance|nda|bla)\b", re.I)),
    ("legal_ruling",   re.compile(r"\b(court ruling|verdict|judgment|settlement)\b", re.I)),
    ("dividend",       re.compile(r"\b(dividend|ex-date|record date)\b", re.I)),
    ("split",          re.compile(r"\b(stock split|reverse split)\b", re.I)),
    ("ipo",            re.compile(r"\b(ipo|initial public offering|debut)\b", re.I)),
]

_UNSCHEDULED_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("ma_deal",        re.compile(r"\b(acqui|merger|buyout|takeover|bid|deal)\b", re.I)),
    ("ma_rumor",       re.compile(r"\b(rumor|rumour|speculation|potential deal|explore.*sale)\b", re.I)),
    ("profit_warning", re.compile(r"\b(profit warning|revenue miss|downward revision|preannounce|shortfall)\b", re.I)),
    ("ceo_change",     re.compile(r"\b(ceo resign|ceo step|ceo.{0,10}depart|chief executive.*depart|management change|cfo resign|resign.*ceo|resign.*cfo)\b", re.I)),
    ("geopolitical",   re.compile(r"\b(sanction|tariff|embargo|geopolitical|war|conflict|attack)\b", re.I)),
    ("security",       re.compile(r"\b(breach|hack|cyber|ransomware|data leak)\b", re.I)),
    ("recall",         re.compile(r"\b(recall|safety.*alert|defect)\b", re.I)),
    ("bankruptcy",     re.compile(r"\b(bankrupt|chapter 11|insolvency|default)\b", re.I)),
]

_STRUCTURAL_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("analyst_upgrade",   re.compile(r"\b(upgrade|outperform|overweight|buy rating)\b", re.I)),
    ("analyst_downgrade", re.compile(r"\b(downgrade|underperform|underweight|sell rating)\b", re.I)),
    ("analyst_initiate",  re.compile(r"\b(initiat|coverage|price target)\b", re.I)),
    ("regulatory",        re.compile(r"\b(regulat|investigat|probe|subpoena|sec filing|enforcement)\b", re.I)),
    ("product_cycle",     re.compile(r"\b(product launch|new product|release|rollout|expansion)\b", re.I)),
    ("contract",          re.compile(r"\b(contract|awarded|partnership|agreement|collaboration)\b", re.I)),
]


def classify_news_event(title: str, content: str = "") -> dict[str, Any]:
    """Classify a news article into event class + label.

    Returns::

        {
            "event_class": "SCHEDULED" | "UNSCHEDULED" | "STRUCTURAL" | "UNKNOWN",
            "event_label": "earnings" | "ma_deal" | "analyst_upgrade" | ...,
            "event_labels_all": ["earnings", "guidance"],  # all matches
            "materiality": "HIGH" | "MEDIUM" | "LOW",
        }
    """
    text = f"{title} {(content or '')[:600]}"
    labels_found: list[tuple[str, str]] = []  # (class, label)

    for label, pat in _SCHEDULED_PATTERNS:
        if pat.search(text):
            labels_found.append((EVENT_SCHEDULED, label))

    for label, pat in _UNSCHEDULED_PATTERNS:
        if pat.search(text):
            labels_found.append((EVENT_UNSCHEDULED, label))

    for label, pat in _STRUCTURAL_PATTERNS:
        if pat.search(text):
            labels_found.append((EVENT_STRUCTURAL, label))

    if not labels_found:
        return {
            "event_class": EVENT_UNKNOWN,
            "event_label": "generic",
            "event_labels_all": [],
            "materiality": "LOW",
        }

    # Primary: the first (highest-priority) match determines class + label
    primary_class, primary_label = labels_found[0]
    all_labels = [lbl for _, lbl in labels_found]

    # Materiality heuristic: unscheduled breaking > scheduled catalysts > structural
    materiality = _estimate_materiality(primary_class, primary_label, title)

    return {
        "event_class": primary_class,
        "event_label": primary_label,
        "event_labels_all": all_labels,
        "materiality": materiality,
    }


def _estimate_materiality(event_class: str, event_label: str, title: str) -> str:
    """Estimate how material a news event is (HIGH / MEDIUM / LOW).

    HIGH = changes cashflows/risk materially (M&A, bankruptcy, earnings surprise,
           FDA approval/rejection, CEO exit)
    MEDIUM = triggers repricing (analyst revision, guidance, macro data)
    LOW = informational, limited direct impact
    """
    high_labels = {
        "ma_deal", "ma_rumor", "profit_warning", "bankruptcy",
        "ceo_change", "fda", "geopolitical", "security", "recall",
    }
    medium_labels = {
        "earnings", "guidance", "macro_cpi", "macro_nfp", "macro_fomc",
        "macro_gdp", "analyst_upgrade", "analyst_downgrade",
        "analyst_initiate", "regulatory", "legal_ruling",
    }

    if event_label in high_labels:
        return "HIGH"
    if event_label in medium_labels:
        return "MEDIUM"
    return "LOW"


# ═══════════════════════════════════════════════════════════════════
# NEWS RECENCY BUCKETS
# ═══════════════════════════════════════════════════════════════════

RECENCY_ULTRA_FRESH = "ULTRA_FRESH"     # <5 minutes
RECENCY_FRESH = "FRESH"                 # <15 minutes
RECENCY_WARM = "WARM"                   # <60 minutes
RECENCY_AGING = "AGING"                 # <24 hours
RECENCY_STALE = "STALE"                 # >24 hours
RECENCY_UNKNOWN = "UNKNOWN"

_RECENCY_CUTOFFS: list[tuple[float, str]] = [
    (5.0,    RECENCY_ULTRA_FRESH),
    (15.0,   RECENCY_FRESH),
    (60.0,   RECENCY_WARM),
    (1440.0, RECENCY_AGING),       # 24h in minutes
]


def classify_recency(
    article_dt: datetime | str | None,
    now_utc: datetime | None = None,
) -> dict[str, Any]:
    """Classify news recency into actionable buckets.

    Returns::

        {
            "recency_bucket": "ULTRA_FRESH" | "FRESH" | "WARM" | "AGING" | "STALE" | "UNKNOWN",
            "age_minutes": float | None,
            "is_actionable": bool,  # True if <60m (still tradeable)
        }
    """
    now = now_utc or datetime.now(UTC)

    if article_dt is None:
        return {"recency_bucket": RECENCY_UNKNOWN, "age_minutes": None, "is_actionable": False}

    if isinstance(article_dt, str):
        try:
            article_dt = datetime.fromisoformat(article_dt.replace("Z", "+00:00"))
            if article_dt.tzinfo is None:
                article_dt = article_dt.replace(tzinfo=UTC)
        except ValueError:
            return {"recency_bucket": RECENCY_UNKNOWN, "age_minutes": None, "is_actionable": False}

    age_minutes = max((now - article_dt).total_seconds() / 60.0, 0.0)

    bucket = RECENCY_STALE
    for cutoff, label in _RECENCY_CUTOFFS:
        if age_minutes <= cutoff:
            bucket = label
            break

    return {
        "recency_bucket": bucket,
        "age_minutes": round(age_minutes, 1),
        "is_actionable": bucket in {RECENCY_ULTRA_FRESH, RECENCY_FRESH, RECENCY_WARM},
    }


# ═══════════════════════════════════════════════════════════════════
# SOURCE QUALITY RANKING
# ═══════════════════════════════════════════════════════════════════

SOURCE_TIER_1 = "TIER_1"   # SEC/8-K, Press Release, Company IR
SOURCE_TIER_2 = "TIER_2"   # Reuters, Bloomberg, WSJ, CNBC
SOURCE_TIER_3 = "TIER_3"   # General financial media
SOURCE_TIER_4 = "TIER_4"   # Social/blogs/unverified

_TIER_1_SOURCES: frozenset[str] = frozenset({
    "sec.gov", "edgar", "8-k", "press release", "pr newswire",
    "business wire", "globenewswire", "globe newswire", "company ir",
    "investor relations", "accesswire",
})
# Word-boundary tokens checked separately to avoid false positives
# (e.g. "sec" matching "sector").
_TIER_1_WORD_TOKENS: frozenset[str] = frozenset({"sec"})

_TIER_2_SOURCES: frozenset[str] = frozenset({
    "reuters", "bloomberg", "wsj", "wall street journal", "cnbc",
    "financial times", "ft", "barron's", "barrons", "marketwatch",
    "seeking alpha", "benzinga", "yahoo finance", "the motley fool",
    "investors.com", "ibd", "zacks", "tipranks",
})

_TIER_4_SOURCES: frozenset[str] = frozenset({
    "twitter", "x.com", "reddit", "stocktwits", "discord",
    "telegram", "tiktok", "youtube", "blog", "substack",
    "medium",
})


def classify_source_quality(source: str, title: str = "") -> dict[str, Any]:
    """Rank news source quality into tiers.

    Returns::

        {
            "source_tier": "TIER_1" | "TIER_2" | "TIER_3" | "TIER_4",
            "source_rank": int,  # 1=highest, 4=lowest
            "source_name": str,
        }
    """
    source_lower = (source or "").strip().lower()
    title_lower = (title or "").strip().lower()
    combined = f"{source_lower} {title_lower}"

    # Check for SEC filings / press releases in title or source
    if any(s in combined for s in _TIER_1_SOURCES):
        return {"source_tier": SOURCE_TIER_1, "source_rank": 1, "source_name": source}
    # Word-boundary check for short tokens like "sec" to avoid "sector" etc.
    if any(re.search(rf"\b{re.escape(tok)}\b", combined) for tok in _TIER_1_WORD_TOKENS):
        return {"source_tier": SOURCE_TIER_1, "source_rank": 1, "source_name": source}

    if any(s in source_lower for s in _TIER_2_SOURCES):
        return {"source_tier": SOURCE_TIER_2, "source_rank": 2, "source_name": source}

    if any(s in source_lower for s in _TIER_4_SOURCES):
        return {"source_tier": SOURCE_TIER_4, "source_rank": 4, "source_name": source}

    # Default: general financial media
    return {"source_tier": SOURCE_TIER_3, "source_rank": 3, "source_name": source}


# ═══════════════════════════════════════════════════════════════════
# 3) PLAYBOOK SELECTION (Gap&Go / Fade / Drift / No Trade)
# ═══════════════════════════════════════════════════════════════════

PLAYBOOK_GAP_AND_GO = "GAP_AND_GO"
PLAYBOOK_GAP_FADE = "GAP_FADE"
PLAYBOOK_POST_NEWS_DRIFT = "POST_NEWS_DRIFT"
PLAYBOOK_NO_TRADE = "NO_TRADE"

# Thresholds
_MIN_GAP_FOR_GO = 1.0           # min gap % for Gap&Go
_MIN_RVOL_FOR_GO = 1.5          # min relative volume
_MIN_EXT_SCORE_FOR_GO = 0.7     # premarket tape strength
_FADE_GAP_OVERDONE = 5.0        # gap % where fade is considered
_FADE_MAX_EXT_SCORE = 0.3       # weak tape = fade signal
_DRIFT_MIN_MATERIALITY = "MEDIUM"
_MAX_SPREAD_BPS_FOR_TRADE = 150.0


@dataclass
class PlaybookResult:
    """Complete playbook assignment for a single candidate.

    This is the full attribution chain:
    News-Type → Setup → Entry-Trigger → Risk → Execution Guardrails
    """
    # --- Identity ---
    symbol: str

    # --- Step 1: News Classification ---
    event_class: str              # SCHEDULED / UNSCHEDULED / STRUCTURAL / UNKNOWN
    event_label: str              # earnings, ma_deal, fda, analyst_upgrade, ...
    event_labels_all: list[str]
    materiality: str              # HIGH / MEDIUM / LOW
    recency_bucket: str           # ULTRA_FRESH / FRESH / WARM / AGING / STALE
    age_minutes: float | None
    is_actionable: bool
    source_tier: str              # TIER_1..4
    source_rank: int

    # --- Step 3: Playbook ---
    playbook: str                 # GAP_AND_GO / GAP_FADE / POST_NEWS_DRIFT / NO_TRADE
    playbook_reason: str          # human-readable explanation
    entry_trigger: str            # concrete entry rule
    invalidation: str             # where the trade is wrong
    time_horizon: str             # "intraday", "swing 1-3d"
    exit_plan: str                # scale-out rules

    # --- Step 4: Microstructure (Execution Guardrails) ---
    spread_bps: float | None
    dollar_volume_ok: bool
    halt_risk: bool               # True if gap_pct > 10% or recent halt
    execution_quality: str         # GOOD / CAUTION / POOR
    size_adjustment: float         # 1.0 = full, 0.5 = half, 0.0 = no trade

    # --- Step 5: Risk ---
    max_loss_pct: float            # of account, e.g. 0.5
    no_trade_zone: bool            # True if we're in a no-trade zone
    no_trade_zone_reason: str      # why no trade

    # --- Regime context ---
    regime: str
    regime_aligned: bool           # True if playbook aligns with regime

    # --- Selection scores ---
    gap_go_score: float            # 0..1 how well it fits gap-and-go
    fade_score: float              # 0..1 how well it fits fade
    drift_score: float             # 0..1 how well it fits drift

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ═══════════════════════════════════════════════════════════════════
# PLAYBOOK ENGINE
# ═══════════════════════════════════════════════════════════════════

def _compute_gap_go_score(
    gap_pct: float,
    rvol: float,
    ext_hours_score: float,
    regime: str,
    event_class: str,
    materiality: str,
    is_actionable: bool,
    macro_bias: float,
) -> float:
    """Score 0..1 how well this candidate fits the Gap&Go playbook.

    Ideal: large gap + high RVOL + strong premarket tape + risk-on regime
    + clear catalyst + actionable recency.
    """
    s = 0.0

    # Gap magnitude (0..0.25)
    if gap_pct >= _MIN_GAP_FOR_GO:
        s += min(gap_pct / 8.0, 0.25)

    # Relative volume (0..0.25)
    if rvol >= _MIN_RVOL_FOR_GO:
        s += min(rvol / 8.0, 0.25)

    # Premarket tape (0..0.2)
    if ext_hours_score >= _MIN_EXT_SCORE_FOR_GO:
        s += min(ext_hours_score / 4.0, 0.2)

    # Regime alignment (0..0.15)
    if regime in ("RISK_ON", "NEUTRAL"):
        s += 0.15 if regime == "RISK_ON" else 0.08

    # Catalyst quality (0..0.15)
    if is_actionable and materiality in ("HIGH", "MEDIUM"):
        s += 0.10
    if event_class in (EVENT_SCHEDULED, EVENT_UNSCHEDULED):
        s += 0.05

    return min(round(s, 4), 1.0)


def _compute_fade_score(
    gap_pct: float,
    rvol: float,
    ext_hours_score: float,
    regime: str,
    event_class: str,
    materiality: str,
    sector_breadth: float,
    macro_bias: float,
) -> float:
    """Score 0..1 how well this candidate fits the Gap Fade playbook.

    Ideal: overdone gap + low RVOL / weak tape + poor breadth + sell-the-news.
    """
    s = 0.0

    # Overdone gap (0..0.3)
    if abs(gap_pct) >= _FADE_GAP_OVERDONE:
        s += min(abs(gap_pct) / 15.0, 0.3)

    # Weak tape (0..0.25)
    if ext_hours_score <= _FADE_MAX_EXT_SCORE:
        s += 0.25 * (1.0 - min(max(ext_hours_score, 0.0), 1.0))

    # Low-ish RVOL for a gap (0..0.15)
    if rvol < 2.0:
        s += 0.15

    # Poor macro/breadth context (0..0.15)
    if regime == "RISK_OFF":
        s += 0.15
    elif sector_breadth < 0.4:
        s += 0.10

    # Structural / aged news = sell-the-news (0..0.15)
    if event_class == EVENT_STRUCTURAL:
        s += 0.10
    if materiality == "LOW":
        s += 0.05

    return min(round(s, 4), 1.0)


def _compute_drift_score(
    gap_pct: float,
    event_class: str,
    event_label: str,
    materiality: str,
    recency_bucket: str,
    momentum_z: float,
) -> float:
    """Score 0..1 how well this candidate fits the Post-News Drift playbook.

    Ideal: material catalyst + post-initial-noise phase + momentum confirmation.
    """
    s = 0.0

    # Material catalyst (0..0.3)
    if materiality == "HIGH":
        s += 0.30
    elif materiality == "MEDIUM":
        s += 0.15

    # Aging news (initial noise settling) (0..0.25)
    if recency_bucket in (RECENCY_WARM, RECENCY_AGING):
        s += 0.25
    elif recency_bucket == RECENCY_FRESH:
        s += 0.10

    # Drift-friendly events (0..0.2)
    drift_labels = {"earnings", "guidance", "ma_deal", "analyst_upgrade", "analyst_downgrade", "fda"}
    if event_label in drift_labels:
        s += 0.20

    # Momentum confirmation (0..0.15)
    if abs(momentum_z) > 1.0:
        s += min(abs(momentum_z) / 5.0, 0.15)

    # Moderate gap (not extreme) (0..0.1)
    if 0.5 <= abs(gap_pct) <= 5.0:
        s += 0.10

    return min(round(s, 4), 1.0)


def _execution_quality(
    spread_bps: float | None,
    avg_volume: float,
    price: float,
) -> tuple[str, float]:
    """Assess execution quality and recommended size adjustment.

    Returns (quality_label, size_adjustment) where:
    - quality: GOOD / CAUTION / POOR
    - size_adjustment: 1.0 (full) / 0.5 (half) / 0.25 (quarter) / 0.0 (skip)
    """
    issues = 0

    # Spread check
    if spread_bps is not None:
        if spread_bps > _MAX_SPREAD_BPS_FOR_TRADE:
            issues += 2
        elif spread_bps > 60.0:
            issues += 1

    # Dollar volume check (require at least $1M avg daily)
    if price > 0 and avg_volume > 0:
        daily_dollar_vol = price * avg_volume
        if daily_dollar_vol < 500_000:
            issues += 2
        elif daily_dollar_vol < 1_000_000:
            issues += 1

    # Avg volume check
    if avg_volume < 50_000:
        issues += 2
    elif avg_volume < 100_000:
        issues += 1

    if issues >= 3:
        return "POOR", 0.0
    if issues >= 2:
        return "CAUTION", 0.25
    if issues >= 1:
        return "CAUTION", 0.5
    return "GOOD", 1.0


def _no_trade_zone(
    *,
    regime: str,
    gap_pct: float,
    recency_bucket: str,
    event_class: str,
    spread_bps: float | None,
    is_halt_risk: bool,
    premarket_stale: bool,
    ext_hours_score: float,
) -> tuple[bool, str]:
    """Determine if this is a no-trade zone.

    Returns (is_no_trade, reason).
    """
    reasons: list[str] = []

    # Directly into a massive breaking-news candle with no reclaim
    if event_class == EVENT_UNSCHEDULED and recency_bucket == RECENCY_ULTRA_FRESH:
        if ext_hours_score < 0.3 and abs(gap_pct) > 3.0:
            reasons.append("breaking_news_no_reclaim")

    # Illiquid premarket
    if premarket_stale:
        if spread_bps is not None and spread_bps > 200:
            reasons.append("illiquid_stale_premarket")

    # Halt risk
    if is_halt_risk and abs(gap_pct) > 15.0:
        reasons.append("extreme_gap_halt_risk")

    # FOMC minutes window (macro release)
    # This would be time-based; flagged via warn_flags externally

    if reasons:
        return True, "; ".join(reasons)
    return False, ""


def _entry_trigger_for_playbook(
    playbook: str,
    gap_pct: float,
    event_label: str,
    earnings_bmo: bool,
) -> str:
    """Generate a concrete, rule-based entry trigger."""
    if playbook == PLAYBOOK_GAP_AND_GO:
        if earnings_bmo:
            return (
                "Wait for post-earnings opening range (first 5min). "
                "Enter on break + hold above ORH with volume confirmation. "
                "Alternative: VWAP reclaim + hold after initial dip."
            )
        return (
            "Enter on break + hold above opening range high (ORH). "
            "Confirm with RVOL > 1.5× and price holding above VWAP. "
            "Alternative: VWAP reclaim if initial dip holds above premarket low."
        )

    if playbook == PLAYBOOK_GAP_FADE:
        if gap_pct > 0:
            return (
                "Short on failed break / VWAP rejection / lower high pattern. "
                "Confirm: gap fading with declining RVOL, bearish tape, bid dropping. "
                "Entry below VWAP on second rejection with volume."
            )
        return (
            "Long reversal on VWAP reclaim from gap-down. "
            "Confirm: price holding above PDL/LOD, improving bid, RVOL pickup. "
            "Entry above VWAP with bullish 5-min close."
        )

    if playbook == PLAYBOOK_POST_NEWS_DRIFT:
        return (
            "Enter after initial noise settles (15–60 min post-news). "
            "Wait for trend confirmation: higher lows for long, lower highs for short. "
            "Use VWAP + ATR levels for entry zone. Swing hold 1–3 days."
        )

    # NO_TRADE
    return "No trade: conditions do not meet playbook criteria."


def _invalidation_for_playbook(
    playbook: str,
    gap_pct: float,
) -> str:
    """Generate invalidation levels for each playbook."""
    if playbook == PLAYBOOK_GAP_AND_GO:
        return (
            "Close below VWAP after entry. "
            "Fill of entire premarket gap. "
            "Price below opening range low (ORL) on increasing volume."
        )

    if playbook == PLAYBOOK_GAP_FADE:
        if gap_pct > 0:
            return (
                "New HOD above entry / ORH breakout with volume. "
                "VWAP reclaim + hold after entry (for short fade)."
            )
        return (
            "New LOD below entry. "
            "VWAP rejection after reclaim attempt (for long fade)."
        )

    if playbook == PLAYBOOK_POST_NEWS_DRIFT:
        return (
            "Reversal of drift direction: higher low broken (long) or lower high broken (short). "
            "Return to pre-news price level (full retracement)."
        )

    return "N/A — no trade selected."


def _exit_plan_for_playbook(playbook: str) -> str:
    """Generate exit/scale-out plan."""
    if playbook == PLAYBOOK_GAP_AND_GO:
        return (
            "Scale ⅓ at +1R. Move stop to break-even. "
            "Scale ⅓ at +1.5R or ATR target. "
            "Trail final ⅓ with ATR×1.5 trailing stop."
        )

    if playbook == PLAYBOOK_GAP_FADE:
        return (
            "Scale ½ at VWAP (mean reversion target). "
            "Scale ½ at previous close or +1R. "
            "Hard stop — no averaging down on fade trades."
        )

    if playbook == PLAYBOOK_POST_NEWS_DRIFT:
        return (
            "Hold for 1–3 days. Scale ⅓ at next resistance/support. "
            "Trail stop with daily ATR×1.5. "
            "Exit fully if drift stalls (volume drying up)."
        )

    return "N/A"


def _time_horizon_for_playbook(playbook: str) -> str:
    """Time horizon for each playbook."""
    return {
        PLAYBOOK_GAP_AND_GO: "intraday (30min–2h)",
        PLAYBOOK_GAP_FADE: "intraday (15min–1h)",
        PLAYBOOK_POST_NEWS_DRIFT: "swing (1–3 days)",
        PLAYBOOK_NO_TRADE: "N/A",
    }.get(playbook, "N/A")


def _max_loss_for_playbook(playbook: str, execution_quality: str) -> float:
    """Max loss per trade as % of account."""
    base = {
        PLAYBOOK_GAP_AND_GO: 0.50,
        PLAYBOOK_GAP_FADE: 0.25,      # tighter risk on countertrend
        PLAYBOOK_POST_NEWS_DRIFT: 0.75,  # wider stop needs smaller size
        PLAYBOOK_NO_TRADE: 0.0,
    }.get(playbook, 0.0)

    if execution_quality == "POOR":
        return 0.0
    if execution_quality == "CAUTION":
        return round(base * 0.5, 2)
    return base


# ═══════════════════════════════════════════════════════════════════
# MAIN ENGINE: assign_playbook()
# ═══════════════════════════════════════════════════════════════════

def assign_playbook(
    candidate: dict[str, Any],
    *,
    regime: str = "NEUTRAL",
    sector_breadth: float = 0.5,
    news_metrics_entry: dict[str, Any] | None = None,
    now_utc: datetime | None = None,
) -> PlaybookResult:
    """Assign a playbook to a ranked candidate.

    This is the main entry point.  It runs all 6 steps and produces
    a complete ``PlaybookResult`` with concrete trade instructions.
    """
    symbol = str(candidate.get("symbol", "")).upper()
    gap_pct = _to_float(candidate.get("gap_pct"), default=0.0)
    price = _to_float(candidate.get("price"), default=0.0)
    volume = _to_float(candidate.get("volume"), default=0.0)
    avg_volume = _to_float(candidate.get("avg_volume") or candidate.get("avgVolume"), default=0.0)
    rvol = (volume / avg_volume) if avg_volume > 0 else 0.0
    ext_hours_score = _to_float(candidate.get("ext_hours_score"), default=0.0)
    momentum_z = _to_float(candidate.get("momentum_z_score"), default=0.0)
    macro_bias = _to_float(candidate.get("macro_bias"), default=0.0)
    spread_bps_raw = candidate.get("premarket_spread_bps")
    spread_bps: float | None = None
    if spread_bps_raw is not None:
        val = _to_float(spread_bps_raw, default=float("nan"))
        spread_bps = None if math.isnan(val) else val
    premarket_stale = bool(candidate.get("premarket_stale", False))
    earnings_bmo = bool(candidate.get("earnings_bmo", False))

    nm = news_metrics_entry or {}
    articles = nm.get("articles") or []

    # — Step 1: News Classification (best article) —
    best_title = ""
    best_source = ""
    best_dt: datetime | str | None = None

    if articles:
        best_art = articles[0]  # already sorted newest-first by news.py
        best_title = best_art.get("title", "")
        best_source = best_art.get("source", "")
        best_dt = best_art.get("date")

    event_info = classify_news_event(best_title)
    recency_info = classify_recency(best_dt, now_utc)
    source_info = classify_source_quality(best_source, best_title)

    # — Step 3: Score each playbook —
    go_score = _compute_gap_go_score(
        gap_pct, rvol, ext_hours_score, regime,
        event_info["event_class"], event_info["materiality"],
        recency_info["is_actionable"], macro_bias,
    )
    fade_score = _compute_fade_score(
        gap_pct, rvol, ext_hours_score, regime,
        event_info["event_class"], event_info["materiality"],
        sector_breadth, macro_bias,
    )
    drift_score = _compute_drift_score(
        gap_pct, event_info["event_class"], event_info["event_label"],
        event_info["materiality"], recency_info["recency_bucket"], momentum_z,
    )

    # — Step 4: Microstructure —
    exec_quality, size_adj = _execution_quality(
        spread_bps, avg_volume, price,
    )
    halt_risk = abs(gap_pct) > 10.0

    # — Step 5: No-trade zone check —
    is_ntz, ntz_reason = _no_trade_zone(
        regime=regime,
        gap_pct=gap_pct,
        recency_bucket=recency_info["recency_bucket"],
        event_class=event_info["event_class"],
        spread_bps=spread_bps,
        is_halt_risk=halt_risk,
        premarket_stale=premarket_stale,
        ext_hours_score=ext_hours_score,
    )

    # — Select best playbook —
    if is_ntz or exec_quality == "POOR":
        playbook = PLAYBOOK_NO_TRADE
        pb_reason = ntz_reason or "Execution quality too poor"
    elif go_score >= fade_score and go_score >= drift_score and go_score >= 0.30:
        playbook = PLAYBOOK_GAP_AND_GO
        pb_reason = f"Gap&Go: gap={gap_pct:.1f}%, RVOL={rvol:.1f}x, tape={ext_hours_score:.2f}"
    elif fade_score >= go_score and fade_score >= drift_score and fade_score >= 0.30:
        playbook = PLAYBOOK_GAP_FADE
        pb_reason = f"Gap Fade: gap={gap_pct:.1f}%, weak tape={ext_hours_score:.2f}, breadth={sector_breadth:.0%}"
    elif drift_score >= 0.25:
        playbook = PLAYBOOK_POST_NEWS_DRIFT
        pb_reason = f"Post-News Drift: {event_info['event_label']}, materiality={event_info['materiality']}"
    else:
        playbook = PLAYBOOK_NO_TRADE
        pb_reason = f"No playbook scores above threshold (go={go_score:.2f}, fade={fade_score:.2f}, drift={drift_score:.2f})"

    # Regime alignment check
    regime_aligned = True
    if playbook == PLAYBOOK_GAP_AND_GO and regime == "RISK_OFF":
        regime_aligned = False
    if playbook == PLAYBOOK_GAP_FADE and regime == "RISK_ON" and gap_pct > 0:
        regime_aligned = False

    return PlaybookResult(
        symbol=symbol,
        # Step 1
        event_class=event_info["event_class"],
        event_label=event_info["event_label"],
        event_labels_all=event_info["event_labels_all"],
        materiality=event_info["materiality"],
        recency_bucket=recency_info["recency_bucket"],
        age_minutes=recency_info["age_minutes"],
        is_actionable=recency_info["is_actionable"],
        source_tier=source_info["source_tier"],
        source_rank=source_info["source_rank"],
        # Step 3
        playbook=playbook,
        playbook_reason=pb_reason,
        entry_trigger=_entry_trigger_for_playbook(playbook, gap_pct, event_info["event_label"], earnings_bmo),
        invalidation=_invalidation_for_playbook(playbook, gap_pct),
        time_horizon=_time_horizon_for_playbook(playbook),
        exit_plan=_exit_plan_for_playbook(playbook),
        # Step 4
        spread_bps=spread_bps,
        dollar_volume_ok=price > 0 and avg_volume > 0 and (price * avg_volume) >= 500_000,
        halt_risk=halt_risk,
        execution_quality=exec_quality,
        size_adjustment=size_adj,
        # Step 5
        max_loss_pct=_max_loss_for_playbook(playbook, exec_quality),
        no_trade_zone=is_ntz,
        no_trade_zone_reason=ntz_reason,
        # Regime
        regime=regime,
        regime_aligned=regime_aligned,
        # Scores
        gap_go_score=go_score,
        fade_score=fade_score,
        drift_score=drift_score,
    )


# ═══════════════════════════════════════════════════════════════════
# BATCH HELPER
# ═══════════════════════════════════════════════════════════════════

def assign_playbooks(
    candidates: list[dict[str, Any]],
    *,
    regime: str = "NEUTRAL",
    sector_breadth: float = 0.5,
    news_metrics: dict[str, dict[str, Any]] | None = None,
    now_utc: datetime | None = None,
) -> list[PlaybookResult]:
    """Assign playbooks to a batch of ranked candidates."""
    results: list[PlaybookResult] = []
    nm = news_metrics or {}

    for candidate in candidates:
        symbol = str(candidate.get("symbol", "")).upper()
        pb = assign_playbook(
            candidate,
            regime=regime,
            sector_breadth=sector_breadth,
            news_metrics_entry=nm.get(symbol),
            now_utc=now_utc,
        )
        results.append(pb)

    return results
