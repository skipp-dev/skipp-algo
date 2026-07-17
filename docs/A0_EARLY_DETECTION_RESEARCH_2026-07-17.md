# A0 früher und schneller erkennen: verifizierte Analyse und Zielbild

Stand: 2026-07-17  
Status: Entscheidungsgrundlage; noch keine Produktionsfreigabe  
Verifizierter Code-Stand: `origin/main` bei `244862229`  
Umsetzungsplan: [A0_EARLY_DETECTION_ACTION_PLAN_2026-07-17.md](A0_EARLY_DETECTION_ACTION_PLAN_2026-07-17.md)

## 1. Kurzfazit

Ein bestätigtes A0 kann technisch schneller erkannt werden, ohne seine
fachliche Bedeutung zu verändern. Der größte Hebel ist, die heutige
Intervallabfrage um einen ereignisgetriebenen Sekunden-Stream zu ergänzen.

Ein zukünftiges A0 kann außerdem früher angekündigt werden. Dafür braucht es
jedoch ein eigenständiges Signal mit eigener Semantik:

- **A0-Fast** bestätigt dieselbe A0-Entscheidung wie der bestehende Detektor,
  erhält die notwendigen Marktdaten aber früher.
- **PRE-A0** schätzt, ob und wann ein A0 voraussichtlich in einem definierten
  Horizont entsteht. Es ist ausdrücklich noch kein bestätigtes A0.

Die bestehende A1-/A2-Leiter einfach umzubenennen oder Schwellen abzusenken ist
keine geeignete Lösung. Das würde Vorlauf und fachliche Bestätigung vermischen
und die Fehlalarmrate erhöhen.

Vor einem Wahrscheinlichkeitsmodell müssen zwei Grundlagen geschlossen werden:

1. Die Volumensemantik in Detektor, UI, Ereignislog und Kalibrierung ist heute
   nicht durchgängig identisch.
2. Das heutige Ereignislog enthält überwiegend bereits ausgelöste Signale und
   keine repräsentativen negativen Verläufe. Damit lässt sich
   `P(A0 innerhalb H)` nicht unverzerrt trainieren.

## 2. Begriffe und Scope

| Begriff | Bedeutung in diesem Dokument |
| --- | --- |
| **A0** | Bestehende, bestätigte Entscheidung des Realtime-Detektors einschließlich seiner Guards und Upgrades |
| **Core-A0** | Erfüllung des regulären Preis-/Volumen-Grundgatters vor nachgelagerten Guards oder alternativen Upgrades |
| **A0-Fast** | Frühere Ausführung derselben bestätigten A0-Logik auf schnelleren und frischen Daten |
| **PRE-A0** | Separater, unbestätigter Hinweis auf ein mögliches A0 innerhalb eines expliziten Horizonts |
| **Warm Set** | Symbole mit genügend Aktivität oder Schwellenfortschritt für teurere, höherfrequente Merkmale |
| **Shadow** | Berechnung, Speicherung und Auswertung ohne produktive Benachrichtigung oder Trading-Wirkung |

Der erste Zielbereich ist die reguläre US-Handelssitzung. Premarket und
Postmarket bleiben getrennte, fail-closed Shadow-Pfade, bis Datenfrische,
Quellenparität und Volumenbasis für die jeweilige Sitzung belegt sind.

## 3. Verifizierter Ist-Zustand

### 3.1 A0 ist mehr als eine feste Doppelschwelle

Die Grundschwellen stehen in
[`open_prep/realtime_signals.py`](../open_prep/realtime_signals.py):

- `A0_VOLUME_RATIO_MIN = 3.0`
- `A0_PRICE_CHANGE_PCT_MIN = 1.5`

Das Volumenmaß ist dabei nicht das rohe Verhältnis aus kumuliertem Tagesvolumen
und durchschnittlichem Tagesvolumen. Der Detektor berechnet:

```text
raw_daily_volume_ratio = cumulative_volume / average_daily_volume
normalized_volume_pace = raw_daily_volume_ratio / expected_volume_fraction
```

