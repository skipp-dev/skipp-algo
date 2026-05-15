# CI Reliability & Drift-Control Review — 2026-05-15

## Scope

Review focus:

- GitHub workflow failures and their actual root-cause clusters
- brittle governance / ledger tests and drift hot spots
- Windows/Linux portability risks in workflow-adjacent tests
- verification discipline for CI fixes
- small, review-derived remediation steps instead of one large cleanup branch

This review was executed against the local checkout plus recent GitHub Actions evidence from `skippALGO/skipp-algo`.

## Executive summary

The dominant recent GitHub Actions failure cluster was **not** a broad runtime regression. It was a **stale line-pinned ledger cluster** caused by line drift in `open_prep/realtime_signals.py` and expressed through:

- `tests/test_noqa_budget.py`
- `tests/test_subprocess_spawn_sites_ledger.py`

That cluster reproduced across multiple unrelated branches and both PR/push CI paths.

A second, separate reliability cluster exists in the workflow-governance tests on Windows:

- stale `continue-on-error` line inventory
- workflow YAML reads without explicit `encoding="utf-8"`
- Unix `grep` dependency inside a test

These are smaller, but they are classic cross-platform CI papercuts and were locally reproducible.

## Failure matrix

| Workflow / Runs | Trigger | Failing job / step | Root cause | Local repro | Status |
|---|---|---|---|---|---|
| `CI` — runs `25920070238`, `25919421866`, `25919428494` | `pull_request` | `validate` → `Run Python tests (PR — no coverage)` | stale line-pinned ledgers after `open_prep/realtime_signals.py` shifted; failures in `tests/test_noqa_budget.py` and `tests/test_subprocess_spawn_sites_ledger.py` | yes | fixed in targeted ledger rebaseline work |
| `CI` — runs `25919420454`, `25919427731`, `25919422835` | `push` | `validate` → `Run Python tests (push — with coverage)` | same stale ledger cluster as above; coverage path only made runtime longer, not different in root cause | yes | fixed in targeted ledger rebaseline work |
| local workflow-governance slice | local Windows checkout | focused pytest run | `tests/test_workflow_continue_on_error_inventory.py` stale `_ALLOWED`, `tests/test_workflow_databento_artifact_handoff.py` used bare `read_text()`, `tests/test_workflow_orphan_inventory.py` shelled out to `grep` | yes | fixed in this review |
| `CI` run `25921435515` (`fix(ci): rebaseline realtime_signals ledgers`) | `push` | `validate` → push coverage path | current verification run for the ledger fix | local counterpart verified in isolated checkout | in progress at review time |
| PR `2234` (`Harden GPU ML/RL research workflow reporting`) / run `25921979577` | `pull_request` | `validate` + `fast-gates` | not part of the historical failure cluster; still in-flight at review time | not applicable in current checkout | in progress at review time |

## Evidence highlights

### 1. Recent CI failures were the same root cause repeated

Representative failed runs showed the same two failing tests:

- `tests/test_noqa_budget.py::test_no_new_noqa_sites`
- `tests/test_subprocess_spawn_sites_ledger.py::test_subprocess_run_site_ledger_pin`

The failing sites were:

- `open_prep/realtime_signals.py:187`
- `open_prep/realtime_signals.py:333`

This confirms a **drift cluster**, not multiple unrelated breakages.

### 2. The realtime-signals ledger cluster is a true hot spot

`open_prep/realtime_signals.py` is pinned by multiple sister ledgers, including:

- `tests/test_noqa_budget.py`
- `tests/test_subprocess_spawn_sites_ledger.py`
- `tests/test_dangerous_io_zero_surface_pin.py`
- `tests/test_random_tempfile_ledger_pin.py`
- `tests/test_fcntl_flock_zero_surface.py`

Conclusion: changing that file without coordinated rebaseline checks is a high-probability CI failure mode.

### 3. Workflow-governance tests had three reproducible Windows fragilities

Locally reproducible before fixes:

1. `tests/test_workflow_continue_on_error_inventory.py`
   - stale exact line inventory across 7 workflows
