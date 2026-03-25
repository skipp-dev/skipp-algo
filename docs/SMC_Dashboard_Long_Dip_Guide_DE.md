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

Seit den juengsten Review-Fixes kommen noch zwei praktische Details dazu:

- `Long Setup` und `Long Visual` bleiben nach einer intrabar-Invalidierung bis zur naechsten Kerze sichtbar auf dem Invalidated/Fail-Zustand, statt auf derselben Echtzeitkerze wieder still auf neutral zurueckzufallen.
- Das Watchlist-Alert-Level folgt jetzt der gleichen aktiven OB/FVG-Zonenpraeferenz wie der Rest der Long-Zonenlogik, statt bei gleichzeitiger OB- und FVG-Verfuegbarkeit immer stumpf OB zu bevorzugen.

## Dashboard-Bloecke

Das Dashboard ist jetzt nicht nur nach Einzelzeilen, sondern auch nach vier Funktionsbloecken gegliedert.

### [ Lifecycle ]

Dieser Block zeigt den reinen Ablauf des Setups.

- Trend
- HTF Trend
- Pullback Zone
- Reclaim
- Long Setup
- Setup Age
- Long Visual
- Exec Tier

Hier geht es um die Frage: Wo steht das Setup gerade im Ablauf?

### [ Hard Gates ]

Dieser Block zeigt die Freigaben und Sperren.

- Session
- Market Gate
- Vola Regime
- Micro Session
- Micro Fresh
- Volume Data
- Quality Env
- Quality Strict

Hier geht es um die Frage: Darf das Setup unter den aktuellen Markt- und Ausfuehrungsbedingungen ueberhaupt weiterlaufen?

### [ Quality ]

Dieser Block zeigt die Kontextqualitaet.

- Primary | Quality Env
- Primary | Quality Score
- Primary | Quality Clean
- Diag | Quality Strict
- Diag | Close Strength
- Diag | EMA Support
- Diag | ADX
- Diag | Rel Volume
- Diag | VWAP Filter
- Diag | Context Quality

Hier geht es um die Frage: Wie sauber und belastbar ist das Setup-Umfeld?

Leseregel:

- `Primary`-Zeilen sind die zuerst zu lesenden Trade-Signal-Metriken.
- `Diag`-Zeilen liefern Einordnung und Debug-Kontext, sollen aber ein schwaches Setup nicht allein zu einem Entry machen.

### [ Modules ]

Dieser Block zeigt die Upgrade-Module.

- SD Confluence
- SD Osc
- Vol Regime
- Vol Squeeze
- Vol Expand
- Stretch
- DDVI
- LTF Bias
- LTF Delta
- Objects
- Swing H/L
- Long Zones
- Long Triggers
- Micro Profile
- Risk Plan

Hier geht es um die Frage: Welche Zusatzmodule heben ein Ready-Setup auf Best oder Strict an?

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
- Invalidated: Setup ist kaputt

Wichtig auf Live-Bars:

- Wenn ein Setup intrabar invalidiert wurde, bleibt `Long Setup` jetzt bis zur naechsten Kerze sichtbar auf `Invalidated`.

### Setup Age

Wie alt ein bewaffnetes oder bestaetigtes Setup ist.

Beispiele:

- armed 2
- confirmed 1

Frische Signale sind meist besser als alte.

### Long Visual

Die farbliche Kurzfassung des Long-Zustands.

Typische Zustaende:

- Fail
- Neutral
- In Zone
- Armed
- Building
- Confirmed
- Ready

`Long Visual` zeigt bewusst nur den Lifecycle.
`Best` und `Strict` stehen separat in `Exec Tier`.

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

Wichtig:

- Das Watchlist-Alert-Level und die Trigger-Interpretation folgen jetzt der bevorzugten aktiven Zone.
- Wenn OB und FVG gleichzeitig moeglich sind, wird nicht mehr automatisch OB fuer das Alert-Level genommen, sondern die intern bereits bevorzugte aktive Zone.

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
- `Long Invalidated`: Setup invalidiert

Wichtige Verhaltensdetails seit den letzten Alert-Fixes:

- `Long Dip Watchlist` feuert nur noch dann neu, wenn die generische Watchlist wirklich neu aktiv wird. Ein Wechsel von OB zu FVG innerhalb derselben Watchlist loest keinen zweiten Watchlist-Alert mehr aus.
- `Long Ready` und `Long Invalidated` sind fuer TradingView-Presets jetzt robuster auf Live-Bars, weil intrabar Zustandswechsel per Latch gehalten werden.
- Im Dynamic-Alert-Modus `Priority` kann `Long Invalidated` jetzt auch spaeter auf derselben Echtzeitkerze noch gesendet werden, selbst wenn zuvor bereits ein schwaecherer Lifecycle-Alert wie Watchlist oder Ready gesendet wurde.
- Passend dazu bleibt die Dashboard-Anzeige fuer `Long Setup` und `Long Visual` auf derselben Echtzeitkerze jetzt ebenfalls sticky auf Invalidated/Fail, damit Alert und UI nicht auseinanderlaufen.

## Profil- und Zonenlogik

Fuer die juengsten Profil- und Ueberlappungs-Fixes ist wichtig:

- Die aktive Long-Zone wird bei Ueberlappung sauberer nach Qualitaet ausgewaehlt, nicht nur nach erstem Treffer.
- Das Watchlist-Alert-Level nutzt jetzt dieselbe Zonenpraeferenz wie diese aktive Long-Zonenwahl.
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

### Regel kompakt

Trend bullish + Preis in OB/FVG-Zone + Reclaim da + Long Setup Confirmed oder Ready + Strong Close + EMA Support OK
