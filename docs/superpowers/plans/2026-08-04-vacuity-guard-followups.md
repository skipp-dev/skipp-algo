# Vacuity Guard Follow-ups Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the four gaps the merged vacuity guard (#4355/#4356/#4357) knowingly left open, so that "green without having looked" stays caught in the two shapes the analyzer currently cannot see, and so that the eleven browserless TypeScript tests stop gating nothing.

**Architecture:** Three of the four items extend the existing single-file AST analyzers (`scripts/detect_vacuous_claims.py`, `scripts/detect_vacuous_claims_ts.ts`) rather than replacing them. The design rule that made the first round reviewable is preserved verbatim: **the analyzer only classifies what it watched being produced.** Each new rule therefore names the producer it can see, and every rule is justified by a measured claim count on `origin/main` — a detector that reports nothing new is not built. The fourth item is CI wiring plus one dependency pin; it touches no analyzer.

**Tech Stack:** Python 3.12 (`ast`), TypeScript 5 (`typescript` compiler API, already a devDependency), pytest, `node:test` via `tsx`, GitHub Actions.

## Measurements this plan is built on

Every number below was measured on `origin/main` at **`fe25ad1ce`** on **2026-08-04**, in a clean sibling worktree, with `/Users/spreuss/Documents/skipp-algo/.venv/bin/python` (3.12). They are the plan's checkpoints: if an implementer's number differs, that is a signal to reconcile before proceeding, not to adjust the expectation.

| Fact | Value |
|---|---|
| Current Python claim set (`tests/`, 1626 files) | **13**, all exempted in `pin_registry.toml` |
| Task 1 — empty collection literals become emptiable | **+7** claims → 20 |
| Task 2 — properties of objects the scope produced | **+30** claims → 50 |
| Task 2 — non-empty-subset witness clears | exactly **1** would-be false positive (`test_smc_volume_profile.py::test_span_distribution_spreads_volume_beyond_close_row::profile.rows`) |
| Task 3 — TypeScript equivalent | ~~**4** sites, 3 distinct~~ → **1** site (`tv_r5_session_diagnostics.test.ts:90 result.failures`). **This row was wrong; corrected 2026-08-04 while executing.** The three `tv_shared.test.ts` `capture.lines` occurrences are bare `assert.ok(x.some(f))`, which `vacuousReceiver` excludes by documented design — `[].some(f)` is `false`, so it fails loudly rather than passing vacuously. The measurement script behind this row *approximated* `vacuousReceiver` by collecting `every`/`some` receivers instead of applying it. Apply the rule; do not re-derive it. |
| Task 4 — the 11 browserless exempt TS tests | **103 tests, 103 pass, 0 fail, 1103 ms** (`npx tsx --test`, wall 1.82 s) |
| Task 5 — `starlette` | ~~1.3.1 installed, not pinned anywhere in `requirements.txt`~~ → **incomplete; corrected while executing.** `requirements.lock` — which the heavy `ci.yml` lane installs — pinned **1.0.0**, frozen since 2026-03-22, while the *required* `fast-gates` lane and the production daemon image both install unpinned `requirements.txt` and resolved to **1.3.1**. The defect was not "unpinned"; it was **four install paths disagreeing**, with the required gate and production on one version and the full suite on another. |
| Task 5 — `httpx2` | exists on PyPI, latest **2.9.1**; **8** test files use `TestClient` (not 7 — one constructs it without a matching import line). **Not adopted**, by measurement — see the corrections section. |

### Two things measured and deliberately NOT built

State these in the PR body. They are findings, not omissions.

1. **Cross-module constant resolution has zero yield.** The follow-up note said property accesses whose producer the analyzer never saw are invisible in both halves. Of the 33 such Python sites, the largest group is `<module alias>.<CONST>`. Every one of them was resolved by hand on 2026-08-04 and every one is a **non-empty literal** — `FAMILIES = ("BOS", "OB", "FVG", "SWEEP")` (`scripts/build_backtest_slippage_samples.py:77`), `WEEKDAYS = ("Mon", …)` (`scripts/plan_2_8_alert_history_heatmap.py:32`), `VALID_STATUSES = frozenset({…})` (`scripts/plan_2_8_ledger_red_index_median.py:15`), `SHARED_LIBRARIES` (`scripts/pine_library_freshness.py:41`), `_STRICT_RELEASE_WARNING_CODES` (`smc_integration/provider_health.py:43`), `SURFACE_DEFINITIONS` (`scripts/smc_bus_manifest.py:255`). Teaching the analyzer to follow imports would therefore add cross-file machinery that classifies **nothing** — and blanket-classifying module attributes *without* resolving them would turn all of these into false positives. That is why Task 2's rule is scoped to objects produced **inside the function**, and why module aliases and globals are excluded by construction rather than by a filter.

2. **A chained-comparison witness has zero yield.** `assert len(ib.placed) == res["intent_count"] >= 1` (`tests/test_smoke_smc_to_ibkr_adapter.py:280`) is a real witness the analyzer cannot read, because `witness_keys` requires `len(test.ops) == 1`. It was measured against the full Task 1 + Task 2 claim set and clears **nothing**: `ib` is bound by `(ib,) = _FakeIB.instances` — a tuple unpacking of an *attribute*, not of a call — so `ib.placed` is not classified under Task 2's rule in the first place. Building the chain reader would add a branch that never fires. Leave it. If a future rule ever classifies `ib.placed`, this becomes actionable and the measurement above is the starting point.

## Global Constraints

Copied verbatim from `CLAUDE.md`, the repo's PR-flow skill, and the constraints that governed the first vacuity round. Every task's requirements implicitly include this section.

- **No unverified assumptions.** Every assumption, caveat, or "maybe / probably / could / should" claim about anything *checkable* must be verified **before** you state it, and resolved into exactly one of three outcomes: TRUE / FALSE / → follow-up PR.
- **Never merge without an explicit signal from the user.**
- **Never `--no-verify`.**
- Use the repo venv: `/Users/spreuss/Documents/skipp-algo/.venv/bin/python` (3.12). **Never** the system 3.9.
- Ledger/guard pytest runs **only** with `PYTEST_ADDOPTS="-n 4"` (or `PYTEST_XDIST_AUTO_NUM_WORKERS=4`). `-n auto` OOMs at rc=137 on 16 GB.
- Run `ruff check .` **separately** — `scripts/run_ledger_drift_guard.sh` does not cover it.
- **Never pipe the guard (or a push whose success you are testing) to `tail`** — the pipeline returns tail's `0` and masks a real failure. Redirect to a file and check `$?`.
- **Sibling worktree only**, e.g. `/Users/spreuss/Documents/skipp-algo-wt-<name>`. **Never** nested inside the main checkout, **never** under `.claude/worktrees/` — the broad-except/budget guards walk the tree and produce false positives.
- `git push` **always** with `run_in_background=true`; a foreground timeout orphans the pre-push hook.
- **`git status` before every commit** — three tests write into `governance/` and `artifacts/`.
- **Never parse `pin_registry.toml` outside `tests/_pin_registry.py`** (ADR-0009).
- Prefer **net-zero (1-for-1) edits** near pinned production `.py` sites; a line added above a pinned call site drifts the ledger.
- Commit trailer: `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>`. PR bodies end with `🤖 Generated with [Claude Code](https://claude.com/claude-code)`.
- **A false positive is never silenced with an exemption.** Three verdicts, not interchangeable: *fix* (add a witness next to the loop), *declare* (dated exemption in `pin_registry.toml` naming the test that does the proving), *sharpen* (the detector is wrong → write the fixture first, then change the detector). Waiving a detector bug hides it in a registry nobody re-derives.
- **Under-reporting beats fabricating.** When a rule is uncertain, the analyzer must return "not a claim" rather than invent a witness. A fabricated witness makes a genuinely vacuous test look proven; a missed claim only leaves the status quo.
- The main checkout `/Users/spreuss/Documents/skipp-algo` sits on an **old HEAD with dirty artifacts** (verified 2026-08-04: `5e5243fd3`). Do not work in it. Branch off `origin/main` in a sibling worktree.

## File Structure