Danach werden sitzungs- beziehungsweise volumenregimeabhängige Multiplikatoren
auf Preis- und Volumenschwellen angewendet.

Zusätzlich beeinflussen unter anderem diese Pfade das endgültige A0:

- PDH-Ausbruch oder PDL-Bruch
- RSI- und Technical-Consensus-Upgrades beziehungsweise Downgrades
- News-Katalysator-Upgrade
- kurzfristige Momentum-Bestätigung
- Stale-Velocity-Gate
- Gate-Hysterese
- dynamischer Cooldown
- Requalifikation und zeitbasierter Zerfall

Ein schneller oder prognostizierter Pfad muss deshalb entweder dieselbe
Entscheidungsfunktion wiederverwenden oder klar als abweichende
Vorstufenentscheidung gekennzeichnet werden. Eine zweite, leicht andere
Schattenimplementierung der A0-Regel wäre langfristig nicht beherrschbar.

### 3.2 Polling ist die zentrale Latenzquelle

Der Code-Default beträgt 20 Sekunden. Die tatsächliche Produktionskonfiguration
kann den Wert übersteuern und muss für jede Messung aus dem laufenden Dienst
erfasst werden.

Für einen Poll-Abstand `T` liegt der reine Terminierungsverzug eines zufällig
zwischen zwei Polls entstehenden A0 näherungsweise zwischen `0` und `T`; unter
gleichmäßiger Verteilung beträgt der Mittelwert `T / 2`. Provider-, Netzwerk-,
Verarbeitungs- und Benachrichtigungslatenz kommen hinzu.

Der Railway-Startbefehl in
[`services/signals_producer/railway.toml`](../services/signals_producer/railway.toml)
startet den Standardmodus. In diesem Modus wird die News-Pipeline synchron vor
dem Quote-Abruf ausgeführt. Der asynchrone News-Poller wird nur für `--fast`
oder `--ultra` gestartet. Das kann variable Quote-Zeitpunkte, lange Polls und
zusätzlichen Jitter verursachen, obwohl News nicht für jede A0-Grundentscheidung
benötigt wird.

### 3.3 Der vorhandene Near-A0-Repoller ist nur ein Teilhebel

`NearA0Repoller` in
[`open_prep/realtime_signals.py`](../open_prep/realtime_signals.py) kann aktive
A1-/A2-Symbole schneller erneut abfragen. Er ist standardmäßig deaktiviert und
hat absichtlich einen begrenzten Scope:

- Er beschleunigt A1/A2-zu-A0-Eskalationen.
- Ein direkt entstehendes A0 bei einem zuvor unauffälligen Symbol wartet weiter
  auf den Vollpoll.
- Der News-Katalysator-Upgradepfad bleibt im Vollpoll.

Der Kommentar in [`open_prep/rt_notify.py`](../open_prep/rt_notify.py) hält als
bisherige empirische Beobachtung fest, dass nur ungefähr ein Prozent der A1 am
selben Tag zu A0 eskalierten und die meisten A0 direkt entstanden. Diese Zahl
ist als Repository-Beobachtung, nicht als neu validierte Modellmetrik zu
behandeln. Der Repoller ist daher ein schneller, risikoarmer Versuch, aber keine
vollständige Lösung.

### 3.4 Databento ist vorhanden, aber derzeit zu grob angebunden

Der bestehende Feed in
[`services/live_overlay_daemon/feed.py`](../services/live_overlay_daemon/feed.py)
abonniert `EQUS.MINI`, `ohlcv-1m`, `ALL_SYMBOLS`. Ein Minutenbar kann ein
Sekundenproblem nicht lösen.

Databento EQUS.MINI stellt laut offizieller Spezifikation aber auch
`OHLCV-1s`, Trades, BBO, TBBO und MBP-1 bereit. Es aggregiert Preise und Volumen
über seine Komponenten-Venues und liefert `ts_event` sowie `ts_recv`. Damit ist
die technische Grundlage für einen Sekundenpfad bereits verfügbar.

