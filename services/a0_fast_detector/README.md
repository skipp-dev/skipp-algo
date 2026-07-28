# A0-Fast Shadow Worker

Dieser Worker ist die isolierte Deployment-Grenze für A0-Fast. Er abonniert
Databento `EQUS.MINI` mit `ohlcv-1s`, führt quellenreines kumuliertes
Regular-Hours-Volumen und verwendet die gemeinsame Kernentscheidung aus
`open_prep.a0_contract`.

## Sicherheitsvertrag

- Start nur mit `A0_FAST_MODE=shadow`.
- Keine Notification-, Slack-, Pine- oder Signals-Publication-Abhängigkeit.
- Explizites Symbolset; kein implizites `ALL_SYMBOLS`.
- Referenzdatei muss Previous Close und ADV aus Databento enthalten.
- Jeder Verbindungsaufbau nutzt Databento Live Intraday Replay ab dem früheren
  Zeitpunkt von Verbindungszeit und 09:30 ET. Damit ist auch bei einem
  Mid-session-Deploy die Lücke zwischen dem verzögerten Historical-Ende und
  dem Echtzeitstrom vollständig belegt, bevor PRE-A0 ausgewertet wird.
- Eine später im laufenden Stream erkannte Lücke löst weiterhin vor einer
  Entscheidung eine vollständige Databento-Rekonstruktion ab Session-Open aus.
- Fehlgeschlagene oder nicht belegbar vollständige Rekonstruktion sowie eine
  fehlende Referenz erzeugen kein A0.
- Ausgaben sind `A0_FAST_SHADOW`-Logereignisse mit `decision_scope=core_only`.
- Vor dem Logereignis wird die erste A0-Entscheidung je
  Session/Symbol/Richtung in ein fsync-gesichertes JSONL-Journal geschrieben;
  schlägt das Persistieren fehl, wird kein Shadow-Ereignis ausgegeben.
- Der produktive FMP-Producer bleibt vollständig unabhängig.
- Reader und Consumer sind durch eine beschränkte Queue getrennt. Bei Überlauf
  wird der älteste Bar verworfen und das betroffene Symbol bis zur belegten
  Historical-Rekonstruktion gesperrt.
- PRE-A0 ist optional in denselben vollständigen Snapshotpfad eingebunden. Ein
  PRE-A0-Fehler wird protokolliert, darf aber die A0-Kernentscheidung nicht
  unterdrücken oder verändern.
