from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from typing import Any

_TICKER_RE = re.compile(r"\b[A-Z]{1,5}\b")


def _extract_symbols_from_tickers(raw: str) -> set[str]:
    """Parse FMP tickers metadata into plain symbols.

    Examples:
    - "NASDAQ:NVDA" -> {"NVDA"}
    - "NYSE:NMM, NASDAQ:PLTR" -> {"NMM", "PLTR"}
    """
    out: set[str] = set()
    for part in (raw or "").split(","):
        token = part.strip().upper()
        if not token:
            continue
        if ":" in token:
            token = token.split(":")[-1].strip()
        if token and _TICKER_RE.fullmatch(token):
            out.add(token)
    return out


def _parse_article_datetime(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    # FMP stable articles usually: "YYYY-MM-DD HH:MM:SS"
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(text, fmt)
            return dt.replace(tzinfo=UTC)
        except ValueError:
            continue
    return None


def build_news_scores(
    symbols: list[str],
    articles: list[dict[str, Any]],
    now_utc: datetime | None = None,
) -> tuple[dict[str, float], dict[str, dict[str, Any]]]:
    """Build per-symbol catalyst scores from FMP articles.

    Returns:
      - news_score_by_symbol: score contribution (float)
      - news_metrics_by_symbol: explainability metrics
    """
    now = now_utc or datetime.now(UTC)
    window_24h = now - timedelta(hours=24)
    window_2h = now - timedelta(hours=2)

    universe = {s.strip().upper() for s in symbols if s.strip()}
    metrics: dict[str, dict[str, Any]] = {
        s: {
            "mentions_total": 0,
            "mentions_24h": 0,
            "mentions_2h": 0,
            "latest_article_utc": None,
            "news_catalyst_score": 0.0,
        }
        for s in universe
    }

    for article in articles:
        ticker_meta = str(article.get("tickers") or "")
        title = str(article.get("title") or "").upper()
        content = str(article.get("content") or "").upper()
        article_dt = _parse_article_datetime(article.get("date"))

        mentioned = _extract_symbols_from_tickers(ticker_meta)

        if not mentioned:
            # Fallback: symbol mention in title/content
            for sym in universe:
                if sym in title or sym in content:
                    mentioned.add(sym)

        for sym in mentioned:
            if sym not in universe:
                continue
            row = metrics[sym]
            row["mentions_total"] += 1
            if article_dt is not None:
                if article_dt >= window_24h:
                    row["mentions_24h"] += 1
                if article_dt >= window_2h:
                    row["mentions_2h"] += 1

                latest_raw = row["latest_article_utc"]
                if latest_raw is None or article_dt.isoformat() > str(latest_raw):
                    row["latest_article_utc"] = article_dt.isoformat()

    scores: dict[str, float] = {}
    for sym, row in metrics.items():
        score = min(2.0, row["mentions_2h"] * 0.5 + row["mentions_24h"] * 0.15)
        row["news_catalyst_score"] = round(score, 4)
        scores[sym] = round(score, 4)

    return scores, metrics
