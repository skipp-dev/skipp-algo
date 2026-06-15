# Glossary — SkippALGO Nomenclature

Single source of truth for the abbreviations, sprint codes, phase names, and
domain vocabulary used across this repository. When a term here disagrees with
a code comment or an older doc, **this file wins** — open a PR to correct the
other reference.

> Scope note: definitions are grounded in [DECISIONS.md](DECISIONS.md), the
> `SPRINT_PLAN_C*` / `SPRINT_ROADMAP_*` docs, the `ADR-*` records, and the
> live-incubation code under `scripts/`. Entries marked _(unverified)_ are
> best-effort and should be confirmed before being relied on.

## How the naming schemes fit together

- **`C<n>` — Sprints.** Sequential delivery sprints on the calibration →
  live-incubation critical path (`C1` … `C14`).
- **`Phase <X>` — Live-incubation stages.** The maturity ladder a strategy
  climbs from paper to full size (`Phase A` → `Phase B` → …).
- **`F<n>` — Experiments / promotion-gate arms.** Named feature experiments
  evaluated by the promotion gate (e.g. `F2`).
- **`Plan <x.y>` — Structure specs.** Versioned specifications for the SMC
  structure engine (e.g. `Plan 2.8`).
- **`W<n><a-c>` / `Wave <n>` — Stat-review hardening waves.** Batched
  statistical-review remediation tracks.
- **`ADR-<nnnn>` — Architecture Decision Records.** Binding decisions; the
  dated entries live in [DECISIONS.md](DECISIONS.md).
- **`F-V<n>-<id>` — Audit/review finding IDs.** Versioned finding codes
  referenced from `CHANGELOG.md` and PR descriptions.

---

## Sprints (`C1` … `C14`)

| Code | Title | Notes |
|------|-------|-------|
| `C1` | Outcome-Tracking-Pipeline | Records realized outcomes for setups. |
| `C2` | Walk-Forward-Pipeline | Out-of-sample walk-forward evaluation. |
| `C3` | Bootstrap-CI | Bootstrap confidence intervals on performance. |
| `C4` | Permutation-Test | Significance testing via permutation. |
| `C5` | Regime-Stratifikation | Stratify results by market regime. |
| `C6` | Probabilistic-Sharpe + MinTRL | PSR and Minimum Track Record Length. |
| `C7` | Dashboard-Frontend | Track-record dashboard. |
| `C8` | Live-Incubation (setup) | First live-incubation scaffolding. |
| `C9` | Drift-Alert + Anomalie-Monitoring | Backtest- and live-mode drift alerts. |
| `C10` | ML-Layer | Machine-learning scoring layer. |
| `C11` | *(reserved / skipped)* | Sprint number reserved; no deliverable assigned. |
| `C12` | RL-Execution | Reinforcement-learning execution layer. |
| `C13` | **Live-Incubation Phase A** | 28-day paper incubation. Signed **NO-GO** 2026-06-09 (root cause: IBKR paper gateway never connected → zero trades). See [DECISIONS.md](DECISIONS.md). |
| `C14` | **Live-Incubation Phase B** | Promotion to `live_small`. **BLOCKED** on a re-signed `C13` GO. |

> The consolidated dependency graph and critical path live in
> `SPRINT_ROADMAP_C2_C9_CONSOLIDATED_2026-04-26.md`.

## Live-incubation phases & trading modes

| Term | Meaning |
|------|---------|
| `Phase A` | **Paper** incubation stage (the `C13` sprint). Dry-run; a zero `AccountState` is acceptable. |
| `Phase B` | **`live_small`** stage (the `C14` sprint). 10 % position size; real capital, gated. |
| `paper` | Trading phase: dry-run, no broker orders submitted by default. `_PHASE_DEFAULTS["paper"]["paper_mode"] = True`. |
| `live_small` | Trading phase: real orders at `PHASE_B_RECOMMENDED_SIZE_SCALE` (10 %). Requires `--account-state-json` and a passing `paper` eval report; `--risk-limits-json` is optional (defaults to `configs/live_risk_limits.json`). |
| `live_full` | Trading phase: real orders at 100 % size. Requires a passing `live_small` eval report; `--risk-limits-json` remains optional with the same default. |

Defined in [scripts/run_smc_live_incubation.py](../scripts/run_smc_live_incubation.py)
(`_PHASE_DEFAULTS`, `PHASE_B_RECOMMENDED_SIZE_SCALE`).

