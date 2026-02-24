# VWAP Long Reclaim — Technical Documentation

**Stand:** 24.02.2026  
**Skripte:**

- `VWAP_Long_Reclaim_Indicator.pine`
- `VWAP_Long_Reclaim_Strategy.pine`

## 1) Scope & Design Intent

Dieses Modul implementiert ein **LONG-only** Reclaim-Setup auf VWAP-Basis mit strukturiertem Zustandsfluss:

1. Reclaim über VWAP
2. Retest im VWAP-Toleranzbereich
3. GO-Break über Pullback-High

Ziele:

- robuste, nachvollziehbare Signalentstehung
- klare Indicator/Strategy-Parität
- begrenzte False-Positives via Trend- und Sequenzlogik

---

## 2) Input Contract

### VWAP

- `hideonDWM`
- `anchor` (`Session`, `Week`, `Month`, `Quarter`, `Year`, `Decade`, `Century`, `Earnings`, `Dividends`, `Splits`)
- `src`, `offset`

### Bands

- `showBand_1`
- `stdevMult_1` (default `0.88`)

### Strategy/Filter

- `matchedTrends` (nur Long bei aufwärtsgerichtetem VWAP-Trend)

### Reclaim

- `preset3m`: `Aggressive | Neutral | Conservative | Custom`
- `reclaimWindowBars`
- `retestTolATR`
- `useAtrTol`
- `debug`
- `showStatusTable`

Effektive Parameter:

- `reclaimWindowBarsEff`
- `retestTolATREff`

---

## 3) Data & Anchoring Layer

Externe Corporate-Event-Serien:

- `request.earnings(...)`
- `request.dividends(...)`
- `request.splits(...)`

Anchor-Schalter:

- Zeitbasiert (`timeframe.change(...)`) oder Event-basiert (`not na(new_earnings)` etc.)
- Bootstrap-Schutz bei erstem validen Balken (`if na(src[1]) and not isEsdAnchor`)

Fail-fast Guard:

- `runtime.error` bei `cumVolume == 0` am letzten Balken

---

## 4) VWAP/Band Calculation

Aktiv, wenn `not (hideonDWM and timeframe.isdwm)`:

- `[_vwap, _stdevUpper, _] = ta.vwap(src, isNewPeriod, 1)`
- `stdevAbs = _stdevUpper - _vwap`
- Band #1: `± stdevMult_1 * stdevAbs`
- Band #2: `± 2 * stdevMult_1 * stdevAbs`

Band #1 ist über `showBand_1` runtime-gesteuert eingeblendet.

---

## 5) State Machine (Reclaim → Retest → GO)

### Core states/vars

- `reclaimBar: int`
- `pullbackHigh: float`
- `retestLow: float`
- `inReclaimSeq: bool`
- `retestSeen: bool`

Zusätzlich im Indicator:

- `inVirtualPos: bool`

### Phase A — Reclaim detection

```text
wasBelowVwap = close[1] < vwapValue[1]
reclaimUp    = wasBelowVwap and close > vwapValue
```

Bei `reclaimUp`:

- startet Sequenz
- setzt `reclaimBar = bar_index`
- initialisiert `pullbackHigh = high`

### Phase B — Sequence maintenance

- `pullbackHigh = max(pullbackHigh, high)`
- `expired = (bar_index - reclaimBar) > reclaimWindowBarsEff`
- `hardFail = close < vwapValue - tol`
- Abbruch bei `expired || hardFail`

### Phase C — Retest confirmation

Retest-Bedingung:

```text
low <= vwapValue + tol and close >= vwapValue - tol
```

Dann:

- `retestSeen = true`
- `retestLow = low`

### Phase D — GO trigger

```text
goLong = inReclaimSeq and retestSeen and close > pullbackHigh[1] and bar_index > reclaimBar
```

`bar_index > reclaimBar` ist die zentrale Absicherung gegen Same-Bar-Degeneration durch alte `pullbackHigh[1]`-Werte.

---

## 6) Trend Filter Contract

- `upV = utils.trendUp(vwapValue)`
- `isUpTrend = upV > 0`
- `matchedTrendsFilter_long = not matchedTrends ? true : isUpTrend`