2. `tests/test_workflow_databento_artifact_handoff.py`
   - bare `Path.read_text()` on workflow YAML triggered `UnicodeDecodeError` under cp1252
3. `tests/test_workflow_orphan_inventory.py`
   - external `grep` subprocess caused `FileNotFoundError` on Windows

These are classic repo-level reliability bugs: small, local, and absolutely capable of wasting large amounts of triage time.

## Brittle test register

| Test file | Pin / guard type | Hot spot | Drift risk | Recommendation |
|---|---|---|---|---|
| `tests/test_noqa_budget.py` | exact `(file, line, codes)` inventory | `open_prep/realtime_signals.py` | high | keep, but treat as part of a sister-ledger bundle |
| `tests/test_subprocess_spawn_sites_ledger.py` | exact `(file, line)` subprocess site ledger | `open_prep/realtime_signals.py` | high | keep, but prefer hot-spot bundle review over isolated edits |
| `tests/test_workflow_continue_on_error_inventory.py` | exact workflow YAML line inventory | `.github/workflows/*.yml` | very high | keep scanner, but reduce manual line-tracking burden |
| `tests/test_dangerous_io_zero_surface_pin.py` | exact `os.kill` sites | `open_prep/realtime_signals.py`, `scripts/ib_client_id.py` | medium-high | keep; valuable zero-surface guard |
| `tests/test_random_tempfile_ledger_pin.py` | exact tempfile sites | several, incl. `open_prep/realtime_signals.py` | medium-high | keep; valuable security control |
| `tests/test_fcntl_flock_zero_surface.py` | exact flock sites | `open_prep/realtime_signals.py`, `open_prep/watchlist.py` | medium-high | keep; pair with portability review |
| `tests/test_builtin_open_encoding_ledger.py` | missing-encoding frozen ledger | `scripts/*` | medium | keep until surface shrinks |
| `tests/test_workflow_databento_artifact_handoff.py` | workflow text scan | workflow YAML | medium | always read workflow text as UTF-8 |
| `tests/test_workflow_orphan_inventory.py` | orphan inventory scan | workflow/test linkage | medium | pure Python only; no external shell tools |

## Hotspot map

### `open_prep/realtime_signals.py`

Why it is hot:

- subprocess site pins
- `# noqa` pins
- `os.kill` pins
- tempfile pins
- `fcntl.flock` pins

Operational rule:

- when this file moves, re-check all sister ledgers together
- do not treat a single failing ledger as the whole blast radius

### `.github/workflows/smc-library-refresh.yml`

Why it is hot:

- large file
- multiple workflow governance tests refer to it
- non-ASCII text makes default-decoding mistakes visible on Windows
- line-oriented tests are especially fragile here

Operational rule:

- workflow YAML tests must use explicit UTF-8
- avoid raw line-number coupling unless the audit value is very high

### `scripts/ib_client_id.py`

Why it is hot:

- POSIX-only `fcntl` usage
- `os.kill(..., 0)` ledger surface
- text-mode file operations and lock behavior intersect with portability rules

Operational rule:

- keep lock behavior explicit and guard portability assumptions in tests

## Remediation executed during this review

The review was not purely observational; the following issues were fixed locally:

- `tests/test_workflow_continue_on_error_inventory.py`
  - rebaselined the stale `_ALLOWED` inventory to current `_scan_workflow()` output
- `tests/test_workflow_databento_artifact_handoff.py`
  - switched workflow text read to explicit `encoding="utf-8"`
- `tests/test_workflow_orphan_inventory.py`
  - replaced external `grep` usage with pure-Python UTF-8 scanning
- `tests/test_feature_importance_daily_workflow.py`
  - hardened workflow text loading to UTF-8
- `tests/test_fvg_quality_recal_shadow_workflow.py`
  - hardened workflow text loading to UTF-8
- `tests/test_realtime_signals_sister_ledger_guardrail.py`
   - added a hotspot coupling guard so `open_prep/realtime_signals.py`
      line drift cannot be rebaselined in `tests/test_noqa_budget.py`
      without also updating `tests/test_subprocess_spawn_sites_ledger.py`

