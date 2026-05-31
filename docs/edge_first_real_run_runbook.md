# Edge-Validation — First Real Run Runbook (EV-13)

**Purpose.** The EV-04…EV-12 stack built the complete edge-evidence pipeline.
This runbook is the credential-bound operator procedure for the **first real
run** against live Databento data. It produces the first timestamped artifact
in `governance/promotion_decisions/` — the thing that turns "tool" into
"evidence".

> Honest status before this run: `governance/promotion_decisions/` is empty.
> No real decision has ever been archived. Everything to date is synthetic /
> unit-tested machinery. This procedure changes that.

---

## 0. Prerequisites (environment-bound)

| Requirement | Check |
| --- | --- |
| `DATABENTO_API_KEY` exported in the shell | `echo $env:DATABENTO_API_KEY` is non-empty |
| Databento entitlement for the target dataset/schema | dataset access confirmed in the Databento portal |
| Python venv active | `& c:\Users\preus\skipp-algo\.venv\Scripts\python.exe -V` |
| Working dir | run all commands from the nested `skipp-algo/skipp-algo` code dir |

The API key is read from the environment. **Never** pass it on the command
line or paste it into a tool prompt — type it directly into your shell.

---

## 1. Pull real bars + detect structure → pipeline input

`scripts/pull_databento_edge_input.py` fetches OHLCV, runs the canonical SMC
structure detector, and emits the exact JSON `run_edge_pipeline` consumes. The
emitted `bars` are the **resampled timeframe bars** the structure events anchor
on — not the raw fetch granularity — so the pipeline's anchor / forward-window
arithmetic matches the live scorer.

```powershell
& c:\Users\preus\skipp-algo\.venv\Scripts\python.exe -m scripts.pull_databento_edge_input `
  --symbol AAPL `
  --dataset XNAS.ITCH `
  --schema ohlcv-1m `
  --timeframe 15m `
  --start 2024-01-01 `
  --end   2025-06-01 `
  --output artifacts/edge_runs/AAPL_15m_input.json
```

Notes:
- `--schema` (fetch granularity) **must be ≤** `--timeframe` (structure
  timeframe). Default `ohlcv-1m` → `15m` is the primary configuration
  (`governance/family_walkforward.py` pins horizons on the 15m frame).
- `--as-of` defaults to the **last bar's timestamp**, so the EV-04 point-in-time
  guard is always armed against the data's own horizon. Override only with a
  deliberate, documented boundary.
- The wrapper **refuses loudly** (exit 1) if the symbol yields no resampled
  bars or no detected structure — an honest empty result, never a vacuous
  payload.

### Sample-size reality check (do this before spending a long window)

The PSR producer needs **≥ 30 triggered returns per family**
(`MIN_OBSERVATIONS_FOR_PSR`). A family with fewer triggered setups is honestly
reported as *not measured* — not a failure, but not evidence either. Pick a
window long enough that the families you care about clear 30 triggered events.

---

## 2. Run the pipeline → archive the decision + verdict

```powershell
& c:\Users\preus\skipp-algo\.venv\Scripts\python.exe -m scripts.run_edge_pipeline `
  --input  artifacts/edge_runs/AAPL_15m_input.json `
  --output artifacts/edge_runs/AAPL_15m_report.json `
  --archive-dir governance/promotion_decisions
```

Exit codes (mirror `run_promotion_gate`):
- `0` — all families promoted.
- `2` — at least one family blocked (this is the **expected, honest** first
  result; promotion requires metrics this scaffold does not yet produce — see
  §4).
- `1` — configuration error (bad input, lookahead leak, etc.). Read stderr.

On success it prints the verdict summary and the archived path, e.g.:

```
pipeline ok: 312 event(s) -> 4 decision(s); verdicts {'edge_supported': 0, 'no_edge': 1, 'inconclusive': 3, 'not_evaluated': 0}
archived: governance/promotion_decisions/promotion_decisions_2026-06-01T....json
```

---

## 3. Read the verdict honestly

The archived report drives the EV-08 verdict and the EV-09 panel:

```powershell
& c:\Users\preus\skipp-algo\.venv\Scripts\python.exe -m governance.family_verdict `
  --report (Get-ChildItem governance/promotion_decisions/promotion_decisions_*.json | Sort-Object Name | Select-Object -Last 1).FullName
```

Verdict semantics (anti-HARKing, EV-08):
- **edge_supported** — gate promoted **and** the pre-registered `primary_metric`
  (PSR) was genuinely measured **and** `observed_n ≥ min_sample_n`.
- **inconclusive** — gate promoted but a pre-registration check failed (metric
  not measured, or sample too small). **An edge is NOT claimed.**
- **no_edge** — measured and the family did not promote.
- **not_evaluated** — no gate decision for a registered family.

---

## 4. Expected first-run outcome (set expectations)

`scripts/build_family_metrics.py` is an EV-06 **scaffold**: it measures only
**PSR** and **MinTRL**. The remaining gate metrics (brier, ece, fdr_pvalue, psi,
conformal, live/wf) are honestly left `None`, so the gate will block those
families as "not yet fully measured". **A first run that returns exit `2` with
mostly `inconclusive` verdicts is the correct, honest result** — it proves the
pipeline runs end-to-end on real data and archives a real decision, without
fabricating a pass. `edge_supported` only becomes reachable once the C-sprint
metric producers (C3 BCa bootstrap, C4 block permutation, C9 PSI, C10 conformal)
are wired in.

---

## 5. Known load-bearing assumptions (review before trusting numbers)

These are chosen, documented trade assumptions — not bugs, but they shape every
number above and must be reviewed before any number is acted on:

- **Trade definition (variant A, `family_returns.py`)** — zone families enter at
  the zone midpoint on first retest touch, exit at the close
  `family_outcome_horizon` bars later; level families enter immediately at the
  break/sweep level. Fixed 5 bps round-turn cost. No target/stop optimisation.
- **Late-touch horizon clamp** — a touch late in the forward window has its exit
  clamped to the last available bar, shortening the intended hold. Review
  whether to lengthen the window or drop such trades.
- **Adapter lookahead vs. outcome horizon** — forward windows
  (BOS 8 / OB 12 / FVG 20 / SWEEP 8) intentionally differ from the exit horizons
  (BOS 8 / OB 6 / FVG 4 / SWEEP 3).
- **`as_of` timezone** — naive ISO `as_of` is treated as **UTC** to match the
  UTC epoch anchor timestamps (EV-12 fix). Pass tz-aware ISO if you mean
  something else.

---

## 6. Failure triage

| Symptom | Likely cause | Action |
| --- | --- | --- |
| `error: ... no detected SMC structure` | window too short / wrong timeframe | widen `--start/--end`, confirm `--timeframe` |
| `error: ... no resampled <tf> bars` | symbol absent in fetch / bad symbol | verify symbol + dataset entitlement |
| `error: ... lookahead leak refused` | `as_of` earlier than some bar | correct `--as-of` or omit to auto-default |
| `error: need at least 30 returns for PSR` | too few triggered setups | longer window or different symbol |
| exit `1` with a Databento/network message | transient API / auth | the client retries transient errors; check the key for auth failures |
