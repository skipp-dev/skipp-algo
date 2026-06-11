from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


# Bug-Hunt 2026-05-01 F-01: deferred so the script also works when
# invoked as `python scripts/X.py` (no PYTHONPATH=.) — sys.path.insert
# above must happen before any first-party `from scripts.` import.
from scripts.smc_atomic_write import atomic_write_text

from newsstack_fmp.config import Config
from newsstack_fmp.pipeline import load_universe
from scripts.smc_newsapi_ai import (
    ARTICLE_FEED_MAX_AGE_SECONDS,
    NewsApiAiProviderError,
    extract_newsapi_feed_article_cursor_uri,
    fetch_newsapi_article_records,
    fetch_newsapi_feed_article_probe,
)


def _load_env_file(env_path: Path) -> None:
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, value)


def _parse_symbols(raw: str) -> list[str]:
    seen: set[str] = set()
    symbols: list[str] = []
    for part in raw.replace("\n", ",").split(","):
        symbol = part.strip().upper()
        if not symbol or symbol in seen:
            continue
        seen.add(symbol)
        symbols.append(symbol)
    return symbols


def _parse_published_epoch(value: Any) -> float | None:
    text = str(value or "").strip()
    if not text:
        return None
    candidates = [text]
    if text.endswith("Z"):
        candidates.append(f"{text[:-1]}+00:00")
    for candidate in candidates:
        try:
            parsed = datetime.fromisoformat(candidate)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=UTC)
            return parsed.astimezone(UTC).timestamp()
        except ValueError:
            continue
    try:
        parsed = datetime.strptime(text, "%Y-%m-%d")
    except ValueError:
        return None
    return parsed.replace(tzinfo=UTC).timestamp()


def _record_summary(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "headline": str(record.get("headline") or record.get("title") or "").strip(),
        "published": str(record.get("published") or record.get("date") or "").strip(),
        "uri": str(record.get("uri") or "").strip(),
        "tickers": list(record.get("tickers") or []),
    }


def _build_probe_plan(
    search_records: list[dict[str, Any]],
    fallback_symbols: list[str],
    *,
    now: datetime,
    seed_symbol_limit: int,
    feed_backoff_minutes: int,
) -> dict[str, Any]:
    now_ts = now.timestamp()
    recent_cutoff = now_ts - ARTICLE_FEED_MAX_AGE_SECONDS

    indexed_records: list[tuple[float | None, dict[str, Any]]] = [
        (_parse_published_epoch(record.get("published") or record.get("date")), record)
        for record in search_records
    ]
    indexed_records.sort(key=lambda item: item[0] or 0.0, reverse=True)

    recent_records = [
        record
        for published_epoch, record in indexed_records
        if published_epoch is not None and recent_cutoff <= published_epoch <= now_ts
    ]
    seed_records = recent_records or [record for _, record in indexed_records]

    seed_symbols: list[str] = []
    seen_symbols: set[str] = set()
    for record in seed_records:
        for raw_symbol in record.get("tickers") or []:
            symbol = str(raw_symbol or "").strip().upper()
            if not symbol or symbol in seen_symbols:
                continue
            seen_symbols.add(symbol)
            seed_symbols.append(symbol)
            if len(seed_symbols) >= seed_symbol_limit:
                break
        if len(seed_symbols) >= seed_symbol_limit:
            break
    if not seed_symbols:
        seed_symbols = list(fallback_symbols[:seed_symbol_limit])

    reference_record = seed_records[0] if seed_records else None
    reference_epoch = (
        _parse_published_epoch((reference_record or {}).get("published") or (reference_record or {}).get("date"))
        if reference_record
        else None
    )
    clamped_floor = now_ts - max(60.0, ARTICLE_FEED_MAX_AGE_SECONDS - 60.0)
    proposed_after_epoch = (reference_epoch or now_ts) - max(feed_backoff_minutes, 1) * 60.0
    after_epoch = min(now_ts, max(proposed_after_epoch, clamped_floor))

    reference_uri = ""
    if reference_record is not None:
        reference_uri = str(reference_record.get("uri") or "").strip()

    return {
        "search_hit_count": len(search_records),
        "recent_search_hit_count": len(recent_records),
        "seed_symbol_count": len(seed_symbols),
        "seed_symbols": seed_symbols,
        "reference_search_uri": reference_uri,
        "reference_search_published": str(
            (reference_record or {}).get("published") or (reference_record or {}).get("date") or ""
        ).strip(),
        "feed_after_epoch": after_epoch,
        "feed_after_iso": datetime.fromtimestamp(after_epoch, tz=UTC).isoformat(),
        "search_samples": [_record_summary(record) for record in seed_records[:5]],
    }


