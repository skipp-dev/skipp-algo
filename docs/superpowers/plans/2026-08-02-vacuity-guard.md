# Vacuity Guard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a repo-wide guard (Python + TypeScript) that fails CI when an assertion runs over an iterable that can be empty at runtime and nothing proves the iterable was non-empty — the "passes green without observing anything" bug class.

**Architecture:** A standalone AST analyzer (`scripts/detect_vacuous_claims.py`) classifies iterated expressions as *emptiable* (discovery calls, filtered comprehensions, names/helpers bound to either) and looks for a **witness per iterable** in the same scope. A pytest guard (`tests/test_vacuous_claim_guard.py`) turns the analyzer output into a merge-blocking check with a dated-exemption registry in `pin_registry.toml`. A second, structurally identical pass covers `@pytest.mark.parametrize` argvalues. A hermetic TypeScript analyzer covers `automation/tradingview/tests/`. The guard carries its own non-vacuity witness, because `assert undeclared == []` over an empty list is exactly the shape it forbids.

**Tech Stack:** Python 3.12 (`ast`, `tomllib`, pytest), TypeScript 5.9.2 (`typescript` compiler API, already a devDependency), `node:test` via `npx tsx --test`, GitHub Actions.

## Global Constraints

Every task's requirements implicitly include this section. Values copied verbatim from the handover spec (§7, §9.2, §9.6).

- **Never merge without an explicit signal from the user.** Opening a PR is fine; merging is not.
- Work in a **sibling worktree off `origin/main`**: `/Users/spreuss/Documents/skipp-algo-wt-vacuity`. **Never** nested, **never** under `.claude/worktrees/` — otherwise the budget guards produce false positives.
- Before creating the branch: `git fetch` **and** `gh pr list`. A fast parallel bug-hunt runs on the same account; `origin/main` moves several times a day.
- Use the repo venv: `/Users/spreuss/Documents/skipp-algo/.venv/bin/python` (3.12). **Never** the system 3.9.
- Ledger/guard pytest runs **only** with `PYTEST_XDIST_AUTO_NUM_WORKERS=4` (hook-enforced; `-n auto` gets SIGKILLed with rc=137 on the 16 GB Mac). Run `ruff check .` **separately** — the ledger guard does not cover it.
- `git push` **always** with `run_in_background=true` (a foreground timeout orphans the pre-push hook).
- **Never `--no-verify`.**
- Net-zero edits near line-pinned `.py` files; before editing, check whether pins sit below the change.
- `fast-gates` is the **only** required check (ADR-0011) — a green PR can still turn `main` red. Any workflow edit therefore additionally requires `pytest tests/ -k workflow` (≈2100 tests, ≈4 min).
- **cwd trap:** the shell occasionally jumps back to `/Users/spreuss`. The `bash-cwd-context.sh` hook reports this after every Bash call — **read it**. Use absolute paths.
- Two hooks block Bash commands that merely *mention* certain script names (e.g. `run_ledger_drift_guard.sh` inside a `cat`/`sed` command is enough). Workaround: use the Read tool on the file directly.
- Every commit message ends with the trailer `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>`.
- Never parse `pin_registry.toml` outside `tests/_pin_registry.py` (ADR-0009) — add an accessor per slice.
- Two throwaway AST probes existed while this plan was written and were deliberately **not** committed — they were references, not source, and their logic was rebuilt TDD-style rather than copied. Their measured baseline (29 loop hits in 17 files, 9 parametrize hits in 8 files) came from prototypes with known false positives; it was a starting point for triage, never a claim about this analyzer's output. The figures the shipped analyzer actually measured are in the execution notes at the end of this file.

## File Structure

| File | Responsibility |
|---|---|
| `scripts/detect_vacuous_claims.py` (create) | Analyzer + CLI. Emptiability classification, witness detection, loop and parametrize vectors, `ScanResult`. |
| `tests/test_detect_vacuous_claims.py` (create) | Unit tests for the analyzer, driven by inline source fixtures (hermetic, no repo scan). |
| `tests/test_vacuous_claim_guard.py` (create) | The merge-blocking guard: scans `tests/`, subtracts exemptions, carries its own non-vacuity witness, flags stale exemptions. |
| `tests/_pin_registry.py` (modify) | New accessor `vacuous_claim_exemptions()`. |
| `pin_registry.toml` (modify) | New table `[vacuous_claim_guard.exemptions]`. |
| `.github/workflows/smc-fast-pr-gates.yml` (modify) | Add both new test files to the "Run pin / ledger drift guard" step file list. |
| `tests/test_fast_gates_silent_skip_coverage.py` (modify) | Add both files to `FULL_REQUIRED_PATH_TRIPWIRES` (the roster check is bidirectional). |
| `tests/_fast_inventory.py` (modify) | Add both files to `FAST_TEST_FILES` (ADR-0012 partition lock-step). |
| `scripts/detect_vacuous_claims_ts.ts` (create) | TypeScript analyzer over `automation/tradingview/tests/`, using the `typescript` compiler API. |
| `automation/tradingview/tests/vacuous_claims_ts.test.ts` (create) | Hermetic (playwright-free) guard for the TS analyzer, with its own dated-exemption map. |
| `.github/workflows/tv-onboarding-packages.yml` (modify) | Register the TS test in the "Test hermetic TV pins" run step **and** in both `paths:` blocks. |
| `automation/tradingview/lib/tv_shared.ts` (modify, **separate PR**) | `assertNoVisibleChartScriptError` gates on the probe, fail-closed on `CHART_ERROR_PROBE_UNREADABLE`. |

**PR split:** Tasks 1–5 are one PR (Python). Task 6 is a second PR (TypeScript guard). Task 7 is a third PR and **must be presented to the user before it is written** — it changes behaviour on the live operator publish path.

---

### Task 1: Analyzer core — which iterables can be empty

**Files:**
- Create: `scripts/detect_vacuous_claims.py`
- Test: `tests/test_detect_vacuous_claims.py`

**Interfaces:**
- Consumes: nothing (first task).
- Produces:
  - `ROOT: Path` — repo root.
  - `DISCOVERY_ATTRS: frozenset[str]`.
  - `@dataclass(frozen=True) class VacuousClaim` with fields `path: str`, `lineno: int`, `test: str`, `iterable: str`, `kind: str` and property `key -> str` (`"path::test::iterable"`).
  - `@dataclass(frozen=True) class ScanResult` with fields `files: tuple[str, ...]`, `claims: tuple[VacuousClaim, ...]`.
  - `classify_iterable(node: ast.expr, bindings: dict[str, str], helpers: dict[str, str]) -> str | None`.
  - `scan_source(source: str, path: str) -> list[VacuousClaim]`.
  - `scan_paths(paths: Iterable[Path]) -> ScanResult`.
  - `main(argv: list[str] | None = None) -> int`.
- Later tasks rely on: Task 2 changes `scan_source` to filter witnessed loops; Task 3 adds `parametrize` claims to the same `scan_source`; Task 4 calls `scan_paths`.

**Context for the implementer:** the bug class is *not* "an edge is missing" (that was a separate sweep). It is "the set is empty, the loop runs zero times, the assertion never fires". A loop over `("--start-date", "--end-date")` or `range(2)` can never be empty and must **not** be flagged. A loop over `path.glob(...)` or over `[x for x in items if cond]` can be, and must be.

- [ ] **Step 1: Create the worktree**

```bash
cd /Users/spreuss/Documents/skipp-algo
git fetch origin
gh pr list --limit 30
git worktree add /Users/spreuss/Documents/skipp-algo-wt-vacuity -b bot/vacuity-guard origin/main
```

Read the `gh pr list` output before continuing: if an open PR already touches `scripts/detect_vacuous_claims.py`, `tests/_fast_inventory.py` or `smc-fast-pr-gates.yml`, stop and report it — the parallel work has priority.

- [ ] **Step 2: Write the failing test**

Create `/Users/spreuss/Documents/skipp-algo-wt-vacuity/tests/test_detect_vacuous_claims.py`:

```python
"""Unit tests for the vacuity analyzer.

Fixtures are inline source strings, not repo files: the analyzer's contract
is about *shapes*, and pinning it to real files would make every unrelated
edit in the repo a failure here. The repo-wide scan lives in
``tests/test_vacuous_claim_guard.py``.
"""

from __future__ import annotations

import textwrap

from scripts.detect_vacuous_claims import scan_source


def _kinds(source: str) -> dict[str, str]:
    """Return ``iterable-source -> kind`` for every claim in *source*."""
    claims = scan_source(textwrap.dedent(source), "tests/example.py")
    return {claim.iterable: claim.kind for claim in claims}


def test_literal_tuple_loop_is_not_a_claim() -> None:
    """A literal cannot be empty at runtime, so it cannot be vacuous."""
    source = """
        def test_flags():
            for flag in ("--start-date", "--end-date"):
                assert flag in TEXT
    """
    assert _kinds(source) == {}


def test_range_loop_is_not_a_claim() -> None:
    source = """
        def test_repeats():
            for i in range(2):
                assert compute(i) == i
    """
    assert _kinds(source) == {}


def test_discovery_call_is_a_claim() -> None:
    source = """
        def test_every_file():
            for path in ROOT.glob("*.py"):
                assert path.is_file()
    """
    assert _kinds(source) == {'ROOT.glob("*.py")': "discovery call"}


def test_filtered_comprehension_bound_locally_is_a_claim() -> None:
    """The shape of the archive gate: a filter can filter everything away."""
    source = """
        def test_archived():
            archived = [s for s in SURFACES if s.lifecycle == "archived"]
            for surface in archived:
                assert not (ROOT / surface.file).is_file()
    """
    assert _kinds(source) == {"archived": "local filtered comprehension"}


def test_helper_returning_a_filtered_set_is_a_claim() -> None:
    source = """
        def _archived_surfaces():
            return [s for s in SURFACES if s.lifecycle == "archived"]

        def test_archived():
            for surface in _archived_surfaces():
                assert not (ROOT / surface.file).is_file()
    """
    assert _kinds(source) == {
        "_archived_surfaces()": "helper returns filtered comprehension"
    }


def test_helper_yielding_from_discovery_is_a_claim() -> None:
    """``_iter_workflow_files()`` shape: a generator over a glob."""
    source = """
        def _iter_workflow_files():
            for path in (ROOT / ".github" / "workflows").glob("*.yml"):
                yield path

        def test_workflows():
            for path in _iter_workflow_files():
                assert path.read_text()
    """
    assert _kinds(source) == {
        "_iter_workflow_files()": "helper yields discovery call"
    }


def test_method_call_on_self_resolves_to_the_helper() -> None:
    """``self._spec_paths()`` must classify like the bare helper name."""
    source = """
        class TestSpecs:
            def _spec_paths(self):
                return list(SPEC_DIR.glob("*.json"))

            def test_specs(self):
                for path in self._spec_paths():
                    assert path.suffix == ".json"
    """
    assert _kinds(source) == {
        "self._spec_paths()": "helper returns discovery call"
    }


def test_loop_without_an_assert_is_not_a_claim() -> None:
    """The guard rates assertions, not iteration."""
    source = """
        def test_collects():
            names = [p.name for p in ROOT.glob("*.py") if p.name]
            for name in names:
                print(name)
            assert names
    """
    assert _kinds(source) == {}


def test_assert_all_over_a_filtered_genexp_is_a_claim() -> None:
    """``all()`` over an empty iterable is True — the same failure, no loop."""
    source = """
        def test_all_typed():
            assert all(line.startswith("export") for line in LINES if line.strip())
    """
    assert _kinds(source) == {
        'line.startswith("export") for line in LINES if line.strip()':
            "filtered comprehension",
    }


def test_assert_not_any_over_a_filtered_genexp_is_a_claim() -> None:
    """``not any()`` over an empty iterable is True as well."""
    source = """
        def test_no_bools():
            assert not any("True" in line for line in LINES if "bool" in line)
    """
    assert _kinds(source) == {
        '"True" in line for line in LINES if "bool" in line':
            "filtered comprehension",
    }


def test_assert_any_alone_is_not_a_claim() -> None:
    """``any()`` over an empty iterable is False — it fails loudly, not silently."""
    source = """
        def test_some_match():
            assert any(line.startswith("export") for line in LINES if line.strip())
    """
    assert _kinds(source) == {}
```