## Verification performed

### Isolated ledger-fix verification

For commit `a9bdbb6147dc70b6b14d59396aa84c02b3168949` on `fix/ci-realtime-signals-ledgers`:

- direct file-content inspection confirmed `187` / `333` ledger values
- direct Python module loading confirmed the effective constants matched the file text
- targeted tests passed:
  - `17 passed` serial
  - `17 passed` with xdist / `worksteal`

### Local workflow-review verification

After the workflow-governance fixes above:

- `pytest -n0 -q tests/test_workflow_continue_on_error_inventory.py tests/test_workflow_databento_artifact_handoff.py tests/test_workflow_orphan_inventory.py`
  - `15 passed`
- broader local workflow sanity slice:
  - `tests/test_workflow_continue_on_error_inventory.py`
  - `tests/test_workflow_databento_artifact_handoff.py`
  - `tests/test_workflow_orphan_inventory.py`
  - `tests/test_feature_importance_daily_workflow.py`
  - `tests/test_fvg_quality_recal_shadow_workflow.py`
  - result: `28 passed`

## Top-10 hardening backlog

1. **Codify the `open_prep/realtime_signals.py` sister-ledger bundle**
   - one edit there should automatically trigger a checklist of related tests
2. **Reduce manual line-number maintenance in workflow inventories**
   - scanner-backed refresh or anchored rationale blocks instead of ad-hoc hand counts
3. **Ban bare workflow `read_text()` calls in tests**
   - add a small helper or guardrail test for UTF-8-only workflow reads
4. **Ban external shell utilities in Python tests**
   - especially `grep`, `sed`, `awk` in test helpers
5. **Document CI parity modes explicitly**
   - serial debug vs xdist vs push-with-coverage
6. **Create a fast governance smoke set**
   - the highest-signal workflow + ledger guards in one focused command
7. **Separate acute CI failure slices from known backlog debt**
   - avoid mixing unrelated local full-suite issues into a targeted fix
8. **Add a workflow-edit checklist**
   - when `.github/workflows/*.yml` changes, review inventory/guard tests in the same PR
9. **Prefer semantic guards over raw line pins where possible**
   - especially for workflow inventories whose audit intent is presence, not exact coordinates
10. **Standardize clean-room verification for CI fixes**
    - detached worktree / target SHA / cache-neutral test rerun before pushing

## Clean-room verification runbook

1. Validate the target SHA in a clean or detached worktree.
2. Inspect the exact files in the commit tree directly (`git show <sha>:path`).
3. Remove `__pycache__` where relevant and set:
   - `PYTHONDONTWRITEBYTECODE=1`
   - `PYTHONPATH=<checkout>`
4. Re-run the exact failing tests first.
5. If the CI path uses xdist or coverage, re-run with the same relevant mode after the serial pass.
6. Keep unrelated failures separate from the acute failure slice.
7. Only then push and watch the exact GitHub run associated with that SHA.

## Recommended PR slicing

### PR 1 — Done / immediate drift unblocking

- ledger rebaseline for the `realtime_signals.py` CI failure cluster
- workflow-governance fixes for stale inventory + UTF-8 + cross-platform orphan scan

### PR 2 — Workflow test hardening

- shared UTF-8 workflow text helpers
- eliminate remaining shell-tool dependencies in tests
- document workflow-test conventions near the test suite

### PR 3 — Hotspot-ledger coupling

- introduce explicit hot-spot maps / comments for `open_prep/realtime_signals.py`
- reduce reviewer guesswork when sister ledgers drift together

### PR 4 — Verification runbook + governance smoke set

- add repo doc / task / maybe VS Code task for clean-room CI repro and focused governance validation

## Bottom line

The repo's recent CI noise is dominated by **drift-management weaknesses**, not by a broad Python quality collapse.

The most valuable engineering move is therefore:

- keep the strongest governance tests,
- reduce their accidental brittleness,
- and formalize clean-room verification so future CI fixes are faster and less ambiguous.
