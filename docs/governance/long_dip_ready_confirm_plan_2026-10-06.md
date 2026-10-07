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
Wert eines solchen Paars deshalb nicht. Erledigt mit #5719 (2026-10-07): der
Leser liest `getInputValues()` + `getInputsInfo()`; live bestätigt (Suite 234
Inputs = Zahl der `input()`-Aufrufe, `in_105..in_108` true/false/true/false,
108 Quell-Inputs = bekannte Bindungen).

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
nicht übernehmen). Erweiterte Handelszeit und Pine-Logs der Varianten sind am
2026-10-07 (00–08 UTC, ohne Live-Kerzen) nachgemessen, siehe unten.

#### Nachmessung 1b (2026-10-07): erweiterte Handelszeit und Logs

Tester, Sitzung des Layouts (ETH, Historie je Symbol ab März bis Juli 2025),
sonst wie oben:

| Variante | Confirmed-Trades (Tage) | netto bps, 95 % KI | Überschuss ggü. Placebo, 95 % KI | Ready / Best / Strict |
|---|---|---|---|---|
| gespeichert (Grundlinie) | 29 (8) | +2.5 [−10.2; +25.4] | +2.6 [−10.7; +22.0] | 0 / 0 / 0 |
| V1 | 75 (27) | −8.0 [−24.4; +6.1] | −3.7 [−18.7; +7.6] | 0 / 0 / 0 |
| V2 | 166 (72) | +0.4 [−11.6; +12.5] | −2.0 [−14.4; +9.3] | 0 / 0 / 0 |
| V3 | 191 (89) | −1.1 [−13.5; +11.7] | −2.3 [−15.5; +10.5] | 0 / 0 / 0 |
| Maßstab: Armed (Grundlinie) | 271 (141) | −0.2 [−13.1; +14.6] | −1.7 [−14.6; +12.3] | – |

Pine-Logs (LONG UNCONFIRMED / LONG PENDING) der Varianten:

| Variante / Sitzung | Armed | Confirmed | Bars Armed-ohne-Confirm | häufigste Confirm-Hürde | PENDING-Bars | Ready |
|---|---|---|---|---|---|---|
| gespeichert / ETH | 318 | 8 | 1 872 | `structure` 96 % | 54 | 0 |
| V1 / ETH | 318 | 27 | 1 763 | `structure` 91 % | 186 | 0 |
| V2 / ETH | 317 | 86 | 1 435 | `no_break` 88 % | 577 | 0 |
| V3 / ETH | 317 | 111 | 1 357 | `no_break` 92 % | 739 | 0 |
| gespeichert / RTH | 218 | 1 | 1 313 | `structure` 94 % | 7 | 0 |
| V1 / RTH | 218 | 9 | 1 273 | `structure` 89 % | 56 | 0 |
| V2 / RTH | 217 | 52 | 1 033 | `no_break` 88 % | 344 | 0 |
| V3 / RTH | 217 | 67 | 990 | `no_break` 91 % | 442 | 0 |

Ohne Struktur-Pflicht scheitert Confirm fast nur noch am Ausbruch über den
Trigger; Confirmed vervielfacht sich, Ready bleibt bei jedem Lauf 0. Das Urteil
oben gilt in beiden Sitzungen.

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

Nach 1b blieb Schritt 2 die offene Option (Betreiber 2026-10-06: „behalte
diese Option"), dann „Dann mach das".

#### Umsetzung (#5706)

Zwei Suite-Inputs, Standard aus (= unveränderte Und-Kette der Library):
`Ready: Min-Count instead of AND chain` und `Ready: Min Soft Gates (of 12)`.
Eingeschaltet bleiben hart: Bar geschlossen, Confirmed, `bar_gap`, nicht
`confirm_expired`, `bearish_guard`, `setup_hard`, `overhead_zone`,
`event_risk` (gegenüber dem Vorschlag zusätzlich, weil es Risiko begrenzt) und
der Haupt-BOS, falls verlangt. Als Punkte zählen `ready_is_fresh`,
`session_structure`, `micro_session`, `micro_freshness`, `market_regime`,
`vola_regime`, `quality`, `accel`, `second_derivative`, `vol_regime_context`,
`stretch`, `ddvi`. Der LONG-PENDING-Log nennt `soft_met`. Pin:
`tests/test_smc_core_engine_semantic_contract.py::test_ready_min_count_is_opt_in_and_keeps_the_risk_gates_hard`.

#### Ergebnis Schritt 2 (2026-10-06)

Suite v446 (Quelle `f5688756e3ed`, main nach #5709) auf `vWgAWyfC`, migriert
mit `--accept-new-suite-input` (#5707): 0 Abweichungen, alle acht Instanzen
zurück. Tester, reguläre Handelszeit 2023-09 bis 2026-10, fünf Symbole, 15
Minuten; Min-Count nur in der Sitzung eingeschaltet. Die TradingView-Workflows
waren dafür auf Betreiberentscheid von 18:38 bis 21:49 UTC pausiert (ein
Konto erlaubt nur eine Sitzung).

| Confirm | N | Ready-Trades | netto bps, 95 % KI | Überschuss ggü. Placebo | bis 2025: n / bps | 2026: n / bps | Best / Strict |
|---|---|---|---|---|---|---|---|
| gespeichert | 12, 10, 8, 6 | 0 | – | – | – | – | 0 / 0 |
| V3 | 12 | 0 | – | – | – | – | 0 / 0 |
| V3 | 10 | 6 | −46.2 [−123.2; +39.8] | −80.1 [−125.7; −34.5] | 5 / −35.2 | 1 / −100.9 | 0 / 0 |
| V3 | 8 | 33 | +1.8 [−38.9; +43.1] | −3.5 [−45.0; +36.3] | 31 / +2.6 | 2 / −10.3 | 0 / 0 |
| V3 | 6 | 68 | −6.8 [−34.3; +17.8] | −5.1 [−32.5; +19.5] | 60 / −5.4 | 8 / −17.6 | 0 / 0 |
| Maßstab Armed | – | 167 | +10.8 [−10.7; +35.3] | +8.4 [−13.6; +32.5] | 132 / +17.3 | 35 / −13.5 | – |

- Mit gespeichertem Confirm entsteht bei keinem N ein Ready: Confirm ist der
  vorgelagerte Engpass (1b).
- Bester Wert im Auswahlzeitraum bis 2025 ist N = 8 mit +2.6 bps (31 Trades),
  deutlich unter Armed im selben Zeitraum (+17.3 bps, 132 Trades); im
  Prüfzeitraum 2026 sind es 2 Trades — zu wenig für ein Urteil.
- Best und Strict bleiben bei 0, auch wenn Ready handelt.

Urteil: Ready als Mindestzahl erzeugt Trades, aber keinen Vorteil gegenüber
Armed. Der Schalter bleibt aus (Standard); am Produkt ändert sich nichts.