- [ ] **Step 3: Run the test to verify it fails**

```bash
cd /Users/spreuss/Documents/skipp-algo-wt-vacuity
PYTHONPATH=. /Users/spreuss/Documents/skipp-algo/.venv/bin/python -m pytest tests/test_detect_vacuous_claims.py -v
```

Expected: collection error — `ModuleNotFoundError: No module named 'scripts.detect_vacuous_claims'`.

- [ ] **Step 4: Write the analyzer**

Create `/Users/spreuss/Documents/skipp-algo-wt-vacuity/scripts/detect_vacuous_claims.py`. The docstring style follows `scripts/select_workflow_guards.py`: measure first, then assert; close the class, not the instance.

```python
"""Find assertions that can pass without having observed anything.

A check that reports green while its loop ran zero times is not a passing
check — it is an unobserved one. The repo already knows the failure mode:
34 places in ``tests/`` say "would pass vacuously" in prose, and at least
one pair of neighbouring tests shows someone healing one instance by hand
and leaving the identical one directly above it alone. What is missing is
not the insight and not the idiom, but the enforcement.

The analyzer rates a *claim*, not a test: a test can prove three things
honestly and carry one vacuum-prone assertion at the same time.

A claim is vacuum-prone when

1. an assertion is carried by an iteration (a ``for`` body containing an
   ``assert``, an ``assert all(...)``, or an ``assert not any(...)``), and
2. the iterated expression can be empty at runtime (see
   :func:`classify_iterable`), and
3. nothing in the same scope proves *that* expression non-empty
   (see :func:`witness_keys`).

Literals are deliberately out of scope: ``for flag in ("--a", "--b")`` and
``for i in range(3)`` cannot be empty, and treating them as suspects is what
made the throwaway prototype report 922 hits instead of a reviewable set.

CLI::

    python -m scripts.detect_vacuous_claims tests/
"""

from __future__ import annotations

import argparse
import ast
import sys
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

#: Calls that discover things at runtime. Each can legitimately find nothing.
DISCOVERY_ATTRS: frozenset[str] = frozenset(
    {"glob", "rglob", "iterdir", "finditer", "findall", "scandir"}
)

#: Wrappers that pass emptiness straight through.
_TRANSPARENT_CALLS: frozenset[str] = frozenset(
    {"sorted", "list", "set", "tuple", "frozenset", "reversed"}
)


@dataclass(frozen=True)
class VacuousClaim:
    """One assertion that can pass without observing anything."""

    path: str
    lineno: int
    test: str
    iterable: str
    kind: str

    @property
    def key(self) -> str:
        """Stable identity used by the exemption registry."""
        return f"{self.path}::{self.test}::{self.iterable}"


@dataclass(frozen=True)
class ScanResult:
    """What a scan looked at, next to what it found.

    ``files`` exists so callers can prove the scan observed something. A
    guard that asserts on ``claims`` alone has the very shape this module
    exists to forbid.
    """

    files: tuple[str, ...]
    claims: tuple[VacuousClaim, ...]


def _walk_own(node: ast.AST) -> Iterator[ast.AST]:
    """Walk *node* without descending into nested function definitions.

    Scope matters: an assertion inside a nested helper belongs to that
    helper, not to the test that defines it.
    """
    for child in ast.iter_child_nodes(node):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            continue
        yield child
        yield from _walk_own(child)


def classify_iterable(
    node: ast.expr,
    bindings: dict[str, str],
    helpers: dict[str, str],
) -> str | None:
    """Return a kind string when *node* can be empty at runtime, else ``None``.

    ``bindings`` maps local names to kinds, ``helpers`` maps function names
    to kinds; both are resolved by the caller so this stays a pure function.
    """
    if isinstance(node, ast.Call):
        func = node.func
        if isinstance(func, ast.Attribute):
            if func.attr in DISCOVERY_ATTRS:
                return "discovery call"
            if func.attr in helpers:
                return helpers[func.attr]
        if isinstance(func, ast.Name):
            if func.id in helpers:
                return helpers[func.id]
            if func.id in _TRANSPARENT_CALLS and node.args:
                return classify_iterable(node.args[0], bindings, helpers)
        return None
    if isinstance(node, (ast.ListComp, ast.SetComp, ast.GeneratorExp)):
        if any(generator.ifs for generator in node.generators):
            return "filtered comprehension"
        return classify_iterable(node.generators[0].iter, bindings, helpers)
    if isinstance(node, ast.Name):
        return bindings.get(node.id)
    if isinstance(node, ast.Attribute):
        return bindings.get(ast.unparse(node))
    return None


def _module_helpers(tree: ast.Module) -> dict[str, str]:
    """Map helper name -> kind for helpers that hand back an emptiable set."""
    helpers: dict[str, str] = {}
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for stmt in _walk_own(node):
            if isinstance(stmt, (ast.Return, ast.YieldFrom)) and stmt.value is not None:
                kind = classify_iterable(stmt.value, {}, helpers)
                if kind is not None:
                    helpers[node.name] = f"helper returns {kind}"
                    break
            if isinstance(stmt, ast.For) and any(
                isinstance(inner, (ast.Yield, ast.YieldFrom))
                for inner in _walk_own(stmt)
            ):
                kind = classify_iterable(stmt.iter, {}, helpers)
                if kind is not None:
                    helpers[node.name] = f"helper yields {kind}"
                    break
    return helpers


def _local_bindings(
    func: ast.FunctionDef | ast.AsyncFunctionDef,
    helpers: dict[str, str],
) -> dict[str, str]:
    """Map names assigned inside *func* to the kind of what they hold."""
    bindings: dict[str, str] = {}
    for stmt in _walk_own(func):
        if isinstance(stmt, ast.Assign):
            targets: list[ast.expr] = list(stmt.targets)
            value: ast.expr | None = stmt.value
        elif isinstance(stmt, ast.AnnAssign):
            targets = [stmt.target]
            value = stmt.value
        else:
            continue
        if value is None:
            continue
        kind = classify_iterable(value, bindings, helpers)
        if kind is None:
            continue
        for target in targets:
            if isinstance(target, ast.Name):
                bindings[target.id] = f"local {kind}"
    return bindings


def _iterating_asserts(
    func: ast.FunctionDef | ast.AsyncFunctionDef,
) -> Iterator[tuple[ast.expr, int]]:
    """Yield ``(iterated expression, lineno)`` for every assertion-bearing loop.

    Three syntactic positions carry the same semantics:

    * ``for x in Y: ... assert ...`` — zero iterations, zero assertions;
    * ``assert all(<genexp>)`` — ``all(())`` is ``True``;
    * ``assert not any(<genexp>)`` — ``any(())`` is ``False``.

    A bare ``assert any(<genexp>)`` is *not* included: over an empty
    iterable it is ``False``, so it fails loudly instead of silently.
    """
    for node in _walk_own(func):
        if isinstance(node, ast.For) and any(
            isinstance(inner, ast.Assert) for inner in _walk_own(node)
        ):
            yield node.iter, node.lineno
        if isinstance(node, ast.Assert):
            test = node.test
            negated = False
            if isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not):
                test, negated = test.operand, True
            if not (isinstance(test, ast.Call) and isinstance(test.func, ast.Name)):
                continue
            wanted = "any" if negated else "all"
            if test.func.id != wanted or not test.args:
                continue
            argument = test.args[0]
            if isinstance(argument, (ast.GeneratorExp, ast.ListComp, ast.SetComp)):
                yield argument, node.lineno


def scan_source(source: str, path: str) -> list[VacuousClaim]:
    """Return every vacuum-prone claim in *source*.

    *path* is used verbatim in :attr:`VacuousClaim.path`; pass a
    repo-relative posix path so the keys stay stable across checkouts.
    """
    tree = ast.parse(source)
    helpers = _module_helpers(tree)
    claims: list[VacuousClaim] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        bindings = _local_bindings(node, helpers)
        for iterated, lineno in _iterating_asserts(node):
            kind = classify_iterable(iterated, bindings, helpers)
            if kind is None:
                continue
            claims.append(
                VacuousClaim(
                    path=path,
                    lineno=lineno,
                    test=node.name,
                    iterable=ast.unparse(iterated),
                    kind=kind,
                )
            )
    return claims


def scan_paths(paths: Iterable[Path]) -> ScanResult:
    """Scan every ``*.py`` file under *paths* (files are taken as given)."""
    files: list[str] = []
    claims: list[VacuousClaim] = []
    for entry in paths:
        candidates = sorted(entry.rglob("*.py")) if entry.is_dir() else [entry]
        for candidate in candidates:
            relative = candidate.resolve().relative_to(ROOT).as_posix()
            files.append(relative)
            claims.extend(
                scan_source(candidate.read_text(encoding="utf-8"), relative)
            )
    return ScanResult(files=tuple(files), claims=tuple(claims))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Find vacuum-prone assertions.")
    parser.add_argument(
        "paths",
        nargs="*",
        type=Path,
        default=[ROOT / "tests"],
        help="files or directories to scan (default: tests/)",
    )
    args = parser.parse_args(argv)
    result = scan_paths(args.paths)
    for claim in result.claims:
        print(f"{claim.path}:{claim.lineno}: {claim.test}: {claim.iterable} [{claim.kind}]")
    print(
        f"{len(result.files)} files scanned, {len(result.claims)} vacuum-prone claims",
        file=sys.stderr,
    )
    return 1 if result.claims else 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 5: Run the test to verify it passes**

```bash
cd /Users/spreuss/Documents/skipp-algo-wt-vacuity
PYTHONPATH=. /Users/spreuss/Documents/skipp-algo/.venv/bin/python -m pytest tests/test_detect_vacuous_claims.py -v
```

Expected: 11 passed. If `test_method_call_on_self_resolves_to_the_helper` fails, the cause is `_module_helpers` walking `ast.walk(tree)` — methods inside a class body are reached, so the fix is in `classify_iterable`'s `ast.Attribute` branch, not in the test.

- [ ] **Step 6: Check the CLI runs against the real tree**

```bash
cd /Users/spreuss/Documents/skipp-algo-wt-vacuity
PYTHONPATH=. /Users/spreuss/Documents/skipp-algo/.venv/bin/python -m scripts.detect_vacuous_claims tests/ | head -40
```

Expected: a list of `path:lineno: test: iterable [kind]` lines and a stderr summary naming >1000 scanned files. **Record the exact counts in the commit message** — this is the honest baseline, and it will differ from the throwaway prototype's 29/17. Do not carry the old number forward.

- [ ] **Step 7: Lint and commit**

```bash
cd /Users/spreuss/Documents/skipp-algo-wt-vacuity
/Users/spreuss/Documents/skipp-algo/.venv/bin/python -m ruff check scripts/detect_vacuous_claims.py tests/test_detect_vacuous_claims.py
git add scripts/detect_vacuous_claims.py tests/test_detect_vacuous_claims.py
git commit -m "feat(guard): classify iterables that can be empty at runtime" -m "Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Witness detection — per iterable, not per test

