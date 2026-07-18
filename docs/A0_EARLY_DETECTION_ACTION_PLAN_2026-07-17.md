# A0-Fast und PRE-A0: detaillierter Action Plan

Stand: 2026-07-18
Status: technische Shadow-Laufzeit aktiv; Evidenz- und Produktionsfreigabe offen
Verifizierter Laufzeitstand: `origin/main` bei `5b0996246`
Fachliche Grundlage: [A0_EARLY_DETECTION_RESEARCH_2026-07-17.md](A0_EARLY_DETECTION_RESEARCH_2026-07-17.md)

## Umsetzungsstand

Stand 2026-07-18 nach Merge und Railway-Rollout:

| Arbeitspaket | Status | Nachweis |
| --- | --- | --- |
| A0-100 Volumenfelder entflechten | umgesetzt | Detektor, VisiData und Event-Schema führen rohe Ratio, erwarteten Tagesanteil und normalisierte Pace getrennt |
| A0-100 `UPCOMING` korrigieren | umgesetzt | Near-A2-Prüfung verwendet jetzt die normalisierte Volumen-Pace |
| A0-100 Kalibrierung migrieren | umgesetzt | Schema v2 nutzt ausschließlich `normalized_volume_pace`; alte v1-Zeilen bleiben explizit als mehrdeutig lesbar; fehlerhafte v2-Zeilen werden verworfen |
| A0-101 Entscheidungstypen | umgesetzt | `open_prep/a0_contract.py` enthält Snapshot, Schwellen-/Zustandskontext, reine Kernentscheidung, finales Level und stabile Reason Codes |
| A0-102 Zeit und Idempotenz | umgesetzt | Event-, Empfangs-, Beobachtungs- und Entscheidungszeit, Datenalter, Quelle, Session, Detector-Version und deterministische Decision-ID werden persistiert |
| A0-103 Golden-Case-Migration | umgesetzt | versionierte JSON-Fixture und Integrationstests decken Schwellenkanten, PDH/PDL, Stale Velocity, RSI, technische Bestätigung, Cooldown, Momentum, Hysterese sowie ungültiges Volumen ab |
| A0-200 News entkoppeln | umgesetzt | der Produktionsstart aktiviert den asynchronen News-Poller jetzt unabhängig von Fast/Ultra; `RT_NEWS_POLL_SECS` steuert nur dessen eigene Kadenz |
| A0-201 Near-A0-Telemetrie | technisch umgesetzt, Beobachtung offen | Prometheus weist Aktivierung, Intervall, Warm-Set, Polls, Fehler und früh gepushte A0 aus; Sitzungsvergleich 2/5/10 s bleibt messzeitgebunden |
| A0-202 Latenzmetriken | teilweise umgesetzt | Quote-Datenalter, tatsächliches Pollintervall, Newsalter/-dauer sowie News- und Quote-Phase sind verfügbar; Notification-Latenz und Dashboard-Auswertung bleiben offen |
| A0-300 Databento-Adapter | technisch umgesetzt | `a0_stream.py` normalisiert OHLCV-1s; `a0_stream_state.py` behandelt Symbol, Event-/Receive-Zeit, RTH-Volumen, Duplikate, Out-of-order, Lücken und Half Days ohne Levelentscheidung im Adapter |
| A0-301 Quellenreine Referenz | technisch umgesetzt | `a0_reference.py` baut Previous Close und ADV ausschließlich aus versionierter, Corporate-Action-adjustierter Databento-Tageshistorie und verwirft Mischquellen |
| A0-302 Bootstrap/Recovery | Recovery-Pfad technisch umgesetzt, Betriebsnachweis offen | Mid-session-Start und erkannte Lücken lösen eine quellenreine Databento-Rekonstruktion von Session-Open bis vor den aktuellen Bar aus; Fetch-, Coverage- und Datenfehler bleiben fail-closed mit Backoff; kontrollierte Live-Reconnects und mehrsitzige Evidenz bleiben offen |
| A0-303 Paritätsmatcher | technisch umgesetzt, Betriebsnachweis offen | Fast- und FMP-Pfade besitzen getrennte opt-in Journale; der deterministische Tagesreport liefert Matchklassen, Lead, Ursachen und beide Snapshots; echte Mehrsitzungsdaten und Dashboard-Auswertung bleiben offen |
| A0-304 Last/Resilienz/Kosten | Shadow aktiv, Mehrsitzungsnachweis offen | dedizierter Worker läuft mit 900 Symbolen, verbundenem Databento-Live-Stream, bounded Queue, privatem Metrics-Scrape und persistentem `/app/data`; Open-Burst und vollständige Sessions fehlen noch |
| A0-400 bis A0-801 | technisch umgesetzt, Evidenz offen | ETA, Snapshotvertrag, Baseline, kalibriertes Candidate-Artefakt und fail-closed Shadow-Inferenz sind vorhanden; neuer Trainingsrun, Shadow-Promotion und Notify bleiben an echte neue Messfenster gebunden |

Die Umsetzung dieses ersten Meilensteins verändert noch keine produktive
Benachrichtigungs- oder Promotion-Semantik. Das bestehende Feld `volume_ratio`
bleibt für Verbraucher rückwärtskompatibel erhalten und ist ausdrücklich die
rohe kumulierte Tagesratio.

## 1. Ziel des Programms

Das Programm liefert zwei getrennte Fähigkeiten:

1. **A0-Fast:** Ein fachlich identisches, bestätigtes A0 wird auf frischen
   Streamingdaten früher erkannt als im bestehenden FMP-Vollpoll.
2. **PRE-A0:** Ein explizit unbestätigtes Signal schätzt für 30, 60 und
   180 Sekunden, ob sich ein A0 derselben Richtung wahrscheinlich entwickelt.

Die bestehende FMP-Pipeline bleibt während der gesamten Entwicklung
produktiver Fallback und Vergleichsmaßstab. Kein Arbeitspaket darf ihre
Verfügbarkeit oder bestehende Benachrichtigungssemantik stillschweigend
verändern.

## 2. Nicht-Ziele

- A1 oder A2 in A0 umbenennen
- A0-Schwellen ohne eigene Outcome-Studie absenken
- Premarket oder Postmarket zusammen mit Regular Hours produktiv aktivieren
- einen zweiten, unabhängigen A0-Regelsatz aufbauen
- ein Deep-Learning-Modell vor einer reproduzierbaren Baseline trainieren
- Databento- und FMP-Volumen ohne gemessenen Quellenvertrag vermischen
- unkalibrierte Heuristiken als Prozentwahrscheinlichkeit anzeigen
- externe Benachrichtigungen ohne gesonderte Rollout- und Betreiberfreigabe
  aktivieren

## 3. Leitentscheidungen

### 3.1 Getrennte Produktverträge

| Vertrag | Fachliche Aussage | Darf bestätigtes A0 ersetzen? |
| --- | --- | --- |
| `A0-Fast` | Bestehende A0-Logik hat auf einem frischen, freigegebenen Datenpfad bestätigt | Ja, nach Paritätsfreigabe |
| `PRE-A0` | Ein Modell oder eine ETA-Heuristik erwartet möglicherweise ein künftiges A0 | Nein |

