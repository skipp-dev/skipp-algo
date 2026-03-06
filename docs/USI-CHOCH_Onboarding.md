# USI-CHoCH — Schnellstart & Onboarding

Stand: 2026-03-06

---

## Was ist USI-CHoCH?

**USI-CHoCH** ist ein TradingView-Overlay-Indikator, der drei Analyse-Ebenen in einem Chart vereint:

| Ebene | Was es tut | Visuell |
|---|---|---|
| **USI (Universal Strength Index)** | 6 Zero-Lag-RSI-Linien erkennen Momentum-Flips | `BUY` / `SHORT` Labels |
| **CHoCH (Change of Character)** | Strukturbrüche über Swing-Levels bestätigt durch Sweep + Volumen | `CHoCH` Labels |
| **VWAP + StdDev-Bänder** | Trend-Regime + Red-Zone-Filter | Weiße VWAP-Linie, Hintergrundtönung |

Zusätzlich: **Pressure Dots + Bollinger Squeeze** (Konsolidierung + Ausbruchs-Timing), **Anticipation** (Frühwarnung), **Momentum Pre-CHoCH** (RSI-Divergenz + Volume-Spike), **OBV Divergence** (Smart-Money-Erkennung) und **CMF** (Volumenfluss-Richtung).

---

## In 60 Sekunden starten

1. **Skript hinzufügen**: `USI-CHOCH.pine` auf einen TradingView-Chart legen (Intraday, z.B. 5m oder 15m)
2. **Preset wählen**: Im Settings-Panel unter *USI Settings* das passende Preset auswählen:
   - **Fast (7/6/4/3/2/1)** — Standard, ideal für 1m–15m
   - **Default (13/11/7/5/4/2)** — wie SkippALGO, für 15m–1h
   - **Medium / Slow / Macro** — für 4h, Daily, Weekly
3. **Beobachten**: Grüner Hintergrund = Aufwärtstrend, Roter Hintergrund = Abwärtstrend
4. **Signale lesen**: `BUY` = USI-Flip bullish, `CHoCH` = Strukturbruch bestätigt
5. **Alerts setzen** (optional): Settings → Alerts → gewünschte Condition auswählen

**Keine weiteren Einstellungen nötig** — die Defaults sind ausgewogen konfiguriert.

---

## Was bedeuten die Signale?

### BUY / SHORT (USI-Flip)

```
     ┌─ Rote RSI-Linie (schnellste) springt über ALLE 5 anderen Linien
     │  = Momentum-Umschwung
     ▼
   ╔═══╗
   ║BUY║  Grünes Label unter der Kerze
   ╚═══╝
```

- Die rote (schnellste) USI-Linie kreuzt alle 5 langsameren Linien
- Mindest-Abstand (Margin) muss eingehalten werden = weniger Rauschen
- Volumen-Filter: Nur bei überdurchschnittlichem Volumen (Standard: 1.4x SMA)
- Red-Zone-Suppression: Kein BUY wenn Preis unter dem unteren VWAP-Band

### CHoCH (Change of Character)

```
   lastSwingLow ───────── Sweep (low < Level, close > Level) ─── Liquidität geholt
       │
       └───► Breakout über lastSwingHigh = Strukturbruch
               + Überdurchschnittliches Volumen
               = ╔═════╗
                 ║CHoCH║  Dunkelgrünes Label
                 ╚═════╝
```

- **BEST Bullish CHoCH** = CHoCH + Liquiditäts-Sweep + Volumen-Bestätigung
- Drei Modi: *Ping* (sofort), *Verify* (Bestätigung nächste Bar), *Ping+Verify* (beides)

### Anticipation (A↑ / A↓)

- Diamant-Symbol: Preis nähert sich einem Swing-Level (innerhalb 0.15%)
- Frühwarnung *vor* dem eigentlichen CHoCH
- Aqua = bullish, Orange = bearish

### Momentum Pre-CHoCH (M↑ / M↓)

- Dreieck-Symbol: RSI-Divergenz + Volume-Spike erkannt
- Bullish: Preis macht tieferes Tief, RSI macht höheres Tief + Volume-Spike
- Noch vor dem Strukturbruch — frühester Hinweis

### OBV Divergence (V↑ / V↓) 🆕

```
   Preis fällt ──────►  Lower Low
   OBV steigt  ──────►  Higher Low   ← Smart Money akkumuliert!
                                      
       ╔══╗
       ║V↑║  Blaues Quadrat unter der Kerze
       ╚══╝
```