Die Databento- und FMP-Volumenzähler sind nicht automatisch identisch. Deshalb
darf ein Databento-Tagesvolumen nicht ungeprüft durch ein FMP-Durchschnittsvolumen
geteilt werden. Zähler und historische Normalisierungsbasis müssen aus
derselben Quelle stammen oder über einen explizit gemessenen Paritätsvertrag
verbunden werden.

### 3.5 Die aktuelle Volumensemantik driftet zwischen Pfaden

Der Hauptdetektor verwendet `normalized_volume_pace`. Beim Bau von
`RealtimeSignal` wird `volume_ratio` jedoch bewusst mit
`raw_daily_volume_ratio` befüllt.

Das erzeugt mehrere Folgeprobleme:

1. Die VisiData-Zeile berechnet ebenfalls das rohe Verhältnis.
2. `UPCOMING` vergleicht dieses rohe Verhältnis mit Schwellen, deren Bedeutung
   aus der normalisierten A2-Logik stammt.
3. [`open_prep/signal_events.py`](../open_prep/signal_events.py) übernimmt
   `volume_ratio` unverändert ins Ereignislog.
4. [`scripts/calibrate_signal_followthrough.py`](../scripts/calibrate_signal_followthrough.py)
   bucktet 3,0 und 1,0 als A0-/A1-Floors, obwohl das gespeicherte Feld das rohe
   Verhältnis enthält.

Außerdem beantwortet der vorhandene Kalibrator eine andere Frage: Er misst
Follow-through nach einem bereits geloggten Signal. Er schätzt nicht, ob aus
einem aktuellen Nicht-A0 innerhalb eines künftigen Horizonts ein A0 wird.

### 3.6 Das Ereignislog ist für PRE-A0 selektionsverzerrt

`SignalEventLogger` speichert nur das erste oder ein stärker gewordenes
A2/A1/A0 pro Symbol und Richtung innerhalb seines Zustandsfensters. Nicht
gespeichert werden insbesondere:

- unauffällige Kontrollverläufe
- wiederholte Nicht-A0-Snapshots
- mehrere getrennte Episoden derselben Richtung
- Kandidaten, die sich der Schwelle nähern und wieder abdrehen
- Datenlücken und dadurch zensierte Horizonte als explizite Zustände

Ein Modell, das nur aus bereits selektierten Signalen lernt, würde seine
Wahrscheinlichkeiten systematisch überschätzen.

## 4. Lösungsraum

### 4.1 Ansatz A: ereignisgetriebenes A0-Fast

**Ziel:** dieselbe bestätigte A0-Entscheidung früher ausführen.

Empfohlener erster Datenpfad:

1. Watchlist über Databento `OHLCV-1s` beobachten.
2. Sitzungskumuliertes Volumen aus demselben Feed führen.
3. Previous Close und historische Durchschnittsvolumina aus einer
   quellenkompatiblen Basis laden.
4. Bei jedem neuen Sekundenbar eine gemeinsame A0-Entscheidungsfunktion
   ausführen.
5. FMP-Polling zunächst unverändert als Vergleich und Fallback weiterführen.

Beim Start mitten in der Sitzung oder nach einem Reconnect muss der Stream den
fehlenden kumulierten Sitzungsstand per Snapshot oder Replay rekonstruieren.
Kann die Lücke nicht geschlossen werden, bleibt A0-Fast fail-closed.

**Erwarteter Effekt:** Die Poll-Quantisierung sinkt von bis zu einem vollen
Poll-Abstand auf ungefähr die Barfrequenz zuzüglich Transport und Verarbeitung.
Der tatsächliche Gewinn ist im Shadow über Ereigniszeitstempel zu messen und
nicht vorab zu behaupten.

### 4.2 Ansatz B: deterministischer A0-Anlauf mit ETA

Ein verständlicher erster PRE-A0 kann ohne trainiertes Modell entstehen. Für
Preis und Volumen werden Fortschritt, Geschwindigkeit und Beschleunigung
berechnet:

```text
price_progress = abs(change_pct) / effective_a0_price_threshold
volume_progress = normalized_volume_pace / effective_a0_volume_threshold

price_eta  = Restdistanz Preis / robuste Preisfortschrittsrate
volume_eta = Restdistanz Volumen / robuste Volumenfortschrittsrate
a0_eta     = max(price_eta, volume_eta)
```

`volume_eta` darf nicht aus einer naiven linearen Verlängerung des kumulierten
Tagesvolumens entstehen. Geeigneter ist die zusätzliche Handelsrate relativ
zur erwarteten inkrementellen Rate des Symbols.

Mindestguards:

- Datenzeitstempel frisch
- beide Fortschrittsraten positiv
- Richtung über ein Mindestfenster stabil
- keine ungeklärte Stream-Lücke
- effektive, regimeadjustierte Schwellen verwendet
- Cooldown-/Hysteresezustand als Kontext berücksichtigt
- keine Ausgabe einer numerischen Wahrscheinlichkeit vor Kalibrierung

Vor der Modellkalibrierung sollte die Oberfläche deshalb zum Beispiel
`A0-Anlauf`, Fortschrittswerte und ein ETA-Band anzeigen, aber keine scheinbar
präzise Prozentzahl.

### 4.3 Ansatz C: symbol- und kontextspezifische Volumenkurve

Die heutige globale Intraday-Kurve nimmt 25 Prozent des Tagesvolumens bis
10:00 Uhr, 40 Prozent bis 11:00 Uhr und danach einen linearen Verlauf bis zum
Schluss an. Sie ist einfach und transparent, bildet aber Unterschiede zwischen
Symbolen, Wochentagen, Eventtagen, Liquiditätsklassen und verkürzten Sitzungen
nur begrenzt ab.

Ein besseres Modell sollte mindestens berücksichtigen:

- Symbol oder robuste Liquiditätsklasse
- Minute der regulären Sitzung
- Wochentag
- Earnings-/Eventtag
- Gap- und Premarket-Aktivität als Kontext, nicht als reguläres Tagesvolumen
- frühe Ist-Abweichung zur historischen Kurve
- Half-Day-Kalender

Die Literatur zeigt, dass dynamische Intraday-Volumenmodelle Periodizität,
Abhängigkeit und Asymmetrie nutzen können und einfache Volumenprognosen
übertreffen. Das rechtfertigt eine quellspezifische und online aktualisierte
Volumenbasis, nicht automatisch ein komplexes Deep-Learning-Modell.

### 4.4 Ansatz D: kalibriertes Multi-Horizon-Modell

Nach Aufbau eines unverzerrten Datensatzes wird PRE-A0 als horizontbezogene
Wahrscheinlichkeit modelliert:

- `P(A0 LONG in 30 s)`
- `P(A0 SHORT in 30 s)`
- analog für 60 und 180 Sekunden

Ein diskretes Hazard-/Survival-Modell kann alternativ die Zeit bis A0 direkt
abbilden und Sitzungsende oder Datenlücken als Zensierung behandeln. Für die
erste Version sind logistische Regression und monotones Gradient Boosting
vorzuziehen: Sie sind leichter zu debuggen, zu kalibrieren und fachlich zu
erklären als ein neuronales Netz.

Geeignete Merkmalsgruppen:

- Schwellenabstand und Fortschritt zu Preis und Volumen
- robuste Steigung und Beschleunigung über 5/15/30 Sekunden
- abnormaler inkrementeller Volumenfluss
- Richtungskonsistenz und realisierte Kurzfristvolatilität
- Distanz zu PDH, PDL, VWAP und Opening Range
- relative Stärke gegenüber Markt und Sektor
- Spread, Top-of-Book-Größen und Microprice
- Order-Flow-Imbalance und Trade-Ankunftsrate
- News-/Earnings-/Eventkontext
- Sitzung, Liquidität, Regime, Hysterese und Cooldown