### 3.2 Gemeinsame Fachlogik

Der FMP- und Streamingpfad müssen denselben versionierten A0-Entscheider
verwenden. Provideradapter dürfen Daten normalisieren, aber nicht selbst über
A0/A1/A2 entscheiden.

### 3.3 Quellenreines Volumen

Für jeden Detektorpfad stammen kumuliertes Volumen und historische
Durchschnittsbasis aus derselben Quelle. Eine eventuelle FMP-Databento-Brücke
benötigt einen expliziten, versionierten und gemessenen Mappingvertrag.

### 3.4 Shadow vor Wirkung

Jede neue Stufe durchläuft:

```text
off -> shadow -> observe -> begrenzte Wirkung -> freigegeben
```

`shadow` schreibt nur Daten und Metriken. `observe` darf eine klar getrennte
Operatoransicht bedienen, aber keine bestehende A0-Benachrichtigung auslösen.

## 4. Programm-Gates

Die folgenden Werte sind **provisorische Startgates**. Phase 0 friert sie nach
der Ist-Baseline ein. Danach dürfen sie nicht anhand der finalen Testdaten
nachträglich gelockert werden.

### 4.1 A0-Fast-Promotion

Mindestumfang:

- mindestens 20 vollständige reguläre Handelssitzungen
- Open, Midday und Close enthalten
- mindestens eine Stream-Unterbrechung oder kontrollierte Reconnect-Probe
- ausreichend A0-Ereignisse für Long und Short; andernfalls Messfenster
  verlängern

Provisorische technische Gates:

| Metrik | Startgate |
| --- | --- |
| Stream-Verfügbarkeit Regular Hours | mindestens 99,5 % |
| Datenalter `decision_at - ts_event` | p95 höchstens 3 s, p99 höchstens 8 s |
| FMP-A0-Abdeckung | mindestens 95 % gleiche Richtung im definierten Matchingfenster |
| Unmatched Fast-A0 | höchstens 5 % aller Fast-A0 und kein Flood-Incident |
| Medianer Lead | positiv und mindestens `max(5 s, 0,25 * Runtime-Pollintervall)` |
| Doppelte produktive Benachrichtigungen | 0 |
| FMP-Fallback bei Stream-Ausfall | unverändert funktionsfähig |

Ein Quellenunterschied kann fachlich plausible Abweichungen erzeugen. Deshalb
reicht eine Gesamtquote allein nicht: Parität ist zusätzlich nach Symbol,
Liquidität, Tageszeit, Richtung und A0-Reason zu prüfen.

### 4.2 PRE-A0-Modellpromotion

Mindestumfang:

- mindestens 20 vollständige Handelssitzungen
- mindestens 200 gelabelte A0-Episoden insgesamt; andernfalls weiter sammeln
- unangetasteter zeitlich später Testsplit
- deterministische ETA-Baseline und Base-Rate-Modell als Vergleich

Provisorische Modellgates:

| Metrik | Startgate |
| --- | --- |
| Brier Skill Score gegen Base Rate | größer 0 |
| PR-AUC gegen deterministische Baseline | mindestens 10 % relativer Gewinn oder dokumentierte Gleichwertigkeit bei deutlich besserer Kalibrierung |
| Expected Calibration Error | höchstens 0,05 gesamt; höchstens 0,10 in freigaberelevanten Slices |
| Betriebspunkt | höchstens 1 Fehlalarm pro regulärer Handelsstunde |
| Recall am Betriebspunkt | Ziel mindestens 40 %; vor Freeze anhand Baseline prüfbar machen |
| Medianer Vorlauf für erkannte Treffer | Ziel mindestens 30 s |
| Leakage-/Split-Audit | 0 offene Findings |
| Unkalibrierte Prozentanzeigen | 0 |

Bei zu wenigen Ereignissen oder breiten Konfidenzintervallen wird nicht
promotet. Ein längeres Messfenster ist ein gültiges Ergebnis, kein Grund für
eine Lockerung des Testdesigns.

## 5. Abhängigkeitsübersicht

```text
Phase 0  Baseline und Verträge
   |
   v
Phase 1  Semantik und gemeinsame A0-Fachlogik
   |-----------------------|
   v                       v
Phase 2  Poll-Latenz       Phase 3  A0-Fast-Stream im Shadow
   |                       |
   |-----------------------|
               v
Phase 4  Deterministischer PRE-A0-ETA
               |
               v
Phase 5  Repräsentativer Datensatz und Labels
               |
               v
Phase 6  Kalibriertes Multi-Horizon-Modell
               |
               v
Phase 7  Inkrementelle Microstructure-/Katalysator-Ablationen
               |
               v
Phase 8  Gestufte Promotion und Betrieb
```

Die schnellere A0-Bestätigung kann nach Phase 3 unabhängig vom
Wahrscheinlichkeitsmodell promotet werden. PRE-A0 hängt dagegen zwingend von
Phasen 1, 4 und 5 ab.

## 6. Phase 0: Baseline, Scope und Gate-Freeze

### Ziel

Den Ist-Zustand so erfassen, dass spätere Verbesserungen, Abweichungen und
Regressionen objektiv messbar sind.

### Arbeitspakete

#### A0-000: A0-Entscheidungsinventar einfrieren

Umfang:

- Grundschwellen und Regime-Multiplikatoren inventarisieren
- alle Upgrade-, Downgrade-, Cooldown-, Hysterese- und Requalifikationspfade
  auflisten
- eindeutige `reason_code`-Taxonomie entwerfen
- Core-Level und finales Level getrennt definieren
- bestehende Edge Cases als Golden Cases sichern

Betroffene beziehungsweise vorgeschlagene Dateien:

- `open_prep/realtime_signals.py`
- neu: `docs/a0_decision_contract.md` oder Vertragsabschnitt im Modul
- neu: `tests/fixtures/a0_decision_cases.json`
- neu: `tests/test_a0_decision_contract.py`

Abnahme:

- jede heutige A0-Entscheidungsroute besitzt mindestens einen Golden Case
- alle Golden Cases erzeugen auf unverändertem Code das erwartete Endlevel und
  nachvollziehbare Reason-Taxonomie
- keine neue Fachlogik in dieser Aufgabe

#### A0-001: Runtime-Latenzbaseline aufnehmen

Pro Poll beziehungsweise Entscheidung erfassen:

- tatsächliches Runtime-Pollintervall und CLI-Modus
- `poll_started_at`, News-Start/-Ende, Quote-Start/-Ende
- Provider-/Quote-Zeitstempel, soweit vorhanden
- Detektor-, Persistenz- und Notify-Zeit
- Watchlist-Größe, Quoteanzahl und Fehlerraten
- Marktphase und Datenalter

Vorgeschlagene Artefakte:

- `artifacts/monitoring/a0_latency_baseline_<date>.json`
- `artifacts/monitoring/a0_latency_baseline_<date>.md`

Abnahme:

