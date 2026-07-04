# Implementation Plan: Markt-Regime-Variablen + Pine-Integration für skipp-algo

**Datum:** 2026-07-04
**Status:** ENTWURF — zur Freigabe
**Kontext:** Ensemble ist eingefroren (kein Edge nachweisbar). Dieser Plan betrifft
ausschließlich skipp-algo/open-prep als Decision-Support-System: neue
Regime-Messgrößen (Efficiency Ratio, Dispersion, Korrelation) erfassen,
nutzerfreundlich anzeigen (Pine + Alerts) und über die bestehende
Outcome-Pipeline ehrlich validieren. **Keine Änderung an Scoring, Gewichten
oder Playbook-Logik in diesem Plan** — erst nach Validierung (Workstream D).

---

## Leitplanken

1. **Nur additiv:** Neue Spalten, neue Anzeigen, neue Skripte. Bestehendes
   Verhalten (Score, Regime-Klassifikator, Gating) bleibt unangetastet.
2. **Anzeigen ja, steuern nein:** Die neuen Variablen informieren den Nutzer.
   In die Score-Gewichte oder Playbook-Wahl fließen sie erst nach
   vorregistrierter Auswertung (D2) ein.
3. **Sync-Richtung respektieren:** Die SMC++-Libraries werden VON TradingView
   ins Repo gesynct (TV = Source of Truth). Das neue Panel geht den
   umgekehrten Weg (Repo = Source of Truth, Publish NACH TV) und bleibt
   deshalb ein **separates, neues Skript** — nichts wird in die gesyncten
   Libraries injiziert.

---

## Workstream A — Regime-Variablen berechnen & persistieren (Backend)

### A1: Neues Modul `open_prep/market_microstructure.py`

Drei tägliche Messgrößen, alle ex-ante berechenbar (nur Vergangenheitsdaten):

| Variable | Berechnung | Datenbasis |
|---|---|---|
| `market_efficiency_ratio` | Pro Aktie: \|Netto-Bewegung\| / Summe \|1h-Bewegungen\| über letzte 5 Handelstage (~35 Bars); Median über Sample | 1h-Bars, ~100 liquideste Universe-Aktien (paginierter Loader existiert) |
| `cs_dispersion` | Querschnitts-Stdabw. der 1-Tages-Renditen über das Sample, geglättet (5d-Mittel) | Daily Closes (`/stable/historical-price-eod`) |
| `avg_pair_correlation` | Durchschnittliche Paarkorrelation der Tagesrenditen, 20d-Fenster (effizient über Portfolio-Varianz-Identität, keine N²-Schleife) | Daily Closes, gleiches Sample |

Dazu abgeleitet: `market_weather` ∈ {GREEN, YELLOW, RED} aus Perzentil-Rängen
der drei Werte gegenüber den letzten 60 Handelstagen (rein informativ,
Schwellen dokumentiert, NICHT als validiert deklariert).

- API-Kosten: ~100–150 Calls/Tag zusätzlich — irrelevant bei Ultimate.
- Akzeptanz: Modul liefert für einen Stichtag reproduzierbare Werte;
  Unit-Test mit fixiertem Mini-Sample.

### A2: Integration in `run_open_prep`

- Snapshot einmal pro Lauf berechnen, in das Ergebnis-JSON und in **jede
  Outcome-Zeile** schreiben (neue Spalten: `market_efficiency_ratio`,
  `cs_dispersion`, `avg_pair_correlation`, `market_weather`).
- Fehlertolerant: Wenn die Berechnung scheitert → Spalten null, Lauf läuft
  weiter (Muster der bestehenden Fetch-Stufen).
- Akzeptanz: outcomes_YYYY-MM-DD.json enthält die vier Felder; bestehende
  Consumer unverändert funktionsfähig.

**Aufwand A gesamt: ~1 Tag**

---

## Workstream B — Watchlist + Regime nach Pine (Kernstück)

Pine kann keine Daten laden → täglich generiertes Skript mit eingebackenen
Daten, publiziert über die vorhandene TV-Automatisierung.

