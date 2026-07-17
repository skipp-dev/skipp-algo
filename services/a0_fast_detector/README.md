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
- Mid-session-Start und erkannte Lücken lösen vor einer Entscheidung eine
  vollständige Databento-Historical-Rekonstruktion ab Session-Open aus.
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

## Pflichtvariablen

| Variable | Bedeutung |
| --- | --- |
| `A0_FAST_MODE` | muss `shadow` sein |
| `DATABENTO_API_KEY` | Databento-Zugang des isolierten Workers |
| `A0_FAST_SYMBOLS` | kommasepariertes, explizites Symbolset |
| `A0_FAST_REFERENCE_FILE` | gemountete JSON-Datei mit `StreamReference`-Zeilen |
| `A0_FAST_PARITY_LOG_DIR` | Verzeichnis auf einem persistenten Volume für tägliche Fast-JSONL-Journale |

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

- `/metrics`: Prometheus-Textformat für Verbindung, Datenalter, Queue-Tiefe und
  -Kapazität, Drops, Resync-Pflicht, Disconnects, Recoveries, Live-/Historical-
  Nutzung, Entscheidungen, CPU und Peak-RSS.
- `/healthz`: `200` nur bei verbundener Quelle ohne ausstehende Resync-Pflicht,
  andernfalls `503`.
- `alert-rules.yml`: Regeln für Disconnect, Slow-Reader-Drops, festhängenden
  Resync, Queue-Druck und stale Daten.

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

Der Report enthält nicht nur die Gesamtzahlen, sondern jeden Matchstatus, beide
Decision-IDs, Lead-Zeit, Reason Codes sowie die Preis-, Volumen- und
Schwellen-Snapshots für den Drill-down. Der Output wird atomar und mit `fsync`
geschrieben.
