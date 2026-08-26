"""Populations-Wächter: JEDER scheduled Workflow ist beobachtet oder begründet ausgenommen.

Befund 2026-08-19: 46 scheduled Workflows, 22 beobachtet, 24 unsichtbar. Möglich
war das, weil die beiden bestehenden Inventar-Tests in
``test_workflow_freshness_monitor_workflow_contract.py`` nur Ledger und Workflow
GEGENEINANDER prüfen — die Stichprobe gegen sich selbst. Keiner prüfte gegen die
Grundgesamtheit, also blieb jeder neue Cron von Geburt an unbeobachtet
(prove-over-population-Klasse).

Beobachtung heißt hier ausschließlich: Merkt jemand, wenn dieser Workflow GAR
NICHT MEHR LÄUFT? Ein eigener Issue-Opener beantwortet das nicht — er läuft dann
selbst nicht. Deshalb zählt nur ein Eintrag auf einer der beiden Watchlists.
"""

from __future__ import annotations

import datetime as dt
import re

import pytest

from tests._workflow_yaml import WORKFLOWS_DIR, iter_workflow_files, load_workflow

# Die beiden Workflows, die scripts/check_workflow_freshness.py mit
# `<datei>.yml=<budget>`-Argumenten aufrufen.
WATCHLIST_WORKFLOWS: tuple[str, ...] = (
    "workflow-freshness-monitor.yml",
    "meta-watchdog.yml",
)

_WATCH_ARG_RE = re.compile(r"^\s+([a-z0-9_-]+\.ya?ml)=\d+", re.M)
# Nach dem Datum darf beliebiger Text folgen (Issue-Referenz, Doppelpunkt,
# Begruendung). Ein strengeres Muster hat sich am 2026-08-19 sofort geraecht:
# das Ergaenzen von " (#4875)" liess den Match auslaufen und entfristete die
# Ausnahme STILL — gefangen von der Mutationsprobe, gesichert durch
# test_befristet_entries_have_a_parsable_date.
_EXEMPT_DEADLINE_RE = re.compile(r"^BEFRISTET bis (\d{4}-\d{2}-\d{2})\b")
_EXEMPT_MARKER = "BEFRISTET"

