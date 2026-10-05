# Themen-ETFs mit Montagskauf oder 1-%-Rückgang und Trailing Stop 5–8 %

Stand 2026-10-05. Auftrag des Operators vom selben Tag. Eine Rückschau, kein
Track Record. Anschluss an `one_percent_a_week_tqqq_2026-10-05.md`.

## Auswahl der ETFs

Gesucht: ETFs mit Titeln zu KI-Modell-Anbietern, Quantencomputern, Hardware
für KI und Quanten, Ausrüstung der Chipherstellung, Speicherchips, Rüstung und
rüstungsbezogenen Rohstoffen. Ausgewählt (US-gelistet, Thema laut Name und
Anbieter, größere und ältere bevorzugt), festgelegt vor dem Laden der Kurse:

| Thema | ETFs |
|---|---|
| KI / KI-Modell-Anbieter | AIQ, CHAT, AGIX (hält Anthropic und xAI direkt) |
| Quantencomputer | QTUM, WQTM |
| Hardware für KI und Quanten | SMH, SOXX |
| Ausrüstung Chipherstellung | EUV (Lithografie); sonst über SMH/SOXX |
| Speicherchips | DRAM |
| Rüstung | ITA, XAR, PPA, SHLD, EUAD, NATO |
| Rüstungsbezogene Rohstoffe | REMX, URA, URNM, DMAT, SETM |

Nicht aufgenommen: ARTY und IGPT (Ticker umbenannt, Historie unter altem
Ticker), DXYZ (geschlossener Fonds, kein ETF). Der Ticker SHLD gehörte bis 2018
Sears Holdings; verwendet ab Fondsstart 2023-09-12. WQTM, EUV und DRAM haben
weniger als 100 Wochen Daten und zählen in der Zusammenfassung nicht mit.

## Regel und Daten

Vorregistriert in `opaw_themes_prereg_2026-10-05.md`. Montag
Eröffnungskurs; **Sofort** = Kauf zur ersten Minute (2 bps), **1 %** =
Limit-Kauf 1 % darunter, gültig bis Wochenschluss. Ausstieg nur über den
Trailing Stop (5, 6, 7, 8 % unter dem Höchstkurs seit Kauf), auch über Wochen;
danach neuer Kauf erst am nächsten Montag. Minutenkerzen von Databento aus
Nasdaq, NYSE Arca und Cboe BZX zusammengeführt (Kosten 0,00 USD), 2018-05
bzw. ab Fondsstart bis 2026-10-02. Voller Einsatz, Konto startet bei 1,00.

## Ergebnis: Endkonto und größter Rückgang (2 bps je Market-Order)