| File | Responsibility | Touched by |
|---|---|---|
| `scripts/detect_vacuous_claims.py` | Python analyzer. Single renderer `_render`; `classify_iterable` decides emptiability; `witness_keys` decides proof. | Tasks 1, 2 |
| `tests/test_detect_vacuous_claims.py` | Analyzer unit tests. Fixtures are **inline source strings**, never repo files — the contract is about shapes. Helper: `_kinds(source) -> {iterable: kind}`. | Tasks 1, 2 |
| `tests/test_vacuous_claim_guard.py` | The repo-wide merge gate. Unchanged by this plan. | — |
| `pin_registry.toml`, section `[vacuous_claim_guard.exemptions]` | `"file::test::iterable" -> "YYYY-MM-DD: reason"`. Read only through `tests/_pin_registry.py`. | Tasks 1, 2 |
| ~17 files under `tests/` | The fix-or-declare round for the new claims. | Tasks 1, 2 |
| `scripts/detect_vacuous_claims_ts.ts` | TypeScript analyzer. `ScopeChain` resolves per-block facts. | Task 3 |
| `automation/tradingview/tests/vacuous_claims_ts.test.ts` | TS analyzer tests + `TS_VACUITY_EXEMPTIONS` (currently `{}`, empty **by measurement**). Helper: `kinds(source)`. | Task 3 |
| `.github/workflows/tv-onboarding-packages.yml` | The **only** TS runner. No discovery — an explicit `npx tsx --test` list plus `paths:` filters. | Task 4 |
| `tests/test_fast_gates_silent_skip_coverage.py` | `_TS_TESTS_INTENTIONALLY_UNGATED` (13 members) and the counts comment above it. | Task 4 |
| `requirements.txt` | Dependency pins. | Task 5 |

Tasks 1 and 2 both change `classify_iterable` and both run a fix-or-declare round; they are separate tasks because a reviewer can meaningfully accept the empty-literal rule and reject the produced-object rule, and because their claim sets are disjoint and separately measured.

---

### Task 1: Empty collection literals are emptiable (Python)

The TypeScript half already classifies `[]` (`"empty array literal"`, `detect_vacuous_claims_ts.ts:164-166`) because the recording-array idiom dominates that suite. The Python half does not, so the same idiom — `calls = []`, something appends, then a loop asserts over `calls` — is invisible. Measured: **+7 claims**.

**Files:**
- Modify: `scripts/detect_vacuous_claims.py` — `classify_iterable` (currently lines 95-135) and the module constants block (lines 47-50)
- Test: `tests/test_detect_vacuous_claims.py` (append fixtures; helper `_kinds` already exists at line 16)
- Modify: `pin_registry.toml`, `[vacuous_claim_guard.exemptions]` (line 843) — only for sites triaged as *declare*
- Modify: whichever of the 7 named test files are triaged as *fix*

**Interfaces:**
- Consumes: `_is_nonempty_literal(node) -> bool` (line 271) — already handles `List`/`Set`/`Tuple`/`Dict`/str-`Constant`; `_TRANSPARENT_CALLS` (line 48)
- Produces: kind strings `"empty literal"` (bare) and `"local empty literal"` (once `_bind_assignments` prefixes it at line 206). Task 2 relies on `classify_iterable` keeping its four-argument signature `(source, node, bindings, helpers)`.

- [ ] **Step 1: Write the failing fixtures**

Append to `tests/test_detect_vacuous_claims.py`:

```python
def test_empty_list_accumulator_is_a_claim() -> None:
    """The recording idiom: starts empty, stays empty when nothing happens.

    This is the shape the TypeScript half has always caught and the Python
    half never did — ``calls = []``, the code under test appends, and the
    loop asserts. When the code under test does nothing at all, the loop
    runs zero times and the test still reports success.
    """
    source = """
        def test_records():
            calls = []
            run(lambda name: calls.append(name))
            for call in calls:
                assert call.startswith("smc")
    """
    assert _kinds(source) == {"calls": "local empty literal"}


def test_nonempty_list_literal_is_not_a_claim() -> None:
    """A literal with elements cannot be empty, exactly as a tuple cannot."""
    source = """
        def test_flags():
            flags = ["--start-date", "--end-date"]
            for flag in flags:
                assert flag in TEXT
    """
    assert _kinds(source) == {}


def test_empty_dict_accumulator_is_a_claim() -> None:
    source = """
        def test_seen():
            seen = {}
            record(seen)
            for key in seen:
                assert key.isupper()
    """
    assert _kinds(source) == {"seen": "local empty literal"}


def test_zero_argument_list_constructor_is_a_claim() -> None:
    """``list()`` is ``[]`` spelled as a call and must read the same.

    ``_TRANSPARENT_CALLS`` already names ``list``/``set``, but only for the
    argument-carrying form where emptiness passes through. With no argument
    there is nothing to pass through — the result is empty by construction.
    """
    source = """
        def test_records():
            calls = list()
            run(calls.append)
            for call in calls:
                assert call
    """
    assert _kinds(source) == {"calls": "local empty literal"}


def test_a_witness_clears_an_empty_literal_accumulator() -> None:
    """The lived fix must keep working: assert the recording non-empty."""
    source = """
        def test_records():
            calls = []
            run(calls.append)
            assert calls, "nothing recorded — this pin would pass vacuously"
            for call in calls:
                assert call.startswith("smc")
    """
    assert _kinds(source) == {}
```

- [ ] **Step 2: Run the fixtures to verify they fail**

```bash
cd /Users/spreuss/Documents/skipp-algo-wt-<name>
PYTEST_ADDOPTS="-n 4" /Users/spreuss/Documents/skipp-algo/.venv/bin/python -m pytest \
  tests/test_detect_vacuous_claims.py -q -k "empty_literal or empty_list or empty_dict or zero_argument or nonempty_list"
```

Expected: 4 FAIL (`assert {} == {'calls': 'local empty literal'}` and its siblings), 1 PASS (`test_nonempty_list_literal_is_not_a_claim` — already correct, it is the regression half of the pair).

- [ ] **Step 3: Add the module constant**

In `scripts/detect_vacuous_claims.py`, directly below `_TRANSPARENT_CALLS` (line 50):

```python
#: Zero-argument constructors that produce an empty collection. Separate
#: from :data:`_TRANSPARENT_CALLS` on purpose: ``list(xs)`` passes ``xs``'s
#: emptiness through, while ``list()`` *is* the emptiness.
_EMPTY_CONSTRUCTORS: frozenset[str] = frozenset({"list", "set", "dict"})
```

- [ ] **Step 4: Teach `classify_iterable` the two shapes**

In the `ast.Call` branch, after the existing `_TRANSPARENT_CALLS` line (currently line 119-120), add the third `ast.Name` case:

```python
        if isinstance(func, ast.Name):
            if func.id in helpers:
                return helpers[func.id]
            if func.id in _TRANSPARENT_CALLS and node.args:
                return classify_iterable(source, node.args[0], bindings, helpers)
            if func.id in _EMPTY_CONSTRUCTORS and not node.args:
                return "empty literal"
        return None
```

And add a new top-level branch immediately after the comprehension branch (after line 125, before the `ast.Name` branch):

```python
    if isinstance(node, (ast.List, ast.Set, ast.Dict)):
        # An empty collection literal is the accumulator idiom's starting
        # point: ``calls = []``, something appends, a loop asserts. When the
        # code under test appends nothing, the loop runs zero times. A
        # literal *with* elements stays out for the reason the module
        # docstring gives for tuples — it cannot be empty at runtime.
        return None if _is_nonempty_literal(node) else "empty literal"
```

`_is_nonempty_literal` is defined further down the module (line 271); Python resolves it at call time, so the forward reference is fine and matches how `_render` is already used above its own definition.

- [ ] **Step 5: Run the fixtures to verify they pass**

```bash
PYTEST_ADDOPTS="-n 4" /Users/spreuss/Documents/skipp-algo/.venv/bin/python -m pytest \
  tests/test_detect_vacuous_claims.py -q
```

Expected: all PASS, including the 40+ pre-existing fixtures. If any pre-existing fixture flipped, the new branch is too broad — sharpen it, do not adjust the old fixture.

- [ ] **Step 6: Measure the repo-wide effect**

```bash
/Users/spreuss/Documents/skipp-algo/.venv/bin/python -m scripts.detect_vacuous_claims tests/ > /tmp/vac-t1.out 2>&1
tail -1 /tmp/vac-t1.out
```

Expected (measured 2026-08-04 on `fe25ad1ce`): `1626 files scanned, 20 vacuum-prone claims` — the 13 already exempted plus these 7:

