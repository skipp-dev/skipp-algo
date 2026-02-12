# SkippALGO — Deep Technical Documentation (v6.2.22)

Stand: 2026-02-12  
Gültig für:

- `SkippALGO.pine` (Indicator)
- `SkippALGO_Strategy.pine` (Strategy)

---

## 1. Zielbild und Systemabgrenzung

SkippALGO ist ein Pine-v6-System mit zwei synchronisierten Ausprägungen:

1. **Indicator** (`SkippALGO.pine`) für Visualisierung, Alerts und discretionary/automatisierte Signalnutzung.
2. **Strategy** (`SkippALGO_Strategy.pine`) für Backtest/Execution-Simulation mit möglichst hoher Logik-Parität.

Architektonisch trennt SkippALGO drei Ebenen:

- **State/Outlook Layer** (deskriptiv, nicht prädiktiv)
- **Forecast/Calibration Layer** (probabilistisch, datengetrieben)
- **Execution Layer** (Entry/Exit, Risk, Alerts, Labeling)

---

## 2. Ausführungsmodell, Nicht-Repainting und Zeitlogik

### 2.1 Nicht-Repainting-Prinzip

SkippALGO nutzt konsequent bar- und timeframe-stabile Logik:

- HTF-Daten via `request.security(..., lookahead_off)`
- zentrale Entscheidungs- und Alert-Events auf bestätigten Bars (`barstate.isconfirmed`)
- Forecast- und Display-Logik so strukturiert, dass keine intrabar-future leaks entstehen

### 2.2 HTF-Pulse und stabile Werte

Für Forecast-Horizonte werden rohe HTF-Werte geladen und über stabile Helfer verarbeitet:

- Pulse-Erkennung (`f_stable_pulse`) zur eindeutigen HTF-Bar-Synchronisation
- Wert-Stabilisierung (`f_stable_val`) für bestätigte HTF-Inputs

Das verhindert, dass State/Forecast aus “in-progress”-HTF-Candles inkonsistent lernen.

---

## 3. Layer-Architektur (fachlich)

## 3.1 State / Outlook Layer

State wird pro TF aus Trend-, Momentum- und Lokationskomponenten gebildet.

Typische Inputs/Funktionen:

- EMAs (Fast/Slow)
- RSI/Connors-RSI-Elemente
- ATR- und Volatilitätsregime
- `f_state_score`, `f_state_tml`, `f_trend_regime`

Ergebnis ist ein interpretiertes Regime-Signal (z. B. ▲ / ▼ / −) plus Score und T/M/L-Komponenten im Table-Output.

## 3.2 Forecast / Calibration Layer

Forecast ist ein separates probabilistisches System (3-way Up/Flat/Down), das State in Outcomes mappt.

Kernpunkte:

- Multi-Horizon (F1…F7)
- Bin-/2D-Logik (Score × Regime)
- Online-Kalibrierung mit historischen Resolves
- Reliability/Evidenz-Gates (Sample-abhängig)

Wichtige Konzepte:

- `rel*` Arrays als zentrale Probability Source of Truth
- `f_decision_quality(...)` für Edge/Samples/Flat-Prüfungen
- Brier/ECE/Drift-Bewertungen zur Modellgüte

## 3.3 Execution Layer

Diese Ebene setzt die tatsächlichen Handelsentscheidungen um:

- Engine-Signale (Hybrid/Breakout/Trend+Pullback/Loose)
- Gating (Confidence, MTF, Macro, Drawdown, Session/Close Filter)
- Reversal-Injektion (ChoCH/Neural-Reversal)
- Risk-Management (ATR Stops/TP/Trail, BE, Stalemate, Decay)
- Alerting + Labeling

---

## 4. Signal Engines und Entry-Gates

Verfügbare Engines:

- `Hybrid`
- `Breakout`
- `Trend+Pullback`
- `Loose`

Gemeinsame Gate-Bausteine (je nach Engine-Kombination):

- Confidence/Trust (`minTrust`)
- MTF Vote
- Macro Gate
- Drawdown Gate
- Forecast Entry Gate (`f_entry_forecast_gate`)
- Enhancements (ADX, ROC, Volume-Score, Pre-Momentum, EMA-Accel, VWAP, RegSlope)

### 4.1 Open-Window Verhalten

Open-Window ist fein granuliert:

- Seitengetrennt (`revOpenWindowLongMins`, `revOpenWindowShortMins`)
- Modus (`All Entries` vs `Reversals Only`)
- Engine-Scoping (`revOpenWindowEngine`)

Damit können pU/pD-Bypasses präzise auf Marktöffnungssituationen begrenzt werden.

### 4.2 REV-BUY Mindestwahrscheinlichkeit

Aktuell ist ein harter Floor aktiv:

- **REV-BUY nur bei $pU \ge 0.37$**, auch im Open-Window-Kontext.

Zusätzlich bleibt die normale REV-Wahrscheinlichkeitslogik (`revMinProb`) für den Standardpfad erhalten.

---

## 5. Strict Mode (aktueller Betriebsmodus)

### 5.1 Always-on Policy

Strict ist mittlerweile **always-on außerhalb Open-Window**:

- `strictAlertsEnabled = not inRevOpenWindow`

Der frühere manuelle Toggle wurde entfernt, um konsistentes Verhalten zu erzwingen.