| ETF | Thema | Wochen | Halten | Sofort 5 % | Sofort 6 % | Sofort 7 % | Sofort 8 % | 1 % + 5 % | 1 % + 6 % | 1 % + 7 % | 1 % + 8 % |
|---|---|---|---|---|---|---|---|---|---|---|---|
| AIQ | KI | 437 | 4,40 (−45 %) | 2,77 (−54 %) | 3,96 (−42 %) | 4,33 (−38 %) | 3,90 (−47 %) | 2,26 (−44 %) | 2,95 (−32 %) | 3,29 (−29 %) | 3,92 (−50 %) |
| CHAT | KI | 176 | 3,73 (−31 %) | 3,07 (−25 %) | 3,05 (−32 %) | 3,03 (−24 %) | 2,52 (−27 %) | 1,73 (−24 %) | 2,75 (−28 %) | 1,88 (−32 %) | 1,57 (−33 %) |
| AGIX | KI | 115 | 1,92 (−32 %) | 1,32 (−28 %) | 1,54 (−28 %) | 1,57 (−25 %) | 1,96 (−20 %) | 1,33 (−23 %) | 1,62 (−25 %) | 1,70 (−26 %) | 2,05 (−21 %) |
| QTUM | Quanten | 421 | 6,27 (−39 %) | 6,01 (−46 %) | 5,84 (−32 %) | 4,43 (−39 %) | 5,01 (−41 %) | 5,55 (−37 %) | 4,26 (−28 %) | 2,73 (−39 %) | 4,29 (−37 %) |
| WQTM * | Quanten | 51 | 1,09 (−29 %) | 0,93 (−26 %) | 0,93 (−30 %) | 0,76 (−34 %) | 0,75 (−41 %) | 0,88 (−24 %) | 0,83 (−29 %) | 0,87 (−32 %) | 0,75 (−40 %) |
| SMH | Halbleiter | 439 | 13,02 (−45 %) | 9,94 (−28 %) | 11,40 (−39 %) | 11,22 (−46 %) | 8,62 (−51 %) | 5,57 (−27 %) | 5,95 (−43 %) | 7,05 (−45 %) | 7,71 (−41 %) |
| SOXX | Halbleiter | 439 | 10,50 (−46 %) | 6,52 (−31 %) | 6,66 (−36 %) | 5,91 (−52 %) | 7,34 (−54 %) | 2,42 (−39 %) | 4,00 (−41 %) | 5,32 (−43 %) | 4,07 (−51 %) |
| EUV * | Chip-Ausrüstung | 21 | 1,03 (−35 %) | 0,92 (−27 %) | 0,87 (−30 %) | 0,95 (−30 %) | 0,92 (−33 %) | 1,04 (−19 %) | 1,06 (−18 %) | 1,12 (−23 %) | 1,02 (−28 %) |
| DRAM * | Speicher | 26 | 2,29 (−45 %) | 0,99 (−36 %) | 1,20 (−40 %) | 1,18 (−31 %) | 1,32 (−35 %) | 0,85 (−33 %) | 0,80 (−36 %) | 0,80 (−32 %) | 1,24 (−35 %) |
| ITA | Rüstung | 439 | 2,17 (−51 %) | 2,13 (−32 %) | 2,33 (−37 %) | 2,58 (−25 %) | 2,37 (−29 %) | 1,21 (−48 %) | 2,27 (−42 %) | 1,44 (−49 %) | 1,38 (−48 %) |
| XAR | Rüstung | 439 | 2,74 (−47 %) | 2,76 (−35 %) | 3,11 (−41 %) | 3,56 (−41 %) | 4,64 (−26 %) | 1,16 (−50 %) | 1,44 (−50 %) | 2,01 (−37 %) | 2,87 (−30 %) |
| PPA | Rüstung | 439 | 2,80 (−44 %) | 2,68 (−27 %) | 3,57 (−22 %) | 4,13 (−22 %) | 3,50 (−26 %) | 1,14 (−51 %) | 2,74 (−24 %) | 2,24 (−27 %) | 2,37 (−33 %) |
| SHLD | Rüstung | 159 | 2,43 (−25 %) | 1,92 (−25 %) | 2,74 (−15 %) | 2,46 (−25 %) | 2,86 (−22 %) | 1,68 (−17 %) | 1,68 (−30 %) | 1,87 (−30 %) | 2,27 (−25 %) |
| EUAD | Rüstung | 101 | 1,60 (−22 %) | 2,02 (−17 %) | 2,06 (−18 %) | 2,04 (−18 %) | 2,14 (−20 %) | 1,91 (−14 %) | 1,98 (−14 %) | 1,59 (−17 %) | 1,54 (−18 %) |
| NATO | Rüstung | 103 | 1,45 (−17 %) | 1,44 (−18 %) | 1,24 (−18 %) | 1,45 (−18 %) | 1,69 (−17 %) | 1,14 (−15 %) | 1,14 (−15 %) | 1,41 (−16 %) | 1,50 (−17 %) |
| REMX | Rohstoffe | 439 | 0,77 (−74 %) | 3,06 (−43 %) | 3,57 (−49 %) | 1,82 (−53 %) | 1,74 (−60 %) | 1,51 (−45 %) | 2,23 (−47 %) | 0,95 (−65 %) | 1,55 (−55 %) |
| URA | Rohstoffe | 439 | 3,01 (−52 %) | 5,16 (−32 %) | 3,93 (−34 %) | 3,98 (−39 %) | 3,31 (−43 %) | 1,99 (−33 %) | 1,89 (−31 %) | 1,82 (−36 %) | 2,69 (−40 %) |
| URNM | Rohstoffe | 356 | 3,77 (−52 %) | 13,59 (−29 %) | 9,52 (−30 %) | 4,62 (−43 %) | 7,56 (−44 %) | 3,09 (−38 %) | 5,07 (−33 %) | 3,75 (−36 %) | 7,24 (−37 %) |
| DMAT | Rohstoffe | 213 | 1,51 (−56 %) | 1,39 (−59 %) | 1,41 (−56 %) | 1,47 (−51 %) | 1,33 (−60 %) | 1,01 (−51 %) | 0,94 (−53 %) | 0,98 (−55 %) | 1,11 (−64 %) |
| SETM | Rohstoffe | 191 | 1,40 (−44 %) | 1,50 (−27 %) | 1,55 (−35 %) | 1,31 (−37 %) | 1,46 (−40 %) | 1,60 (−24 %) | 1,43 (−30 %) | 1,88 (−30 %) | 2,33 (−28 %) |

