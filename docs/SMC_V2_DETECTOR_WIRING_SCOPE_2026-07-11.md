# SMC v2 Detector Chain — Wiring Scope

**Status:** MOSTLY EXECUTED (2026-07-12) — WS2 + WS1 landed, WS4a shadow live,
Reaction Zone reworked; only WS3 (SMT) remains deferred. This was originally a
SCOPE / not-started decision doc; the workstreams below have since been built.
See the **Resolution status** section immediately below the TL;DR for the
per-workstream matrix. The body preserved beneath it is the original scoping
analysis (retained for provenance) — read it through the resolution lens.
**Date:** 2026-07-11 (resolution matrix appended 2026-07-12)
**Owner:** @preuss_steffen
**Provenance:** truth-audit of `smc_core` (2026-07-10/11). Findings F1 (detector
starvation + direction inversion) and F5 (SMT starvation); the audit only made
the docstrings honest (#3381) and left the wiring as an explicit deferred
project. This doc scopes that project.

---

## Resolution status (2026-07-12)

The scope below has since been executed for the sweep-trap / reaction-zone
lane. The direction-inversion "landmine" (see §1 and WS2) is **resolved** — do
not read it as an open decision.

| Workstream | Scope | Status | Landed by |
|---|---|---|---|
| **WS2 — direction mapping** | Unify `is_bullish_sweep` ⇔ SELL_SIDE (bullish setup = low swept, reclaim upward); BUY_SIDE ⇔ bearish | ✅ **RESOLVED** | #3406 (`smc_core/sweep_trap.py` docstring + logic; call-site `measurement_evidence.py`; end-to-end direction test) |
| **WS1 — sweep / reaction-zone plumbing** | Derive `swept_level`/`sweep_extreme`/`origin_level` so `classify_sweep_trap` runs on real sweeps | ✅ **WIRED (shadow, default-OFF)** | #3407 (`_derive_sweep_trap_geometry` in `measurement_evidence.py`; `classify_sweep_trap` now runs when `is_sweep_trap_enabled()`) |
| **WS4a — shadow observability + daily eval** | Grafana surface + committed daily Brier-delta ledger | ✅ **LIVE (observe-only)** | #3411 (daily shadow evaluation), #3414 (Grafana bridge/gauges/panel/stale alert) |
| **Reaction Zone semantics** | Correct reclaim semantics (level-cross + separate rejection band; drop the inverted discount) | ✅ **REWORKED (observe-only)** | #3501, follow-through study emit+eval #3503 |
| **WS3 — SMT correlated feed** | Provide `correlated_context` so `detect_smt_divergence` contributes | ⏸️ **DEFERRED** | still input-starved in production (only tests build `correlated_context`) |

**Net current state.** `classify_sweep_trap()` and `compute_reaction_zone()`
run on real sweeps behind `ENABLE_SWEEP_TRAP` / `ENABLE_REACTION_ZONE`
(default-OFF, observe-only — recorded for the follow-through study, **no score
weight applied**). Only **SMT** remains productively input-starved (WS3). Any
score-budget weight for the sweep/reaction lane still awaits the shadow-Brier
evidence gate described in WS4b.

---

## TL;DR

The three v2 "Phase B/C/E" detectors — `sweep_trap`, `reaction_zone`,
`smt_divergence` — are documented as integrated but are **starved of inputs at
every production entry point**. Turning their flags on today changes almost
nothing. Making them useful is a **feature project**, not a fix, and it carries
a **direction-inversion landmine** that must be defused first.

Recommended phasing: **Phase 1 (direction fix)** is a cheap, standalone
correctness fix — do it independently. **Phase 2 (data plumbing + shadow
observe)** is a scoped mini-project gated on **evidence** (Brier/hit-rate delta)
before any score-budget weight is granted. **Phase 3 (SMT correlated feed)** is
the most expensive with the least certain payoff — defer until it stands on its
own.

---

## 1. Current state (precise — it is NOT 100 % dead)

There are **two layers**, and they behave differently:

| Layer | Functions | Behavior today |
|---|---|---|
| **Shallow `detect_*` wrappers** | `detect_sweep_trap`, `detect_reaction_zone` (read the lean `liquidity_sweeps` enrichment) | Run when their flag is set; currently only drive a **freshness downgrade** (`scripts/smc_signal_quality.py:670–676`). Coarse, but they *do* something. |
| **Deep quality functions** | `classify_sweep_trap`, `compute_reaction_zone`, `detect_smt_divergence` | **Starved.** `classify_sweep_trap` needs `swept_level`/`sweep_extreme`/`origin_level`; the gate `candidate["swept_level"] > 0` (`smc_integration/measurement_evidence.py:873`) is never true. SMT needs `correlated_context`, which only tests build → its **4 budget points** always contribute 0. |

**v2 score budget (sum = 100)** — `scripts/smc_signal_quality.py:96–103`:

```
STRUCTURE 18 · SESSION 18 · LIQUIDITY 12 · OB 12 · FVG 12 · COMPRESSION 12 · CONFLUENCE 12 · SMT 4
```

`sweep_trap` / `reaction_zone` have **no dedicated budget line** — they act via
the freshness downgrade and (once wired) the sweep contribution inside the
CONFLUENCE bucket. Any new weight must come out of an existing bucket to keep
the sum at 100.

### The direction-inversion landmine (must fix first)

> **RESOLVED by #3406 (2026-07-12).** The mapping below was unified to
> `is_bullish_sweep = True` ⇔ SELL_SIDE (bullish setup, reclaim upward) and
> `False` ⇔ BUY_SIDE (bearish, reclaim downward), across the classifier logic,
> its docstring, and the `measurement_evidence.py` call site, with an
> end-to-end direction test. The description below is retained for provenance;
> it is **no longer an open landmine**.

Producer convention (`scripts/smc_liquidity_engine.py:107/132`,
`scripts/smc_liquidity_sweeps.py:75–82`):

- **SELL_SIDE** sweep = a **low** was taken (`low < level && close > level`) → **bullish** setup (reversal up).
- **BUY_SIDE** sweep = a **high** was taken (`high > level && close < level`) → **bearish** setup (trapped longs).

But `classify_sweep_trap.is_bullish_sweep` is internally defined as "broke
**above** a prior high" (= BUY_SIDE geometry), while the call site maps
`side == "SELL_SIDE" → is_bullish_sweep = True`
(`measurement_evidence.py:851–888`). **Caller and classifier disagree on what
"bullish" means.** If wired naively, "reclaim" fires on downside continuation
and `fib_retrace_depth` clamps to 0 → the signal comes out **inverted**.

---

## 2. Workstreams

### WS2 — Fix the direction mapping *(do this first, always)* — ✅ DONE (#3406)

- **Decide one canonical meaning.** Recommended: `is_bullish_sweep = True` ⇔
  bullish **setup** = SELL_SIDE sweep (a low was swept and reclaimed upward).
- Align all three to it: the classifier's internal logic
  (`reclaim` / `fib_retrace_depth` sign), the docstring, and the call-site
  mapping. Add an **end-to-end direction test** (SELL_SIDE input → bullish
  reclaim math; BUY_SIDE → bearish).
- **Files:** `smc_core/sweep_trap.py`, `smc_integration/measurement_evidence.py:851–888`.
- **Effort:** ~0.5–1 day. **Risk:** low. **Lands standalone** as a correctness
  fix even if nothing else is wired (the classifier is simply correct then).
- **DoD:** direction test green; docstring, classifier, and call site provably
  consistent; no behavior change for shipped callers (path is flag-gated + starved).

### WS1 — Sweep / reaction-zone data plumbing

Smaller than it looks — most inputs already exist:

- `swept_level` = **already** the sweep event's `price` (= `level_price`,
  `smc_liquidity_engine.py`) → just pass it under the expected key.