- mindestens fünf vollständige reguläre Sitzungen oder eine begründete längere
  Messperiode
- p50/p95/p99 für Poll-Dauer und verfügbare Ende-zu-Ende-Latenzen
- Verteilung der Abstände zwischen tatsächlichen Quote-Snapshots
- quantifizierter Anteil von News-, Provider- und lokaler Verarbeitungslatenz

#### A0-002: Daten- und Kostenbudget festlegen

Zu entscheiden:

- explizite Watchlist oder `ALL_SYMBOLS`
- maximale Streambandbreite und CPU-/Speicherbudgets
- Speicherziel für Trainingssnapshots
- Aufbewahrungsdauer und Komprimierung
- Databento-Live-/Historical-Kosten und Rate-Limits
- getrennte Regular-/Extended-Hours-Abonnements

Kapazitätsannahme für die Planung:

```text
900 Symbole * 4.680 Fünfsekundenpunkte = ca. 4,2 Mio. Grundzeilen/Sitzung
```

Warm-Set-Sekundendaten kommen hinzu. Deshalb sind partitioniertes Parquet und
ein kontrolliertes Negative-Sampling gegenüber ungefiltertem JSONL zu prüfen.

Abnahme:

- erwartete Zeilen, Bytes, CPU, Netzwerk und Aufbewahrung dokumentiert
- Lasttest mit mindestens der erwarteten Symbolzahl
- Speicherziel ist atomar, wiederanlaufbar und nicht an Git-Artefakte gekoppelt

#### A0-003: Promotion-Gates einfrieren

Auf Basis von A0-001 und A0-002:

- Matchingfenster für FMP versus Stream festlegen
- provisorische Gates aus Abschnitt 4 bestätigen oder vorab anpassen
- Slice-Liste und Mindeststichproben definieren
- Regel festlegen, wann ein unzureichendes Sample nur verlängert wird

Abnahme:

- versioniertes Gate-Dokument mit Datum und Begründung
- keine Änderung dieser Gates nach Sichtung des finalen Testfensters ohne neue,
  vollständig getrennte Evaluationsrunde

### Phase-0-Exit

- A0-Fachvertrag vollständig inventarisiert
- Baselinebericht vorhanden
- Datenbudget freigegeben
- Gates vor Experimentbeginn eingefroren

## 7. Phase 1: Semantik und gemeinsame A0-Fachlogik

### Ziel

Alle Pfade verwenden eindeutige Volumenfelder und eine einzige versionierte
A0-Entscheidung.

### Arbeitspakete

#### A0-100: Volumenfelder entflechten

Neue explizite Felder:

- `raw_daily_volume_ratio`
- `expected_volume_fraction`
- `normalized_volume_pace`
- `effective_a0_volume_threshold`
- `effective_a0_price_threshold`

Migrationsregel:

- `volume_ratio` bleibt während eines begrenzten Kompatibilitätsfensters als
  Alias für die bisherige rohe Anzeige erhalten.
- Neue Fachlogik darf den Alias nicht konsumieren.
- Schema und Payload tragen eine Versionsnummer.

Betroffene Dateien:

- `open_prep/realtime_signals.py`
- `open_prep/signal_events.py`
- `open_prep/rt_notify.py`
- `open_prep/streamlit_monitor.py`
- `scripts/calibrate_signal_followthrough.py`
- relevante Overlay-Consumer und Tests

Abnahme:

- `UPCOMING` verwendet `normalized_volume_pace`
- Eventlog enthält rohe und normalisierte Werte getrennt
- bestehender Follow-through-Kalibrator bucktet das beabsichtigte Feld
- Kompatibilitätsalias ist dokumentiert und mit Sunset-Ticket versehen
- Contract-Tests verhindern erneute Vermischung

#### A0-101: Reine Feature- und Entscheidungstypen einführen

Vorgeschlagene neue Module:

- `open_prep/a0_contract.py`
- `open_prep/a0_features.py`

Vorgeschlagene Typen:

- `A0MarketSnapshot`
- `A0ThresholdContext`
- `A0StateContext`
- `A0Decision`
- `A0ReasonCode`

Aufteilung:

1. Provideradapter erzeugen einen validierten Snapshot.
2. Feature-Code berechnet quellenunabhängige Größen.
3. Ein gemeinsamer Entscheider ermittelt Core-Level und finales Level.
4. Zustandshafte Hysterese/Cooldowns werden über expliziten Kontext injiziert.

Abnahme:

- FMP-Pfad nutzt den neuen Entscheider ohne Änderung seiner Golden-Ergebnisse
- Provideradapter enthalten keine A0-Levelentscheidung
- Entscheidung ist mit eingefrorenem Snapshot deterministisch replaybar
- Reason Codes erklären jedes Upgrade und jeden Downgrade

#### A0-102: Zeit- und Idempotenzvertrag ergänzen

Pflichtfelder:

- `ts_event`
- `ts_recv`
- `observed_at`
- `decision_at`
- `data_age_ms`
- `source`
- `session_date`
- `decision_id`
- `detector_version`

Abnahme:

- Latenz kann ohne Logtext-Parsing berechnet werden
- gleiche fachliche Entscheidung erhält nach Retry dieselbe `decision_id`
- fehlende oder unplausible Ereigniszeit führt zu `data_age_unknown`, nicht zu
  impliziter Frische

#### A0-103: Migration und Regressionstests

Testmatrix:

- Schwellenwerte exakt unter/auf/über A0
- Regime-Multiplikatoren
- PDH-/PDL-Upgrade
- News-/Technical-/RSI-Upgrade und Block
- Momentum- und Stale-Velocity-Downgrade
- Hysterese und Cooldown
- Half Day und Session Boundary
- fehlendes Durchschnittsvolumen
- `NaN`, negative oder rückläufige Volumenzähler
- Datenalter unbekannt beziehungsweise stale
- Payload v1 zu v2

### Phase-1-Exit

- FMP-Golden-Ergebnisse unverändert
- rohe und normalisierte Volumenfelder durchgängig getrennt
- gemeinsamer Entscheider produktiv im bestehenden Pfad
- Timestamp-, Reason- und Idempotenzvertrag vorhanden

## 8. Phase 2: Sofortige Poll-Latenzverbesserungen

### Ziel

Latenz und Jitter reduzieren, ohne Datenquelle oder A0-Semantik zu wechseln.

### Arbeitspakete

#### A0-200: News aus dem Quote-kritischen Pfad lösen

Empfohlene Änderung:

- asynchronen News-Poller unabhängig von `--fast`/`--ultra` starten
- Quote-Abruf darf niemals auf einen aktuellen News-Poll warten
- letzter frischer News-Snapshot wird als Kontext gelesen
- News-Frische und News-Ausfall getrennt ausweisen

Nicht empfohlen:

- den Produktionsdienst nur deshalb pauschal mit `--fast` zu starten, weil
  dieser Modus weitere Poll-, Cooldown- oder UI-Semantik verändern kann

Betroffene Dateien:

- `open_prep/realtime_signals.py`
- `services/signals_producer/railway.toml`
- `services/signals_producer/requirements.txt`, falls der WebSocket-Pfad
  aktiviert wird