| File:line | Test | Iterable |
|---|---|---|
| `tests/test_assert_and_open_encoding_pin.py:131` | `test_assert_files_exist` | `sorted(_FROZEN_ASSERT_COUNTS)` (parametrize) |
| `tests/test_assert_and_open_encoding_pin.py:223` | `test_open_files_exist` | `sorted(_FROZEN_OPEN_COUNTS)` (parametrize) |
| `tests/test_benzinga_rss_adapter.py:307` | `test_fetch_news_enforces_timeout_on_http_not_feedparser` | `"timeout" not in kw for kw in captured_parse_kwargs` |
| `tests/test_databento_production_workbook_shared.py:373` | `test_write_databento_production_workbook_from_frames_threads_progress` | `"(t+" in m for m in msgs` |
| `tests/test_databento_production_workbook_slim_whitelist.py:454` | `test_write_canonical_workbook_env_all_retains_full_sheet_set` | `"slim-whitelist active" in m for m in messages` |
| `tests/test_publish_bot_snapshot.py:54` | `test_transient_branch_fetch_failure_aborts_without_push` | `call and call[0] == "push" for call in calls` |
| `tests/test_smc_live_overlay_feed_lifecycle_thread_safety.py:185` | `test_worker_liveness_runs_under_lifecycle_lock` | `liveness_results` |

If your count is not 20, stop and reconcile before triaging — a different number means the branch behaves differently from the reference implementation above.

- [ ] **Step 7: Triage each of the 7 — fix, declare, or sharpen**

Read each site. Apply exactly one verdict per site, and record the verdict in the task report:

- **fix** — the emptiness is not intended: add the witness next to the loop, in the same block, using the idiom already lived in this repo:
  ```python
  assert msgs, "no progress messages recorded — this pin would pass vacuously"
  ```
  Note the two `assert not any(... for ... in xs)` shapes above (`test_benzinga_rss_adapter.py:307`, and the `"timeout" not in kw` form): a witness there is `assert captured_parse_kwargs, "…"`, because the claim is that the recording happened *and* carried no timeout.
- **declare** — the emptiness is intended and something else does the proving: add to `[vacuous_claim_guard.exemptions]` in `pin_registry.toml` with a dated reason that **names the test that does the proving**:
  ```toml
  "tests/test_x.py::test_y::xs" = "2026-08-04: xs is empty by construction here; tests/test_x.py::test_roster_is_not_empty proves the roster non-empty."
  ```
- **sharpen** — the detector is wrong: add a fixture to `tests/test_detect_vacuous_claims.py` **first**, then narrow the branch. Never waive a detector bug.

The two `parametrize` hits on `_FROZEN_ASSERT_COUNTS` / `_FROZEN_OPEN_COUNTS` need a look at how those module-level dicts are built. Two corrections to how this paragraph originally read, both measured on 2026-08-04 while executing the task:

- **An empty `argvalues` does not silently collect zero tests.** `empty_parameter_set_mark` is unset in this repo, so pytest's default `skip` applies and the run emits `SKIPPED … got empty parameter set` — measured, four such skips in this one file. It is an **unrun check reported as a skip**, not a silent pass. That changes the reasoning you write down, not the verdict: an unrun check still proves nothing.
- **These two are *declare*, not *sharpen*.** Both dicts are hand-maintained and provably never mutated (AST scan: no subscript assign, no `AugAssign`, no `append/add/update/extend`, no `global`) — but that makes them a population which is *permanently* empty, which is the stronger form of the condition, not a false positive. `pin_registry.toml` names exactly this as exemption shape 1, "a population that is intentionally empty today, pinned by a test that says so (the archive gate)", and already carries the structurally identical `_archived_surfaces()` entries. Narrowing the detector instead would encode the emptiness as permanent behaviour, so nothing re-audits it when the ledger fills again; a dated exemption goes stale-red through `test_every_exemption_still_matches_a_claim`.

A dict genuinely populated by a loop at import time remains a true claim and must stay detected — do not add a module-scope filter to suppress the two above. Note also that the sibling parametrize sites over `sorted(_FROZEN_*.items())` (`:122`, `:213`) carry the identical emptiness and are **invisible** to the analyzer, because `.items()` is neither a discovery attribute nor a helper. Say so in the exemption reason rather than implying the analyzer sees the whole ledger; extending `.items()` handling is out of scope here and is recorded as a follow-up.

- [ ] **Step 8: Verify the guard is green**

```bash
PYTEST_ADDOPTS="-n 4" /Users/spreuss/Documents/skipp-algo/.venv/bin/python -m pytest \
  tests/test_detect_vacuous_claims.py tests/test_vacuous_claim_guard.py -q
ruff check .
```

Expected: all PASS, `All checks passed!`. `test_every_exemption_still_matches_a_claim` is the one that catches an over-broad declare — if it goes red, an exemption you added does not match a real claim key.

- [ ] **Step 9: Commit**

```bash
git status --porcelain   # must show only the files you intended
git add scripts/detect_vacuous_claims.py tests/test_detect_vacuous_claims.py pin_registry.toml <fixed test files>
git commit -m "fix(guard): classify empty collection literals as emptiable

The TypeScript analyzer has always read \`[]\` as emptiable because the
recording-array idiom dominates that suite; the Python analyzer did not,
so \`calls = []\` + append + loop was invisible. Measured on fe25ad1ce:
7 new claims over tests/, triaged fix/declare per site.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Properties of objects the scope produced (Python)

`out = run_walk_forward(...)` then `for fold in out.folds:` is invisible today: `classify_iterable`'s `ast.Attribute` branch only resolves a dotted name that `_bind_assignments` watched being *assigned* something emptiable. This task widens that to a second, equally bounded producer — **an object this function produced by calling something** — and closes the one witness gap that widening exposes. Measured: **+30 claims**, and **1** false positive prevented by the witness rule.

The boundedness is the whole design. A module alias (`plf.SHARED_LIBRARIES`) or a global (`MANIFEST.SURFACE_DEFINITIONS`) is **not** covered, and that is not an oversight — see "Two things measured and deliberately NOT built" above: those all resolve to non-empty literals, so classifying them would be a false-positive factory.

**Files:**
- Modify: `scripts/detect_vacuous_claims.py` — new `_produced_names`, `_produced_properties`, `_subset_bindings`; `_local_bindings` (line 251), `witness_keys` (line 432), `_block_claims` (line 655), `scan_source` (line 737)
- Test: `tests/test_detect_vacuous_claims.py`
- Modify: `pin_registry.toml`, `[vacuous_claim_guard.exemptions]`
- Modify: the ~17 test files listed in Step 6

**Interfaces:**
- Consumes: `_render(source, node) -> str` (line 551, the module's **single** renderer — a witness rendered any other way silently never matches), `_walk_own(node)` (line 82, skips nested `def`/`lambda`), `_bind_assignments(source, stmts, helpers) -> dict[str, str]` (line 161), `_is_nonempty_length_check(op, right) -> bool` (line 260)
- Produces:
  - `_produced_names(func: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]`
  - `_produced_properties(source: str, func: ast.FunctionDef | ast.AsyncFunctionDef) -> dict[str, str]`
  - `_subset_bindings(source: str, func: ast.FunctionDef | ast.AsyncFunctionDef) -> dict[str, set[str]]`
  - `witness_keys(source, body, subsets=None)` — a **third, optional** parameter; the two-argument call stays valid, which matters because `witness_keys` is named in the module docstring and called from `_block_claims`
  - kind string `"property of a produced object"`

- [ ] **Step 1: Write the failing fixtures**

Append to `tests/test_detect_vacuous_claims.py`:

```python
def test_a_property_of_a_produced_object_is_a_claim() -> None:
    """The analyzer watched this object being made, so its fields are data.

    It cannot see inside ``run_walk_forward``, but it does not need to: the
    object is a runtime result, not source text, so ``out.folds`` can be
    empty and the loop can run zero times.
    """
    source = """
        def test_folds():
            out = run_walk_forward(returns)
            for fold in out.folds:
                assert fold.n_train == 80
    """
    assert _kinds(source) == {"out.folds": "property of a produced object"}


def test_a_property_of_an_imported_module_is_not_a_claim() -> None:
    """A module constant is source the analyzer never watched being produced.

    Measured 2026-08-04: every ``<module alias>.<CONST>`` iterated in
    ``tests/`` resolves to a non-empty tuple or frozenset literal, so
    classifying these would report false positives rather than defects.
    """
    source = """
        import scripts.pine_library_freshness as plf

        def test_scope():
            for name in plf.SHARED_LIBRARIES:
                assert name.startswith("skipp_")
    """
    assert _kinds(source) == {}


def test_a_produced_object_itself_is_not_a_claim() -> None:
    """Only the *properties* are classified, never the object.

    ``for row in load_rows()`` is already covered by the helper and
    discovery rules; making the bare name emptiable would classify every
    local that happens to hold a call result.
    """
    source = """
        def test_object():
            out = run_walk_forward(returns)
            for fold in out:
                assert fold.n_train == 80
    """
    assert _kinds(source) == {}


