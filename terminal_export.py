"""Export utilities for the Bloomberg Terminal.

- **JSONL writer**: appends one JSON object per line for VisiData tailing.
- **VisiData snapshot**: per-symbol ranked JSONL (atomic overwrite, one row per ticker).
- **TradersPost webhook stub**: fires HTTP POST when a high-score item arrives.

Both functions are safe to call even when disabled — they short-circuit
on empty config values.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import tempfile
import time
from datetime import UTC, datetime
from typing import Any

import httpx

from open_prep.playbook import classify_recency
from terminal_poller import ClassifiedItem

logger = logging.getLogger(__name__)


# ── JSONL Export for VisiData ───────────────────────────────────

def append_jsonl(item: ClassifiedItem, path: str) -> None:
    """Append one classified item as a single JSON line.

    Creates the file + parent directories if they don't exist.
    Each line is a self-contained JSON object that VisiData can
    read with ``vd --filetype jsonl <path>``.
    """
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    line = json.dumps(item.to_dict(), ensure_ascii=False, default=str)
    with open(path, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def rewrite_jsonl(path: str, items: list[dict[str, Any]]) -> None:
    """Atomically rewrite *path* with only the given *items*.

    Used after in-memory prune so that stale entries are removed from
    disk and won't reappear when the next Streamlit session starts.

    Items are written in **chronological order** (oldest ``published_ts``
    first) so the on-disk convention matches ``append_jsonl`` (newest at
    the end).  ``load_jsonl_feed`` reverses the file on read, so the
    newest items always appear first in memory.
    """
    # Sort oldest-first before writing so subsequent load+reverse works
    sorted_items = sorted(
        items,
        key=lambda d: d.get("published_ts") or d.get("updated_ts") or 0,
    )
    dest_dir = os.path.dirname(os.path.abspath(path)) or "."
    os.makedirs(dest_dir, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=dest_dir, suffix=".tmp", prefix="rw_")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            for d in sorted_items:
                fh.write(json.dumps(d, default=str) + "\n")
        os.replace(tmp_path, path)
        logger.info("Rewrote JSONL %s with %d items", path, len(sorted_items))
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def rotate_jsonl(path: str, max_lines: int = 5000, max_age_s: float = 14400.0) -> None:
    """Trim JSONL file to the last *max_lines* lines and drop stale entries.

    Uses atomic tempfile + os.replace so a crash during rotation
    cannot truncate/corrupt the existing file.
    Called periodically (e.g. every 100 polls).

    When *max_age_s* > 0, lines whose ``published_ts`` is older than
    ``time.time() - max_age_s`` are dropped regardless of count.
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except FileNotFoundError:
        return

    # Age-based filtering
    cutoff = time.time() - max_age_s if max_age_s > 0 else 0.0
    if cutoff:
        fresh_lines: list[str] = []
        for raw in lines:
            try:
                d = json.loads(raw)
                if (d.get("published_ts") or 0) >= cutoff:
                    fresh_lines.append(raw)
            except (json.JSONDecodeError, TypeError):
                fresh_lines.append(raw)  # keep unparseable lines
        lines = fresh_lines

    # Line-count cap
    if len(lines) <= max_lines and not cutoff:
        return
    keep = lines[-max_lines:] if len(lines) > max_lines else lines

    dest_dir = os.path.dirname(os.path.abspath(path)) or "."
    fd, tmp_path = tempfile.mkstemp(dir=dest_dir, suffix=".tmp", prefix="rot_")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.writelines(keep)
        os.replace(tmp_path, path)
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
    logger.info("Rotated JSONL %s: %d → %d lines", path, len(lines), len(keep))