> Not to be confused with **“Phase C Analysis”** in `PHASE_C_ANALYSIS.md`,
> which is an unrelated non-behavioural code-cleanup inventory — _not_ a
> live-incubation stage.

## SMC — Smart Money Concepts

`SMC` = **Smart Money Concepts**, the structure-detection core. Canonical
implementation lives in `smc_core` / `smc_integration`
(see [ADR-001](ADR-001-open-prep-integration-boundary.md)).

| Term | Meaning |
|------|---------|
| `BOS` | **Break of Structure** — continuation of the prevailing trend. |
| `CHoCH` | **Change of Character** — early trend-reversal signal (see `SMC_Core_Engine.pine`). |
| `OB` | **Order Block** — institutional supply/demand zone. |
| `FVG` | **Fair Value Gap** — price imbalance / inefficiency. |
| `SWEEP` | **Liquidity Sweep** — stop-hunt past a prior high/low. |

These four families (`BOS`, `OB`, `FVG`, `SWEEP`) are the structure setups the
live-incubation pipeline tracks.

## Hero state / decision vocabulary

The "Hero" surface is the decision-first HUD state derived for each ticker and
mirrored between Python and the Pine dashboard (cross-checked by
`tests/test_pine_python_vocab_cross_check.py`).

| Term | Values |
|------|--------|
| `HERO_ACTION` | `ACTIVE`, `WATCH`, `AVOID`, `BLOCKED` |
| `TRADE_STATE` | `BLOCKED`, `DISCOURAGED` (gates entry: `regime_allows_entry = TRADE_STATE != "BLOCKED"`) |

## Experiments, specs & stat-review waves

| Term | Meaning |
|------|---------|
| `F2` | The **promotion-gate dual-arm experiment**, evaluated daily by [`.github/workflows/f2-promotion-gate-daily.yml`](../.github/workflows/f2-promotion-gate-daily.yml). |
| `Plan 2.8` | SMC structure spec covering the multi-timeframe stack (`5m / 15m / 1H / 4H`); `Phase-E2` is its cross-timeframe-structure milestone. |
| `W7a` / `W7b` / `W7c` | **Stat-review Wave 7** sub-tasks: `ledger-fail-closed`, `vote-integrity`, `redflag-staleness` respectively. |
| `Wave <n>` | A batched statistical-review hardening track (e.g. `Wave 8` = `stat-review/wave-8-fixes`). |
| `SPRT` | **(Wald) Sequential Probability Ratio Test** — one-sided sequential test used by the F2 gate. |
| `PSR` / `MinTRL` | **Probabilistic Sharpe Ratio** / **Minimum Track Record Length** (sprint `C6`). |

## Data providers

| Provider | Role |
|----------|------|
| `FMP` | Financial Modeling Prep — primary fundamentals/quotes; backs the trade-cards producer. |
| `Databento` | Market-data feed (feature-gated). |
| `Finnhub` | Quotes / fundamentals. |
| `NewsAPI.ai` | News enrichment (active path: `scripts/smc_newsapi_ai.py`). |
| `Benzinga` | News / calendar fallback. |
| `TradingView` | Technicals via `tradingview_ta` + Playwright `TV_STORAGE_STATE`. |
| `IBKR` / `TWS` | **Interactive Brokers** / **Trader Workstation** execution. TWS defaults: `7497` paper, `7496` live. IB Gateway convention: `4002` paper, `4001` live. Paper account numbers are prefixed `DU*`. |

## Process & audit codes

| Term | Meaning |
|------|---------|
| `ADR-<nnnn>` | **Architecture Decision Record**. Numbered records under `docs/`; dated decisions in [DECISIONS.md](DECISIONS.md). |
| `F-V<n>-<id>` | Versioned **audit/review finding ID** (e.g. `F-V5-F1`), referenced from `CHANGELOG.md`. |
| `WF-<nnn>` | **Workflow audit finding ID** (e.g. `WF-012`), used in `.github/workflows/*` comments. |
| `Open-Prep` | The pre-open briefing pipeline that emits ranked candidates and **trade cards**. |
| `data/phase-a-audit` | Data branch isolating Phase-A run artifacts from code history. |

---

_Maintained as the canonical nomenclature reference. Add new codes here in the
same PR that introduces them._