- Quadrat-Symbol: On-Balance-Volume divergiert vom Preis
- Bullish (V↑): Preis fällt, aber OBV steigt → unsichtbare Akkumulation (Smart Money kauft)
- Bearish (V↓): Preis steigt, aber OBV fällt → unsichtbare Distribution (Smart Money verkauft)
- Frühester aller Early Signals — feuert oft *vor* M↑ und A↑
- Ergänzt RSI-Divergenz perfekt: RSI misst Momentum, OBV misst Geldfluss

### Squeeze Release (SQ↑ / SQ↓) 🆕

```
   BB innerhalb KC  ────►  Squeeze aktiv (Kompressions-Phase)
   BB verlässt KC   ────►  Release! Ausbruch startet!
                                      
       ╔═══╗
       ║SQ↑║  Goldener Diamant unter der Kerze
       ╚═══╝
```

- Bollinger Bands innerhalb des Keltner Channels = extremer Druck-Aufbau
- SQ↑/SQ↓ feuert genau beim **Release** (Ende des Squeeze = Ausbruch beginnt)
- Richtung bestimmt durch BB-Midline-Momentum (steigend = bullish)
- Während Squeeze leuchten Pressure Dots heller (Orange→Rot statt Gelb)

### CMF (C↑ / C↓) 🆕

- Kreuz-Symbol: Chaikin Money Flow zeigt **Richtung** des Volumenflusses
- C↑ = starker Kaufdruck (CMF > 0.10) in bearisher Struktur → Geld fließt rein
- C↓ = starker Verkaufsdruck (CMF < -0.10) in bullisher Struktur → Geld fließt raus
- Unterschied zu OBV: CMF ist ein **bounded Oszillator** (-1 bis +1), OBV ist kumulativ
- Ergänzt Volumen-Stärke (OBV) mit Volumen-**Richtung**

### Pressure Dots (gelb → rot)

- Kreise unter den Kerzen nur während **Konsolidierungsphasen**
- Gelb = ruhige Konsolidierung, Rot = Druck steigt, Ausbruch wahrscheinlich
- Bei aktivem Bollinger Squeeze: Dots leuchten heller (Orange→Rot-Spektrum)
- Verschwinden automatisch wenn der Markt ausbricht
- 4 unabhängige Bedingungen: ADX, ATR, USI-Spread, BB-Squeeze (≥2 = Konsolidierung)

---

## Hintergrundfarben verstehen

| Farbe | Bedeutung |
|---|---|
| 🟢 Leicht grüner Hintergrund | VWAP-Aufwärtstrend (Slope > 0 oder Preis über VWAP) |
| 🔴 Leicht roter Hintergrund | VWAP-Abwärtstrend |
| Aqua-Blitz (1 Bar) | Anticipation bullish |
| Orange-Blitz (1 Bar) | Anticipation bearish |
| Lime-Blitz (1 Bar) | Momentum Pre-CHoCH bullish |
| Fuchsia-Blitz (1 Bar) | Momentum Pre-CHoCH bearish |
| Hellblau-Blitz (1 Bar) | OBV Divergence bullish |
| Tomatenrot-Blitz (1 Bar) | OBV Divergence bearish |
| Limegreen-Blitz (1 Bar) | CMF Kaufdruck bullish |
| Crimson-Blitz (1 Bar) | CMF Verkaufsdruck bearish |

---

## Settings-Gruppen im Überblick

### ⚡ USI Settings

| Setting | Default | Was es tut |
|---|---|---|
| USI Preset | Fast | Vorkonfigurierte Linien-Längen (6 Linien) |
| Custom Lengths | — | Nur aktiv bei Preset = "Custom" |

### 🔒 Signal Filters

| Setting | Default | Was es tut |
|---|---|---|
| Bar Close Only | ❌ | Signale nur auf bestätigten Bars (verhindert Flicker) |
| Volume Filter | ✅ | Nur Signale bei überdurchschnittl. Volumen |
| Min Volume Ratio | 1.4 | Aktuelles Volumen / SMA muss ≥ 1.4 sein |

### 🧭 Stability Filters

| Setting | Default | Was es tut |
|---|---|---|
| USI Margin | 1.0 | Mindest-Abstand der roten Linie (RSI-Punkte) |
| Relaxed Flip | ❌ | Flip darf über N Bars entwickeln statt 1 Bar |
| Strong Stack | ❌ | Volle sequenzielle Ordnung L5>L4>…>L0 nötig |
| Slow Trend | ❌ | Langsamste Linien müssen konstruktiv sein |

### VWAP Settings

| Setting | Default | Was es tut |
|---|---|---|
| Anchor Period | Session | VWAP-Reset-Zeitraum |
| Suppress BUY in Red Zone | ✅ | BUY unterdrücken wenn Preis unter unterem Band |
| Background Tint | ✅ | Chart-Hintergrund nach Trend einfärben |
| Tint Transparency | 92 | 92 = dezent, 50 = deutlich |