- `sweep_extreme` = the detection bar's `high`/`low` (`:107/132`) → **trivial**,
  just emit it.
- `origin_level` = **the one real design decision.** Define it (e.g. the
  opposite pivot / the pre-sweep swing origin), compute, emit.
- Reaction-zone needs zone bounds + a confirmation-bar window analogously.
- **Files:** `scripts/smc_liquidity_engine.py`, `scripts/explicit_structure_from_bars.py`,
  `smc_integration/measurement_evidence.py` (the `swept_level > 0` gate + hand-off).
- **Effort:** ~1–2 days. **Risk:** medium (the `origin_level` definition is a
  judgment call and drives `fib_retrace_depth`).
- **DoD:** with a flag on, `classify_sweep_trap` / `compute_reaction_zone`
  actually execute on real events and emit `SWEEP_TRAP_QUALITY_SCORE` etc.;
  golden fixtures for a known sweep.

### WS3 — SMT correlated feed *(largest, separate track)*

`detect_smt_divergence` needs `enr["correlated_context"]` with `CORRELATED_BIAS`
+ `CORRELATED_LAST_EVENT` (`smc_core/smt_divergence.py:28–30`). This is a **new
data source**:

- Per-symbol partner mapping (SPY↔QQQ, sector ETF, beta pair) — `KNOWN_SMT_PAIRS`
  exists as a stub.
