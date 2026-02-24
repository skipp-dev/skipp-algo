# VWAP Long Reclaim — Kurzguide für Nutzer

**Stand:** 24.02.2026  
**Skripte:** `VWAP_Long_Reclaim_Indicator.pine`, `VWAP_Long_Reclaim_Strategy.pine`

## Worum geht’s?

`VWAP Long Reclaim` sucht ein klares Long-Setup in drei Schritten:

1. **Reclaim**: Kurs war unter VWAP und schließt wieder darüber.
2. **Retest**: Preis testet den VWAP-Bereich erneut (mit Toleranz).
3. **GO**: Schlusskurs bricht über das bisherige Pullback-High.

Kurz: Erst zurück über VWAP, dann sauberer Test, dann Ausbruch.

---

## Unterschied: Indicator vs. Strategy

- **Indicator**
  - zeigt Signale/Labels auf dem Chart (`Buy`, `TP`, `Exit`)
  - führt keine echten Orders aus
  - simuliert intern eine „virtuelle Position“ für saubere TP/Exit-Labels

- **Strategy**
  - erzeugt echte Strategy-Entries/Exits in TradingView
  - nutzt `strategy.entry`, `strategy.exit`, `strategy.close`
  - ist für Backtests und Auswertungen gedacht

---

## Standard-Labels auf dem Chart

Wenn `Show Trade Labels = ON`:

- **Buy**: Long-Einstieg
- **TP**: Stretch-Take-Profit (Band #2 erreicht/überschritten)
- **Exit**: Verlust des VWAP mit Toleranz

Optional mit `Debug Markers`:

- `R` = Reclaim erkannt
- `T` = Retest erkannt

---

## Wichtige Einstellungen

## 1) Reclaim-Preset (3m)

`3m Preset`:

- **Aggressive**: mehr Setups, toleranter
- **Neutral**: ausgewogen (Default)
- **Conservative**: strenger, weniger Setups
- **Custom**: eigene Werte

Die Presets steuern intern:

- `Reclaim: Max Bars bis Retest` (Zeitfenster)
- `Retest Toleranz (ATR-Anteil)`

## 2) Trendfilter

`Only Show/Enter on Matched Trends`:

- ON: nur Long-Signale, wenn VWAP-Trend aufwärts ist
- OFF: zeigt/erlaubt Signale ohne Trend-Match

## 3) Band-Visualisierung

`Show Band 1` blendet Band #1 ein/aus.  
Band #2 bleibt als Stretch-/Extrem-Bereich sichtbar.

## 4) Display

- `Barcolors`
- `Show Trade Labels`
- `Show Status Table`

---

## Empfohlener Start (3-Minuten, Intraday)

- Preset: **Neutral**
- Anchor: **Session**
- Matched Trends: **ON**
- Show Trade Labels: **ON**
- Debug Markers: für Setup-Training kurzzeitig **ON**, später eher **OFF**

---

## Interpretation der Signale

- **Buy** ist erst nach vollständiger 3-Phasen-Bestätigung aktiv.
- **TP** ist ein Teilgewinn-/Streckungs-Hinweis, kein „Muss-Exit“.
- **Exit** signalisiert Strukturverlust gegenüber VWAP (mit Toleranz).

In der **Strategy** wird bei TP aktuell eine Teilreduktion ausgeführt (50%), der Rest wird weiter über Stop/Exit-Logik verwaltet.

---

## Häufige Fragen

### „Warum sehe ich nicht ständig TP/Exit-Labels?“

Das ist beabsichtigt: TP/Exit sind an aktive Position gekoppelt (Indicator: virtuelle Position, Strategy: echte Position). Dadurch weniger Label-Spam.

### „Warum kommt kein Buy auf dem Reclaim-Bar selbst?“

Absichtlich abgesichert: Der GO-Schritt darf nicht auf derselben Kerze wie der Reclaim feuern. So bleibt das 3-Phasen-Muster sauber.

### „Welchen Anchor soll ich verwenden?“

Für 3m Daytrading in der Regel **Session**.

---

## Praxis-Workflow

1. Setup im **Indicator** visuell trainieren.
2. Parameter im **Strategy**-Backtest validieren.
3. Erst danach Alerts/Execution-Flow aufsetzen.

---

## Risikohinweis

Das Skript ist ein technisches Regelwerk, kein Gewinnversprechen. Nutze Positionsgröße, Stop-Logik und Markt-/News-Kontext diszipliniert.
