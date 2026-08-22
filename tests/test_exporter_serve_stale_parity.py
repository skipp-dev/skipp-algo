"""Exporter und Serve-Pfad muessen sich einig sein, was "stale" heisst.

`compute._signals_snapshot_is_fresh` sagt in ihrem Docstring ausdruecklich, sie
spiegele den Exporter-Vertrag, "so the overlay payload and the alerting layer
agree on what stale means" — und `metrics._trading_signals_snapshot` sagt an
ihrer Uhr-Vorlauf-Stelle dasselbe in die Gegenrichtung ("so the alerting
contract matches compute._signals_snapshot_is_fresh"). Die Parität ist also
erklaerte Absicht, kein Zufall.

An EINER Stelle war sie nicht eingeloest. Die Serve-Seite verwirft seit #4056
als ERSTES einen Snapshot, dessen `signals` kein List ist:

    if not isinstance(snap.get("signals"), list):
        return False

Der Exporter hatte dafuer kein Gegenstueck (`raw.get("signals") or []`) und
leitete `stale` allein aus `updated_epoch` ab. Gemessen am 2026-08-20 mit
`{"updated_epoch": now-12, "signal_count": 3}` ohne `signals`:

* Serve   -> `is_fresh=False` ⇒ ALLE Trade-Felder `None`, fuer JEDES Symbol.
* Exporter-> `loaded=1.0 age_known=1.0 stale=0.0` ⇒ keine der drei
  Grafana-Regeln feuert.

Stiller Totalverlust des Handelskontexts bei gruener Alarmflaeche — genau die
Fehlerklasse, gegen die der Freshness-Monitor ueberhaupt gebaut wurde.
"""

from __future__ import annotations

import time
from typing import Any

from services.live_overlay_daemon import compute, metrics


def _snapshot_without_signals() -> dict[str, Any]:
    """Frisch nach der Uhr, aber ohne die Liste, aus der Serve schoepft."""
    return {
        "updated_epoch": time.time() - 12.0,
        "signal_count": 3,
        "a0_count": 1,
        "watched_symbols": ["AAPL", "MSFT"],
    }


def _snapshot_with_signals() -> dict[str, Any]:
    snap = _snapshot_without_signals()
    snap["signals"] = [
        {
            "symbol": "AAPL",
            "level": "A0",
            "score": 0.9,
            "fired_epoch": time.time() - 30.0,
        }
    ]
    return snap


def test_exporter_calls_it_stale_when_serve_refuses_the_snapshot(monkeypatch) -> None:
    """Das Invariant: verwirft Serve, darf der Exporter nicht "frisch" melden."""
    snap = _snapshot_without_signals()
    monkeypatch.setattr(compute, "_load_signals_snapshot", lambda: snap)

    served_fresh = compute._signals_snapshot_is_fresh(snap)
    exported = metrics._trading_signals_snapshot()

    # Vorbedingung: Serve verwirft diesen Snapshot wirklich.
    assert served_fresh is False, (
        "Serve akzeptiert den Snapshot — dann prueft dieser Test nicht mehr, "
        "was er zu pruefen vorgibt."
    )
    assert exported["loaded"] == 1.0

    assert exported["stale"] == 1.0, (
        "Der Exporter meldet den Snapshot als frisch, waehrend der Serve-Pfad "
        "ihn komplett verwirft und fuer JEDES Symbol None liefert. Genau diese "
        "Divergenz laesst den Handelskontext still ausfallen, ohne dass eine "
        "Alarmregel feuert."
    )


def test_a_usable_snapshot_stays_fresh_on_both_sides(monkeypatch) -> None:
    """Positivkontrolle — sonst waere der Test oben auch mit `stale = 1.0` gruen.

    Ohne diese Haelfte koennte man den Exporter pauschal auf "stale" stellen
    und beide Zeilen waeren erfuellt; der Alarm feuerte dann dauerhaft und
    saegte sich seine eigene Glaubwuerdigkeit ab.
    """
    snap = _snapshot_with_signals()
    monkeypatch.setattr(compute, "_load_signals_snapshot", lambda: snap)

    assert compute._signals_snapshot_is_fresh(snap) is True
    exported = metrics._trading_signals_snapshot()

    assert exported["loaded"] == 1.0
    assert exported["stale"] == 0.0
    assert exported["age_known"] == 1.0


def test_an_empty_signal_list_is_fresh_not_stale(monkeypatch) -> None:
    """Leer ist nicht unbrauchbar: keine aktiven Signale ist ein Zustand.

    Die Grenze verlaeuft zwischen "Feld fehlt / falscher Typ" (Serve verwirft)
    und "Feld ist eine leere Liste" (Serve akzeptiert, es gibt nur nichts zu
    zeigen). Ohne diesen Test koennte der Fix beides in einen Topf werfen und
    an jedem ruhigen Handelstag Alarm schlagen.
    """
    snap = _snapshot_without_signals()
    snap["signals"] = []
    monkeypatch.setattr(compute, "_load_signals_snapshot", lambda: snap)

    assert compute._signals_snapshot_is_fresh(snap) is True
    assert metrics._trading_signals_snapshot()["stale"] == 0.0
