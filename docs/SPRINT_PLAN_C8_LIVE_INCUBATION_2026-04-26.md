# Sprint-Plan C8 — Live-Inkubation (Paper → Small-Size Live)

**Datum:** 2026-04-26
**Owner:** Steffen Preuss
**Sprint-Größe:** 5-8 Werktage Setup + **3-6 Monate Wartezeit/Inkubation**
**Status:** Plan, noch nicht gestartet
**Voraussetzung:** C1+C2+C3+C4+C5+C6+C7 fertig, mindestens 1 SMC-Variante mit Track-Record-Gate-Status "amber" oder "green"

## Ziel

Statistische Validierung des Backtest→Live-Pfads. Liefert das letzte fehlende Puzzlestück für die Verkaufbarkeit:

> **Live-Performance-Drift gegenüber Backtest-Sharpe ist <50% UND mindestens 30 Live-Trades über ≥3 Monate (ideal 6) sind dokumentiert.**

Track-Record-Gate-Akzeptanzkriterium aus Master-Doc:

| Metrik | Mindestwert |
|---|---|
| Live-Inkubation-Dauer | ≥ 3 Monate, ideal 6 Monate |
| Live-Trades | ≥ 30 (Quelle: [QuantVPS Paper-to-Live Guide](https://www.quantvps.com/blog/paper-trading-simulators)) |
| Live-Sharpe ÷ Backtest-Sharpe | ≥ 0.50 |
| Position-Size live | 10-25% des Ziel-Sizings ([QuantVPS](https://www.quantvps.com/blog/paper-trading-simulators)) |

Ohne C8 ist der Track-Record nicht extern verkaufbar — Backtest allein, selbst mit C2-C6-Härtung, hat in der Investor-Community keinen Wert ohne Live-Bestätigung ([Reddit r/algotrading Konsens](https://www.reddit.com/r/algotrading/comments/uls93l/how_do_you_determine_if_a_you_are_going_deploy/)).

## Inventur (✅ vorhanden / ❌ Greenfield)

### IBKR-Stack vorhanden
- ✅ `ib_async>=2.1.0` in `requirements.txt`
- ✅ `scripts/run_ibkr_open_execution.py` (291 Zeilen) — Execution-Event-Log + Reconnect-Supervision
- ✅ `scripts/execute_ibkr_watchlist.py` (1118 Zeilen) — vollständige Order-Pipeline:
  - `IBKRConnectionConfig` `:44` mit Default-Port 7497 (Paper-Trading)
  - `IBKRExecutionConfig` `:54`, `IBKROrderIntent` `:66`
  - `_attempt_ibkr_reconnect()` `:191`, `_call_with_reconnect()` `:258`
  - `monitor_open_orders()` `:524`, `reconcile_fills_and_positions()` `:562`
  - `cancel_symbol_orders_after()` `:620`, `flatten_after()` `:653`
  - `place_order_intents_with_ib()` `:725`, `place_order_intents()` `:805`
- ✅ Stop-Loss-Felder integriert: `execute_ibkr_watchlist.py:74` `stop_loss: float`, `:390` `stop_loss = round(_as_valid_price(...))`
- ✅ Trailing-Stop-Build via `_build_tp_trail_orders()` `:485`
- ✅ `tests/test_execute_ibkr_watchlist.py` und `tests/test_execute_ibkr_watchlist_uplift_j.py` existieren

### Long-Dip-Strategie als Live-Beispiel vorhanden
- ✅ `scripts/generate_databento_watchlist.py` mit `LongDipConfig` und `build_daily_watchlists()`
- ✅ `LONG_DIP_*` Konfiguration in `strategy_config.py`
- ⚙️ Dies ist eine **bestehende, separat von SMC** laufende Live-Pipeline. C8 nutzt diese Infrastruktur, **portiert SMC-Setups dorthin**.

### Outcome-Backfill für Live→Backtest-Vergleich
- ✅ `open_prep/outcome_backfill.py:9` mit Comment "calibration feedback loop has labeled data"
- ✅ `backfill_outcomes()` `:211`, Wrapper `:420`
- ✅ `open_prep/outcomes.py:13` "calibration feedback loop"
- ⚙️ Diese Funktion wird Live-Trades zurück in den Outcome-Stream schreiben — Pipeline ist bereit.

### Atomic-Write für Audit-Trail
- ✅ `scripts/smc_atomic_write.py` mit `atomic_write_parquet/csv/text/json` `:25-28`

### Was fehlt
- ❌ Keine `scripts/run_smc_live_incubation.py` — SMC-spezifische Live-Pipeline
- ❌ Kein Live-vs-Backtest-Drift-Detector (Statistik-Vergleich Live-Sharpe vs OOS-Sharpe)
- ❌ Kein Kill-Switch / Circuit-Breaker (verifiziert: `grep -ri "kill_switch\|circuit_breaker\|max_loss"` zeigt keine Production-Implementierung)
- ❌ Kein Live-Position-Size-Sizer (10-25% Skalierung gegen Backtest-Ziel-Size)
- ❌ Keine Live-Inkubations-Reporting-Pipeline (`cache/live/incubation_<date>.json`)

## Strategischer Pfad

Schrittfolge nach [QuantVPS Paper-to-Live Guide](https://www.quantvps.com/blog/paper-trading-simulators):

```
Build Strategy (DONE) → Backtest (C2-C6) → Paper Trade (C8 Phase A) →
Small-Size Live Testing (C8 Phase B) → Scale (C8+ Stretch)
```

**Phase A — IBKR Paper-Account (Wochen 1-4):**
- Port 7497 (Paper) statt 7496 (Live) — bereits Default in `IBKRConnectionConfig`
- 100% Position-Size aus SMC-Calibration übernehmen
- Slippage-Model 0.5% einrechnen ([QuantVPS](https://www.quantvps.com/blog/paper-trading-simulators))
- Mindestens 20 Paper-Trades, Drift Paper-Sharpe vs Backtest-OOS-Sharpe <30%

**Phase B — IBKR Live, Small-Size (Monate 2-6):**
- Port 7496 (Live) nach Phase-A-Pass
- Position-Size **10-25%** des Backtest-Ziel-Sizings ([Alpaca Guide](https://alpaca.markets/learn/paper-trading-vs-live-trading-a-data-backed-guide-on-when-to-start-trading-real-money), [QuantVPS](https://www.quantvps.com/blog/paper-trading-simulators))
- Mindestens 30 Live-Trades über ≥3 Monate
- Wöchentlicher Live-vs-Backtest-Drift-Check
- Hard Kill-Switch bei DD >2× Backtest-Max-DD oder Live-Sharpe <0 nach 15 Trades

**Phase C — Scale-Up (nur bei Phase-B-Pass):**
- Schrittweise auf 100% Ziel-Size, 10-Punkt-Increments
- Out-of-Scope für C8, Voraussetzung für C9-Drift-Alert + Verkaufs-Material

## Tasks

### T1 (Tag 1) — SMC-Strategy-Adapter zu IBKR-Order-Pipeline ⚙️🧪

`scripts/smc_to_ibkr_adapter.py` (oder Funktion in bestehender Pipeline):

```python
def build_ibkr_intents_from_smc_setups(
    setup_records: list[dict[str, Any]],
    execution_cfg: IBKRExecutionConfig,
    size_scale: float = 1.0,  # 0.1-0.25 für Phase B
    paper_mode: bool = True,
) -> list[IBKROrderIntent]:
    """
    Transformiert SMC-Setup-Output (entry, stop, take-profit) in
    IBKROrderIntent-Liste, kompatibel mit place_order_intents().
    """
```

Reuse:
- `IBKROrderIntent` `:66` aus `scripts/execute_ibkr_watchlist.py`
- `_apply_common_order_fields()` `:471`
- `_build_tp_trail_orders()` `:485`

Test-Pins in `tests/test_smc_to_ibkr_adapter.py`:
- SMC-Setup mit Entry/SL/TP wird zu OrderIntent mit korrekten Preisen
- size_scale=0.1 reduziert quantity auf 10%
- paper_mode=True erzwingt Port 7497, paper_mode=False Port 7496
- Stop-Loss-Validation: SL muss anders als Entry sein (vermeidet Zero-Risk-Orders)

### T2 (Tag 1-2) — Position-Size-Scaler + Hard-Limits ⚙️🧪

`open_prep/live_risk_limits.py` (greenfield):

```python
@dataclass(frozen=True)
class LiveRiskLimits:
    max_loss_per_trade_usd: float = 200.0   # Phase B Default
    max_loss_per_day_usd: float = 1000.0
    max_open_positions: int = 5
    max_drawdown_from_peak: float = 0.10  # 10% Peak-DD = Kill
    size_scale: float = 0.10              # Phase B Default
    paper_mode: bool = True

def check_pre_order_limits(intent: IBKROrderIntent, limits: LiveRiskLimits, account_state: dict) -> tuple[bool, str]:
    """
    Returns (allowed, reason). False blockt Order-Submission.
    """

def check_kill_switch(account_state: dict, limits: LiveRiskLimits) -> tuple[bool, str]:
    """
    Returns (continue_trading, reason). False löst flatten_after() aus.
    """
```

Test-Pins:
- Per-Trade-Loss-Cap funktioniert
- Daily-Loss-Cap aggregiert korrekt
- Drawdown-from-Peak triggert Kill bei 10%
- size_scale=0.1 wird auf quantity angewendet

Hook-Integration in `place_order_intents_with_ib()` `:725`:
- Pre-Order: `check_pre_order_limits()` → bei `False` skip + log
- Post-Fill: `check_kill_switch()` → bei `False` `flatten_after(0)`

### T3 (Tag 2-3) — Live-Run-Executable mit Audit-Log ⚙️

`scripts/run_smc_live_incubation.py`:

```bash
python scripts/run_smc_live_incubation.py \
  --phase paper \           # paper | live_small | live_full
  --setup-types smc_breaker,smc_zone \
  --size-scale 0.10 \
  --max-loss-per-trade 200 \
  --max-loss-per-day 1000 \
  --max-dd-from-peak 0.10 \
  --output cache/live/incubation_<date>.jsonl
```

Workflow:
1. Lade SMC-Setups aus letztem Calibration-Run
2. Filter: nur Variants mit Track-Record-Gate-Status amber/green (aus C7)
3. `build_ibkr_intents_from_smc_setups()`
4. `check_pre_order_limits()` für jeden Intent
5. `place_order_intents()` (existing)
6. Monitor + Reconcile (existing `monitor_open_orders` + `reconcile_fills_and_positions`)
7. Kill-Switch alle 60s prüfen
8. Audit-Log via `atomic_write_jsonl`

Output-Schema `cache/live/incubation_<date>.jsonl`:

```json
{
  "ts": "2026-XX-XXTHH:MM:SSZ",
  "phase": "live_small",
  "variant": "smc_breaker_btc",
  "intent_id": "...",
  "action": "submitted | filled | rejected | flattened",
  "entry_price": 102.34,
  "stop_loss": 100.50,
  "take_profit": 105.20,
  "size_usd": 250.0,
  "size_scale": 0.10,
  "fill_price": 102.36,
  "slippage_pct": 0.020,
  "outcome_pnl_usd": null,    // backfill nach Trade-Close
  "outcome_r_multiple": null,
  "kill_switch_triggered": false
}
```

### T4 (Tag 3-4) — Live-vs-Backtest-Drift-Detector ⚙️🧪

`scripts/compute_live_drift.py`:

```python
def compute_live_drift(
    live_jsonl: Path,
    backtest_calibration: Path,
    min_trades: int = 15,  # Frühest mögliche Drift-Bewertung
) -> dict[str, Any]:
    """
    Vergleicht Live-Sharpe vs Backtest-OOS-Sharpe pro Variant.
    Returns Drift-Score 0-1 (1=identisch, 0=kompletter Drift).
    """
```

Methoden:
- Live-Sharpe annualisiert (mit Bailey-Lopez-de-Prado-PSR aus C6)
- Backtest-OOS-Sharpe aus C2-Walk-Forward
- Drift = `live_sharpe / max(backtest_sharpe, 0.001)` mit Cap [0, 1.5]
- Per-Trade-Slippage-Distribution + KS-Test gegen erwartete (0.5% mean)
- Hit-Rate-Konsistenz: 95%-CI aus Bootstrap (C3) — Live-HR muss in CI liegen

Test-Pins:
- Identische Live + Backtest → Drift=1.0
- Live-Sharpe = 0, Backtest-Sharpe = 1 → Drift=0.0
- KS-Test Slippage-Distribution feuert bei Mismatch

Output `cache/live/drift_<date>.json`:

```json
{
  "computed_at": "2026-XX-XX",
  "live_window_days": 90,
  "variants": [
    {
      "variant": "smc_breaker_btc",
      "n_live_trades": 24,
      "live_sharpe": 0.71,
      "backtest_sharpe": 0.93,
      "drift_score": 0.76,
      "slippage_ks_p": 0.32,
      "hr_in_bootstrap_ci": true,
      "verdict": "acceptable"  // pass | acceptable | concerning | fail
    }
  ]
}
```

### T5 (Tag 4-5) — Outcome-Backfill-Hook ⚙️🧪

Integration in bestehenden `open_prep/outcome_backfill.py:211 backfill_outcomes()`:

- Live-Trades aus `cache/live/incubation_*.jsonl` lesen
- Per-Trade-Outcome (PnL, R-Multiple) berechnen nach Trade-Close
- In Outcome-Stream zurückschreiben für Calibration-Feedback-Loop
- Test-Pin: Live-Trade mit fill_price=102 + close=104 + stop=100 → R-Multiple=1.0 korrekt

### T6 (Tag 5-6) — Dashboard-Integration (C7-Pflug) ⚙️🧪

`tab_live_incubation.py` aus C7-Stub konkretisieren:

- Per-Variant Live-Metriken: n_live, live_sharpe, drift_score
- Plotly: Equity-Curve Live vs Backtest-Erwartung
- Slippage-Histogramm Live vs Erwartung 0.5%
- Kill-Switch-Event-Log (rot bei aktiv)

Test-Pin: Tab rendert mit Mock-`drift_<date>.json`-Daten.

### T7 (Tag 6-7) — Documentation + Phase-Gates ⚙️🧪

`docs/c8_live_incubation_runbook.md`:

- Pre-Phase-A-Checkliste:
  - C2-C6 alle gemerged
  - C7-Dashboard läuft
  - IBKR-Paper-Account aktiv
  - mindestens 1 Variant mit Gate-Status "amber"
- Phase-A-Pass-Kriterien (4 Wochen):
  - ≥20 Paper-Trades
  - Paper-Sharpe vs OOS-Sharpe Drift <30%
  - Slippage-Distribution KS-Test p>0.05
- Phase-B-Pass-Kriterien (3-6 Monate):
  - ≥30 Live-Trades
  - Live-Sharpe ÷ Backtest-Sharpe ≥ 0.50
  - Kill-Switch nicht ausgelöst
  - Max-DD < 2× Backtest-Max-DD
- Phase-C-Scale-Up-Decision-Tree

Phase-Gates müssen **manuell von Steffen** signiert werden — kein Auto-Promotion. Begründung: live_full hat reales Geld-Risiko.

### T8 (Wartezeit 3-6 Monate) — Inkubations-Phase

Während dieser Zeit:
- Tägliche Drift-Checks via Cron (siehe C9 für Alerting)
- Wöchentlicher manueller Review
- Bei Phase-B-Trigger: Sprint C8.B-Reactivation (klein, <2 Tage) für Live-Switch

## Speed-Hebel-Anwendung

- **AI-Repo-Tool**: SMC-zu-IBKR-Adapter ist Pattern-Code mit klaren Test-Inputs — 70-80% AI-Treffer realistisch.
- **pytest-xdist**: ✅ in `requirements.txt`. Reconnect/Order-Lifecycle-Tests parallel.
- **Reuse `execute_ibkr_watchlist.py`-Stack**: vollständig — `place_order_intents_with_ib`, `monitor_open_orders`, `reconcile_fills_and_positions`, `flatten_after` sind Production-erprobt.
- **Reuse `outcome_backfill.py`**: Feedback-Loop bereits gebaut, nur Live-Quelle hinzufügen.
- **Sequentiell zu C7**: Dashboard-Integration in T6 setzt C7-Stub voraus.
- **2-Iterations-Limit**: bei Phase-A vor allem **Geduld** — keine Über-Iteration in 4-Wochen-Phase, Daten brauchen Zeit.
- **Anti-Hebel: Live-Trading nicht beschleunigen**. 3-Monate-Inkubation ist nicht abkürzbar — [Reddit-Konsens](https://www.reddit.com/r/algotrading/comments/uls93l/how_do_you_determine_if_a_you_are_going_deploy/) und [Roguequant Substack](https://roguequant.substack.com/p/the-75-win-rate-strategy-i-found) bestätigen 3-Monate-Mindest-Inkubation. Versuch der Verkürzung = invalide Stichprobe.

## Risiken + Gegenmaßnahmen

| Risiko | Gegenmaßnahme |
|---|---|
| IBKR-API-Disconnect mid-trade | Reuse `_attempt_ibkr_reconnect` `:191` (Production-erprobt) |
| Slippage höher als erwartet | T4 KS-Test triggert Drift-Verdict "concerning" → Phase-Halt |
| Kill-Switch versagt → Verlust | Doppelte Verteidigung: Pre-Order-Cap + Post-Fill-Drawdown-Check |
| Live-Sharpe-Schwankung verleitet zu Premature-Promotion | Phase-Gates manuell signiert, keine Auto-Promotion |
| Backtest-Bias: Curve-Fit erst Live sichtbar | C2 (Walk-Forward) + C4 (Permutation) sollten dies vorab abfangen — ansonsten "fail"-Verdict in T4 |
| Anwendungspezifische SMC-Setups skalieren schlecht auf Live | Phase-A 100%-Size, Phase-B 10-25%-Size erlaubt Cushion zur Validation |
| Marktphase ändert sich während Inkubation | C5-Regime-Stratifikation aus Backtest macht Mismatch sichtbar |

## Akzeptanzkriterien (Sprint-Setup, vor 3-Monate-Wartezeit)

- [ ] `smc_to_ibkr_adapter.py` mit 4+ Test-Pins
- [ ] `live_risk_limits.py` mit Pre-Order + Kill-Switch + 4+ Test-Pins
- [ ] `run_smc_live_incubation.py` läuft gegen IBKR Paper-Account end-to-end
- [ ] `compute_live_drift.py` mit Drift-Score 0-1 + KS-Test
- [ ] Outcome-Backfill-Hook integriert
- [ ] `tab_live_incubation.py` (aus C7) rendert mit Mock-Drift-Daten
- [ ] Runbook `docs/c8_live_incubation_runbook.md` mit Phase-Gates
- [ ] Mindestens 1 Variant mit Gate-Status "amber" oder "green" als Inkubations-Kandidat ausgewählt

## Akzeptanzkriterien (nach 3-6 Monate Inkubation)

- [ ] ≥30 Live-Trades dokumentiert
- [ ] Live-Sharpe ÷ Backtest-Sharpe ≥ 0.50 (mindestens 1 Variant)
- [ ] Kill-Switch nicht ausgelöst
- [ ] Max-DD live < 2× Backtest-Max-DD
- [ ] Drift-Verdict "pass" oder "acceptable"
- [ ] **Damit ist der Track-Record extern verkaufbar.**

## Out-of-Scope

- Multi-Broker (nur IBKR via `ib_async`)
- Crypto-Exchanges (ccxt nicht installiert — späterer Sprint)
- Auto-Position-Sizing über Kelly-Kriterium (kommt mit Scale-Phase C)
- Live-WebSocket-Streaming-UI (C9 oder später)
- Marketing/Verkaufs-Material (Track-Record-Verkaufs-Asset ist Folge-Sprint nach C8.B-Pass)

## Quellen

- [QuantVPS — Paper Trading Simulators (März 2026)](https://www.quantvps.com/blog/paper-trading-simulators) — 30-50 Trades, 3-6 Monate, 10-25% Size, 0.5% Slippage-Default
- [Alpaca Markets Data-Backed Guide (August 2025)](https://alpaca.markets/learn/paper-trading-vs-live-trading-a-data-backed-guide-on-when-to-start-trading-real-money) — Paper-zu-Live-Transition Daten
- [QuantInsti IBKR-Bot-Guide (März 2026)](https://www.quantinsti.com/articles/build-trading-bot-interactive-brokers-python-chatgpt/) — `ib_async`-Pattern
- [PickMyTrade IBKR Automated Trading Guide 2026](https://blog.pickmytrade.io/ibkr-automated-trading-system-guide-2026/) — API-Updates Oktober 2025, Risk-Tools
- [Reddit r/algotrading — Live-Deploy-Kriterien](https://www.reddit.com/r/algotrading/comments/uls93l/how_do_you_determine_if_a_you_are_going_deploy/) — 2-3 Monate Demo-Inkubation
- [Roguequant Substack (August 2025)](https://roguequant.substack.com/p/the-75-win-rate-strategy-i-found) — 3 Monate / 30 Trades als Minimum
- [Bajaj Broking — Paper-zu-Live-Transition](https://www.bajajbroking.in/blog/how-to-switch-from-paper-trading-to-live-trading) — Mikro-Position-Test
- [TradersPost — Paper-Trading-Validierung](https://blog.traderspost.io/article/paper-trading-strategy-development-guide) — Variation-Monitoring
- [arXiv 2604.18821 — Live-Performance-Analyse](https://arxiv.org/pdf/2604.18821) — 6-Monate-Horizon-Sample-Sizes
