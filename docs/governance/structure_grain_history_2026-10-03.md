# Rückschau: alle Mess-Definitionen auf der Databento-Historie 2023–2026

Stand 2026-10-03. Gerechnet am 2026-10-03 mit dem Pipeline-Code auf
`main` (b9ea37976, ADR-0031 bis Nachtrag IV). Eine Rückschau, kein Track
Record: alle Trades liegen vor dem Evidenz-Start (2026-10-05), und der Detektor
sah zusammenhängende Jahre statt der rollenden 22-Tage-Fenster der Pipeline.

## Frage

Der Track Record misst Struktur mit 1-Kerzen-Pivots; die Pine-Engine arbeitet
mit Swing 50. Die Rückschau vom 2026-10-02 (10.8.–2.10., ein Regime) fand
keine Körnung positiv. Hält das über drei Jahre und mehrere Regime? Und wie
stehen OB, FVG und SWEEP über dieselbe Zeit?

## Daten und Weg

- **Kerzen:** Databento `EQUS.MINI`, Schema `ohlcv-1m`, 2023-03-28 (Beginn
  des Datensatzes) bis 2026-08-10, dazu die bereits vorhandenen Kerzen bis
  2026-10-02. 24 Symbole des Mess-Universums. Kosten laut
  `metadata.get_cost` vor dem Abruf: 0,00 USD (476 MB, 8,5 Mio. Zeilen).
- **Weg:** je Symbol und Kalenderjahr (plus 30 Tage Kontext davor)
  `build_explicit_structure_from_bars(…, "15m", pivot_lookup=1)` für alle vier
  Familien und `pivot_lookup=50` für BOS; `family_events_from_structure`
  (Vorwärtsfenster, Eröffnungskurse); `realized_return` unter
  `next_open_then_horizon_close`, 5 bps; Intervall über gezogene UTC-Tage
  (`_day_clustered_mean`, B = 2000). Börsengerechte 15m-Kerzen (Nachtrag III).
- **SWEEP getrennt:** das Profil `hybrid_default` behält je Durchlauf nur die
  100 jüngsten Sweeps. In Jahres-Chunks blieben davon ~13 Tage je Jahr; die
  Sweeps sind deshalb in 10-Tage-Fenstern (30 Tage Kontext) nachgerechnet, in
  denen die Kappung nicht greift.
- Skripte und Rohdaten: `~/.claude/scripts/family-fill-analysis/`
  (`pull_history.py`, `history_retro.py`, `history_sweeps.py`,
  `results_history_2026-10-03.txt`, `results_history_sweeps_2026-10-03.txt`,
  je Trade in `results_history_2026-10-03.json`). Nicht im Repo: 476 MB
  Kerzen und 390 824 Einzeltrades.

## Ergebnis: bps je Trade, 95 %-Intervall über Tage

| Definition | Familie | Jahr | Trades | Tage | Mittel |
|---|---|---|---|---|---|
| Pivot 1 | BOS | 2023 | 23 102 | 208 | −4,0 [−5,5; −2,5] |
| Pivot 1 | BOS | 2024 | 31 969 | 286 | −4,4 [−5,8; −3,1] |
| Pivot 1 | BOS | 2025 | 33 818 | 283 | −4,1 [−6,0; −2,2] |
| Pivot 1 | BOS | 2026 | 23 202 | 207 | −6,9 [−8,7; −5,1] |
| Pivot 1 | BOS | alle | 112 091 | 984 | **−4,7 [−5,6; −3,9]** |
| Pivot 1 | OB | 2023 | 14 073 | 192 | −3,8 [−4,9; −2,7] |
| Pivot 1 | OB | 2024 | 19 080 | 256 | −5,2 [−6,4; −4,1] |
| Pivot 1 | OB | 2025 | 20 096 | 252 | −5,6 [−7,0; −4,3] |
| Pivot 1 | OB | 2026 | 13 534 | 187 | −5,8 [−7,2; −4,4] |
| Pivot 1 | OB | alle | 66 783 | 887 | **−5,2 [−5,8; −4,5]** |
| Pivot 1 | FVG | 2023 | 38 183 | 214 | −4,5 [−5,5; −3,6] |
| Pivot 1 | FVG | 2024 | 54 444 | 291 | −5,1 [−6,0; −4,3] |
| Pivot 1 | FVG | 2025 | 58 767 | 283 | −3,8 [−4,8; −2,8] |
| Pivot 1 | FVG | 2026 | 39 269 | 203 | −4,8 [−6,0; −3,7] |
| Pivot 1 | FVG | alle | 190 663 | 991 | **−4,5 [−5,0; −4,0]** |
| Pivot 1 | SWEEP | 2023 | 44 231 | 178 | −5,3 [−5,9; −4,7] |
| Pivot 1 | SWEEP | 2024 | 66 381 | 264 | −4,5 [−5,2; −3,7] |
| Pivot 1 | SWEEP | 2025 | 68 027 | 264 | −5,0 [−5,8; −4,2] |
| Pivot 1 | SWEEP | 2026 | 49 153 | 190 | −4,7 [−5,5; −3,9] |
| Pivot 1 | SWEEP | alle | 227 792 | 896 | **−4,8 [−5,2; −4,4]** |
| Pivot 50 | BOS | 2023 | 2 347 | 189 | −1,8 [−6,2; +2,6] |
| Pivot 50 | BOS | 2024 | 3 336 | 253 | −3,6 [−7,1; −0,2] |
| Pivot 50 | BOS | 2025 | 3 746 | 255 | −1,9 [−6,4; +2,8] |
| Pivot 50 | BOS | 2026 | 2 594 | 189 | −5,7 [−10,7; −0,5] |
| Pivot 50 | BOS | alle | 12 023 | 886 | **−3,2 [−5,4; −0,9]** |

