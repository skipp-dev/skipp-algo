# Die TradingView-Sperre auf das reduzieren, was sie sperren soll

**Stand 2026-08-13. Alle Zahlen gemessen, Herkunft je Zeile angegeben.**

## Das Problem, in einem Satz

Ein `smc-library-refresh`-Lauf hält die Gruppe `tradingview-session` rund
**140 Minuten**, von denen **13 Minuten** eine TradingView-Sitzung brauchen.

## Die Messungen

**Wo die Zeit hingeht** (Schrittzeiten aus Lauf 31545616987, live gelesen):

| Schritt | Dauer | braucht TV-Sitzung |
|---|---:|---|
| Run pre-publish strict release gates | 59,4 min | nein |
| Run strict release gates | 19,9 min | nein |
| Run evidence gate tests | 4,4 min | nein |
| Erzeugung, Setup, Artefakte | ~10 min | nein |
| Publish library to TradingView | 5,7 min | **ja** |
| TradingView post-release validation | 3,8 min | **ja** |
| TradingView readonly preflight | 3,4 min | **ja** |

**Warum die Gates keine Sitzung brauchen** — zwei unabhängige Belege:

1. `Run pre-publish strict release gates` läuft **vor**
   `Write TradingView storage state`. Zu dem Zeitpunkt existiert im Lauf keine
   TV-Anmeldung.
2. In `scripts/run_smc_release_gates.py` sind alle 16 TradingView-Vorkommen
   Fehlercode-Klassifikation eines fertigen JSON-Berichts. Kein Playwright, kein
   Browser, kein Netzaufruf. `verify_structure_artifact_availability.py` erwähnt
   TradingView nicht.

**Woher die 59 Minuten kommen:** Zwei Tore werten das Kreuzprodukt
Symbole × Zeitrahmen sequenziell aus — 12 × 7 = 84 Paare je Tor, 168 gesamt.
Lokal gemessen: 922 s für das ganze Skript, Torbilanz
`reference_bundle ok Paare=84` und `measurement_lane warn Paare=84`.
In CI 59 min, also ~21 s pro Paar
gegen ~5,5 s lokal (Runner-Faktor ~4). Der Verfügbarkeits-Prüfer im selben
Schritt braucht **1 Sekunde** und ist nicht der Kostenpunkt.

**Die Folge:** 18–21 Läufe pro Werktag (Cron gibt 9, `workflow_run` verdoppelt)
× 2,33 h = ~42 h Nachfrage auf einen Platz mit 24 h. Überlast 1,75×, die
Schlange wächst um ~18 h pro Tag. Gemessene Wartezeiten: 22 h bis 36,5 h.
`tv-save-consumer-source` steht in derselben FIFO-Schlange, weshalb die
Verifikation der Kundenoberflächen strukturell rund anderthalb Tage zu spät
kommt — das ist die Ursache der beiden roten TradingView-Alarme, nicht
TradingView selbst.

## Warum es ein Workflow-Split wird und kein Job-Split

`concurrency:` steht in `smc-library-refresh.yml` auf **Workflow-Ebene**
(Zeile 129, Spalte 0). Der ganze Lauf hält die Gruppe, nicht ein Job darin — ein
Job-Split würde die Sperrzeit deshalb **nicht** verkürzen.

Die Gruppe auf Job-Ebene zu verschieben wäre der kleinere Eingriff, ist aber
nicht abgesichert: Im Repo gibt es **67 Workflow-Ebene-Blöcke und null auf
Job-Ebene**. `queue: max` — die Eigenschaft, die am 2026-08-06 eingeführt wurde,
weil unter der Vorgabe `queue: single` der nächste Ankömmling den Wartenden
**stornierte** — ist damit auf Job-Ebene im Repo unbelegt. Ein stiller Rückfall
in das Verwerfen von Läufen wäre schlimmer als der heutige Stau, weil er
unsichtbar ist.

Deshalb: zwei Workflows, und der veröffentlichende erbt den erprobten Block
wortgleich.

## Der Zuschnitt

**`smc-library-refresh.yml`** (Name, Zeitplan und Auslöser bleiben)

- Der Workflow-Ebene-Block `concurrency: tradingview-session` **entfällt**.
- Enthält Schritte bis einschließlich `Archive dated library snapshot`.
- Neu am Ende: Übergabe-Artefakt hochladen und die Entscheidung festschreiben.

**`smc-library-publish.yml`** (neu)

- Auslöser: `workflow_run` auf `smc-library-refresh`, `completed` + `success`.
- Trägt den bestehenden `concurrency`-Block **wortgleich**.
- Enthält Schritte ab `Write TradingView storage state` bis zum Ende, unverändert.

## Was über die Grenze muss

