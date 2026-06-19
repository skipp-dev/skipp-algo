# Reviewed Plan — Timeframe Expansion to `5m, 10m, 15m, 30m, 1H, 4H, 1D`

> **Status:** Reviewed planning artifact (read-only). No code change in this document.
> **Reviewer:** GitHub Copilot — evidence-based review of the original expansion plan.
> **Date:** 2026-06-19
> **Base:** `origin/main` @ `884dcdfd`
> **Scope correction:** This review keeps the original plan's intent but corrects three
> factual inaccuracies and surfaces one **hard design conflict** with the just-merged
> live-overlay hardening (PR #2860). Read §0 first — it changes the rest of the plan.

---

## 0. Review summary — what changed vs. the original plan

The original plan is largely accurate and well-scoped, but it treats **all** timeframe
enums across the repo as one single canonical list. That assumption is wrong and would
break a deliberate design boundary. Three corrections and one conflict:

| # | Finding | Severity | Effect on plan |
|---|---|---|---|
| R1 | **Two distinct TF domains exist** — a *structure/snapshot* domain (5-TF, includes `1D`) and a *live-overlay* domain (intraday-only, 4-TF, **no `1D`**). They must not be merged into one list. | **High** | Splits §2.1 into a small typed family of constants; changes Q1/Q5. |
| R2 | **`bar_close_guard` uses a separate lowercase casing domain** (`1h`/`4h`/`1d`) and already contains `30m`. Only `10m` is missing. "Align casing to `1H`/`1D`" would break callers. | Medium | Corrects §3.1 / §3.5 — add `"10m": 600`, do **not** re-case keys. |
| R3 | **`select_ipda_htf` returns a daily/weekly IPDA *anchor* (`D`/`W`/`M`), not a sibling intraday TF.** `30m` already maps to `D`; `10m` already falls through to `D`. The plan's premise (`10m`→`15m/30m`) misreads the function. | Medium | Corrects §3.1 / Phase 1.5 / Q4 — change is cosmetic + a test, not new mapping logic. |
| C1 | **Conflict with PR #2860:** the live-overlay surface (`SUPPORTED_TIMEFRAMES`, `TimeframeLiteral`, `spec/smc_live_overlay.schema.json` `tf` enum, `services/live_overlay_daemon/main.py` `_VALID_TFS`) is an intentional intraday-only whitelist. PR #2860 **just removed `1D`** from `_VALID_TFS` to align with that schema. Adding `1D` to the live-overlay surface would directly revert that intent. | **High** | The live-overlay whitelist gets `10m`+`30m` **only**, never `1D`. |

**Net effect:** the expansion is **not** "set one tuple to 7 values everywhere." It is:
- **Structure / snapshot / release domain** → full 7-TF list incl. `1D`.
- **Live-overlay domain** → intraday-only, **6** values (`5m,10m,15m,30m,1H,4H`), no `1D`.
- **`bar_close_guard` domain** → lowercase, add `10m` only.

---

## 1. Goal & Scope (unchanged)

**Goal:** Expand canonical timeframes from `5m, 15m, 1H, 4H` to
`5m, 10m, 15m, 30m, 1H, 4H, 1D`.

**Scope:** Plan only — no code change now. Covers Python core, SMC integration,
workflows, Pine scripts, schemas, tests, CI, data artifacts, docs.

---

## 2. Design decisions (revised)

### 2.1 Canonicalization — a typed family, not one tuple *(revised, R1/C1)*
There is **no single canonical list** because the live-overlay surface legitimately
excludes `1D`. Introduce a small, derived family in `smc_integration/timeframes.py`
(the existing canonical home for `is_daily_timeframe`):

```python
CANONICAL_TIMEFRAMES: tuple[str, ...] = ("5m", "10m", "15m", "30m", "1H", "4H", "1D")
DAILY_TIMEFRAMES: tuple[str, ...]     = ("1D",)
INTRADAY_TIMEFRAMES: tuple[str, ...]  = tuple(tf for tf in CANONICAL_TIMEFRAMES if tf not in DAILY_TIMEFRAMES)
LIVE_OVERLAY_TIMEFRAMES: tuple[str, ...] = INTRADAY_TIMEFRAMES  # == 6 values, no 1D
```

- `RELEASE_REFERENCE_TIMEFRAMES` **derives** from `CANONICAL_TIMEFRAMES` (full 7).
- `SUPPORTED_TIMEFRAMES` (live overlay) **derives** from `LIVE_OVERLAY_TIMEFRAMES` (6).
- This makes the domain split explicit and test-pinnable instead of implicit.

### 2.2 Casing convention *(clarified, R2)*
Two casing domains coexist on purpose — keep them separate:
- **Canonical / Pine domain:** minutes lowercase (`5m,10m,15m,30m`), hours/days
  uppercase (`1H,4H,1D`). Used by `ids.py`, `release_policy.py`, schemas, contracts.
- **`bar_close_guard._INTERVAL_SECONDS` domain:** fully lowercase (`1h,4h,1d`).
  Callers normalize to lowercase before calling; `interval_seconds` raises on unknown
  tokens. **Do not re-case these keys** — only add `"10m": 600`.

### 2.3 Daily handled separately *(verified)*
`is_daily_timeframe()` already accepts `{"1D","D","DAILY","1DAY"}` (case-insensitive)
via `_DAILY_ALIASES`. **No change needed.** `10m`/`30m` are correctly non-daily.

### 2.4 Release-gate coverage *(see Q2)*
`EVIDENCE_MIN_TIMEFRAME_COVERAGE = 2` is trivially met by 7 TFs. Raise to **4**, but
only **after** backfill exists (otherwise the gate fails on legacy 4-TF artifacts).

---

## 3. Affected files — verification status

Legend: ✅ verified accurate · ⚠️ corrected · ❓ needs check during implementation.

### 3.1 Core constants

| File | Plan claim | Verdict |
|---|---|---|
| `smc_integration/release_policy.py:37` `RELEASE_REFERENCE_TIMEFRAMES = ("5m","15m","1H","4H")` | extend to 7 | ✅ — but derive from `CANONICAL_TIMEFRAMES` |
| `smc_integration/release_policy.py:50` `EVIDENCE_MIN_TIMEFRAME_COVERAGE = 2` | maybe raise | ✅ raise to 4 (Q2), separate commit |
| `smc_tv_bridge/contracts/live_overlay.py` `SUPPORTED_TIMEFRAMES` / `TimeframeLiteral` (4-TF, no 1D) | extend | ⚠️ extend to **6** (intraday), **never add 1D** (C1) |
| `smc_core/ids.py:22` `_TIMEFRAME_TO_SECONDS` (5m,15m,1H,4H,1D) | add 10m=600, 30m=1800 | ✅ accurate |
| `smc_core/bar_close_guard.py` `_INTERVAL_SECONDS` (lowercase; has 1m,5m,15m,30m,1h,4h,1d,1w) | add 10m + align casing | ⚠️ add `"10m":600` only; **do not re-case** (R2). `30m` already present |
| `smc_core/htf_context.py:45` `select_ipda_htf` `intraday_short={1m,5m,15m,30m,1H,2H}` | add 10m | ⚠️ returns IPDA anchor `D`, not sibling TF (R3). `30m`→`D` already; `10m`→`D` via default. Add `"10m"` for explicitness + test |
| `smc_integration/timeframes.py` | introduce CANONICAL | ✅ greenfield — no constant exists today |

### 3.2 JSON schemas *(domain split is critical here)*

| File | Current enum | Target |
|---|---|---|
| `spec/smc_snapshot.schema.json:15` | `["5m","15m","1H","4H","1D"]` | full 7 incl `1D` |
| `spec/smc_structure_artifact.schema.json:37,51,98` | `["5m","15m","1H","4H","1D"]` | full 7 incl `1D` |
| `spec/smc_live_overlay.schema.json:22` `tf` enum | `["5m","15m","1H","4H"]` | **6 intraday, no `1D`** ⚠️ (C1) |
| `spec/smc_pine_payload.schema.json` | ❓ | check; align to the relevant domain |
| `spec/smc_dashboard_payload.schema.json` | ❓ | check; align to domain |
| `spec/smc_delivery_bundle.schema.json` | ❓ | check; align to domain |

> Contract test `tests/test_smc_live_overlay_contract.py::test_supported_timeframes_match_schema`
> pins `SUPPORTED_TIMEFRAMES == schema tf enum` — both move together to the 6-value set.

### 3.3–3.8 Pine, workflows, scripts, tests, artifacts, docs
The original plan's lists for these are accurate in spirit. Apply the domain rule:
- Pine `smc_live_overlay_consumer.pine` mapping: add `"10"→"10m"`, `"30"→"30m"`. The
  `"D"→"1D"` branch stays (Pine may *display* on a daily chart) but the **served overlay
  payload** stays intraday-only — daily is fallback-to-baked, consistent with C1.
- Workflows (`smc-measurement-benchmark*`, `f2-frozen-artifact-bootstrap`, etc.):
  benchmark/structure jobs use the **full 7** (they feed the snapshot/structure domain).
- `services/live_overlay_daemon/main.py` `_VALID_TFS`: extend to the **6** intraday
  values, coordinated with PR #2860. **Do not re-add `1D`.**
- `terminal_technicals.py` `INTERVAL_MAP` / `intervals`: add `10m`; this is a TradingView
  data domain — match its existing casing, do not force canonical casing blindly.
- Tests: every pinned `("5m","15m","1H","4H")` literal updates; add new property tests
  for `10m`/`30m` seconds-mapping and `10m`/`30m → "D"` anchor.

---

## 4. Open questions — answered

### Q1 — Single source of truth, or separate `CANONICAL_TIMEFRAMES`?
**Answer: Introduce `CANONICAL_TIMEFRAMES` in `smc_integration/timeframes.py` and derive the rest.**
A single tuple cannot express that the live-overlay surface excludes `1D` (R1/C1). Use one
*source* (`CANONICAL_TIMEFRAMES`) plus derived views (`INTRADAY_TIMEFRAMES`,
`LIVE_OVERLAY_TIMEFRAMES`, `DAILY_TIMEFRAMES`). `RELEASE_REFERENCE_TIMEFRAMES` and
`SUPPORTED_TIMEFRAMES` both become *derived* — eliminating drift while honoring the
domain boundary. `timeframes.py` is already the canonical predicate home, so it is the
natural anchor.

### Q2 — Raise `EVIDENCE_MIN_TIMEFRAME_COVERAGE`?
**Answer: Yes — raise `2 → 4`, in a separate commit after backfill.**
With 7 canonical TFs the value `2` is trivially satisfied and no longer a meaningful gate.
`4` forces release evidence to span both fast (`5m`/`10m`) and slow (`1H`/`4H`) frames
without demanding all 7 from every surface (the live overlay only emits 6, and legacy
artifacts only 4). **Sequencing:** raise it *only after* the 10m/30m backfill exists,
otherwise `release_policy` rejects historical 4-TF evidence (`REASON_INSUFFICIENT_TIMEFRAMES`).

### Q3 — Produce 10m/30m for all symbols immediately, or gradually?
**Answer: Gradually (staged), forward-first then backfill.**
Storage and CI runtime scale ~linearly with TF count (4→7 ≈ +75%). Roll out by:
1. enabling `10m`/`30m` in the generating workflows (forward generation),
2. then a controlled one-off historical backfill per symbol cohort,
3. then raise the coverage gate (Q2).
This bounds CI cost spikes and lets benchmark-rolling absorb the new volume incrementally.

### Q4 — Adjust `intraday_short`/`intraday_long` in `htf_context.py` for 10m/30m?
**Answer: Minimal/cosmetic — no new anchor logic.**
`select_ipda_htf` returns the **IPDA anchor** (`D`/`W`/`M`/`6M`), not a sibling intraday
TF. `30m` is already in `intraday_short` (→ `D`); `10m` already falls to the default
`return "D"`. Both are already correct. Add `"10m"` to `intraday_short` purely for
explicitness/readability, and add a property test asserting `select_ipda_htf("10m") ==
select_ipda_htf("30m") == "D"`. The original plan's premise (`10m`→`15m/30m`,
`30m`→`1H/4H`) misreads the function and should be dropped.

