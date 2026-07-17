# A0-Fast: Last-, Resilienz- und Kostenprobe

Stand: 2026-07-17

Scope: A0-304, technischer synthetischer Nachweis

Produktionsfreigabe: nein

## Ergebnis

Die deterministische Probe besteht alle sieben definierten Szenarien. Sie
belegt, dass die von uns kontrollierte Übergabequeue beschränkt bleibt, Drops
nicht verschwiegen werden und betroffene Symbole bis zu einer erfolgreichen
Historical-Rekonstruktion fail-closed bleiben.

Der Lauf ist kein Ersatz für einen vollständigen Databento-Live-Test. SDK-
Puffer, reale Netzwerkbandbreite, Provider-Limits und Container-RSS müssen im
mehrsitzigen Shadow-Betrieb zusätzlich gemessen werden.

Ausführung:

```bash
.venv/bin/python -m scripts.run_a0_load_probe \
  --duration-seconds 8 \
  --all-symbol-count 6889 \
  --output /tmp/a0_load_probe_2026-07-17.json
```

Ergebnis: `PASS`, sieben von sieben Szenarien.

## Provisorisches A0-002-Budget

Diese Grenzen dienen nur dem reproduzierbaren technischen Startgate. Sie
dürfen nicht als gemessene Databento- oder Railway-Produktionsgrenzen gelesen
werden.

| Grenze | Wert |
| --- | ---: |
| CPU-Zeit je synthetischem Szenario | 10 s |
| Prozess-Peak-RSS je Szenario | 256 MB |
| geschätztes OHLCV-1s-Wirevolumen je Szenario | 500 MB |
| maximale Dropquote im expliziten Slow-Consumer-Chaosfall | 50 % |
| maximale Historical Requests je Szenario | 10.000 |

Normal-, Max-Symbol- und Open-Burst-Szenarien verlangen unabhängig davon null
Drops. Nur der absichtlich unterdimensionierte Slow Consumer darf Drops
erzeugen; jeder Drop muss als Resync-Pflicht sichtbar bleiben.

## Messergebnisse

| Szenario | Records | Queue-Peak | Drops | Historical Requests | CPU | Peak RSS | Ergebnis |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 200 Symbole, normal | 1.600 | 200/2.048 | 0 | 0 | 0,027 s | 27,43 MB | PASS |
| 900 Symbole, normal | 7.200 | 900/3.600 | 0 | 0 | 0,165 s | 27,92 MB | PASS |
| 900 Symbole, 3x Open-Burst | 10.800 | 2.700/5.400 | 0 | 0 | 0,227 s | 28,70 MB | PASS |
| 900 Symbole, Slow Consumer | 7.200 | 1.800/1.800 | 3.300 | 0 abgeschlossen, 600 ausstehend | 0,126 s | 28,75 MB | PASS, degradiert/alarmierend |
| 900 Symbole, Disconnect | 6.300 | 900/3.600 | 0 | 900 | 0,141 s | 28,75 MB | PASS |
| 900 Symbole, Restart + Bootstrap | 7.200 | 900/3.600 | 0 | 1.800 | 0,167 s | 28,75 MB | PASS |
| 6.889 Symbole, normal | 55.112 | 6.889/27.556 | 0 | 0 | 1,266 s | 33,44 MB | PASS |

Die Wire-Schätzung verwendet 104 Bytes je OHLCV-1s-Record. Für das
6.889-Symbol-Szenario ergeben sich in acht synthetischen Sekunden 5,732 MB.
Zusätzlich zum Prozess-Peak-RSS enthält das JSON-Artefakt den Python-seitigen
`tracemalloc`-Peak je Szenario.

## Backpressure- und Recovery-Vertrag

1. Der Reader schreibt ausschließlich in eine Queue mit fester Kapazität.
2. Bei Überlauf wird der älteste Bar entfernt; die Queue wächst nie über ihr
   Limit.
3. Das betroffene Symbol wird als `resync_required` markiert.
4. Solange die vollständige Rekonstruktion von Session-Open nicht erfolgreich
   ist, erzeugt dieses Symbol kein A0.
5. Erst nach erfolgreicher Rekonstruktion wird die Markierung bestätigt und
   entfernt.
6. Sobald ein Disconnect bekannt ist, werden noch gepufferte Bars verworfen
   und ebenfalls als Drops gezählt; daraus darf kein verspätetes A0 entstehen.
7. Nach jedem Disconnect werden alle abonnierten Symbole vorsorglich
   invalidiert. Der FMP-Pfad bleibt davon unabhängig.

## Alarmierbarkeit

Der Worker exponiert `/metrics` und `/healthz`. Fertige Regeln liegen in
`services/a0_fast_detector/alert-rules.yml`:

- Stream länger als eine Minute getrennt
- neue Queue-Drops innerhalb von fünf Minuten
- Resync-Pflicht länger als zwei Minuten
- Queue länger als 30 Sekunden über 80 %
- verbundener, aber älter als acht Sekunden inaktiver Stream

## Offene Betriebsnachweise

- mindestens eine kontrollierte echte Databento-Unterbrechung
- reales RSS/CPU/Wireprofil für 200 und 900 Symbole über Open, Midday und Close
- Provider-Limit- und Kostenbeleg für die Historical-Rekonstruktion
- Optimierung oder ausdrückliche Freigabe der derzeit bis zu 900 einzelnen
  Historical Requests nach einem 900-Symbol-Disconnect
- Scrape- und Alert-Readback in der späteren Shadow-Umgebung

Bis diese Punkte belegt sind, bleibt A0-Fast im Shadow-Modus und darf nicht
promotet werden.