- Fetch the partner's structure/bias in the same timeframe (databento/FMP),
  time-align, and inject as `correlated_context`.
- **Cost/latency:** doubled data fetches, TF alignment, caching.
- **Effort:** ~3–5 days + ongoing data/latency cost. **Risk:** high — a real
  integration project that must be justified on its own.
- **DoD:** a live symbol gets a non-neutral SMT verdict from real partner data;
  the SMT 4-point budget can actually move.

### WS4 — Evidence *(time, not just code)*

- **4a Shadow-observe:** run the WS1/WS2-wired detectors behind their flags,
  write their outputs **observe-only** into the measurement ledger alongside
  actual outcomes (mirrors `scored_family_events` → `smc_core/benchmark.py` →
  release gates). No score effect.
- **4b Evidence gate:** after ≥ N samples, analyze the **Brier / hit-rate
  delta** — do the signals improve prediction? **Only on proven improvement**
  grant budget weight (and rebalance the 100-point budget — take from another
  bucket).
- **Effort:** ~1–2 days code + **2–4 weeks data accrual** + analysis.
  **Risk:** this *is* the "is it worth it?" question.
- **DoD:** a documented Brier/hit-rate comparison on a sufficient sample →
  explicit weight/no-weight decision.

---

## 3. Sequencing, gates & kill criteria

1. **WS2** (direction fix) — immediately, standalone, defuses the landmine.
2. **WS1** (plumbing) — unlocks the deep quality path in **shadow**.
3. **WS4a** (shadow-observe) — accrue data, **no** score effect.
4. **WS4b gate** — Brier improves on ≥ N samples?
   - **No → do not weight** (keep observe-only or remove).
   - **Yes → weight** (rebalance the budget).
5. **WS3** (SMT) — **last or parallel**, only if the correlated feed is
   independently justified; otherwise shelve.

**Kill criteria:** no Brier gain in shadow → no weight. SMT feed cost high +
signal marginal → don't build.

This mirrors the repo's **evidence-first** discipline (cf. the eps_surprise /
PEAD decision: a feature graduates from observe-only to weighted **only** on
FI/measurement evidence, never because it "is there").

---

## 4. Effort summary & recommendation

| Phase | Work | Effort | Risk | When |
|---|---|---|---|---|
| **1** | WS2 direction fix (+test) | ~1 day | low | now, standalone |
| **2** | WS1 plumbing + WS4a shadow | ~2–3 days code, then 2–4 wks observe | medium | scoped mini-project |
| **3** | WS4b evidence decision | analysis | — | after data accrues |
| **4** | WS3 SMT correlated feed | ~1 week + data cost | high | defer until self-justifying |

**Recommendation:**

- **Release Phase 1 now** (direction fix + docstrings) — small, low-risk, and
  the classifier is correct afterwards even if nothing else is wired.
- **Plan Phase 2 as a deliberate mini-project** when capacity allows; do not
  grant budget weight before the WS4b evidence gate.
- **Defer SMT (WS3)** until the correlated feed stands on its own — it is the
  most expensive part with the least certain payoff.

---

## 5. Open decisions (need a human call)

1. **`is_bullish_sweep` canonical meaning** — confirm "bullish = SELL_SIDE
   reversal-up setup" (WS2). Everything downstream keys off this.
2. **`origin_level` definition** (WS1) — opposite pivot vs pre-sweep swing origin?
   Drives `fib_retrace_depth`.
3. **Budget rebalance** — if a detector earns weight (WS4b), which bucket gives
   up points to keep the sum at 100?
4. **SMT partner map** (WS3) — which correlated instrument per symbol, and is the
   extra data fetch/latency acceptable?
