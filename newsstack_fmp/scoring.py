"""Headline classifier + impact/novelty scorer.

Assigns each normalised news item a category label and a composite score
(0.0 – 1.0) based on keyword/regex matching against the headline.

Enhanced with:
- 16 category patterns (up from 8) covering macro, crypto, insider, buyback, etc.
- Entity-level relevance scoring
- Headline-similarity novelty detection via Jaccard coefficient

Works with both ``NewsItem`` objects and plain dicts (backward compat).
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any

from .common_types import NewsItem

# ── Category patterns (ordered by priority) ─────────────────────

PATTERNS: list[tuple[str, float, re.Pattern[str]]] = [
    # ── Highest urgency ──
    ("halt",        0.95, re.compile(r"\b(trading\s+halt|halted|resumption|resumed)\b", re.I)),
    ("offering",    0.92, re.compile(r"\b(offering|atm|registered\s+direct|pipe|public\s+offering|priced|dilution|shelf\s+registration)\b", re.I)),
    ("mna",         0.90, re.compile(r"\b(acquire|acquires|to\s+be\s+acquired|merger|definitive\s+agreement|takeover|tender\s+offer|buyout)\b", re.I)),
    ("fda",         0.90, re.compile(r"\b(fda|crl|pdufa|approval|clinical\s+trial|phase\s+[123]|breakthrough\s+therapy|nda|bla)\b", re.I)),
    # ── High urgency ──
    ("guidance",    0.88, re.compile(r"\b(raises?\s+guidance|lowers?\s+guidance|outlook|reaffirms?\s+guidance|withdraws?\s+guidance)\b", re.I)),
    ("insider",     0.85, re.compile(r"\b(insider\s+(buy|sell|purchase)|form\s+4|beneficial\s+ownership|13[df]|activist)\b", re.I)),
    ("buyback",     0.83, re.compile(r"\b(buyback|repurchase|share\s+repurchase|stock\s+buyback)\b", re.I)),
    ("dividend",    0.82, re.compile(r"\b(dividend|special\s+dividend|ex[\-\s]?dividend|payout)\b", re.I)),
    ("earnings",    0.80, re.compile(r"\b(reports?\s+q\d|earnings|eps|revenue|beat\s+estimates?|miss\s+estimates?)\b", re.I)),
    # ── Medium urgency ──
    ("macro",       0.78, re.compile(r"\b(fed|fomc|rate\s+(cut|hike|decision)|cpi|inflation|nonfarm|payrolls?|gdp|pce|jobless\s+claims)\b", re.I)),
    ("crypto",      0.75, re.compile(r"\b(bitcoin|btc|ethereum|eth|crypto|blockchain|defi|nft|stablecoin)\b", re.I)),
    ("ipo",         0.80, re.compile(r"\b(ipo|initial\s+public\s+offering|direct\s+listing|spac)\b", re.I)),
    ("analyst",     0.65, re.compile(r"\b(upgrade|downgrade|initiates?|price\s+target|reiterate|overweight|underweight|outperform|underperform)\b", re.I)),
    ("contract",    0.70, re.compile(r"\b(contract\s+award|wins?\s+contract|partnership|collaboration|license\s+agreement|strategic\s+alliance)\b", re.I)),
    # ── Lower urgency ──
    ("lawsuit",     0.25, re.compile(r"\b(class\s+action|lawsuit|investigation|sec\s+probe|doj|indictment|subpoena)\b", re.I)),
    ("management",  0.60, re.compile(r"\b(ceo|cfo|cto|appoints?|resigns?|steps?\s+down|board\s+of\s+directors)\b", re.I)),
]

POS_HINTS = re.compile(
    r"\b(raises|beats|approval|wins|award|record|growth|surge|"
    r"outperform|upgrade|strong|accelerat|exceeds|profit|positive)\b", re.I,
)
NEG_HINTS = re.compile(
    r"\b(lowers|misses|crl|halted|offering|dilution|bankruptcy|delist|"
    r"plunge|downgrade|underperform|weak|decline|loss|negative|warning|recall)\b", re.I,
)

# ── Headline token set for Jaccard novelty ──────────────────────


@dataclass(frozen=True)
class ScoreResult:
    category: str
    impact: float
    clarity: float
    polarity: float
    score: float
    cluster_hash: str
    relevance: float  # 0.0–1.0 composite relevance (impact + clarity + entity specificity)
    entity_count: int  # number of tickers mentioned


def _norm(s: str) -> str:
    s = (s or "").strip().lower()
    s = re.sub(r"[^\w\s]", "", s)
    return re.sub(r"\s+", " ", s)


def cluster_hash(headline: str, tickers: list[str]) -> str:
    """Deterministic cluster key for novelty tracking.

    Provider is intentionally excluded so that the same story from
    FMP + Benzinga maps to the same cluster and receives proper
    novelty decay.
    """
    # Normalise tickers to uppercase so mixed-case inputs hash identically.
    key = f"{_norm(headline)}|{','.join(sorted(set(t.upper() for t in tickers)))}"
    return hashlib.sha1(key.encode("utf-8")).hexdigest()


def classify_and_score(
    item: NewsItem | dict[str, Any],
    cluster_count: int,
    chash: str | None = None,
) -> ScoreResult:
    """Classify headline and compute composite score with relevance.

    Accepts both ``NewsItem`` and legacy plain-dict items.

    Parameters
    ----------
    chash : str, optional
        Pre-computed cluster hash.  When supplied the (relatively
        expensive) SHA-1 computation is skipped.
    """
    # Guard against invalid cluster_count from external callers
    cluster_count = max(1, cluster_count)

    # Use duck-typing instead of isinstance so that Streamlit module
    # reloading (which can create a second NewsItem class identity)
    # doesn't break the check and fall through to dict `.get()`.
    if hasattr(item, "headline"):
        headline = item.headline or ""  # type: ignore[union-attr]
        tickers = item.tickers or []  # type: ignore[union-attr]
    else:
        headline = item.get("headline") or ""  # type: ignore[union-attr]
        tickers = item.get("tickers") or []  # type: ignore[union-attr]
    if chash is None:
        chash = cluster_hash(headline, tickers)

    entity_count = len(tickers)

    category = "other"
    impact = 0.10
    for cat, base_impact, rx in PATTERNS:
        if rx.search(headline):
            category = cat
            impact = base_impact
            break

    # Clarity: headlines with numbers or high-impact categories are clearer
    has_number = bool(re.search(r"\b\d+(\.\d+)?\b", headline))
    clarity = 0.60 + (0.20 if has_number else 0.0)
    if category in ("halt", "offering", "mna", "fda", "insider", "ipo"):
        clarity += 0.10
    clarity = min(1.0, clarity)

    # Polarity
    pos = bool(POS_HINTS.search(headline))
    neg = bool(NEG_HINTS.search(headline))
    polarity = 0.0
    if pos and not neg:
        polarity = 0.5
    elif neg and not pos:
        polarity = -0.5

    # Novelty: 1st occurrence = 1.0, decays per cluster hit
    novelty = max(0.15, min(1.0, 1.0 / (0.8 + 0.35 * (cluster_count - 1))))

    # ── Entity-specificity bonus ────────────────────────────
    # Stories with 1-2 tickers are more tradeable than broad market stories.
    entity_bonus = 0.0
    if 1 <= entity_count <= 2:
        entity_bonus = 0.10
    elif 3 <= entity_count <= 5:
        entity_bonus = 0.05

    # ── Relevance: combines impact, clarity, entity-specificity ──
    relevance = max(0.0, min(1.0,
        impact * 0.45 + clarity * 0.30 + entity_bonus + novelty * 0.15,
    ))

    # Weighted composite
    score = max(0.0, min(1.0, impact * 0.55 + clarity * 0.25 + novelty * 0.20))

    return ScoreResult(category, impact, clarity, polarity, score, chash, relevance, entity_count)
