# Host-Telemetrie der Arbeitsmaschine — Runbook

Betrifft die Alarme im Grafana-Ordner **Host Telemetry** (Gruppe
`darwin-host-telemetry`, definiert in
`services/live_overlay_daemon/infra/grafana/alert-rules.yaml`).

Quelle ist der macOS-node_exporter der Grafana-Cloud-Integration
(`job="integrations/macos-node"`, Scrape-Intervall 60 s). Dashboard:
[MacOS / overview](https://bronzeporridge977.grafana.net/d/darwin-overview/macos-overview).

Zustellung: **Webex**, nicht Slack. Kontaktpunkt `webex-macbook-alerts`,
ausgewählt über das Label `alert_channel: webex` in
`notification-routing.yaml`. Der Trading-Stack meldet unverändert nach Slack.

## Warum diese Regeln so aussehen

Alle Schwellwerte sind an der echten Instanz gemessen (2026-09-01, 7- bzw.
30-Tage-Fenster), nicht geschätzt. Wer sie ändert, sollte neu messen statt zu
raten — die Kommentare in `alert-rules.yaml` nennen jeweils die Zahlen.

| Regel | Schwelle | `for` | Messung |
|---|---|---|---|
| `darwin-cpu-high` | > 90 % | 2 m | 222 Fünf-Minuten-Fenster über 90 % in 30 Tagen |
| `darwin-memory-high` | > 85 % | 2 m | 24 Fenster in 30 Tagen (bei 90 %: **genau 1**) |
| `darwin-swap-thrashing` | > 2 MB/s | 10 m | 35 Fenster in 30 Tagen (bei 5 MB/s: **0**) |

Drei Fallen, die beim Bau dieser Regeln gemessen wurden und die man beim
Ändern wieder auslösen kann:

1. **`node_memory_MemAvailable_bytes` gibt es auf macOS nicht.** Das ist eine
   Linux-Metrik. Der darwin-Exporter liefert `active/compressed/free/inactive/
   internal/purgeable/swap_*/total/wired`. Eine Regel auf `MemAvailable`
   liefert 0 Serien und schweigt für immer, ohne dass etwas rot wird.
2. **`rate(...[1m])` ist bei 60 s Scrape leer.** `rate()` braucht zwei Punkte
   im Fenster; gemessen enthält `[1m]` genau ein Sample. Ratenfenster
   deshalb ≥ `[5m]`.
3. **Swap in *Prozent* ist auf macOS bedeutungslos.** Das System legt die
   Swap-Datei dynamisch an (gemessen: Gesamtgröße schwankt 0–34 GB, Auslastung
   im Median 91,5 %). Aussagekräftig ist der Auslagerungs-*Durchsatz*.

`noDataState: OK` bei allen dreien: ein zugeklappter Laptop liefert keine
Metriken. Das ist der Normalfall, kein Vorfall.

## Wenn ein Alarm kommt

### MacBook CPU sustained high
Erwartbar bei Backtests, Builds und der TradingView-Automation — die Maschine
lag in 30 Tagen mehrfach täglich über 90 %. Ein Alarm ist also kein Defekt,
sondern die Frage „ist das gerade gewollt?".

1. Verursacher: `top -o cpu` oder Activity Monitor, Spalte „% CPU".
2. Ist es ein bekannter Lauf (Backtest, `tv:*`, Suite)? Dann nichts tun.
3. Bleibt es rot, ohne dass ein Lauf offen ist, hängt ein Prozess — vor dem
   Beenden prüfen, ob er in einen Marker/Ledger schreibt.

### MacBook memory pressure high
Ruhewert dieser Maschine ist ~79 % von 16 GB. Anhaltend > 85 % heißt, der
Kompressor arbeitet; der nächste Schritt des Systems ist Auslagern.

1. Activity Monitor → Reiter „Speicher", Spalte „Speicher" absteigend.
2. Browser-Tabs und Parallels sind die üblichen Verdächtigen.
3. Kommt kurz darauf `darwin-swap-thrashing`, ist es kein Rauschen mehr,
   sondern echte Verdrängung — dann etwas beenden.

### MacBook sustained swap-out
Die Maschine schreibt seit 10 Minuten dauerhaft > 2 MB/s Speicher auf die SSD.
Das kostet Latenz in **jedem** laufenden Dienst (auch im live_overlay_daemon,
falls er lokal läuft) und verbraucht Schreibzyklen.

1. Größten Speicherverbraucher beenden (siehe oben).
2. Ist es ein Backtest, Parallelität senken (`-n` der Suite, Worker-Zahl).
3. Hält es über Stunden an, ist die Arbeitslast für 16 GB zu groß — das ist
   eine Kapazitätsfrage, kein Vorfall, den man wegklicken kann.

## Zustellkette prüfen

Wenn ein Alarm in Grafana feuert, aber in Webex nichts ankommt:

1. Grafana → Alerting → Contact points → `webex-macbook-alerts` → *Test*.
2. Webex-Incoming-Webhooks akzeptieren **nur** ein JSON-Objekt mit `markdown`
   oder `text`. Grafanas Standard-Rumpf ist ein anderes Schema und wird mit
   HTTP 400 abgelehnt. Der Kontaktpunkt trägt deshalb ein
   `payload.template` — fehlt es, kommt nichts an.
3. Das Template baut den Text in einer Variablen und gibt ihn einmal mit
   `printf "%q"` aus. Interpolierte Werte laufen vorher durch
   `reReplaceAll "[[:cntrl:]]" " "`, weil Go für Steuerzeichen `\a`/`\v`
   schreibt und JSON die nicht kennt — ein einziges solches Zeichen macht den
   Rumpf ungültig und die Meldung fällt lautlos aus.
4. Die Webhook-URL ist ein Secret (`WEBEX_WEBHOOK_URL`, GitHub-Secret des
   Repos): wer sie hat, kann in den Raum schreiben. Sie steht nur als
   Platzhalter in der YAML.
