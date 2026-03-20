# SMC++ Dashboard Guide fuer Long-Dip Setups (DE)

## Zweck

Diese Dokumentation erklaert das SMC++-Dashboard in einfachem Deutsch.
Sie ist eine Arbeits- und Interpretationshilfe, kein alleinstehendes Kaufsignal.

Grundregel:

- Das Dashboard ist eine Ampel und Checkliste.
- Je mehr Felder zusammenpassen, desto sauberer ist ein Setup.
- Eine Zone allein ist kein Einstieg.

## Neueste Aenderungen (Maerz 2026)

Die juengsten SMC++-Updates haben vor allem vier Dinge geschaerft:

- Die `Watchlist` ist jetzt wieder bewusst generisch: Sie bedeutet nur, dass ein bullischer Trend plus eine aktive Pullback-Zone vorhanden sind.
- Alles Strenge dahinter ist jetzt quellenspezifisch: Reclaim-Sequenz, Armed/Confirmed-Tracking und Invalidierung folgen dem konkreten OB- oder FVG-Objekt, das das Setup traegt.
- Datenqualitaet wird klarer getrennt: fehlendes Volumen auf der aktuellen Kerze, schwache Feed-Qualitaet und fehlende LTF-Volumenbasis werden nicht mehr in einen Topf geworfen.
- Alerts und Dashboard sind enger synchronisiert: Ready- und Invalidated-Ereignisse nutzen gelatchte Event-States, und die Microstructure-Anzeige zeigt jetzt Hauptprofil plus aktive Modifier.

## Dashboard-Begriffe einfach erklaert

### Trend

Die aktuelle Marktstruktur des aktiven Charts.

- Bullish: Struktur eher aufwaerts
- Bearish: Struktur eher abwaerts
- Neutral: kein klarer Strukturvorteil

### HTF Trend

HTF bedeutet Higher Time Frame.
Das Feld zeigt, ob hoehere Zeitebenen den Trade unterstuetzen.

Beispiel:

`3:Bearish | 10:Bullish | 30:Bearish`

Das ist gemischt und fuer einen konservativen Long-Dip eher unguenstig.

### Pullback Zone

Zeigt, ob der Preis in einer moeglichen Reaktionszone liegt.

Typische Zustaende:

- In OB Zone
- In FVG Zone
- In OB + FVG Zone
- No Long Zone

Wichtig: Eine Zone bedeutet Beobachten, nicht Kaufen.

### Reclaim

Reclaim bedeutet, dass der Markt ein relevantes Level oder eine Zone zurueckerobert.
Fuer Longs ist das wichtig, weil es zeigt, dass Kaeufer wieder Kontrolle uebernehmen.

Positive Beispiele:

- OB Reclaimed
- FVG Reclaimed
- Internal Low Reclaimed
- Swing Low Reclaimed

Warnsignal:

- No Reclaim

### Long Setup

Der operative Zustand des Long-Setups.

- In Zone: interessanter Bereich, aber noch kein Entry
- Armed: Setup ist vorgemerkt
- Building: Struktur baut sich auf
- Confirmed: wichtige Bestaetigung liegt vor
- Ready: sauberes, fortgeschrittenes Setup
- Blocked oder Invalidated: Setup ist kaputt

### Setup Age

Wie alt ein bewaffnetes oder bestaetigtes Setup ist.

Beispiele:

- armed 2
- confirmed 1

Frische Signale sind meist besser als alte.

### Long Visual

Die farbliche Kurzfassung des Long-Zustands.

### Close Strength

Zeigt, wie stark die aktuelle Kerze schliesst.

- Strong Close: bullischer Schluss
- Weak Close: schwacher Schluss

### EMA Support

Prueft, ob Preis und EMA-Struktur den Long unterstuetzen.

- OK: sauberer Rueckenwind
- No: kein sauberer Trend-Rueckenwind

### ADX

ADX misst Trendstaerke.
Mit der Zusatzinfo erkennt man auch, wer Druck macht.