### 🔴 Pressure Dots + Squeeze

| Setting | Default | Was es tut |
|---|---|---|
| Show Pressure Dots | ✅ | Konsolidierungs-Druckpunkte anzeigen |
| ADX Threshold | 25 | Unter diesem ADX-Wert = Konsolidierung |
| Dots Distance (ATR) | 1.0 | Abstand der Dots unter den Kerzen |
| Enable BB Squeeze | ✅ | Bollinger Squeeze als 4. Consolid.-Bedingung |
| BB Length | 20 | Bollinger Band Periode |
| BB StdDev Mult | 2.0 | BB Standardabweichungs-Faktor |
| KC Length | 20 | Keltner Channel Periode |
| KC ATR Mult | 1.5 | Keltner Channel ATR-Faktor |
| Show Squeeze Release | ✅ | SQ↑/SQ↓ Marker beim Squeeze-Ende |

### 📊 OBV Divergence

| Setting | Default | Was es tut |
|---|---|---|
| Enable OBV Divergence | ✅ | Smart-Money-Divergenz aktivieren |
| OBV Divergence lookback | 10 | Bars zurückschauen für Preis vs. OBV Vergleich |
| OBV Smoothing (SMA) | 5 | Glättung des OBV. 1 = roh, 5 = weniger Rauschen |
| Show OBV Div markers | ✅ | V↑/V↓ Marker anzeigen |

### 💰 CMF (Chaikin Money Flow)

| Setting | Default | Was es tut |
|---|---|---|
| Enable CMF signals | ✅ | Volumenfluss-Richtungs-Signale aktivieren |
| CMF Length | 20 | Lookback-Periode für CMF |
| CMF Threshold | 0.10 | Mindest-CMF für Signal (0.10 = moderate Stärke) |
| Show CMF markers | ✅ | C↑/C↓ Marker anzeigen |

---

## Preset-Übersicht: Welches Preset für welchen Timeframe?

```
Timeframe        Empfohlenes Preset           Linien-Längen (L0→L5)
─────────────    ─────────────────────        ─────────────────────
1m – 15m         Fast (7/6/4/3/2/1)           7, 6, 4, 3, 2, 1
15m – 1h         Default (13/11/7/5/4/2)      13, 11, 7, 5, 4, 2
1h – 4h          Medium (26/22/14/10/8/4)     26, 22, 14, 10, 8, 4
4h – Daily       Slow (39/33/21/15/12/6)      39, 33, 21, 15, 12, 6
Daily – Weekly   Macro (52/44/28/20/16/8)     52, 44, 28, 20, 16, 8
Eigene Werte     Custom                       Manuelle Eingabe
```

---

## Schritt-für-Schritt: Alerts einrichten

1. Auf dem Chart: Rechtsklick → **Alert hinzufügen** (oder `Alt+A`)
2. **Condition**: `USI-CHoCH` auswählen
3. **Alert-Typ** wählen:
   - `USI Flip BUY` — nur BUY-Signale
   - `USI Flip SHORT` — nur SHORT-Signale
   - `BEST Bullish CHoCH` — nur die stärksten CHoCH-Signale
   - `Any Signal` — BUY + SHORT + CHoCH zusammen
   - `Anticipation Bullish/Bearish` — Frühwarnungen
   - `Momentum Pre-CHoCH Bullish/Bearish` — RSI-Divergenz-Signale
   - `OBV Divergence Bullish/Bearish` — Smart-Money-Akkumulation/Distribution
   - `CMF Bullish/Bearish` — Volumenfluss-Richtung 🆕
   - `Squeeze Release / Bullish / Bearish` — Ausbruch aus Kompression 🆕
   - VWAP-Alerts: Cross Up, Cross Down, Above, Below
4. **Trigger**: "Once Per Bar Close" empfohlen
5. **Destination**: Webhook, E-Mail, App-Notification, etc.

---

## Typische Workflows

### Workflow 1: Einfach — Nur BUY/SHORT folgen

- Preset auf den Timeframe einstellen
- Auf BUY/SHORT Labels achten
- Hintergrundfarbe als Trend-Kontext nutzen
- ✅ Sofort einsatzbereit ohne Tuning

### Workflow 2: Konservativ — Zusätzliche Filter

- `Bar Close Only` = ✅ (kein Intra-Bar-Flicker)
- `Require strong stack` = ✅ (weniger, aber stärkere Signale)
- `Require slow trend` = ✅ (nur in Trendrichtung)
- ✅ Weniger Signale, höhere Qualität

### Workflow 3: Full Context — Alle Features nutzen