Der Datensplit muss zeitlich erfolgen. Überlappende Horizonte desselben
Ereignisses dürfen nicht über Train-, Validation- und Testtage verteilt werden.

### 4.5 Ansatz E: Microstructure nur für das Warm Set

Orderbuchdaten für das gesamte Universum können teuer und operational schwer
sein. Ein zweistufiger Pfad ist effizienter:

1. `OHLCV-1s` bildet das breit beobachtete, günstige Gate.
2. Nur warme Kandidaten erhalten BBO/TBBO/MBP-1-Merkmale.

Plausible Zusatzgrößen sind:

- Order-Flow-Imbalance
- Bid-/Ask-Size-Imbalance
- Microprice relativ zum Mid
- Spread- und Tiefenänderung
- aggressive Kauf-/Verkaufsrate
- Trade-Intensität und Burst-Maße

Forschung findet einen robusten kurzfristigen Zusammenhang zwischen
Order-Flow-Imbalance und Preisänderungen sowie Vorhersagekraft der
Queue-Imbalance für den nächsten Midprice-Tick. Das ist relevante Evidenz für
Merkmale, aber noch kein Beleg für unser konkretes Ziel `A0 in H`. Jede
Microstructure-Erweiterung bleibt deshalb A0-spezifisch zu validieren.

### 4.6 Ansatz F: News und Auktion als spezialisierte Priors

Der Benzinga-WebSocket kann neue Nachrichten push-basiert statt im Quote-Poll
bereitstellen. Er ist sinnvoll für:

- sofortige Aufnahme eines Symbols ins Warm Set
- Ereignis- und Katalysatorflags
- getrennte Vorhersagemodelle für News- und Nicht-News-Episoden

News allein darf kein A0 bestätigen. Forschung zeigt, dass relevante Meldungen
oft schnell zu Sprüngen führen, zugleich aber die große Mehrheit beobachteter
Intraday-Sprünge keiner identifizierbaren öffentlichen Meldung zugeordnet
werden kann.

Für die Minuten vor der Eröffnung ist Nasdaq NOII beziehungsweise ein
gleichwertiger Auction-Imbalance-Feed ein spezialisierter Prior. Indikativer
Cross-Preis, Nettoimbalance und gepaarte Menge können ein A0 unmittelbar nach
09:30 ET ankündigen. Dieser Pfad ist zeitlich und venuespezifisch und darf nicht
als allgemeines Tagesmodell behandelt werden.

### 4.7 Nachrangige Ansätze

Diese Ansätze werden nicht ausgeschlossen, aber erst nach den messbaren
Baselines priorisiert:

- Optionsflow als PRE-A0-Merkmal
- VPIN oder komplexe Flow-Toxicity-Maße
- Transformer/LSTM auf Rohereignissen
- generische technische Indikatoren ohne inkrementellen A0-Nachweis
- Absenken oder Umbenennen der A0-Schwellen

Sie erhöhen Datenmenge und Modellrisiko, bevor geklärt ist, wie viel Nutzen ein
sauberer Sekundenstream und ein einfacher Schwellen-ETA bereits liefern.

## 5. Empfohlenes Zielbild

```text
FMP Batch Poll --------------------------> bestehender A0-Detektor / Fallback
       |                                              |
       |                                              v
       +-------------------------------> A0-Paritätsvergleich

Databento OHLCV-1s --> Quellenadapter --> Feature-Snapshot --> gemeinsamer A0-Entscheider
                              |                 |                    |
                              |                 |                    +--> A0-Fast (bestätigt)
                              |                 |
                              |                 +--> ETA-Baseline --> PRE-A0 (unbestätigt)
                              |                                      |
                              +--> Warm Set --> BBO/TBBO/MBP-1 ------+

Benzinga WS / Earnings / Auction Imbalance -------------------------> Kontextmerkmale

Alle Pfade --> Event-/Entscheidungslog --> Labels --> Walk-forward-Kalibrierung
```

