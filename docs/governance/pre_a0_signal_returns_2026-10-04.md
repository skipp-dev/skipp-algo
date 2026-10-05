# Verdient ein PRE-A0-Signal nach dem Spread Geld? Messung 2026-10-04

Stand 2026-10-04. Owner-Freigabe vom selben Tag für den Abruf der
Shadow-Snapshots und für die Handelsdefinition. Eine Rückschau über 53
Sitzungen, kein Track Record.

## Frage

PRE-A0 ist das einzige Stück des Projekts mit belegter Vorhersagekraft: es
sagt voraus, dass binnen 30/60/180 **Sekunden** ein A0-Alarm bestätigt wird
(Kursbewegung gegen den Vortagesschluss über der Schwelle bei mindestens
dreifachem Volumentempo), und es nennt eine Richtung
(`docs/pre_a0_rollout_runbook.md`). Auf Ertrag war es nie gemessen. Trägt die
Vorwarnung einen handelbaren Vorteil?

## Regel, vor dem ersten Kurs festgelegt

Im Kopf von `pre_a0_returns.py` niedergelegt, bevor ein Quote abgerufen war:

- **Signal:** der erste Snapshot einer Episode im Zustand `IMMINENT` (was der
  Pilot-Tailer meldet); `up` = long, `down` = short.
- **Einstieg:** erster Quote ab Signal + 2 s (höchstens + 7 s); long kauft zum
  Brief, short verkauft zum Geld.
- **Ausstieg:** nach 60 s, 180 s und 900 s zum Quote dieses Zeitpunkts (nicht
  älter als 30 s); long verkauft zum Geld, short kauft zum Brief. Kein
  Ausstieg nach 15:59:59 New York.
- **Kosten:** allein der Spread, über diese Preise. Keine Kommission, keine
  Leihgebühr. Brutto = Mitte zu Mitte auf denselben Quotes.
- **Gültiger Quote:** Geld > 0, Brief > Geld, Spanne höchstens 10 % der Mitte.
- **Primäre Prüfung, ohne Suche:** alle Signale, 180 s. Ein Vorteil gilt nur,
  wenn das Netto-Mittel ein 95 %-Intervall über gezogene Sitzungen hat, dessen
  untere Grenze über null liegt.
- **Sekundär, mit Suche:** Horizont × Seite × Drittel von `probability_180` ×
  Tageszeit; Suche in den Sitzungen bis 31.8., Bestätigung ab 1.9.

## Daten

- **Signale:** Volume des Railway-Dienstes `a0-fast-shadow`, abgerufen am
  2026-10-04 nach Runbook: 53 Sitzungen (2026-07-21 bis 2026-10-02),
  1 192 995 Snapshot-Zeilen, 4 483 Episoden, 892 Symbole. Daraus 1 895
  Signale in 341 Symbolen, 59 % short. 43 % fallen in die erste halbe
  Handelsstunde.
- **Quotes:** Databento `bbo-1s`, je Symbol und Sitzung vom ersten Signal bis
  15 min nach dem letzten; 1 323 Fenster. Vorregistrierte Quelle `EQUS.MINI`.
  Kosten laut `metadata.get_cost`: 0,00 USD.
- **Das Universum sind Kleinstwerte:** Medianpreis der bestätigten A0-Events
  1,27 USD, ein Zehntel unter 0,17 USD.
- 25 % der Signale folgt binnen 180 s ein bestätigter A0-Alarm derselben
  Richtung.

## Ergebnis (bps je Trade, 95 %-Intervall über Sitzungen)

Vorregistrierte Quelle `EQUS.MINI`; 874 der 1 895 Signale hatten dort einen
gültigen Einstiegs-Quote, Spanne beim Einstieg im Median 257 bps:

| Horizont | Trades | brutto (Mitte zu Mitte) | netto (nach Spread) |
|---|---|---|---|
| 60 s | 750 | +1 [−31; +32] | −304 [−345; −266] |
| **180 s (primär)** | 663 | +4 [−45; +42] | **−293 [−347; −248]** |
| 900 s | 631 | +5 [−101; +100] | −279 [−376; −193] |

**Primäre Prüfung: kein Vorteil.** Sekundär: 108 Zellen durchsucht, **kein
einziger Kandidat** (keine Zelle mit positivem Netto-Mittel in der Suche).
Long und Short getrennt: beide negativ (long −232, short −367 bei 180 s).

## Empfindlichkeit gegen die Quote-Quelle (nachträglich, nicht vorregistriert)

`EQUS.MINI` ist ein Teil-Feed, nicht der NBBO. Deshalb dieselbe Rechnung auf
dem Nasdaq-Buch (`XNAS.ITCH`) und auf dem je Sekunde besten Geld/Brief beider
Feeds:

| Quelle | Trades mit Einstieg | Spanne Median | 180 s brutto | 180 s netto |
|---|---|---|---|---|
| `EQUS.MINI` | 874 | 257 bps | +4 [−45; +42] | −293 [−347; −248] |
| `XNAS.ITCH` | 1 343 | 213 bps | −7 [−45; +22] | −274 [−314; −243] |
| bestes aus beiden | 1 817 | 192 bps | +5 [−22; +28] | −249 [−274; −225] |

Auf dem besten aus beiden bei 900 s: brutto +24 [−30; +77], netto −217
[−268; −162]; wieder 108 Zellen, kein Kandidat. Nach Preisband (nachträglich,
180 s): unter 1 USD netto −303, 1–5 USD −192, 5–20 USD −221, ab 20 USD −236.

## Ablesung

- **Vor Kosten liegt der Ertrag bei null** — auf allen drei Quellen, auf allen
  drei Horizonten. Das Signal sagt, DASS ein Titel die Alarmschwelle gleich
  überschreitet; daraus folgt keine Richtung für die Minuten danach. Ein
  Titel, der schon 20 % gelaufen ist, kann beides.
- **Die Spanne ist das Hundertfache dessen, was zu verdienen wäre.** Rund
  2 bis 2,6 % je Einstieg; ein Hin und Zurück kostet 250 bis 300 bps.
- **Der wahre NBBO ist enger als jede der drei Quellen.** Das verschiebt das
  Netto, nicht das Brutto: bei null brutto bleibt jede positive Spanne ein
  Verlust.
- PRE-A0 bleibt, was das Runbook sagt: eine Vorwarnung für die Aufmerksamkeit,
  kein Handelssignal.

## Was die Messung nicht trägt

- 53 Sitzungen, drei Modellstände (`71831770…` bis 3.8., `de97b74e…` bis
  21.8., `12db269a…` danach); der Zustand `IMMINENT` ist regelbasiert, die
  Wahrscheinlichkeit stammt vom jeweiligen Modell.
- Marktorders zur angezeigten Spitze; keine Aussage über Limit-Orders in der
  Spanne. Leerverkäufe sind in diesen Titeln oft nicht verfügbar; die
  Short-Zeilen sind eine Obergrenze dessen, was erreichbar wäre.
- Nur das erste `IMMINENT` je Episode. `WATCH`/`BUILDING` und spätere
  Snapshots sind nicht geprüft.

Skripte, Signale und Einzeltrades: `~/.claude/scripts/family-fill-analysis/`
(`pre_a0_returns.py`, `data/pre_a0/`, `results_pre_a0_2026-10-04_*.txt`,
`results_pre_a0_trades*.json`); nicht im Repo.
