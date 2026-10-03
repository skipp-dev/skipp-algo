# Trennen die eigenen Merkmale gute von schlechten Events? Historie 2023–2026

Stand 2026-10-03. Ergänzt
`docs/governance/structure_grain_history_2026-10-03.md` (dieselben Daten,
derselbe Codepfad, dieselbe Regel). Eine Rückschau, kein Track Record.

## Frage

Die Rückschau über die Historie fand keine Familie und keine Körnung nach
Kosten positiv. Offen blieb, ob eine Teilmenge der Events positiv ist — ob
also eines der Merkmale, die die Pipeline jedem Event zum Ankerzeitpunkt
mitgibt, die guten von den schlechten trennt.

## Regel, vor dem ersten Lauf festgelegt

Im Kopf von `history_features.py` niedergelegt, bevor ein Ergebnis vorlag:

- **Merkmale:** was `family_events_from_structure` am Anker anhängt — `score`
  (ATR-normierte Geometrie-Stärke), `relative_volume`, `vrvp_vpoc_dist`,
  `vrvp_va_pos` (je Fünftel) sowie `regime` und Richtung (je Kategorie).
- **Suche:** Anker in 2023 und 2024. **Bestätigung:** Anker in 2025 und 2026,
  mit den Schwellen aus der Suche.
- **Kandidat:** eine Zelle (Definition × Merkmal × Fünftel/Kategorie) mit
  Netto-Mittel über null bei mindestens 300 Trades in der Suche.
- **Bestätigt:** nur wenn das Netto-Mittel in der Bestätigung ein
  95 %-Intervall über gezogene Tage hat, dessen untere Grenze über null liegt.

## Ergebnis

609 352 Trades (Suche 297 146, Bestätigung 312 206), alle Merkmale zu 100 %
belegt.

- **120 Zellen durchsucht, 2 Kandidaten, 0 bestätigt.**

| Definition | Zelle | Suche | Bestätigung |
|---|---|---|---|
| Pivot 50 BOS | `score`, oberstes Fünftel | 1 137 Trades, +2,2 bps | 1 347 Trades, −3,7 [−10,8; +3,9] |
| Pivot 50 BOS | `regime` = TRENDING | 1 693 Trades, +0,1 bps | 1 933 Trades, −3,0 [−9,3; +4,1] |

- **Spanne der Fünftel-Mittel (netto, alle Jahre, bps): bestes / schlechtestes**

| Definition | `score` | `relative_volume` | `vrvp_vpoc_dist` | `vrvp_va_pos` |
|---|---|---|---|---|
| Pivot 1 BOS | −3,7 / −5,7 | −3,4 / −5,4 | −3,5 / −5,6 | −3,7 / −5,4 |
| Pivot 1 OB | −3,9 / −6,1 | −3,5 / −6,4 | −4,5 / −6,3 | −4,6 / −5,4 |
| Pivot 1 FVG | −4,0 / −5,0 | −4,3 / −4,7 | −4,3 / −4,8 | −4,3 / −4,6 |
| Pivot 1 SWEEP | −3,5 / −5,9 | −4,0 / −5,2 | −4,6 / −5,4 | −4,6 / −4,9 |
| Pivot 50 BOS | −1,2 / −5,1 | +0,7 / −6,4 | +0,7 / −5,4 | −2,6 / −3,5 |

## Vor Kosten

Derselbe Bestand, Ertrag vor den 5 bps (bps je Trade; Streuung je Trade):

| Definition | Trades | brutto | Streuung | Trefferquote netto |
|---|---|---|---|---|
| Pivot 1 BOS | 112 092 | +0,17 | 98,6 | 46,0 % |
| Pivot 1 OB | 66 783 | −0,18 | 76,5 | 45,1 % |
| Pivot 1 FVG | 190 660 | +0,47 | 67,0 | 44,7 % |
| Pivot 1 SWEEP | 227 815 | +0,16 | 59,7 | 43,8 % |
| Pivot 50 BOS | 12 022 | +1,80 | 96,9 | 46,8 % |

Kein Symbol der 24 ist über alle Pivot-1-Familien netto positiv (−5,8 bis
−2,7 bps). Keine Sitzungsphase (Vorbörse, Eröffnung, Mitte, Schluss,
Nachbörse) erreicht brutto die 5 bps; am nächsten kommt Pivot 50 BOS in Vor-
und Nachbörse (+4,7 / +6,2 bei 1 733 / 1 016 Trades, dort sind 5 bps Kosten
zu niedrig angesetzt). BOS und CHoCH unterscheiden sich nicht.

## Ablesung

- Die Events tragen als Richtungssignal keine messbare Information: brutto
  liegen sie bei null, und zwar eng (über 600 000 Trades).
- Niedrigere Kosten ändern das Urteil nicht — schon bei 1 bp bliebe netto
  nichts.
- Die Merkmale der Pipeline verschieben das Mittel um 1 bis 2 bps, nicht um
  die 5 bis 6, die es bräuchte. Die beiden Kandidaten gehören zum groben BOS,
  dessen vorwärts laufende Bilanz (`ledger/returns_ledger_15m_p50.jsonl`)
  die Frage ohnehin offen hält; als Filter sind sie nicht bestätigt.
- Weitere Filter aus denselben Kerzendaten zu suchen erhöht ab hier vor allem
  die Zahl der Zufallstreffer.

## Was das nicht trägt

- Dieselben Vorbehalte wie die Rückschau: zusammenhängende Jahre statt
  22-Tage-Fenster, EQUS.MINI statt Produktions-Export, 5 bps pauschal.
- Nur die Merkmale, die ohne Tick-Daten entstehen. Orderflow-, Options- und
  Lead-Lag-Merkmale sind getrennt geprüft und null
  (`docs/governance/adr0019_magnitude_regime_ab_findings.md`,
  `adr0020_options_flow_ab_findings.md`,
  `adr0021_cross_asset_lead_lag_ab_findings.md`).
- Kombinationen von Merkmalen sind nicht durchsucht.

Skripte und Einzeltrades: `~/.claude/scripts/family-fill-analysis/`
(`history_features.py`, `results_history_features_2026-10-03.txt`,
`results_history_features_2026-10-03.json`); nicht im Repo.
