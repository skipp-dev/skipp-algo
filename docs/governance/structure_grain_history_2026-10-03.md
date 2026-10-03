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
  Kerzen und 390 821 Einzeltrades.

## Ergebnis: bps je Trade, 95 %-Intervall über Tage

| Definition | Familie | Jahr | Trades | Tage | Mittel |
|---|---|---|---|---|---|
| Pivot 1 | BOS | 2023 | 23 102 | 208 | −4,0 [−5,5; −2,5] |
| Pivot 1 | BOS | 2024 | 31 970 | 286 | −4,7 [−6,3; −3,2] |
| Pivot 1 | BOS | 2025 | 33 818 | 283 | −4,1 [−6,0; −2,2] |
| Pivot 1 | BOS | 2026 | 23 202 | 207 | −6,9 [−8,7; −5,1] |
| Pivot 1 | BOS | alle | 112 092 | 984 | **−4,8 [−5,7; −4,0]** |
| Pivot 1 | OB | 2023 | 14 073 | 192 | −3,8 [−4,9; −2,7] |
| Pivot 1 | OB | 2024 | 19 080 | 256 | −5,2 [−6,4; −4,1] |
| Pivot 1 | OB | 2025 | 20 096 | 252 | −5,6 [−7,0; −4,3] |
| Pivot 1 | OB | 2026 | 13 534 | 187 | −5,8 [−7,2; −4,4] |
| Pivot 1 | OB | alle | 66 783 | 887 | **−5,2 [−5,8; −4,5]** |
| Pivot 1 | FVG | 2023 | 38 183 | 214 | −4,5 [−5,5; −3,6] |
| Pivot 1 | FVG | 2024 | 54 441 | 291 | −5,1 [−6,0; −4,3] |
| Pivot 1 | FVG | 2025 | 58 767 | 283 | −3,8 [−4,8; −2,8] |
| Pivot 1 | FVG | 2026 | 39 269 | 203 | −4,8 [−6,0; −3,7] |
| Pivot 1 | FVG | alle | 190 660 | 991 | **−4,5 [−5,0; −4,0]** |
| Pivot 1 | SWEEP | 2023 | 44 247 | 178 | −5,3 [−5,9; −4,7] |
| Pivot 1 | SWEEP | 2024 | 66 388 | 264 | −4,5 [−5,2; −3,7] |
| Pivot 1 | SWEEP | 2025 | 68 027 | 264 | −5,0 [−5,8; −4,2] |
| Pivot 1 | SWEEP | 2026 | 49 153 | 190 | −4,7 [−5,5; −3,9] |
| Pivot 1 | SWEEP | alle | 227 815 | 896 | **−4,8 [−5,2; −4,4]** |
| Pivot 50 | BOS | 2023 | 2 347 | 189 | −1,8 [−6,2; +2,6] |
| Pivot 50 | BOS | 2024 | 3 335 | 253 | −3,7 [−7,1; −0,3] |
| Pivot 50 | BOS | 2025 | 3 746 | 255 | −1,9 [−6,4; +2,8] |
| Pivot 50 | BOS | 2026 | 2 594 | 189 | −5,7 [−10,7; −0,5] |
| Pivot 50 | BOS | alle | 12 022 | 886 | **−3,2 [−5,4; −0,9]** |

## Ablesung

- **Keine Familie, keine Körnung, kein Jahr ist nach Kosten positiv.** Für
  Pivot 1 liegt die obere Intervallgrenze in allen 20 Zellen unter null; die
  Mittel liegen eng beieinander (−4 bis −7 bps) und nahe den Kosten (5 bps):
  vor Kosten liegen die Trades um null.
- **Das grobe Korn verliert weniger je Trade** (−3,2 gegen −4,8 bps über alles,
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
- **Pine-Engine.** Gemessen ist ihre Pivot-Körnung, nicht HH/LH/HL/LL,
  Strong/Weak-Levels oder Trend-Stack.

Verwandt: ADR-0031 (Nachträge II–IV),
`docs/governance/variant_a_entry_price_measurement_2026-10-02.md`,
`docs/calibration/gates/README.md`.