Architekturprinzipien:

1. **Eine A0-Fachlogik:** FMP und Stream dürfen keine unabhängigen Kopien der
   Entscheidung unterhalten.
2. **Getrennte Semantik:** PRE-A0 ist nie ein A0 und nutzt eigene Labels,
   Symbole, Benachrichtigungskanäle und Metriken.
3. **Fail closed:** Unfrische Daten, Reconnect-Lücken oder fehlende
   Normalisierungsbasis deaktivieren den schnellen Pfad, nicht den FMP-Fallback.
4. **Quellenreinheit:** Volumenzähler und Durchschnittsvolumen stammen aus
   derselben Quelle oder einem versionierten Paritätsvertrag.
5. **Ereigniszeit vor Empfangszeit:** Fachliche Fenster verwenden `ts_event`;
   `ts_recv`, Beobachtungs- und Entscheidungszeit dienen der Latenzmessung.
6. **Shadow first:** Neue Datenquellen, Modelle und Benachrichtigungen werden
   erst nach nachgewiesener Parität beziehungsweise Kalibrierung aktiviert.

## 6. Vorgeschlagener Datenvertrag

### 6.1 Markt- und Feature-Snapshot

| Feld | Bedeutung |
| --- | --- |
| `schema_version` | Version des Snapshots |
| `symbol`, `session_date`, `market_session` | Identität und Sitzungsbezug |
| `source` | Zum Beispiel `fmp_batch_quote` oder `databento_equs_mini` |
| `ts_event`, `ts_recv`, `observed_at`, `decision_at` | Fach-, Transport- und Verarbeitungstimestamps |
| `data_age_ms`, `gap_state` | Datenfrische und bekannte Stream-Lücken |
| `price`, `previous_close`, `change_pct` | Preiszustand |
| `cumulative_volume`, `average_daily_volume` | Quellenreine Volumenbasis |
| `raw_daily_volume_ratio` | Rohes kumuliertes Verhältnis |
| `expected_volume_fraction` | Erwarteter kumulierter Sitzungsanteil |
| `normalized_volume_pace` | Zeitnormalisiertes Volumentempo |
| `effective_a0_price_threshold` | Aktuelle Preisgrenze nach Regime |
| `effective_a0_volume_threshold` | Aktuelle Volumengrenze nach Regime |
| `price_progress`, `volume_progress` | Normierter Schwellenfortschritt |
| `price_slope_*`, `volume_rate_*` | Robuste Fenstermerkmale |
| `direction_state`, `direction_stability_s` | Richtung und Beständigkeit |
| `pdh_distance`, `pdl_distance`, `vwap_distance` | Levelkontext |
| `cooldown_state`, `hysteresis_state` | Zustandsbehaftete A0-Guards |
| `news_context`, `event_context` | Katalysatorinformationen |

### 6.2 A0-Entscheidung

| Feld | Bedeutung |
| --- | --- |
| `decision_id` | Idempotenter Schlüssel aus Symbol, Richtung, Ereignis und Regelversion |
| `detector_version` | Versionierte A0-Fachlogik |
| `level`, `direction` | Bestehende A0/A1/A2-Semantik |
| `core_level` | Ergebnis nur des Preis-/Volumen-Grundgatters |
| `final_reason_codes` | Schwelle, PDH/PDL, News, Technik, Downgrade, Cooldown usw. |
| `source` | Datenquelle der Entscheidung |
| `is_shadow` | Darf die Entscheidung externe Wirkung entfalten? |

### 6.3 PRE-A0-Ausgabe

| Feld | Bedeutung |
| --- | --- |
| `pre_a0_state` | `WATCH`, `BUILDING`, `IMMINENT` oder leer |
| `horizon_s` | Expliziter Zielhorizont |
| `probability` | Nur bei aktivierter, kalibrierter Modellversion |
| `eta_low_s`, `eta_high_s` | Robustes ETA-Band statt Scheingenauigkeit |
| `model_version`, `calibration_version` | Nachvollziehbare Modellherkunft |
| `reason_codes` | Haupttreiber der Frühwarnung |
| `expires_at` | Kurze, explizite Gültigkeit |
| `is_calibrated` | Verhindert Prozentanzeige bei unkalibrierten Heuristiken |