Abnahme:

- künstlich langsame Newsquelle verschiebt Quote-Abrufe nicht
- Quote-Poll läuft bei Newsfehlern unverändert weiter
- Newsalter ist sichtbar
- Poll-p95 verschlechtert sich nicht

#### A0-201: Near-A0-Repoller messbar im Shadow betreiben

Neue beziehungsweise zu bestätigende Metriken:

- Warm-Set-Größe
- Repolls und Fehler
- A1/A2-zu-A0-Eskalationen
- Lead gegenüber nächstem Vollpoll
- zusätzliche FMP-Requests und Bytes
- de-novo A0, die der Repoller nicht sehen konnte

Rollout:

1. `RT_NEAR_A0_REPOLL_SECS` nur in Shadow-/Operatorumgebung setzen.
2. Keine zusätzliche Benachrichtigung, bis Dedup und Kosten belegt sind.
3. Intervalle 2, 5 und 10 Sekunden über getrennte Sitzungen vergleichen.

Abnahme:

- keine doppelten Signale
- kein geteilter, nicht threadsicherer FMP-Client
- Mehrkosten und tatsächlicher Recallbeitrag dokumentiert
- Entscheidung über Beibehalten, Umbauen oder Verwerfen getroffen

#### A0-202: Ende-zu-Ende-Latenzmetriken produktionsnah machen

Vorgeschlagene Metriken:

- `a0_quote_data_age_seconds`
- `a0_poll_phase_seconds{phase}`
- `a0_decision_latency_seconds{source}`
- `a0_notification_latency_seconds{channel}`
- `a0_poll_interval_actual_seconds`
- `a0_news_snapshot_age_seconds`
- `a0_near_repoll_lead_seconds`

Abnahme:

- p50/p95/p99 im Dashboard auswertbar
- unbekannte Datenzeit separat von frischen Daten
- Alert auf Quote-Datenalter und nicht nur Loop-Liveness

### Phase-2-Exit

- Quote-Pfad blockiert nicht auf News
- Near-A0-Nutzen und Kosten gemessen
- Latenzkomponenten operational sichtbar

## 9. Phase 3: Databento A0-Fast im Shadow

### Ziel

Einen ausfallsicheren Sekundenpfad aufbauen und gegen den bestehenden FMP-A0
vermessen.

### Empfohlene Deployment-Grenze

Für den ersten Shadow wird ein eigener Worker empfohlen, damit Streamfehler,
Dependencies und Last den produktiven FMP-Producer nicht destabilisieren.

Vorgeschlagene Struktur:

```text
services/a0_fast_detector/
  railway.toml
  requirements.txt
  README.md
open_prep/a0_stream.py
open_prep/a0_stream_state.py
open_prep/a0_parity.py
```

Der Worker importiert die gemeinsame A0-Fachlogik aus Phase 1 und schreibt
zunächst ausschließlich Shadow-Snapshot, Paritätsereignisse und Metriken.

### Arbeitspakete

#### A0-300: Databento-Adapter für `OHLCV-1s`

Anforderungen:

- explizite Symbolnormalisierung
- `ts_event` und `ts_recv` erhalten
- kumuliertes Regular-Hours-Volumen führen
- Out-of-order- und Duplicate-Events behandeln
- rückläufigen Volumenzähler erkennen
- Sessionkalender inklusive Half Days verwenden
- keine Levelentscheidung im Adapter

Abnahme:

- deterministischer Replaytest aus aufgezeichneten DBN-Daten
- identische Ausgabe bei erneutem Replay
- Datenalter und Lückenstatus korrekt

#### A0-301: Quellenreine Referenzdaten

Aufgaben:

- Previous Close aus definierter Quelle bereitstellen
- Databento-kompatibles Durchschnittsvolumen aus historischen Tagesdaten
  berechnen
- Lookback, Corporate Actions und fehlende Historie versionieren
- Fallbackhierarchie definieren

Fail-closed-Regel:

- Fehlt quellenkompatibles Durchschnittsvolumen, darf A0-Fast für das Symbol
  nicht entscheiden.

Abnahme:

- kein impliziter FMP-Denominator für Databento-Zähler
- Split-/Corporate-Action-Testfälle
- Referenzdatenalter und Herkunft im Snapshot

#### A0-302: Bootstrap und Reconnect-Gap-Recovery

Fälle:

- Start vor 09:30 ET
- Start mitten in der Sitzung
- kurzer Reconnect mit Replay
- lange Lücke ohne vollständige Rekonstruktion
- Prozessrestart

Regeln:

- vollständiger kumulierter Stand muss belegbar sein
- während ungeklärter Lücke `gap_state != complete`
- A0-Fast bleibt dann stumm; FMP läuft weiter

Abnahme:

- kontrollierte Disconnect-/Reconnect-Tests
- kein A0 aus partiellem Volumenstand
- Gap- und Recovery-Metriken

Umsetzungsstand 2026-07-17:

- Der Worker startet die Rekonstruktion automatisch beim ersten
  `BOOTSTRAP_REQUIRED` oder `GAP_DETECTED`.
- Historische OHLCV-1s-Bars werden über den zentralen Databento-Retry-Pfad von
  Session-Open bis exklusiv zum aktuellen Bar geladen, validiert, dedupliziert
  und anschließend zusammen mit dem erneut eingespielten aktuellen Bar in
  einen vollständigen Zustand überführt.
- Fetchfehler, unvollständige Coverage, Fremdsymbole sowie ungültige oder
  sitzungsfremde Bars erzeugen keine Entscheidung. Ein 30-Sekunden-Backoff
  begrenzt wiederholte Historical-Abrufe.
- Deterministische Tests belegen Mid-session-Recovery, Gap-Recovery,
  Deduplizierung und die Fail-closed-Fälle. Kontrollierte Live-Reconnect-Proben,
  dedizierte Prometheus-Metriken und die mehrsitzige Beobachtung bleiben als
  Betriebsnachweis offen.

#### A0-303: Paritäts- und Lead-Matcher

Für jedes Shadow-A0 speichern:

- Fast- und FMP-Decision-ID
- Richtung und Reason Codes
- Preis-, Volumen- und Schwellenwerte beider Quellen
- Zeitdifferenz
- Matchstatus und Abweichungsursache

Matchklassen:

- `same_decision_fast_first`
- `same_decision_fmp_first`
- `fast_only_source_semantics`
- `fmp_only_missing_stream_data`
- `rule_state_mismatch`
- `unmatched_unknown`

Abnahme:

- täglich reproduzierbarer Paritätsreport
- keine reine Gesamtquote ohne Ursachenklassen
- Drill-down bis zum zugrunde liegenden Snapshot

Umsetzungsstand 2026-07-17:

- Der Fast-Worker verlangt `A0_FAST_PARITY_LOG_DIR` auf persistentem Storage
  und schreibt die erste A0-Entscheidung je Session, Symbol und Richtung als
  sortierte JSONL-Zeile mit `flush` und `fsync`. Erst nach erfolgreicher
  Persistenz wird das zugehörige `A0_FAST_SHADOW`-Ereignis geloggt.