## Ablesung

- **Keine Familie, keine Körnung, kein Jahr ist nach Kosten positiv.** Für
  Pivot 1 liegt die obere Intervallgrenze in allen 20 Zellen unter null; die
  Mittel liegen eng beieinander (−4 bis −7 bps) und nahe den Kosten (5 bps):
  vor Kosten liegen die Trades um null.
- **Das grobe Korn verliert weniger je Trade** (−3,2 gegen −4,7 bps über alles,
  Intervalle überlappen nicht ganz) **und ist trotzdem nicht positiv**; in
  2023 und 2025 schließt sein Intervall die Null ein, 2026 ist es das
  schlechteste Jahr. Das ist die vorwärts zu prüfende Spanne: nicht „Edge
  oder kein Edge", sondern „−3 bps oder null". Mit rund 10 Trades je Tag
  über 24 Symbole braucht die grobe Bilanz viele Handelstage, bis ihr
  Intervall diese Frage trennt.
- **Die Stichprobe vom September war typisch, nicht ein schlechter Monat:**
  10.8.–2.10. ergab −8,2 (BOS) bzw. −11,0 (BOS grob); 2026 insgesamt ist das
  schwächste Jahr beider Definitionen.
- **Positivkontrolle:** die Pipeline-Ablesung auf dem Börsenraster vom 2.10.
  (`15m/track_record_gate_2026-10-02.json`, 4 Tage) liegt mit −10,6 (BOS),
  −6,3 (OB), −7,0 (FVG), −4,4 (SWEEP) innerhalb bzw. am Rand der Jahreswerte.

## Was die Rückschau nicht trägt

- **Fensterform.** Die Pipeline rechnet rollende 22-Tage-Fenster; der Detektor
  ist zustandsbehaftet (Strukturrichtung aus den letzten Pivots, Sweep-Linien
  nur im Fenster). Zusammenhängende Jahre kennen mehr Pivots und ältere
  Linien. Die Ereignismengen sind deshalb ähnlich, nicht identisch.
- **Kursquelle.** EQUS.MINI ist ein konsolidiertes Mini-Feed-Sample; die
  Produktion liest ihre eigenen Databento-Exporte. Einzelne Kerzen können
  abweichen.
- **Kosten.** 5 bps rund um die Uhr; die §5-Kostenkalibrierung ist nicht
  eingerechnet.
- **Pine-Engine.** Oben gemessen ist nur ihre Pivot-Körnung; HH/LH/HL/LL,
  Strong/Weak und Trend-Stack misst der Nachtrag unten.
- **NVDA-Split (10.6.2024, 10:1).** Die 1m-Historie von EQUS.MINI ist
  nicht split-bereinigt. Die erste Fassung dieser Tabelle enthielt dadurch
  einen Pivot-1-Trade mit −9 011 bps (NVDA, 7.6.2024). Die Tabelle oben ist
  bereinigt neu gerechnet (Kurse vor dem Split ÷ 10, Volumen × 10; über alle
  24 Symbole der einzige Sprung außerhalb 0,7–1,4 von Tag zu Tag).
  Geändert: Pivot 1 BOS 2024 −4,7 → −4,4, alle −4,8 → −4,7; Pivot 50 BOS
  2024 −3,7 → −3,6; sonst nur Trade-Zahlen um wenige Trades. Keine Aussage
  ändert sich.

## Nachtrag 2026-10-03: die Engine selbst

**Frage.** Trägt die Struktur-Engine der Suite
(`SMC++/smc_engine_private.pine`, `detect_structure`) über ihre
Pivot-Körnung hinaus etwas: Strukturbrüche, Swing-Labels HH/LH/HL/LL,
Strong/Weak-Levels, Trend-Stack 4H/1D/1W?