def test_a_length_witness_clears_a_produced_property() -> None:
    source = """
        def test_folds():
            out = run_walk_forward(returns)
            assert len(out.folds) == 4
            for fold in out.folds:
                assert fold.n_train == 80
    """
    assert _kinds(source) == {}


def test_a_nonempty_subset_witnesses_the_base_it_was_drawn_from() -> None:
    """A non-empty subset proves the set it came from non-empty.

    Lived at ``tests/test_smc_volume_profile.py:69-73``: the test filters
    ``profile.rows`` into ``nonzero_rows``, asserts that is non-empty, then
    loops over ``profile.rows``. Without this rule that loop reports as
    unwitnessed even though the proof is two lines above it.
    """
    source = """
        def test_rows():
            profile = compute_volume_profile(bars)
            nonzero = [row for row in profile.rows if row.total > 0.0]
            assert len(nonzero) > 1
            for row in profile.rows:
                assert row.total > 0.0
    """
    assert _kinds(source) == {}


def test_a_bare_truth_check_on_a_subset_also_witnesses_its_base() -> None:
    source = """
        def test_rows():
            profile = compute_volume_profile(bars)
            nonzero = [row for row in profile.rows if row.total > 0.0]
            assert nonzero
            for row in profile.rows:
                assert row.total > 0.0
    """
    assert _kinds(source) == {}


def test_the_subset_rule_does_not_run_backwards() -> None:
    """The inverse stays refused: a non-empty base proves nothing about a subset.

    This is the direction :func:`_witness_candidates` already rejects, and
    the subset rule must not reopen it — the filter can empty the result
    while the base is full.
    """
    source = """
        def test_rows():
            profile = compute_volume_profile(bars)
            assert len(profile.rows) > 1
            nonzero = [row for row in profile.rows if row.total > 0.0]
            for row in nonzero:
                assert row.total > 0.0
    """
    assert _kinds(source) == {"nonzero": "local filtered comprehension"}
```

- [ ] **Step 2: Run the fixtures to verify they fail**

```bash
PYTEST_ADDOPTS="-n 4" /Users/spreuss/Documents/skipp-algo/.venv/bin/python -m pytest \
  tests/test_detect_vacuous_claims.py -q -k "produced or subset"
