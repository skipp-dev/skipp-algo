# Audit L-1 Merge-Train — Code-Review Retrospective & Remediation Plan

**Date:** 2026-05-12
**Scope:** 18 PRs merged today (#2146 → #2165), inclusive of the
"provider-rationalization" merge train (#2153–#2164) and the wrap-up #2165.
**Reviewer signal source:** GitHub Copilot inline-review comments fetched via
`gh api repos/.../pulls/<N>/comments --paginate` plus
`reviewThreads` GraphQL (per `/memories/copilot-review-comments.md`).

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
| #2148 | F-V8-Q5b skip oversized second_detail sheets         | 2        | C1 (psutil claim), C7 (eager arg) |
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
  `ENABLE_OPRA_UOA` "default 0 for safe rollout" in PR body, but **all 3 code
  sites and `Config.enable_opra_uoa` default to "1"** (#2155 ×3, #2163 ×1).
  Confirmed today on `main`:
  ```text
  open_prep/streamlit_monitor.py:677  os.environ.get("ENABLE_OPRA_UOA", "1")
  open_prep/streamlit_monitor.py:2277 os.environ.get("ENABLE_OPRA_UOA", "1")
  newsstack_fmp/config.py:66          os.getenv("ENABLE_OPRA_UOA", "1") == "1"
  ```
- **CHANGELOG arithmetic / citation error** — "#2154 → #2161 (8 PRs) +
  #2163" is internally inconsistent (range already accounts for 8) (#2165).
- **Audit document landed describing a state the repo did not yet have**
  (#2161 ×7) — every one of the 7 findings is a claim about removed/added code
  that landed only in a *later* PR in the train. Doc lapped the code.
- **Comments referencing constants that were removed in the same PR** —
  `UW_FLOW_ALERTS_PATH` cited in `docs/OPEN_PREP_OPS_QUICK_REFERENCE.md` (#2164).

### C2 — Default-value / configuration inconsistency (≈5 findings)
- Three independent `os.environ.get("ENABLE_OPRA_UOA", "1")` call-sites — no
  single source of truth. Drift inevitable when default changes.
- `Config.enable_opra_uoa` flag introduced (#2155) but **never wired** —
  every consumer reads `os.environ` directly. Dead config.

### C3 — Concurrency / shared-state safety (3 findings, all real bugs)
Confirmed today on `main`:

- **`FMPClient._endpoint_usage_stats`** (#2154 ×2): mutated unsynchronized from
  `_record_endpoint_event` while `get_batch_quotes()` submits via
  `ThreadPoolExecutor`. Read–modify–write increments will silently lose
  counts and can `RuntimeError: dictionary changed size during iteration` from
  `get_endpoint_usage_stats()` snapshotting.
  Spot-checked: no `threading.Lock` guards `_endpoint_usage_stats` in
  [open_prep/macro.py](open_prep/macro.py#L676).
- **`_http_get` env-var mutation** (#2156): `open_prep/macro.py` line 2041
  temporarily writes `FINNHUB_API_KEY` into `os.environ` around the call into
  `terminal_finnhub._get`. Process-global mutation under concurrent fetch is
  racy AND violates the spirit of `tests/test_os_environ_mutation_ledger.py`.
- **Watchdog branch-agnostic guard + 20-row pagination cap** (#2153 ×2):
  `RUN_COUNT` can be paged out and the watchdog double-dispatches.

### C4 — Secret leakage via error/log surfaces (3 findings)
- `_try_call` in [scripts/probe_databento_entitlement.py](scripts/probe_databento_entitlement.py)
  returns `str(exc)` directly into the report. Databento client errors can
  embed request URLs/headers — leaks key. Repo already has
  `databento_client._redact_sensitive_error_text()` that was not used (#2157).
- `url.replace(api_key, "***")` redaction in
  [scripts/probe_fmp_13f_endpoints.py](scripts/probe_fmp_13f_endpoints.py)
  silently fails when key contains characters that `urlencode` percent-escapes
  (#2154).
- `psutil` claimed-imported but **not in `requirements.txt`** (#2148) — not a
  secret leak, but the same class of "claim ≠ reality" hazard.

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
- `expected_min=0` in `probe_fmp_eod_bulk` bypasses the `len(data) <
  expected_min` check, then crashes on `data[0]` (#2159, **real bug**).
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
ledger test file, find ``backtick-quoted ``module.function`` references in
comments, attempt `importlib.import_module(...)` + `getattr(...)`, fail
loudly if the symbol no longer exists. Catches #2155 ×2 directly.

### R3 (T1) — PR-template "Defaults Table" + grep-gate

Add to `.github/PULL_REQUEST_TEMPLATE.md`:

```markdown
## Defaults table (mandatory if this PR adds/changes any ENABLE_* / *_DEFAULT)
| env-var | default in code | default claimed in this PR body |
|---------|-----------------|---------------------------------|
| ENABLE_OPRA_UOA | "1" | "1" |
```

Add CI step `tools/check_defaults_table.py` that `gh pr view --json body`s
the current PR, extracts the table, and `grep`s the diff for matching
`os.environ.get("<KEY>", "<X>")` — fails the build if claimed-default ≠
code-default. Catches #2155 ×3 + #2163 ×1.

### R4 (T2) — Single feature-flag source of truth

Replace scattered `os.environ.get("ENABLE_OPRA_UOA", "1")` with
`from feature_flags import FLAGS; FLAGS.enable_opra_uoa`. `feature_flags.py`
exposes typed booleans and is the **only** module allowed to call
`os.environ.get` for `ENABLE_*`. Add a Ruff custom rule (or
`tests/test_feature_flag_centralization.py`) that fails when
`os.environ.get("ENABLE_*"` appears outside `feature_flags.py`.
Wires `Config.enable_opra_uoa` into reality. Kills C2 entirely.

### R5 (T2) — Concurrency safety for `FMPClient._endpoint_usage_stats`

Add `self._stats_lock = threading.Lock()` to `FMPClient.__post_init__`.
Wrap `_record_endpoint_event` mutation and `get_endpoint_usage_stats`
snapshot under the lock. Add regression test
`tests/test_fmpclient_stats_concurrency.py` that hammers
`_record_endpoint_event` from 32 threads × 1000 ops and asserts the
recorded count equals `32_000`. Real bug, real fix.

### R6 (T2) — Eliminate `os.environ` mutation in `_http_get`

Refactor `terminal_finnhub._get` to accept an explicit `api_key` kwarg, OR
have `_http_get` pass the key through a thread-local. Either way, **stop
writing `FINNHUB_API_KEY` into `os.environ`**. Add the call-site to the
allow-deny ledger in `tests/test_os_environ_mutation_ledger.py`.

### R7 (T1) — Mandatory error-message redaction in probes

Add to `tests/test_secret_leakage_probes.py`: AST-scan every
`scripts/probe_*.py`; flag any `print(<…str(exc)…>)` or
`return (..., str(exc))` that is not wrapped in `_redact_sensitive_error_text`
or equivalent. Land the missing wrapping in
`scripts/probe_databento_entitlement.py::_try_call` and
`scripts/probe_fmp_13f_endpoints.py` (use `urllib.parse` redaction
instead of `str.replace`). Kills C4.

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
Forces `int(os.getenv(...))` style import-time parsing into
`_safe_int_env` helpers (which already exist in `newsstack_fmp/config.py`).
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

### R14 (T2) — Resolve the 56 outstanding Copilot threads

Per `/memories/copilot-review-comments.md` triage protocol:
1. For each unresolved thread, `read_file` the cited line on `main`.
2. If suggestion already implemented (drift / stale), resolve via
   `resolveReviewThread` mutation — no code change.
3. If still actionable, queue under the next chore PR.

Expectation based on prior audits: ~60% stale / ~40% actionable,
i.e. ~22 fresh fixes. Group by file; aim for one chore-PR per cluster.

---

## 5. Prioritized remediation timeline

| Order | Item | Tier | Est. LOC / effort |
|------:|------|------|-------------------|
| 1 | R1 — citation validator | T1 | ~80 LOC |
| 2 | R2 — pin-test symbol validator | T1 | ~40 LOC |
| 3 | R7 — probe secret-leak guard + redact wrapping | T1 | ~60 LOC |
| 4 | R8 — Ruff scope to `scripts/probe_*.py` | T1 | 1 line + drift fixes |
| 5 | R10 — import-safety sweep | T1 | ~60 LOC |
| 6 | R11 — `list_datasets_normalized` helper | T1 | ~20 LOC |
| 7 | R3 — PR-template Defaults Table + gate | T1 | ~50 LOC |
| 8 | R13 — codify whole-file grep into memory | T1 | docs only |
| 9 | R14 — triage 56 unresolved threads | T1/T2 | mostly resolutions |
|10 | R5 — `_endpoint_usage_stats` lock + concurrency test | T2 | ~50 LOC |
|11 | R6 — eliminate `FINNHUB_API_KEY` mutation | T2 | ~30 LOC + ledger entry |
|12 | R4 — `feature_flags.py` SSOT | T2 | ~80 LOC |
|13 | R9 — module-coverage tripwire | T2 | ~60 LOC |
|14 | R12 — audit-doc-follows-code CI guard | T2 | ~70 LOC |

**T1 set (items 1–9) collectively prevents ~58 of today's 70 findings**
(every C1, C4, C5, C7-import, C8 finding plus the structural Defaults gap).

**T2 set (items 10–14) prevents the remaining structural classes**
(concurrency, env-var mutation, missing tests, doc-leads-code).

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

## 7. Lessons codified into memory

The following will be (or already are) added to `~/.../memories/`:

- `copilot-review-comments.md`: ✅ existing — re-emphasize the
  whole-file grep before pushing YAML/MD header edits (R13).
- `debugging.md`: doc-leads-code is a recurring trap; audit docs must land
  with or after the code they describe (R12).
- New: `feature-flag-defaults.md` — "single SSOT, never grep-distribute
  defaults" (R4).
- New: `concurrency-shared-mutables.md` — "any module-level mutable dict/list
  touched from a `ThreadPoolExecutor` or `asyncio` callback needs an
  explicit lock + concurrency test" (R5/R6).

---

## 8. Appendix — Raw inline-comment dump

Captured at retrospective time for traceability:
`/tmp/audit-l1-review/inline-comments.txt` (21 KB, all 70 findings with
`{path}:{line} {body}` per line). Re-fetched any time via:

```bash
gh api repos/skippALGO/skipp-algo/pulls/<N>/comments --paginate \
  | python3 -c "import sys,json;[print(f\"{c['path']}:{c.get('line')} {c['body']}\") for c in json.load(sys.stdin) if 'opilot' in c['user']['login'].lower()]"
```