**Files:**
- Modify: `scripts/detect_vacuous_claims.py`
- Test: `tests/test_detect_vacuous_claims.py`

**Interfaces:**
- Consumes: `classify_iterable`, `scan_source`, `VacuousClaim`, `_walk_own` from Task 1.
- Produces: `witness_keys(func: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]` and a `scan_source` that suppresses witnessed claims. Task 3 and Task 4 both depend on this filtering already being in place.

**Context for the implementer:** the throwaway prototype exonerated a whole test as soon as it saw *any* witness. That is wrong, and the repo proves it: in `tests/test_enrichment_contract_integration.py` two neighbouring tests have the identical shape, the lower one carries `assert bool_lines, "…would pass vacuously"` and the upper one (`test_pine_syntax_valid`, line 374, `for line in export_lines:`) carries nothing. `assert bool_lines` says nothing about `export_lines`. **The witness binds to the expression, not to the test.**

Four witness forms must all be recognised (spec §5). Form 4 is the loop-exhaustion idiom that makes `tests/test_global_statement_budget.py` and `tests/test_http_client_discipline.py` correct despite looking suspicious: when the loop finds nothing, control falls into an explicit `raise`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_detect_vacuous_claims.py`:

```python
def test_bare_truth_check_witnesses_its_own_iterable() -> None:
    """The lived idiom from the repo: ``assert xs, "…would pass vacuously"``."""
    source = """
        def test_no_python_booleans():
            bool_lines = [ln for ln in TEXT.splitlines() if "const bool " in ln]
            assert bool_lines, "generator emitted no 'const bool' export"
            for line in bool_lines:
                assert "True" not in line
    """
    assert _kinds(source) == {}


def test_a_witness_for_one_iterable_does_not_cover_its_neighbour() -> None:
    """The strongest single piece of evidence in the repo, in one fixture.

    Someone recognised the class, healed ``bool_lines`` and left the
    identically shaped ``export_lines`` directly above it alone.
    """
    source = """
        def test_pine_syntax_valid():
            export_lines = [ln for ln in TEXT.splitlines() if ln.startswith("export")]
            bool_lines = [ln for ln in TEXT.splitlines() if "const bool " in ln]
            assert bool_lines
            for line in export_lines:
                assert TYPE_PAT.match(line)
    """
    assert _kinds(source) == {"export_lines": "local filtered comprehension"}


def test_len_check_is_a_witness() -> None:
    source = """
        def test_ledgers_are_gated():
            ledgers = [p for p in TEST_DIR.glob("test_*.py") if "pin_registry" in p.read_text()]
            assert len(ledgers) >= 15, "discovery found nothing"
            for ledger in ledgers:
                assert ledger.name in STEP
    """
    assert _kinds(source) == {}


def test_equality_with_a_nonempty_literal_is_a_witness() -> None:
    source = """
        def test_exact_set():
            found = [n for n in NAMES if n.startswith("smc_")]
            assert found == ["smc_a", "smc_b"]
            for name in found:
                assert name.islower()
    """
    assert _kinds(source) == {}


def test_equality_with_an_empty_literal_is_not_a_witness() -> None:
    """``assert xs == []`` proves emptiness — the opposite of a witness."""
    source = """
        def test_nothing_left():
            found = [n for n in NAMES if n.startswith("smc_")]
            assert found == []
            for name in found:
                assert name.islower()
    """
    assert _kinds(source) == {"found": "local filtered comprehension"}


def test_raise_after_the_loop_is_a_witness() -> None:
    """The ``frozen site`` idiom: exhausting the loop is itself a failure."""
    source = """
        def test_frozen_site_still_present():
            for path in ROOT.rglob("*.py"):
                if path.name == "target.py":
                    assert path.read_text()
                    return
            raise AssertionError("target.py no longer present — pin is stale")
    """
    assert _kinds(source) == {}


def test_for_else_raise_is_a_witness() -> None:
    source = """
        def test_frozen_site_still_present():
            for path in ROOT.rglob("*.py"):
                if path.name == "target.py":
                    assert path.read_text()
                    break
            else:
                raise AssertionError("target.py no longer present")
    """
    assert _kinds(source) == {}


def test_pytest_fail_after_the_loop_is_a_witness() -> None:
    source = """
        def test_frozen_site_still_present():
            for path in ROOT.rglob("*.py"):
                if path.name == "target.py":
                    assert path.read_text()
                    return
            pytest.fail("target.py no longer present")
    """
    assert _kinds(source) == {}


def test_a_witness_in_a_different_test_does_not_count() -> None:
    """Cross-test witnesses are a registry decision, not a detector heuristic.

    ``tests/test_spec_constant_drift.py`` is the real instance: a separate
    ``test_at_least_one_spec_exists`` proves the glob non-empty, but at a
    different expression instance that no static rule can tie to this one.
    Such cases get a dated exemption, so the reasoning stays visible.
    """
    source = """
        def test_at_least_one_spec_exists():
            assert list(SPEC_DIR.glob("*.json"))

        def test_specs_are_valid():
            for path in SPEC_DIR.glob("*.json"):
                assert path.read_text()
    """
    assert _kinds(source) == {'SPEC_DIR.glob("*.json")': "discovery call"}
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd /Users/spreuss/Documents/skipp-algo-wt-vacuity
PYTHONPATH=. /Users/spreuss/Documents/skipp-algo/.venv/bin/python -m pytest tests/test_detect_vacuous_claims.py -v
```

Expected: `test_bare_truth_check_witnesses_its_own_iterable`, `test_len_check_is_a_witness`, `test_equality_with_a_nonempty_literal_is_a_witness`, `test_raise_after_the_loop_is_a_witness`, `test_for_else_raise_is_a_witness` and `test_pytest_fail_after_the_loop_is_a_witness` FAIL (claims still reported). The other three already pass — they pin behaviour that must survive the change.

- [ ] **Step 3: Implement witness detection**

Insert into `scripts/detect_vacuous_claims.py` above `_iterating_asserts`:

```python
def _is_nonempty_length_check(op: ast.cmpop, right: ast.expr) -> bool:
    """True when ``len(x) <op> <right>`` proves ``x`` non-empty."""
    if not (isinstance(right, ast.Constant) and isinstance(right.value, int)):
        return False
    if isinstance(op, ast.Gt):
        return right.value >= 0
    if isinstance(op, (ast.GtE, ast.Eq)):
        return right.value >= 1
    return False


def _is_nonempty_literal(node: ast.expr) -> bool:
    """True for literals that cannot be empty."""
    if isinstance(node, (ast.List, ast.Set, ast.Tuple)):
        return bool(node.elts)
    if isinstance(node, ast.Dict):
        return bool(node.keys)
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return bool(node.value)
    return False


def witness_keys(func: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    """Return the unparsed expressions proven non-empty inside *func*.

    Four forms, all of them already lived in this repo (spec §5):
    ``assert xs``, ``assert len(xs) >= n``, ``assert xs == <non-empty
    literal>``, and — handled in :func:`_exhaustion_raises` — a ``raise``
    reached by exhausting the loop.

    Scoped to one function on purpose. A witness for ``bool_lines`` says
    nothing about ``export_lines`` two lines above it.
    """
    keys: set[str] = set()
    for node in _walk_own(func):
        if not isinstance(node, ast.Assert):
            continue
        test = node.test
        if isinstance(test, ast.Compare) and len(test.ops) == 1:
            left = test.left
            op = test.ops[0]
            right = test.comparators[0]
            if (
                isinstance(left, ast.Call)
                and isinstance(left.func, ast.Name)
                and left.func.id == "len"
                and left.args
            ):
                if _is_nonempty_length_check(op, right):
                    keys.add(ast.unparse(left.args[0]))
                continue
            if isinstance(op, ast.Eq) and _is_nonempty_literal(right):
                keys.add(ast.unparse(left))
            continue
        keys.add(ast.unparse(test))
    return keys


def _raises_or_fails(node: ast.AST) -> bool:
    """True for ``raise ...`` and for ``pytest.fail(...)``."""
    if isinstance(node, ast.Raise):
        return True
    return (
        isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Call)
        and ast.unparse(node.value.func).endswith("fail")
    )


def _exhaustion_raises(
    func: ast.FunctionDef | ast.AsyncFunctionDef,
    loop: ast.For,
) -> bool:
    """True when falling out of *loop* raises instead of continuing.

    ``for … else: raise`` and a ``raise`` as the loop's next sibling are the
    same contract: "finding nothing is a failure". That is the correct
    anti-vacuity idiom and must be recognised, not flagged.
    """
    if any(_raises_or_fails(stmt) for stmt in loop.orelse):
        return True
    for node in ast.walk(func):
        for _field, value in ast.iter_fields(node):
            if not isinstance(value, list):
                continue
            for index, item in enumerate(value):
                if item is loop and index + 1 < len(value):
                    return _raises_or_fails(value[index + 1])
    return False
