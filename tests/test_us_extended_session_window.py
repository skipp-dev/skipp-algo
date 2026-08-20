"""Die Datenfluss-Alarme wachen ueber das Produktfenster, nicht ueber RTH.

2026-08-20 (Deep-Review des Serve-Pfads, Fund (a), Teil 1 von 2). Gemessen:
``feed._run_supervisor_loop`` berechnet ``stalled`` ausschliesslich INNERHALB
von ``if market_hours.is_us_regular_session_open():``, und die beiden
Alarmregeln, die Datenfluss messen, waren mit ``live_overlay_market_us_open``
MULTIPLIZIERT. Eine Leitung, die Freitag 16:10 ET verstummt, wurde also weder
gemeldet noch geheilt — bis Montag 09:30.

Dass dort Bars fliessen MUESSTEN, sagen zwei unabhaengige Quellen: die
Subscription ist ``EQUS.MINI ohlcv-1m ALL_SYMBOLS`` (kein Sitzungsfilter), und
``OPS.md`` haelt einen Neustart am 2026-07-22 um 09:13Z fest — 05:13 ET —,
nach dem "premarket repopulated".

Warum NUR die Alarme in diesem Schritt: das Sitzungs-Gate im Supervisor ist
keine Schlamperei, sondern eine SICHERUNG. Nachts sieht "keine Bars, weil zu"
exakt aus wie "keine Bars, weil kaputt"; ohne Gate wuerde der Supervisor
dreimal heilen und dann ``os._exit`` rufen, und Railway gibt nach
``restartPolicyMaxRetries = 3`` auf — aus Feierabend wuerde ein dauerhaft
toter Dienst. Ein ALARM kann das nicht: er klingelt, mehr nicht. Deshalb
zuerst die risikofreie Haelfte.
"""

from __future__ import annotations

import datetime
import json
from pathlib import Path

import pytest
import yaml

from services.live_overlay_daemon import market_hours

_ET = "America/New_York"
_RULES = (
    Path(__file__).resolve().parents[1]
    / "services/live_overlay_daemon/infra/grafana/alert-rules.yaml"
)
# Genau die Regeln, die DATENFLUSS messen. Kundenverkehr und News haben eigene
# Rhythmen und bleiben bewusst auf der regulaeren Sitzung.
_DATA_FLOW_RULES = ("lo-feed-down-market-open", "lo-last-bar-stale-open")


def _at(year: int, month: int, day: int, hour: int, minute: int) -> datetime.datetime:
    from zoneinfo import ZoneInfo

    local = datetime.datetime(year, month, day, hour, minute, tzinfo=ZoneInfo(_ET))
    return local.astimezone(datetime.UTC)


@pytest.fixture(autouse=True)
def _no_holidays(monkeypatch: pytest.MonkeyPatch) -> None:
    """Feiertage aus dem Weg — hier wird das FENSTER geprueft, nicht der Kalender."""
    monkeypatch.setattr(
        market_hours, "_holiday_dates_for_year", lambda *a, **k: frozenset()
    )
    monkeypatch.setattr(market_hours, "_is_us_early_close", lambda _d: False)


@pytest.mark.parametrize(
    ("hour", "minute", "expected"),
    [
        (3, 59, False),  # vor dem Pre-Market
        (4, 0, True),  # Pre-Market beginnt
        (5, 13, True),  # der Zeitpunkt aus dem OPS-Protokoll
        (9, 30, True),  # RTH
        (16, 10, True),  # genau die Minute, in der der Fund entstand
        (19, 59, True),  # Post-Market
        (20, 0, False),  # Feierabend
    ],
)
def test_the_product_window_spans_04_to_20_et(hour: int, minute: int, expected: bool) -> None:
    assert market_hours.is_us_extended_session_open(_at(2026, 8, 20, hour, minute)) is expected


def test_the_window_is_wider_than_the_regular_session_where_it_matters() -> None:
    """Positivkontrolle gegen die alte Grenze: 16:10 ist der Kern des Fundes."""
    moment = _at(2026, 8, 20, 16, 10)
    assert market_hours.is_us_regular_session_open(moment) is False
    assert market_hours.is_us_extended_session_open(moment) is True


def test_the_weekend_stays_closed() -> None:
    """Ein Fenster, das samstags offen waere, wuerde jedes Wochenende alarmieren."""
    assert market_hours.is_us_extended_session_open(_at(2026, 8, 22, 12, 0)) is False


def test_every_data_flow_rule_gates_on_the_product_window() -> None:
    """Der eigentliche Wachter: die Regeln muessen das neue Tor benutzen.

    Abgeleitet aus der Regeldatei, nicht aus dem Gedaechtnis — und in BEIDE
    Richtungen: keine Datenfluss-Regel darf auf der regulaeren Sitzung
    zurueckbleiben, und keine der uebrigen Regeln darf versehentlich
    mitgewandert sein.
    """
    document = yaml.safe_load(_RULES.read_text(encoding="utf-8"))
    found: dict[str, str] = {}

    def walk(node: object) -> None:
        if isinstance(node, dict):
            uid = node.get("uid")
            if isinstance(uid, str):
                found[uid] = json.dumps(node)
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(document)
    for uid in _DATA_FLOW_RULES:
        assert uid in found, f"Regel {uid} existiert nicht mehr — dieser Test bewacht ein Phantom"
        assert "live_overlay_market_us_extended_open" in found[uid], (
            f"{uid} misst Datenfluss, gated aber noch auf die regulaere Sitzung"
        )

    strays = [
        uid
        for uid, blob in found.items()
        if uid not in _DATA_FLOW_RULES and "live_overlay_market_us_extended_open" in blob
    ]
    assert not strays, (
        f"diese Regeln sind unbeabsichtigt auf das Produktfenster gewandert: {strays} — "
        "Kundenverkehr und News haben eigene Rhythmen"
    )
