from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from typing import Any

_TICKER_RE = re.compile(r"\b[A-Z][A-Z0-9.-]{0,5}\b")


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
    iso_text = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        dt = datetime.fromisoformat(iso_text)
        if dt.tzinfo is None:
            return dt.replace(tzinfo=UTC)
        return dt.astimezone(UTC)
    except ValueError:
        pass
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

    # Precompile regex patterns for fallback matching to avoid false positives (e.g. "A" in "APPLE")
    sym_patterns = {sym: re.compile(rf"\b{re.escape(sym)}\b") for sym in universe}

    for article in articles:
        ticker_meta = str(article.get("tickers") or "")
        title = str(article.get("title") or "").upper()
        content = str(article.get("content") or "").upper()
        article_dt = _parse_article_datetime(article.get("date"))

        mentioned = _extract_symbols_from_tickers(ticker_meta)

        # Fallback: symbol mention in title/content if FMP didn't tag it
        for sym, pattern in sym_patterns.items():
            if sym not in mentioned:
                if pattern.search(title) or pattern.search(content):
                    mentioned.add(sym)

        for sym in mentioned:
            if sym not in universe:
                continue
            row = metrics[sym]
            row["mentions_total"] += 1
            if article_dt is not None:
                # Guard against future-dated articles (provider timezone drift):
                # they count as mentions_total but must not inflate recency windows.
                if window_24h <= article_dt <= now:
                    row["mentions_24h"] += 1
                if window_2h <= article_dt <= now:
                    row["mentions_2h"] += 1

                latest_dt: datetime | None = row["latest_article_utc"]
                # Compare datetime objects to avoid the '.' vs '+' ASCII
                # ordering bug that occurs with ISO strings when microseconds
                # are present (e.g. '14:30:00.654321+00:00' > '14:30:00+00:00'
                # under naive string ordering despite representing the same or
                # an earlier moment than '15:30:00+00:00').
                if article_dt <= now and (
                    latest_dt is None or article_dt > latest_dt
                ):
                    row["latest_article_utc"] = article_dt

    scores: dict[str, float] = {}
    for sym, row in metrics.items():
        # Subtract 2h mentions from 24h count so articles are not double-counted
        # across both recency windows (2h articles are already boosted at 0.5).
        mentions_24h_only = max(row["mentions_24h"] - row["mentions_2h"], 0)
        score = min(2.0, row["mentions_2h"] * 0.5 + mentions_24h_only * 0.15)
        row["news_catalyst_score"] = round(score, 4)
        scores[sym] = round(score, 4)
        # Convert stored datetime → ISO string for serialisable output.
        if row["latest_article_utc"] is not None:
            row["latest_article_utc"] = row["latest_article_utc"].isoformat()

    return scores, metrics
