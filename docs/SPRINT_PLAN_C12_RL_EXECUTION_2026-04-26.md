# Sprint-Plan C12 — Reinforcement Learning für Execution + Sizing

**Datum:** 2026-04-26
**Branch:** `sprint/c12-rl-execution`
**Status:** Aktive Implementierung — Phase A (Slippage-Modell + Simulator + TWAP/VWAP-Baselines + Safety-Layer + Drift-Monitor) im Branch `sprint/c12-rl-execution` (PR #312). PPO/SAC-Agenten als optionale stable-baselines3-Backends gegated. Pipeline läuft Ende-zu-Ende auf synthetischen Trades; Live-Daten-Wiring ist ein Dataset-Swap aus dem Order-Lifecycle (siehe `rl/README.md` auf dem PR-#312-Branch).
**Vorgänger:** C2-C9 (Statistik-Härtung), C10 (ML-Layer auf Familien)
**Sprache:** Deutsch
**Trigger-Bedingung:** Erst aktivieren, **nachdem** mindestens eine SMC-Familie das C7/C8-Promotions-Gate übersprungen hat und **seit ≥ 4 Wochen** live im Inkubations-Modus läuft.

---

## Ziel

Einen Reinforcement-Learning-Layer einziehen, der **nicht entscheidet, ob gehandelt wird**, sondern **wie** gehandelt wird — Order-Slicing, Eintritts-Timing, Position-Sizing, Stop-Management. Das Setup-Signal kommt unverändert aus der regelbasierten SMC-Pipeline plus dem C10-ML-Layer; RL übernimmt nur die **Execution-Schicht**.

**Verbindlicher Vertrag:** RL ist Execution-Optimierung, nicht Setup-Erkennung. Falsche Setups durch RL "schöner zu klicken" ist explizit Out-of-Scope. Wenn die zugrundeliegende Familie kein Edge hat, wird auch das RL-Modul nicht aktiviert.

**Drei Phasen, sequentiell, mit Trigger-Gate dazwischen:**

1. **Phase A — Slippage-Modell-Kalibrierung** (Voraussetzung für jede sinnvolle RL-Belohnung)
2. **Phase B — RL-Order-Slicing** (Industrie-Standard, niedriges Risiko)
3. **Phase C — RL-Position-Sizing** (höheres Risiko, separate Promotion)

Out of Scope für C12: RL-basierte Setup-Detection, RL auf Familien-Auswahl, Multi-Agent-RL — alle als Forschungs-Spike-Kandidaten markiert; ein Ablageort unter `docs/research/` würde dafür bei Bedarf im Rahmen des jeweiligen Spikes neu angelegt.

---

## Inventur (✅ vorhanden / ❌ Greenfield)

### Setup-Signal-Strom ✅ vorhanden (Voraussetzung)

C2-C9 + C10 liefern kalibrierte `(family, P(profitable | features), regime)` Tupel. RL konsumiert diesen Strom als Input, erzeugt ihn nicht.

### Live-Inkubations-Pipeline ✅ vorhanden

Aus C8 — Live-Outcome-Stream mit echten Slippage-Werten, Latency-Beobachtungen, Fill-Qualität. Das ist die einzige zuverlässige Quelle für RL-Belohnungs-Kalibrierung.

### Drift-Watchdog ✅ vorhanden

C9 — wird auf RL-Action-Distribution gespiegelt (Phase B/C).

### Promotions-Gate ✅ vorhanden

17-Punkte-Gate aus C7/C8. RL-Module gehen durch ein **eigenes** Promotions-Gate mit zusätzlichen Kriterien (Action-Distribution-Stabilität, Implementation-Shortfall-Verbesserung).

### Slippage-Modell ❌ Greenfield

Aktuell vermutlich vereinfachtes Spread-basiertes Modell. RL braucht ein **kalibriertes Almgren-Chriss-ähnliches Modell** mit temporärem und permanentem Market-Impact. Greenfield in Phase A.

### RL-Frameworks ❌ Greenfield

Es gibt heute **keine** RL-Library im Repo. Greenfield mit `stable-baselines3` (PPO/SAC/DQN) plus `gymnasium`-Environments.

### Training-Infrastruktur ❌ Greenfield

GPU-Compute-Cluster oder Cloud-GPU-Budget noch nicht etabliert. Phase B braucht ~100k-1M Episoden — auf CPU machbar, mit GPU schneller.

### Marktdaten-Tick-Stream ❌ Greenfield (für Phase B/C optimal)

Bar-Daten reichen für Phase A (Slippage-Modell-Kalibrierung), aber Phase B (Order-Slicing) profitiert massiv von Tick-Daten. Annahme im Plan: Bar-Daten Default, Tick-Daten als optionaler Boost-Pfad.

---

## Methoden-Foundation

### Phase A — Slippage- und Market-Impact-Modell

**Architektur:** Ein parametrisches Modell, das aus Live-Inkubations-Daten geschätzt wird und als RL-Belohnungs-Kompass dient.

- **Almgren-Chriss-Framework** ([Almgren-Chriss 2000 Optimal Execution of Portfolio Transactions](https://www.smallake.kr/wp-content/uploads/2016/03/optliq.pdf)):
  - Permanent Impact: linear in Order-Größe, modifiziert dauerhaft den Mid-Price
  - Temporary Impact: linear in Order-Geschwindigkeit, verschwindet nach Trade
  - Implementation Shortfall = Markt-Impact + Volatilitäts-Risiko + Spread-Kosten
- **Datenquelle:** Live-Outcome-Stream aus C8 — pro Trade Soll-Preis (Signal-Bar-Close) vs. Ist-Fill-Preis vs. Volume-Profil
- **Schätzung:** Bayesian Linear Regression mit Half-Normal-Prior auf Impact-Koeffizienten (verhindert negative Impact-Schätzung)
- **Validierung:** Walk-Forward-Splits mit MAE/RMSE auf Slippage-Vorhersage, MAE auf Implementation-Shortfall

**Akademische Basis:**
- [Almgren-Chriss 2000](https://www.smallake.kr/wp-content/uploads/2016/03/optliq.pdf) — Original-Framework
- [Gatheral 2010 No-Dynamic-Arbitrage and Market Impact](https://mfe.baruch.cuny.edu/wp-content/uploads/2014/12/qf2008.pdf)
- [Bouchaud-Farmer-Lillo 2009 How Markets Slowly Digest Changes](https://arxiv.org/abs/0809.0822)

### Phase B — RL-Order-Slicing

**Architektur:** Episodisches RL-Problem — gegeben eine Order-Größe `Q` und ein Zeit-Budget `T`, finde die Slicing-Sequenz, die Implementation Shortfall minimiert.

- **State-Space:** `(remaining_qty, remaining_time, current_volatility, current_spread, recent_volume_profile, signal_strength)`
- **Action-Space:** Diskret — `slice_size ∈ {0, 5%, 10%, 25%, 50%, 100%} × order_type ∈ {limit_at_mid, limit_aggressive, market}`
- **Reward:** `−ImplementationShortfall − λ·Variance` (mean-variance Objective wie in Almgren-Chriss)
- **Algorithmus:**
  - Default: **PPO** ([Schulman et al. 2017 Proximal Policy Optimization](https://arxiv.org/abs/1707.06347)) — robust, sample-effizient, Industrie-Standard
  - Alternative: **SAC** ([Haarnoja et al. 2018 Soft Actor-Critic](https://arxiv.org/abs/1801.01290)) — falls kontinuierlicher Action-Space gewünscht
  - Baseline: TWAP (Time-Weighted Average Price) und VWAP (Volume-Weighted Average Price) als nicht-RL-Vergleich
- **Training:**
  - Simulator basiert auf Phase-A-Slippage-Modell + historischer Volume-Profil-Replay
  - 100k-500k Episoden, je 50-200 Steps
  - Hyperparameter via Optuna mit Pruning

**Akademische Basis:**
- [Nevmyvaka-Feng-Kearns 2006 RL for Trade Execution](https://www.cis.upenn.edu/~mkearns/papers/rlexec.pdf) — erste produktionsnahe Studie
- [Schulman et al. 2017 PPO](https://arxiv.org/abs/1707.06347)
- [Haarnoja et al. 2018 SAC](https://arxiv.org/abs/1801.01290)
- [JPMorgan LOXM 2017](https://www.jpmorgan.com/insights/markets/algorithmic-trading/jpmorgan-introduces-loxm-2017) — Production-Anwendung
- [Ning-Lin-Jaimungal 2018 Double Deep Q-Learning for Optimal Execution](https://arxiv.org/abs/1812.06600)

### Phase C — RL-Position-Sizing

**Architektur:** Komplementäres RL-Problem — gegeben Setup-Signal-Stärke `P(profitable)` und Portfolio-Zustand, wähle Positionsgröße zwischen 0 und Risk-Budget-Cap.

- **State-Space:** `(signal_strength, current_drawdown, recent_volatility, regime_id, family_id, time_since_last_trade, account_equity)`
- **Action-Space:** Kontinuierlich `size_pct ∈ [0, max_risk_per_trade]` mit `max_risk_per_trade = 1%` als Hard-Cap
- **Reward:** `log(equity_t / equity_{t-1})` (Kelly-äquivalent, log-utility) **MIT** Drawdown-Penalty `−κ·max(0, drawdown − threshold)²`
- **Algorithmus:** SAC (kontinuierlich, off-policy, sample-effizient)
- **Sicherheits-Constraint:** Hard-Cap auf Position-Size auch wenn RL es verletzen wollte — RL ist **Empfehlung**, Risk-Manager hat Veto
- **Training:**
  - Walk-Forward-Episoden auf historischen Trades
  - Stress-Test auf Drawdown-Szenarien (2008, 2020-03, eigene historische Drawdowns)
  - Min-200k Episoden mit Bootstrap-Resampling

**Akademische Basis:**
- [Kelly 1956 A New Interpretation of Information Rate](https://www.princeton.edu/~wbialek/rome/refs/kelly_56.pdf) — Optimal-Sizing-Theorie
- [Moody-Saffell 2001 Learning to Trade via Direct Reinforcement](https://www.cs.cmu.edu/~ggordon/780-fall07/readings/Moody-and-Saffell-2001-IEEE-tnn-direct-reinforcement.pdf)
- [Deng et al. 2017 Deep Direct Reinforcement Learning for Financial Signal Representation and Trading](https://ieeexplore.ieee.org/document/7407387)
- [Lillicrap et al. 2016 DDPG](https://arxiv.org/abs/1509.02971)

---

## Tasks

### T1 (Tag 1) — Trigger-Gate-Verifikation + Inventur ⚙️

- Verifizieren, dass mindestens eine Familie in C8-Live-Inkubation läuft seit ≥ 4 Wochen mit Outcomes
- Slippage-Daten-Vollständigkeit prüfen: pro Trade müssen `signal_ts`, `decision_ts`, `fill_ts`, `fill_price`, `mid_at_signal`, `volume_at_signal` vorhanden sein
- Falls Trigger-Gate nicht erfüllt: Sprint pausiert, Bericht in `docs/c12_trigger_blocked.md`
- Schema-Lock für `rl/schemas/v1_execution_state.json`

**Deliverable:** Trigger-Gate-Verifikation grün ODER dokumentierter Aufschub.

### T2 (Tag 1-3) — Phase A: Slippage-Modell ⚙️🧪

- `rl/slippage/almgren_chriss_calibrator.py` — Bayesian Linear Regression auf Live-Daten
- Permanent + Temporary Impact-Koeffizienten pro Familie und pro Regime
- Cross-Validation auf Walk-Forward-Splits, MAE-Reporting
- Test: `tests/test_slippage_calibration.py` — Reproduzierbarkeit, Edge-Cases (zero-volume, gap-bars), Sanity-Check (Impact-Koeffizienten ≥ 0)
- Output: `models/slippage/v{date}.joblib` plus Diagnostik-Plots in `docs/c12/slippage_diagnostics_{date}.md`

**Deliverable:** Kalibriertes Slippage-Modell mit dokumentierten Konfidenz-Intervallen, MAE < 1bp auf Held-out.

### T3 (Tag 3-4) — Simulator + Baseline ⚙️🧪

- `rl/simulator/execution_env.py` — `gymnasium`-Environment mit Phase-A-Slippage als Belohnungsfunktion
- TWAP- und VWAP-Baselines als `rl/baselines/twap.py`, `rl/baselines/vwap.py`
- Backtest-Harness `scripts/run_execution_backtest.py` für reproduzierbare Vergleiche
- Test: `tests/test_execution_env_determinism.py` — gleicher Seed → gleiche Trajektorie

**Deliverable:** Simulator + Baselines, dokumentierte Performance-Werte für TWAP/VWAP auf historischen Trades.

### T4 (Tag 4-7) — Phase B: PPO-Order-Slicing ⚙️🧪

- `rl/agents/ppo_slicer.py` mit `stable-baselines3.PPO`
- Training-Loop in `scripts/train_ppo_slicer.py` mit `wandb`-Logging
- Hyperparameter via Optuna: lr ∈ [1e-5, 1e-3], gamma ∈ [0.95, 0.999], n_steps ∈ {128, 512, 2048}
- Walk-Forward-Splits mit Embargoes (kein Future-Leak)
- Evaluation: Implementation Shortfall vs. TWAP/VWAP — RL muss **mindestens 10% besser** sein, sonst Falsifikation
- Test: `tests/test_ppo_slicer_smoke.py` — synthetische Trajektorie, Konvergenz innerhalb 1k Episoden

**Deliverable:** PPO-Modell mit dokumentierter Outperformance gegen TWAP/VWAP ODER begründeter Falsifikations-Bericht.

### T5 (Tag 7-9) — RL-spezifisches Promotions-Gate ⚙️🧪

Ergänzung zum 17-Punkte-Gate:

- **G1:** Implementation-Shortfall-Verbesserung gegen TWAP ≥ 10% (FDR-q ≤ 0,10 via Permutationstest)
- **G2:** Action-Distribution-Stabilität — JS-Divergenz zwischen Train/Val Action-Distribution ≤ 0,1
- **G3:** Worst-Case-Episode-Drawdown — 99%-Quantil des Implementation-Shortfall ≤ 2× TWAP-Worst-Case
- **G4:** Robustheit gegen Slippage-Modell-Stress — Performance bleibt erhalten bei ±50% Impact-Koeffizienten-Perturbation
- **G5:** Latency-SLA — Action-Inferenz ≤ 5ms (sonst Live-Decisioning gefährdet)
- Test: `tests/test_rl_promotion_gate.py` — alle G1-G5 als pytest-Cases mit echten oder synthetischen Daten

**Deliverable:** RL-Promotion-Gate-Tests grün, Promotion-Record in `docs/c12/rl_promotion_record.md`.

### T6 (Tag 9-11) — Phase C: SAC-Position-Sizing ⚙️🧪

- `rl/agents/sac_sizer.py` mit `stable-baselines3.SAC`
- State-Space + Action-Space wie in Foundation-Section
- Risk-Manager-Veto-Layer in `rl/safety/hard_constraints.py` — überschreibt RL-Output bei Verletzung
- Stress-Test gegen historische Drawdown-Szenarien
- Test: `tests/test_sac_sizer_safety.py` — Hard-Cap wird **immer** durchgesetzt, auch bei adversarialem Input

**Deliverable:** SAC-Modell mit dokumentierter Sharpe/PSR-Verbesserung gegen Fixed-Sizing-Baseline ODER Falsifikations-Bericht.

### T7 (Tag 11-12) — Drift-Watchdog-Integration ⚙️🧪

- C9-Drift-Watchdog erweitern um RL-Action-Distribution als zusätzlichen Detektor
- PSI auf Action-Distribution (Schwelle 0,15 für Refit, 0,2 für Alarm — strenger als ML-Layer wegen direkter Live-Wirkung)
- Refit-Trigger: PSI-Threshold-Hit ODER Implementation-Shortfall-Regression > 20% gegen Baseline
- Alert-Klasse `RLDriftAlert` in C9-Schema
- Test: `tests/test_rl_drift_detection.py` — historisches Drift-Replay

**Deliverable:** RL-Drift in C9-Pipeline gespiegelt, Dashboard-Panel `docs/calibration/rl_drift.html` (intern).

### T8 (Tag 12-13) — Live-Shadow-Mode ⚙️🧪

Vor Live-Aktivierung mindestens **4 Wochen Shadow-Mode**:

- RL-Modul läuft parallel zur regelbasierten Execution, Vorschläge werden geloggt aber nicht ausgeführt
- Tägliche Reports: TWAP-Baseline vs. Regelbasiert vs. RL-Vorschlag
- Statistischer Vergleich nach 4 Wochen via Permutationstest
- Promotion zu Live nur bei FDR-q ≤ 0,10 für Outperformance

**Deliverable:** Shadow-Mode-Cron läuft, Reporting-Pipeline aktiv, Promotion-Entscheidung dokumentiert.

### T9 (Tag 13-14) — Doku + Sprint-Close 🧪

- `docs/rl/architecture.md` — System-Diagramm
- `docs/rl/safety_constraints.md` — alle Hard-Caps und Veto-Regeln explizit
- ADR `docs/adr/2026-XX-rl-execution-layer.md`
- Eintrag im Master-Doc CLOUD_MIGRATION
- Sprint-Retro

**Deliverable:** Doku komplett, Sprint geschlossen, PR review-ready.

---

## Speed-Hebel-Anwendung

- **Bibliotheken statt Eigenbau:** `stable-baselines3`, `gymnasium`, `optuna`, `wandb` — alle peer-reviewed Industrie-Standard
- **Phase-A-Output als RL-Reward:** kein eigener Reward-Engineering-Loop, das Slippage-Modell ist die Belohnungsfunktion
- **Wiederverwendung C2-C9 + C10:** Walk-Forward-Splits, Promotions-Gate-Boilerplate, Drift-Watchdog, Cron — alles bestehend
- **Shadow-Mode statt Direct-Live:** kein finanzielles Risiko während der Validierung
- **Hard-Cap statt Hoffnung:** RL ist Empfehlung, Risk-Manager hat Veto — entkoppelt RL-Korrektheit von operativem Risiko

---

## Risiken + Gegenmaßnahmen

### Risiko 1 — Reward-Hacking durch unrealistisches Slippage-Modell

**Symptom:** RL findet Strategien, die im Simulator brillant sind, aber live versagen.
**Gegenmaßnahme:** Phase A muss MAE < 1bp auf Held-out erfüllen, sonst keine Phase B; Shadow-Mode (T8) als zusätzliche Realitäts-Prüfung; Stress-Test mit ±50% Perturbation der Impact-Koeffizienten (G4).

### Risiko 2 — Sample-Effizienz zu gering, Training divergiert

**Symptom:** PPO/SAC konvergieren nicht innerhalb 100k Episoden.
**Gegenmaßnahme:** Diskreter Action-Space in Phase B reduziert Komplexität, Optuna mit Pruning, Curriculum-Learning (start mit kleinen Order-Größen, langsam steigern).

### Risiko 3 — RL überstimmt Risk-Limits

**Symptom:** RL-Action verletzt 1%-Risk-per-Trade-Cap.
**Gegenmaßnahme:** Hard-Cap-Layer (`rl/safety/hard_constraints.py`) ist **separat** vom RL-Modell und nicht trainierbar — er überschreibt jede RL-Action ohne Ausnahme.

### Risiko 4 — Action-Distribution-Drift in Live

**Symptom:** RL-Verhalten driftet stillschweigend, Performance verschlechtert sich unbemerkt.
**Gegenmaßnahme:** Drift-Watchdog auf Action-Distribution (T7) mit strengerer Schwelle als ML-Layer; Auto-Rollback bei Implementation-Shortfall-Regression > 20%.

### Risiko 5 — Latency-SLA-Verletzung

**Symptom:** RL-Inferenz > 5ms, Live-Decisioning verzögert.
**Gegenmaßnahme:** Action-Inferenz-Latency-Test (G5) als Promotions-Gate, Modell-Quantisierung als Fallback (FP16 oder INT8), kleinere Network-Architektur falls nötig.

### Risiko 6 — Setup-Fehler durch RL kompensiert

**Symptom:** RL "rettet" schlechte Setups durch geschicktes Slicing, verschleiert Familien-Fehler.
**Gegenmaßnahme:** Promotion-Gate verlangt, dass die zugrundeliegende Familie **eigenständig** profitabel ist, **bevor** RL aktiviert wird. RL darf nicht der Grund sein, warum eine Familie das Gate übersteht.

### Risiko 7 — Trainings-Compute-Budget reicht nicht

**Symptom:** Optuna braucht > 1 Woche pro Familie für Hyperparameter-Search.
**Gegenmaßnahme:** Pre-trained Baselines (z.B. nur PPO mit Default-Hyperparametern), GPU-Cloud-Budget freischalten falls nötig, oder Phase B auf eine Familie pro Sprint beschränken statt alle vier parallel.

### Risiko 8 — Backtest-Lookahead durch Future-Volume

**Symptom:** Simulator nutzt Future-Volume-Profile, Live-Performance verschlechtert sich.
**Gegenmaßnahme:** Volume-Profile nur aus historischen Bars vor dem Decision-Zeitpunkt, Audit-Test `tests/test_rl_no_future_leak.py`.

---

## Akzeptanzkriterien

C12 ist abgeschlossen, wenn:

1. **Trigger-Gate erfüllt:** Mindestens eine Familie war ≥ 4 Wochen live in C8 mit Outcome-Daten
2. **Phase A:** Slippage-Modell kalibriert mit MAE < 1bp auf Held-out
3. **Phase B:** PPO-Slicer Implementation-Shortfall ≥ 10% besser als TWAP, FDR-q ≤ 0,10, alle G1-G5 grün ODER begründete Falsifikation
4. **Phase C:** SAC-Sizer dokumentierte Sharpe/PSR-Verbesserung gegen Fixed-Sizing-Baseline ODER begründete Falsifikation
5. **Hard-Caps:** Risk-Manager-Veto getestet, kann durch keine RL-Action umgangen werden
6. **Shadow-Mode:** ≥ 4 Wochen parallel-Lauf abgeschlossen, statistischer Vergleich dokumentiert
7. **Drift-Detection:** RL-Action-Distribution-Drift in C9 integriert
8. **Doku:** ADR, Architecture, Safety-Constraints, Promotion-Record, Sprint-Retro vorhanden
9. **Code-Qualität:** Coverage ≥ 80% auf `rl/` Modul, mypy strict, alle Tests grün

---

## Out-of-Scope mit Roadmap

### RL für Setup-Detection (nie geplant)

⚠ nur plausibel: RL als Setup-Generator wäre ein anderes Geschäftsmodell — der Falsifikations-Vertrag aus C2-C9 würde aufgeweicht, weil RL-Strategien per Design Reward-maximieren statt Edge-falsifizieren. Bewusst nicht im Plan.

### Multi-Agent-RL (Forschungs-Spike)

Multiple RL-Agenten, die gegeneinander oder gegen Marktteilnehmer agieren. Methodisch interessant, operativ unreif. 1-Tages-Spike in `docs/research/` möglich, kein Sprint.

### Foundation Models für Trade-Execution

[Reinformer (2023)](https://arxiv.org/abs/2305.07440), [Decision Transformer (2021)](https://arxiv.org/abs/2106.01345) als Alternative zu klassischem RL. Nach C12-Abschluss bewerten, separater Spike.

### Online-Learning ohne Offline-Pretraining

Pure Online-RL auf Live-Markt — verboten durch Risk-Management. Jedes RL-Modul muss Offline-vortrainiert sein, Online-Updates nur via Refit-Cron mit Promotion-Gate.

---

## Quellen

### RL-Algorithmen
- [Schulman et al. 2017 PPO](https://arxiv.org/abs/1707.06347)
- [Haarnoja et al. 2018 SAC](https://arxiv.org/abs/1801.01290)
- [Lillicrap et al. 2016 DDPG](https://arxiv.org/abs/1509.02971)
- [Mnih et al. 2015 DQN Nature](https://www.nature.com/articles/nature14236)

### RL für Trade-Execution
- [Nevmyvaka-Feng-Kearns 2006 RL for Optimized Trade Execution](https://www.cis.upenn.edu/~mkearns/papers/rlexec.pdf)
- [Ning-Lin-Jaimungal 2018 Double Deep Q-Learning for Optimal Execution](https://arxiv.org/abs/1812.06600)
- [JPMorgan LOXM 2017](https://www.jpmorgan.com/insights/markets/algorithmic-trading/jpmorgan-introduces-loxm-2017)
- [Moody-Saffell 2001 Direct Reinforcement Trading](https://www.cs.cmu.edu/~ggordon/780-fall07/readings/Moody-and-Saffell-2001-IEEE-tnn-direct-reinforcement.pdf)
- [Deng et al. 2017 Deep Direct RL for Trading](https://ieeexplore.ieee.org/document/7407387)

### Market-Impact-Modelle
- [Almgren-Chriss 2000 Optimal Execution](https://www.smallake.kr/wp-content/uploads/2016/03/optliq.pdf)
- [Gatheral 2010 No-Dynamic-Arbitrage and Market Impact](https://mfe.baruch.cuny.edu/wp-content/uploads/2014/12/qf2008.pdf)
- [Bouchaud-Farmer-Lillo 2009](https://arxiv.org/abs/0809.0822)

### Position-Sizing-Theorie
- [Kelly 1956 Information Rate](https://www.princeton.edu/~wbialek/rome/refs/kelly_56.pdf)

### Statistische Härtung (aus C2-C9)
- [Bailey-López de Prado 2012 PSR/MinTRL](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=1821643)
- [Benjamini-Hochberg 1995 FDR](https://www.jstor.org/stable/2346101)
- [Phipson-Smyth 2010 Permutation p-values](https://www.degruyter.com/document/doi/10.2202/1544-6115.1585/html)

---

## Evidenz-Marker-Zusammenfassung

- ✅ im Code (Voraussetzung): `EventFamily`, `FamilyScoringMetrics` aus C2-C9, ML-Layer aus C10
- 🧪 als Vertrag getestet: RL-Promotion-Gate G1-G5, Hard-Cap-Tests, Shadow-Mode-Permutationstests
- ⚙️ operativ vorgesehen: Slippage-Kalibrator, PPO-Slicer, SAC-Sizer, RL-Drift-Watchdog
- ⚠ nur plausibel: RL-Outperformance ist nicht garantiert — Phase B/C können ergebnislos abgebrochen werden, das ist ein gültiges Sprint-Outcome (genau wie bei C10)