Kartiert über alle 67 Schritte des `refresh`-Jobs. Es gibt genau zwei Sorten,
beide übergabefähig:

**Dateien** (als Artefakt `refresh-payload-<run_id>`):

```
pine/generated/smc_micro_profiles_generated.pine        <- das, was publiziert wird
pine/generated/smc_micro_profiles_generated.json
pine/generated/smc_micro_profiles_core_import_snippet.pine
artifacts/ci/**                                          <- Gate-Evidenz + Diff-Patch
artifacts/snapshots/<datum>/**
```

**Entscheidungen** (heute `steps.X.outputs.Y`): `changed`, `publish_allowed`,
`breaking`, `reason`, `first_failed_test`, `first_failed_test_line`,
`stale_guard_active`, `provider_preflight_severity`, `bundle_present`.

`workflow_run`-Ereignisse tragen **keine** Job-Outputs des auslösenden Laufs.
Deshalb wandern diese Werte als `artifacts/ci/refresh_handoff.json` **mit dem
Artefakt** und werden im Publisher in einem frühen Schritt nach `$GITHUB_OUTPUT`
zurückgelesen. Damit hängt keine Bedingung an einer API, die sie nicht liefert.

**Was ausdrücklich NICHT übergeben wird:**

- Der **TradingView-Zustand** kommt aus dem Secret `TV_STORAGE_STATE` und wird im
  Publisher frisch geschrieben.
- Das **Databento-Bündel** holt `scripts/restore_databento_export_bundle.py` per
  `GH_TOKEN`. Der Publisher wiederholt den Aufruf, statt das Bündel
  durchzureichen — die post-publish-Tore brauchen dieselben Daten.
- `/tmp/library_before.pine` und `/tmp/manifest_before.json` leben nur zwischen
  „Snapshot vor der Erzeugung" und `Detect library changes`; beide bleiben im
  Refresh.

Kein Prozesszustand, keine offene Sitzung, kein Arbeitsverzeichnis-Zustand außer
Dateien. Das war die Frage, an der der Plan hätte scheitern können.

## Erwartete Wirkung

Heute hält **jeder** Lauf die Sperre über seine volle Dauer — auch die rund 60 %,
die bei unveränderter Bibliothek früh aussteigen, denn die Gruppe wird beim
Start des Laufs genommen, nicht beim ersten TradingView-Schritt.

Nach dem Split hält nur der Publisher die Sperre, und er startet nur, wenn sich
etwas geändert hat:

| | heute | nachher |
|---|---:|---:|
| Läufe, die die Sperre halten | 18–21/Tag | ~7/Tag (nur `changed=true`) |
| Sperrzeit je Lauf | ~140 min | ~43 min (Setup 5 + TV 13 + post-Tore 20 + Rest 5) |
| Nachfrage | ~42 h/Tag | **~5 h/Tag** |
| Auslastung des einen Platzes | 175 % | ~21 % |

Die Sperre wird beim **Job-Start** genommen, also inklusive Checkout und
Installation — die 5 Minuten Setup zählen mit. Das ist eingerechnet.

## Was danach offen bleibt

- **Die 84 Paare laufen sequenziell.** Parallelisierung senkt die Laufzeit
  unabhängig davon, wo die Tore stehen. Ob die Paare unabhängig sind, ist nicht
  geprüft.
- **Zehn weitere Workflows halten dieselbe Gruppe auf Workflow-Ebene**:
  `credential-health-check`, `openprep-pine-panel-publish`,
  `pine-library-version-monitor`, `pine-library-publish-handlibs`,
  `smc-overlay-library-publish`, `smc-release-gates`, `smc-r4-context-readback`,
  `tradingview-storage-refresh`, `tv-post-mutation-verify`,
  `tv-save-consumer-source`. Bei mehreren davon ist offen, ob sie überhaupt eine
  Browser-Sitzung anfassen. Nicht in diesem Schnitt geprüft, nicht behauptet.

## Prüfregeln für die Umsetzung

- Workflow-Änderungen wählt der Ledger-Guard **nicht** aus:
  `pytest tests/ -k workflow` vollständig fahren, sonst ist die Prüfung vakuum.
  (Und `-k workflow` ist selbst eine Auswahl: Dateien ohne „workflow" im Namen
  — etwa `test_tradingview_session_concurrency.py` — fallen heraus. Erst der
  volle Ledger-Guard hat sie erwischt.)
- Jeder Schritt im Publisher hängt heute an `diff.changed` bzw.
  `publish_gate.publish_allowed`. Beim Umzug müssen diese Bedingungen erhalten
  bleiben, nur aus der Handoff-Datei gespeist — ein vergessenes `if` würde
  publizieren, wo heute nichts passiert.
- Der Publisher darf **nicht** starten, wenn `changed=false`.
