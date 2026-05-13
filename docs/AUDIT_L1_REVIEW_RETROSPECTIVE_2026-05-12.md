# Audit L-1 Merge-Train — Code-Review Retrospective & Remediation Plan

**Date:** 2026-05-12
**Revision:** v2 (incorporates senior-engineer review feedback — see
*Revision history* at end of doc).
**Scope:** 18 PRs merged today (#2146 → #2165), inclusive of the
"provider-rationalization" merge train (#2153–#2164) and the wrap-up #2165.
**Reviewer signal source:** GitHub Copilot inline-review comments fetched via
`gh api repos/.../pulls/<N>/comments --paginate` plus
`reviewThreads` GraphQL (protocol committed as
`docs/COPILOT_REVIEW_TRIAGE_PROTOCOL.md` per R14 step 0).

> **Quick numbers**
>
> | Metric                                             | Count |
> |----------------------------------------------------|-------|
> | PRs reviewed today                                 | 18    |
> | PRs with ≥1 Copilot finding                        | 11    |
> | Total Copilot inline findings                      | **70**|
> | Unresolved threads at retrospective time           | **56**|
> | Distinct **root-cause clusters** identified        | **8** |
> | Findings that map to **doc/code drift** alone      | ~35   |

This report (a) catalogs every finding by cluster, (b) traces each cluster to a
single mechanistic root cause, and (c) prescribes concrete preventive
controls so the same class of issue cannot land again. Cluster 1 (doc/code
drift) is the dominant failure mode and gets the most engineering investment in
the remediation plan.

---

## 1. Findings by PR (raw catalog)

| PR    | Title (short)                                        | Findings | Notable cluster(s)         |
|-------|------------------------------------------------------|---------:|----------------------------|
| #2148 | F-V8-Q5b skip oversized second_detail sheets         | 2        | C7 (eager arg); psutil finding STALE-AT-REVIEW (`requirements.txt:16` already had `psutil>=5.9.0` from #2151) |
| #2153 | smc-export-cron-watchdog                             | 7        | C1, C3 (race, branch-agnostic guard) |
| #2154 | provider-utilization audit follow-up (G3/G4/G6)      | 7        | C3, C4, C1                 |
| #2155 | OPRA.PILLAR UOA detector (replaces UW flow)          | **21**   | C1, C2, C6, C7, C8         |
| #2156 | G5/Option-A Finnhub HTTP wiring                      | 2        | C3 (env-var mutation)      |
| #2157 | Databento entitlement probe                          | 10       | C1, C4, C5, C8             |
| #2159 | FMP mover-seed + eod-bulk probes                     | 1        | C7 (`expected_min=0` IndexError) |
| #2160 | Finnhub Option-B drop /company-news                  | 0        | —                          |
| #2161 | Provider-rationalization audit doc                   | 7        | C1 (massive doc drift)     |
| #2163 | Surgical removal of UW flow-alerts path              | 5        | C1, C2, C5                 |
| #2164 | Post-audit follow-ups                                | 4        | C1 (4× wrong module path)  |
| #2165 | Audit-L-1 wrap-up (CHANGELOG + OPRA probe + UW dep.) | 4        | C1, C8 (datasets normalize)|

> Only #2160 was clean. The dominant outlier is **#2155 (21 findings)** — a
> large cross-module feature swap (UW → Databento OPRA) where most findings
> were not bugs in business logic but were artifacts of cross-cutting drift
> between docstrings, PR description, multiple call-sites, and pin-tests.

---

## 2. Root-cause clusters

### C1 — Documentation/code drift (≈35 findings, ~50% of all)
The largest cluster. Sub-categories:

- **Wrong module/file paths in comments and docstrings** —
  `open_prep/opra_uoa.py` referenced when actual is `newsstack_fmp/opra_uoa.py`;
  `newsstack_fmp/ingest_opra_options.py` referenced when actual is
  `…_options_flow.py`. Found in #2155 ×4, #2163 ×2, #2164 ×4, #2165 ×1.
- **Stale function-name references in pin-test rationale** —
  `tests/test_silent_error_swallow_pin.py` and
  `tests/test_broad_except_silent_budget.py` cite `opra_uoa._ts_to_ns()`
  while implementation defines `_normalize_ts()`.
- **Module docstrings that contradict implementation** — input type claimed
  to be `pandas.DataFrame` while function takes `Iterable[Mapping]` (#2155);
  probe claims `HEAD/GET` while only doing `GET` (#2154); probe claims to call
  `metadata.list_schemas` while only calling `get_dataset_range` (#2157);
  watchdog header comment claims `+0…+90 min window` while actual is `+45…+90`
  (#2153); permission rationale claims `gh workflow run` while actual call is
  `gh api .../dispatches` (#2153 ×2).
- **PR description ↔ implementation mismatch** —
  `ENABLE_OPRA_UOA` "default 0 for safe rollout" in PR body, but **all 4 code
  sites and `Config.enable_opra_uoa` default to "1"** (#2155 ×3, #2163 ×1).
  Confirmed today on `main`:
  ```text
  scripts/probe_providers.py:344       os.getenv("ENABLE_OPRA_UOA", "1")
  open_prep/streamlit_monitor.py:677   os.environ.get("ENABLE_OPRA_UOA", "1")
  open_prep/streamlit_monitor.py:2277  os.environ.get("ENABLE_OPRA_UOA", "1")
  newsstack_fmp/config.py:66           os.getenv("ENABLE_OPRA_UOA", "1") == "1"
  ```
- **CHANGELOG arithmetic / citation error** — "#2154 → #2161 (8 PRs) +
  #2163" is internally inconsistent (range already accounts for 8) (#2165).
- **Audit document landed describing a state the repo did not yet have**
  (#2161 ×7) — every one of the 7 findings is a claim about removed/added code
  that landed only in a *later* PR in the train. Doc lapped the code.
- **Comments referencing constants that were removed in the same PR** —
  `UW_FLOW_ALERTS_PATH` cited in `docs/OPEN_PREP_OPS_QUICK_REFERENCE.md` (#2164).

### C2 — Default-value / configuration inconsistency (≈5 findings)
- **Four** independent default-reading call-sites for `ENABLE_OPRA_UOA`
  (see C1 PR↔impl block above). No single source of truth — drift inevitable
  when default changes.
- `Config.enable_opra_uoa` flag introduced (#2155) but **has zero importers in
  the repo** — verified via `git grep -nE "enable_opra_uoa" --include="*.py"`
  which returns only the definition line itself. Every consumer reads
  `os.environ` directly. Dead config.

### C3 — Concurrency / shared-state safety (3 findings, all real bugs)
Confirmed today on `main`:

- **`FMPClient._endpoint_usage_stats`** (#2154 ×2): mutated unsynchronized from
  `_record_endpoint_event` while `get_batch_quotes()` submits via
  `ThreadPoolExecutor`. The current code carries an explicit comment that
  reads (verified on `main`):
  > *"Cheap dict mutation; safe to call from any code path. Not thread-safe
  > across processes but fine within a single producer run."*

  This assumption is **wrong intra-process too**: nested `bucket["count"] += 1`
  is read-modify-write at the Python level and is racy under threads regardless
  of the GIL (the GIL only guarantees single-bytecode atomicity, not
  LOAD_ATTR + INPLACE_ADD + STORE_ATTR sequences). Symptoms: silent counter
  loss + occasional `RuntimeError: dictionary changed size during iteration`
  from `get_endpoint_usage_stats()` snapshotting.
  Spot-checked: `FMPClient._lock` exists but `_record_endpoint_event` does not
  acquire it (`open_prep/macro.py:~676`).
- **`_http_get` env-var mutation** (#2156): `open_prep/macro.py` line 2041
  temporarily writes `FINNHUB_API_KEY` into `os.environ` around the call into
  `terminal_finnhub._get`. Process-global mutation under concurrent fetch is
  racy AND violates the spirit of `tests/test_os_environ_mutation_ledger.py`.
- **Watchdog branch-agnostic guard + 20-row pagination cap** (#2153 ×2):
  `RUN_COUNT` can be paged out and the watchdog double-dispatches.

### C4 — Secret leakage via error/log surfaces (3 findings)
- `_try_call` in [scripts/probe_databento_entitlement.py](../scripts/probe_databento_entitlement.py)
  returns `str(exc)` directly into the report. Databento client errors can
  embed request URLs/headers — leaks key. Repo already has
  `databento_client._redact_sensitive_error_text()` that was not used (#2157).
- `url.replace(api_key, "***")` redaction in
  [scripts/probe_fmp_13f_endpoints.py](../scripts/probe_fmp_13f_endpoints.py)
  silently fails when key contains characters that `urlencode` percent-escapes
  (#2154).

> **Note on the #2148 `psutil` finding:** initially listed under "claim ≠
> reality" in this cluster, but verification against current `main` shows
> `requirements.txt:16` already declares `psutil>=5.9.0` (added by #2151,
> which landed *before* the #2148 review pass). The Copilot finding was
> **stale at review time** — it is not C4 evidence. It is, however, a
> direct confirmation of the R14 hypothesis that ~60% of unresolved
> Copilot threads are stale at retrospective time.

### C5 — Lint-budget bypass / dead code (5 findings)
- `import json` unused in `scripts/probe_databento_entitlement.py` (#2157 ×2).
- `# noqa: BLE001` for a rule not enabled by current Ruff config — RUF100
  (unused-noqa) **is** enabled and would flag this if `scripts/probe_*.py` were
  in scope (#2157).
- Dead import `is_uw_configured as _uw_configured` in `streamlit_monitor.py`
  after UW removal (#2163).
- Dead constant `UW_FLOW_RECENT_PATH` (#2163).

Root: `scripts/probe_*.py` and a number of one-off utilities are **excluded**
from the Ruff include-pattern in `pyproject.toml`, so F401/RUF100 don't fire.

### C6 — Test gap (3 findings)
- New `newsstack_fmp/ingest_opra_options_flow.py` provider wrapper has **zero
  unit tests**. Behaviors that aren't covered:
  ticker normalization, provider-instantiation failure → `[]`,
  `client.get_range` failures → `[]`, limit trimming.
- `test_aggressor_classification` includes a `(None, …)` parameter case but
  the test fixture coerces `side or ""`, so the `None` branch is never
  reached. Phantom coverage.
- Detector input contract (DataFrame vs iterable) was never tested.

### C7 — Boundary / edge-case bugs (3 findings)
- `expected_min=0` in `probe_fmp_eod_bulk` bypasses the `len(data) < expected_min` check, then crashes on `data[0]` (#2159, **real bug**).
- `_memory_snapshot()` evaluated inside f-string args passed to `_emit(...)`,
  so the snapshot **always runs** even when `progress_callback is None`
  (#2148, defeats the early-exit cost guard).
- `int(os.getenv("OPRA_UOA_TRADES_WINDOW_MIN"))` evaluated **at import time**
  in `newsstack_fmp/ingest_opra_options_flow.py`. Malformed env var → import
  raises `ValueError` → `streamlit_monitor` import-guard
  `except ImportError` doesn't catch it → monitor fails to start (#2155 ×2).

### C8 — Wrong import path / silent degradation (2 findings)
- `from databento_client import PREFERRED_DATABENTO_DATASETS` — the constant
  lives in `databento_utils.py` (#2157). Fallback path silently degraded.
- `client.metadata.list_datasets()` may return non-string objects; elsewhere
  in the repo we normalize via `str(d)` before comparison. The new OPRA probe
  in #2165 does `"OPRA.PILLAR" not in datasets` raw — possible false-FAIL
  (#2165, my own code).

---

## 2.1. Failure-risk matrix (blast-radius per cluster)

Frequency alone is a misleading prioritization signal — a single C4 leak
outranks 20 C1 doc-drift findings on operational impact. The matrix below
re-justifies the T1/T2 sequencing in §5 by **blast-radius**:

| Cluster | Findings | Blast-radius if a fresh one slips through                                              | Severity |
|---------|---------:|----------------------------------------------------------------------------------------|----------|
| C1 doc/code drift     | ~35 | Audit-trail debt; reviewer trust erosion; future grep-citations may break             | LOW      |
| C2 defaults inconsistency | ~5 | Silent flag-flip skew between modules; "works on monitor, not on probe" debugging     | MED      |
| **C3 concurrency**       | 3  | **Silent counter loss + sporadic `RuntimeError` in production producer runs**          | **HIGH** |
| **C4 secret leakage**    | 3  | **API key in CI log forever; rotate-credentials response required**                    | **HIGH** |
| C5 lint-budget bypass    | 5  | Dead code accumulates; future refactors trip on phantom imports                       | LOW      |
| C6 test gaps             | 3  | New code paths regress invisibly; coverage metrics stale                              | MED      |
| **C7 boundary bugs**     | 3  | **Production monitor fails to start (import-time `ValueError`); probe IndexError**     | **HIGH** |
| C8 wrong import path     | 2  | Silent degradation (fallback constant, false-FAIL probe); slow to detect              | MED      |

**Implication for §5 ordering:** R5/R6/R10 (covering C3/C7) deserve T1
rather than the original frequency-based T2 placement. The §5 timeline
below is updated accordingly.

---

## 3. Why this happened — meta-analysis

Three structural conditions enabled today's profile:

1. **Train-style merging without a "doc-locks-with-code" gate.** The audit
   document #2161 was prepared as a *forward-looking* artifact and merged
   describing PRs that hadn't yet landed on `main`. Result: 7 doc-drift
   findings on a single PR.
2. **No single source of truth for feature-flag defaults.** `ENABLE_OPRA_UOA`
   has 3 code-site defaults + 1 dataclass default + N comment claims. There is
   no enforcement that they agree.
3. **Lint scope and pin-test scope drift behind code growth.** `scripts/probe_*.py`
   files are routinely added without being on the Ruff include-list. Pin-tests
   that cite function-names by string literal aren't validated against the
   live import graph.

These are textbook compounding factors: large cross-cutting refactor (#2155),
parallel docs PR (#2161), fast cadence (12 substantive merges in 12 hours),
and reviewer attention pulled across multiple branches simultaneously.

---

## 4. Remediation plan

Each remediation is concrete, testable, and assigned a tier:

- **T1 — Land in next chore PR (≤ 1 day)**: cheap CI hooks, narrow code fixes.
- **T2 — Land within the week**: refactors, new test files, Ruff scope expand.
- **T3 — Backlog (sprint+1)**: structural changes (Pydantic settings, etc.).

### R1 (T1) — File/function citation validator (kills ~50% of C1)

Add `tests/test_citation_freshness.py` that, for every `.py`/`.md`/`.yml`
under tracked paths, scans for the regex
`(newsstack_fmp|open_prep|scripts|docs|tests|\.github)/[\w_/\-\.]+\.(py|md|yml|yaml|pine)`
inside comments/docstrings/markdown body and asserts each cited path
**exists on disk**. Implementation: ~50 LOC, AST-walk + `pathlib.Path.exists`.
Failure mode caught: every "wrong module path" finding from #2155, #2163,
#2164, #2165 (≈11 findings).

### R2 (T1) — Pin-test function-name reference validator (kills `_ts_to_ns` class)

Extend `tests/test_citation_freshness.py` with a second pass: for each pin/
ledger test file, find backtick-quoted `module.function` references in
comments, attempt `importlib.import_module(...)` + `getattr(...)`, fail
loudly if the symbol no longer exists. Catches #2155 ×2 directly.

### R3 (T1 best-effort + T2 hardening) — PR-template "Defaults Table" + gate

Add to `.github/PULL_REQUEST_TEMPLATE.md`:

```markdown
## Defaults table (mandatory if this PR adds/changes any ENABLE_* / *_DEFAULT)
| env-var | default in code | default claimed in this PR body |
|---------|-----------------|---------------------------------|
| ENABLE_OPRA_UOA | "1" | "1" |
```

**T1 (best-effort)** — `tools/check_defaults_table.py` regex-grep'es the diff
for `os\.environ\.get\("<KEY>",\s*"<X>"\)` and `os\.getenv\("<KEY>",\s*"<X>"\)`
and cross-checks against the table. Lands fast; catches the obvious cases
(#2155 ×3 + #2163 ×1).

**T2 (hardening)** — replace the regex with an AST-walker over the diff'd
files. Reason: regex misses values flowing through helpers
(`_env_int(...)`, `_env_bool(...)`, module-level constants like
`_DEFAULT_OPRA = "1"; os.environ.get(KEY, _DEFAULT_OPRA)`) and would clear a
PR that is silently inconsistent. The AST pass resolves call targets and
the constant-assignment graph, then asserts equality with the table. Mark
the T1 gate **non-blocking warning** until the T2 AST pass lands; flip to
blocking once T2 is green.

### R4 (T2) — Single feature-flag source of truth

Replace scattered `os.environ.get("ENABLE_OPRA_UOA", "1")` with
`from feature_flags import FLAGS; FLAGS.enable_opra_uoa`. `feature_flags.py`
exposes typed booleans and is the **only** module allowed to call
`os.environ.get` for `ENABLE_*`. Add a Ruff custom rule (or
`tests/test_feature_flag_centralization.py`) that fails when
`os.environ.get("ENABLE_*"` appears outside `feature_flags.py`.
Wires `Config.enable_opra_uoa` into reality. Kills C2 entirely.

### R5 (T1, promoted from T2 — see §2.1) — Concurrency safety for `FMPClient._endpoint_usage_stats`

Add `self._stats_lock = threading.Lock()` to `FMPClient.__post_init__` (or
reuse the existing `self._lock`; pick one and document). Wrap
`_record_endpoint_event` mutation and `get_endpoint_usage_stats` snapshot
under the lock. Snapshot must defensive-copy under the lock
(`{k: dict(v) for k, v in self._endpoint_usage_stats.items()}`).

**Test design — reviewer-strengthened:** a naive 32-threads × 1000-ops
increment test will likely be GREEN even *without* the lock, because the
GIL serializes individual bytecodes and the contention window for
LOAD_ATTR + INPLACE_ADD + STORE_ATTR is sub-microsecond. The test must
*manufacture* contention in one of two ways:

1. **Sleep injection** — monkey-patch the bucket update to perform
   `value = bucket["count"]; time.sleep(0.0001); bucket["count"] = value + 1`
   (i.e. expand the read-modify-write window). Without the lock, ≥1 lost
   increment is statistically guaranteed at 32×1000.
2. **Atomic-counter baseline** — run the same workload against a
   `collections.Counter` guarded by `threading.Lock`, then against the
   under-test code, and assert recorded counts agree. Any divergence
   exposes the unsynchronized path.

Land both: (1) gives a deterministic regression for the lock removal
failure mode; (2) gives a robustness oracle. Without these, the test is
security-theatre.

### R6 (T2) — Eliminate `os.environ` mutation in `_http_get`

Refactor `terminal_finnhub._get` to accept an explicit `api_key` kwarg, OR
have `_http_get` pass the key through a thread-local. Either way, **stop
writing `FINNHUB_API_KEY` into `os.environ`**. Add the call-site to the
allow-deny ledger in `tests/test_os_environ_mutation_ledger.py`.

### R7 (T1) — Mandatory error-message redaction in probes

Add to `tests/test_secret_leakage_probes.py`: AST-scan every
`scripts/probe_*.py` and flag every exception-stringification path that is
not wrapped in `_redact_sensitive_error_text` (or an explicit allowlist
entry). The heuristic must catch all of the following — naive
`str(exc)`-only matching is insufficient:

| Pattern                                                  | AST shape to detect |
|----------------------------------------------------------|---------------------|
| `print(f"err: {exc}")`                                   | `JoinedStr` containing `Name(exc)` inside `Call(print)` |
| `print("err:", exc)`                                     | `Call(print)` with `Name(exc)` positional arg |
| `print(f"err: {exc.args}")`                              | `JoinedStr` containing `Attribute(value=Name(exc), attr="args")` |
| `return (..., str(exc))` / `return (..., repr(exc))`     | `Return(Tuple)` with `Call(str|repr, [Name(exc)])` |
| `return (..., f"...{exc}...")`                           | `Return(Tuple)` containing `JoinedStr(...Name(exc)...)` |
| `logger.error("...", exc_info=True)`                     | `Call(Attribute(logger, error\|warning\|info))` with `keyword(arg="exc_info", value=True)` |
| `raise RuntimeError(str(exc))` re-raise into report dict | `Raise` with `Call(str, [Name(exc)])` |

Allowlist is opt-in per-line via `# noqa: SECLEAK` with reason. Land the
missing wrapping in `scripts/probe_databento_entitlement.py::_try_call` and
`scripts/probe_fmp_13f_endpoints.py` (use `urllib.parse` redaction instead
of `str.replace`). Kills C4.

### R8 (T1) — Expand Ruff include scope to `scripts/probe_*.py`

Edit `pyproject.toml` `[tool.ruff] include` (or remove the exclude pattern)
so the probe scripts are linted under the same `F401`/`RUF100` rules as the
rest of the codebase. Will retroactively flag the 4 #2157 findings (unused
`json` import, unused `noqa: BLE001`, plus latent ones).

### R9 (T2) — Per-new-module test-coverage tripwire

Add `tests/test_module_test_coverage_pin.py`: enumerate
`newsstack_fmp/`, `open_prep/`, `scripts/probe_*.py`; for each module,
require a `tests/test_<module_name>.py` (or a pytest collection annotation
in an existing file) to exist. Grandfather current state via an
allowlist; new modules added without a test file fail CI.
Catches the C6 gap from #2155 directly.

### R10 (T1) — Import-time safety sweep test

`tests/test_import_safety.py`: in a subprocess with **all** `*_API_KEY`
env vars unset and selected parseable env vars deliberately mis-set
(`OPRA_UOA_TRADES_WINDOW_MIN=not-an-int`), `importlib.import_module` every
`newsstack_fmp/`, `open_prep/`, `scripts/` module. Assert no exception.
Forces `int(os.getenv(...))` style import-time parsing into the existing
`_env_int(...)` / `_env_bool(...)` helpers in
[newsstack_fmp/config.py](newsstack_fmp/config.py) (note: helper is named
`_env_int`, **not** `_safe_int_env` — clarified after reviewer feedback).
Kills C7 sub-issue.

### R11 (T1) — `databento.metadata.list_datasets()` normalization helper

Add `databento_utils.list_datasets_normalized(client) -> set[str]` that
does `{str(d) for d in client.metadata.list_datasets()}`. Migrate the OPRA
probe from #2165 and any other call-site to use it. Closes my own
finding from #2165.

### R12 (T2) — "Doc-PR follows code-PR" rule

Add CI guard `tools/check_audit_doc_consistency.py` that, for any PR that
touches `docs/PROVIDER_RATIONALIZATION_AUDIT_*.md` or
`docs/AUDIT_*_*.md`, requires either (a) the same PR also contains the
referenced code change (heuristic: every `removed:` / `added:` claim in
the doc maps to a file in the diff), or (b) the PR body contains an
explicit acknowledgement
`Audit-doc-precedes-code: yes — landing PR is #N`. Catches #2161 entirely.

### R13 (T1) — Self-stale grep before push

Codify in `/memories/copilot-review-comments.md` (already partial): before
pushing any edit to a YAML/Markdown file with header comments, run
`grep -nE "<old-value>|<old-citation>" <file>` on the **whole file**, not
just the diff context. We already know this trap from F-V8-C4; today it
re-appeared in the watchdog header comment (#2153) and in #2161's TL;DR.

### R14 (T1 step 0 + T2 triage) — Resolve the 56 outstanding Copilot threads

**Step 0 (T1, prerequisite — kills the knowledge-silo risk):** the triage
protocol currently lives only in operator-local Copilot memory
(`/memories/copilot-review-comments.md`). That makes it invisible to other
maintainers and to a fresh checkout. Commit it as
`docs/COPILOT_REVIEW_TRIAGE_PROTOCOL.md` in this repo so it is versioned,
reviewable, and reproducible across machines. The memory file remains the
operator's quick-reference; the repo doc is the source of truth.

**Triage (T2):**
1. For each unresolved thread, `read_file` the cited line on `main`.
2. If suggestion already implemented (drift / stale), resolve via
   `resolveReviewThread` mutation — no code change.
3. If still actionable, queue under the next chore PR.

Expectation based on prior audits: ~60% stale / ~40% actionable,
i.e. ~22 fresh fixes. Group by file; aim for one chore-PR per cluster.
Evidence for the 60%-stale base rate: see the C4 `psutil` finding above —
stale at review time, would have been a no-op fix.

---

## 5. Prioritized remediation timeline

Reordered after reviewer feedback to weight by **blast-radius** (§2.1)
rather than frequency alone. C3/C7 items (R5, R6, R10) are promoted to T1.

| Order | Item | Tier | Est. LOC / effort | Drives down cluster |
|------:|------|------|-------------------|---------------------|
|  1 | R7 — probe secret-leak guard + redact wrapping | T1 | ~60 LOC + AST-walker | C4 (HIGH) |
|  2 | R10 — import-safety sweep | T1 | ~60 LOC | C7 (HIGH) |
|  3 | R5 — `_endpoint_usage_stats` lock + sleep-injection test | T1 | ~50 LOC + test | C3 (HIGH) |
|  4 | R6 — eliminate `FINNHUB_API_KEY` env-mutation | T1 | ~30 LOC + ledger entry | C3 (HIGH) |
|  5 | R14-step0 — commit triage protocol as repo doc | T1 | docs only | meta |
|  6 | R1 — citation validator | T1 | ~80 LOC | C1 |
|  7 | R2 — pin-test symbol validator | T1 | ~40 LOC | C1 |
|  8 | R8 — Ruff scope to `scripts/probe_*.py` | T1 | 1 line + drift fixes | C5 |
|  9 | R11 — `list_datasets_normalized` helper | T1 | ~20 LOC | C8 |
| 10 | R3 (regex part) — PR-template Defaults Table + warn-gate | T1 | ~50 LOC | C2 |
| 11 | R13 — codify whole-file grep into memory | T1 | docs only | C1 |
| 12 | R3 (AST part) — replace regex gate with AST-walker | T2 | ~120 LOC | C2 |
| 13 | R4 — `feature_flags.py` SSOT | T2 | ~80 LOC | C2 |
| 14 | R9 — module-coverage tripwire | T2 | ~60 LOC | C6 |
| 15 | R12 — audit-doc-follows-code CI guard | T2 | ~70 LOC | C1 (audit-doc class) |
| 16 | R14 — triage 56 unresolved threads | T2 | mostly resolutions | meta |

**T1 set (items 1–11) collectively prevents ~60 of today's 70 findings**
and additionally addresses the three HIGH-blast-radius clusters (C3, C4, C7)
on day one.

**T2 set (items 12–16) closes the remaining structural classes** (defaults
SSOT, missing tests, doc-leads-code) and converts the R3 warn-gate into a
blocking AST-validated gate.

---

## 6. KPIs to verify the plan worked

After landing T1 + T2:

1. **Doc-drift findings per merge train** — target: < 3 per train (today: 35).
2. **Unresolved Copilot threads after a PR is merged** — target: < 2
   (today: avg 5 per PR with findings).
3. **Pin-test/citation breakage caught locally** — target: ≥ 1 catch within 30
   days of landing R1+R2 (proves the validator is doing real work).
4. **Concurrency test stability** — `tests/test_fmpclient_stats_concurrency.py`
   green across 100 consecutive CI runs.
5. **Import-safety sweep** — green across 100 consecutive CI runs with
   randomized env-var mis-settings.

---

## 7. Lessons codified into memory **and into the repo**

Operator memory is convenient but invisible to other maintainers. Each
lesson below has both a memory entry (fast-access for the active operator)
**and** a planned repo-versioned counterpart (R14 step 0 + R12) so it
survives a fresh checkout / new contributor onboarding.

- `copilot-review-comments.md` (memory) → planned
  `docs/COPILOT_REVIEW_TRIAGE_PROTOCOL.md` (repo, R14 step 0).
  Re-emphasizes the whole-file grep before pushing YAML/MD header edits
  (R13).
- `debugging.md` (memory): doc-leads-code is a recurring trap; audit docs
  must land with or after the code they describe — codified into CI by R12.
- New: `feature-flag-defaults.md` (memory) — "single SSOT, never
  grep-distribute defaults" (R4). Repo counterpart: the `feature_flags.py`
  module + `tests/test_feature_flag_centralization.py` themselves serve
  as the versioned spec.
- New: `concurrency-shared-mutables.md` (memory) — "any module-level
  mutable dict/list touched from a `ThreadPoolExecutor` or `asyncio`
  callback needs an explicit lock + sleep-injected concurrency test"
  (R5/R6). Repo counterpart: the test files themselves
  (`tests/test_fmpclient_stats_concurrency.py`,
  `tests/test_os_environ_mutation_ledger.py`) plus a short section in
  `docs/COPILOT_REVIEW_TRIAGE_PROTOCOL.md`.

---

## 8. Appendix — Raw inline-comment dump

Captured at retrospective time for traceability:
`/tmp/audit-l1-review/inline-comments.txt` (21 KB, all 70 findings with
`{path}:{line} {body}` per line). Re-fetched any time via:

```bash
gh api repos/skippALGO/skipp-algo/pulls/<N>/comments --paginate \
  | python3 -c "import sys,json;[print(f\"{c['path']}:{c.get('line')} {c['body']}\") for c in json.load(sys.stdin) if 'opilot' in c['user']['login'].lower()]"
```

---

## 9. Revision history

### v2 — 2026-05-12, post senior-engineer review

Reviewer findings (8) and how each is addressed in this revision:

| # | Reviewer finding                                                                 | Fix in v2                                                                                       |
|---|----------------------------------------------------------------------------------|-------------------------------------------------------------------------------------------------|
| 1 | C4 `psutil` evidence is stale (`requirements.txt:16` already had it from #2151)  | Removed from C4 bullet list; added explanatory note re-attributing it to R14's stale-thread thesis. §1 cluster column for #2148 updated. |
| 2 | R10 cited `_safe_int_env` but actual helper is `_env_int`                        | R10 corrected; clarification note added.                                                        |
| 3 | C2 said "three" call-sites but actually four (incl. `scripts/probe_providers.py:344`); also missed proof that `Config.enable_opra_uoa` has 0 importers | C1 PR↔impl block expanded to four sites with file paths + line numbers; C2 bullet rewritten with the `git grep` evidence. |
| 4 | C3 #1 should cite the explicit "fine within a single producer run" comment and refute it, not silently treat the bug as "nobody thought about it" | C3 #1 now block-quotes the comment, then refutes with the bytecode-level argument (LOAD_ATTR + INPLACE_ADD + STORE_ATTR is not single-bytecode-atomic). |
| 5 | R3 regex-based gate is bypassed by helper-wrapped or constant-mediated defaults | R3 split into T1 (regex, warn-only) + T2 (AST-walker, blocking). Timeline reflects both rows.   |
| 6 | R7 AST heuristic too narrow — misses f-strings, `exc.args`, `logger.error(..., exc_info=True)`, return-tuples | R7 expanded with a 7-row pattern table covering every exception-stringification path.            |
| 7 | R14 protocol lives in operator-local memory only — knowledge silo                | R14 step 0 added: commit `docs/COPILOT_REVIEW_TRIAGE_PROTOCOL.md` to repo. §7 reframed to pair every memory file with a versioned repo counterpart. |
| 8 | Frequency-only prioritization undersells C3/C4/C7 blast-radius                   | New §2.1 Failure-risk matrix with explicit blast-radius column. §5 timeline reordered: R5/R6/R7/R10 promoted to T1. |

Bonus reviewer point (R5 test design): naive 32×1000 thread test with GIL +
`setdefault` may pass even without the lock → "security theatre". R5 test
spec rewritten to require sleep-injection between read-modify-write **and**
an `Atomic-Counter` baseline-comparison oracle.

### v1 — 2026-05-12, initial submission
Original report opened as PR #2166.