# Dateiname -> Begründung, warum ein stiller Ausfall KEINE Datenfolge hat.
_EXEMPT: dict[str, str] = {
    # --- Berichte/Digests: Ausfall kostet einen Bericht, keinen Zustand. ---
    "ops-digest-daily.yml": (
        "Reiner Tages-Digest an einen Chat-Kanal; faellt er aus, fehlt eine "
        "Zusammenfassung, kein Zustand kippt und keine Evidenz geht verloren."
    ),
    "plan-2-8-status-daily.yml": (
        "Statusbericht ueber Plan 2.8; die zugrundeliegenden Daten entstehen "
        "anderswo, der Bericht ist reine Darstellung."
    ),
    "plan-2-8-weekly-digest.yml": (
        "Wochenzusammenfassung desselben Plans; oeffnet bei Fehlschlag selbst "
        "ein Issue und traegt keine Datenfolge."
    ),
    "plan-2-8-monthly-digest.yml": (
        "Monatliche Zusammenfassung; Ausfall ist ohne Datenfolge und faellt "
        "beim naechsten Monatslauf auf."
    ),
    "f2-weekly-digest.yml": (
        "Woechentliche Darstellung des F2-Gates; das Gate selbst laeuft "
        "taeglich und steht auf der Watchlist."
    ),
    "promotion-gate-weekly-dashboard.yml": (
        "Dashboard-Rendering ueber die taeglichen Promotion-Gate-Ergebnisse; "
        "promotion-gate-daily.yml ist beobachtet."
    ),
    "ev20-real-run-reminder.yml": (
        "Monatliche Erinnerung, die bei Fehlschlag selbst ein Issue oeffnet; "
        "Ausfall verzoegert eine Erinnerung, mehr nicht."
    ),
    # --- Selten/wochenweise, Ergebnis wird beim naechsten Lauf neu erzeugt. ---
    "ml-family-research.yml": (
        "Woechentlicher Forschungslauf ohne Produktionskonsumenten; Ergebnisse "
        "sind explorativ und werden beim naechsten Lauf neu erzeugt."
    ),
    "regime-stratification-validation.yml": (
        "Woechentliche Validierung mit Report-Charakter; kein Gate haengt am "
        "Ergebnis, kein Live-Pfad liest es."
    ),
    "smc-measurement-benchmark.yml": (
        "Samstags-Benchmark; die taegliche Variante "
        "smc-measurement-benchmark-rolling.yml traegt die Messkette und ist "
        "beobachtet."
    ),
    "pine-library-freshness.yml": (
        "Monatlicher 120-Tage-Waechter ueber die handgeschriebenen "
        "Pine-Libraries; die Kadenz ist so lang, dass ein Freshness-Budget "
        "keine zusaetzliche Information traegt."
    ),
    "pine-library-publish-handlibs.yml": (
        "Sonntaeglicher Publish der Hand-Libraries; ein ausgefallener Lauf "
        "publiziert beim naechsten Mal, und die Version-Drift faengt "
        "pine-library-version-monitor.yml (beobachtet)."
    ),
    # --- Externe Integration, Ausfall ist am Zielsystem sichtbar. ---
    "composio-canary.yml": (
        "Canary gegen eine externe Integration; ein Ausfall zeigt sich "
        "unmittelbar an der Integration selbst, nicht an unseren Daten."
    ),
    "composio-publish.yml": (
        "Woechentlicher Publish an dieselbe externe Integration; kein "
        "Repo-Zustand haengt daran."
    ),
    # ats-baseline-daily.yml: BEFRISTET-Eintrag (#4875) am 2026-08-26 nach
    # Plan aufgeloest — Laufzeitprofil gemessen (Build 32:49, Budget 30->75
    # in #5088), Messlauf 32940381326 gruen, Watchlist-Zeile '=72:weekday'
    # ergaenzt.
}


def _scheduled_workflows() -> set[str]:
    """Alle Workflows mit mindestens einem cron-Schedule."""
    scheduled: set[str] = set()
    for path in iter_workflow_files():
        workflow = load_workflow(path)
        # PyYAML parst den Schluessel `on:` als Boolean True (YAML 1.1). Ohne
        # diesen Fallback faende der Test NIE einen Trigger und waere
        # vakuum-gruen.
        triggers = workflow.get("on", workflow.get(True))
        if not isinstance(triggers, dict):
            continue
        schedule = triggers.get("schedule")
        if isinstance(schedule, list) and any(
            isinstance(entry, dict) and entry.get("cron") for entry in schedule
        ):
            scheduled.add(path.name)
    return scheduled


def _watched_workflows() -> set[str]:
    watched: set[str] = set()
    for name in WATCHLIST_WORKFLOWS:
        watched |= set(
            _WATCH_ARG_RE.findall((WORKFLOWS_DIR / name).read_text(encoding="utf-8"))
        )
    return watched


def test_the_population_is_not_empty() -> None:
    """Vakuitaets-Schutz: ein kaputter Parser darf nicht als 'alles beobachtet' durchgehen."""
    scheduled = _scheduled_workflows()
    watched = _watched_workflows()

    assert len(scheduled) >= 40, (
        f"nur {len(scheduled)} scheduled Workflows gefunden — Parser kaputt?"
    )
    assert len(watched) >= 20, (
        f"nur {len(watched)} Watchlist-Eintraege gefunden — Regex kaputt?"
    )