- Der produktive FMP-Pfad bleibt unverändert maßgeblich und erhält mit
  `RT_A0_PARITY_LOG_DIR` einen unabhängigen, fail-soft Opt-in-Evidenz-Sink. Er
  persistiert sowohl finale A0 als auch Core-A0-Entscheidungen, die durch
  Cooldown, Momentum oder andere Zustandsregeln final heruntergestuft wurden.
- Der Journalzustand wird beim Restart rekonstruiert; gleiche Episoden werden
  dadurch nicht erneut geschrieben. Konfligierende Decision-IDs, beschädigte
  JSONL-Zeilen, falsche Quellen und fehlende Pflichtfelder brechen den Report
  sichtbar ab statt stillschweigend die Quote zu schönen.
- `scripts/report_a0_parity.py` verbindet beide Journale für genau eine
  ET-Session, klassifiziert Ursachen, berechnet die Fast-Lead-Zeit und schreibt
  einen atomaren, `fsync`-gesicherten JSON-Report. Jede Matchzeile enthält beide
  Decision-IDs, Reason Codes, Zeiten, Preise, Volumenwerte, Schwellen und
  Vertrags-/Referenzmetadaten für den Drill-down.
- Ein Fast-Ereignis mit `decision_scope=core_only` zählt nur dann als gleiche
  Entscheidung, wenn das FMP-Ereignis ebenfalls `core_level=A0` belegt;
  andernfalls wird es als `rule_state_mismatch` ausgewiesen.
- Offen bleiben reale Mehrsitzungsreports, die Kalibrierung des Matchfensters
  und eine Dashboard-/Alert-Auswertung der gespeicherten Ursachenklassen.

#### A0-304: Last-, Resilienz- und Kostenprobe

Szenarien:

- 200, 900 und – falls vorgesehen – alle Symbole
- Open-Burst
- langsamer Consumer
- Netzwerkunterbrechung
- Prozessrestart
- Historienbootstrap

Abnahme:

- keine unbeschränkte Queue
- definierte Backpressure-/Drop-Policy
- CPU, RAM, Netzwerk und Databento-Nutzung innerhalb Phase-0-Budget
- Slow-Reader- und Disconnect-Zustände alarmierbar

Umsetzungsstand 2026-07-17:

- Reader und Consumer sind über `BoundedBarBuffer` mit harter Kapazität
  getrennt. Die Drop-Policy entfernt den ältesten Bar und erzwingt für dessen
  Symbol eine Historical-Rekonstruktion; die Markierung wird erst nach
  erfolgreicher Recovery entfernt.
- Der Worker reconnectet nach Streamende oder Readerfehler mit begrenztem
  Backoff. Nach einem Disconnect werden alle Symbole invalidiert; FMP bleibt
  vollständig unabhängig.
- `/metrics`, `/healthz` und versionierte Alertregeln machen Queue-Drops,
  Queue-Druck, Disconnects, stale Daten und festhängende Resyncs sichtbar.
- `scripts/run_a0_load_probe.py` simuliert deterministisch 200, 900 und optional
  die volle Symbolzahl sowie Open-Burst, Slow Consumer, Disconnect, Restart und
  Bootstrap. Der Lauf mit 6.889 Symbolen bestand alle sieben Szenarien; Details
  und provisorische Budgets stehen in
  `A0_FAST_LOAD_RESILIENCE_REPORT_2026-07-17.md`.
- Der technische Nachweis ersetzt keine echte Provider-/Container-Messung.
  Insbesondere bis zu 900 einzelne Historical Requests nach einem
  900-Symbol-Disconnect benötigen einen Live-Kosten-/Rate-Limit-Beleg oder eine
  Batchoptimierung. A0-Fast bleibt deshalb Shadow-only.

### Phase-3-Exit

- Shadow-Worker läuft mindestens über das eingefrorene Mindestfenster
- Paritäts- und Latenzgates ausgewertet
- FMP bleibt vollständig unabhängig
- Entscheidung: A0-Fast verwerfen, nachbessern oder für begrenzte Promotion
  zulassen

## 10. Phase 4: Deterministischer PRE-A0-ETA

### Ziel

Eine verständliche, replaybare Frühwarnbaseline schaffen, bevor ein Modell
trainiert wird.

### Arbeitspakete

#### A0-400: Fortschrittsmerkmale

Vorgeschlagenes Modul:

- `open_prep/pre_a0.py`

Pflichtmerkmale:

- `price_progress`
- `volume_progress`
- Restdistanz zu beiden effektiven A0-Schwellen
- robuste Preissteigung 5/15/30 Sekunden
- inkrementelle Volumenrate 5/15/30 Sekunden
- Beschleunigung
- Richtungsstabilität
- Datenalter und Gapstatus
- Distanz zu PDH/PDL als separater Upgradepfad

Abnahme:

- Features verwenden ausschließlich Informationen bis zum Snapshotzeitpunkt
- Grenz- und Nullsteigungsfälle deterministisch
- keine Division durch sehr kleine oder negative Raten

#### A0-401: ETA und Zustandsautomat

Vorgeschlagene Zustände:

```text
NONE -> WATCH -> BUILDING -> IMMINENT
```

Beispielregeln:

- `WATCH`: beide Achsen zeigen relevanten Fortschritt
- `BUILDING`: beide Raten positiv und Richtung stabil
- `IMMINENT`: konservatives ETA-Band liegt innerhalb Zielhorizont
- Rückstufung mit eigener Hysterese
- Ablauf nach kurzer Inaktivität oder Richtungswechsel

ETA:

- robuste Steigung statt letzter Tick
- langsamerer der beiden Schwellenpfade bestimmt die zentrale ETA
- Unsicherheit aus mehreren Fenstern erzeugt `eta_low_s` und `eta_high_s`
- kein ETA, wenn eine Achse nicht fortschreitet

Abnahme:

- synthetische Rampen, Beschleunigung, Abbremsung und Reversal abgedeckt
- keine Flapping-Flut an der Zustandsgrenze
- `is_calibrated = false`; keine Prozentwahrscheinlichkeit

#### A0-402: Operatoransicht und Payload

Anzeigevorschlag:

```text
PRE-A0 LONG | BUILDING | Preis 88 % | Volumen 79 % | ETA 40-75 s
```

Anforderungen:

- optisch und sprachlich klar von A0 getrennt
- Reason Codes sichtbar
- Alter und Ablauf sichtbar
- eigene Metriken und eigener Payloadblock
- keine bestehende A0/A1/A2-Sortierung manipulieren

Abnahme:

- UI-/Schema-Test verhindert Darstellung als bestätigtes A0
- unkalibrierte Prozentanzeige technisch unmöglich

#### A0-403: Deterministische Outcome-Auswertung

Je PRE-A0-Episode messen:

- wurde A0 derselben Richtung innerhalb 30/60/180 Sekunden erreicht?
- tatsächlicher Vorlauf
- maximale erreichte Fortschritte
- Abbruchursache
- Anzahl wiederholter Hinweise derselben Episode

