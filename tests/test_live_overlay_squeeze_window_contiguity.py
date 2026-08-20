"""Ein Fenster mit einem Loch darf kein selbstsicheres Urteil ergeben.

2026-08-20 (Deep-Review des Serve-Pfads). ``compute_squeeze_on`` faellt schon
heute auf ``None`` zurueck, wenn zu WENIGE Kerzen da sind — die Schranke zaehlt
aber KERZEN, nicht ZEIT. Nach einem Feed-Ausfall saettigen die Bars von VOR dem
Ausfall die Warmup-Schranke, also liefert der Daemon vom ersten neuen Bar an ein
definitives Urteil, das ueber die Preis-Diskontinuitaet hinweg gerechnet ist.

Gemessen auf dem ECHTEN Pfad (``_bars_for_timeframe`` -> ``compute_squeeze_on``,
tf=5m, 15 h alte Historie 18 Punkte tiefer):

    Minuten nach Wiederanlauf | allein | mit Vor-Ausfall-Historie
                           25 | None   | False
                           60 | None   | False
                          120 | None   | True     <- kippt
                          200 | None   | True
                          335 | True   | True

Also 335 Minuten lang ein Wert, der sich sicher gibt und dabei UMSPRINGT —
getrieben vom Mischungsverhaeltnis alt/neu statt vom Markt.

ABGRENZUNG, bewusst und gemessen:

* Die UEBERNACHT-Luecke zu ueberbruecken ist KORREKT. Pine tut das auf dem
  Chart genauso: eine 5m-EMA um 09:35 traegt den Vortag mit. Ein Wachter, der
  jede Luecke ablehnt, braeche die Paritaet, die ``#4013`` hergestellt hat.
* Ein Loch MITTEN in der Sitzung aendert das Urteil kaum: 40 fehlende Minuten
  in 8 Konstruktionen (Ausbruch-Amplituden 2/4/8/16 x zwei Ruhe-Niveaus)
  ergaben 0 Abweichungen — das BB-Fenster nutzt nur die letzten 20 Schluss-
  kurse, EMA und RMA gewichten Aelteres weg.
* Fuer Zeitrahmen ab 15m ist das 67-Kerzen-Warmup laenger als die laengste
  lueckenfreie Strecke eines Tages (960 min = 04:00-20:00 ET): 15m braucht
  16,8 h, 1H braucht 67 h. Dort ist das Ueberspannen mehrerer Sitzungen der
  KONSTRUIERTE Zustand — der Kommentar an ``_TF_RAW_BAR_REQUIREMENTS`` sagt
  das woertlich. Eine strikte Regel wuerde diese Zeitrahmen dauerhaft auf
  ``None`` setzen statt sie zu heilen.

Die Regel bleibt deshalb SITZUNGSFREI (kein Kalender, kein DST, keine
Feiertage) und begrenzt sich selbst: sie greift nur, wo ein lueckenfreies
Fenster ueberhaupt in einen Tag passt.
"""

from __future__ import annotations

import time
from typing import Any

from services.live_overlay_daemon import compute

_PERIOD = 20
_MINUTE = 60


def _minutes(start: float, count: int, price: float) -> list[dict[str, Any]]:
    """``count`` Ein-Minuten-Bars ab ``start`` auf konstantem Niveau."""
    return [
        {
            "ts_event": int((start + index * _MINUTE) * 1_000_000_000),
            "open": price,
            "high": price + 0.5,
            "low": price - 0.5,
            "close": price,
            "volume": 1000,
        }
        for index in range(count)
    ]


def _verdict(bars: list[dict[str, Any]], tf: str) -> bool | None:
    return compute.compute_squeeze_on(compute._bars_for_timeframe(bars, tf), period=_PERIOD)


def test_a_window_that_straddles_an_outage_has_no_verdict() -> None:
    """Der Kern: alte Bars duerfen die Warmup-Schranke nicht saettigen."""
    now = time.time()
    after_outage = _minutes(now - 120 * _MINUTE, 120, 118.0)
    before_outage = _minutes(now - 30 * 3600, 900, 100.0)

    assert _verdict(after_outage, "5m") is None, "Vorbedingung: allein reicht die Historie nicht"
    assert _verdict(before_outage + after_outage, "5m") is None, (
        "das Urteil wurde ueber den Ausfall hinweg gerechnet — die Warmup-Schranke "
        "zaehlt Kerzen statt Zeit, also saettigen Vor-Ausfall-Bars sie"
    )


def test_a_contiguous_window_still_gets_a_verdict() -> None:
    """Positivkontrolle. Ohne sie waere die Regel auch dann gruen, wenn sie
    schlicht alles auf ``None`` setzt."""
    now = time.time()
    bars = _minutes(now - 400 * _MINUTE, 400, 100.0)
    assert _verdict(bars, "5m") is not None, (
        "eine lueckenlose Historie muss weiterhin ein Urteil ergeben"
    )


def test_one_missing_candle_does_not_blind_the_indicator() -> None:
    """Ein einzelner Aussetzer ist Datenrauschen, kein Ausfall.

    Duenne Symbole liefern nicht in jeder Minute einen Bar. Eine Regel, die
    darauf schon ausloest, macht den Indikator fuer genau diese Symbole
    dauerhaft blind — die teurere Fehlerrichtung.
    """
    now = time.time()
    bars = _minutes(now - 400 * _MINUTE, 400, 100.0)
    holed = bars[:200] + bars[205:]  # eine 5m-Kerze fehlt
    assert _verdict(holed, "5m") is not None


def test_timeframes_whose_warmup_never_fits_one_day_are_left_alone() -> None:
    """15m und groesser ueberspannen IMMER eine Nacht — by construction.

    Dort ist die Mehrsitzungs-Spanne der konstruierte Zustand, nicht der
    Defekt. Die Regel muss sich selbst begrenzen, sonst setzt sie diese
    Zeitrahmen dauerhaft auf ``None``.
    """
    now = time.time()
    day_two = _minutes(now - 400 * _MINUTE, 400, 100.0)
    day_one = _minutes(now - 30 * 3600, 900, 100.5)
    assert _verdict(day_one + day_two, "15m") is not None, (
        "die Kontiguitaets-Regel hat einen Zeitrahmen erwischt, dessen Warmup "
        "prinzipbedingt ueber Nacht reicht"
    )
