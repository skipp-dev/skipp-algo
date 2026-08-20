"""Der inerte Snapshot-Test von #2353 bekommt eine Frist statt einer Hoffnung.

``tests/test_smc_strategy_snapshot.py`` prueft den Python-Spiegel einer
SMC-Strategie und traegt seit dem 2026-05-25 einen ``pytestmark``-skipif mit
dem Grund *"python/strategies/smc_mirror not implemented yet (#2353)"*. Der
Gedanke war gut gemeint und ausdruecklich dokumentiert: das Tor loest sich von
selbst, sobald der Spiegel importierbar wird — kein Quelltext-Edit noetig.

Nur ist genau das eine Zukunfts-Prosa ohne Mechanismus. Der Spiegel ist seit
knapp drei Monaten nicht gelandet, niemand liest den skipif-Grund zu einem
bestimmten Zeitpunkt, und die Datei sieht in jedem Lauf gruen aus. Der Sweep
vom 2026-08-19 hat sie deshalb ins Skip-Ledger eingetragen (``DECISION
OWED``) — ein Eintrag macht die Stille sichtbar, faellt aber keine
Entscheidung.

Dieser Tripwire ist die Entscheidung: **bis zum ``_DUE_BY`` unten darf der
Spiegel fehlen, danach nicht mehr schweigend.** Drei Zustaende, alle
gemessen, keiner still:

* Spiegel fehlt, heute <= Frist  -> gruen. Der Tripwire schlaeft.
* Spiegel fehlt, heute >  Frist  -> rot. Landen, loeschen, oder die Frist
  ABSICHTLICH mit datierter Begruendung verschieben (dasselbe Muster wie
  ``dueByHistory`` im Hold-Manager-Record).
* Spiegel da                     -> rot. Der skipif und beide Ledger-Zeilen
  sind erledigt und gehoeren entfernt — ein Eintrag bei Null verlangt
  Loeschen, nicht Schweigen.

Die Frist selbst ist injizierbar, damit beide Seiten des Datumsvergleichs
GELIEFERT werden koennen: die Tests unten fahren den Urteilspfad unter einer
verschobenen Uhr, statt zu behaupten, er wuerde spaeter schon feuern.
"""

from __future__ import annotations

import importlib.util
from datetime import date

_ISSUE = "#2353"
_MIRROR_MODULE = "python.strategies.smc_mirror"
_GATED_FILE = "tests/test_smc_strategy_snapshot.py"

# 2026-08-20 (Geburtsfehler-Sweep): Frist gesetzt, weil der skipif seit
# 2026-05-25 ohne Ablauf steht. Sechs Wochen sind die Spanne, in der ein
# Spiegel entweder gebaut wird oder erkennbar niemand ihn braucht.
_DUE_BY = date(2026, 9, 30)


def _mirror_present() -> bool:
    try:
        return importlib.util.find_spec(_MIRROR_MODULE) is not None
    except ModuleNotFoundError:
        return False


def _verdict(*, mirror_present: bool, today: date) -> str | None:
    """None = schlafend. Sonst der Text, der die Entscheidung einfordert."""
    if mirror_present:
        return (
            f"{_MIRROR_MODULE} existiert jetzt — {_GATED_FILE} laeuft wieder. "
            "Entferne den pytestmark-skipif dort UND beide Zeilen im "
            f"pin_registry-Skip-Ledger, und schliesse {_ISSUE}. Ein Ledger-"
            "Eintrag bei Null verlangt Loeschen, nicht Schweigen."
        )
    if today > _DUE_BY:
        return (
            f"{_MIRROR_MODULE} fehlt seit 2026-05-25 und die Frist {_DUE_BY} ist "
            f"vorbei: {_GATED_FILE} war die ganze Zeit inert. Entscheide jetzt — "
            "Spiegel bauen, oder Testdatei samt Fixtures und Ledger-Zeile loeschen. "
            "Wenn du mehr Zeit brauchst, verschiebe _DUE_BY in dieser Datei "
            "ABSICHTLICH mit datierter Begruendung."
        )
    return None


def test_the_inert_snapshot_test_has_not_outlived_its_deadline() -> None:
    verdict = _verdict(mirror_present=_mirror_present(), today=date.today())
    assert verdict is None, verdict


def test_the_deadline_actually_fires_under_a_shifted_clock() -> None:
    """Beide Seiten des Vergleichs geliefert — nicht behauptet.

    Ohne diesen Lauf waere die Frist selbst wieder nur Prosa: ein Vergleich,
    von dem niemand weiss, ob er jemals die rote Seite erreicht.
    """
    day_before = date(_DUE_BY.year, _DUE_BY.month, _DUE_BY.day)
    day_after = date(_DUE_BY.year, _DUE_BY.month + 1, 1)

    assert _verdict(mirror_present=False, today=day_before) is None, (
        "am Fristtag selbst muss der Tripwire noch schlafen"
    )
    late = _verdict(mirror_present=False, today=day_after)
    assert late is not None and "Frist" in late, (
        "einen Tag nach der Frist muss er rot werden — sonst ist die Frist Dekoration"
    )


def test_a_landed_mirror_demands_the_cleanup() -> None:
    """Der andere Ausgang ist ebenso wenig still."""
    landed = _verdict(mirror_present=True, today=date(2026, 1, 1))
    assert landed is not None and "pin_registry" in landed, (
        "landet der Spiegel, muss der Tripwire das Aufraeumen einfordern"
    )


def test_the_gated_file_still_carries_the_skip_this_tripwire_watches() -> None:
    """Koppelt den Tripwire an sein Objekt.

    Verschwindet der skipif drueben (oder die Datei), ist dieser Tripwire
    gegenstandslos und muss mitgehen — sonst bewacht er ein Phantom.
    """
    from pathlib import Path

    source = (Path(__file__).resolve().parents[1] / _GATED_FILE).read_text(encoding="utf-8")
    assert "pytestmark = pytest.mark.skipif(" in source, (
        f"{_GATED_FILE} traegt den erwarteten Modul-skipif nicht mehr — "
        "entweder ist der Spiegel gelandet oder die Datei wurde umgebaut; "
        "in beiden Faellen gehoert dieser Tripwire mit angepasst oder entfernt."
    )
    assert _MIRROR_MODULE.replace(".", "/") in source or _MIRROR_MODULE in source, (
        f"{_GATED_FILE} nennt {_MIRROR_MODULE} nicht mehr — die Praemisse dieses "
        "Tripwires ist weg."
    )