```

Then rewrite `_iterating_asserts` to skip exhaustion-witnessed loops and rewrite `scan_source` to subtract the witness keys. Replace the `for` branch of `_iterating_asserts` and the loop body of `scan_source`:

```python
# inside _iterating_asserts, replacing the ast.For branch:
        if isinstance(node, ast.For) and any(
            isinstance(inner, ast.Assert) for inner in _walk_own(node)
        ):
            if not _exhaustion_raises(func, node):
                yield node.iter, node.lineno
```

```python
# inside scan_source, replacing the body of the function loop:
        bindings = _local_bindings(node, helpers)
        witnessed = witness_keys(node)
        for iterated, lineno in _iterating_asserts(node):
            source_text = ast.unparse(iterated)
            if source_text in witnessed:
                continue
            kind = classify_iterable(iterated, bindings, helpers)
            if kind is None:
                continue
            claims.append(
                VacuousClaim(
                    path=path,
                    lineno=lineno,
                    test=node.name,
                    iterable=source_text,
                    kind=kind,
                )
            )
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
cd /Users/spreuss/Documents/skipp-algo-wt-vacuity
PYTHONPATH=. /Users/spreuss/Documents/skipp-algo/.venv/bin/python -m pytest tests/test_detect_vacuous_claims.py -v
```

Expected: 20 passed.

- [ ] **Step 5: Re-measure and record the drop**

```bash
cd /Users/spreuss/Documents/skipp-algo-wt-vacuity
PYTHONPATH=. /Users/spreuss/Documents/skipp-algo/.venv/bin/python -m scripts.detect_vacuous_claims tests/ 2>&1 >/dev/null
PYTHONPATH=. /Users/spreuss/Documents/skipp-algo/.venv/bin/python -m scripts.detect_vacuous_claims tests/test_enrichment_contract_integration.py
```

Expected on the second command: `test_pine_syntax_valid` is reported and `test_no_python_booleans` is not. This is the calibration case — if both or neither appear, the witness is not binding per iterable and Step 3 is wrong.

- [ ] **Step 6: Lint and commit**

```bash
cd /Users/spreuss/Documents/skipp-algo-wt-vacuity
/Users/spreuss/Documents/skipp-algo/.venv/bin/python -m ruff check scripts/detect_vacuous_claims.py tests/test_detect_vacuous_claims.py
git add scripts/detect_vacuous_claims.py tests/test_detect_vacuous_claims.py
git commit -m "feat(guard): bind the non-emptiness witness to the iterable, not the test" -m "Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: The second syntax position — empty `parametrize`

**Files:**
- Modify: `scripts/detect_vacuous_claims.py`
- Test: `tests/test_detect_vacuous_claims.py`

**Interfaces:**
- Consumes: `classify_iterable`, `VacuousClaim`, `scan_source` from Tasks 1–2.
- Produces: `parametrize` claims inside the same `scan_source` output, with `test` set to the decorated function's name and `kind` prefixed `"parametrize "`. No new public function — Task 4 keeps calling `scan_paths` only.

**Context for the implementer:** if `@pytest.mark.parametrize(..., argvalues)` gets an empty `argvalues`, pytest collects **zero** tests: no skip, no failure, no line of output. The handover's first take (§3.4) aimed at the wrong instances — `_FROZEN_SITES` and `_FROZEN_URLOPEN_SITES` are literal frozensets and cannot silently become empty, because emptying a literal is a visible edit. Applying the same emptiability rule as for loops narrows the naive 148 hits to a reviewable set (the throwaway probe measured 9 in 8 files, e.g. `tests/test_workflow_auth_pattern.py:111` via `_iter_workflow_files()` and `tests/test_spec_constant_drift.py:183` via `(REPO_ROOT/'artifacts'/'experiments').glob('*.json')`, which currently has exactly one file under it).

Witness scope for this vector is the **module**, not a function: `argvalues` is evaluated at import time. A separate `test_<ledger>_roster_is_not_empty` therefore cannot be seen by the analyzer — that is deliberate (Task 2, cross-test witnesses). Such cases get a dated exemption in Task 5 whose justification names the enforcing test.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_detect_vacuous_claims.py`:

```python
def test_parametrize_over_a_literal_is_not_a_claim() -> None:
    """A literal argvalues list cannot silently become empty."""
    source = """
        @pytest.mark.parametrize("name", ["a", "b"])
        def test_names(name):
            assert name.islower()
    """
    assert _kinds(source) == {}


def test_parametrize_over_a_frozenset_constant_is_not_a_claim() -> None:
    """``_FROZEN_SITES`` is a literal: emptying it is a visible edit."""
    source = """
        _FROZEN_SITES = frozenset({("a.py", 1), ("b.py", 2)})

        @pytest.mark.parametrize(("rel", "lineno"), sorted(_FROZEN_SITES))
        def test_frozen_site_still_present(rel, lineno):
            assert (ROOT / rel).is_file()
    """
    assert _kinds(source) == {}


def test_parametrize_over_a_discovery_call_is_a_claim() -> None:
    """Zero argvalues collects zero tests — no skip, no failure, no output."""
    source = """
        @pytest.mark.parametrize("path", (REPO_ROOT / "artifacts").glob("*.json"))
        def test_specs(path):
            assert path.read_text()
    """
    assert _kinds(source) == {
        '(REPO_ROOT / "artifacts").glob("*.json")': "parametrize discovery call"
    }


def test_parametrize_over_a_helper_is_a_claim() -> None:
    source = """
        def _iter_workflow_files():
            return sorted((ROOT / ".github" / "workflows").glob("*.yml"))

        @pytest.mark.parametrize("path", _iter_workflow_files())
        def test_workflow_auth(path):
            assert "permissions:" in path.read_text()
    """
    assert _kinds(source) == {
        "_iter_workflow_files()": "parametrize helper returns discovery call"
    }


def test_parametrize_over_a_filtered_module_constant_is_a_claim() -> None:
    source = """
        _NK_CASES = [c for c in ALL_CASES if c.n > 0]

        @pytest.mark.parametrize("case", _NK_CASES)
        def test_llr(case):
            assert case.llr > 0
    """
    assert _kinds(source) == {"_NK_CASES": "parametrize local filtered comprehension"}
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd /Users/spreuss/Documents/skipp-algo-wt-vacuity
PYTHONPATH=. /Users/spreuss/Documents/skipp-algo/.venv/bin/python -m pytest tests/test_detect_vacuous_claims.py -k parametrize -v
```

Expected: the two "is a claim" tests plus `test_parametrize_over_a_filtered_module_constant_is_a_claim` FAIL with `assert {} == {...}`; the two "is not a claim" tests pass.

- [ ] **Step 3: Implement the parametrize vector**

Add to `scripts/detect_vacuous_claims.py`:

```python
def _module_bindings(tree: ast.Module, helpers: dict[str, str]) -> dict[str, str]:
    """Map module-level names to the kind of what they hold.

    ``argvalues`` is evaluated at import time, so module scope — not test
    scope — is what decides whether a parametrize set can be empty.
    """
    bindings: dict[str, str] = {}
    for stmt in tree.body:
        if isinstance(stmt, ast.Assign):
            targets: list[ast.expr] = list(stmt.targets)
            value: ast.expr | None = stmt.value
        elif isinstance(stmt, ast.AnnAssign):
            targets = [stmt.target]
            value = stmt.value
        else:
            continue
        if value is None:
            continue
        kind = classify_iterable(value, bindings, helpers)
        if kind is None:
            continue
        for target in targets:
            if isinstance(target, ast.Name):
                bindings[target.id] = f"local {kind}"
    return bindings


def _parametrize_argvalues(
    func: ast.FunctionDef | ast.AsyncFunctionDef,
) -> Iterator[tuple[ast.expr, int]]:
    """Yield ``(argvalues expression, lineno)`` for every parametrize decorator."""
    for decorator in func.decorator_list:
        if not isinstance(decorator, ast.Call):
            continue
        target = decorator.func
        if not (isinstance(target, ast.Attribute) and target.attr == "parametrize"):
            continue
        if len(decorator.args) < 2:
            continue
        yield decorator.args[1], decorator.lineno
```

Extend `scan_source`: compute `module_bindings = _module_bindings(tree, helpers)` next to `helpers`, and add inside the function loop, after the existing `_iterating_asserts` block:

```python
        for argvalues, lineno in _parametrize_argvalues(node):
            kind = classify_iterable(argvalues, module_bindings, helpers)
            if kind is None:
                continue
            claims.append(
                VacuousClaim(
                    path=path,
                    lineno=lineno,
                    test=node.name,
                    iterable=ast.unparse(argvalues),
                    kind=f"parametrize {kind}",
                )
            )
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
cd /Users/spreuss/Documents/skipp-algo-wt-vacuity
PYTHONPATH=. /Users/spreuss/Documents/skipp-algo/.venv/bin/python -m pytest tests/test_detect_vacuous_claims.py -v
```

Expected: 25 passed.

- [ ] **Step 5: Verify against the known real instances**

```bash
cd /Users/spreuss/Documents/skipp-algo-wt-vacuity
PYTHONPATH=. /Users/spreuss/Documents/skipp-algo/.venv/bin/python -m scripts.detect_vacuous_claims \
  tests/test_workflow_auth_pattern.py tests/test_spec_constant_drift.py \
  tests/test_workflow_no_fake_push_success.py tests/test_global_statement_budget.py
```

Expected: `parametrize`-kind claims in the first three files; **no** claim in `test_global_statement_budget.py` (its frozen-site loop is exhaustion-witnessed and its parametrize runs over a literal frozenset). If `test_global_statement_budget.py` is reported, Task 2's witness or Task 3's literal handling regressed — fix that before continuing.

- [ ] **Step 6: Lint and commit**

```bash
cd /Users/spreuss/Documents/skipp-algo-wt-vacuity
/Users/spreuss/Documents/skipp-algo/.venv/bin/python -m ruff check scripts/detect_vacuous_claims.py tests/test_detect_vacuous_claims.py
git add scripts/detect_vacuous_claims.py tests/test_detect_vacuous_claims.py
git commit -m "feat(guard): catch parametrize sets that can collect zero tests" -m "Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: The guard, the exemption registry, and the required path

**Files:**
- Create: `tests/test_vacuous_claim_guard.py`
- Modify: `tests/_pin_registry.py` (new accessor), `pin_registry.toml` (new table), `.github/workflows/smc-fast-pr-gates.yml`, `tests/test_fast_gates_silent_skip_coverage.py`, `tests/_fast_inventory.py`

**Interfaces:**
- Consumes: `ROOT`, `ScanResult`, `scan_paths`, `VacuousClaim.key` from Tasks 1–3.
- Produces: `vacuous_claim_exemptions() -> dict[str, str]` in `tests/_pin_registry.py`, keyed `"tests/x.py::test_y::iterable"` with a dated justification as the value. Task 5 fills this table.

