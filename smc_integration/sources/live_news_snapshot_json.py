from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from scripts.smc_news_scorer import compute_news_sentiment

from .base import SourceCapabilities, SourceDescriptor

LIVE_NEWS_SNAPSHOT_JSON = (
    Path(__file__).resolve().parents[2]
    / "artifacts"
    / "smc_microstructure_exports"
    / "smc_live_news_snapshot.json"
)


def describe_source() -> SourceDescriptor:
    return SourceDescriptor(
        name="live_news_snapshot_json",
        path_hint="artifacts/smc_microstructure_exports/smc_live_news_snapshot.json",
        capabilities=SourceCapabilities(
            has_structure=False,
            has_meta=True,
            structure_mode="none",
            meta_mode="partial",
        ),
        notes=[
            "Provider-neutral live news snapshot emitted by the SMC refresh pipeline.",
            "Can aggregate Benzinga, FMP, NewsAPI.ai, and TradingView news into a single symbol-level news domain.",
        ],
    )


def _load_payload() -> dict[str, Any]:
    if not LIVE_NEWS_SNAPSHOT_JSON.exists():
        raise FileNotFoundError(f"live news snapshot source not found: {LIVE_NEWS_SNAPSHOT_JSON}")
    payload = json.loads(LIVE_NEWS_SNAPSHOT_JSON.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"live news snapshot payload must be an object: {LIVE_NEWS_SNAPSHOT_JSON}")
    return payload


