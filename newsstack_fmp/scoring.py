"""Headline classifier + impact/novelty scorer.

Assigns each normalised news item a category label and a composite score
(0.0 – 1.0) based on keyword/regex matching against the headline.

Works with both ``NewsItem`` objects and plain dicts (backward compat).
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Union

from .common_types import NewsItem

# ── Category patterns (ordered by priority) ─────────────────────

PATTERNS: list[tuple[str, float, re.Pattern[str]]] = [
    ("halt",      0.95, re.compile(r"\b(trading\s+halt|halted|resumption|resumed)\b", re.I)),
    ("offering",  0.92, re.compile(r"\b(offering|atm|registered\s+direct|pipe|public\s+offering|priced|dilution)\b", re.I)),
    ("mna",       0.90, re.compile(r"\b(acquire|acquires|to\s+be\s+acquired|merger|definitive\s+agreement)\b", re.I)),
    ("guidance",  0.88, re.compile(r"\b(raises?\s+guidance|lowers?\s+guidance|outlook)\b", re.I)),
    ("earnings",  0.80, re.compile(r"\b(reports?\s+q\d|earnings|eps|revenue)\b", re.I)),
    ("fda",       0.90, re.compile(r"\b(fda|crl|pdufa|approval|clinical\s+trial)\b", re.I)),
    ("analyst",   0.65, re.compile(r"\b(upgrade|downgrade|initiates|price\s+target)\b", re.I)),
    ("lawsuit",   0.25, re.compile(r"\b(class\s+action|lawsuit|investigation)\b", re.I)),
]

POS_HINTS = re.compile(r"\b(raises|beats|approval|wins|award|record|growth|surge)\b", re.I)
NEG_HINTS = re.compile(r"\b(lowers|misses|crl|halted|offering|dilution|bankruptcy|delist|plunge)\b", re.I)


@dataclass(frozen=True)
class ScoreResult:
    category: str
    impact: float
    clarity: float
    polarity: float
    score: float
    cluster_hash: str


def _norm(s: str) -> str:
    s = (s or "").strip().lower()
    return re.sub(r"\s+", " ", s)


def cluster_hash(provider: str, headline: str, tickers: List[str]) -> str:
    """Deterministic cluster key for novelty tracking."""
    key = f"{provider}|{_norm(headline)}|{','.join(sorted(set(tickers)))}"
    return hashlib.sha1(key.encode("utf-8")).hexdigest()


def classify_and_score(item: Union[NewsItem, Dict[str, Any]], cluster_count: int) -> ScoreResult:
    """Classify headline and compute composite score.

    Accepts both ``NewsItem`` and legacy plain-dict items.
    """
    if isinstance(item, NewsItem):
        headline = item.headline or ""
        tickers = item.tickers or []
        provider = item.provider or ""
    else:
        headline = item.get("headline") or ""
        tickers = item.get("tickers") or []
        provider = item.get("provider", "")
    chash = cluster_hash(provider, headline, tickers)

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
    if category in ("halt", "offering", "mna", "fda"):
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
    novelty = max(0.15, 1.0 / (0.8 + 0.35 * (cluster_count - 1)))

    # Weighted composite
    score = max(0.0, min(1.0, impact * 0.55 + clarity * 0.25 + novelty * 0.20))

    return ScoreResult(category, impact, clarity, polarity, score, chash)