Abnahme:

- täglicher Baselinebericht
- Precision, Recall, Fehlalarme/Stunde und Lead je Horizont
- Betriebspunkt und Zustandsgrenzen vor Modellvergleich eingefroren

### Phase-4-Exit

- replaybare ETA-Baseline vorhanden
- Nutzersemantik klar getrennt
- Baseline-Metriken über ausreichende Sitzungen vorhanden

## 11. Phase 5: Repräsentativer PRE-A0-Datensatz

### Ziel

Einen reproduzierbaren, leak-freien Datensatz mit positiven, negativen und
zensierten Episoden aufbauen.

### Arbeitspakete

#### A0-500: Snapshot-Schema und Writer

Vorgeschlagene Komponenten:

- `open_prep/pre_a0_events.py`
- `open_prep/pre_a0_schema.py`
- `scripts/build_pre_a0_dataset.py`

Speicherformat:

- partitioniertes Parquet nach `session_date`, `source` und optional
  `market_session`
- atomare Manifestaktualisierung
- Schema-Version und Feature-Version in jeder Partition

Sampling:

- fünf Sekunden für die Grundgesamtheit
- eine Sekunde für das Warm Set
- ruhige Negative kontrolliert herunterstichproben
- `sample_weight` und Auswahlgrund speichern

Abnahme:

- Crash erzeugt keine als vollständig markierte Teilpartition
- Duplikat- und Vollständigkeitsprüfung
- Schema-Drift bricht fail-closed
- Speichernutzung innerhalb Budget

#### A0-501: Episoden- und Labelerzeugung

Vorgeschlagenes Modul:

- `open_prep/pre_a0_labels.py`

Episode beginnt beispielsweise bei:

- Eintritt in ein breites Fortschrittsgate
- außergewöhnlicher Volumenrate
- relevantem News-/Eventtrigger

Episode endet bei:

- erstem finalen A0 derselben Richtung
- Richtungswechsel
- Rückkehr unter Inaktivitätsgate
- Datenlücke/Staleness
- Sitzungsende

Labels:

- `y_30`, `y_60`, `y_180`
- `time_to_a0_s`
- `a0_direction`
- `a0_reason_codes`
- `censor_reason`

Abnahme:

- Handprüfung einer stratifizierten Stichprobe
- Golden-Episoden für Treffer, Reversal, Stale, Session-End und Mehrfach-A0
- kein Label nutzt Informationen außerhalb seines Horizonts

#### A0-502: Leakage- und Qualitätsaudit

Prüfungen:

- Feature-Zeit größer als Vorhersagezeit
- Forward-Fill über Sitzungs- oder Gapgrenze
- gleiche Episode in mehreren Splits
- Symboldaten aus Zukunftstagen in Volumenprofilen
- Corporate-Action- und Splitdrift
- Klassenverteilung je Tag und Slice
- Missingness nach Quelle

Abnahme:

- maschinenlesbarer Auditreport
- null offene kritische Leakage-Findings
- bekannte Missingness wird Feature oder Ausschlussgrund, nicht stiller Imputer

#### A0-503: Walk-forward-Splits materialisieren

Anforderungen:

- Split nach vollständigen Tagen
- Purge/Embargo mindestens größter Horizont
- separates Kalibrierungsfenster
- finaler Testsplit unverändert versiegelt
- Splitmanifest enthält Daten- und Code-Provenienz

Abnahme:

- identischer Build erzeugt identische Split-Hashes
- kein Hyperparameterzugriff auf finalen Testsplit

### Phase-5-Exit

- repräsentative positive, negative und zensierte Episoden
- reproduzierbarer Dataset-Build
- Leakage-Audit grün
- finaler Testsplit versiegelt

## 12. Phase 6: Kalibriertes Multi-Horizon-Modell

### Ziel

Eine robuste Wahrscheinlichkeit liefern, die die deterministische ETA-Baseline
nachweislich ergänzt.

### Arbeitspakete

#### A0-600: Modellbaselines

Reihenfolge:

1. Base Rate nach Horizont und Slice
2. deterministische ETA-Regel
3. logistische Regression
4. monotones Gradient Boosting

Komplexere Modelle kommen nur in Betracht, wenn diese Baselines dokumentiert
sind.

Vorgeschlagene Scripts:

- `scripts/train_pre_a0_model.py`
- `scripts/evaluate_pre_a0_model.py`

Mögliche bestehende Dependency-Gruppe:

- `requirements-ml.txt` mit scikit-learn, LightGBM und XGBoost

Abnahme:

- gleiche Splits und Metrics für alle Baselines
- Featureliste und Monotonieannahmen versioniert
- Seed- und Thread-Determinismus soweit technisch möglich

#### A0-601: Horizont- und Richtungsstrategie

Zu vergleichen:

- getrennte Modelle pro Richtung und Horizont
- ein gemeinsames Modell mit Richtung/Horizont als Kontext
- diskretes Hazard-Modell

Entscheidungskriterien:

- Kalibrierung
- Stichprobengröße
- Stabilität über Tage und Slices
- Inferenzkosten
- Erklärbarkeit

Abnahme:

- Modellwahl durch Walk-forward-Evidenz, nicht Trainingsscore
- Long-/Short-Asymmetrie explizit dokumentiert

#### A0-602: Wahrscheinlichkeitskalibrierung

Methoden:

- Platt Scaling als einfache Baseline
- isotone Regression nur bei ausreichender Stichprobe

Pflichtausgaben:

- Reliability Diagram
- ECE und Brier Score
- Konfidenzintervalle oder Bootstrap-Stabilität
- Slice-Kalibrierung

Abnahme:

- `is_calibrated = true` nur bei gültigem, nicht abgelaufenem
  Kalibrierungsartefakt
- keine Extrapolation außerhalb trainierter Featurebereiche ohne Warnzustand

#### A0-603: Modellartefakt und Registry-Vertrag

Artefakt enthält:

- Modellbinärdatei
- Feature- und Schema-Version
- Trainings-/Validierungs-/Kalibrierungsfenster
- Splitmanifest-Hash
- Metriken und Gates
- unterstützte Horizonte und Sitzungen
- Ablauf-/Reviewdatum
- Fallbackverhalten

Abnahme:

- inkompatible Features verhindern Laden
- fehlendes/abgelaufenes Modell schaltet PRE-A0 aus, nicht A0
- reproduzierbarer Offline-Score für Golden Snapshots

#### A0-604: Shadow-Inferenz

Vorgeschlagene Laufzeitmetriken:

- Inferenzdauer
- Feature-Missingness
- Out-of-range-Features
- Modell-/Kalibrierungsversion
- Wahrscheinlichkeitsverteilung
- PRE-A0-Episoden und Outcomes

Abnahme:

- kein Einfluss auf A0-Fachlogik oder FMP-Poll
- Gates aus Abschnitt 4 auf unangetastetem Test-/Shadowfenster erfüllt
- Betreiberreview vor jeder Benachrichtigungsstufe