```

Expected: `test_a_property_of_a_produced_object_is_a_claim` FAILs with `assert {} == {'out.folds': 'property of a produced object'}`; the two subset-witness tests FAIL with a claim reported where none is expected; the three negative tests already PASS (they are the regression half and must stay green through every edit below).

- [ ] **Step 3: Add the producer discovery**

In `scripts/detect_vacuous_claims.py`, directly above `_local_bindings` (line 251):

```python
def _produced_names(func: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    """Names *func* bound to the result of a call, or to a ``with`` target.

    "Produced" is the whole boundedness rule of :func:`_produced_properties`
    and is deliberately narrow. ``out = run_walk_forward(...)`` produced an
    object here, so its fields hold runtime data. ``import x as mod`` and a
    module-level constant did not, and their attributes are source text the
    analyzer never watched being built — measured 2026-08-04, every such
    iterable in ``tests/`` resolves to a non-empty literal, so treating them
    as emptiable would only manufacture false positives.

    Tuple targets are excluded on purpose: ``(a,) = obj.instances`` unpacks
    an *attribute*, not a call, and following it would need the producer of
    ``obj`` — the very thing this rule refuses to guess at.
    """
    produced: set[str] = set()
    for stmt in _walk_own(func):
        if isinstance(stmt, ast.Assign) and isinstance(stmt.value, ast.Call):
            for target in stmt.targets:
                if isinstance(target, ast.Name):
                    produced.add(target.id)
        elif isinstance(stmt, ast.AnnAssign) and isinstance(stmt.value, ast.Call):
            if isinstance(stmt.target, ast.Name):
                produced.add(stmt.target.id)
        elif isinstance(stmt, (ast.With, ast.AsyncWith)):
            for item in stmt.items:
                if isinstance(item.optional_vars, ast.Name):
                    produced.add(item.optional_vars.id)
    return produced


def _produced_properties(
    source: str, func: ast.FunctionDef | ast.AsyncFunctionDef
) -> dict[str, str]:
    """Map ``obj.attr`` (rendered) -> kind for objects *func* produced.

    Returned as *bindings* rather than as a new argument to
    :func:`classify_iterable`, so the existing ``ast.Attribute`` branch
    there resolves them with no signature change — and so a real binding
    from :func:`_bind_assignments` always wins, because the caller merges
    these in with ``setdefault``.

    Every key goes through :func:`_render`, the module's single renderer.
    Rendering a binding one way and the lookup another is the defect this
    module was corrected for once already: the two sides stop matching on
    quote style alone and nothing says so.
    """
    produced = _produced_names(func)
    properties: dict[str, str] = {}
    for node in _walk_own(func):
        if not isinstance(node, ast.Attribute):
            continue
        base: ast.expr = node
        while isinstance(base, ast.Attribute):
            base = base.value
        if isinstance(base, ast.Name) and base.id in produced:
            properties[_render(source, node)] = "property of a produced object"
    return properties


def _subset_bindings(
    source: str, func: ast.FunctionDef | ast.AsyncFunctionDef
) -> dict[str, set[str]]:
    """Map a name assigned a comprehension -> the base that comprehension iterates.

    A non-empty *subset* proves the set it was drawn from non-empty: if
    ``[row for row in profile.rows if row.total > 0]`` has an element, then
    ``profile.rows`` had one. That direction is sound, and it is the exact
    inverse of the one :func:`_witness_candidates` refuses — a non-empty
    base says nothing about a filtered comprehension over it, because the
    filter can empty the result.

    Only the first generator's iterable is recorded. With a second ``for``
    clause a non-empty result proves that *some* inner iterable was
    non-empty, not the one any particular loop iterates, so accepting the
    rest would fabricate a witness.
    """
    subsets: dict[str, set[str]] = {}
    for stmt in _walk_own(func):
        if not isinstance(stmt, ast.Assign):
            continue
        value = stmt.value
        if not isinstance(value, (ast.ListComp, ast.SetComp, ast.GeneratorExp)):
            continue
        base = _render(source, value.generators[0].iter)
        for target in stmt.targets:
            if isinstance(target, ast.Name):
                subsets.setdefault(target.id, set()).add(base)
    return subsets
```

- [ ] **Step 4: Merge the produced properties into the local bindings**

Replace `_local_bindings` (line 251-257) with:

```python
def _local_bindings(
    source: str,
    func: ast.FunctionDef | ast.AsyncFunctionDef,
    helpers: dict[str, str],
) -> dict[str, str]:
    """Map names assigned inside *func* to the kind of what they hold.

    Assignments win over produced properties: a dotted name the function was
    seen assigning something emptiable carries a more specific kind than
    "some field of an object we produced", so :func:`_bind_assignments` runs
    first and ``setdefault`` leaves it alone.
    """
    bindings = _bind_assignments(source, _walk_own(func), helpers)
    for key, kind in _produced_properties(source, func).items():
        bindings.setdefault(key, kind)
    return bindings
```

- [ ] **Step 5: Thread the subset witnesses through**

Three edits, all mechanical.

`witness_keys` (line 432) — new optional parameter, and the two places a witness is recorded also credit the subset's base:

```python
def witness_keys(
    source: str,
    body: Iterable[ast.stmt],
    subsets: dict[str, set[str]] | None = None,
) -> set[str]:
```

Inside it, in the `len(...)` branch, replace

```python
                if _is_nonempty_length_check(op, right):
                    keys.add(_render(source, left.args[0]))
                continue
```

with

```python
                if _is_nonempty_length_check(op, right):
                    keys |= _witnessed_by(source, left.args[0], subsets)
                continue
```

and replace the trailing bare-truthiness line `keys.add(_render(source, test))` with

```python
        keys |= _witnessed_by(source, test, subsets)
```

Add the shared helper directly above `witness_keys`:

```python
def _witnessed_by(
    source: str, node: ast.expr, subsets: dict[str, set[str]] | None
) -> set[str]:
    """The keys proven non-empty by a witness written about *node*.

    Always the node's own rendering. Additionally, when *node* is a name
    bound to a comprehension, the base that comprehension was drawn from —
    see :func:`_subset_bindings` for why that direction is sound and the
    other one is not.
    """
    keys = {_render(source, node)}
    if subsets and isinstance(node, ast.Name):
        keys |= subsets.get(node.id, set())
    return keys
```

`_block_claims` (line 655) — accept and forward `subsets`:

```python
def _block_claims(
    source: str,
    body: list[ast.stmt],
    inherited: set[str],
    bindings: dict[str, str],
    helpers: dict[str, str],
    *,
    witnesses_hold: bool = True,
    subsets: dict[str, set[str]] | None = None,
) -> Iterator[tuple[ast.expr, int, str]]:
```

with its first line becoming

```python
    visible = inherited | (witness_keys(source, body, subsets) if witnesses_hold else set())
```

and the recursive call gaining `subsets=subsets`:

```python
            yield from _block_claims(
                source, block, visible, bindings, helpers,
                witnesses_hold=holds, subsets=subsets,
            )
```

`scan_source` (line 737) — compute the subsets once per function and pass them:

```python
        bindings = _local_bindings(source, node, helpers)
        subsets = _subset_bindings(source, node)
        for iterated, lineno, kind in _block_claims(
            source, node.body, set(), bindings, helpers, subsets=subsets
        ):
```

- [ ] **Step 6: Run the fixtures and measure the repo-wide effect**

```bash
PYTEST_ADDOPTS="-n 4" /Users/spreuss/Documents/skipp-algo/.venv/bin/python -m pytest \
  tests/test_detect_vacuous_claims.py -q
/Users/spreuss/Documents/skipp-algo/.venv/bin/python -m scripts.detect_vacuous_claims tests/ > /tmp/vac-t2.out 2>&1
tail -1 /tmp/vac-t2.out
```

Expected: every fixture PASSes, and `1626 files scanned, 50 vacuum-prone claims` — the 20 after Task 1 plus these 30 (measured 2026-08-04 on `fe25ad1ce`):

| File:line | Test | Iterable |
|---|---|---|
| `test_check_resource_envelope.py:141` | `test_below_drift_fraction_no_advisory` | `… for d in result.drift_advisories` |
| `test_check_resource_envelope.py:148` | `test_at_warning_is_warning_not_drift` | `… for d in result.drift_advisories` |
| `test_explicit_structure_profiles.py:72` | `test_conservative_profile_filters_invalid_zones` | `… for row in result.orderblocks` |
| `test_explicit_structure_profiles.py:73` | `test_conservative_profile_filters_invalid_zones` | `… for row in result.fvg` |
| `test_fvg_label_audit.py:261` | `test_parity_block_counts_both_populations` | `… for f in audit.findings` |
| `test_fvg_label_audit.py:311` | `test_distinct_slices_do_not_flag` | `… for f in audit.findings` |
| `test_fx_probe_universe.py:211` | `test_run_probe_handles_bad_close_field` | `… for r in rep.pairs` |
| `test_per_tf_structure_artifact_wiring.py:185` | `test_contract_without_warnings_adds_nothing` | `… for w in evidence.warnings` |
| `test_post_release_product_state.py:52` | `test_full_payload_passes` | `… for c in report.checks` |
| `test_realtime_active_signal_lifecycle.py:56` | `test_level_upgrade_replaces_active` | `… for s in eng._active_signals` |
| `test_realtime_active_signal_lifecycle.py:64` | `test_direction_flip_replaces_active` | `… for s in eng._active_signals` |
| `test_realtime_active_signal_lifecycle.py:99` | `test_other_symbols_are_not_disturbed_on_replace` | `… for s in eng._active_signals` |
| `test_realtime_signals_uplift_b.py:398` | `test_technical_scorer_evicts_via_ttl_when_over_capacity` | `… for k in s._cache` |
| `test_regime_fear_greed.py:47` | `test_classify_regime_ignores_fear_greed_with_invalid_value` | `… for r in snap.reasons` |
| `test_run_ab_comparison_fdr_defense.py:53` | `test_fdr_q_constant_is_float_literal` | `module.body` |
| `test_smc_integration_measurement_evidence.py:146-149` | `test_build_measurement_evidence_uses_contract_and_real_bars` | 4 × `… for event in evidence.scored_events` |
| `test_smc_integration_structure_contract_diagnostics.py:299` | `test_exact_match_has_no_fallback_warning` | `… for w in contract.warnings` |
| `test_smc_integration_structure_contract_diagnostics.py:305` | `test_case_insensitive_match_has_no_fallback_warning` | `… for w in contract.warnings` |
| `test_smc_micro_streamlit_app_finalize.py:456` | `test_run_streamlit_micro_base_app_generate_pine_reuses_selected_session_result` | `… for message in fake_streamlit.info_messages` |
| `test_smc_qualify_dont_block.py:71` | `test_event_risk_high_reduces_strength` | `snapshot_normal.layered.zone_styles` |
| `test_sprint_inventory.py:83,108,113,118` | four tests | 4 × `… for h in result.hits` |
| `test_streamlit_terminal_session_schema_invalidation.py:54` | `test_invalidation_drops_derived_keys_on_version_change` | `sentinel_keys` |
| `test_track_record_gate.py:108` | `test_missing_optionals_are_skipped_not_red` | `verdict.checks` |
| `test_walk_forward_runner.py:140` | `test_runner_handles_evaluator_returning_none` | `out.folds` |

`tests/test_smc_volume_profile.py:73 profile.rows` must **not** appear — it is the site the subset witness clears, and its absence is the check that Step 5 landed. If it is in the list, `_subset_bindings` or the threading is wrong.

- [ ] **Step 7: Triage each of the 30 — fix, declare, or sharpen**

Same three verdicts, same rules as Task 1 Step 7. Two patterns dominate and pull in opposite directions, so read each site rather than batching:

- **Genuine defects.** `test_full_payload_passes` asserting `all(c.status is CheckStatus.PASS for c in report.checks)` proves nothing if `report.checks` is empty — that is the class, and the fix is `assert report.checks, "…"` (or a count assertion) next to it.
- **Intended emptiness.** `test_exact_match_has_no_fallback_warning` asserting `not any("legacy_tf_fallback" in w for w in contract.warnings)` is *about* the warning list being clean; an empty list is the expected state, not a blind spot. These are **declare**, with a dated reason that says so and names what proves the contract was actually built.

Do not batch-declare a whole file. One key, one decision.

- [ ] **Step 8: Verify green**

```bash
PYTEST_ADDOPTS="-n 4" /Users/spreuss/Documents/skipp-algo/.venv/bin/python -m pytest \
  tests/test_detect_vacuous_claims.py tests/test_vacuous_claim_guard.py -q
ruff check .
git status --porcelain
```

Expected: all PASS, `All checks passed!`, and no stray writes into `governance/` or `artifacts/`.

- [ ] **Step 9: Commit**

```bash
git add scripts/detect_vacuous_claims.py tests/test_detect_vacuous_claims.py pin_registry.toml <triaged files>
git commit -m "fix(guard): classify properties of objects the scope produced

An object this function made by calling something holds runtime data, so
its fields can be empty; a module constant is source the analyzer never
watched being built and stays out — measured, every such iterable in
tests/ is a non-empty literal. Adds the non-empty-subset witness, without
which one honest test (test_smc_volume_profile) would report falsely.
Measured on fe25ad1ce: 30 new claims, triaged fix/declare per site.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: The same producer rule in the TypeScript half

The TS analyzer binds dotted names only from an object-literal initialiser (`detect_vacuous_claims_ts.ts:205-217`). `const result = await runDiagnostics(...)` followed by `assert.ok(result.failures.every(...))` is invisible for the same reason the Python half was. Measured: **4 sites, 3 distinct** — including `result.failures`, which is literally the example the follow-up note named.

**Files:**
- Modify: `scripts/detect_vacuous_claims_ts.ts` — `collectBindings` (line 199) and `classify` (line 153)
- Test: `automation/tradingview/tests/vacuous_claims_ts.test.ts` (helper `kinds` at line 25; `TS_VACUITY_EXEMPTIONS` at line 23)
- Modify: `automation/tradingview/tests/tv_r5_session_diagnostics.test.ts`, `automation/tradingview/tests/tv_shared.test.ts` — only where triage says *fix*

**Interfaces:**
- Consumes: `ScopeChain<T>` with `add(container, name, value)` / `resolve(name, at)` (line 121), `containerOf(node)` (line 105), `render(node, source)` (line 78, the single renderer), `classify(node, source, bindings, at)` (line 153)
- Produces: kind string `"property of a produced object"`, resolvable through the existing `ts.isPropertyAccessExpression` branch of `classify` (line 183)

- [ ] **Step 1: Write the failing fixtures**

Append to `automation/tradingview/tests/vacuous_claims_ts.test.ts`, before the repo-wide scan tests:

```ts
test("a property of a produced object is a claim", () => {
  const source = `
    const result = runDiagnostics(page);
    assert.ok(result.failures.every((f) => f.code.startsWith("CE")));
  `;
  assert.deepEqual(kinds(source), {
    "result.failures": "property of a produced object",
  });
});

test("an awaited producer counts the same", () => {
  const source = `
    const capture = await collectConsoleLines(page);
    for (const line of capture.lines) { assert.ok(line.length > 0); }
  `;
  assert.deepEqual(kinds(source), {
    "capture.lines": "property of a produced object",
  });
});

test("a property of an imported constant is not a claim", () => {
  const source = `
    for (const name of CONFIG.targets) { assert.ok(name.length > 0); }
  `;
  assert.deepEqual(kinds(source), {});
});

test("a length witness clears a produced property", () => {
  const source = `
    const result = runDiagnostics(page);
    assert.ok(result.failures.length > 0, "no failures collected — vacuous");
    assert.ok(result.failures.every((f) => f.code.startsWith("CE")));
  `;
  assert.deepEqual(kinds(source), {});
});
```

- [ ] **Step 2: Run to verify they fail**

```bash
cd /Users/spreuss/Documents/skipp-algo-wt-<name>
npx tsx --test automation/tradingview/tests/vacuous_claims_ts.test.ts
```

Expected: the first two FAIL (`{}` vs the expected kind); the third and fourth already PASS and are the regression half.

- [ ] **Step 3: Bind produced-object properties**

In `scripts/detect_vacuous_claims_ts.ts`, inside `collectBindings`'s `visit`, after the existing object-literal block (line 205-217), add:

```ts
      // An object this scope produced by calling something holds runtime
      // data, so its fields can be empty. `CONFIG.targets` — a property of
      // something the analyzer never watched being built — deliberately
      // stays out: the Python half measured every such iterable in its own
      // suite and found them all to be non-empty literals, so classifying
      // them would manufacture false positives rather than find defects.
      const producer = ts.isAwaitExpression(node.initializer)
        ? node.initializer.expression
        : node.initializer;
      if (ts.isCallExpression(producer)) {
        for (const property of propertiesReadFrom(source, node.name.text)) {
          bindings.add(containerOf(node), property, "property of a produced object");
        }
      }
```

and add the collector above `collectBindings`:

```ts
/**
 * Dotted names in *source* whose base identifier is *name*.
 *
 * Bound like the object-literal case rather than resolved on demand,
 * because `ScopeChain` is keyed by rendered text and every key must come
 * from `render` — the single renderer. A file-wide sweep is sound here:
 * `ScopeChain.add` files the key under the *declaration's* container, so a
 * `result.failures` written in a different block still resolves only if
 * that block is nested inside the one that declared `result`.
 */
const propertiesReadFrom = (source: ts.SourceFile, name: string): string[] => {
  const found = new Set<string>();
  const visit = (node: ts.Node): void => {
    if (ts.isPropertyAccessExpression(node)) {
      let base: ts.Node = node;
      while (ts.isPropertyAccessExpression(base)) base = base.expression;
      if (ts.isIdentifier(base) && base.text === name) found.add(render(node, source));
    }
    ts.forEachChild(node, visit);
  };
  visit(source);
  return [...found];
};
```

No change to `classify` is needed: its `ts.isPropertyAccessExpression` branch (line 183) already resolves a rendered dotted name through the scope chain.

- [ ] **Step 4: Run the fixtures and the repo-wide scan**

```bash
npx tsx --test automation/tradingview/tests/vacuous_claims_ts.test.ts
```

Expected: all fixtures PASS; the repo-wide test in the same file now reports the new claim. **One** site: `tv_r5_session_diagnostics.test.ts:90 result.failures` — re-measured 2026-08-04 by applying `vacuousReceiver` rather than approximating it, and confirmed twice over (`scanDir` reports 0 claims at the fixed HEAD and exactly 1 with the pre-fix file substituted back in).

Do **not** manufacture sites to reach a higher number. The `tv_shared.test.ts` `capture.lines` occurrences that an earlier draft of this plan listed are bare `assert.ok(x.some(f))` and are correctly out of scope.

- [ ] **Step 5: Triage each site — fix, declare, or sharpen**

Same three verdicts. `TS_VACUITY_EXEMPTIONS` is currently `{}` **by measurement** — the first round found every TS claim to be a real defect a length witness healed. Keep that property if the triage allows it; a first entry there needs a dated reason that names what does the proving.

- [ ] **Step 6: Verify the whole TS suite**

```bash
npm run tv:test 2>&1 | tail -20
```

Expected: no failures. Note this launches real browsers for `tv_shared.test.ts` — budget ~25 s.

If instead you see **uniform ~210 s timeouts**, that is not a flake and not your change: it means the pinned Playwright browser is missing from this checkout. Install it and re-run; do not start diagnosing the analyzer.

- [ ] **Step 7: Commit**

```bash
git status --porcelain
git add scripts/detect_vacuous_claims_ts.ts automation/tradingview/tests/vacuous_claims_ts.test.ts <triaged files>
git commit -m "fix(guard): classify produced-object properties in the TS analyzer

Mirrors the Python rule one language over: an object this scope made by
calling something holds runtime data. Measured on fe25ad1ce: 4 sites, 3
distinct, including the result.failures case the guard handover named.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Wire the eleven browserless TypeScript tests into CI

`tv-onboarding-packages.yml` is the **only** TS runner and has no discovery. Thirteen `*.test.ts` files run nowhere. Two of them genuinely cannot (`tv_shared.test.ts`, `tv_pine_editor_close.test.ts` launch a pinned browser). The other eleven are exempt for history — `tests/test_fast_gates_silent_skip_coverage.py:876-879` says so in as many words. Measured 2026-08-04 on `fe25ad1ce`: those eleven are **103 tests, 103 pass, 0 fail, 1103 ms** (wall 1.82 s).

**Files:**
- Modify: `.github/workflows/tv-onboarding-packages.yml` — the "Test hermetic TV pins" `run:` list (line ~203) **and** the push/pull_request `paths:` filters
- Modify: `tests/test_fast_gates_silent_skip_coverage.py` — `_TS_TESTS_INTENTIONALLY_UNGATED` (line 897) and the counts comment above it (lines 864-887)

**Interfaces:**
- Consumes: `_tv_run_step_tests()` (line 922) parses every `tsx --test` line by regex; `_tv_paths_filter_tests()` (line 933) parses the `paths:` entries; `test_gated_ts_tests_trigger_their_own_workflow` (line 983) requires a wired test to also appear in `paths:`
- Produces: `_TS_TESTS_INTENTIONALLY_UNGATED` reduced from 13 members to 2

- [ ] **Step 1: Re-measure the eleven before changing anything**

Do not take the plan's number on faith — it is the whole justification for this task.

```bash
cd /Users/spreuss/Documents/skipp-algo-wt-<name>
time npx tsx --test \
  automation/tradingview/tests/tv_auth_probe_precedence.test.ts \
  automation/tradingview/tests/tv_binding_repair.test.ts \
  automation/tradingview/tests/tv_launch_options.test.ts \
  automation/tradingview/tests/tv_preflight_identity_assertion.test.ts \
  automation/tradingview/tests/tv_producer_refresh_layouts.test.ts \
  automation/tradingview/tests/tv_publish_draw_library.test.ts \
  automation/tradingview/tests/tv_publish_micro_library.test.ts \
  automation/tradingview/tests/tv_publish_openprep_panel.test.ts \
  automation/tradingview/tests/tv_publish_overlay_library.test.ts \
  automation/tradingview/tests/tv_read_editor_content.test.ts \
  automation/tradingview/tests/tv_save_consumer_source.test.ts 2>&1 | tail -12
```

Expected: `pass 103`, `fail 0`, `duration_ms` around 1100. Record the actual numbers — they go into the workflow comment in Step 3. If any fails, stop: wiring a red test into CI is not this task's job, and the failure is the finding.

- [ ] **Step 2: Confirm none of them launches a browser**

```bash
grep -l "launchTradingViewChromium\|chromium.launch" \
  automation/tradingview/tests/tv_auth_probe_precedence.test.ts \
  automation/tradingview/tests/tv_binding_repair.test.ts \
  automation/tradingview/tests/tv_launch_options.test.ts \
  automation/tradingview/tests/tv_preflight_identity_assertion.test.ts \
  automation/tradingview/tests/tv_producer_refresh_layouts.test.ts \
  automation/tradingview/tests/tv_publish_draw_library.test.ts \
  automation/tradingview/tests/tv_publish_micro_library.test.ts \
  automation/tradingview/tests/tv_publish_openprep_panel.test.ts \
  automation/tradingview/tests/tv_publish_overlay_library.test.ts \
  automation/tradingview/tests/tv_read_editor_content.test.ts \
  automation/tradingview/tests/tv_save_consumer_source.test.ts
```

Expected: no output. A hit means that file belongs in the exempt set with a technical reason, not in the run step — drop it from the list and say so in the report. (`tv_launch_options.test.ts` mentions `playwright` 15 times but only as a *type/value import*, which the existing comment at line 864-871 already establishes does not force exemption; the runtime launch is what does.)

- [ ] **Step 3: Add the eleven to the run step**

In `.github/workflows/tv-onboarding-packages.yml`, append the eleven paths to the existing `npx tsx --test …` line of the "Test hermetic TV pins" step, and update that step's comment with the measured numbers from Step 1:

```yaml
      - name: Test hermetic TV pins
        # Mostly source-scan / pure-logic pins. Two named exceptions:
        # tv_chart_error_probe.test.ts launches a real headless Chromium per
        # test (measured 2026-08-03: 931ms / 196ms / 202ms), and the eleven
        # added 2026-08-04 were exempt for history rather than for any
        # technical obstacle — measured together at 103 tests / 0 fail /
        # 1103ms, verified to launch no browser.
```

- [ ] **Step 4: Add the eleven to the `paths:` filters**

`test_gated_ts_tests_trigger_their_own_workflow` requires every wired test to appear under the push **and** pull_request `paths:` filters, so a change to the test triggers the run that guards it. Add all eleven to both.

- [ ] **Step 5: Shrink the exempt set**

In `tests/test_fast_gates_silent_skip_coverage.py`, replace `_TS_TESTS_INTENTIONALLY_UNGATED` (line 897) with the two that remain, and rewrite the comment block above it so it states the new counts rather than the old:

```python
#: TS tests that do not run in tv-onboarding-packages.yml. Both need a pinned
#: browser at RUNTIME — tv_shared.test.ts (25 launchTradingViewChromium call
#: sites; 133 tests, 21.5s locally) and tv_pine_editor_close.test.ts (4 sites,
#: 2.6s). The eleven that were exempt for history were wired in on 2026-08-04
#: after measuring them at 103 tests / 0 fail / 1103ms with no browser launch.
#: Adding a member is a deliberate edit (audit trail); reducing it means a
#: browserless test was wired into CI.
_TS_TESTS_INTENTIONALLY_UNGATED: frozenset[str] = frozenset(
    {
        "tv_pine_editor_close.test.ts",
        "tv_shared.test.ts",
    }
)
```

Also update the re-derived counts line (currently line 886-887) to `55 *.test.ts total = 53 run (1 + 1 + 51 across the three npx tsx --test steps) + 2 exempt`, **after** confirming the arithmetic against the file rather than copying it.

- [ ] **Step 6: Verify**

```bash
PYTEST_ADDOPTS="-n 4" /Users/spreuss/Documents/skipp-algo/.venv/bin/python -m pytest \
  tests/ -k workflow -q
ruff check .
```

**Run the whole `-k workflow` selection, not just `test_fast_gates_silent_skip_coverage.py`.** The diff-driven guard selection only runs what the changed files map to, and a workflow edit has repeatedly turned out to break a *different* workflow-reading test than the obvious one (`tv_consumer_source_drift`, #4296). The narrow run would have been green.

Expected: all PASS. `test_every_ts_test_is_gated_or_exempt`, `test_exempt_ts_tests_still_exist` and `test_gated_ts_tests_trigger_their_own_workflow` are the three that will catch a half-done wiring — a test added to the run step but not to `paths:` fails the third. A `StarletteDeprecationWarning` in this run is a foreign dependency, not this branch; Task 5 owns it.

- [ ] **Step 7: Commit**

```bash
git status --porcelain
git add .github/workflows/tv-onboarding-packages.yml tests/test_fast_gates_silent_skip_coverage.py
git commit -m "ci(tv): wire the eleven browserless TS tests into the hermetic step

They were exempt for history, not for a technical obstacle — the file's own
comment said so since 2026-08-03. Measured 2026-08-04: 103 tests, 0 fail,
1103ms, no browser launch. Exempt set drops from 13 to the 2 that really
need a pinned browser.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: Pin `starlette`, decide `httpx2`

`StarletteDeprecationWarning: Using httpx with starlette.testclient is deprecated; install httpx2 instead` appears in every `-k workflow` run. Investigating it surfaced the larger finding: **`starlette` is pinned nowhere in `requirements.txt`** and has floated to `1.3.1` — a major version — as a transitive dependency of `fastapi`. The unpinned major is the real risk; the warning is its symptom.

**Files:**
- Modify: `requirements.txt` (currently `httpx==0.28.1` at line 3, `fastapi==0.136.1` at line 19)

**Interfaces:**
- Consumes: nothing from earlier tasks — this task is independent and can land in any order
- Produces: nothing later tasks rely on

- [ ] **Step 1: Record the current state**

```bash
/Users/spreuss/Documents/skipp-algo/.venv/bin/python -c "
import importlib.metadata as md
for p in ('fastapi', 'starlette', 'httpx', 'anyio'):
    try: print(p, md.version(p))
    except Exception: print(p, 'ABSENT')
"
grep -n "^fastapi\|^starlette\|^httpx" requirements.txt
```

Expected (measured 2026-08-04): `fastapi 0.136.3`, `starlette 1.3.1`, `httpx 0.28.1`, and no `starlette` line in `requirements.txt`. Note the venv also drifts from the pin (`fastapi` 0.136.3 installed vs `==0.136.1` pinned) — that is a **local environment** fact, not a repo defect, and belongs in the report rather than in this diff.

- [ ] **Step 2: Pin `starlette` to what is already in use**

Add to `requirements.txt`, adjacent to the `fastapi` line so the pair reads together:

```
starlette==1.3.1  # 2026-08-04: pinned at the version already in use. It was
                  # unpinned and reached 1.x transitively via fastapi; an
                  # unpinned major on the ASGI layer is the actual risk here,
                  # the TestClient deprecation warning is only its symptom.
```

This is a no-op for behaviour by construction — it pins the version already installed and already exercised by CI.

- [ ] **Step 3: Test whether `httpx2` silences the warning without changing behaviour**

Do this in a **throwaway** venv. Do not mutate the repo venv.

```bash
/Users/spreuss/Documents/skipp-algo/.venv/bin/python -m venv /tmp/httpx2-probe
/tmp/httpx2-probe/bin/pip install -q -r requirements.txt httpx2==2.9.1
/tmp/httpx2-probe/bin/python -m pytest -W error -q \
  tests/test_smc_live_overlay_endpoint.py \
  tests/test_hold_manager_shadow_receiver.py \
  tests/test_smc_live_overlay_metrics_basic_auth.py \
  tests/test_smc_live_overlay_metrics_endpoint.py \
  tests/test_live_overlay_stale_flag_data_freshness.py \
  tests/test_grafana_composio_fanout.py \
  tests/test_smc_live_cache_miss_context.py 2>&1 | tail -15
```

These are the seven files that import `TestClient` (verified 2026-08-04).

- [ ] **Step 4: Decide from the measurement, and say which branch you took**

- **All seven green and the warning gone** → add `httpx2==2.9.1` to `requirements.txt` with a dated comment saying it exists for `starlette.testclient` and that `httpx` stays for outbound calls, then re-run the seven in the repo venv after installing it there too.
- **Anything fails, or the warning persists** → do **not** add `httpx2`. Leave `httpx` in place and record the decision as a dated comment next to the `httpx` pin:
  ```
  httpx==0.28.1  # 2026-08-04: starlette 1.3.1's TestClient warns and asks for
                 # httpx2. Measured: <what failed>. Staying on httpx until that
                 # is resolved; the warning is accepted, not unseen.
  ```
  A recorded decision is the deliverable either way. An unexplained warning is not.

- [ ] **Step 5: Verify and commit**

```bash
PYTEST_ADDOPTS="-n 4" /Users/spreuss/Documents/skipp-algo/.venv/bin/python -m pytest -q \
  tests/test_smc_live_overlay_endpoint.py tests/test_hold_manager_shadow_receiver.py \
  tests/test_smc_live_overlay_metrics_basic_auth.py tests/test_smc_live_overlay_metrics_endpoint.py \
  tests/test_live_overlay_stale_flag_data_freshness.py tests/test_grafana_composio_fanout.py \
  tests/test_smc_live_cache_miss_context.py
ruff check .
rm -rf /tmp/httpx2-probe
git status --porcelain
git add requirements.txt
git commit -m "chore(deps): pin starlette, record the httpx2 decision

starlette was pinned nowhere and had floated to 1.3.1 transitively via
fastapi — an unpinned major on the ASGI layer. Pinned at the version
already in use, so behaviour is unchanged. The TestClient deprecation
warning is <resolved by httpx2 | accepted with a dated reason>.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## PR split

Five tasks, but **not** five PRs. The first vacuity round cost a day by leaving merge order as prose in a PR body instead of as a mechanism — #4352/#4353 merged into #4351's branch and silently loaded it with a live behaviour change. Two rules follow from that, both non-negotiable:

- **Stacked PRs MUST be drafts.** A draft is a mechanism; a sentence is a request.
- The repo has `delete_branch_on_merge=true`. After a merge the feature branch is gone remotely and must be re-pushed from the local clone if it is still needed. A squash-merge also breaks any branch stacked on it — repair with `git rebase --onto origin/main <old-base>`, never by force-pushing an unrebased branch.

Proposed split:

| PR | Tasks | Base | State |
|---|---|---|---|
| A | 1 + 2 | `main` | ready |
| B | 3 | A's branch | **draft** until A merges |
| C | 4 + 5 | `main` | ready — independent of A/B, touches no analyzer |

Tasks 4 and 5 share no file with 1-3 and can go in parallel. Confirm this split with the user before opening anything; do not merge without an explicit signal.

## Self-Review

**1. Spec coverage.** The four recorded follow-ups map as: property-access producers → Tasks 2 and 3 (with the module-constant branch measured to zero yield and explicitly not built); Python not classifying `[]` → Task 1; the eleven TS tests exempt for history → Task 4; the `StarletteDeprecationWarning` httpx→httpx2 decision → Task 5. No follow-up is unaddressed.

**2. Placeholder scan.** Every code step carries the actual code. The two places that legitimately cannot be pre-written are the per-site triage verdicts in Tasks 1, 2 and 3 — those are judgement calls with a stated three-way rule, a worked example of each direction, and a named site to apply them to, which is what the first round used successfully. Task 5 Step 4 is a two-branch decision with the measurement that selects the branch, not an open question.

**3. Type consistency.** `classify_iterable(source, node, bindings, helpers)` keeps its four-argument signature across Tasks 1 and 2 — Task 2 reaches it through `bindings`, which is why no caller changes. `witness_keys` gains a third **optional** parameter, so the existing two-argument call in any not-yet-updated caller stays valid. `_render` is the single renderer on both sides; every key produced by `_produced_properties`, `_subset_bindings` and `propertiesReadFrom` goes through it, which is the invariant the first round had to be corrected for. Kind strings are `"empty literal"` (Task 1) and `"property of a produced object"` (Tasks 2 and 3, identical in both languages), each prefixed with `"local "` by the existing binding code where applicable.

---

## Corrections found while executing this plan (2026-08-04)

Every one of these was found by an implementer or reviewer measuring something this document asserted. They are recorded here because the previous round of this work proved that a plan containing reference code gets transcribed, and a plan containing a number gets trusted. **Nine defects, all in text or code written by the plan's author.**

### Defects in the plan's reference code

1. **`_EMPTY_CONSTRUCTORS` ignored keyword arguments.** Task 1's Step 4 snippet tested `not node.args` only, so `dict(a=1)` and `dict(**other)` classified as `"empty literal"`. Over-reporting, so the safe direction — but it burns a triage cycle on a provably non-empty dict. Fix: `and not node.args and not node.keywords`.

2. **Task 2's Step 4 merge order was wrong.** The plan said compute `_bind_assignments` first and merge produced properties in with `setdefault`. Bindings *derived from* a produced property then never form, because `_bind_assignments` classifies each assignment against the dict it is still building. Measured symptom: **44 claims instead of 45**, with exactly one row of this plan's own Step 6 table missing. Seeding before the walk reproduces the table exactly — which also proves the table's measurement came from a correct implementation and only the transcribed code was wrong.

3. **`_subset_bindings` must reject `ast.GeneratorExp`.** A generator object is always truthy, so `assert gen` over a comprehension-derived name would have fabricated a witness for its base. List and set comprehensions are fine.

4. **`_subset_bindings` was flow-insensitive.** The plan's `dict[str, set[str]]` design unions *every* comprehension ever assigned to a name. Three shapes then fabricate a witness. **The plan author's prescribed fix — per-target last-write-wins plus `pop` on a non-comprehension rebind — was itself measured to still fabricate**, and was order-sensitive in `if`/`else`. The implemented rule is: **a name bound more than once anywhere in the function is dropped entirely.** Eight binding forms are counted (assign/annassign/augassign/for/walrus, `with … as`, parameters incl. `*args`/`**kwargs`, `except … as`, `import … as`, `match` captures); comprehension targets deliberately are not, because a comprehension has its own scope.

### Defects in the plan's stated facts

5. **An empty `argvalues` does not silently collect zero tests.** `empty_parameter_set_mark` is unset in this repo, so pytest's default `skip` applies and the run emits `SKIPPED … got empty parameter set` — four such skips in `tests/test_assert_and_open_encoding_pin.py` alone. It is an **unrun check reported as a skip**. The verdict is unchanged; the reasoning written into exemptions is not.

6. **The TypeScript site count was 1, not "4 sites, 3 distinct".** The three `tv_shared.test.ts` `capture.lines` occurrences are bare `assert.ok(x.some(f))`, excluded by documented design because `[].some(f)` is `false` and fails loudly. The measurement script behind that row **approximated `vacuousReceiver` instead of applying it**.

7. **The `starlette` finding was mis-stated.** The plan said "pinned nowhere" and called the pin "a no-op for behaviour by construction". In fact `requirements.lock` — which the heavy `ci.yml` lane installs — pinned **1.0.0** while the *required* `fast-gates` lane and the production daemon image resolved to **1.3.1**. The defect was four install paths disagreeing. Pinning to 1.3.1 is a no-op for three of them and lifts the fourth off a stale version missing three upstream security fixes; pinning *back* to 1.0.0 would have been the unsafe choice.

### Defects in the plan's own verification steps — the plan's own vacuity

Three separate instructions in this document would have reported success without observing what they claimed to check. That is the exact class this plan exists to close, one layer up, and it is the most useful thing the execution produced.

8. **`pytest tests/ -k workflow` does not select the three TS-wiring guards.** `-k` filters by name substring and only one of the three test names contains "workflow"; the other two would have been silently deselected. (They are covered anyway, because `smc-fast-pr-gates.yml` runs the whole file with no `-k` — but not because of this instruction.)

9. **`-W error::DeprecationWarning` cannot catch `StarletteDeprecationWarning`.** That class subclasses `UserWarning`, verified via `__mro__`. The command as written would have "validated" the `httpx2` branch regardless of the outcome. `-W error` is the working form.

### Decisions taken during execution

- **`httpx2` was not adopted.** It is the only real behaviour change the dependency work could have carried — `starlette.testclient` does `import httpx2 as httpx`, swapping the whole HTTP implementation for every `TestClient` request. The warning it silences fires in no *required* lane and cannot fail any lane (there is no `filterwarnings = error`). Three packages and a transport swap are not worth silencing it. Recorded as a dated comment beside the `httpx` pin.
- **`starlette` was also pinned on the production path** (`services/live_overlay_daemon/requirements.txt`), which the plan did not name and where the stated risk was actually live.
- **The `push.paths` / `pull_request.paths` guard split** was fixed, and immediately exposed **12 pre-existing tests wired into `push.paths` only** — they ran, but a PR touching only one of them never triggered the workflow that guards it.

### Known limitation, deliberately deferred

In **both** analyzers a witness can be credited to a different object than the one asserted over, via block shadowing (TypeScript only) or via plain reassignment (both languages). Pre-existing, uniform across every rule, reaching no live site in either suite today, and documented in the TypeScript module docstring. Fixing it needs a shadow/generation barrier in shared code, and crediting fewer witnesses risks false positives on the legitimate outer-witness / inner-use pattern — so it wants its own change with its own fixtures, not a fold-in.