### B1: Generator `scripts/generate_openprep_pine_panel.py`

Erzeugt `pine/generated/openprep_daily_panel.pine` (Pine v6, Indikator):

- **Eingebackene Konstanten** aus dem letzten open-prep-Lauf:
  Datum, Regime (RISK_ON/…), `market_weather`-Ampel, die drei Messwerte,
  und pro Watchlist-Kandidat: Symbol, Score, Tier, Playbook, Richtung,
  Gap %, RVOL.
- **Anzeige (table, Ecke konfigurierbar):**
  - Kopfzeile: Datum + Ampel (🟢/🟡/🔴) + Klartext („Breakout-Wetter" /
    „Durchwachsen" / „Sägemarkt") + Regime.
  - Eine Zeile pro Kandidat (max. ~12 Zeilen — Pine-Table-Limits unkritisch).
  - **Highlight:** Ist das Chart-Symbol auf der Watchlist, wird seine Zeile
    hervorgehoben + Banner „ANF heute auf der Watchlist — Playbook GAP_AND_GO
    (long)". Das ist der größte Einzel-Mehrwert für Chart-Nutzer.
- **Freshness-Guard im Panel:** Datenstand älter als 1 Handelstag → Panel
  färbt sich grau + Warnhinweis „Watchlist veraltet (Stand: …)". Schützt
  Nutzer vor stiller Veralterung (gleiches SLA-Denken wie
  `check_pine_library_age.py`).
- Akzeptanz: Generator läuft gegen ein echtes outcomes-JSON; erzeugtes Pine
  kompiliert auf TradingView fehlerfrei; Chart-Symbol-Highlight verifiziert.

### B2: Tägliche Publikation (GitHub Actions)

Neuer Workflow `openprep-pine-daily.yml`:

1. Läuft nach Abschluss des morgendlichen open-prep-Runs (workflow_run-Trigger
   oder gemeinsamer Schedule mit Abhängigkeit).
2. Generiert das Panel-Pine (B1).
3. Publiziert das Update nach TradingView über den vorhandenen
   Playwright-Mechanismus (TV_STORAGE_STATE — dieselbe Auth wie der
   Library-Sync). *Vorab zu verifizieren:* der bestehende Publish-Codepfad
   (CLAUDE.md referenziert ihn; konkretes Skript in Phase 3 identifizieren
   oder als `tv_publish_openprep_panel.ts` analog zu
   `tv_fetch_smc_libraries.ts` neu bauen).
4. Nutzer-Seite: Indikator einmalig dem Chart hinzufügen (invite-only oder
   privat-geteilt); Updates propagieren beim Republish automatisch.
- Akzeptanz: 3 aufeinanderfolgende Handelstage automatisch publiziert;
  Panel zeigt jeweils frisches Datum.

### B3: CI-Freshness-Gate

Job im bestehenden Gate-Workflow: schlägt an, wenn das Panel >1 Handelstag
alt ist (analog pine-library-freshness). Aufwand: Stunden.

**Option B-alt (experimentell, nicht Teil des Kernplans):** TradingView
„Pine Seeds" (Custom-Data über GitHub-Repo als SEED_-Symbole) könnte die
Regime-Werte als *plottbare Zeitserie* liefern statt nur als Tages-Snapshot.
Verfügbarkeit/Onboarding ist limitiert — nur prüfen, nicht darauf bauen.

**Aufwand B gesamt: ~2–3 Tage** (B1 ~1–1,5 d, B2 ~1 d, B3 ~0,25 d)

---

## Workstream C — Slack/Discord-Alerts nutzerfreundlich angleichen

`open_prep/alerts.py` trägt das Regime bereits in den Payloads. Erweiterung:

- C1: Ampel + Klartextzeile in alle drei Formatter (`_format_slack_payload`,
  `_format_discord_payload`, `_format_generic_payload`):
  „🟢 Breakout-Wetter — Bewegungen laufen aktuell durch (ER 0.42, Disp 1.8%,
  Korr 0.31)" — dieselben Formulierungen wie im Pine-Panel (ein Wording,
  alle Kanäle).