Long-Signal:

- Indicator: `longSignal = goLong and matchedTrendsFilter_long and not inVirtualPos`
- Strategy: `longSignal = goLong and matchedTrendsFilter_long and strategy.position_size == 0`

---

## 7) Indicator Execution Model

Da kein echtes Positionsobjekt existiert, wird eine virtuelle Position verwendet:

- On `longSignal` → `inVirtualPos := true`
- gleichzeitig Reset von Sequenzflags (`inReclaimSeq := false`, `retestSeen := false`)

TP-/Exit-Definitionen:

- `tpCross = ta.crossover(high, upperBandValue2)`
- `tpStretch = inVirtualPos and tpCross`
- `exitOnVwapLoss = inVirtualPos and close < vwapValue - tol`

Lifecycle-Ende:

- Bei `tpStretch` oder `exitOnVwapLoss` → `inVirtualPos := false`

Dadurch feuern TP/Exit-Labels nur im aktiven virtuellen Trade-Kontext.

---

## 8) Strategy Execution Model

Orderfluss:

- Entry: `strategy.entry("Long", strategy.long)` bei `longSignal`
- Initial Stop: `longStop = retestLow - tol`
- Schutzstop: `strategy.exit("L-Stop", "Long", stop=longStop)`
- Stretch TP: bei `ta.crossover(high, upperBandValue2)` und offener Position → `strategy.close("Long", qty_percent=50)`
- VWAP-Loss Exit: `strategy.close("Long")` bei `close < vwapValue - tol`

`strategy.position_size == 0` im `longSignal` verhindert Stop-Overwrite während bereits offener Positionen.

---

## 9) Visual & Alert Contracts

### Plots

- VWAP + Band #1/#2
- Fill-Farben abhängig von `isUpTrend`
- `pullbackHigh` nur sichtbar in aktiver Sequenz/Position:
  - Indicator: `inReclaimSeq or inVirtualPos`
  - Strategy: `inReclaimSeq or strategy.position_size > 0`

### Labels

- `Buy`, `TP`, `Exit` via `showTradeLabels`
- Debug `R`/`T` via `debug`

### Alerts (Indicator)

- `Long Entry`
- `Stretch Take Profit`
- `VWAP Loss Exit`

---

## 10) Reliability Notes (Implemented Hardening)

1. **No label spam**: TP/Exit sind position-gated.
2. **No consecutive long re-fire**: Sequenzflags werden auf Entry sauber zurückgesetzt.
3. **Parity TP semantics**: Indicator nutzt ebenfalls `ta.crossover` statt `>=`.
4. **No same-bar reclaim-go shortcut**: `bar_index > reclaimBar` guard.
5. **Band input wired**: `showBand_1` steuert Band #1 effektiv.
6. **Stale line prevention**: `pullbackHigh` nur bei aktivem Kontext.

---

## 11) Known Limitations / Future Ideas

- Debug-`T`-Marker zeigt „Retest bereits gesehen“, nicht nur den Erst-Event.
- Mehrstufige TP-Logik (50% + Rest-Management) kann optional weiter ausgebaut werden.
- Erweiterbar um Session-/Volumen-/News-Guards für intraday regime control.

---

## 12) Quick Verification Checklist

1. Preset auf `Neutral`, Anchor `Session`.
2. Reclaim unter/über VWAP visuell prüfen (`R`).
3. Retest-Bestätigung (`T`) innerhalb `reclaimWindowBarsEff` prüfen.
4. `Buy` erst nach Retest + Break über `pullbackHigh[1]` auf Folgebars.
5. `TP` nur bei aktiver Position + Cross über Band #2.
6. `Exit` nur bei aktiver Position + VWAP-Verlust (`tol` berücksichtigt).
7. In Strategy: Stop wird nach Entry gesetzt und nicht durch Re-Signale überschrieben.

---

## 13) File References

- Indicator: `VWAP_Long_Reclaim_Indicator.pine`
- Strategy: `VWAP_Long_Reclaim_Strategy.pine`
- Ergänzende TradingView-Doku: `docs/TRADINGVIEW_STRATEGY_GUIDE.md`