### Phase-6-Exit

- Modell schlägt Base Rate und ETA-Baseline nach eingefrorenen Gates
- Kalibrierung gültig
- Runtime fail-closed
- Shadowbericht mit Slice- und Stabilitätsanalyse vorhanden

## 13. Phase 7: Inkrementelle Enrichments

### Ziel

Nur Merkmale hinzufügen, die einen messbaren zusätzlichen Nutzen gegenüber dem
freigegebenen Basismodell liefern.

### A0-700: Symbol-/Kontext-Volumenprofil

Varianten:

- globale aktuelle Kurve
- Liquiditätsklassenkurve
- symbol- und wochentagspezifische Kurve
- online aktualisierte Kurve mit Eventkontext

Ablation:

- Fehler der erwarteten kumulierten Fraktion
- PRE-A0-PR-AUC, Brier und Lead
- Open-/Midday-/Close-Slices
- Half Days separat

Promotion nur, wenn:

- Out-of-sample-Volumenprognose besser
- PRE-A0-Metriken nicht nur auf Eventtagen steigen
- kein unvertretbarer Missingness- oder Wartungsaufwand

### A0-701: BBO/TBBO/MBP-1 für das Warm Set

Merkmale:

- Spread
- Bid-/Ask-Size-Imbalance
- Microprice
- Order-Flow-Imbalance
- aggressive Trade-Rate
- Event-/Trade-Intensität

Guardrails:

- kein unkontrollierter Full-Firehose-Pfad
- Bounded Queue und Lastbudget
- EQUS.MINI-order-count-Einschränkungen berücksichtigen
- ausschließlich Ereignisse bis zum Vorhersagezeitpunkt

Promotion nur bei inkrementellem Gewinn über das Modell ohne Microstructure.

### A0-702: Benzinga-WebSocket als Katalysatorkontext

Aufgaben:

- Dependency und Service-Wiring schließen
- Eventzeit, Empfangszeit und Deduplikation erfassen
- Symbolmapping und Relevanzfilter testen
- REST- und WebSocket-Drift messen
- News als Feature/Warm-Set-Trigger, nicht als alleinige A0-Bestätigung

Slices:

- News-A0
- Earnings-A0
- A0 ohne identifizierbare News

### A0-703: Opening-Auction-Modell

Scope:

- eigener Zeitraum vor und unmittelbar nach 09:30 ET
- NOII beziehungsweise venuespezifische Imbalance
- indikativer Cross-Preis, paired quantity und Nettoimbalance
- separate Label- und Kalibrierungsprüfung

Kein Zusammenlegen mit dem allgemeinen Intraday-Modell ohne belegte
Kalibrierungsverbesserung.

### A0-704: Optionsflow- und Deep-Learning-Entscheidung

Erst nach A0-700 bis A0-703 entscheiden:

- verbleibt ein relevanter Fehlercluster?
- existiert genügend Stichprobe?
- rechtfertigt der erwartete Grenznutzen Datenkosten und Modellrisiko?

Ein negatives Ergebnis wird dokumentiert und beendet den Workstream.

### Phase-7-Exit

- jede Erweiterung besitzt einen eigenen Ablationsreport
- nur inkrementell nützliche Features bleiben aktiv
- keine Erweiterung verschlechtert Kalibrierung oder Betriebsstabilität

## 14. Phase 8: Promotion, UX und Betrieb

### Ziel

A0-Fast und PRE-A0 unabhängig, reversibel und beobachtbar aktivieren.

### 14.1 Feature Flags und Kill Switches

Vorgeschlagen:

```text
RT_A0_FAST_MODE=off|shadow|observe|active
RT_A0_FAST_MAX_DATA_AGE_MS=<int>
RT_PRE_A0_MODE=off|shadow|observe|notify
RT_PRE_A0_MODEL_PATH=<path-or-url>
RT_PRE_A0_ALLOWED_HORIZONS=30,60,180
RT_PRE_A0_MAX_ALERTS_PER_HOUR=<int>
```

Regeln:

- A0-Fast- und PRE-A0-Schalter sind unabhängig.
- Modell- oder Streamfehler dürfen bestehendes FMP-A0 nicht deaktivieren.
- `active` beziehungsweise `notify` benötigen explizite Deploymentfreigabe.

### 14.2 A0-Fast-Rollout

1. **Shadow:** nur Parität und Metriken.
2. **Observe:** Operatoransicht zeigt Fast-A0 mit FMP-Matchstatus.
3. **Limited active:** ausgewählte Symbole oder kurze Zeitfenster; bestehender
   Dedup verhindert Doppelmeldungen.
4. **Active:** vollständiger Regular-Hours-Scope nach Gate-Review.

Rollback:

- `RT_A0_FAST_MODE=off`
- Streamworker stoppen
- FMP-Pfad bleibt unverändert aktiv

### 14.3 PRE-A0-Rollout

1. **Shadow:** Modell und Outcomes ohne UI.
2. **Observe:** Operatoransicht, keine Benachrichtigung.
3. **Limited notify:** eigener Kanal, hartes Alarmbudget, klarer PRE-A0-Text.
4. **Notify:** erst nach Stabilitäts- und Nutzerreview.

UX-Regeln:

- PRE-A0 nutzt niemals A0-Farbe, A0-Emoji oder „bestätigt“.
- Horizont, Alter, Ablauf und Kalibrierungsstatus sind sichtbar.
- Prozentwert nur bei gültiger Kalibrierung.
- ETA ist ein Bereich, kein punktgenaues Versprechen.

Rollback:

- `RT_PRE_A0_MODE=off`
- A0/A1/A2 bleiben unverändert

### 14.4 Monitoring und Alerts

Pflichtmetriken A0-Fast:

- Feed verbunden/bereit
- Datenalter bekannt/unbekannt
- Gapstatus und Reconnects
- Event- und Entscheidungsrate
- FMP-Parität und Lead
- Fast-only/FMP-only nach Reason
- Queue-Tiefe und Drops

Pflichtmetriken PRE-A0:

- Modell- und Kalibrierungsversion
- Inferenzfehler und Missingness
- Alerts nach Horizont/Richtung
- Outcomes, Precision/Recall und Fehlalarme/Stunde
- Probability Drift und Calibration Drift
- ETA-Abdeckung

Alerts:

- Feed stale oder Gap unbekannt
- Shadowdaten fehlen trotz Regular Hours
- Parität fällt unter Gate
- Duplicate Decision IDs
- Modell abgelaufen/inkompatibel
- Alarmbudget überschritten
- Kalibrierungsdrift

### Phase-8-Exit

- getrennte Runbooks für A0-Fast und PRE-A0
- getestete Kill Switches
- FMP-Fallback nachweislich unabhängig
- explizite Freigabe je Wirkungsebene
- Post-Rollout-Review mit vereinbartem Beobachtungsfenster

## 15. Teststrategie über alle Phasen

### 15.1 Unit-Tests

- Volumen- und Schwellenmathematik
- Zeitfenster und robuste Steigungen
- ETA-Grenzfälle
- Reason Codes
- Label- und Zensierungslogik
- Modell-/Schema-Kompatibilität
- Feature Flags und fail-closed Verhalten