**Context for the implementer:** four registration surfaces, all in the same PR, all verified against `origin/main`:

1. `.github/workflows/smc-fast-pr-gates.yml`, step "Run pin / ledger drift guard" — the file list ends at `tests/test_update_overlay_dashboard.py` (around line 568). `_drift_guard_step_text()` scopes from "Run pin / ledger drift guard" to "Run fast SMC integration tests" and strips comments, so a commented-out entry does not count.
2. `FULL_REQUIRED_PATH_TRIPWIRES` in `tests/test_fast_gates_silent_skip_coverage.py` (around line 98). The roster check is **bidirectional**: a step entry without a roster entry is just as red as the reverse.
3. `FAST_TEST_FILES` in `tests/_fast_inventory.py` (ADR-0012 partition; `tests/test_pytest_marker_bucket_discipline.py` enforces lock-step with the workflow).
4. `scripts/run_ledger_drift_guard.sh` is **not** a fourth edit — it reads the list out of the workflow step with `awk` and follows automatically. (Do not name that script inside a Bash command; a hook blocks it. Use the Read tool.)

The guard registers *itself* as mandatory: `_pinned_ledgers()` in `tests/test_fast_gates_silent_skip_coverage.py` treats every test file containing the string `pin_registry` as a pinned ledger, and `test_every_pinned_ledger_is_on_the_required_path` (around line 478) then demands it be gated. So surface 1 is not optional once the guard reads the registry.

**The guard must survive its own rule.** `assert undeclared == []` over an empty list is precisely the forbidden shape. The repo already has the answer three times over in the meta-guards — `assert len(ledgers) >= 15`, `assert len(guards) >= 15`, `assert len(all_ts) >= 20`. The new guard cites that precedent and carries `assert len(result.files) > 1_000`.

- [ ] **Step 1: Write the failing guard**

Create `/Users/spreuss/Documents/skipp-algo-wt-vacuity/tests/test_vacuous_claim_guard.py`:

```python
"""Merge gate for the "green without having looked" class.

A check whose loop runs zero times reports success without evidence. The
repo has said so in prose 34 times (``"…would pass vacuously"``) and has
healed individual instances by hand; what it lacked was enforcement. This
guard closes the class: every vacuum-prone claim is either fixed with the
lived idiom or carries a dated justification in ``pin_registry.toml``.

This guard is subject to its own rule. ``assert undeclared == []`` over an
empty list is exactly the shape it forbids, so it carries a witness that
the analyzer actually looked at something — the same idiom the fast-gates
meta-guards already use (``assert len(ledgers) >= 15`` and its two
siblings in ``tests/test_fast_gates_silent_skip_coverage.py``).
"""

from __future__ import annotations

import re
from functools import lru_cache

from scripts.detect_vacuous_claims import ROOT, ScanResult, scan_paths
from tests._pin_registry import vacuous_claim_exemptions

TESTS_DIR = ROOT / "tests"

#: An exemption is a decision, and a decision has a date and a reason.
_DATED_REASON = re.compile(r"^\d{4}-\d{2}-\d{2}: \S")


@lru_cache(maxsize=1)
def _scan() -> ScanResult:
    return scan_paths([TESTS_DIR])


def test_the_analyzer_observed_the_test_suite() -> None:
    """Witness for the gate below — without it, this file is its own bug.

    If discovery breaks (a moved tests/ layout, a swallowed parse error),
    the claim set goes empty and every assertion here passes while proving
    nothing. Pinning the scanned population makes that failure loud.
    """
    scanned = _scan().files
    assert len(scanned) > 1_000, (
        f"the analyzer scanned only {len(scanned)} files — discovery or the "
        "tests/ layout changed and this guard would pass vacuously"
    )


def test_no_unexempted_vacuous_claims() -> None:
    """Every vacuum-prone assertion is fixed or explicitly declared."""
    exemptions = vacuous_claim_exemptions()
    undeclared = sorted(
        f"{claim.key}  [{claim.kind}]  {claim.path}:{claim.lineno}"
        for claim in _scan().claims
        if claim.key not in exemptions
    )
    assert undeclared == [], (
        "assertion(s) can pass without observing anything: the iterable can "
        "be empty at runtime and nothing in the same scope proves it is not.\n\n"
        + "\n".join(undeclared)
        + "\n\nFix with the idiom this repo already uses — assert the set "
        "non-empty next to the loop (`assert bool_lines, \"…would pass "
        "vacuously\"`), or raise when the loop finds nothing. If the "
        "emptiness is intended and proven elsewhere, add the key to "
        "[vacuous_claim_guard.exemptions] in pin_registry.toml with a dated "
        "reason naming the test that does the proving."
    )


def test_every_exemption_still_matches_a_claim() -> None:
    """A stale exemption silently shrinks the guarded set.

    Same contract as the ``frozen site still present`` tests: if the code an
    exemption refers to was fixed or deleted, the exemption must go with it,
    otherwise the registry drifts into a list of things nobody checks.
    """
    keys = {claim.key for claim in _scan().claims}
    stale = sorted(set(vacuous_claim_exemptions()) - keys)
    assert stale == [], (
        "exemption(s) no longer match any detected claim (fixed, renamed or "
        f"deleted): {stale}. Remove them so the registry stays a true mirror "
        "of what is actually being waived."
    )


def test_every_exemption_carries_a_dated_reason() -> None:
    """An undated waiver is indistinguishable from an accident."""
    undated = sorted(
        key
        for key, reason in vacuous_claim_exemptions().items()
        if not _DATED_REASON.match(reason)
    )
    assert undated == [], (
        f"exemption(s) without a ``YYYY-MM-DD: reason`` justification: {undated}"
    )
```

- [ ] **Step 2: Run it to verify it fails**

```bash
cd /Users/spreuss/Documents/skipp-algo-wt-vacuity
PYTHONPATH=. /Users/spreuss/Documents/skipp-algo/.venv/bin/python -m pytest tests/test_vacuous_claim_guard.py -v
```

Expected: collection error — `ImportError: cannot import name 'vacuous_claim_exemptions' from 'tests._pin_registry'`.

- [ ] **Step 3: Add the registry accessor and the table**

Append to `tests/_pin_registry.py`, following the existing accessor style (one slice per ledger test, docstring naming the shape):

```python
def vacuous_claim_exemptions() -> dict[str, str]:
    """Return waived vacuum-prone claims: ``"file::test::iterable" -> reason``.

    The reason is a dated justification (``YYYY-MM-DD: …``) and normally
    names the test that proves the emptiness is intended.
    """
    return dict(_load()["vacuous_claim_guard"]["exemptions"])
```

Append to `pin_registry.toml`:

```toml
# ---------------------------------------------------------------------------
# test_vacuous_claim_guard.py — assertions whose iterable may legitimately be
# empty. Key: "file::test::iterable". Value: dated reason, normally naming the
# test that proves the emptiness is declared rather than incidental.
# ---------------------------------------------------------------------------
[vacuous_claim_guard.exemptions]
```

Leave the table empty for now — Task 5 fills it from measurement, not from guesswork.

- [ ] **Step 4: Run it again — expect a real, informative failure**

```bash
cd /Users/spreuss/Documents/skipp-algo-wt-vacuity
PYTHONPATH=. /Users/spreuss/Documents/skipp-algo/.venv/bin/python -m pytest tests/test_vacuous_claim_guard.py -v
```

Expected: `test_the_analyzer_observed_the_test_suite`, `test_every_exemption_still_matches_a_claim` and `test_every_exemption_carries_a_dated_reason` PASS; `test_no_unexempted_vacuous_claims` FAILS and lists the baseline. **Copy that list into `/tmp/vacuity-baseline.txt`** — Task 5 works from it.

```bash
cd /Users/spreuss/Documents/skipp-algo-wt-vacuity
PYTHONPATH=. /Users/spreuss/Documents/skipp-algo/.venv/bin/python -m scripts.detect_vacuous_claims tests/ \
  > /private/tmp/claude-501/-Users-spreuss/vacuity-baseline.txt
```

- [ ] **Step 5: Wire all three registration surfaces**

Edit `.github/workflows/smc-fast-pr-gates.yml`, step "Run pin / ledger drift guard": the list currently ends with `tests/test_update_overlay_dashboard.py` (no trailing backslash). Add a backslash there and append two lines:

```yaml
            tests/test_update_overlay_dashboard.py \
            tests/test_detect_vacuous_claims.py \
            tests/test_vacuous_claim_guard.py
```

Edit `tests/test_fast_gates_silent_skip_coverage.py`, tuple `FULL_REQUIRED_PATH_TRIPWIRES` — insert alphabetically (find the neighbours with `grep -n 'test_datetime_tz_safety\|test_update_overlay_dashboard' tests/test_fast_gates_silent_skip_coverage.py`):

```python
    "tests/test_detect_vacuous_claims.py",
```

```python
    # 2026-08-03: the vacuity guard reads pin_registry.toml, so
    # test_every_pinned_ledger_is_on_the_required_path demands it be gated.
    # Registered here as well because the roster check is bidirectional.
    "tests/test_vacuous_claim_guard.py",
```

Edit `tests/_fast_inventory.py`, `FAST_TEST_FILES` (basenames, no `tests/` prefix):

```python
    "test_detect_vacuous_claims.py",
    "test_vacuous_claim_guard.py",
```

- [ ] **Step 6: Verify the wiring, including the workflow-edit obligation**

```bash
cd /Users/spreuss/Documents/skipp-algo-wt-vacuity
PYTEST_XDIST_AUTO_NUM_WORKERS=4 PYTHONPATH=. /Users/spreuss/Documents/skipp-algo/.venv/bin/python -m pytest \
  tests/test_fast_gates_silent_skip_coverage.py tests/test_pytest_marker_bucket_discipline.py -v
```

Expected: all pass. A failure in `test_full_tripwire_roster_pinned_in_fast_gates` means the step and the roster disagree; a failure in the marker-bucket test means `_fast_inventory.py` and the workflow disagree.

Because this PR edits a workflow, the required extra run (Global Constraints):

```bash
cd /Users/spreuss/Documents/skipp-algo-wt-vacuity
PYTEST_XDIST_AUTO_NUM_WORKERS=4 PYTHONPATH=. /Users/spreuss/Documents/skipp-algo/.venv/bin/python -m pytest tests/ -k workflow
```

Expected: green (≈2100 tests, ≈4 min).

- [ ] **Step 7: Commit**

```bash
cd /Users/spreuss/Documents/skipp-algo-wt-vacuity
/Users/spreuss/Documents/skipp-algo/.venv/bin/python -m ruff check tests/ scripts/
git add tests/test_vacuous_claim_guard.py tests/_pin_registry.py pin_registry.toml \
  .github/workflows/smc-fast-pr-gates.yml tests/test_fast_gates_silent_skip_coverage.py tests/_fast_inventory.py