def load_jsonl_feed(path: str, max_items: int = 500) -> list[dict[str, Any]]:
    """Read persisted JSONL feed file and return newest-first list of dicts.

    Used on Streamlit startup to restore the feed so that users don't
    see "No items yet" after a page reload.

    Items are sorted by ``published_ts`` descending (newest first) so
    the result is independent of the on-disk line order.  This is more
    robust than relying on ``reverse()`` of append order, which can
    break if ``rewrite_jsonl`` or ``rotate_jsonl`` reorder lines.
    """
    result: list[dict[str, Any]] = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for raw in f:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    result.append(json.loads(raw))
                except json.JSONDecodeError:
                    continue
    except FileNotFoundError:
        return []
    # Sort by timestamp descending — always correct regardless of
    # on-disk line order (append, rewrite, rotate all may differ).
    result.sort(
        key=lambda d: d.get("published_ts") or d.get("updated_ts") or 0,
        reverse=True,
    )
    if len(result) > max_items:
        result = result[:max_items]
    return result


# ── VisiData Per-Symbol Snapshot ────────────────────────────────

_VD_SNAPSHOT_DEFAULT = "artifacts/terminal_vd.jsonl"
_RT_VD_SIGNALS_DEFAULT = "artifacts/open_prep/latest/latest_vd_signals.jsonl"

_SENT_EMOJI = {"bullish": "🟢", "bearish": "🔴", "neutral": "🟡"}

# Fields copied from RT engine rows into the terminal VisiData snapshot
_RT_QUOTE_FIELDS = ("direction", "tick", "streak", "price", "chg_pct", "vol_ratio")