- C2: Regime-Change-Alert (`alert_regime_change`) um Ampel-Wechsel ergänzen
  (eigener Event-Typ `weather_change`, gleiche Hysterese-Idee wie beim
  VIX: Wechsel nur bei klarem Perzentil-Übertritt, kein Geflacker).
- Akzeptanz: Test-Webhook zeigt neue Felder; kein Bruch bestehender Consumer
  (nur additive Felder).

**Aufwand C gesamt: ~0,5 Tag**

---

## Workstream D — Validierung (die Schleife ehrlich schließen)

- D1: Läuft automatisch — die Spalten aus A2 akkumulieren mit jedem
  gelabelten Outcome.
- D2: **Pre-Registration JETZT schreiben** (`regime_study/PREREG_OPENPREP.md`),
  bevor Daten anfallen. Vorschlag der Hypothesen:
  1. GAP_AND_GO-Kandidaten haben höhere 30m-Hit-Rate an Tagen im obersten
     ER-Terzil als im untersten.
  2. GAP_FADE-Kandidaten zeigen das umgekehrte Muster.
  3. Hit-Rate aller Kandidaten ist im obersten Dispersions-Terzil höher als
     im untersten.
  Auswertung erst bei ≥300 neu gelabelten Zeilen NACH Einführung der Spalten
  (~5–6 Monate), Terzil-Grenzen aus rollierenden 60d-Perzentilen (ex-ante).
- D3: Erst bei Bestätigung: Vorschlag für Gewichts-/Playbook-Integration als
  separater, eigener Plan.
- **Stop-Regel:** Nicht bestätigte Hypothesen werden nicht auf denselben
  Daten nachjustiert. Anzeige-Features (B/C) bleiben davon unberührt — sie
  sind als Information gerechtfertigt, nicht als validierte Prognose.

**Aufwand D gesamt: ~0,5 Tag jetzt + Auswertung in ~6 Monaten**

---

## Phasenfolge & Abhängigkeiten

| Phase | Inhalt | Abhängig von | Aufwand |
|---|---|---|---|
| 1 | A1+A2 (Variablen + Outcome-Spalten) | — | ~1 Tag |
| 2 | D2 (Pre-Registration) | A1-Definitionen | ~0,5 Tag |
| 3 | B1 (Pine-Generator + Panel, manueller Publish-Test) | A2 | ~1,5 Tage |
| 4 | B2+B3 (Publikations-Automation + CI-Gate) | B1 | ~1,25 Tage |
| 5 | C1+C2 (Alert-Angleichung) | A1 | ~0,5 Tag |
| 6 | D-Auswertung | ~6 Monate Daten | später |

Gesamt bis „Nutzer sieht Watchlist + Ampel in Pine": **~4–5 Arbeitstage.**

## Risiken & offene Punkte

1. **TV-Publish-Codepfad:** Existenz/Details des Publish-Skripts (Gegenstück
   zum Fetch) in Phase 4 verifizieren; ggf. neu bauen (Playwright-Muster
   vorhanden). Größte Unbekannte des Plans.
2. **TradingView-Limits:** Tägliches Republish eines privaten/invite-only
   Skripts ist üblich, aber Rate-Limits/TOS beim ersten Automationstest
   beobachten.
3. **Snapshot-Charakter:** Das Panel ist ein Tages-Snapshot (kein Intraday-
   Update). Für den Premarket-Use-Case von open-prep ausreichend; im Panel
   klar als „Stand: HH:MM ET" ausgewiesen.
4. **Disziplin:** Verlockung widerstehen, die 91 vorhandenen Labels jetzt
   schon für Schwellen-Tuning zu benutzen (Kleinstichproben-Falle, dreimal
   demonstriert). Schwellen sind Perzentil-basiert und rein informativ,
   bis D2 ausgewertet ist.