`*` = weniger als 100 Wochen, nicht in der Zusammenfassung.

## Die vorab festgelegten Fragen

**1. Hilft das Warten auf 1 % Rückgang?** Nein. Bei keiner Trailing-Weite
liegt der Vorteil gegenüber dem Sofortkauf bei auch nur einem der 17
auswertbaren ETFs sicher über null. Das Mittel ist bei 15 bis 16 der 17 ETFs
negativ, bei 10 von 68 Kombinationen sicher negativ (CHAT, SOXX, ITA, XAR,
PPA, SHLD, EUAD, URNM). Bei 10 bps Kosten dasselbe Bild.

**2. Ist die Trailing-Regel besser als Halten (Sharpe)?** Nicht belegt. Beim
Sofortkauf hat die Regel bei 10 bis 11 der 17 ETFs ein höheres Sharpe als das
Halten, aber nur bei 0 bis 2 ETFs mit Intervall über null (REMX, URNM bei
5–6 %, SHLD bei 8 %). Der größte Rückgang ist bei 11 bis 15 der 17 ETFs
kleiner. Bei 10 bps Kosten höheres Sharpe nur noch bei 5 bis 9 ETFs.

## Ablesung

- Der Trailing Stop wirkt wie eine Versicherung, und ihr Nutzen hängt am
  Verlauf des Themas, nicht an der Regel: Wo das Thema zwischendurch
  einbrach oder seitwärts lief (Seltene Erden REMX: Halten 0,77, Sofort + 5 %
  3,06; Uran URNM 3,77 gegen 13,59; Rüstung XAR, PPA), schützte er und
  brachte mehr. Wo das Thema stetig stieg (Halbleiter SMH 13,02 gegen
  8,6–11,4; KI CHAT, AGIX), kostete er Ertrag.
- Die Ergebnisse springen zwischen benachbarten Weiten (URNM: 13,6 / 9,5 /
  4,6 / 7,6 bei 5 / 6 / 7 / 8 %). Das spricht für Zufall im Pfad, nicht für
  eine „richtige" Weite.
- Das Warten auf 1 % schadet bei ungehebelten Themen-ETFs fast durchweg:
  man verpasst Wochen, die ohne Rücksetzer steigen.

## Was das nicht trägt

- Die ETFs eines Themas laufen fast gleich; 17 ETFs sind keine 17
  unabhängigen Bestätigungen.
- DMAT und NATO handeln nur 10 bzw. 21 Minuten pro Tag; ihre Eröffnung und
  Stop-Auslösung sind grob gemessen. Ein Ausreißer bei URNM (+8,3 % am
  2020-01-24, 09:30) ist nicht entfernt.
- Kosten pauschal; kleine ETFs haben Spannen über 10 bps.

Skripte und Ergebnisse: `~/.claude/scripts/family-fill-analysis/`
(`opaw_themes_prereg_2026-10-05.md`, `opaw_themes.py`,
`results_opaw_themes_{2,10}bps_2026-10-05.{txt,csv}`); nicht im Repo.