git commit -m "feat(guard): gate vacuum-prone assertions on the required path" -m "Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

The guard is red at this point, by design — Task 5 turns it green with evidence rather than with a weakened rule.

---

### Task 5: Baseline triage — fix, declare, or sharpen

**Files:**
- Modify: the test files named in the baseline, `pin_registry.toml`, and (where a false positive is found) `scripts/detect_vacuous_claims.py` + `tests/test_detect_vacuous_claims.py`

**Interfaces:**
- Consumes: the baseline written in Task 4 Step 4, `vacuous_claim_exemptions()`.
- Produces: a green `tests/test_vacuous_claim_guard.py`.

**Context for the implementer:** the handover's prototype measured 29 loop hits in 17 files and 9 parametrize hits in 8 files, but only four of them were ever looked at in the code. **The true-positive rate of the rest is unknown and must not be asserted.** Your analyzer is not that prototype, so your baseline will differ. Work from your own measurement.

Every entry gets exactly one of three outcomes, and the choice is evidence-based:

- **Fix** — the emptiness is not intended: add the lived witness next to the loop (`assert xs, "…would pass vacuously"`), or make loop exhaustion raise. Preferred outcome.
- **Declare** — the emptiness is intended and proven elsewhere: a dated exemption whose reason names the proving test. The archive gate in `tests/test_pine_surface_registry.py` is the model: its emptiness is pinned by `test_the_archived_population_is_declared_rather_than_incidental` and the rule itself is proven on data in `tests/test_archived_surface_consumers.py`. All parametrize cases fixed with a `test_<ledger>_roster_is_not_empty` also land here — the roster test is a cross-test witness the analyzer deliberately cannot see, so the exemption is what records the reasoning.
- **Sharpen** — the analyzer is wrong: add a fixture to `tests/test_detect_vacuous_claims.py` that reproduces the shape, then change the classifier. Never silence a false positive with an exemption.

- [ ] **Step 1: Turn the baseline into a triage table**

Read `/private/tmp/claude-501/-Users-spreuss/vacuity-baseline.txt` and open each cited site. Write `/private/tmp/claude-501/-Users-spreuss/vacuity-triage.md` with one row per claim: `key | verdict (fix/declare/sharpen) | evidence`. Evidence means what you saw in the code, not what the shape suggested.

- [ ] **Step 2: Measure the production-Python surface before deciding its scope**

```bash
cd /Users/spreuss/Documents/skipp-algo-wt-vacuity
PYTHONPATH=. /Users/spreuss/Documents/skipp-algo/.venv/bin/python -m scripts.detect_vacuous_claims scripts/ services/ 2>&1 | tail -20
```

The spec asks for production code too. `assert` in production is already budget-gated by `tests/test_assert_in_production_budget.py`, so this surface may well be empty — and a guard over an empty surface would be the very thing this work forbids. Record the number. If it is zero, say so in the PR description and leave the guard scoped to `tests/` with that reason; if it is not zero, add the roots to `TESTS_DIR`'s call site in `tests/test_vacuous_claim_guard.py` and triage them like the rest. Either way this is a measured decision, not an assumption.

- [ ] **Step 3: Apply the fixes**

For each `fix` row, edit the test. The canonical shape, from `tests/test_enrichment_contract_integration.py:387`:

```python
        export_lines = _export_lines(text)
        assert export_lines, "generator emitted no export line — type pin would pass vacuously"
        for line in export_lines:
            assert type_pat.match(line), f"Bad export line: {line}"
```

`tests/test_enrichment_contract_integration.py::test_pine_syntax_valid` (line ~374) is the known instance and should be fixed exactly like its neighbour directly below it.

Check for line pins before editing (Global Constraints):

```bash
cd /Users/spreuss/Documents/skipp-algo-wt-vacuity
grep -n "$(basename <file>)" pin_registry.toml
```

- [ ] **Step 4: Apply the declarations**

For each `declare` row, add to `[vacuous_claim_guard.exemptions]` in `pin_registry.toml`:

```toml
"tests/test_pine_surface_registry.py::test_archived_surfaces_are_removed::_archived_surfaces()" = "2026-08-03: the archived population is intentionally empty and pinned by test_the_archived_population_is_declared_rather_than_incidental; the rule itself is proven on data in tests/test_archived_surface_consumers.py"
```

(Substitute the real key from your baseline — the test name above is the shape, not a guess to be copied blind.)

Where the verdict is `declare` because a roster test does the proving, add that test first, e.g. for `tests/test_workflow_auth_pattern.py`:

```python
def test_workflow_roster_is_not_empty() -> None:
    """Zero argvalues would collect zero tests — silently, with no output."""
    workflows = list(_iter_workflow_files())
    assert len(workflows) >= 10, (
        f"workflow discovery found {len(workflows)} files — the parametrized "
        "checks below would collect nothing and report nothing"
    )
```

- [ ] **Step 5: Apply the sharpenings**

For each `sharpen` row, add the reproducing fixture to `tests/test_detect_vacuous_claims.py` first (red), then change `classify_iterable` / `witness_keys` (green). Re-run the full unit suite after each one:

```bash
cd /Users/spreuss/Documents/skipp-algo-wt-vacuity
PYTHONPATH=. /Users/spreuss/Documents/skipp-algo/.venv/bin/python -m pytest tests/test_detect_vacuous_claims.py -v
```

- [ ] **Step 6: Verify the guard is green for the right reason**

```bash
cd /Users/spreuss/Documents/skipp-algo-wt-vacuity
PYTHONPATH=. /Users/spreuss/Documents/skipp-algo/.venv/bin/python -m pytest tests/test_vacuous_claim_guard.py -v
```

Expected: 4 passed. Then confirm the guard is not green by accident — temporarily append a synthetic offender to a scratch test file, re-run, see it reported, and remove it again:

```bash
cd /Users/spreuss/Documents/skipp-algo-wt-vacuity
printf '\n\ndef test_synthetic_vacuity_probe():\n    hits = [p for p in ROOT.glob("*.nope") if p.is_file()]\n    for hit in hits:\n        assert hit.is_file()\n' >> tests/test_detect_vacuous_claims.py
PYTHONPATH=. /Users/spreuss/Documents/skipp-algo/.venv/bin/python -m pytest tests/test_vacuous_claim_guard.py::test_no_unexempted_vacuous_claims -v
git checkout tests/test_detect_vacuous_claims.py
```

Expected: the middle command FAILS and names `test_synthetic_vacuity_probe`. If it passes, the guard is itself vacuous and Tasks 1–4 must be re-checked before anything is committed.

- [ ] **Step 7: Full pre-push validation, commit, push, PR**

Use the `Documents/skipp-algo:pre-push-guard` skill for the mandatory gate, then:

```bash
cd /Users/spreuss/Documents/skipp-algo-wt-vacuity
/Users/spreuss/Documents/skipp-algo/.venv/bin/python -m ruff check .
git add -A
git status
git commit -m "fix(tests): heal the vacuum-prone assertions the new guard found" -m "Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

`git status` before committing is not optional: three tests in this suite write into `governance/` and `artifacts/` in the working tree.

Push in the background (Global Constraints), then open the PR with the `Documents/skipp-algo:skipp-pr-flow` skill. The PR description states: the measured baseline, the fix/declare/sharpen split, and the self-witness argument (`assert len(scanned) > 1_000`) — the guard is subject to its own rule and says so. Frame it as codifying a convention the repo already lives (34 prose mentions of "would pass vacuously"), not as a new policy. **Do not merge without an explicit signal from the user.**

---

### Task 6: TypeScript analyzer and guard

**Files:**
- Create: `scripts/detect_vacuous_claims_ts.ts`, `automation/tradingview/tests/vacuous_claims_ts.test.ts`
- Modify: `.github/workflows/tv-onboarding-packages.yml`

**Interfaces:**
- Consumes: nothing from Tasks 1–5 (separate lane, separate PR).
- Produces: `export interface TsVacuousClaim { path: string; line: number; scope: string; iterable: string; kind: string; key: string }` and `export function scanSource(source: string, path: string): TsVacuousClaim[]`, `export function scanDir(dir: string): { files: string[]; claims: TsVacuousClaim[] }`.

**Context for the implementer:** start from a fresh branch off current `origin/main` (`git fetch` + `gh pr list` again). TypeScript 5.9.2 is already a devDependency, so the analyzer can `import ts from "typescript"` — no new package. The surface is 51 `*.test.ts` files with ~36 `for (const … of …)` loops and ~32 `.every(`/`.some(` sites.

Registration is hook-enforced, not conventional. `test_every_ts_test_is_gated_or_exempt` turns any new `*.test.ts` red unless it runs in the `npx tsx --test` step or sits in `_TS_TESTS_INTENTIONALLY_UNGATED`; `test_gated_ts_tests_trigger_their_own_workflow` additionally requires a `paths:` entry in **both** trigger blocks of `tv-onboarding-packages.yml` (push block near line 9, pull_request block near line 67). The run step is "Test hermetic TV pins" (near line 188) — that step is for source-scan / pure-logic pins with no playwright import, which is exactly what this test is.

- [ ] **Step 1: Write the failing test**

Create `automation/tradingview/tests/vacuous_claims_ts.test.ts`:

```ts
import assert from "node:assert/strict";
import path from "node:path";
import test from "node:test";

import { scanDir, scanSource } from "../../../scripts/detect_vacuous_claims_ts";

const TEST_DIR = path.resolve(__dirname);

/**
 * Waived claims: key -> dated reason. Mirrors
 * [vacuous_claim_guard.exemptions] in pin_registry.toml, which TypeScript
 * cannot read. Same contract: a waiver is a decision, so it is dated and
 * says why, and a stale one is red.
 */
const TS_VACUITY_EXEMPTIONS: Record<string, string> = {};

const kinds = (source: string): Record<string, string> =>
  Object.fromEntries(scanSource(source, "example.test.ts").map((c) => [c.iterable, c.kind]));

test("a literal array loop is not a claim", () => {
  const source = `for (const flag of ["--a", "--b"]) { assert.ok(text.includes(flag)); }`;
  assert.deepEqual(kinds(source), {});
});

test("a filtered array loop is a claim", () => {
  const source = `
    const hits = lines.filter((line) => line.includes("export"));
    for (const hit of hits) { assert.ok(hit.startsWith("export")); }
  `;
  assert.deepEqual(kinds(source), { hits: "local filter call" });
});

test("a directory read is a claim", () => {
  const source = `
    for (const name of fs.readdirSync(dir)) { assert.ok(name.endsWith(".ts")); }
  `;
  assert.deepEqual(kinds(source), { "fs.readdirSync(dir)": "discovery call" });
});

test("assert.ok over .every of a filtered array is a claim", () => {
  const source = `
    const hits = lines.filter((line) => line.includes("export"));
    assert.ok(hits.every((hit) => hit.startsWith("export")));
  `;
  assert.deepEqual(kinds(source), { hits: "local filter call" });
});

test("a length witness clears its own iterable", () => {
  const source = `
    const hits = lines.filter((line) => line.includes("export"));
    assert.ok(hits.length > 0, "no export line — this pin would pass vacuously");
    for (const hit of hits) { assert.ok(hit.startsWith("export")); }
  `;
  assert.deepEqual(kinds(source), {});
});

test("a witness for one array does not clear another", () => {
  const source = `
    const exports = lines.filter((line) => line.startsWith("export"));
    const bools = lines.filter((line) => line.includes("bool"));
    assert.ok(bools.length > 0);
    for (const line of exports) { assert.ok(TYPE_PAT.test(line)); }
  `;
  assert.deepEqual(kinds(source), { exports: "local filter call" });
});

test("a throw after the loop is a witness", () => {
  const source = `
    for (const name of fs.readdirSync(dir)) {
      if (name === "target.ts") { assert.ok(name); return; }
    }
    throw new Error("target.ts is gone — the pin is stale");
  `;
  assert.deepEqual(kinds(source), {});
});

test("the analyzer observed the TypeScript test suite", () => {
  // Witness for the gate below: an empty scan would make it pass silently.
  const { files } = scanDir(TEST_DIR);
  assert.ok(
    files.length >= 20,
    `scanned only ${files.length} *.test.ts files — discovery broke and the gate below is vacuous`,
  );
});

test("no unexempted vacuous claims in the TypeScript tests", () => {
  const { claims } = scanDir(TEST_DIR);
  const undeclared = claims
    .filter((claim) => !(claim.key in TS_VACUITY_EXEMPTIONS))
    .map((claim) => `${claim.key} [${claim.kind}] ${claim.path}:${claim.line}`)
    .sort();
  assert.deepEqual(
    undeclared,
    [],
    `assertion(s) can pass without observing anything:\n${undeclared.join("\n")}`,
  );
});

test("every TypeScript exemption still matches a claim", () => {
  const { claims } = scanDir(TEST_DIR);
  const keys = new Set(claims.map((claim) => claim.key));
  const stale = Object.keys(TS_VACUITY_EXEMPTIONS).filter((key) => !keys.has(key)).sort();
  assert.deepEqual(stale, [], `stale exemption(s): ${stale.join(", ")}`);
});

test("every TypeScript exemption carries a dated reason", () => {
  const undated = Object.entries(TS_VACUITY_EXEMPTIONS)
    .filter(([, reason]) => !/^\d{4}-\d{2}-\d{2}: \S/.test(reason))
    .map(([key]) => key)
    .sort();
  assert.deepEqual(undated, [], `undated exemption(s): ${undated.join(", ")}`);
});
```

- [ ] **Step 2: Run it to verify it fails**

```bash
cd /Users/spreuss/Documents/skipp-algo-wt-vacuity
npx tsx --test automation/tradingview/tests/vacuous_claims_ts.test.ts
```

Expected: module-not-found for `scripts/detect_vacuous_claims_ts`.

- [ ] **Step 3: Write the TypeScript analyzer**

Create `scripts/detect_vacuous_claims_ts.ts`:

```ts
/**
 * Find TypeScript assertions that can pass without observing anything.
 *
 * Same rule as scripts/detect_vacuous_claims.py, one language over:
 * `for (const x of xs)` with an assert inside, and `assert(xs.every(...))`,
 * both report success when `xs` is empty. A literal array cannot be empty;
 * `.filter(...)` and a directory read can.
 *
 * Witnesses bind to the expression, not to the test: `assert.ok(a.length)`
 * says nothing about `b`.
 */

import fs from "node:fs";
import path from "node:path";

import ts from "typescript";

export interface TsVacuousClaim {
  path: string;
  line: number;
  scope: string;
  iterable: string;
  kind: string;
  key: string;
}

const DISCOVERY_METHODS = new Set(["readdirSync", "globSync", "matchAll"]);
const EMPTIABLE_METHODS = new Set(["filter", "flatMap", "match"]);

const text = (node: ts.Node, source: ts.SourceFile): string =>
  node.getText(source).replace(/\s+/g, " ").trim();

const classify = (
  node: ts.Expression,
  source: ts.SourceFile,
  bindings: Map<string, string>,
): string | null => {
  if (ts.isCallExpression(node) && ts.isPropertyAccessExpression(node.expression)) {
    const method = node.expression.name.text;
    if (DISCOVERY_METHODS.has(method)) return "discovery call";
    if (EMPTIABLE_METHODS.has(method)) return `${method} call`;
  }
  if (ts.isIdentifier(node)) return bindings.get(node.text) ?? null;
  if (ts.isArrayLiteralExpression(node)) return null;
  return null;
};

/** Collect `const xs = <emptiable>` bindings, innermost scope wins. */
const collectBindings = (source: ts.SourceFile): Map<string, string> => {
  const bindings = new Map<string, string>();
  const visit = (node: ts.Node): void => {
    if (ts.isVariableDeclaration(node) && ts.isIdentifier(node.name) && node.initializer) {
      const kind = classify(node.initializer, source, bindings);
      if (kind !== null) bindings.set(node.name.text, `local ${kind}`);
    }
    ts.forEachChild(node, visit);
  };
  visit(source);
  return bindings;
};

/** Expressions proven non-empty: `assert…(xs.length …)` in any form. */
const collectWitnesses = (source: ts.SourceFile): Set<string> => {
  const witnesses = new Set<string>();
  const visit = (node: ts.Node): void => {
    if (ts.isCallExpression(node) && /^assert/.test(node.expression.getText(source))) {
      for (const argument of node.arguments) {
        const walk = (inner: ts.Node): void => {
          if (
            ts.isPropertyAccessExpression(inner) &&
            inner.name.text === "length" &&
            ts.isExpressionStatement(inner.parent) === false
          ) {
            witnesses.add(text(inner.expression, source));
          }
          ts.forEachChild(inner, walk);
        };
        walk(argument);
      }
    }
    ts.forEachChild(node, visit);
  };
  visit(source);
  return witnesses;
};

/** True when falling out of the loop throws instead of continuing. */
const exhaustionThrows = (loop: ts.ForOfStatement): boolean => {
  const parent = loop.parent;
  if (!parent || !ts.isBlock(parent)) return false;
  const index = parent.statements.indexOf(loop as ts.Statement);
  const next = index >= 0 ? parent.statements[index + 1] : undefined;
  return next !== undefined && ts.isThrowStatement(next);
};

const enclosingName = (node: ts.Node, source: ts.SourceFile): string => {
  let current: ts.Node | undefined = node;
  while (current) {
    if (ts.isCallExpression(current) && current.expression.getText(source) === "test") {
      const first = current.arguments[0];
      if (first && ts.isStringLiteralLike(first)) return first.text;
    }
    current = current.parent;
  }
  return "<module>";
};

export const scanSource = (sourceText: string, filePath: string): TsVacuousClaim[] => {
  const source = ts.createSourceFile(filePath, sourceText, ts.ScriptTarget.Latest, true);
  const bindings = collectBindings(source);
  const witnesses = collectWitnesses(source);
  const claims: TsVacuousClaim[] = [];

  const record = (expression: ts.Expression, node: ts.Node): void => {
    const iterable = text(expression, source);
    if (witnesses.has(iterable)) return;
    const kind = classify(expression, source, bindings);
    if (kind === null) return;
    const scope = enclosingName(node, source);
    const line = source.getLineAndCharacterOfPosition(node.getStart(source)).line + 1;
    claims.push({
      path: filePath,
      line,
      scope,
      iterable,
      kind,
      key: `${path.basename(filePath)}::${scope}::${iterable}`,
    });
  };

  const hasAssert = (node: ts.Node): boolean => {
    let found = false;
    const walk = (inner: ts.Node): void => {
      if (ts.isCallExpression(inner) && /^assert/.test(inner.expression.getText(source))) {
        found = true;
      }
      ts.forEachChild(inner, walk);
    };
    walk(node);
    return found;
  };

  const visit = (node: ts.Node): void => {
    if (ts.isForOfStatement(node) && hasAssert(node.statement) && !exhaustionThrows(node)) {
      record(node.expression, node);
    }
    if (ts.isCallExpression(node) && /^assert/.test(node.expression.getText(source))) {
      for (const argument of node.arguments) {
        if (
          ts.isCallExpression(argument) &&
          ts.isPropertyAccessExpression(argument.expression) &&
          argument.expression.name.text === "every"
        ) {
          record(argument.expression.expression, node);
        }
      }
    }
    ts.forEachChild(node, visit);
  };
  visit(source);
  return claims;
};

export const scanDir = (dir: string): { files: string[]; claims: TsVacuousClaim[] } => {
  const files = fs
    .readdirSync(dir)
    .filter((name) => name.endsWith(".test.ts"))
    .sort();
  const claims = files.flatMap((name) =>
    scanSource(fs.readFileSync(path.join(dir, name), "utf-8"), name),
  );
  return { files, claims };
};
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
cd /Users/spreuss/Documents/skipp-algo-wt-vacuity
npx tsx --test automation/tradingview/tests/vacuous_claims_ts.test.ts
```

Expected: the seven shape tests and the scan witness pass. `no unexempted vacuous claims` will likely fail with a real baseline — triage it exactly as in Task 5 (fix / declare with a dated reason in `TS_VACUITY_EXEMPTIONS` / sharpen the analyzer with a new shape test). Do not widen the exemption map to make it green.

- [ ] **Step 5: Register the test in all three required places**

In `.github/workflows/tv-onboarding-packages.yml`:

1. Append ` automation/tradingview/tests/vacuous_claims_ts.test.ts` to the `run:` line of the step "Test hermetic TV pins".
2. Add `      - "automation/tradingview/tests/vacuous_claims_ts.test.ts"` to the `push:` `paths:` list.
3. Add the same line to the `pull_request:` `paths:` list.

Also add `      - "scripts/detect_vacuous_claims_ts.ts"` to both `paths:` lists, so a change to the analyzer triggers its own test.

- [ ] **Step 6: Verify the registration guards agree**

```bash
cd /Users/spreuss/Documents/skipp-algo-wt-vacuity
PYTEST_XDIST_AUTO_NUM_WORKERS=4 PYTHONPATH=. /Users/spreuss/Documents/skipp-algo/.venv/bin/python -m pytest \
  tests/test_fast_gates_silent_skip_coverage.py -v
PYTEST_XDIST_AUTO_NUM_WORKERS=4 PYTHONPATH=. /Users/spreuss/Documents/skipp-algo/.venv/bin/python -m pytest tests/ -k workflow
```

Expected: green. `test_every_ts_test_is_gated_or_exempt` and `test_gated_ts_tests_trigger_their_own_workflow` are the two that fail if a registration place was missed.

- [ ] **Step 7: Commit, push, PR**

```bash
cd /Users/spreuss/Documents/skipp-algo-wt-vacuity
npm run tv:test
git add scripts/detect_vacuous_claims_ts.ts automation/tradingview/tests/vacuous_claims_ts.test.ts \
  .github/workflows/tv-onboarding-packages.yml
git commit -m "feat(tv): gate vacuum-prone assertions in the TypeScript tests" -m "Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

Push in the background, open the PR via `Documents/skipp-algo:skipp-pr-flow`. **Do not merge without an explicit signal from the user.**

---

### Task 7: `assertNoVisibleChartScriptError` must not read "unreadable" as "clean"

> **Present this task to the user before writing any code.** It changes behaviour on the live operator publish path — a publish that used to proceed will now fail when the legend cannot be read. That is a decision, not a bugfix, and it gets its own PR and its own signal.

**Files:**
- Modify: `automation/tradingview/lib/tv_shared.ts` (`assertNoVisibleChartScriptError`, around line 8257)
- Test: `automation/tradingview/tests/tv_chart_error_probe.test.ts` (already gated in CI — no registration work)

**Interfaces:**
- Consumes: `probeVisibleChartScriptError(page, scriptName): Promise<string | typeof CHART_ERROR_PROBE_UNREADABLE | null>` and `CHART_ERROR_PROBE_UNREADABLE` — both already exported from `tv_shared.ts` (around lines 8197 and 8216).
- Produces: no signature change. `assertNoVisibleChartScriptError(page, scriptName): Promise<void>` keeps its shape and gains a fail-closed branch.

**Context for the implementer:** the tri-state already exists and the runtime-smoke caller (around line 8720) handles `CHART_ERROR_PROBE_UNREADABLE` explicitly. `getVisibleChartScriptError` (line ~8252) is the documented flat view and its own docstring says *"this must NOT be used by anything that gates on a clean compile — use the probe."* `assertNoVisibleChartScriptError`, directly below it, does exactly that. Its only production caller is `scripts/tv_publish_openprep_panel.ts:198`, so the openprep publish path currently reports "no chart error" when the legend was merely unreadable. The fix is small and local: gate on the probe, treat unreadable as failure. `getVisibleChartScriptError` itself stays as-is — it is a documented convenience view with a correct warning.

- [ ] **Step 1: Present and get the signal**

Summarise for the user: what changes (openprep publish fails instead of proceeding when the chart legend cannot be read), why (a gate that cannot look must not report clean), the blast radius (one caller), and the alternative (leave it, keep the silent pass). Wait for an explicit go.

- [ ] **Step 2: Write the failing test**

Read `automation/tradingview/tests/tv_chart_error_probe.test.ts` first and reuse the fake-`Page` factory it already defines — keep its existing name and shape rather than adding a second one. Then append, substituting that factory for `makeFakePage`:

```ts
test("assertNoVisibleChartScriptError fails when the legend cannot be read", async () => {
  // An unreadable surface is not a clean surface. The gate must refuse to
  // certify what it could not look at.
  const page = makeFakePage({ legendReadable: false });
  await assert.rejects(
    () => assertNoVisibleChartScriptError(page, "smc_openprep_panel"),
    /unreadable|could not read/i,
  );
});

test("assertNoVisibleChartScriptError passes on a readable, error-free legend", async () => {
  const page = makeFakePage({ legendReadable: true, errorText: null });
  await assert.doesNotReject(() =>
    assertNoVisibleChartScriptError(page, "smc_openprep_panel"),
  );
});
```

- [ ] **Step 3: Run the test to verify it fails**

```bash
cd /Users/spreuss/Documents/skipp-algo-wt-vacuity
npx tsx --test automation/tradingview/tests/tv_chart_error_probe.test.ts
```

Expected: the first new test FAILS — the current implementation resolves instead of rejecting.

- [ ] **Step 4: Implement the fail-closed gate**

Replace `assertNoVisibleChartScriptError` in `automation/tradingview/lib/tv_shared.ts`:

```ts
export async function assertNoVisibleChartScriptError(page: Page, scriptName: string): Promise<void> {
  // Gate on the probe, not on getVisibleChartScriptError: that view maps
  // "could not look" to null, so a publish would certify a compile it never
  // observed. Its own docstring says not to use it for gating.
  const probed = await probeVisibleChartScriptError(page, scriptName);
  if (probed === CHART_ERROR_PROBE_UNREADABLE) {
    throw new Error(
      `Chart legend unreadable for ${scriptName}: refusing to report a clean compile from a surface that could not be read.`,
    );
  }
  if (probed) {
    throw new Error(`Visible chart error detected for ${scriptName}: ${probed}`);
  }
}
```

- [ ] **Step 5: Run the tests to verify they pass**

```bash
cd /Users/spreuss/Documents/skipp-algo-wt-vacuity
npx tsx --test automation/tradingview/tests/tv_chart_error_probe.test.ts
npm run tv:test
```

Expected: both new tests pass, no other TS test regresses.

- [ ] **Step 6: Commit, push, PR**

```bash
cd /Users/spreuss/Documents/skipp-algo-wt-vacuity
git add automation/tradingview/lib/tv_shared.ts automation/tradingview/tests/tv_chart_error_probe.test.ts
git commit -m "fix(tv): fail the openprep publish gate when the chart legend is unreadable" -m "Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

The PR description names the behaviour change on the first line and the single affected caller (`scripts/tv_publish_openprep_panel.ts:198`). **Do not merge without an explicit signal from the user.**

---

## Self-Review Notes

- **Spec coverage:** §3.1 emptiability → Task 1; §3.2 witness-per-iterable → Task 2; §3.3 false positives (frozen-site idiom, partial vacuity, per-iterable binding) → Task 2 + Task 5 "sharpen"; §3.4/§9.3 parametrize → Task 3; §4/§9.2 registration surfaces → Task 4 Step 5; §5 module design, dataclass, four witness forms, exemption registry, self-witness, stale exemptions → Tasks 1–4; §6 task cut → Tasks 1–7; §7 constraints → Global Constraints; §9.4 corrected TS finding → Task 7; §9.5 TS sizing → Task 6.
- **Deliberate deviation from §3.1:** the analyzer also treats `assert all(...)` / `assert not any(...)` as iterating assertions, and deliberately does **not** treat a bare `assert any(...)` as one (`any(())` is `False`, which fails loudly). The prototype's `(all/any)` kind labels lumped these together.
- **Known consequence to accept, not to "fix":** cross-test witnesses are invisible to the analyzer by design (§9.3), so every parametrize case healed with a `test_<ledger>_roster_is_not_empty` also needs a dated exemption naming that test. That is the archive-gate pattern from §5, not a gap.
- **Numbers to re-measure, never to carry over:** 29/17 (loops) and 9/8 (parametrize) come from throwaway prototypes with known false positives. Tasks 1, 4 and 5 each re-measure and record their own figures.

---

## Corrections found while executing this plan (2026-08-03)

The plan was executed task-by-task with a review after each. **Five defects were found in this plan's own reference code.** They are recorded here because anyone re-reading the code blocks above would otherwise rebuild them.

1. **Task 2's `witness_keys` renders with `ast.unparse` while the iterable is rendered from the source segment.** `ast.unparse` normalizes string quoting, so `ROOT.glob("*.py")` becomes `ROOT.glob('*.py')` and the two sides of the comparison can never be equal. Every witness would silently fail to match and the guard would flag correctly witnessed loops. Neither task's own fixtures catch it, because each exercises one side only. **Both sides must go through one renderer.** The shipped code uses a module-private `_render`, documented as the single renderer for anything compared or used as identity.

2. **Task 3's `_parametrize_argvalues` accepts only `FunctionDef | AsyncFunctionDef`,** so `@pytest.mark.parametrize` on a *class* is never inspected. pytest applies a class-level parametrize to every method in the class. A real instance exists (`tests/test_newsstack_retry_after_hygiene.py`). The shipped code walks `ClassDef.decorator_list` and attributes the claim once to the class.

3. **Task 2's `_raises_or_fails` uses `ast.unparse(...).endswith("fail")`,** which matches any call whose text ends in "fail" — `logger.softfail(...)`, `report_fail(...)`. Such a call next to a loop would fabricate an exhaustion witness and silently suppress a real claim. The shipped code requires an exact `.fail` attribute call.

4. **Task 2's `witness_keys` collects every `assert` in the function with no reachability filter,** so an assert inside `if`, inside a neighbouring `for`, or inside `with pytest.raises(...)` all count as witnesses. The third is a polarity inversion: an assertion *expected to fail* read as proof of non-emptiness. The shipped code scopes witnesses to the claim's own block and enclosing blocks. Note that the obvious fix — a flat "must be at function top level" filter — was tried first and produced two false positives on live code.

5. **Task 6's TypeScript `collectWitnesses` treats every `.length` as a witness.** `assert.equal(wrappers.length, 0, …)` exists in this suite (`tv_shared.test.ts:1162`), so a collection proven **empty** would have exonerated a loop over it — the plan's sketch would have built the exact bug the tool exists to prevent. The shipped code accepts a length comparison only when it implies a count of at least one.

Two further plan-level problems, both about scope claims rather than code:

6. **Task 5 Step 2 under-scopes the production measurement.** It says to scan `scripts/ services/` and call that "production Python". The repo has 13 further production packages. Measured across the whole tree: **1133 files, 0 claims** (2758 total `.py` = 1625 under `tests/` + 1133 production, nothing uncovered). The conclusion survived; the scope claim did not.

7. **`VacuousClaim.key` omits `kind`,** so one test producing both a loop claim and a parametrize claim over identically rendered text would collide under a single registry key and one exemption would waive both. The key format was kept (it is the documented registry schema) and a `test_claim_keys_are_unique` was added instead, so a collision is loud rather than a silent over-waiver.

**What the plan got right and should be reused:** the three-verdict triage (*fix* / *declare* / *sharpen*, never silencing a false positive with an exemption), the dated-exemption registry with a stale-exemption check, and the demand that the guard carry its own witness. On that last point the plan under-specified in an interesting way: `assert len(scanned) > 1_000` turned out to be the *weaker* of the two channels. The stale-exemption test is what actually closes the hole, because a classifier that stopped classifying leaves all 13 exemptions unmatched and goes red.