Beispiel:

`30 | Bearish pressure`

Das bedeutet: Bewegung hat Kraft, aber diese Kraft kommt eher von der Verkaeuferseite.

### Rel Volume

Relatives Volumen gegen den Durchschnitt.

- 1.2x: mehr Teilnahme als normal
- 0.5x: unterdurchschnittlich
- 0.01x: extrem schwach

Wichtig seit den letzten Fixes:

- Das Dashboard trennt jetzt besser zwischen `schwacher aktueller Volumen-Kerze` und `grundsaetzlich unbrauchbarer Volumenbasis`.
- Wenn Volumendaten fehlen, degradiert das System kontrolliert, statt RelVol, Profile und volumengetriebene Bestaetigungen stillschweigend falsch zu behandeln.

### LTF Bias

LTF bedeutet Lower Time Frame.
Das Feld misst die Tendenz der kleineren Unterstruktur.

### LTF Delta

Kurzfristiger Druck bzw. Volumenunterschied auf Unterzeitebene.

- positiv: eher Kaeuferdruck
- negativ: eher Verkaeuferdruck
- n/a: keine brauchbare Datenbasis

Neu dabei:

- LTF-Preisverfuegbarkeit und LTF-Volumenverfuegbarkeit werden getrennt behandelt.
- Dadurch kann das System klar anzeigen, ob es nur preisbasierte Unterstruktur sieht oder ob auch Volumen-Delta wirklich belastbar ist.

### Micro Profile

Zeigt das dominante Microstructure-Profil fuer den aktuellen Marktabschnitt.

- Das kann zum Beispiel neutral, trendig, impulsiv oder ausgeduennt sein.
- Neu ist, dass zusaetzliche Modifier im Dashboard sichtbar werden, wenn mehrere Microstructure-Regeln gleichzeitig aktiv sind.
- So sieht man besser, warum ein Setup geschaerft oder abgeschwaecht wurde.

### Objects

Zeigt, wie viele OB- und FVG-Objekte sichtbar sind. Das ist eher Orientierung als Entry-Signal.

### Swing H/L

Zeigt Haupt- und interne Struktur-Hochs und -Tiefs.

### Long Zones

Die aktuell relevanten Long-Zonen.

### Long Triggers

Die Rueckeroberungs- oder Bestaetigungslevel fuer das Setup.

### Legend

Farblegende des Dashboards:

- Aqua: Zone
- Orange: Armed
- Gold: Building
- Lime: Confirmed
- Green: Ready
- Red: Fail

## Snapshot-Deutung in einfacher Sprache

Beispiel:

- Trend = Bullish
- HTF Trend = 3:Bearish | 10:Bullish | 30:Bearish
- Pullback Zone = In FVG Zone
- Reclaim = No Reclaim
- Long Visual = In Zone
- Close Strength = Weak Close
- EMA Support = No
- ADX = 30 | Bearish pressure
- Rel Volume = 0.01x

Kurz gelesen:

- Preis ist in einer moeglichen Long-Zone.
- Aber fast alle wichtigen Bestaetigungen fehlen noch.

Praxisfazit:

> Interessante Long-Zone ja, aber noch keine saubere Long-Bestaetigung. Eher warten als einsteigen.

## Was man mit so einem Zustand nicht tun sollte

- Nicht nur wegen `In FVG Zone` oder `In OB Zone` kaufen.
- Nicht gegen klaren Verkaeuferdruck blind long gehen.
- Nicht `Trend = Bullish` ueberbewerten, wenn HTF, Reclaim, Close und EMA nicht mitziehen.
- Nicht bei extrem schwachem Volumen aggressiv einsteigen.
- Nicht ohne klares Invalidations-Level handeln.

## Worauf man fuer einen Long-Dip warten sollte

Die saubere Reihenfolge ist meistens:

1. Preis kommt in eine sinnvolle Zone.
2. Ein Reclaim erscheint.
3. Das Long Setup wird Armed oder Building.
4. Spaeter folgt Confirmed oder Ready.
5. Close, EMA, ADX und Volumen sprechen nicht mehr klar dagegen.

## Drei Phasen

### 1. Beobachten

- Trend bullish oder wenigstens nicht bearish
- Preis in OB- oder FVG-Zone
- Reclaim noch nicht vorhanden
- Long Visual noch In Zone

### 2. Vorbereiten

- Reclaim ist vorhanden
- Long Setup wird Armed oder Building
- Close Strength verbessert sich
- EMA Support verbessert sich

### 3. Einstieg

- Trend bullish
- Reclaim vorhanden
- Long Setup ist Confirmed oder Ready
- Strong Close
- EMA Support OK
- ADX nicht bearish pressure
- Volumen nicht tot

## Ampel fuer Long-Dips

### Gruen

- Trend bullish
- HTF nicht klar gegen den Trade
- Pullback Zone aktiv
- Reclaim vorhanden
- Long Setup Confirmed oder Ready
- Strong Close
- EMA Support OK

### Gelb

- Zone aktiv
- erster Reclaim oder frueher Strukturwechsel sichtbar
- Long Setup Armed oder Building

### Rot

- No Reclaim
- Weak Close
- EMA Support No
- ADX bearish pressure
- extrem schwaches Volumen
- nur In Zone ohne Bestaetigung

## Fuenf-Punkte-Checkliste vor dem Long

1. Trend bullish?
2. Preis in einer sinnvollen OB- oder FVG-Zone?
3. Reclaim vorhanden?
4. Long Setup Confirmed oder Ready?
5. Close, EMA, ADX und Volumen sprechen nicht dagegen?

Wenn davon nur ein oder zwei Punkte passen, ist es meist zu frueh.

## Neue Long-Dip-Alert-Presets

Die aktuellen Alert-Presets in `SMC++.pine` bilden den Workflow direkt ab:

- `Long Dip Watchlist`: bullish trend plus aktive Pullback-Zone
- `Long Dip Armed+`: Zone, Reclaim und bewaffnetes Setup
- `Long Dip Early`: frueher Hinweis mit interner Struktur, Strong Close und EMA Support
- `Long Dip Clean`: bestaetigtes und gefiltertes Setup
- `Long Dip Entry Best`: empfohlener Standard-Entry-Alert
- `Long Dip Entry Strict`: spaeter und selektiver mit HTF- und Momentum-Filtern
- `Long Dip Failed`: Setup invalidiert

Wichtige Verhaltensdetails seit den letzten Alert-Fixes:

- `Long Dip Watchlist` feuert nur noch dann neu, wenn die generische Watchlist wirklich neu aktiv wird. Ein Wechsel von OB zu FVG innerhalb derselben Watchlist loest keinen zweiten Watchlist-Alert mehr aus.
- `Long Ready` und `Long Invalidated` sind fuer TradingView-Presets jetzt robuster auf Live-Bars, weil intrabar Zustandswechsel per Latch gehalten werden.
- Im Dynamic-Alert-Modus `Priority` kann `Long Invalidated` jetzt auch spaeter auf derselben Echtzeitkerze noch gesendet werden, selbst wenn zuvor bereits ein schwaecherer Lifecycle-Alert wie Watchlist oder Ready gesendet wurde.

## Profil- und Zonenlogik

Fuer die juengsten Profil- und Ueberlappungs-Fixes ist wichtig:

- Die aktive Long-Zone wird bei Ueberlappung sauberer nach Qualitaet ausgewaehlt, nicht nur nach erstem Treffer.
- OB-Profile bauen ihre Value Area jetzt vom POC nach aussen auf. Das ist naeher an der eigentlichen Profil-Logik.
- Leere oder volumenlose Profile werden nicht mehr so behandelt, als haetten sie einen gueltigen POC oder eine gueltige Value Area.
- Wenn ein Setup auf einem bestimmten OB oder FVG bewaffnet wurde, dann prueft auch die spaetere Invalidierung genau dieses Backing-Objekt.

