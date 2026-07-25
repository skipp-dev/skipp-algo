"""Benzinga WS↔REST shadow-latency recorder (Scope B — measurement only).

Purpose
-------
Quantify whether the Benzinga **WebSocket** push feed delivers market-moving
headlines materially earlier than the **REST** delta-poll path that currently
drives skipp-algo's ``news_catalyst`` A1/A2→A0 upgrade — *before* wiring WS
into the live upgrade trigger. News is an add-on with no proven edge, so this
harness measures the latency gap (and its price-move value) at zero live-trade
risk instead of betting on it.

Zero live-path risk
-------------------
This recorder is **fully standalone**. It runs its *own* WS listener and its
*own* REST poller (at the live cadence) and records, per Benzinga ``item_id``:

    t_published   — Benzinga's own publish epoch (from the payload)
    t_ws          — when the WS frame arrived at this recorder
    t_rest        — when the same id was first seen via a REST poll
    t_x           — RESERVED (always null here) — see "The t_x column" below

It never feeds ``poll_once`` / the live scoring stream, and it does **not** set
``ENABLE_BENZINGA_WS`` in the live pipeline. The production ``realtime_signals``
path stays 100% REST-driven and unchanged.

The t_x column
--------------
The measurable end-goal is to compare Benzinga-WS latency against X/Twitter
(the X Activity API). X posts do **not** share Benzinga's ``item_id``, so a
``t_x`` join needs an *event matcher* (ticker + headline similarity + time
window), which is deliberately out of scope for this PR. The column is
reserved in the record schema, the JSONL, and the analyzer from day one so
that adding X later is a config/matcher step, not a storage/schema change.
A future X source calls ``ledger.observe(item_id, "x", ts, ...)`` once it can
resolve a Benzinga id for the matched event.

Design
------
Mirrors ``scripts/measure_ttf.py``: the join/delta/scoring core is pure and
unit-tested; the WS/REST/flush threads at the bottom are a thin I/O shim.
Finalized records are accumulated in memory and flushed via the blessed
``atomic_write_text`` helper (full atomic rewrite of a date-stamped JSONL) —
the daily headline volume is small, so this stays crash-safe without a raw
append handle.

Usage
-----
    PYTHONPATH=. python scripts/bz_ws_shadow_recorder.py \\
        --rest-interval 30 --linger-seconds 900 --max-runtime 28800

Env: ``BENZINGA_DIRECT_API_KEY`` (or ``BENZINGA_API_KEY``) must be set — the
WS host is always ``api.benzinga.com`` (direct), matching the live adapter.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import logging
import os
import threading
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from scripts.news_event_matcher import SourceItem, items_match

logger = logging.getLogger("bz_ws_shadow_recorder")

# ── Catalyst keyword scorer (deterministic; NO LLM in this path) ─────
#
# Mirrors the fast-path event taxonomy: a small keyword table that flags the
# discrete, market-moving event types worth an edge measurement. Kept
# deliberately simple — the analyzer only uses it to *select* which headlines
# get an (expensive) Databento intraday price-window lookup.
CATALYST_KEYWORDS: dict[str, tuple[str, ...]] = {
    "earnings": ("earnings", "eps", "beats", "misses", "guidance"),
    "offering": ("offering", "dilution", "secondary", "prices $", "shelf"),
    "m_and_a": ("merger", "acquire", "acquisition", "buyout", "takeover"),
    "regulatory": ("fda", "approval", "rejection", "crl", "phase 3", "phase iii"),
    "legal": ("investigation", "subpoena", "lawsuit", "sec charges", "doj"),
    "management": ("resigns", "resignation", "steps down", "ceo", "cfo"),
    "solvency": ("bankruptcy", "chapter 11", "default", "going concern"),
    "capital_return": ("buyback", "repurchase", "dividend", "special dividend"),
    "trading": ("halt", "halted", "resumes trading", "circuit breaker"),
    "contract": ("contract award", "awarded", "wins contract", "selected by"),
    "cyber": ("breach", "ransomware", "cybersecurity incident", "hacked"),
    "analyst": ("upgrade", "downgrade", "initiates", "price target"),
}

# One catalyst family present already flags the headline; the score scales
# with how many distinct families match, saturating at 1.0. This is a coarse
# selector, not a calibrated signal.
_CATALYST_SATURATION = 3.0


def quick_catalyst_score(headline: str) -> float:
    """Return a deterministic ``0.0..1.0`` catalyst score for *headline*.

    Pure and side-effect free. ``0.0`` means no known market-moving event
    keyword was found. The value scales with the number of distinct event
    families matched, saturating at 1.0 after ``_CATALYST_SATURATION`` hits.
    """
    if not headline:
        return 0.0
    hay = headline.lower()
    families_hit = sum(
        1 for kws in CATALYST_KEYWORDS.values() if any(k in hay for k in kws)
    )
    if families_hit == 0:
        return 0.0
    return min(1.0, families_hit / _CATALYST_SATURATION)


# ── Pure join core ──────────────────────────────────────────────────

_ARRIVAL_FIELD: dict[str, str] = {"ws": "t_ws", "rest": "t_rest", "x": "t_x"}


@dataclass
class ShadowRecord:
    """One news event observed across one or more channels."""

    item_id: str
    headline: str = ""
    tickers: list[str] = field(default_factory=list)
    source_name: str = ""  # publisher / author
    t_published: float | None = None
    t_ws: float | None = None
    t_rest: float | None = None
    t_tv: float | None = None  # TradingView arrival, via the cross-source matcher
    t_x: float | None = None  # RESERVED — filled by a future X event matcher
    catalyst_score: float = 0.0
    first_seen_ts: float = 0.0


class ShadowJoinLedger:
    """Thread-safe join of channel sightings keyed by Benzinga ``item_id``.

    First arrival per channel wins (a later sighting never overwrites an
    earlier timestamp). Metadata (published/headline/tickers) is backfilled
    from whichever channel first carries it. ``pop_ready`` emits records once
    they have lingered long enough for the slower channel to have arrived.
    """

    def __init__(self) -> None:
        self._recs: dict[str, ShadowRecord] = {}
        # item_ids already flushed — the REST poller re-returns the same
        # "latest" page every cycle, so without this an id that outlives the
        # linger window would be re-added and emitted again on every poll.
        # Bounded by a day's distinct headlines (small); a daily runner resets it.
        self._emitted: set[str] = set()
        self._lock = threading.Lock()

    def observe(
        self,
        item_id: str,
        channel: str,
        arrival_ts: float,
        *,
        published_ts: float | None = None,
        headline: str | None = None,
        tickers: list[str] | None = None,
    ) -> None:
        """Record that *item_id* was seen on *channel* at *arrival_ts*."""
        field_name = _ARRIVAL_FIELD.get(channel)
        if field_name is None:
            raise ValueError(
                f"unknown channel {channel!r}; expected one of {sorted(_ARRIVAL_FIELD)}"
            )
        if not item_id:
            return
        with self._lock:
            if item_id in self._emitted:
                return  # already flushed — do not resurrect on a re-sighting
            rec = self._recs.get(item_id)
            if rec is None:
                rec = ShadowRecord(item_id=item_id, first_seen_ts=arrival_ts)
                self._recs[item_id] = rec
            # First arrival per channel wins.
            if getattr(rec, field_name) is None:
                setattr(rec, field_name, arrival_ts)
            # Backfill metadata from whichever channel first carries it.
            if rec.t_published is None and published_ts is not None:
                rec.t_published = published_ts
            if not rec.headline and headline:
                rec.headline = headline
                rec.catalyst_score = quick_catalyst_score(headline)
            if not rec.tickers and tickers:
                rec.tickers = list(tickers)

    def pop_ready(self, now: float, linger_s: float) -> list[ShadowRecord]:
        """Remove and return records first seen at or before ``now-linger_s``."""
        cutoff = now - linger_s
        with self._lock:
            ready = [r for r in self._recs.values() if r.first_seen_ts <= cutoff]
            for r in ready:
                del self._recs[r.item_id]
                self._emitted.add(r.item_id)
        # Stable order by first sighting for deterministic output.
        ready.sort(key=lambda r: r.first_seen_ts)
        return ready

    def pending_count(self) -> int:
        with self._lock:
            return len(self._recs)


def compute_deltas(rec: ShadowRecord) -> dict[str, float | None]:
    """Return the pairwise latency deltas (seconds), None-safe.

    ``ws_rest_delta_s`` > 0 means WS arrived *earlier* than REST — the
    latency advantage this harness exists to measure.
    """

    def _sub(a: float | None, b: float | None) -> float | None:
        if a is None or b is None:
            return None
        return a - b

    return {
        "ws_rest_delta_s": _sub(rec.t_rest, rec.t_ws),
        "pub_ws_delta_s": _sub(rec.t_ws, rec.t_published),
        "pub_rest_delta_s": _sub(rec.t_rest, rec.t_published),
        # TradingView deltas (positive => the other channel arrived earlier than TV).
        "ws_tv_delta_s": _sub(rec.t_tv, rec.t_ws),
        "rest_tv_delta_s": _sub(rec.t_tv, rec.t_rest),
        "pub_tv_delta_s": _sub(rec.t_tv, rec.t_published),
    }


def _iso(ts: float | None) -> str | None:
    if ts is None:
        return None
    return datetime.fromtimestamp(ts, tz=UTC).isoformat()


def record_to_dict(rec: ShadowRecord) -> dict[str, Any]:
    """Flatten a record to a JSONL-ready dict (epoch + ISO + deltas + t_x)."""
    d: dict[str, Any] = {
        "item_id": rec.item_id,
        "headline": rec.headline,
        "tickers": rec.tickers,
        "source_name": rec.source_name,
        "catalyst_score": rec.catalyst_score,
        "t_published": rec.t_published,
        "t_ws": rec.t_ws,
        "t_rest": rec.t_rest,
        "t_tv": rec.t_tv,  # TradingView arrival (matched cross-source)
        "t_x": rec.t_x,  # reserved — null until the X event matcher lands
        "t_published_iso": _iso(rec.t_published),
        "t_ws_iso": _iso(rec.t_ws),
        "t_rest_iso": _iso(rec.t_rest),
        "t_tv_iso": _iso(rec.t_tv),
        "t_x_iso": _iso(rec.t_x),
    }
    d.update(compute_deltas(rec))
    return d


def attach_cross_source(
    records: list[ShadowRecord],
    foreign: dict[str, list[SourceItem]],
    *,
    time_window_s: float,
    min_headline_sim: float,
) -> list[ShadowRecord]:
    """Populate ``t_tv`` / ``t_x`` on each record from foreign-source items.

    Foreign providers (TradingView, X) share no Benzinga ``item_id``, so we
    match on content: each Benzinga record is compared against every buffered
    foreign item via :func:`items_match` (shared ticker + published-time
    proximity + headline similarity). On a match, the record's ``t_tv`` /
    ``t_x`` is set to the foreign item's *arrival* time (its local receipt,
    comparable to ``t_ws`` / ``t_rest``), taking the earliest matching arrival.

    Pure and side-effect free apart from mutating the passed records.
    """
    for rec in records:
        if not rec.headline or not rec.tickers:
            continue
        anchor_ts = rec.t_published if rec.t_published is not None else (rec.t_ws or rec.t_rest)
        if anchor_ts is None:
            continue
        anchor = SourceItem(
            source="benzinga", item_id=rec.item_id, published_ts=anchor_ts,
            headline=rec.headline, tickers=list(rec.tickers),
        )
        for src, items in foreign.items():
            best: float | None = None
            for it in items:
                if not items_match(anchor, it, time_window_s=time_window_s,
                                   min_headline_sim=min_headline_sim):
                    continue
                ts = it.arrival_ts if it.arrival_ts is not None else it.published_ts
                if ts is not None and (best is None or ts < best):
                    best = ts
            if best is None:
                continue
            if src == "tv":
                rec.t_tv = best
            elif src == "x":
                rec.t_x = best
    return records


# ── I/O shim: live WS + REST capture threads (not unit-tested) ──────


def _resolve_key() -> str:
    """Direct-host key preference, matching the live BenzingaRestAdapter."""
    return os.getenv("BENZINGA_DIRECT_API_KEY") or os.getenv("BENZINGA_API_KEY") or ""


def _observe_news_items(
    ledger: ShadowJoinLedger, channel: str, items: list[Any], now: float
) -> int:
    """Feed a batch of ``NewsItem`` objects into the ledger. Returns count."""
    n = 0
    for it in items:
        item_id = getattr(it, "item_id", "") or ""
        if not item_id:
            continue
        ledger.observe(
            item_id,
            channel,
            now,
            published_ts=getattr(it, "published_ts", None),
            headline=getattr(it, "headline", "") or "",
            tickers=list(getattr(it, "tickers", []) or []),
        )
        n += 1
    return n


def run_recorder(
    *,
    out_path: Path,
    rest_interval: float,
    linger_seconds: float,
    flush_seconds: float,
    max_runtime: float | None,
    channels: str | None,
    tv_symbols: list[str] | None = None,
    tv_interval: float = 20.0,
    match_window_s: float = 180.0,
    match_sim: float = 0.6,
) -> int:
    """Run the standalone WS+REST shadow recorder until ``max_runtime``.

    Returns the number of records written. Best-effort and defensive: any
    adapter error is logged and retried; the recorder never raises into the
    caller once started.
    """
    key = _resolve_key()
    if not key:
        logger.error("no BENZINGA_DIRECT_API_KEY/BENZINGA_API_KEY set; nothing to record")
        return 0

    # Imported lazily so the pure core (and its tests) need no network stack.
    from newsstack_fmp.config import Config
    from newsstack_fmp.ingest_benzinga import (
        BenzingaRestAdapter,
        BenzingaWsAdapter,
    )

    cfg = Config()
    ledger = ShadowJoinLedger()
    stop = threading.Event()
    written: list[dict[str, Any]] = []
    lock = threading.Lock()

    ws = BenzingaWsAdapter(key, cfg.benzinga_ws_url, channels=channels)
    ws.start()
    rest = BenzingaRestAdapter(key, provider="direct")

    # Optional TradingView (Reuters/DJ) shadow poller — populates t_tv via the
    # cross-source matcher. First-seen arrival per TV id wins; buffer is pruned
    # past the linger+match horizon. Standalone read of the unofficial endpoint
    # for MEASUREMENT — NOT a re-enable of the retired runtime provider (#3777).
    tv_buf: dict[str, SourceItem] = {}
    tv_lock = threading.Lock()

    def _tv_loop() -> None:
        from scripts.bz_tv_lead_study import _tv_items
        while not stop.is_set():
            try:
                now = time.time()
                fetched = _tv_items(tv_symbols or [])
                with tv_lock:
                    for it in fetched:
                        if it.item_id and it.item_id not in tv_buf:
                            it.arrival_ts = now
                            tv_buf[it.item_id] = it
                    horizon = now - (linger_seconds + match_window_s + 60.0)
                    for k in [k for k, v in tv_buf.items()
                              if (v.arrival_ts or 0.0) < horizon]:
                        del tv_buf[k]
            except Exception:  # pragma: no cover - live loop resilience
                logger.debug("tv poll error", exc_info=True)
            stop.wait(tv_interval)

    def _foreign_snapshot() -> dict[str, list[SourceItem]]:
        if not tv_symbols:
            return {}
        with tv_lock:
            return {"tv": list(tv_buf.values())}

    def _ws_loop() -> None:
        while not stop.is_set():
            try:
                items = ws.drain()
                if items:
                    _observe_news_items(ledger, "ws", items, time.time())
            except Exception:  # pragma: no cover - live loop resilience
                logger.debug("ws drain error", exc_info=True)
            stop.wait(0.25)

    def _rest_loop() -> None:
        while not stop.is_set():
            try:
                items = rest.fetch_news(page_size=100)
                _observe_news_items(ledger, "rest", items, time.time())
            except Exception:  # pragma: no cover - live loop resilience
                logger.debug("rest poll error", exc_info=True)
            stop.wait(rest_interval)

    def _flush() -> None:
        ready = ledger.pop_ready(time.time(), linger_seconds)
        if not ready:
            return
        attach_cross_source(ready, _foreign_snapshot(),
                            time_window_s=match_window_s, min_headline_sim=match_sim)
        with lock:
            written.extend(record_to_dict(r) for r in ready)
            _write_jsonl(out_path, written)
        logger.info("flushed %d records (%d pending)", len(ready), ledger.pending_count())

    threads = [
        threading.Thread(target=_ws_loop, name="bz-ws", daemon=True),
        threading.Thread(target=_rest_loop, name="bz-rest", daemon=True),
    ]
    if tv_symbols:
        threads.append(threading.Thread(target=_tv_loop, name="tv-poll", daemon=True))
    for t in threads:
        t.start()

    started = time.time()
    try:
        while not stop.is_set():
            stop.wait(flush_seconds)
            _flush()
            if max_runtime is not None and (time.time() - started) >= max_runtime:
                break
    except KeyboardInterrupt:
        logger.info("interrupted; draining")
    finally:
        stop.set()
        with contextlib.suppress(Exception):
            ws.stop()
        # Final drain: emit everything still pending regardless of linger.
        remaining = ledger.pop_ready(time.time() + linger_seconds + 1.0, linger_seconds)
        attach_cross_source(remaining, _foreign_snapshot(),
                            time_window_s=match_window_s, min_headline_sim=match_sim)
        with lock:
            written.extend(record_to_dict(r) for r in remaining)
            _write_jsonl(out_path, written)
    logger.info("recorder done: %d records -> %s", len(written), out_path)
    return len(written)


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    """Atomic full-rewrite of the JSONL (small daily volume; crash-safe)."""
    from scripts.smc_atomic_write import atomic_write_text

    body = "\n".join(json.dumps(r, default=str) for r in rows)
    atomic_write_text(body + ("\n" if body else ""), path)


def _default_out_path() -> Path:
    day = datetime.now(tz=UTC).strftime("%Y%m%d")
    return Path("artifacts") / "bz_ws_shadow" / f"latency_{day}.jsonl"


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--out", type=Path, default=None, help="JSONL output path")
    p.add_argument("--rest-interval", type=float, default=30.0,
                   help="REST poll cadence in seconds (mirror the live path)")
    p.add_argument("--linger-seconds", type=float, default=900.0,
                   help="how long to wait for the slower channel before emitting")
    p.add_argument("--flush-seconds", type=float, default=60.0,
                   help="flush cadence")
    p.add_argument("--max-runtime", type=float, default=None,
                   help="stop after N seconds (e.g. a session); default: run forever")
    p.add_argument("--channels", type=str, default=None,
                   help="optional Benzinga channel filter (comma-separated)")
    p.add_argument("--tv-symbols", type=str, default=None,
                   help="comma-separated symbols to also poll TradingView headlines "
                        "for (populates t_tv via the cross-source matcher); off if unset")
    p.add_argument("--tv-interval", type=float, default=20.0,
                   help="TradingView poll cadence in seconds")
    p.add_argument("--match-window-s", type=float, default=180.0,
                   help="max published-time gap when matching a foreign item to a Benzinga event")
    p.add_argument("--match-sim", type=float, default=0.6,
                   help="min headline similarity for a cross-source match")
    args = p.parse_args(argv)

    out_path = args.out or _default_out_path()
    tv_symbols = ([s.strip().upper() for s in args.tv_symbols.split(",") if s.strip()]
                  if args.tv_symbols else None)
    return 0 if run_recorder(
        out_path=out_path,
        rest_interval=args.rest_interval,
        linger_seconds=args.linger_seconds,
        flush_seconds=args.flush_seconds,
        max_runtime=args.max_runtime,
        channels=args.channels,
        tv_symbols=tv_symbols,
        tv_interval=args.tv_interval,
        match_window_s=args.match_window_s,
        match_sim=args.match_sim,
    ) >= 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
