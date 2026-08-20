"""Regression tests: the /smc_live ``stale`` flag must track DATA freshness.

A dead or silently-stalled feed leaves the bar cache frozen while the
overlay-refresh thread keeps recomputing payloads from those frozen bars every
``OVERLAY_REFRESH_SECS`` (1800s default). Each recompute refreshes
``cache.overlay_age_secs()``, so a stale flag derived from overlay age alone
can never trip (1800 < OVERLAY_MAX_STALE_SECS=3600) — Pine keeps painting
hours-old values as live instead of degrading to its baked ``mp.*`` baseline
(the WP-D fallback contract, tests/test_smc_live_overlay_fallback.py).

The non-default-timeframe path already derives ``stale`` from bar recency
(main._get_payload_for_timeframe); these tests pin the same data-freshness
semantics for the default 5m path served from the background overlay cache.

Endpoint functions are invoked directly (repo convention — no TestClient).
"""
from __future__ import annotations

import json
import time
from typing import Any

import pytest

import services.live_overlay_daemon.main as main_mod

_TOKEN = "test-token"


def _bars(newest_age_secs: float, n: int = 30) -> list[dict[str, Any]]:
    """n one-minute bars whose newest ts_event is newest_age_secs old."""
    newest = time.time() - newest_age_secs
    return [
        {
            "open": 100.0 + i,
            "high": 101.0 + i,
            "low": 99.0 + i,
            "close": 100.5 + i,
            "volume": 1000,
            "ts_event": int((newest - (n - 1 - i) * 60) * 1_000_000_000),
        }
        for i in range(n)
    ]


def _cached_5m_payload() -> dict[str, Any]:
    """A background-snapshot payload as the refresh thread would cache it."""
    return {
        "schema": "smc-live-overlay/1",
        "symbol": "NVDA",
        "asof_ts": int(time.time()),
        "stale": False,
        "news_strength": None,
        "news_bias": None,
        "flow_rel_vol": 1.2,
        "flow_delta_proxy_pct": 0.4,
        "squeeze_on": 0,
        "ats_state": "neutral",
        "ats_zscore": 0.1,
        "vix_level": 17.5,
        "tone": "NEUTRAL",
        "global_heat": 0.0,
        "event_window_state": "normal",
        "event_risk_level": "low",
        "next_event_name": None,
        "next_event_time": None,
        "market_event_blocked": False,
        "symbol_event_blocked": False,
        "event_provider_status": "unavailable",
        "signal_level": None,
        "signal_direction": None,
        "trade_entry": None,
        "trade_stop": None,
        "trade_target": None,
        "trade_r": None,
    }


@pytest.fixture
def serving(monkeypatch: pytest.MonkeyPatch):
    """Daemon serving a freshly-recomputed 5m overlay snapshot for NVDA."""
    monkeypatch.setattr(main_mod.config, "overlay_secret_token", lambda: _TOKEN)
    monkeypatch.setattr(main_mod.config, "max_stale_secs", lambda: 3600)
    # The background refresh thread just ran — overlay cache age is tiny.
    monkeypatch.setattr(main_mod.cache, "overlay_age_secs", lambda: 10.0)
    monkeypatch.setattr(
        main_mod.cache, "get_overlay", lambda _sym: _cached_5m_payload()
    )
    return monkeypatch


def _get(tf: str = "5m") -> dict[str, Any]:
    return json.loads(main_mod.smc_live(token=_TOKEN, symbol="NVDA", tf=tf).body)


def test_5m_stale_true_when_bars_frozen_despite_fresh_compute(serving) -> None:
    """Feed dead 2h, compute thread alive: the payload must self-declare stale."""
    serving.setattr(main_mod.cache, "get_bars_snapshot", lambda _sym: _bars(7200.0))
    assert _get("5m")["stale"] is True


def test_5m_stale_true_when_bars_evicted(serving) -> None:
    """Overlay entry survives but the bar deque is gone: no recency evidence."""
    serving.setattr(main_mod.cache, "get_bars_snapshot", lambda _sym: [])
    assert _get("5m")["stale"] is True


def test_5m_stale_false_when_bars_fresh(serving) -> None:
    """Healthy flow: fresh bars + fresh compute stay non-stale."""
    serving.setattr(main_mod.cache, "get_bars_snapshot", lambda _sym: _bars(30.0))
    assert _get("5m")["stale"] is False