### Q5 — External consumers with a whitelist?
**Answer: Yes — the live-overlay surface is a hard, intentional whitelist. Expand it to 6 (add 10m/30m), never to include 1D.**
The whitelisted consumers are:
- `smc_tv_bridge/contracts/live_overlay.py` — `SUPPORTED_TIMEFRAMES` + `TimeframeLiteral`,
- `spec/smc_live_overlay.schema.json` — `tf` enum,
- `services/live_overlay_daemon/main.py` — `_VALID_TFS` (PR #2860 **removed `1D`** here),
- `pine/smc_live_overlay_consumer.pine` — Pine-side TF mapping.
Decision: add `10m` + `30m` to this whitelist (intraday), keep it **`1D`-free** to stay
consistent with PR #2860's design intent. **Coordinate the merge order** so this work does
not revert PR #2860. The structure/snapshot domain remains separate and keeps `1D`.

### Q6 — Keep old 4-TF artifacts as legacy or migrate?
**Answer: Keep legacy; generate forward (additive, non-destructive).**
Existing `<SYM>/5m … 4H` artifact paths remain untouched; new `<SYM>/10m`, `<SYM>/30m`
are generated going forward, with an optional one-off historical backfill (Q3). No
destructive migration: artifacts are immutable evidence and freshness lineage; rewriting
them would break reproducibility and the staleness model. `f2-frozen-artifact-bootstrap`
regenerates the full 7-TF set on its next forward run.

---

## 5. Risks & mitigations (revised)

| Risk | Impact | Mitigation |
|---|---|---|
| **Re-adding `1D` to live overlay reverts PR #2860** (C1) | Schema/daemon contract regression | Live-overlay surface stays `1D`-free; coordinate merge order; contract test pins 6 intraday values |
| Treating all enums as one list (R1) | Daily leaks into intraday overlay | Typed constant family (Q1); separate schema enums |
| Re-casing `bar_close_guard` keys (R2) | Callers passing lowercase raise `ValueError` | Add `"10m":600` only; keep lowercase domain |
| Wrong HTF-anchor assumptions (R3) | Wasted work / wrong tests | Recognize anchor semantics; cosmetic add + 1 test |
| Hardcoded 4-lists missed | CI failures, wrong data | Exhaustive `git grep` inventory (Phase 0), staged rollout |
| Coverage gate raised too early (Q2) | Release gate fails on legacy artifacts | Raise threshold only after backfill |
| Data volume / CI cost (Q3) | Longer runs, more storage | Staged rollout, forward-first, cohort backfill |
| Pinned-expression tests drift | Red guard ring | Treat the §3.6 list as a checklist; update ledger pins if `noqa`/`type: ignore`/skips added |

---

## 6. Revised commit sequencing

1. **Core constants** — `smc_integration/timeframes.py` (`CANONICAL_*` family),
   `release_policy.py` (derive `RELEASE_REFERENCE_TIMEFRAMES`), `smc_core/ids.py`
   (`10m`/`30m` seconds), `bar_close_guard.py` (`10m` only), `htf_context.py`
   (cosmetic `10m`).
2. **Contracts & schemas — domain-split** — structure/snapshot schemas → 7 incl `1D`;
   live-overlay contract + `smc_live_overlay.schema.json` → 6 intraday (no `1D`),
   coordinated with PR #2860.
3. **Workflows** — benchmark/structure jobs → 7; any live-overlay job → 6.
4. **Pine** — `smc_live_overlay_consumer.pine` mapping (`10`,`30`); generated files.
5. **Scripts & modules** — `terminal_technicals.py`, databento/profile generators.
6. **Tests** — pinned-expression updates + new `10m`/`30m` property tests.
7. **Coverage gate raise (2→4) + docs** — only after backfill (Q2); `CHANGELOG.md`,
   `README.md`, `docs/`.

> Step 7's gate raise is intentionally last and gated on Phase 7 backfill completion.

---

## 7. Validation checklist (revised)

- [ ] `pytest tests/test_plan_2_8_s3_1_chart_tf_expansion.py`
- [ ] `pytest tests/test_plan_2_8_s3_1_per_tf_partitioning.py`
- [ ] `pytest tests/test_smc_core_ids.py` (now incl `10m`,`30m`)
- [ ] `pytest tests/test_timeframes_invariants_property.py`
- [ ] `pytest tests/test_bar_close_guard_invariants_property.py`
- [ ] `pytest tests/test_smc_live_overlay_contract.py` (pins **6** intraday values, no `1D`)
- [ ] `pytest tests/test_smc_integration_release_policy.py`
- [ ] `pytest tests/test_htf_context_invariants_property.py` (`10m`,`30m`→`"D"`)
- [ ] New: `test_10m_30m_recognized_as_intraday`, `test_10m_seconds_mapping`,
      `test_live_overlay_excludes_daily` (asserts `1D` **not** in live-overlay whitelist)
- [ ] Guard ring green (global-statement / getattr / basicConfig ledgers — re-pin if lines drift)
- [ ] `actionlint` / `zizmor` on changed workflows (lower budgets if findings drop)
- [ ] JSON-schema validation for both domains
- [ ] Dry-run rolling benchmark with 7 TFs
- [ ] Pine compilation check

---

## 8. Coordination note — PR #2860

PR #2860 (`fix/live-overlay-post-merge-bugs`) hardened the live-overlay daemon and
**removed `1D` from `_VALID_TFS`** to match `spec/smc_live_overlay.schema.json`. This
expansion must land **after** #2860 merges (or be explicitly rebased on it) and must
**preserve** the intraday-only live-overlay contract — adding `10m`/`30m` there, never
`1D`. Treat C1 as a blocking pre-condition for the schema/contract commit (step 2).
