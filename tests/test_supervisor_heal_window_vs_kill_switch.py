"""Die Erkennung darf breiter sein als der Totmannschalter — und muss es bleiben.

2026-08-20 (Deep-Review des Serve-Pfads, Fund (a), Teil 2 von 2).

Teil 1 (#4920) hat die ALARME auf das Produktfenster 04:00-20:00 ET gestellt.
Dieser Teil zieht die ERKENNUNG im Supervisor nach — aber ausdruecklich NICHT
die Eskalation.

Warum die Trennung existiert, in einer Kette:

    ``_escalate_to_platform_restart`` ruft ``os._exit``
    -> ``railway.toml`` traegt ``restartPolicyMaxRetries = 3``
    -> nach etwa vier Prozessleben bleibt der Dienst UNTEN.

Ausserhalb der regulaeren Sitzung ist "keine Bars" mehrdeutig: ein wirklich
geschlossener Markt sieht aus wie eine haengende Leitung. Ein falsches
"Markt offen" — etwa durch einen leeren Feiertagskalender, siehe
``tests/test_holiday_calendar_fallback_is_audible.py`` — wuerde den Dienst
also nicht heilen, sondern abschalten. Reconnects sind billig und
zurueckdrehbar; ein ``os._exit`` gegen ein Drei-Neustart-Budget ist es nicht.

Ein toter Worker-THREAD ist etwas anderes: das ist ein echter Zombie, den ein
Neustart repariert, unabhaengig von der Uhrzeit. Der eskaliert weiter.

Dieser Test ist zugleich der Kopplungs-Waechter, den die Gedaechtnisnotiz zu
(a) verlangt: er pinnt, dass Erkennungs-Gate und Eskalations-Gate VERSCHIEDENE
Praedikate sind. Verdrahtet jemand spaeter beides auf dasselbe Fenster, wird er
rot — und genau das ist der Fehler, der sich einen naechtlichen Selbstabschuss
baut.
"""

from __future__ import annotations

import ast
import types
from pathlib import Path

import pytest

from services.live_overlay_daemon import feed as feed_mod

_FEED = Path(__file__).resolve().parents[1] / "services/live_overlay_daemon/feed.py"