**Weg.** Python-Nachbau von `detect_swings` / `detect_pivot` /
`detect_structure`, verdrahtet wie `SMC_Long_Dip_Suite.pine`: Swing-Struktur
Länge 50, Internal-Struktur Länge 5 mit den Swing-Levels als `super`-Level,
beide mit `filter_insignificant_internal_breaks = true`. Labels wie
`plot_pivot_points`, Strong/Weak wie `plot_swing_levels`, Trend-Stack wie
`get_confirmed_structure_trend` (Anzeige-Trend der VORHERIGEN Kerze der
höheren Zeitebene, Länge 50; 4H auf NY-Uhr ab 04:00, 1D aus RTH, 1W aus 1D;
Vorlauf vor 2023-03-28 aus Tageskursen). Dieselben Kerzen wie oben,
börsengerechte 15m, NVDA bereinigt. Ertrag wie im Track Record: Entscheidung
mit dem Schluss der Signalkerze, Einstieg zur nächsten Eröffnung, Ausstieg
nach 8 Kerzen (BOS-Haltedauer), 5 bps; Intervall über gezogene UTC-Tage.
Positivkontrolle: dieselbe Ertragsrechnung gegen
`family_events_from_structure` + `realized_return` auf den groben
BOS-Events von AAPL — 0 von 317 Trades weichen ab.

**Ergebnis (bps je Trade, netto, 95 %-Intervall über Tage):**

| Baustein | Trades | Mittel |
|---|---|---|
| Swing-Brüche (BOS + CHoCH, beide Seiten) | 3 547 | +0,2 [−3,9; +4,5] |
| Internal-Brüche | 27 375 | −4,2 [−5,8; −2,8] |
| Swing HH (long) / HL (long) | 2 664 / 2 857 | −2,3 / −2,6 |
| Swing LH (short) / LL (short) | 2 483 / 2 280 | −12,4 / −9,3 |
| Internal-Labels, alle vier | 95 544 | −4,9 [−5,6; −4,1] |
| Handel Richtung schwaches Level (Swing) | 13 190 | −6,0 [−7,9; −4,2] |

- **Strukturbrüche:** Swing-Brüche verdienen vor Kosten etwa die Kosten
  (besser als Pivot 1 mit −4,7), sind aber in keinem Jahr positiv; auf
  einem reinen RTH-Chart −4 bis −11 je Signal.
- **HH/LH/HL/LL:** keine Richtungsinformation. Long-Labels liegen brutto
  bei +2 bis +3 bps — das ist die Marktdrift (jede Kerze long: +1,7
  brutto); Short-Labels verlieren entsprechend.
- **Strong/Weak:** Das schwache Level wird in 66,5 % der Fälle zuerst
  erreicht; ein richtungsloser Zufallslauf ergäbe bei denselben Abständen
  67,1 % (Differenz −0,6 pp [−1,3; +0,2]; Internal −0,7 [−1,1; −0,3]). Die
  Namen beschreiben den Abstand zum Kurs, keine Haltekraft.
- **Trend-Zustand:** jede Kerze in Richtung des Engine-Trends: brutto
  −0,4 [−1,1; +0,4].
- **Trend-Stack:** „≥ 2 von 3 bullisch" verbessert nichts — jede Kerze
  long brutto +1,3 bei Stack ≥ 2, +2,7 bei Stack < 2; bullische
  Swing-Brüche mit Stack ≥ 2 netto −1,1 [−7,0; +5,1].
- Zwei von rund 80 abgelesenen Zellen sind positiv (bullische Swing-Brüche
  bei Stack 0: +22,6 [+3,0; +41,9], 117 Trades; bullische Internal-CHoCH
  über 32 Kerzen: +7,4 [+1,0; +14,1]) — im Rahmen des Zufalls bei so vielen
  Zellen, und nicht vorab benannt.

**Ablesung.** Kein Baustein der Engine ist nach Kosten positiv; keiner
trägt Richtungsinformation über die Marktdrift hinaus. „Die Engine ist
besser als der Track Record" bleibt unbelegt.

**Was der Nachtrag nicht trägt.**

- Der Nachbau ist nicht gegen TradingView geprüft (kein Compiler); die
  Logik ist zeilenweise aus dem Pine-Quelltext übertragen.
- Die Long-Dip-Einstiege (Zustandsmaschine Armed → Confirmed → Ready →
  Entry Best/Strict mit allen Gates) sind NICHT gemessen; das Urteil gilt
  für die Struktur-Bausteine, auf denen sie aufsetzt.
- Rückschau, kein Track Record; Kosten wie oben 5 bps.
- Skript und Rohdaten außerhalb des Repos:
  `~/.claude/scripts/family-fill-analysis/engine_retro.py`,
  `results_engine_2026-10-03.txt`, je Signal in
  `results_engine_2026-10-03.parquet`.

Verwandt: ADR-0031 (Nachträge II–IV),
`docs/governance/variant_a_entry_price_measurement_2026-10-02.md`,
`docs/calibration/gates/README.md`.
