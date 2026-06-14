from __future__ import annotations

import hashlib
import json
import os
import stat
import tempfile
import time
from collections.abc import Callable
from contextlib import contextmanager, suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .common_types import NewsItem

DEFAULT_SHARED_NEWS_CACHE_DIR = "artifacts/shared_news_cache"
DEFAULT_SHARED_NEWS_CACHE_TTL_SECONDS = 90.0
_LOCK_POLL_INTERVAL_SECONDS = 0.05
_LOCK_TIMEOUT_SECONDS = 15.0
_PROVIDER_TTL_ENV_KEYS = {
    "newsapi_ai": "NEWSAPI_AI_SHARED_CACHE_TTL_SECONDS",
}


@dataclass(frozen=True)
class CachedNewsBatch:
    provider: str
    scope: dict[str, Any]
    items: list[NewsItem]
    raw_count: int
    cursor: float
    fetched_at: float
    raw_items: list[NewsItem] = field(default_factory=list)
    from_cache: bool = False


def resolved_shared_cache_ttl_seconds(provider: str, default_ttl_seconds: float) -> float:
    resolved_default = max(float(default_ttl_seconds or 0.0), 0.0)
    env_key = _PROVIDER_TTL_ENV_KEYS.get(str(provider or "").strip().lower())
    if not env_key:
        return resolved_default
    raw_value = str(os.getenv(env_key, "") or "").strip()
    if not raw_value:
        return resolved_default
    try:
        return max(float(raw_value), 0.0)
    except (TypeError, ValueError):
        return resolved_default


def default_shared_cache_dir(cache_dir: str | Path | None = None) -> Path:
    if cache_dir is not None:
        return Path(cache_dir)
    return Path(os.getenv("SHARED_NEWS_CACHE_DIR", DEFAULT_SHARED_NEWS_CACHE_DIR))


def news_item_timestamp(item: NewsItem) -> float:
    published_ts = float(item.published_ts or 0.0)
    updated_ts = float(item.updated_ts or 0.0)
    return max(updated_ts, published_ts, 0.0)


def filter_news_items_since(items: list[NewsItem], min_cursor: float) -> list[NewsItem]:
    threshold = max(float(min_cursor or 0.0), 0.0)
    if threshold <= 0.0:
        return list(items)
    return [item for item in items if news_item_timestamp(item) > threshold]


def tv_headline_to_news_item(headline: Any) -> NewsItem:
    provider_name = str(getattr(headline, "provider", "unknown") or "unknown").strip().lower()
    published_ts = float(getattr(headline, "published", 0.0) or 0.0)
    title = str(getattr(headline, "title", "") or "").strip()
    item_id = str(getattr(headline, "id", "") or "").strip()
    if not item_id:
        digest = hashlib.md5(title.encode("utf-8", errors="replace"), usedforsecurity=False).hexdigest()[:10]
        item_id = f"tv_{int(published_ts)}_{digest}"
    tickers = [
        str(ticker or "").strip().upper()
        for ticker in (getattr(headline, "tickers", []) or [])
        if str(ticker or "").strip()
    ]
    url = str(getattr(headline, "story_url", "") or "").strip() or None
    source = str(getattr(headline, "source", provider_name or "TradingView") or provider_name or "TradingView").strip()
    raw = {
        "id": item_id,
        "title": title,
        "provider": provider_name,
        "source": source,
        "published": published_ts,
        "tickers": list(tickers),
        "story_url": url,
        "urgency": getattr(headline, "urgency", None),
        "is_exclusive": getattr(headline, "is_exclusive", False),
        "is_flash": getattr(headline, "is_flash", False),
    }
    return NewsItem(
        provider=f"tv_{provider_name}",
        item_id=item_id,
        published_ts=published_ts,
        updated_ts=published_ts,
        headline=title,
        snippet="",
        tickers=tickers,
        url=url,
        source=source,
        raw=raw,
    )


def fetch_cached_batch(
    *,
    provider: str,
    scope: dict[str, Any] | None,
    ttl_seconds: float,
    min_cursor: float,
    fetcher: Callable[[], list[NewsItem] | Any],
    cache_dir: str | Path | None = None,
) -> CachedNewsBatch:
    resolved_scope = dict(scope or {})
    cache_root = default_shared_cache_dir(cache_dir)
    cache_root.mkdir(parents=True, exist_ok=True)
    cache_path = _cache_path(cache_root, provider, resolved_scope)
    lock_path = cache_path.with_suffix(cache_path.suffix + ".lock")
    effective_ttl_seconds = resolved_shared_cache_ttl_seconds(provider, ttl_seconds)

    with _file_lock(lock_path):
        cached_payload = _read_payload(cache_path)
        if _payload_is_reusable(cached_payload, ttl_seconds=effective_ttl_seconds, min_cursor=min_cursor):
            if cached_payload is None:
                raise RuntimeError("_payload_is_reusable returned True for None payload")
            return _filtered_batch(_payload_to_batch(provider, cached_payload, from_cache=True), min_cursor=min_cursor)

        raw_items = _coerce_news_items(fetcher())
        fetched_at = time.time()
        batch = CachedNewsBatch(
            provider=provider,
            scope=resolved_scope,
            items=raw_items,
            raw_items=list(raw_items),
            raw_count=len(raw_items),
            cursor=max([max(float(min_cursor or 0.0), 0.0), *[news_item_timestamp(item) for item in raw_items]], default=max(float(min_cursor or 0.0), 0.0)),
            fetched_at=fetched_at,
            from_cache=False,
        )
        _write_payload(cache_path, _batch_to_payload(batch))
        return _filtered_batch(batch, min_cursor=min_cursor)


