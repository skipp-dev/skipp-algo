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
from typing import Any, Dict, List, Optional

import httpx

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


def rotate_jsonl(path: str, max_lines: int = 5000) -> None:
    """Trim JSONL file to the last *max_lines* lines if it grows too big.

    This avoids unbounded growth while keeping enough history for
    VisiData sessions.  Called periodically (e.g. every 100 polls).
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        if len(lines) <= max_lines:
            return
        with open(path, "w", encoding="utf-8") as f:
            f.writelines(lines[-max_lines:])
        logger.info("Rotated JSONL %s: %d → %d lines", path, len(lines), max_lines)
    except FileNotFoundError:
        pass


def load_jsonl_feed(path: str, max_items: int = 500) -> list[dict[str, Any]]:
    """Read persisted JSONL feed file and return newest-first list of dicts.

    Used on Streamlit startup to restore the feed so that users don't
    see "No items yet" after a page reload.
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
    # Newest first (JSONL is append-order, so reverse)
    result.reverse()
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
) -> Dict[str, Dict[str, Any]]:
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
        result: Dict[str, Dict[str, Any]] = {}
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
    feed: List[Dict[str, Any]],
    rt_quotes: Optional[Dict[str, Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """Build one row per ticker from the full feed, ranked by best news_score.

    When *rt_quotes* is provided (from ``load_rt_quotes()``), the live
    quote fields (tick, streak, price, chg_pct, vol_ratio) are
    merged in from the RT engine's latest snapshot.

    Columns mirror the open_prep realtime VisiData format:
    symbol, N, sentiment, tick, score, streak, category, event,
    materiality, impact, clarity, sentiment_score, polarity, recency,
    age_min, actionable, price, chg_pct, vol_ratio
    """
    if rt_quotes is None:
        rt_quotes = {}

    best: Dict[str, Dict[str, Any]] = {}   # ticker → best-scored item
    counts: Dict[str, int] = {}             # ticker → article count

    for d in feed:
        tk = d.get("ticker", "?")
        if tk == "MARKET":
            continue
        counts[tk] = counts.get(tk, 0) + 1
        prev = best.get(tk)
        if prev is None or d.get("news_score", 0) > prev.get("news_score", 0):
            best[tk] = d

    rows: List[Dict[str, Any]] = []
    for tk, d in best.items():
        sent_label = d.get("sentiment_label", "neutral")
        rt = rt_quotes.get(tk, {})

        rows.append({
            "symbol":           tk,
            "N":                counts.get(tk, 0),
            "sentiment":        _SENT_EMOJI.get(sent_label, "🟡"),
            "tick":             rt.get("tick", ""),
            "score":            round(d.get("news_score", 0), 4),
            "streak":           rt.get("streak", 0),
            "category":         d.get("category", ""),
            "event":            d.get("event_label", ""),
            "materiality":      d.get("materiality", ""),
            "impact":           d.get("impact", 0),
            "clarity":          d.get("clarity", 0),
            "sentiment_score":  d.get("sentiment_score", 0),
            "polarity":         d.get("polarity", 0),
            "recency":          d.get("recency_bucket", ""),
            "age_min":          round(d.get("age_minutes", 0) or 0, 1),
            "actionable":       "✅" if d.get("is_actionable") else "",
            "price":            rt.get("price", 0.0),
            "chg_pct":          rt.get("chg_pct", 0.0),
            "vol_ratio":        rt.get("vol_ratio", 0.0),
        })

    # Sort by score descending
    rows.sort(key=lambda r: r.get("score", 0), reverse=True)
    return rows


def save_vd_snapshot(
    feed: List[Dict[str, Any]],
    path: str = _VD_SNAPSHOT_DEFAULT,
    rt_jsonl_path: str = _RT_VD_SIGNALS_DEFAULT,
) -> None:
    """Write per-symbol VisiData JSONL — atomic overwrite, one line per ticker.

    Automatically loads RT engine quotes from *rt_jsonl_path* (if the RT
    engine is running and the file is fresh) and merges live quote fields
    (tick, streak, price, chg_pct, vol_ratio) into each row.

    Uses the same atomic-replace pattern as the RT engine
    (tempfile + os.replace) so VisiData can ``--reload`` every few
    seconds without reading a half-written file.
    """
    rt_quotes = load_rt_quotes(rt_jsonl_path)
    rows = build_vd_snapshot(feed, rt_quotes=rt_quotes)
    if not rows:
        return

    dest = os.path.abspath(path)
    dest_dir = os.path.dirname(dest)
    os.makedirs(dest_dir, exist_ok=True)

    try:
        fd, tmp_path = tempfile.mkstemp(dir=dest_dir, suffix=".tmp", prefix="vd_")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
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
) -> Optional[Dict[str, Any]]:
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

    payload: Dict[str, Any] = {
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
    headers: Dict[str, str] = {"Content-Type": "application/json"}
    if secret:
        headers["X-Signature-256"] = f"sha256={_sign_payload(body, secret)}"

    try:
        with httpx.Client(timeout=timeout) as client:
            r = client.post(url, content=body, headers=headers)
            r.raise_for_status()
            logger.info(
                "Webhook fired for %s (score=%.3f): HTTP %d",
                item.ticker, item.news_score, r.status_code,
            )
            try:
                return r.json()
            except Exception:
                return {"status": r.status_code, "text": r.text[:200]}
    except Exception as exc:
        logger.warning("Webhook failed for %s: %s", item.ticker, exc)
        return None