## 7. Datensatz und Labeldefinition

### 7.1 Sampling

Ein praktikabler Start ist:

- alle beobachteten Symbole alle fünf Sekunden als Grundgesamtheit
- warme Kandidaten zusätzlich im Sekundentakt
- unveränderte, ruhige Negative kontrolliert und mit Samplinggewicht
  herunterstichproben
- lückenlose Speicherung aller A0-Entscheidungen und Zustandswechsel

Die Artefakte gehören partitioniert nach Sitzungsdatum und Quelle in einen
nicht eingecheckten Runtime-/Research-Speicher. Repository-Manifest und
Schema bleiben dagegen versioniert.

### 7.2 Zielvariable

Für Richtung `d` und Horizont `H`:

```text
y(d, H) = 1,
wenn der bestehende finale A0-Detektor innerhalb H Sekunden erstmals
dieselbe Richtung d bestätigt, bevor Episode, Richtung oder Datenfrische endet.
```

Zusätzlich werden gespeichert:

- `time_to_a0_s`
- `a0_reason_codes`
- Ende durch Richtungswechsel
- Ende durch Sitzungsgrenze
- Ende durch Datenlücke oder Staleness
- Ende ohne A0

Damit lassen sich horizontbezogene Klassifikation und Survival-Auswertung aus
demselben Rohdatensatz ableiten.

### 7.3 Split und Leakage-Schutz

- Walk-forward-Split nach vollständigen Handelstagen
- keine Episode in mehreren Splits
- Purge-/Embargo-Abstand mindestens so lang wie der größte Zielhorizont
- Feature-Zeitstempel müssen kleiner oder gleich dem Vorhersagezeitpunkt sein
- Kalibrierung ausschließlich auf einem separaten Zeitfenster
- finaler Test auf späteren, unangetasteten Sitzungen

## 8. Bewertungsrahmen

### 8.1 A0-Fast

- Verfügbarkeit während der regulären Sitzung
- p50/p95/p99 `decision_at - ts_event`
- Lead gegenüber dem FMP-A0
- Anteil gleicher Richtung und gleicher Reason-Klasse
- Fehlalarme relativ zum bestehenden A0
- Reconnect- und Gap-Recovery-Erfolg
- Parität nach Symbol-, Liquiditäts- und Tageszeitslice

### 8.2 PRE-A0

- Precision und Recall je Horizont
- PR-AUC statt alleiniger ROC-AUC bei seltenem A0
- Fehlalarme pro Stunde am gewählten Betriebspunkt
- Median und Quantile des tatsächlichen Vorlaufs
- Brier Score und Brier Skill Score
- Expected Calibration Error und Reliability Diagram
- Abdeckung und Breite des ETA-Intervalls
- Auswertung getrennt nach Long/Short, Open/Midday/Close, Liquidität,
  Event-/Nicht-Eventtag und Volatilitätsregime

Ein Modell wird nicht nach einer einzelnen Accuracy-Zahl befördert. Es muss
gegen die deterministische ETA-Baseline und gegen ein Base-Rate-Modell gewinnen.

## 9. Risiken und Guardrails