def load_rt_quotes(
    path: str = _RT_VD_SIGNALS_DEFAULT,
    max_age_s: float = 120.0,
) -> dict[str, dict[str, Any]]:
    """Read RT engine's per-symbol VisiData JSONL and return {SYMBOL: row}.

    Returns an empty dict if the file doesn't exist, is unreadable,
    or is older than *max_age_s* seconds (stale safety guard — the RT
    engine must still be actively polling for the data to be useful).
    """
    try:
        if not os.path.isfile(path):
            return {}
        # Stale guard: skip if the file hasn't been updated recently
        mtime = os.path.getmtime(path)
        if max_age_s > 0 and (time.time() - mtime) > max_age_s:
            logger.debug("RT JSONL stale (age=%.0fs > %.0fs): %s",
                         time.time() - mtime, max_age_s, path)
            return {}
        result: dict[str, dict[str, Any]] = {}
        with open(path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                    sym = str(row.get("symbol", "")).upper()
                    if sym:
                        result[sym] = row
                except json.JSONDecodeError:
                    continue
        return result
    except Exception as exc:
        logger.debug("Failed to load RT quotes from %s: %s", path, exc)
        return {}


def build_vd_snapshot(
    feed: list[dict[str, Any]],
    rt_quotes: dict[str, dict[str, Any]] | None = None,
    bz_quotes: list[dict[str, Any]] | None = None,
    max_age_s: float = 14400.0,
    bz_dividends: list[dict[str, Any]] | None = None,
    bz_guidance: list[dict[str, Any]] | None = None,
    bz_options: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Build one row per ticker from the full feed, ranked by best news_score.

    When *rt_quotes* is provided (from ``load_rt_quotes()``), the live
    quote fields (tick, streak, price, chg_pct, vol_ratio) are
    merged in from the RT engine's latest snapshot.

    When *bz_quotes* is provided (from Benzinga delayed quotes), they
    serve as a **fallback** for symbols not covered by the RT engine.
    During extended hours (pre-market / after-hours), Benzinga delayed
    quotes are the freshest price source available.

    When *bz_dividends*, *bz_guidance*, or *bz_options* are provided
    (from Benzinga calendar/financial endpoints), enrichment columns
    are added per symbol: div_exdate, div_yield, guid_eps, options_flow.

    Time-dependent fields (age_min, recency, actionable) are
    **recomputed live** from the item's ``published_ts`` so the
    VisiData snapshot always reflects current staleness — not the
    frozen value from classification time.

    Items older than *max_age_s* (default 4 h) are excluded so the
    snapshot does not show stale symbols.

    Columns mirror the open_prep realtime VisiData format:
    symbol, N, sentiment, tick, score, streak, category, event,
    materiality, impact, clarity, sentiment_score, polarity, recency,
    age_min, actionable, price, chg_pct, vol_ratio,
    div_exdate, div_yield, guid_eps, options_flow
    """
    if rt_quotes is None:
        rt_quotes = {}

    # Build Benzinga quote lookup (symbol → quote dict)
    bz_by_sym: dict[str, dict[str, Any]] = {}
    if bz_quotes:
        for q in bz_quotes:
            sym = (q.get("symbol") or "").upper().strip()
            if sym:
                bz_by_sym[sym] = q

    # Build Benzinga enrichment lookups (ticker → best entry)
    _div_by_sym: dict[str, dict[str, Any]] = {}
    if bz_dividends:
        for d in bz_dividends:
            sym = (d.get("ticker") or "").upper().strip()
            if sym:
                _div_by_sym.setdefault(sym, d)

    _guid_by_sym: dict[str, dict[str, Any]] = {}
    if bz_guidance:
        for g in bz_guidance:
            sym = (g.get("ticker") or "").upper().strip()
            if sym:
                _guid_by_sym.setdefault(sym, g)

    _opts_by_sym: dict[str, dict[str, Any]] = {}
    if bz_options:
        for o in bz_options:
            sym = (o.get("ticker") or "").upper().strip()
            if sym:
                _opts_by_sym.setdefault(sym, o)

    best: dict[str, dict[str, Any]] = {}   # ticker → best-scored item
    counts: dict[str, int] = {}             # ticker → article count

    cutoff = time.time() - max_age_s if max_age_s > 0 else 0.0

    for d in feed:
        tk = d.get("ticker", "?")
        if tk == "MARKET":
            continue
        # Skip stale items
        if cutoff and (d.get("published_ts") or 0) < cutoff:
            continue
        counts[tk] = counts.get(tk, 0) + 1
        prev = best.get(tk)
        if prev is None or d.get("news_score", 0) > prev.get("news_score", 0):
            best[tk] = d

    now = time.time()
    rows: list[dict[str, Any]] = []
    for tk, d in best.items():
        sent_label = d.get("sentiment_label", "neutral")
        rt = rt_quotes.get(tk, {})

        # Price data priority: RT engine > Benzinga delayed quotes
        # Use `is not None` — 0.0 is a valid value (e.g. flat stock chg_pct=0)
        _rt_price = rt.get("price")
        _rt_chg = rt.get("chg_pct")
        _rt_vol = rt.get("vol_ratio")
        price = _rt_price if _rt_price is not None else None
        chg_pct = _rt_chg if _rt_chg is not None else None
        vol_ratio = _rt_vol if _rt_vol is not None else None
        tick = rt.get("tick", "")
        streak = rt.get("streak", 0)

        # Fallback to Benzinga delayed quotes when RT has no data
        if price is None and tk in bz_by_sym:
            bq = bz_by_sym[tk]
            bz_last = bq.get("last")
            if bz_last is not None:
                try:
                    price = round(float(bz_last), 2)
                except (ValueError, TypeError):
                    pass
            bz_chg = bq.get("changePercent")
            if bz_chg is not None and chg_pct is None:
                try:
                    chg_pct = round(float(bz_chg), 2)
                except (ValueError, TypeError):
                    pass

        # Recompute recency live from published_ts
        pub_ts = d.get("published_ts")
        if pub_ts and pub_ts > 0:
            live_age_min = max((now - pub_ts) / 60.0, 0.0)
            article_dt = datetime.fromtimestamp(pub_ts, tz=UTC)
            recency = classify_recency(article_dt)
            recency_bucket = recency["recency_bucket"]
            is_actionable = recency["is_actionable"]
        else:
            live_age_min = d.get("age_minutes") or 0
            recency_bucket = d.get("recency_bucket", "")
            is_actionable = d.get("is_actionable", False)

        rows.append({
            "symbol":           tk,
            "N":                counts.get(tk, 0),
            "sentiment":        _SENT_EMOJI.get(sent_label, "🟡"),
            "tick":             tick,
            "score":            round(d.get("news_score", 0), 4),
            "relevance":        round(d.get("relevance", 0), 4),
            "streak":           streak,
            "category":         d.get("category", ""),
            "event":            d.get("event_label", ""),
            "materiality":      d.get("materiality", ""),
            "impact":           d.get("impact", 0),
            "clarity":          d.get("clarity", 0),
            "sentiment_score":  d.get("sentiment_score", 0),
            "polarity":         d.get("polarity", 0),
            "recency":          recency_bucket,
            "age_min":          round(live_age_min, 1),
            "actionable":       "✅" if is_actionable else "",
            "headline":         (d.get("headline", "") or "")[:120],
            "url":              d.get("url", ""),
            "provider":         d.get("provider", ""),
            "price":            price,
            "chg_pct":          chg_pct,
            "vol_ratio":        vol_ratio,
            # Benzinga enrichment columns
            "div_exdate":       _div_by_sym.get(tk, {}).get("ex_date", ""),
            "div_yield":        _div_by_sym.get(tk, {}).get("dividend_yield", ""),
            "guid_eps":         _guid_by_sym.get(tk, {}).get("eps_guidance_est", ""),
            "options_flow":     "🎰" if tk in _opts_by_sym else "",
        })

    # Composite rank: 70% absolute price change + 30% news score
    for r in rows:
        _chg = abs(float(r.get("chg_pct") or 0))
        _ns = float(r.get("score") or 0)
        r["rank_score"] = round(_chg * 0.7 + _ns * 100.0 * 0.3, 2)

    # Sort by rank_score desc, then freshest first, then symbol asc
    rows.sort(key=lambda r: (-r.get("rank_score", 0), r.get("age_min", 9999), r.get("symbol", "")))
    return rows


def save_vd_snapshot(
    feed: list[dict[str, Any]],
    path: str = _VD_SNAPSHOT_DEFAULT,
    rt_jsonl_path: str = _RT_VD_SIGNALS_DEFAULT,
    max_age_s: float = 14400.0,
    bz_quotes: list[dict[str, Any]] | None = None,
    bz_dividends: list[dict[str, Any]] | None = None,
    bz_guidance: list[dict[str, Any]] | None = None,
    bz_options: list[dict[str, Any]] | None = None,
) -> None:
    """Write per-symbol VisiData JSONL — atomic overwrite, one line per ticker.

    Automatically loads RT engine quotes from *rt_jsonl_path* (if the RT
    engine is running and the file is fresh) and merges live quote fields
    (tick, streak, price, chg_pct, vol_ratio) into each row.

    When *bz_quotes* is provided (Benzinga delayed quotes), they serve as
    a fallback for symbols not covered by the RT engine — keeping the
    VisiData file fresh during extended hours.

    When *bz_dividends*, *bz_guidance*, or *bz_options* are provided,
    enrichment columns (div_exdate, div_yield, guid_eps, options_flow)
    are added per symbol.

    Items older than *max_age_s* are excluded (pass 0 to disable).

    Uses the same atomic-replace pattern as the RT engine
    (tempfile + os.replace) so VisiData can ``--reload`` every few
    seconds without reading a half-written file.
    """
    rt_quotes = load_rt_quotes(rt_jsonl_path)
    rows = build_vd_snapshot(
        feed, rt_quotes=rt_quotes, bz_quotes=bz_quotes, max_age_s=max_age_s,
        bz_dividends=bz_dividends, bz_guidance=bz_guidance, bz_options=bz_options,
    )
    if not rows:
        return

    # Compute snapshot-level freshness metadata
    now_epoch = time.time()
    _newest_age = min((r.get("age_min", 9999) for r in rows), default=0)
    _stale_warn = "⚠️ STALE" if _newest_age > 2 else ""
    _meta_row: dict[str, Any] = {
        "symbol":    f"_META {_stale_warn}".strip(),
        "N":         len(rows),
        "sentiment": "",
        "tick":      "",
        "score":     0,
        "relevance": 0,
        "streak":    0,
        "category":  f"snapshot {datetime.fromtimestamp(now_epoch, tz=UTC).strftime('%H:%M:%S')} UTC",
        "event":     f"feed_age={_newest_age:.0f}m",
        "materiality": _stale_warn or "OK",
        "headline":  f"{len(rows)} symbols · newest {_newest_age:.0f}m ago",
    }

    dest = os.path.abspath(path)
    dest_dir = os.path.dirname(dest)
    os.makedirs(dest_dir, exist_ok=True)

    try:
        fd, tmp_path = tempfile.mkstemp(dir=dest_dir, suffix=".tmp", prefix="vd_")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                # Meta row first — immediately visible in VisiData
                fh.write(json.dumps(_meta_row, ensure_ascii=False, default=str))
                fh.write("\n")
                for row in rows:
                    fh.write(json.dumps(row, ensure_ascii=False, default=str))
                    fh.write("\n")
            os.replace(tmp_path, dest)
        except BaseException:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
    except Exception as exc:
        logger.debug("VisiData snapshot write failed: %s", exc)


# ── Benzinga Calendar JSONL Export ─────────────────────────────

_VD_BZ_CALENDAR_DEFAULT = "vd_bz_calendar.jsonl"


def build_vd_bz_calendar(
    bz_dividends: list[dict[str, Any]] | None = None,
    bz_splits: list[dict[str, Any]] | None = None,
    bz_ipos: list[dict[str, Any]] | None = None,
    bz_guidance: list[dict[str, Any]] | None = None,
    bz_retail: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Build a flat JSONL-ready list from all Benzinga calendar types.

    Each row includes a ``type`` column (``dividend``, ``split``, ``ipo``,
    ``guidance``, ``retail``) and the key fields from that calendar type.
    This creates a unified VisiData-friendly view of upcoming corporate
    events that complements the per-symbol news snapshot.

    Returns
    -------
    list[dict]
        One dict per calendar event, sorted by date descending.
    """
    rows: list[dict[str, Any]] = []

    for d in (bz_dividends or []):
        rows.append({
            "type":       "dividend",
            "ticker":     d.get("ticker", ""),
            "name":       d.get("name", ""),
            "date":       d.get("ex_date", d.get("date", "")),
            "detail":     f"${d.get('dividend', '?')} (yield: {d.get('dividend_yield', '?')})",
            "frequency":  d.get("frequency", ""),
            "importance": d.get("importance", ""),
        })

    for s in (bz_splits or []):
        rows.append({
            "type":       "split",
            "ticker":     s.get("ticker", ""),
            "name":       s.get("name", ""),
            "date":       s.get("date_ex", s.get("date", "")),
            "detail":     f"Ratio: {s.get('ratio', '?')}",
            "frequency":  "",
            "importance": s.get("importance", ""),
        })

    for i in (bz_ipos or []):
        rows.append({
            "type":       "ipo",
            "ticker":     i.get("ticker", ""),
            "name":       i.get("name", ""),
            "date":       i.get("pricing_date", i.get("date", "")),
            "detail":     f"${i.get('price_min', '?')}-${i.get('price_max', '?')} | {i.get('deal_status', '?')}",
            "frequency":  "",
            "importance": i.get("importance", ""),
        })

    for g in (bz_guidance or []):
        rows.append({
            "type":       "guidance",
            "ticker":     g.get("ticker", ""),
            "name":       g.get("name", ""),
            "date":       g.get("date", ""),
            "detail":     f"EPS: {g.get('eps_guidance_est', '?')} | Rev: {g.get('revenue_guidance_est', '?')}",
            "frequency":  f"{g.get('period', '')} {g.get('period_year', '')}".strip(),
            "importance": g.get("importance", ""),
        })

    for r in (bz_retail or []):
        rows.append({
            "type":       "retail",
            "ticker":     r.get("ticker", ""),
            "name":       r.get("name", ""),
            "date":       r.get("date", ""),
            "detail":     f"SSS: {r.get('sss', '?')} (est: {r.get('sss_est', '?')}) surprise: {r.get('retail_surprise', '?')}",
            "frequency":  f"{r.get('period', '')} {r.get('period_year', '')}".strip(),
            "importance": r.get("importance", ""),
        })

    # Sort by date descending (most recent first)
    rows.sort(key=lambda x: str(x.get("date", "")), reverse=True)
    return rows


def save_vd_bz_calendar(
    bz_dividends: list[dict[str, Any]] | None = None,
    bz_splits: list[dict[str, Any]] | None = None,
    bz_ipos: list[dict[str, Any]] | None = None,
    bz_guidance: list[dict[str, Any]] | None = None,
    bz_retail: list[dict[str, Any]] | None = None,
    path: str = _VD_BZ_CALENDAR_DEFAULT,
) -> None:
    """Write Benzinga calendar data as a JSONL file for VisiData.

    Creates a unified view of dividends, splits, IPOs, guidance, and
    retail events — one line per event, sorted by date.
    Atomic write (tmp + rename) to avoid partial reads.
    """
    rows = build_vd_bz_calendar(
        bz_dividends=bz_dividends,
        bz_splits=bz_splits,
        bz_ipos=bz_ipos,
        bz_guidance=bz_guidance,
        bz_retail=bz_retail,
    )
    if not rows:
        logger.debug("No BZ calendar data to write to %s", path)
        return

    tmp_path = path + ".tmp"
    try:
        with open(tmp_path, "w") as fh:
            for row in rows:
                fh.write(json.dumps(row, default=str) + "\n")
        os.replace(tmp_path, path)
        logger.debug("Wrote %d BZ calendar events to %s", len(rows), path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


# ── TradersPost Webhook Stub ───────────────────────────────────

def _sign_payload(payload: bytes, secret: str) -> str:
    """HMAC-SHA256 signature for webhook payload."""
    return hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()


def fire_webhook(
    item: ClassifiedItem,
    url: str,
    secret: str = "",
    timeout: float = 5.0,
    min_score: float = 0.70,
    _client: httpx.Client | None = None,
) -> dict[str, Any] | None:
    """POST a classified item to TradersPost (or any webhook receiver).

    Guarded:
    - If ``url`` is empty, returns ``None`` immediately (disabled).
    - If ``item.news_score < min_score``, skips (not worth alerting).

    Parameters
    ----------
    item : ClassifiedItem
        The enriched news item to send.
    url : str
        Webhook endpoint URL.  Empty string = disabled.
    secret : str
        HMAC-SHA256 signing secret.  Empty = no signature header.
    timeout : float
        HTTP timeout in seconds.
    min_score : float
        Minimum news_score to fire the webhook.
    _client : httpx.Client, optional
        Pre-created httpx client to reuse across multiple calls.
        When provided the caller is responsible for closing it.
        When ``None`` (default) a one-shot client is created per call.

    Returns
    -------
    dict or None
        Response JSON on success, None on skip/error.
    """
    if not url:
        return None
    if item.news_score < min_score:
        return None

    # Map sentiment to simple action hint
    action = "watch"
    if item.sentiment_label == "bullish" and item.news_score >= 0.80:
        action = "buy"
    elif item.sentiment_label == "bearish" and item.news_score >= 0.80:
        action = "sell"

    payload: dict[str, Any] = {
        "ticker": item.ticker,
        "action": action,
        "headline": item.headline[:200],
        "score": round(item.news_score, 4),
        "sentiment": item.sentiment_label,
        "sentiment_score": item.sentiment_score,
        "event": item.event_label,
        "event_class": item.event_class,
        "materiality": item.materiality,
        "category": item.category,
        "source_tier": item.source_tier,
        "recency": item.recency_bucket,
        "is_actionable": item.is_actionable,
        "url": item.url,
        "timestamp": item.published_ts,
        "fired_at": time.time(),
    }

    body = json.dumps(payload, ensure_ascii=False).encode()
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if secret:
        headers["X-Signature-256"] = f"sha256={_sign_payload(body, secret)}"

    # Reuse caller-provided client or create a one-shot client
    managed = _client is None
    client = _client if _client is not None else httpx.Client(timeout=timeout)
    try:
        r = client.post(url, content=body, headers=headers)
        r.raise_for_status()
        logger.info(
            "Webhook fired for %s (score=%.3f): HTTP %d",
            item.ticker, item.news_score, r.status_code,
        )
        try:
            return dict(r.json())  # type: ignore[arg-type]
        except Exception:
            return {"status": r.status_code, "text": r.text[:200]}
    except Exception as exc:
        logger.warning("Webhook failed for %s: %s", item.ticker, exc)
        return None
    finally:
        if managed:
            client.close()
