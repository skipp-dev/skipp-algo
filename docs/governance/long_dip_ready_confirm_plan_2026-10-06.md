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

#### Ergebnis 1a (2026-10-06)

Suite v436 (Quelle `bf195d114e6e`) auf `vWgAWyfC`, migriert 07:17 UTC, gelesen
07:25–07:42 UTC, dieselben fünf Symbole und Sitzungen wie oben.

Scheiternde Confirm-Bedingungen über alle Armed-ohne-Confirm-Bars:

| Bedingung | ETH (1 872 Bars) | RTH (1 313 Bars) |
|---|---|---|
| `structure` | 1 797 | 1 228 |
| `no_break` | 1 391 | 987 |
| `not_fresh` | 1 303 | 917 |
| `micro_freshness` | 574 | 385 |
| `bearish_guard` | 216 | 226 |
| `accel`, `second_derivative`, `micro_session` | 0 | 0 |

Im Confirm-Fenster (Setup-Alter 1 und 2, danach greift `not_fresh`):

| Alter | Bars ETH | davon `structure` | davon `no_break` | Bars RTH | davon `structure` | davon `no_break` |
|---|---|---|---|---|---|---|
| 1 | 292 | 287 | 225 | 203 | 194 | 164 |
| 2 | 277 | 270 | 201 | 193 | 180 | 141 |

Setups, die zusätzlich Confirmed werden könnten, wenn Bedingungen entfielen
(statisch je Setup: mindestens eine Bar mit Alter ≥ 1, an der nur entfallene
Bedingungen scheitern; Untergrenze wie bei Ready):

| entfällt | ETH (318 Setups) | RTH (218 Setups) |
|---|---|---|
| `not_fresh` | 4 | 1 |
| `structure` | 80 | 51 |
| `structure` + `not_fresh` | 98 | 65 |
| `structure` + `not_fresh` + `micro_freshness` | 138 | 82 |

`structure` ist `long_confirm_structure_ok`: mit
`Require Internal Break For Confirm` = true (auf dem Chart über die Chart-API gelesen: `in_105` = true) und
`Structure Mode` = „Internal CHoCH only" verlangt Confirm einen internen
bullischen CHoCH seit dem Arming. Das Zeitfenster allein (`not_fresh`) erklärt
die Abläufe nicht.

Nebenbefund: der Eingabe-Leser von `tv_suite_publication_migration.ts`
(Einstellungsdialog) ordnet bei zwei Checkboxen in einer Zeile den Wert falsch
zu (er meldete `Require Internal Break For Confirm` = false und
`Live Confirm Uses High` = false; die Chart-API zeigt beide true). Die Migrations-Prüfung
vergleicht vorher/nachher mit demselben Leser und sieht eine Änderung am ersten
Wert eines solchen Paars deshalb nicht. UNGESICHERT — verlässt sich auf
menschliches Gedächtnis: Umstellung des Lesers auf `getInputValues()`.

### 1b — Confirm lockern (Betreiberentscheid)

Nach dem Ergebnis von 1a, jeweils als eigene Variante gegen Armed gemessen:

| Variante | bestehender Input |
|---|---|
| Struktur auch per internem BOS | `Structure Mode` → „Internal CHoCH or BOS" |
| keine Struktur-Pflicht für Confirm | `Require Internal Break For Confirm` → false (Preset „Easy" tut das) |
| zusätzlich längeres Fenster | `Max Bars Armed -> Confirm` 2 → 6 |

Die erste Variante lässt sich aus dem Log nicht vorrechnen (er enthält keinen
BOS-Zeitpunkt); sie braucht den Tester.

#### Ergebnis 1b (2026-10-06, Betreiber: alle drei messen)

Gemessen im Tester auf `vWgAWyfC` (Suite v436), reguläre Handelszeit,
2023-09-01 bis 2026-10-05/06, fünf Symbole, 15 Minuten. Die Varianten wurden
nur in der Sitzung gesetzt (`--suite-input`, #5695), nie gespeichert; eine
frische Sitzung las danach die gespeicherten Werte unverändert (`in_105` true,
`in_72` 2, `in_109` „Internal CHoCH only"). Bewertung wie im Bericht vom
2026-10-04: 5 bps je Trade, Intervall über gezogene Einstiegstage, Placebo je
Trade 200 Zufallseinstiege.

| Variante | Confirmed-Trades (Tage) | netto bps, 95 % KI | Überschuss ggü. Placebo, 95 % KI | Ready / Best / Strict |
|---|---|---|---|---|
| gespeichert (Grundlinie) | 1 (1) | −227.8 | −22.5 | 0 / 0 / 0 |
| V1 `Structure Mode` → „Internal CHoCH or BOS" | 21 (9) | −16.2 [−82.8; +21.2] | −13.1 [−79.9; +25.9] | 0 / 0 / 0 |
| V2 `Require Internal Break For Confirm` → false | 75 (53) | +9.2 [−19.4; +36.5] | +10.1 [−19.8; +37.2] | 0 / 0 / 0 |
| V3 = V2 + `Max Bars Armed -> Confirm` 2 → 6 | 94 (69) | +4.1 [−20.2; +27.4] | +4.3 [−19.7; +27.6] | 0 / 0 / 0 |
| Maßstab: Armed (Grundlinie) | 167 (132) | +10.8 [−10.7; +35.3] | +8.4 [−13.6; +32.5] | – |

Keine Variante schlägt Armed, keine erreicht Ready. Confirm zu lockern löst
den Engpass nicht; die gespeicherten Werte bleiben (Betreiber 2026-10-06: V1
nicht übernehmen). Nicht gemessen: erweiterte Handelszeit (der Report setzte
sich bei laufender Vorbörse nicht) und die Pine-Logs der Varianten (Netzausfall
während des Laufs). UNGESICHERT — verlässt sich auf menschliches Gedächtnis.

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

Werkzeug (Stand 2026-10-06): `--suite-input` setzt Suite-Inputs nur in der
Sitzung; gemessen nicht dauerhaft (frische Sitzung liest den gespeicherten Wert).

Nach 1b bleibt Schritt 2 die offene Option (Betreiber 2026-10-06: „behalte
diese Option"). Die Werkzeuglücke ist geschlossen (#5695: `--suite-input`);
ein Mindestzahl-Zuschnitt braucht dagegen eine Änderung der Suite selbst.

UNGESICHERT — verlässt sich auf menschliches Gedächtnis: Schritt 2 ist
zurückgestellt und wartet auf die Entscheidung des Betreibers.