## Empfohlene Nutzung der Alerts

### Zum Beobachten

- `Long Dip Watchlist`

### Fuer vorbereitete Setups

- `Long Dip Armed+`

### Fuer echte Entries

- `Long Dip Entry Best`

### Fuer sehr selektive Entries

- `Long Dip Entry Strict`

## Klare Standard-Empfehlung

Der beste Standard-Alert ist `Long Dip Entry Best`, weil er nicht zu frueh und nicht zu spaet ist.
Er passt gut zum Dashboard-Workflow:

- Trend bullish
- Reclaim vorhanden
- Ready-State vorhanden
- Strong Close
- EMA Support OK

## 1-Zeilen-Regel

Long-Dip nur traden, wenn:

**Trend bullish + Preis in OB/FVG-Zone + Reclaim da + Long Setup Confirmed oder Ready + Strong Close + EMA Support OK**

*** Add File: /Users/steffenpreuss/Downloads/skipp-algo/docs/SMC_Dashboard_Long_Dip_Guide_EN.md
# SMC++ Dashboard Guide for Long-Dip Setups (EN)

## Purpose

This document explains the SMC++ dashboard in plain English.
It is an interpretation and workflow guide, not a standalone buy signal.

Core rule:

- The dashboard is a traffic light and checklist.
- The more fields align, the cleaner the setup.
- A zone by itself is not an entry.

## Dashboard Terms in Plain English

### Trend

The active market structure on the current chart.

- Bullish: structure leans upward
- Bearish: structure leans downward
- Neutral: no clear structural edge yet

### HTF Trend

HTF means Higher Time Frame.
This field shows whether larger timeframes support the trade.

Example:

`3:Bearish | 10:Bullish | 30:Bearish`

That is mixed and not ideal for a conservative long-dip.

### Pullback Zone

Shows whether price is inside a possible reaction zone.

Typical states:

- In OB Zone
- In FVG Zone
- In OB + FVG Zone
- No Long Zone

Important: a zone means watch, not buy.

### Reclaim

Reclaim means price has recovered an important level or zone.
For longs, that matters because it shows buyers are taking control back.

Positive examples:

- OB Reclaimed
- FVG Reclaimed
- Internal Low Reclaimed
- Swing Low Reclaimed

Warning sign:

- No Reclaim

### Long Setup

The operating state of the long setup.

- In Zone: interesting area, but not an entry yet
- Armed: setup is being tracked
- Building: structure is improving
- Confirmed: key confirmation is in place
- Ready: clean, advanced setup
- Blocked or Invalidated: setup is broken

### Setup Age

How old an armed or confirmed setup is.

Examples:

- armed 2
- confirmed 1

Fresh setups are usually better than old ones.

### Long Visual

The visual summary of the long state.

### Close Strength

Shows how strong the current candle closed.

- Strong Close: bullish close
- Weak Close: weak close

### EMA Support

Checks whether price and EMA structure support the long.

- OK: clean tailwind
- No: no clean trend support

### ADX

ADX measures trend strength.
With the extra text you also see who is applying pressure.

Example:

`30 | Bearish pressure`

That means the move has strength, but sellers currently control that strength.

### Rel Volume

Relative volume against average volume.

- 1.2x: above normal participation
- 0.5x: below normal participation
- 0.01x: extremely weak

### LTF Bias

LTF means Lower Time Frame.
This field measures the tendency of the smaller internal structure.

### LTF Delta

Short-term pressure or volume imbalance on the lower timeframe.

- positive: buyer pressure
- negative: seller pressure
- n/a: no useful data base

### Objects

Shows how many OB and FVG objects are visible. This is more orientation than entry logic.

### Swing H/L

Shows major and internal structure highs and lows.

### Long Zones

The currently relevant long zones.

### Long Triggers