def _run_feed_attempt(
    *,
    api_key: str,
    seed_symbols: list[str],
    after_epoch: float,
    after_uri: str,
    max_articles: int,
    now: datetime,
    client: httpx.Client,
) -> dict[str, Any]:
    try:
        probe_payload = fetch_newsapi_feed_article_probe(
            api_key,
            seed_symbols,
            article_feed_after_epoch=after_epoch,
            article_feed_after_uri=after_uri or None,
            max_articles=max_articles,
            current_time=now,
            client=client,
        )
    except NewsApiAiProviderError as exc:
        return {  # noqa: SECLEAK — exposes provider_status + detail (operator-facing diagnostic), no API key in either field
            "record_count": 0,
            "cursor_uri": "",
            "error": {
                "provider_status": exc.provider_status,
                "detail": exc.detail,
            },
            "raw_diagnostics": {
                "request_count": 0,
                "raw_result_count": 0,
                "matched_result_count": 0,
                "accepted_record_count": 0,
                "requests": [],
            },
            "sample_headlines": [],
            "sample_uris": [],
            "matched_tickers": [],
        }

    feed_records = list(probe_payload.get("records") or [])
    diagnostics = list(probe_payload.get("diagnostics") or [])

    matched_tickers = sorted(
        {
            str(ticker or "").strip().upper()
            for record in feed_records
            for ticker in record.get("tickers") or []
            if str(ticker or "").strip()
        }
    )
    return {
        "record_count": len(feed_records),
        "cursor_uri": extract_newsapi_feed_article_cursor_uri(feed_records) or "",
        "raw_diagnostics": {
            "request_count": len(diagnostics),
            "raw_result_count": sum(int(item.get("raw_result_count") or 0) for item in diagnostics),
            "matched_result_count": sum(int(item.get("matched_result_count") or 0) for item in diagnostics),
            "accepted_record_count": sum(int(item.get("accepted_record_count") or 0) for item in diagnostics),
            "requests": diagnostics,
        },
        "sample_headlines": [str(record.get("headline") or record.get("title") or "") for record in feed_records[:5]],
        "sample_uris": [str(record.get("uri") or "") for record in feed_records[:5]],
        "matched_tickers": matched_tickers,
    }


def _resolve_symbols(args: argparse.Namespace, cfg: Config) -> list[str]:
    explicit_symbols = _parse_symbols(args.symbols)
    if explicit_symbols:
        return explicit_symbols[: max(args.symbol_limit, 1)]
    universe = sorted(load_universe(cfg.universe_path))
    return universe[: max(args.symbol_limit, 1)]


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Search-seeded NewsAPI.ai feed cursor probe")
    parser.add_argument("--symbols", default="", help="Comma-separated base symbol list. Defaults to the configured universe file.")
    parser.add_argument("--symbol-limit", type=int, default=40, help="Maximum number of base symbols to search before feed seeding.")
    parser.add_argument("--seed-symbol-limit", type=int, default=12, help="Maximum number of symbols to carry into the feed probe.")
    parser.add_argument("--lookback-days", type=int, default=2, help="Search lookback window in days.")
    parser.add_argument("--articles-per-request", type=int, default=100, help="Maximum search/feed articles per request.")
    parser.add_argument("--feed-backoff-minutes", type=int, default=30, help="How far before the newest search hit the feed cursor should start.")
    parser.add_argument(
        "--output-path",
        default="artifacts/newsapi_ai/newsapi_feed_probe.json",
        help="Where to write the JSON probe summary.",
    )
    return parser


def main() -> int:
    _load_env_file(PROJECT_ROOT / ".env")
    parser = build_argument_parser()
    args = parser.parse_args()

    cfg = Config()
    api_key = str(cfg.newsapi_ai_key or os.getenv("NEWSAPI_KEY") or "").strip()
    if not api_key:
        parser.error("NEWSAPI_KEY is required")

    base_symbols = _resolve_symbols(args, cfg)
    if not base_symbols:
        parser.error("No symbols available for probe. Pass --symbols or configure a non-empty universe file.")

    now = datetime.now(UTC)
    with httpx.Client(timeout=20.0) as client:
        search_records = fetch_newsapi_article_records(
            api_key,
            base_symbols,
            lookback_days=max(args.lookback_days, 1),
            articles_per_request=max(args.articles_per_request, 1),
            client=client,
        )

        probe_plan = _build_probe_plan(
            search_records,
            base_symbols,
            now=now,
            seed_symbol_limit=max(args.seed_symbol_limit, 1),
            feed_backoff_minutes=max(args.feed_backoff_minutes, 1),
        )
        seed_symbols = list(probe_plan["seed_symbols"])
        feed_after_epoch = float(probe_plan["feed_after_epoch"])
        reference_uri = str(probe_plan["reference_search_uri"] or "").strip()

        timestamp_seed_result = _run_feed_attempt(
            api_key=api_key,
            seed_symbols=seed_symbols,
            after_epoch=feed_after_epoch,
            after_uri="",
            max_articles=max(args.articles_per_request, 1),
            now=now,
            client=client,
        )
        uri_seed_result = None
        if reference_uri:
            uri_seed_result = _run_feed_attempt(
                api_key=api_key,
                seed_symbols=seed_symbols,
                after_epoch=feed_after_epoch,
                after_uri=reference_uri,
                max_articles=max(args.articles_per_request, 1),
                now=now,
                client=client,
            )

    payload = {
        "generated_at": now.isoformat(),
        "base_symbol_count": len(base_symbols),
        "base_symbols": base_symbols,
        "probe_plan": probe_plan,
        "feed_attempts": {
            "timestamp_seed": timestamp_seed_result,
            "search_uri_seed": uri_seed_result,
        },
    }

    output_path = Path(args.output_path)
    if not output_path.is_absolute():
        output_path = PROJECT_ROOT / output_path
    output_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(json.dumps(payload, indent=2, ensure_ascii=True), output_path)
    print(json.dumps(payload, indent=2, ensure_ascii=True))
    print(f"Wrote probe summary to {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