def test_every_scheduled_workflow_is_watched_or_exempt() -> None:
    """Der fehlende dritte Test: Population statt Stichprobe."""
    unobserved = sorted(_scheduled_workflows() - _watched_workflows() - set(_EXEMPT))

    assert not unobserved, (
        "Diese scheduled Workflows sterben still — niemand merkt, wenn ihr Cron "
        f"aufhoert zu feuern: {unobserved}. Entweder eine Zeile "
        "`<datei>.yml=<budget_hours>[:any][:weekday]` im Probe-Step von "
        "workflow-freshness-monitor.yml ergaenzen (und den Ledger in "
        "test_workflow_freshness_monitor_workflow_contract.py mitziehen), ODER "
        "hier in _EXEMPT eintragen mit einer Begruendung, warum ein stiller "
        "Ausfall keine Datenfolge hat."
    )


def test_exemptions_have_a_real_rationale() -> None:
    """Eine Ausnahme ohne Begruendung ist eine unsichtbare Watchlist-Luecke mit Extraschritt."""
    for name, rationale in sorted(_EXEMPT.items()):
        assert len(rationale.strip()) >= 30, f"{name}: Begruendung zu duenn ({rationale!r})"


def test_exemptions_are_not_stale_entries() -> None:
    """Karteileichen: eine Ausnahme fuer einen Workflow, den es nicht mehr gibt."""
    scheduled = _scheduled_workflows()
    orphans = sorted(name for name in _EXEMPT if name not in scheduled)

    assert not orphans, (
        f"_EXEMPT nennt Workflows, die nicht (mehr) scheduled sind: {orphans} — "
        "Eintrag entfernen."
    )


def test_no_workflow_is_both_watched_and_exempt() -> None:
    both = sorted(_watched_workflows() & set(_EXEMPT))

    assert not both, f"beobachtet UND ausgenommen — widerspruechlich: {both}"


def test_befristet_entries_have_a_parsable_date() -> None:
    """Ein Tippfehler im Fristformat darf nicht still entfristen.

    Ohne diesen Test ist die Frist nur so stark wie ein Regex-Match: wer den
    Text umformuliert, entwaffnet den Stolperdraht unbemerkt und der Eintrag
    gilt fuer immer. Genau das passierte am 2026-08-19 beim Ergaenzen einer
    Issue-Referenz.
    """
    for name, rationale in sorted(_EXEMPT.items()):
        text = rationale.strip()
        if _EXEMPT_MARKER not in text:
            continue
        assert _EXEMPT_DEADLINE_RE.match(text), (
            f"{name}: Begruendung nennt '{_EXEMPT_MARKER}', aber die Frist ist "
            "nicht parsbar. Exakt 'BEFRISTET bis YYYY-MM-DD' am Textanfang "
            "schreiben (danach ist beliebiger Text erlaubt) — sonst laeuft die "
            "Ausnahme nie ab."
        )


@pytest.mark.parametrize("today", [dt.date.today()])
def test_time_boxed_exemptions_expire(today: dt.date) -> None:
    """Stolperdraht statt Prosa: eine befristete Ausnahme MUSS ablaufen.

    Muster aus #4858 (Early-Close-Horizont): Das Ablaufdatum steht im Text und
    der Test wird an diesem Tag rot — mit Handlungsanweisung. Ohne diesen
    Mechanismus waere 'wir nehmen ihn spaeter auf' blosse Prosa (CLAUDE.md,
    Forward-Promises-Regel).
    """
    for name, rationale in sorted(_EXEMPT.items()):
        match = _EXEMPT_DEADLINE_RE.match(rationale.strip())
        if not match:
            continue
        deadline = dt.date.fromisoformat(match.group(1))
        assert today <= deadline, (
            f"{name}: befristete Ausnahme ist am {deadline} abgelaufen. Jetzt "
            "entscheiden: Ursache behoben -> auf die Watchlist von "
            "workflow-freshness-monitor.yml (plus Ledger-Eintrag im "
            "Contract-Test); noch offen -> Frist mit NEUEM Datum und "
            "aktualisierter Begruendung verlaengern. Nicht kommentarlos verlaengern."
        )