### 15.2 Property-/Invariant-Tests

- höherer Preisfortschritt darf bei sonst gleichen Daten ETA nicht verlängern
- höhere positive Volumenrate darf bei sonst gleichen Daten Volumen-ETA nicht
  verlängern
- unfrischere Daten dürfen keine stärkere Entscheidung erzeugen
- PRE-A0 darf nie in `level=A0` serialisieren
- unbekannter Gapstatus darf kein A0-Fast auslösen
- identischer Snapshot und Zustand erzeugen identische Entscheidung

### 15.3 Replay-Tests

- vollständige Sitzung
- Open-Burst
- direktes de-novo A0
- A1/A2-Eskalation
- Reversal kurz vor Schwelle
- News-Katalysator
- PDH-/PDL-Upgrade
- Streamlücke und Wiederanlauf
- Half Day

### 15.4 Integrationstests

- FMP und Databento durch gemeinsamen Entscheider
- Shadow-Persistenz und Paritätsmatcher
- Telemetrie und Dashboard
- Modell laden/ablehnen/fallback
- Notification-Dedup ohne tatsächlichen externen Versand

### 15.5 Chaos-/Betriebstests

- Newsquelle hängt
- Databento-Verbindung bricht ab
- Eventqueue läuft voll
- Referenzdaten fehlen
- Uhr driftet oder `ts_event` liegt in der Zukunft
- Partition Writer stirbt mitten im Write
- Modellartefakt korrupt oder abgelaufen

## 16. Vorgeschlagene PR-Reihenfolge

Jeder PR bleibt atomar und enthält eigene Tests sowie einen klaren Rollback.

| PR | Scope | Abhängigkeit | Risiko |
| --- | --- | --- | --- |
| 1 | Volumenfelder, Schema v2 und Contract-Tests | Phase 0 | Mittel |
| 2 | Gemeinsamer A0-Entscheider mit Golden-Parität | PR 1 | Hoch, fachlich zentral |
| 3 | Timestamp-/Reason-/Latenztelemetrie | PR 2 | Mittel |
| 4 | Asynchroner Newskontext und Near-A0-Shadow-Metriken | PR 3 | Mittel |
| 5 | Databento-Adapter, Referenzdaten und Reconnect-Replay | PR 2-3 | Hoch |
| 6 | A0-Fast-Shadow-Worker und Paritätsreport | PR 5 | Hoch |
| 7 | Deterministische PRE-A0-Features, ETA und Operatorpayload | PR 2-3 | Mittel |
| 8 | Snapshot-Dataset, Labels und Leakage-Audit | PR 6-7 | Hoch |
| 9 | Modelltraining, Kalibrierung und Registryvertrag | PR 8 | Hoch |
| 10 | Shadow-Inferenz und PRE-A0-Auswertung | PR 9 | Mittel |
| 11+ | Je ein PR pro Microstructure-/News-/Auction-Ablation | PR 10 | Variabel |
| final | Feature Flags, Runbooks und gestufte Promotion | jeweilige Gatefreigabe | Hoch |

Für line-pinned Produktionsdateien sind Ledger-Drift und repo-spezifische
Guards in jedem betroffenen PR zu aktualisieren. Große Änderungen an
`open_prep/realtime_signals.py` sollten möglichst durch Extraktion in neue
Module erfolgen, damit die Fachänderung und reine Zeilenverschiebung getrennt
reviewbar bleiben.

## 17. Empfohlene Verifikationskommandos

Die exakten Testdateien entstehen phasenweise. Der gemeinsame lokale Einstieg
bleibt die Repo-Venv:

```bash
.venv/bin/python -m pytest \
  tests/test_a0_decision_contract.py \
  tests/test_pre_a0.py \
  tests/test_pre_a0_labels.py \
  tests/test_a0_stream.py \
  tests/test_a0_parity.py \
  -q
```

Ergänzend pro PR:

```bash
.venv/bin/python -m pytest \
  tests/test_realtime_signals_runtime.py \
  tests/test_realtime_signals_uplift.py \
  -q
.venv/bin/python -m pytest tests/test_rt_notify.py -q
.venv/bin/python -m pytest tests/test_signal_events.py -q
.venv/bin/python -m ruff check open_prep services scripts tests
```

Die tatsächlichen vorhandenen Testdateinamen sind vor Ausführung zu prüfen;
neu vorgeschlagene Namen in diesem Plan sind noch keine Aussage über bereits
existierende Dateien.

## 18. Definition of Done

### A0-Fast ist fertig, wenn

- derselbe versionierte A0-Entscheider von FMP und Stream genutzt wird
- Quellen- und Zeitverträge vollständig sind
- Streambootstrap und Reconnect fail-closed funktionieren
- eingefrorene Paritäts-, Latenz- und Stabilitätsgates erfüllt sind
- doppelte produktive Entscheidungen ausgeschlossen sind
- FMP als unabhängiger Fallback getestet ist
- Runbook, Monitoring und Kill Switch vorhanden sind

### PRE-A0 ist fertig, wenn

- PRE-A0 semantisch und visuell nicht mit A0 verwechselt werden kann
- ETA-Baseline reproduzierbar ausgewertet ist
- Datensatz positive, negative und zensierte Episoden enthält
- Split-/Leakage-Audit grün ist
- Modell Base Rate und ETA nach eingefrorenen Gates schlägt
- Wahrscheinlichkeiten nachweislich kalibriert sind
- Shadow- und Slice-Stabilität belegt sind
- Alarmbudget, Rollback und Modellablauf operational abgesichert sind

### Das Gesamtprogramm ist fertig, wenn

- beide Fähigkeiten unabhängig ein- und ausgeschaltet werden können
- keine neue Datenquelle oder Modellkomponente den bestehenden A0-Fallback
  gefährdet
- produktive Wirkung für jede Stufe separat freigegeben wurde
- Dokumentation, Tests, Metriken, Dashboards und Runbooks den tatsächlichen
  Implementierungsstand widerspiegeln

## 19. Nächster konkreter Schritt

Ab der nächsten vollständigen US-Handelssitzung echte Shadow-Evidenz sammeln:

1. A0-Fast-Parität, Latenz, Reconnects und Persistenz über mindestens 20
   vollständige Sessions messen.
2. PRE-A0-Snapshots und bestätigte A0-Episoden ausschließlich aus echten neuen
   Sessions labeln.
3. Nach fünf qualifizierten Sessions das MLflow-Shadow-Gate auswerten; dies ist
   noch keine Notify-Freigabe.
4. Einen neuen Trainingsrun und eine Shadow-Promotion nur bei bestandenem Gate
   erzeugen. Notify bleibt zusätzlich bis 20 Sessions und 200 bestätigten
   A0-Episoden blockiert.
5. Parallel 7–10 vollständige OPRA-Sessions im separaten privaten Shadow-
   Service sammeln und dessen Definition Coverage, Duplikate, Gaps und Latenz
   unabhängig bewerten.