| Risiko | Guardrail |
| --- | --- |
| Unterschiedliche Provider-Volumina | Quellenreine Normalisierung und Shadow-Paritätsreport |
| Stream startet mitten in der Sitzung | Snapshot/Replay; andernfalls Fast-Pfad deaktivieren |
| Doppelte A0-Benachrichtigungen | Idempotenter `decision_id` und gemeinsamer Dedup-Zustand |
| PRE-A0 wird mit A0 verwechselt | Eigene Bezeichnung, Farbe, Payload und Benachrichtigung |
| Scheingenauigkeit | Keine Prozentzahl ohne Kalibrierungsstatus; ETA als Band |
| Selection Bias | Regelmäßige Grundgesamtheit plus gewichtete Negative loggen |
| Leakage | Tagesbasierter Walk-forward-Split mit Purge/Embargo |
| Open-/Half-Day-Fehlkalibrierung | Handelskalender und getrennte Sitzungsmodelle |
| News blockiert Quote-Pfad | News asynchron und nur als Kontext konsumieren |
| Stream-Ausfall | FMP-Polling bleibt unabhängiger produktiver Fallback |
| Premarket-Stale-Daten | Erweiterte Sitzungen weiterhin fail-closed im Shadow |

## 10. Priorisierte Empfehlung

1. Volumenfelder und Ereignisvertrag semantisch korrigieren.
2. Ist-Latenz und tatsächliche Runtime-Konfiguration messen.
3. News aus dem Quote-kritischen Pfad lösen.
4. Near-A0-Repoller zunächst im Shadow instrumentieren.
5. Databento `OHLCV-1s` als parallelen A0-Fast-Pfad aufbauen.
6. Deterministischen A0-Anlauf mit Fortschritt und ETA testen.
7. Repräsentative PRE-A0-Snapshots und Labels sammeln.
8. Erst danach ein kalibriertes Multi-Horizon-Modell trainieren.
9. Microstructure, News und Auction Imbalance nur nach inkrementellem
   A0-Nachweis hinzufügen.
10. Produktive Aktivierung stufenweise und mit jederzeit möglichem Fallback
    durchführen.

Der größte kurzfristige Nutzen ist schnellere Bestätigung. Der größte
langfristige Nutzen ist eine kalibrierte Frühwarnung. Beide Ziele sind
komplementär, dürfen aber weder im Datenvertrag noch in der Nutzeroberfläche
vermischt werden.

## 11. Quellen

Interne Code- und Vertragsquellen:

- [`open_prep/realtime_signals.py`](../open_prep/realtime_signals.py)
- [`open_prep/rt_notify.py`](../open_prep/rt_notify.py)
- [`open_prep/signal_events.py`](../open_prep/signal_events.py)
- [`scripts/calibrate_signal_followthrough.py`](../scripts/calibrate_signal_followthrough.py)
- [`services/signals_producer/railway.toml`](../services/signals_producer/railway.toml)
- [`services/live_overlay_daemon/feed.py`](../services/live_overlay_daemon/feed.py)

Externe Primär- beziehungsweise Originalquellen, abgerufen am 2026-07-17:

- [Databento US Equities Mini: Feed-Spezifikation](https://databento.com/docs/venues-and-datasets/equs-mini)
- [Databento: Real-time Stock Screener](https://databento.com/docs/examples/algo-trading/live-stock-screener)
- [Databento: Live-Latenz mit `ts_recv` messen](https://databento.com/docs/examples/basics-live/live-latency)
- [Databento: MBP-1-Schema](https://databento.com/docs/schemas-and-data-formats/mbp-1)
- [Brownlees, Cipollini, Gallo: Intra-daily Volume Modeling and Prediction](https://iris.luiss.it/handle/11385/253224)
- [Cont, Kukanov, Stoikov: The Price Impact of Order Book Events](https://arxiv.org/abs/1011.6402)
- [Gould, Bonart: Queue Imbalance as a One-Tick-Ahead Price Predictor](https://arxiv.org/abs/1512.03492)
- [Benzinga WebSocket API Overview](https://docs.benzinga.com/ws-reference/overview)
- [Aït-Sahalia, Li, Li: So Many Jumps, So Little News](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4897887)
- [Groß-Klußmann, Hautsch: When Machines Read the News](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=1536005)
- [Nasdaq NOIView 3.0 Specification](https://www.nasdaqtrader.com/content/technicalsupport/specifications/dataproducts/NOIViewSpecification.pdf)
- [Databento: Auction Imbalance Dynamics](https://databento.com/docs/examples/equities/auction-imbalance)