The reclaim or confirmation levels for the setup.

### Legend

Dashboard color legend:

- Aqua: Zone
- Orange: Armed
- Gold: Building
- Lime: Confirmed
- Green: Ready
- Red: Fail

## Example Snapshot Interpretation

Example:

- Trend = Bullish
- HTF Trend = 3:Bearish | 10:Bullish | 30:Bearish
- Pullback Zone = In FVG Zone
- Reclaim = No Reclaim
- Long Visual = In Zone
- Close Strength = Weak Close
- EMA Support = No
- ADX = 30 | Bearish pressure
- Rel Volume = 0.01x

Simple read:

- Price is inside a possible long zone.
- But most key confirmations are still missing.

Practical conclusion:

> Interesting long zone, but not a clean long confirmation yet. Waiting is better than entering.

## What You Should Not Do in This State

- Do not buy only because price is inside an FVG or OB zone.
- Do not blindly go long into clear seller pressure.
- Do not overrate `Trend = Bullish` if HTF, reclaim, close, and EMA do not agree.
- Do not enter aggressively on extremely weak volume.
- Do not trade without a clear invalidation level.

## What to Wait For in a Long-Dip

The cleaner sequence is usually:

1. Price reaches a meaningful zone.
2. A reclaim appears.
3. The long setup becomes Armed or Building.
4. Later it becomes Confirmed or Ready.
5. Close, EMA, ADX, and volume stop arguing against the trade.

## Three Phases

### 1. Watch

- Trend bullish or at least not bearish
- Price in an OB or FVG zone
- No reclaim yet
- Long Visual still In Zone

### 2. Prepare

- Reclaim is present
- Long Setup becomes Armed or Building
- Close Strength improves
- EMA Support improves

### 3. Entry

- Trend bullish
- Reclaim present
- Long Setup is Confirmed or Ready
- Strong Close
- EMA Support OK
- ADX not bearish pressure
- Volume not dead

## Traffic Light for Long-Dips

### Green

- Trend bullish
- HTF not clearly against the trade
- Pullback Zone active
- Reclaim present
- Long Setup Confirmed or Ready
- Strong Close
- EMA Support OK

### Yellow

- Zone active
- first reclaim or early internal shift visible
- Long Setup Armed or Building

### Red

- No Reclaim
- Weak Close
- EMA Support No
- ADX bearish pressure
- extremely weak volume
- only In Zone without confirmation

## Five-Point Checklist Before a Long

1. Trend bullish?
2. Price inside a meaningful OB or FVG zone?
3. Reclaim present?
4. Long Setup Confirmed or Ready?
5. Are close, EMA, ADX, and volume not fighting the trade?

If only one or two of these are true, it is usually too early.

## New Long-Dip Alert Presets

The current alert presets in `SMC++.pine` map directly to the workflow:

- `Long Dip Watchlist`: bullish trend plus active pullback zone
- `Long Dip Armed+`: zone, reclaim, and an armed setup
- `Long Dip Early`: early hint with internal structure, strong close, and EMA support
- `Long Dip Clean`: confirmed and filtered setup
- `Long Dip Entry Best`: recommended standard entry alert
- `Long Dip Entry Strict`: later and more selective with HTF and momentum filters
- `Long Dip Failed`: setup invalidated

## Recommended Alert Usage

### For monitoring

- `Long Dip Watchlist`

### For prepared setups

- `Long Dip Armed+`

### For actual entries

- `Long Dip Entry Best`

### For highly selective entries

- `Long Dip Entry Strict`

## Clear Default Recommendation

The best default alert is `Long Dip Entry Best`, because it is not too early and not too late.
It fits the dashboard workflow well:

- trend bullish
- reclaim present
- ready state present
- strong close
- EMA support OK

## One-Line Rule

Only trade a long-dip when:

**Trend is bullish + price is in an OB/FVG zone + reclaim is present + Long Setup is Confirmed or Ready + close is strong + EMA Support is OK**