def _coerce_optional_float(value: Any) -> float | None:
    if isinstance(value, (int, float, str)):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _parse_generated_at(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(UTC).timestamp()
    except ValueError:
        return None


def _extract_stories(payload: dict[str, Any]) -> list[dict[str, Any]]:
    stories = payload.get("stories")
    if not isinstance(stories, list):
        raise ValueError("live news snapshot payload has no story rows")
    return [story for story in stories if isinstance(story, dict)]


def _story_tickers(story: dict[str, Any]) -> list[str]:
    return [
        str(raw_symbol).strip().upper()
        for raw_symbol in list(story.get("tickers") or [])
        if str(raw_symbol).strip()
    ]


def _snapshot_mentions_symbol(payload: dict[str, Any], symbol: str) -> bool:
    wanted = str(symbol).strip().upper()
    if not wanted:
        return False

    raw_symbols = payload.get("symbols")
    if isinstance(raw_symbols, list):
        normalized_symbols = {str(item).strip().upper() for item in raw_symbols if str(item).strip()}
        if wanted in normalized_symbols:
            return True

    return any(wanted in _story_tickers(story) for story in _extract_stories(payload))


def _score_for_symbol(scored_payload: dict[str, Any], symbol: str) -> float | None:
    wanted = str(symbol).strip().upper()
    for part in str(scored_payload.get("ticker_heat_map") or "").split(","):
        item = part.strip()
        if not item:
            continue
        ticker, separator, raw_score = item.partition(":")
        if not separator or str(ticker).strip().upper() != wanted:
            continue
        try:
            return float(raw_score)
        except ValueError:
            return None

    if wanted in {str(item).strip().upper() for item in list(scored_payload.get("bullish_tickers") or [])}:
        return max(float(scored_payload.get("news_heat_global") or 0.0), 0.2)
    if wanted in {str(item).strip().upper() for item in list(scored_payload.get("bearish_tickers") or [])}:
        return min(float(scored_payload.get("news_heat_global") or 0.0), -0.2)
    if wanted in {str(item).strip().upper() for item in list(scored_payload.get("neutral_tickers") or [])}:
        return 0.0
    return None


def _matching_story_articles(payload: dict[str, Any], symbol: str) -> tuple[list[dict[str, Any]], list[str], float | None]:
    wanted = str(symbol).strip().upper()
    provider_names: set[str] = set()
    latest_published_ts: float | None = None
    articles: list[dict[str, Any]] = []

    for story in _extract_stories(payload):
        tickers = _story_tickers(story)
        if wanted not in tickers:
            continue

        published_ts = _coerce_optional_float(story.get("published_ts"))
        if published_ts is not None:
            latest_published_ts = published_ts if latest_published_ts is None else max(latest_published_ts, published_ts)

        for raw_provider in list(story.get("provider_names") or []) or list(story.get("providers") or []):
            provider_name = str(raw_provider).strip()
            if provider_name:
                provider_names.add(provider_name)
        first_provider = str(story.get("first_provider") or "").strip()
        if first_provider:
            provider_names.add(first_provider)

        articles.append(
            {
                "headline": str(story.get("headline") or "").strip(),
                "snippet": str(story.get("summary") or story.get("snippet") or "").strip(),
                "tickers": tickers,
            }
        )

    return articles, sorted(provider_names), latest_published_ts


def load_raw_structure_input(symbol: str, timeframe: str) -> dict[str, Any]:
    del timeframe
    payload = _load_payload()
    if not _snapshot_mentions_symbol(payload, symbol):
        raise ValueError(f"symbol {str(symbol).strip().upper()} not present in live news snapshot source")
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
    reference_time: float | None = None,
    **_kwargs: Any,
) -> dict[str, Any]:
    payload = _load_payload()
    wanted = str(symbol).strip().upper()
    generated_at_ts = _parse_generated_at(payload.get("generated_at"))

    articles, provider_names, latest_published_ts = _matching_story_articles(payload, wanted)
    asof_strategy = str(payload.get("asof_strategy", "")).strip().lower()
    if asof_strategy == "now":
        # Snapshot opt-in: stamp meta with current time so this CI fixture
        # never trips the 48h _META_DOMAIN_STALE_HOURS gate. Real article
        # published_ts are still preserved for sentiment scoring; only the
        # meta-domain freshness pointer is overridden. When the caller
        # supplies a reference_time (e.g. the bundle's generated_at), prefer
        # it so two calls with the same generated_at produce byte-identical
        # bundles (otherwise time.time() drift breaks determinism under
        # xdist parallel workers).
        asof_ts = float(reference_time) if reference_time is not None else float(time.time())
        asof_source = "now_strategy"
    else:
        # latest article published_ts preferred; snapshot generated_at is a
        # disclosed proxy (no matching articles → asof reflects snapshot
        # creation, not story recency — audit #2670 W7).
        if latest_published_ts:
            asof_ts = latest_published_ts
            asof_source = "published_ts"
        else:
            asof_ts = generated_at_ts
            asof_source = "generated_at"
    if asof_ts is None:
        raise ValueError("live news snapshot is missing both generated_at and published_ts timestamps")

    result: dict[str, Any] = {
        "symbol": wanted,
        "timeframe": str(timeframe).strip(),
        "asof_ts": asof_ts,
        "asof_source": asof_source,
        "provenance": [
            "repo:artifacts/smc_microstructure_exports/smc_live_news_snapshot.json",
            f"repo:artifacts/smc_microstructure_exports/smc_live_news_snapshot.json#symbol={wanted}",
        ],
    }

    if provider_names:
        result["provenance"].append(
            "smc_integration:live_news_snapshot_providers[" + ",".join(provider_names) + "]"
        )

    if not articles:
        return result

    scored_payload = compute_news_sentiment([wanted], articles)
    score = _score_for_symbol(scored_payload, wanted)
    if score is None:
        return result

    if score > 0.1:
        bias = "BULLISH"
    elif score < -0.1:
        bias = "BEARISH"
    else:
        bias = "NEUTRAL"

    result["news"] = {
        "value": {
            "strength": round(min(1.0, abs(score)), 4),
            "bias": bias,
        },
        "asof_ts": asof_ts,
        "stale": False,
    }
    result["provenance"].append("smc_integration:news_mapped_from_live_news_snapshot")
    return result