- Der Worker-Prozess besitzt weiterhin keinen Notification-Pfad. `notify` wird
  auch bei gesetzter Freigabe fail-closed abgelehnt. Der optionale
  PRE-A0-Pilot-Tailer (siehe „PRE-A0 Pilotbetrieb") ist ein separater,
  read-only Prozess hinter dem Logstrom — kein Import und keine Codeänderung
  im Worker.

## Pflichtvariablen

| Variable | Bedeutung |
| --- | --- |
| `A0_FAST_MODE` | muss `shadow` sein |
| `DATABENTO_API_KEY` | Databento-Zugang des isolierten Workers |
| `A0_FAST_SYMBOLS` | kommasepariertes, explizites Symbolset |
| `A0_FAST_REFERENCE_FILE` | gemountete JSON-Datei mit `StreamReference`-Zeilen |
| `A0_FAST_PARITY_LOG_DIR` | Verzeichnis auf einem persistenten Volume für tägliche Fast-JSONL-Journale |

`RT_A0_FAST_MODE=shadow` ist der kanonische Schalter; `A0_FAST_MODE=shadow`
bleibt als Kompatibilitätsalias erhalten.

## Optionaler PRE-A0-Shadowbetrieb

PRE-A0 startet nur, wenn alle folgenden Variablen gültig sind. Andernfalls
bleibt ausschließlich PRE-A0 aus; A0-Fast und FMP-A0 laufen unabhängig weiter.

| Variable | Bedeutung |
| --- | --- |
| `RT_PRE_A0_MODE` | `shadow` oder `observe`; `notify` ist in diesem Worker verboten |
| `RT_PRE_A0_MODEL_PATH` | lokales, kompatibles und nicht abgelaufenes Modellartefakt |
| `RT_PRE_A0_SNAPSHOT_DIR` | persistentes Ziel für atomare Parquet-Partitionen und Manifeste |
| `RT_PRE_A0_ALLOWED_HORIZONS` | Teilmenge von `30,60,180` |
| `RT_PRE_A0_SNAPSHOT_FLUSH_ROWS` | Puffergrenze, Default `500`, maximal `100000` |

Sampling: ruhige Grundgesamtheit alle fünf Sekunden mit `sample_weight=5`,
ab `WATCH` jede Sekunde mit `sample_weight=1`. Recovery, Queue-Lücke und
Disconnect löschen den rollierenden PRE-A0-Zustand. `observe` schreibt nur ein
klar unbestätigtes `PRE_A0_OBSERVE`-Operatorlog; der Worker-Prozess selbst hat
weiterhin keinen Versandpfad. Optional konsumiert der Pilot-Tailer dieses Log
(siehe „PRE-A0 Pilotbetrieb").

## PRE-A0 Pilotbetrieb

Explizit freigeschalteter Pilot-Pfad (2026-07-21): `start.sh` pipet den
Logstrom des Workers durch `pilot_alert_tailer.py`. Der Tailer reicht jede
Zeile unverändert weiter (Railway-Logs bleiben intakt) und postet beim
Übergang eines Symbols in `IMMINENT` eine klar gelabelte Pilot-Nachricht in
einen dedizierten Slack-Kanal. Er ist bewusst **nicht** der `notify`-Pfad des
Rollout-Runbooks und übernimmt dessen User-Semantik: kein A0-Claim, keine
bestätigte Formulierung, ETA nur als Range, niemals eine Wahrscheinlichkeit
(Bootstrap-Kalibrierung ist degeneriert, siehe #3847).

| Variable | Bedeutung |
| --- | --- |
| `RT_PRE_A0_PILOT` | `1` schaltet den Tailer ein; sonst reiner Passthrough |
| `RT_PRE_A0_PILOT_WEBHOOK_URL` | https-Slack-Incoming-Webhook des Pilot-Kanals |
| `RT_PRE_A0_PILOT_COOLDOWN_S` | Re-Alert-Sperre je Symbol+Richtung, Default `1800` |
| `RT_PRE_A0_PILOT_MAX_ALERTS_PER_HOUR` | hartes Stundenbudget, Default `20` |

Voraussetzung: `RT_PRE_A0_MODE=observe` (das Bootstrap-Artefakt erfüllt das
`offline_evaluated`-Gate). Fehlende oder ungültige Pilot-Variablen lassen den
Tailer fail-closed als Passthrough laufen. Kill-Switch: `RT_PRE_A0_PILOT`
entfernen (oder `RT_PRE_A0_MODE=shadow`) und redeployen.

Optional: `A0_FAST_MAX_GAP_SECONDS`, `A0_FAST_A0_VOLUME`,
`A0_FAST_A0_PRICE` und die entsprechenden A1-/A2-Schwellen sowie:

| Variable | Default | Bedeutung |
| --- | ---: | --- |
| `A0_FAST_BUFFER_CAPACITY` | `max(2048, 4 × Symbole)` | harte Obergrenze der Reader-/Consumer-Queue |
| `A0_FAST_RECONNECT_BACKOFF_SECONDS` | `5` | Reconnect-Backoff, zulässig 0,1 bis 60 s |
| `A0_FAST_METRICS_PORT` | `9108` | lokaler Metrics-/Health-Port; `0` deaktiviert |
| `A0_FAST_METRICS_HOST` | `127.0.0.1` | sichere Bind-Adresse; für externes Scraping bewusst konfigurieren |

Nach einem Disconnect reconnectet der Worker selbstständig. Alle abonnierten
Symbole werden dabei invalidiert und müssen vor einer neuen Entscheidung ihre
Sessionhistorie rekonstruieren. Ein Prozessrestart erreicht denselben
fail-closed Zustand über den Mid-session-Bootstrap.

## Metrics und Alerts

- Grafana: [PRE-A0 Shadow Operations](https://bronzeporridge977.grafana.net/d/pre-a0-shadow-v1/pre-a0-shadow-operations)
  bündelt Shadow-Readiness, Modellidentität, Live-Datenpfad, Inferenzqualität,
  Persistenz, Runtime-Resilienz und Promotion-Guardrails. Die versionierte Quelle
  ist `services/live_overlay_daemon/infra/grafana/dashboard-pre-a0.json`; sie wird
  bei Änderungen auf `main` automatisch in den Grafana-Ordner `PRE-A0` publiziert.
- `/metrics`: Prometheus-Textformat für Verbindung, Datenalter, Queue-Tiefe und
  -Kapazität, Drops, Resync-Pflicht, Disconnects, Recoveries, Live-/Historical-
  Nutzung, Entscheidungen, CPU und Peak-RSS.
- Bei aktiviertem PRE-A0 zusätzlich Modell-/Kalibrierungsstatus, Inferenzzeit,
  Missingness, Out-of-range-Werte, Zustände, Score-Buckets, Snapshotwrites und
  Persistenzfehler. `pre_a0_enabled=0` unterdrückt Modellalarme im Off-Modus.
- `/healthz`: `200` nur bei verbundener Quelle ohne ausstehende Resync-Pflicht,
  andernfalls `503`; empfangene, aber dauerhaft unverarbeitete Records sind
  ebenfalls ungesund.
- `/evidencez`: `200` erst wenn die laufende Instanz Records empfängt und
  verarbeitet, PRE-A0-Inferenz ausführt und mindestens einen Snapshot-Puffer
  erfolgreich auf das persistente Volume gespült hat. Ein erfolgreiches
  Railway-Deployment oder `/healthz=200` allein belegt ausdrücklich **nicht**,
  dass die Messperiode läuft.
- `alert-rules.yml`: Regeln für Disconnect, Slow-Reader-Drops, festhängenden
  Resync, Queue-Druck, stale Daten und empfangenen Markttraffic ohne
  persistierten PRE-A0-Evidenzfluss.

## Verbindlicher Deployment-Nachweis

„PRE-A0 sammelt Messdaten“ darf erst berichtet werden, wenn derselbe laufende
Container alle folgenden Nachweise liefert:

1. `/healthz` und `/evidencez` antworten beide mit HTTP 200.
2. `a0_fast_records_processed_total`, `pre_a0_scores_total` und
   `pre_a0_snapshots_recorded_total` steigen über zwei zeitlich getrennte
   Abfragen während der Regular Session.
3. `pre_a0_snapshot_rows_flushed_total > 0` und
   `pre_a0_persistence_errors_total == 0`.
4. Unter `RT_PRE_A0_SNAPSHOT_DIR` existiert mindestens eine aktuelle
   Parquet-Partition samt Manifest auf dem persistenten Volume.
5. Die Session-/Episodenzählung wird aus diesen Dateien ermittelt; Deployment-
   Alter, Stream-Verbindung und Modellbereitschaft werden niemals als
   empirische Session-Evidenz gezählt.

## Reproduzierbare Lastprobe

```bash
.venv/bin/python -m scripts.run_a0_load_probe \
  --duration-seconds 8 \
  --all-symbol-count 6889 \
  --output /tmp/a0_load_probe.json
```

Die Probe deckt 200, 900 und optional die angegebene Maximalzahl, Open-Burst,
Slow Consumer, Disconnect, Prozessrestart und Historical Bootstrap ab. Der
aktuelle Messbericht steht in
`docs/A0_FAST_LOAD_RESILIENCE_REPORT_2026-07-17.md`.

## Noch nicht produktionsbereit

Der Worker rekonstruiert nach einem Mid-session-Start oder einer erkannten
Lücke automatisch den quellenreinen Databento-Volumenstand von Session-Open bis
unmittelbar vor dem aktuellen Bar und spielt diesen Bar danach erneut ein. Der
Abruf verwendet den zentralen Retry-Pfad. Kann der Abruf die vollständige
Zeitspanne nicht belegen oder enthält er ungültige Daten, bleibt das Symbol
fail-closed und wird nach einem kurzen Backoff erneut versucht.

Offen sind kontrollierte Live-Disconnect-/Reconnect-Nachweise und ein
mehrsitziger Shadow-Rollout. Die geloggte Entscheidung ist außerdem
`core_only`; der Paritätsreport zählt sie deshalb nur dann als gleiche
Entscheidung, wenn der FMP-Snapshot ebenfalls `core_level=A0` belegt. Final
abweichende Zustandsregeln erscheinen explizit als `rule_state_mismatch`.

## Täglicher Paritätsreport

Der bestehende FMP-Producer kann seine A0-Entscheidungen über
`RT_A0_PARITY_LOG_DIR` in ein eigenes tägliches, fsync-gesichertes
Paritätsjournal schreiben. Das ist opt-in und fail-soft, damit ein
Evidenzproblem den produktiven FMP-Fallback nicht beeinflusst. Der lokale
Report verbindet diese Datei mit dem Fast-Journal reproduzierbar:

```bash
.venv/bin/python -m scripts.report_a0_parity \
  --session-date 2026-07-17 \
  --fast /volume/a0_shadow_databento_2026-07-17.jsonl \
  --fmp /volume/a0_shadow_fmp_2026-07-17.jsonl \
  --stream-health /volume/a0_stream_health_2026-07-17.json \
  --output /volume/a0_parity_2026-07-17.json
```

Der Report trennt ab Schema 2 zwei Verträge: `engine_parity` replayt die
gemeinsame A0-Schwellenlogik je kanonischem Snapshot; `source_equivalence`
vergleicht die tatsächlich unterschiedlichen Provider-Snapshots und nennt
Preis-, Previous-Close-, Volume-Pace- und Timing-Ursachen. Jeder Matchstatus,
beide Decision-IDs, Lead-Zeit, Reason Codes sowie die Roh-Snapshots bleiben für
den Drill-down erhalten. Der Output wird atomar und mit `fsync` geschrieben.
Der vollständige Cutover-Vertrag steht in
`docs/CROSS_SOURCE_VOLUME_DECISION.md`.