def test_5m_stale_true_when_newest_bar_is_in_the_future(serving) -> None:
    """A future-dated upstream bar is invalid recency evidence, never fresh."""
    serving.setattr(main_mod.cache, "get_bars_snapshot", lambda _sym: _bars(-600.0))
    assert _get("5m")["stale"] is True


def test_5m_stale_true_when_compute_stale_even_with_fresh_bars(serving) -> None:
    """Existing overlay-age semantics are preserved: a wedged refresh thread
    still marks the payload stale even while bars keep flowing."""
    serving.setattr(main_mod.cache, "get_bars_snapshot", lambda _sym: _bars(30.0))
    serving.setattr(main_mod.cache, "overlay_age_secs", lambda: 7200.0)
    assert _get("5m")["stale"] is True


def test_bar_age_is_judged_on_the_bar_clock_not_the_compute_clock(serving) -> None:
    """Ein Bar, den der Daemon selbst als Stall zaehlt, darf nicht frisch heissen.

    2026-08-20 (Deep-Review des Serve-Pfads): ``OVERLAY_MAX_STALE_SECS`` ist am
    deployten Dienst NICHT gesetzt (63 Railway-Variablen geprueft), also greift
    der Default 3600 s. Dieser EINE Wert wird gegen ZWEI Groessen verglichen,
    die um Faktor 60 auseinanderliegen: das Overlay-Alter (Refresh-Kadenz 1800 s
    — dort ist 3600 korrekt bemessen) und das BAR-Alter (Bars kommen im 60-s-
    Takt). Der Docstring von ``_latest_bar_age_secs`` rechnet woertlich "under a
    60s budget"; gegen 3600 s ist die dortige +60-s-Korrektur wirkungslos.

    Der Daemon hat seine eigene Definition von "Feed steht" bereits:
    ``feed._STALL_MAX_BAR_AGE_SECS = 180`` — drei Minuten ohne Bar sind ein
    Stall, den der Supervisor heilt. Was der Supervisor als Stall behandelt,
    darf die Nutzlast nicht als frisch ausliefern.

    Die vorhandenen Tests dieser Datei pinnen 7200 s (stale) und 30 s (frisch)
    und lassen genau das Fenster dazwischen offen — 180 s bis 3600 s, also die
    erste Stunde jedes Einfrierens.
    """
    serving.setattr(main_mod.cache, "get_bars_snapshot", lambda _sym: _bars(900.0))
    assert _get("5m")["stale"] is True, (
        "ein 15 Minuten alter Bar wurde als frisch serviert — das Bar-Alter wird "
        "gegen das Compute-Budget geprueft statt gegen ein bar-skaliertes"
    )


def test_the_on_demand_timeframe_path_uses_the_same_bar_budget(serving) -> None:
    """Beide Pfade, nicht nur der 5m-Pfad.

    ``_get_payload_for_timeframe`` leitet ``stale`` bereits aus der Bar-
    Aktualitaet ab — aber gegen dasselbe Compute-Budget. Ein Fix, der nur den
    5m-Pfad anfasst, liesse die uebrigen Zeitrahmen mit der alten Toleranz
    zurueck.
    """
    serving.setattr(main_mod.cache, "get_bars_snapshot", lambda _sym: _bars(900.0))
    serving.setattr(main_mod.cache, "get_overlay", lambda _sym: None)
    assert _get("15m")["stale"] is True, (
        "der On-demand-Zeitrahmenpfad serviert einen 15 Minuten alten Bar als frisch"
    )


def test_a_normally_flowing_feed_is_still_fresh(serving) -> None:
    """Positivkontrolle: das neue Budget darf den Normalbetrieb nicht roeten.

    Bars kommen im 60-s-Takt, ``_latest_bar_age_secs`` misst seit dem SCHLUSS
    des neuesten Bars — im Normalbetrieb pendelt das zwischen 0 und 60 s.
    Ohne diese Kontrolle koennte der Test oben auch dadurch gruen werden, dass
    schlicht alles stale heisst.
    """
    serving.setattr(main_mod.cache, "get_bars_snapshot", lambda _sym: _bars(45.0))
    assert _get("5m")["stale"] is False