- CHoCH + Anticipation + Momentum Pre-CHoCH aktiviert lassen
- Pressure Dots beobachten: Gelb→Rot = Ausbruch kommt (heller bei Squeeze)
- Ablauf: Dots → C↑ (Geldfluss) → V↑ (Smart Money) → SQ↑ (Squeeze Release) → M↑ (Divergenz) → A↑ (fast da) → CHoCH/BUY (Entry)
- ✅ Maximale Vorwarnung aus 6 unabhängigen Quellen, erfordert etwas Übung

---

## Häufige Fragen (FAQ)

### Warum sehe ich keine BUY-Labels?

- **Volume Filter**: Ist aktiviert (Default) und filtert Bars mit unterdurchschnittlichem Volumen weg. Versuche `Min Volume Ratio` auf 1.0 zu senken.
- **Red Zone Suppression**: Ist der Preis unter dem unteren VWAP-Band? Dann werden BUYs unterdrückt. Deaktiviere `Suppress BUY in Red Zone` zum Testen.
- **Margin zu hoch**: Ein USI Margin von 1.0 filtert flache Flips. Versuche 0.5.

### Warum sehe ich keine CHoCH-Labels?

- CHoCH benötigt einen **Strukturwechsel** (vorheriger Abwärtstrend → Aufwärts)
- Zusätzlich muss ein **Liquidity Sweep** stattfinden (`Require sweep/reclaim` ist default ✅)
- Volume muss überdurchschnittlich sein

### Was bedeutet "Red Zone"?

- Preis (hl2) liegt unter dem unteren VWAP-StdDev-Band **UND** VWAP zeigt keinen Aufwärtstrend
- In dieser Zone werden BUY- und CHoCH-Signale unterdrückt (konfigurierbar)
- Debug: `Show Red Zone Debug` = ✅ zeigt die Zone im Chart

### Repainting?

- Mit `Bar Close Only = ✅` sind Signale **non-repainting** (nur auf bestätigten Bars)
- Ohne diesen Filter können Signale intra-bar erscheinen und wieder verschwinden

### VWAP nicht sichtbar?

- VWAP funktioniert nur auf **Intraday-Timeframes** (unter Daily)
- `Hide VWAP on 1D or Above` ist standardmäßig ❌, aber auf Daily+ gibt es keine Session-Resets

---

## Glossar

| Begriff | Bedeutung |
|---|---|
| **USI** | Universal Strength Index — 6 Zero-Lag-RSI-Linien mit unterschiedlichen Längen |
| **Zero-Lag EMA** | 2×EMA(x) - EMA(EMA(x)) — reduziert EMA-Lag um ~50% |
| **CHoCH** | Change of Character — Wechsel der Marktstruktur (Bär → Bulle) |
| **Sweep** | Preis dringt kurz unter ein Swing-Low, schließt aber darüber (Liquidität geholt) |
| **BOS** | Break of Structure — Fortsetzung des bestehenden Trends (kein Richtungswechsel) |
| **VWAP** | Volume-Weighted Average Price — volumengewichteter Durchschnittspreis |
| **StdDev-Band** | Standardabweichung um VWAP → definiert Red Zone / Green Zone |
| **ADX** | Average Directional Index — misst Trendstärke (< 25 = Konsolidierung) |
| **ATR** | Average True Range — misst Volatilität |
| **Pressure Dots** | Visuelle Druckmesser während Konsolidierungsphasen |
| **Anticipation** | Frühwarnung: Preis nähert sich einem Swing-Level |
| **Pre-CHoCH** | RSI-Divergenz + Volume-Spike vor dem eigentlichen Strukturbruch |
| **OBV** | On-Balance Volume — kumulatives Volumen-Delta (steigt bei Up-Bars, fällt bei Down-Bars) |
| **OBV Divergence** | Preis und OBV bewegen sich gegensätzlich → Smart Money handelt gegen den sichtbaren Trend |
| **CMF** | Chaikin Money Flow — bounded Oszillator (-1 bis +1) der Volumenfluss-Richtung misst |
| **Bollinger Bands** | SMA ± Standardabweichung — Band-Breite zeigt Volatilität |
| **Keltner Channel** | EMA ± ATR — wenn BB innerhalb KC = Squeeze (extreme Kompression) |
| **Squeeze** | BB innerhalb KC = Volatilität extrem niedrig, Ausbruch steht bevor |
| **Squeeze Release** | Moment wenn BB den KC wieder verlässt = Ausbruch beginnt |

---

## Nächste Schritte

- **SkippALGO** ausprobieren: Vollständiges Handelssystem mit Outlook, Forecast und Entry-Engine
- **Strategy-Variante testen**: `SkippALGO_Strategy.pine` für Backtests mit gleicher Kernlogik
- **Tuning Guide lesen**: `docs/SkippALGO_Tuning_Guide.md` für fortgeschrittene Parameter-Optimierung