def _coerce_news_items(value: Any) -> list[NewsItem]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, NewsItem)]


def _filtered_batch(batch: CachedNewsBatch, *, min_cursor: float) -> CachedNewsBatch:
    raw_items = list(batch.raw_items or batch.items)
    return CachedNewsBatch(
        provider=batch.provider,
        scope=dict(batch.scope),
        items=filter_news_items_since(raw_items, min_cursor=min_cursor),
        raw_items=raw_items,
        raw_count=batch.raw_count,
        cursor=batch.cursor,
        fetched_at=batch.fetched_at,
        from_cache=batch.from_cache,
    )


def _payload_is_reusable(payload: dict[str, Any] | None, *, ttl_seconds: float, min_cursor: float) -> bool:
    if not isinstance(payload, dict):
        return False
    fetched_at = float(payload.get("fetched_at") or 0.0)
    if fetched_at <= 0.0:
        return False
    age_seconds = max(time.time() - fetched_at, 0.0)
    if age_seconds > max(float(ttl_seconds or 0.0), 0.0):
        return False
    cached_cursor = float(payload.get("cursor") or 0.0)
    return cached_cursor >= max(float(min_cursor or 0.0), 0.0)


def _cache_path(cache_root: Path, provider: str, scope: dict[str, Any]) -> Path:
    scope_json = json.dumps(scope, sort_keys=True, separators=(",", ":"), default=str)
    digest = hashlib.sha1(scope_json.encode("utf-8"), usedforsecurity=False).hexdigest()[:16]
    safe_provider = provider.replace("/", "_")
    return cache_root / f"{safe_provider}__{digest}.json"


def _batch_to_payload(batch: CachedNewsBatch) -> dict[str, Any]:
    return {
        "provider": batch.provider,
        "scope": batch.scope,
        "raw_count": batch.raw_count,
        "cursor": batch.cursor,
        "fetched_at": batch.fetched_at,
        "items": [_serialize_news_item(item) for item in batch.items],
    }


def _payload_to_batch(provider: str, payload: dict[str, Any], *, from_cache: bool) -> CachedNewsBatch:
    items = [_deserialize_news_item(item) for item in payload.get("items") or [] if isinstance(item, dict)]
    return CachedNewsBatch(
        provider=provider,
        scope=dict(payload.get("scope") or {}),
        items=items,
        raw_items=list(items),
        raw_count=int(payload.get("raw_count") or 0),
        cursor=float(payload.get("cursor") or 0.0),
        fetched_at=float(payload.get("fetched_at") or 0.0),
        from_cache=from_cache,
    )


def _serialize_news_item(item: NewsItem) -> dict[str, Any]:
    return {
        "provider": item.provider,
        "item_id": item.item_id,
        "published_ts": item.published_ts,
        "updated_ts": item.updated_ts,
        "headline": item.headline,
        "snippet": item.snippet,
        "tickers": list(item.tickers),
        "url": item.url,
        "source": item.source,
        "raw": item.raw,
    }


def _deserialize_news_item(payload: dict[str, Any]) -> NewsItem:
    return NewsItem(
        provider=str(payload.get("provider") or "").strip(),
        item_id=str(payload.get("item_id") or "").strip(),
        published_ts=float(payload.get("published_ts") or 0.0),
        updated_ts=float(payload.get("updated_ts") or 0.0),
        headline=str(payload.get("headline") or "").strip(),
        snippet=str(payload.get("snippet") or ""),
        tickers=[str(item).strip().upper() for item in payload.get("tickers") or [] if str(item).strip()],
        url=(str(payload.get("url") or "").strip() or None),
        source=str(payload.get("source") or "").strip(),
        raw=dict(payload.get("raw") or {}),
    )


def _read_payload(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _write_payload(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        dir=str(path.parent),
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    os.close(fd)
    tmp_path = Path(tmp_name)
    try:
        tmp_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        # mkstemp creates the temp file as 0o600; preserve the destination's
        # existing permissions so a shared (e.g. group-readable) cache file is
        # not silently downgraded when it is rewritten.
        with suppress(FileNotFoundError):
            os.chmod(tmp_path, stat.S_IMODE(os.stat(path).st_mode))
        os.replace(tmp_path, path)
    except BaseException:
        with suppress(OSError):
            tmp_path.unlink()
        raise


@contextmanager
def _file_lock(lock_path: Path):
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    # Audit 2026-05-10 (PR-J1): use time.monotonic() for the deadline.
    # time.time() is wall-clock and can jump BACKWARDS (NTP correction,
    # VM live-migrate, manual `date -s`); a backwards jump prevents the
    # original deadline from ever expiring and the lock-waiter loops
    # forever, deadlocking every shared-fetch caller.
    deadline = time.monotonic() + _LOCK_TIMEOUT_SECONDS
    fd: int | None = None
    while True:
        try:
            fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(os.getpid()).encode("utf-8"))
            break
        except FileExistsError:
            if time.monotonic() >= deadline:
                raise TimeoutError(f"Timed out waiting for shared news cache lock: {lock_path}") from None
            time.sleep(_LOCK_POLL_INTERVAL_SECONDS)
    try:
        yield
    finally:
        if fd is not None:
            os.close(fd)
        with suppress(FileNotFoundError):
            lock_path.unlink()