### 5.2 Strict Confirmation Semantik

- BUY/SHORT Alerts sind um 1 Bar verzögert (`buyEvent[1]`/`shortEvent[1]` + zusätzliche Strict-Checks)
- EXIT/COVER bleiben same-bar

Zusätzliche Strict-Filter:

- MTF Margin Check (`strictMtfMargin`, optional adaptiv)
- ChoCH-Recency/Confirm-Check (`strictChochConfirmBars`)

### 5.3 Adaptive Strict Margin

Optional wird die MTF-Margin per ATR-Rang dynamisch angepasst:

- höheres Volatilitätsregime ⇒ strenger
- ruhiges Regime ⇒ weniger streng

Steuerung über:

- `useAdaptiveStrictMargin`
- `strictAdaptiveRange`
- `strictAdaptiveLen`

---

## 6. Risk- und Exit-Subsystem

Unterstützte Mechaniken:

- ATR-basierter initialer SL/TP
- optional Infinite TP + Trail
- Dynamic Risk Decay
- Breakeven Trigger
- Stalemate Exit
- ChoCH/Structure Exits mit Grace-Logik

### 6.1 Stalemate

Stalemate beendet Trades, die nach `staleBars` nicht mindestens `staleMinATR` Fortschritt erreicht haben.  
Ziel: Kapital aus ineffizienten Seitwärts-Trades lösen.

---

## 7. Labeling und Visualisierung

### 7.1 Entry/Exit Labels

- BUY/SHORT/REV-BUY/REV-SHORT werden als dynamische `label.new(...)` Labels gerendert.
- EXIT/COVER enthalten Kontext (Reason, Held Bars, Entry-Typ-Tag).

### 7.2 PRE Labels

PRE-BUY/PRE-SHORT zeigen:

- Gap zur Trigger-Bedingung (in ATR)
- pU/pD
- Confidence

### 7.3 Strict Marker (side-aware)

Strict Marker sind jetzt an Long/Short-Label-Sichtbarkeit gekoppelt:

- Strict-Long nur bei `showLongLabels == true`
- Strict-Short nur bei `showShortLabels == true`

Damit passen Marker zur Nutzerintention “nur Long” bzw. “nur Short”.

---

## 8. Alerting-Architektur

### 8.1 Konsolidierte Alert-Ausgabe

Runtime-Alerts werden pro Bar konsolidiert (Single-Message-Ansatz), um Alert-Throttling zu reduzieren.

### 8.2 Payload

Payload enthält u. a.:

- `mode = strict|normal`
- `confirm_delay = 1|0`

So kann ein externer Consumer Strict-Verzögerung deterministisch interpretieren.

---

## 9. Indicator vs Strategy Parität

Paritätsziel: möglichst identische Entscheidungslogik in beiden Skripten.

Bekannte Unterschiede sind intentional:

- Strategy enthält `strategy.entry/close`-Semantik und Backtest-spezifische Aspekte.
- Indicator priorisiert Visualisierung/Alert-Integration.

Parität wird über dedizierte Tests abgesichert (regex/contract + behavioral simulator).

---

## 10. Test- und Qualitätssicherung

Wichtige Testmodule:

- `tests/test_skippalgo_pine.py`
- `tests/test_skippalgo_strategy_pine.py`
- `tests/test_behavioral.py`
- `tests/pine_sim.py` (event-order simulation)

Getestet werden u. a.:

- Strict Event Ordering
- Open-Window-Bypass-Varianten
- Marker-/Payload-Verträge
- Indicator/Strategy-Parität

---

## 11. Tuning-Leitplanken (technisch)

Empfohlene Reihenfolge:

1. Erst Gate-Qualität (Confidence/MTF/Macro) stabilisieren
2. Dann Forecast-Thresholds (`minDirProb`, `minEdgePP`) feinjustieren
3. Dann Strict-Margin/Adaptive-Range an Volatilität anpassen
4. Erst danach Risk-Parameter aggressiv verändern

Warnung:

- Zu viele gleichzeitige Parameteränderungen erschweren Root-Cause-Analyse bei Drift.

---

## 12. Operative Hinweise für Deployments

- Nach signifikanten Regeländerungen Alerts neu erstellen (TV cached Conditions/Messages je nach Setup).
- CI/PR-Status als primäre Verifikationsquelle verwenden; harte Testzahlen in statischen Docs vermeiden.
- Bei Symbol-/Regime-Wechsel ggf. Kalibrierungs-Warmup erneut einplanen.

---

## 13. Änderungsfokus v6.2.21–v6.2.22 (kompakt)

- Strict UX/Marker erweitert
- Open-Window feingranular gemacht
- REV-BUY Floor (`pU >= 0.37`) ergänzt
- Strict always-on (außer Open-Window)
- Strict Marker side-aware an Long/Short Label-Sichtbarkeit gekoppelt
- Copilot-Review-Kommentare technisch aufgelöst

---

## 14. Referenzen im Repository

- Hauptskripte: `SkippALGO.pine`, `SkippALGO_Strategy.pine`
- Changelog: `CHANGELOG.md`, `docs/CHANGELOG_v6.2.21_strict_mode_ux.md`
- Strategy Guide: `docs/TRADINGVIEW_STRATEGY_GUIDE.md`
- Troubleshooting: `docs/TROUBLESHOOTING*.md`
