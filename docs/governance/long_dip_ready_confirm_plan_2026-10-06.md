# Long-Dip: Plan für Armed → Confirmed und den Zuschnitt von Ready

Stand 2026-10-06. Grundlage: der LONG-PENDING-Log aus #5666, gelesen mit
`scripts/tv_long_engine_log_readout.ts` vom Hauptchart `vWgAWyfC`, der seit
2026-10-06 die Suite v435 rechnet (Migration mit
`scripts/tv_suite_publication_migration.ts`, #5681/#5690). Fünf Symbole (AAPL,
NVDA, JPM, XOM, UNH), 15 Minuten, einmal mit der Sitzung des Layouts (ETH) und
einmal mit regulären Handelszeiten (RTH). Vorgänger:
`long_dip_strategy_report_2026-10-04.md`.

## Vorbehalt

Keine Stufe der Engine hat bisher nach Kosten einen Vorteil gezeigt
(`long_dip_strategy_report_2026-10-04.md`, `structure_grain_history_2026-10-03.md`).
Mehr Durchlass an Confirm oder Ready erzeugt zunächst nur mehr Trades. Jeder
Schritt unten ist deshalb ein Versuch mit Maßstab, keine Auslieferung:
**ein geänderter Zuschnitt muss nach Kosten besser abschneiden als Armed auf
denselben Symbolen**, sonst ist er nur ein späteres Armed mit weniger Trades.

## Befund

### Trichter

| Stufe | ETH | RTH |
|---|---|---|
| Armed | 318 | 218 |
| davon „Armed expired (no Confirm in time)" | 232 | 164 |
| davon „price below invalidation level" | 74 | 43 |
| davon „source zone invalidated" | 5 | 10 |
| Confirmed | 8 | 1 |
| PENDING-Bars (Confirmed, nicht Ready) | 54 | 7 |
| Ready | 0 | 0 |

Die Invalidierungen über den Kurs sind gewollt. Der Verlust sind die
Abläufe ohne Confirm.

### Warum Ready nie erreicht wird

Gleichzeitig scheiternde Ready-Bedingungen je PENDING-Bar:

| scheiternde Bedingungen | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 | 11 |
|---|---|---|---|---|---|---|---|---|---|
| PENDING-Bars ETH | 4 | 3 | 1 | 8 | 17 | 12 | 5 | 3 | 1 |
| PENDING-Bars RTH | – | – | 1 | 1 | – | 2 | 3 | – | – |

Häufigste Bedingungen (Anteil der PENDING-Bars):

| Bedingung | ETH (54) | RTH (7) |
|---|---|---|
| `quality` | 54 | 7 |
| `stretch` | 54 | 1 |
| `accel` | 44 | 3 |
| `trade_hard` | 42 | 7 |
| `second_derivative` | 38 | 7 |
| `ddvi` | 23 | 7 |
| `overhead_zone` | 9 | 7 |

Keine Einzelursache: keine PENDING-Bar scheitert an weniger als drei
Bedingungen.

### Zeitfenster im Code

| Input | Wert | Wirkung |
|---|---|---|
| `Max Bars Armed -> Confirm` | 2 | `confirm_is_fresh` nur bis Setup-Alter 2 |
| `Setup Expiry Bars` | 6 | Armed läuft nach 6 Bars ab |
| `Max Bars Confirm -> Ready` | 2 | `ready_is_fresh` nur bis Confirm-Alter 2 |
| `Confirmed Expiry Bars` | 6 | Confirmed läuft nach 6 Bars ab |

Ein Confirm ist damit nur 1–2 Bars nach dem Arming möglich
(`resolve_long_confirm_break_state` verlangt eine spätere Bar als die
Arming-Bar); die Bars 3–6 können nur noch ablaufen. Ob das die Abläufe erklärt,
misst Schritt 1a — es ist eine Vermutung, kein Befund.

## Schritte

### 1a — Confirm-Diagnose (dieser PR, umgesetzt)

Bei eingeschaltetem Long-Engine-Debug schreibt die Suite auf jeder bestätigten
Bar im Zustand Armed-ohne-Confirm
`LONG UNCONFIRMED | age=<Setup-Alter> | trigger_gap_pct=<Abstand Trigger in %> | failing=<…>`
mit allen scheiternden Bedingungen aus `compute_long_confirm_transition_state`:
`no_break`, `structure`, `not_fresh`, `bearish_guard`, `micro_session`,
`micro_freshness`, `accel`, `second_derivative`. Kein Einfluss auf Signale,
Plots oder Alerts. Pin: `tests/test_smc_core_engine_semantic_contract.py::test_confirm_diagnosis_log_names_every_failing_confirm_condition`.

Danach: Suite-Quelle auf TradingView speichern, `vWgAWyfC` mit
`tv_suite_publication_migration.ts` migrieren (Trockenlauf zuerst, außerhalb
der US-Handelszeit), Logs beider Sitzungen lesen. Eigentümer: die Sitzung, die
diesen PR landet (live).

### 1b — Confirm lockern (nach 1a, Betreiberentscheid)

Je nach Befund aus 1a, jeweils als eigene Variante gegen Armed gemessen:

| wenn 1a zeigt … | Variante |
|---|---|
| `not_fresh` dominiert ab Alter 3 | `Max Bars Armed -> Confirm` 2 → 6 (gleich der Frist) |
| `no_break` mit kleinem `trigger_gap_pct` | `Confirm Break Lookback` 3 → 2 (niedrigerer Trigger) |
| `accel` / `second_derivative` dominieren | beide aus Confirm nehmen, wie „Scoring over Blocking" bei Ready |

UNGESICHERT — verlässt sich auf menschliches Gedächtnis: 1b wartet auf die
Auswertung von 1a und die Entscheidung des Betreibers.

### 2 — Ready zuschneiden (Betreiberentscheid)

Statische Nachrechnung auf den 61 PENDING-Bars (Untergrenze: eine gelockerte
Bedingung verändert den weiteren Verlauf, den echten Effekt zeigt nur der
Tester):

| Variante | Ready von 61 |
|---|---|
| A: bestehender Schalter „Scoring over Blocking" (ohne `accel`, `second_derivative`, `vol_regime_context`, `stretch`, `ddvi`) | 0 |
| B: A ohne `quality` | 8 |
| C: B ohne `not_fresh` | 12 |
| D: C ohne `micro_freshness` | 12 |

Vorschlag: Ready als **Mindestzahl statt Und-Kette**. Hart bleiben die
risikobegrenzenden Bedingungen (`bar_gap`, `confirm_expired`, `bearish_guard`,
`setup_hard`, `overhead_zone`); die übrigen zählen als Punkte, Ready verlangt
„mindestens N". Best und Strict behalten ihre vollen Hürden. N wird auf
2023-09 bis 2025-12 festgelegt, 2026 bleibt für einen einzigen Test unberührt.

Werkzeuglücke: `tv_strategy_report_readout.ts` schaltet nur die Stufe der
Strategy um, keine Suite-Inputs. Für A–D braucht er eine Option, die
Suite-Inputs nur in der Sitzung setzt, ohne Speichern; ob solche Änderungen
ohne Speichern nicht dauerhaft werden, ist ungemessen.

UNGESICHERT — verlässt sich auf menschliches Gedächtnis: Schritt 2 wartet auf
die Entscheidung des Betreibers.