def _supervisor_source() -> str:
    tree = ast.parse(_FEED.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_run_supervisor_loop":
            return ast.get_source_segment(_FEED.read_text(encoding="utf-8"), node) or ""
    raise AssertionError("_run_supervisor_loop nicht gefunden — dieser Test bewacht ein Phantom")


def test_detection_runs_on_the_product_window() -> None:
    """Die Stall-Erkennung muss das breitere Fenster benutzen."""
    source = _supervisor_source()
    assert "is_us_extended_session_open()" in source, (
        "die Stall-Erkennung haengt nicht am Produktfenster — eine Leitung, die "
        "16:10 ET verstummt, bleibt bis zum naechsten Handelstag ungeheilt"
    )


def test_the_kill_switch_still_asks_for_the_regular_session() -> None:
    """Der Totmannschalter muss das ENGERE Fenster behalten."""
    source = _supervisor_source()
    assert "is_us_regular_session_open()" in source, (
        "die Eskalation fragt die regulaere Sitzung nicht mehr — ein falsches "
        "'Markt offen' ausserhalb RTH schaltet den Dienst jetzt dauerhaft ab "
        "(os._exit gegen restartPolicyMaxRetries = 3)"
    )


def test_the_two_gates_are_not_the_same_predicate() -> None:
    """Der eigentliche Kopplungs-Waechter.

    Beide Aufrufe einzeln zu pruefen genuegt nicht: jemand koennte die
    Eskalation auf das breite Fenster ziehen und den engen Aufruf anderswo
    stehen lassen. Dieser Test verlangt, dass der Eskalationszweig SELBST die
    regulaere Sitzung nennt.
    """
    source = _supervisor_source()
    marker = "if heal_attempts > _SELF_HEAL_MAX_ATTEMPTS:"
    assert marker in source, "der Eskalationszweig wurde umgebaut — Kopplung neu bewerten"
    escalation_branch = source.split(marker, 1)[1]
    head = escalation_branch[: escalation_branch.find("_escalate_to_platform_restart()")]
    assert "is_us_regular_session_open()" in head, (
        "zwischen der erschoepften Heilung und dem os._exit steht kein "
        "Sitzungs-Gate mehr — der Totmannschalter ist auf das Produktfenster "
        "gewandert"
    )
    assert "is_us_extended_session_open()" not in head, (
        "der Eskalationszweig fragt das PRODUKTFENSTER — genau der Fehler, den "
        "dieser Waechter verhindern soll"
    )


def test_a_dead_worker_still_escalates_at_any_hour() -> None:
    """Ein toter Thread ist ein Zombie, kein Marktzustand."""
    source = _supervisor_source()
    marker = "if heal_attempts > _SELF_HEAL_MAX_ATTEMPTS:"
    head = source.split(marker, 1)[1]
    head = head[: head.find("_escalate_to_platform_restart()")]
    assert "workers_dead" in head or "all(workers.values())" in head, (
        "die Eskalation unterscheidet nicht mehr zwischen einem toten Worker "
        "(jederzeit ein Neustart wert) und einem Stall ausserhalb RTH (nicht)"
    )


# --- Verhaltensbeweis -------------------------------------------------------
# Die vier Pruefungen oben lesen QUELLTEXT. Das faengt eine Umverdrahtung, aber
# es beweist nicht, was der Supervisor TUT. Der Treiber unten faehrt die echte
# Schleife gegen eine Fake-Uhr — geliehen aus
# tests/test_live_overlay_supervisor_heal_grace.py, das dieselbe Technik seit
# 2026-08-05 benutzt.

def _drive(
    monkeypatch: pytest.MonkeyPatch,
    *,
    regular_open: bool,
    extended_open: bool,
    workers_alive: bool = True,
    max_cycles: int = 400,
) -> dict:
    """Eine nie genesende Leitung. Gibt den beobachteten Endzustand zurueck."""
    state = {"now": 0.0, "last_bar": 0.0, "heals": 0, "exited": False}

    class _Stop:
        def __init__(self) -> None:
            self.cycles = 0

        def wait(self, seconds: float) -> bool:
            self.cycles += 1
            state["now"] += seconds
            return self.cycles >= max_cycles or state["exited"]

        def is_set(self) -> bool:
            return False

    def _break() -> bool:
        state["heals"] += 1
        return True  # ein Client WURDE gebrochen, sonst refundet der Zaehler

    monkeypatch.setattr(feed_mod, "time", types.SimpleNamespace(monotonic=lambda: state["now"]))
    # Der Bar altert immer weiter: die Leitung erholt sich nie.
    monkeypatch.setattr(feed_mod, "last_bar_age_secs", lambda: state["now"] - state["last_bar"])
    monkeypatch.setattr(feed_mod, "_supervisor_break_stalled_client", _break)
    monkeypatch.setattr(
        feed_mod, "_escalate_to_platform_restart", lambda: state.__setitem__("exited", True)
    )
    monkeypatch.setattr(
        feed_mod,
        "worker_liveness",
        lambda: {
            "live_feed": workers_alive,
            "ingest_processor": True,
            "overlay_refresh": True,
            "flow_refresh": True,
        },
    )
    monkeypatch.setattr(feed_mod, "_do_start", lambda *a, **k: None, raising=False)
    monkeypatch.setattr(
        feed_mod.market_hours, "is_us_regular_session_open", lambda *a, **k: regular_open
    )
    monkeypatch.setattr(
        feed_mod.market_hours, "is_us_extended_session_open", lambda *a, **k: extended_open
    )
    monkeypatch.setattr(feed_mod, "_inc_metric", lambda *a, **k: None)
    feed_mod._fatal_config_error.clear()
    feed_mod._run_supervisor_loop(_Stop())
    return state


def test_a_stall_after_the_close_heals_but_never_kills(monkeypatch: pytest.MonkeyPatch) -> None:
    """16:10 ET: Erkennung greift, der Totmannschalter nicht."""
    state = _drive(monkeypatch, regular_open=False, extended_open=True)
    assert state["heals"] > 0, (
        "nach dem Schluss wurde gar nicht geheilt — die Erkennung haengt noch an RTH"
    )
    assert state["exited"] is False, (
        "der Supervisor hat sich ausserhalb der regulaeren Sitzung selbst abgeschossen — "
        "gegen restartPolicyMaxRetries = 3 heisst das ein dauerhaft toter Dienst"
    )


def test_the_same_stall_during_rth_still_escalates(monkeypatch: pytest.MonkeyPatch) -> None:
    """Positivkontrolle. Ohne sie waere der Test oben auch dann gruen, wenn die
    Eskalation ueberhaupt nicht mehr funktioniert."""
    state = _drive(monkeypatch, regular_open=True, extended_open=True)
    assert state["exited"] is True, "die Eskalation feuert waehrend RTH nicht mehr"


def test_a_dead_worker_escalates_even_after_the_close(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ein toter Thread ist ein Zombie, den ein Neustart repariert — zu jeder Stunde."""
    state = _drive(monkeypatch, regular_open=False, extended_open=False, workers_alive=False)
    assert state["exited"] is True, (
        "ein toter Worker-Thread eskaliert nach dem Schluss nicht mehr — die "
        "Unterscheidung Zombie vs. Marktzustand ist verloren"
    )
