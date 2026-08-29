"""Run the fast-gates path-classification step instead of reading its text.

``smc-fast-pr-gates.yml``'s ``gate`` step decides two things for a ``bot/*``
PR: whether the heavy suite runs (``run_heavy``) and whether the R1-attested-
source guard runs (``run_pine_guard``). Both are decided in shell, and a test
that asserts on the shell's *source text* cannot tell "publishes the output"
from "publishes it as ``false`` forever".

That is not hypothetical. Measured 2026-08-04, twice on this one step:

* deleting ``*.pine|pine/generated/*) pine=true ;;`` left all fourteen tests in
  ``test_check_r1_attested_sources.py`` green while the R1 guard went blind
  again — the defect #4376 had just fixed, reintroduced under a passing suite
  (closed by #4377);
* deleting the ``*)`` arm that sets ``heavy=true`` left 2198 tests green under
  ``-k "fast_gates or workflow or r1_attested"``, and 202 green across the 14
  test files that name this workflow — while a ``bot/*`` PR touching
  ``services/*.py`` would merge without the heavy suite at all, verbatim the
  hole the step's own comment claims to have closed. (Two selections, two
  numbers, both measured; neither is "the whole suite".)

So execute the step. This module is the shared harness; the assertions live
next to the workflow they describe — ``test_fast_gates_silent_skip_coverage.py``
(the silent-skip contract), ``test_check_r1_attested_sources.py`` and
``test_fast_gates_attested_pine_coverage.py`` (the R1 half), and
``test_ci_workflow_contract.py`` for ci.yml's gate.

GitHub's ``if:`` expression evaluation is covered too, by
:func:`evaluate_condition` below. It was lifted in here from
``tests/test_fast_gates_attested_pine_coverage.py`` on 2026-08-04 when a second
consumer appeared; ten test modules import it today. Copying it would have left
two evaluators to drift apart, and a private helper imported across test modules
is exactly what broke ``main`` that same day, when #4383 moved ``_run_gate`` out
from under #4385.

(Until 2026-08-07 the two paragraphs above said the evaluator lives OUTSIDE this
module and invited a third consumer to lift it in. Both were already false when
written: the file that supposedly owned it imports it from here.)
"""

from __future__ import annotations

import ast
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "smc-fast-pr-gates.yml"

# The shell GitHub really gives this block. smc-fast-pr-gates.yml declares
# `defaults: run: shell: bash`, which Actions expands to
# `bash --noprofile --norc -eo pipefail {0}` -- NOT the implicit default
# (`bash -e {0}`, no pipefail). test_the_harness_matches_the_declared_shell pins
# BOTH sides -- the workflow's declaration and this tuple -- because pinning only
# the declaration leaves the tuple free to drift, and a review measured exactly
# that: gutting it to ("bash", "-e") killed no test.
#
# `bash` resolves through PATH, so locally this is the developer's bash (3.2 on
# stock macOS) while CI runs 5.x. Every construct in the block is 3.2-safe; the
# skew can only cause a local false alarm, never a green local run that fails CI.
SHELL = ("bash", "--noprofile", "--norc", "-e", "-o", "pipefail")

# The path-inspection branch is unreachable for anything else, and this is the
# branch shape #4371 actually used.
BOT_BRANCH = "bot/library-refresh-30861895594-1"


# Everything the harness feeds the step besides PATH and GITHUB_OUTPUT. Kept as
# a module constant so a test can compare it against the step's own `env:` block
# -- the step runs under `-e` but NOT `-u`, so a variable the workflow adds and
# this dict does not expands to "" in silence, and a shape like
# `[[ -n "$NEW_FLAG" ]]` would then classify differently here than in CI without
# anything going red.
HARNESS_ENV: dict[str, str] = {
    "EVENT_NAME": "pull_request",
    "HEAD_REF": BOT_BRANCH,
    "PR_NUMBER": "4371",
    "REPO": "skipp-dev/skipp-algo",
    "GH_TOKEN": "stub-token",
}


def gate_step() -> dict:
    """The whole ``gate`` step, read structurally out of the workflow.

    Loaded through the YAML rather than sliced out of the text, so indentation,
    comment and ordering churn cannot break it -- and a missing step id is a
    named failure rather than a silently empty script.
    """
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    for step in workflow["jobs"]["fast-gates"]["steps"]:
        if step.get("id") == "gate":
            return dict(step)
    raise AssertionError("fast-gates has no step with id 'gate'")


def gate_run_block() -> str:
    """The ``gate`` step's shell."""
    return str(gate_step()["run"])


# --- ci.yml's own gate ------------------------------------------------------
#
# The same shape, one workflow over: `validate` has an `id: gate` step whose
# run_heavy output every later step hangs on -- including the full pytest run.
# Its contract is pinned in test_ci_workflow_contract.py by source text, and a
# mutation sweep on 2026-08-04 showed what that cannot see: flipping the
# main-push arm from `run_heavy=true` to `false` killed NO test, because the
# string `run_heavy=true` still appears in another arm. Deletions are caught,
# inversions are not.
CI_WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"

# Mirrors the `env:` block of that step, and nothing more. It once also carried
# HEAD_REF/PR_NUMBER/REPO/GH_TOKEN, for the bot-path arm #4396 removed as
# unreachable; keeping scaffolding named after deleted logic is how a harness
# starts describing a workflow that no longer exists. `run_ci_gate` still ACCEPTS
# a head_ref and a file list, but as probe input rather than as scaffolding — see
# its docstring.
CI_HARNESS_ENV: dict[str, str] = {
    "EVENT_NAME": "push",
    "REF_NAME": "main",
}


def ci_gate_step() -> dict:
    """The ``gate`` step of ci.yml's ``validate`` job."""
    workflow = yaml.safe_load(CI_WORKFLOW.read_text(encoding="utf-8"))
    for step in workflow["jobs"]["validate"]["steps"]:
        if step.get("id") == "gate":
            return dict(step)
    raise AssertionError("ci.yml's validate job has no step with id 'gate'")


def run_ci_gate(
    tmp_path: Path,
    *,
    event_name: str,
    ref_name: str,
    head_ref: str = "",
    changed_files: list[str] | None = None,
    gh_exit_code: int = 0,
) -> dict[str, str]:
    """Execute ci.yml's gate and return what it wrote to GITHUB_OUTPUT.

    ``head_ref``, ``changed_files`` and ``gh_exit_code`` describe inputs this
    gate does NOT read: #4396 deleted its ``bot/*`` path allow-list as
    unreachable. They are kept as probe input, not as leftover scaffolding —
    ``test_a_bot_pull_request_is_status_only_like_any_other`` feeds a bot branch,
    a source path and a failing ``gh``, and the verdict staying ``false`` is what
    proves the allow-list has not come back. Pass them only to make that point;
    a test that supplies them incidentally implies a path check that ci.yml does
    not perform.
    """
    return _run_step_shell(
        str(ci_gate_step()["run"]),
        tmp_path,
        env={
            **CI_HARNESS_ENV,
            "EVENT_NAME": event_name,
            "REF_NAME": ref_name,
            "HEAD_REF": head_ref,
        },
        changed_files=changed_files or [],
        gh_exit_code=gh_exit_code,
    )


def run_gate(
    changed_files: list[str],
    tmp_path: Path,
    *,
    head_ref: str = BOT_BRANCH,
    event_name: str = "pull_request",
    gh_exit_code: int = 0,
) -> dict[str, str]:
    """Execute the fast-gates gate against a stubbed ``gh``; return its outputs.

    ``gh_exit_code`` drives the fail-closed path: the step must fall back to the
    heavy suite when it cannot list the PR's files, rather than skip on a branch
    name alone.
    """
    return _run_step_shell(
        gate_run_block(),
        tmp_path,
        env={**HARNESS_ENV, "EVENT_NAME": event_name, "HEAD_REF": head_ref},
        changed_files=changed_files,
        gh_exit_code=gh_exit_code,
    )


# Aufrufspur je Lauf, damit `gh_was_called()` sie lesen kann.
_GH_TRACE_BY_TMP: dict[Path, Path] = {}


def gh_was_called(tmp_path: Path) -> bool:
    """Hat der ausgefuehrte Schritt das gestubbte ``gh`` angefasst?"""
    trace = _GH_TRACE_BY_TMP.get(tmp_path)
    return bool(trace and trace.exists() and trace.read_text().strip())


def _run_step_shell(
    run_block: str,
    tmp_path: Path,
    *,
    env: dict[str, str],
    changed_files: list[str],
    gh_exit_code: int,
) -> dict[str, str]:
    """Run one workflow step's shell with a stubbed ``gh``; return its outputs."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    stub = bin_dir / "gh"
    # printf over the list rather than a heredoc: a heredoc delimiter can be
    # collided with by a changed path that happens to equal it, and this
    # harness's whole job is to not have blind spots of that shape.
    quoted = " ".join(shlex.quote(path) for path in changed_files)
    # Der Stub hinterlaesst eine SPUR. Bis 2026-08-20 wurde "der Gate ruft kein
    # `gh`" darueber bewiesen, dass ein fehlschlagendes `gh` den fail-closed
    # Zweig (run_heavy=true) genommen haette und das Urteil trotzdem `false`
    # blieb. Seit pull_request regulaer `true` liefert, unterscheidet dieser
    # Diskriminator NICHTS mehr -- beide Seiten sehen gleich aus. Die Spur
    # ersetzt ihn durch eine direkte Messung.
    trace = tmp_path / "gh_calls"
    body = f"#!/bin/sh\necho called >> {shlex.quote(str(trace))}\n"
    body += (
        f"printf '%s\\n' {quoted}\nexit {gh_exit_code}\n" if changed_files
        else f"exit {gh_exit_code}\n"
    )
    stub.write_text(body, encoding="utf-8")
    stub.chmod(0o755)

    github_output = tmp_path / "github_output"
    github_output.write_text("", encoding="utf-8")
    _GH_TRACE_BY_TMP[tmp_path] = trace

    result = subprocess.run(
        [*SHELL, "-c", run_block],
        # Deliberately not `{**os.environ, ...}`: `bash -c` sources BASH_ENV
        # even under --noprofile --norc, so a developer's shell could change
        # what this measures. PATH is kept (with the stub in front) because the
        # step legitimately needs to find `gh` and bash itself.
        env={
            **env,
            "PATH": f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}",
            "GITHUB_OUTPUT": str(github_output),
        },
        capture_output=True,
        text=True,
        # The step is pure path classification; anything slower is a hang, and
        # a hang here would burn the job's whole timeout instead of failing.
        timeout=60,
    )
    # The step names the arm it took on stdout; stderr alone identifies nothing.
    assert result.returncode == 0, (
        f"the step exited {result.returncode}\n"
        f"--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}"
    )

    return dict(
        line.split("=", 1)
        for line in github_output.read_text(encoding="utf-8").splitlines()
        if "=" in line
    )


# --- the `if:` half ---------------------------------------------------------
#
# Executing a `run:` block says what the step COMPUTES. It says nothing about
# whether the step runs at all -- that is the `if:`, and it is a separate blind
# spot with its own history: #4376's finding was that the R1 guard was skipped
# because the CHECKOUT was skipped, and the test that was supposed to catch it
# read `"run_pine_guard" in condition`, which any mention satisfies.
#
# Lifted here from tests/test_fast_gates_attested_pine_coverage.py on
# 2026-08-04 when a second consumer appeared, exactly as this module's own
# docstring instructs -- copying it would have left two evaluators to drift
# apart, and a private helper imported across test modules is what broke `main`
# earlier the same day.

def step_conditions(workflow: Path | None = None, job: str = "fast-gates") -> dict[str, str]:
    """Every step's ``if:`` expression in one job, keyed by step name.

    Defaults to ``fast-gates`` so the two callers that predate the second
    workflow keep reading unchanged. ``c13-daily-cron.yml`` needs the same
    thing for a six-step advisory chain, and reproducing this four-line read
    beside it is how two copies start drifting.
    """
    doc = yaml.safe_load((workflow or WORKFLOW).read_text(encoding="utf-8"))
    return {
        str(step.get("name")): _unwrap(str(step.get("if", "")))
        for step in doc["jobs"][job]["steps"]
        if isinstance(step, dict)
    }


def _unwrap(expression: str) -> str:
    """Strip the optional ``${{ … }}`` around a condition.

    Actions treats `if: a == 'b'` and `if: ${{ a == 'b' }}` identically, and
    both spellings are in use — `ml-family-research.yml` and
    `rl-research-training.yml` wrap theirs. Left in, the braces are an
    unreadable token and the evaluator refuses the condition, which would look
    like an unsupported expression rather than a formatting difference.
    """
    stripped = expression.strip()
    if stripped.startswith("${{") and stripped.endswith("}}"):
        return stripped[3:-2].strip()
    return stripped


# The subset of GitHub's expression grammar the two conditions below use:
# parentheses, `&&`, `||`, `==`/`!=`, single-quoted literals, and context
# references. Anything else raises rather than evaluating to something —
# a step condition this cannot read is a condition this test cannot vouch for,
# and reporting green on it would be the vacuity being removed here.
# The trailing `-` in the identifier class is load-bearing: GitHub job ids may
# contain hyphens, and this workflow has one (`needs.select-runner.outputs.…`).
# Without it the tokenizer stops mid-reference and the condition is rejected as
# unreadable rather than evaluated.
_EXPRESSION_TOKEN = re.compile(r"\s*(\(|\)|&&|\|\||==|!=|'[^']*'|[A-Za-z_][A-Za-z0-9_.-]*)")


class _GhNull:
    """Der Wert, den GitHub fuer den Output eines UEBERSPRUNGENEN Steps liefert.

    Kein leerer String: ``steps.<id>.outputs.<name>`` eines uebersprungenen
    Steps ist ``null``, und GitHubs lose Gleichheit castet bei ungleichen Typen
    nach Zahl — ``null`` -> 0 und ``'0'`` -> 0, also ist
    ``steps.uebersprungen.outputs.rc == '0'`` **wahr**.

    Das ist nicht aus der Doku abgeleitet, sondern GEMESSEN: in Lauf
    33216084496 (c13-daily-cron, 2026-08-28) war ``drift_input`` skipped und
    Step 3 — dessen einziges Gate ``steps.drift_input.outputs.rc == '0'`` ist —
    lief trotzdem; ebenso liefen 4b/5a/5b/5c hinter dem uebersprungenen
    ``drift``. Dieser Evaluator modellierte den Fall vorher als leeren String
    und verglich ihn als String, konnte das Leck also strukturell nicht sehen.
    """

    def __repr__(self) -> str:  # pragma: no cover - Diagnose-Hilfe
        return "<GitHub null (skipped step)>"


SKIPPED = _GhNull()


def _as_number(value: object) -> float | None:
    """GitHubs Zahl-Cast fuer die lose Gleichheit; None = NaN (nie gleich)."""
    if isinstance(value, _GhNull):
        return 0.0
    if value == "":
        return 0.0
    try:
        return float(str(value))
    except ValueError:
        return None


def _gh_equals(left: object, right: object) -> bool:
    """Lose Gleichheit wie GitHub sie auswertet.

    Gleiche Typen (hier: zwei Strings) vergleichen als String. Sobald eine
    Seite ``null`` ist — der Fall eines uebersprungenen Steps — castet GitHub
    BEIDE Seiten nach Zahl. Ein nicht-numerischer String wird dabei zu NaN und
    ist mit nichts gleich, auch nicht mit sich selbst.
    """
    if isinstance(left, _GhNull) or isinstance(right, _GhNull):
        links, rechts = _as_number(left), _as_number(right)
        if links is None or rechts is None:
            return False
        return links == rechts
    return left == right


def evaluate_condition(
    expression: str,
    outputs: dict[str, object],
    *,
    event_name: str = "pull_request",
    contexts: dict[str, str] | None = None,
) -> bool:
    """Evaluate a step's ``if:`` against real gate outputs.

    Deliberately does NOT short-circuit: both sides of every ``&&`` / ``||``
    are evaluated, so an operand this evaluator does not understand raises even
    when the other side already decided the verdict. A silent skip is what is
    being tested for; it must not be how the test itself behaves.

    ``outputs`` accepts either shape: bare keys (``{"run_heavy": "true"}``) for
    a condition that names one step, or step-qualified keys
    (``{"backfill.rc": "0", "drift.outcome": "failure"}``) for a chain whose
    conditions name several. Qualified wins where both exist.

    ``contexts`` supplies values for references outside ``steps.*`` -- currently
    only ``needs.select-runner.outputs.runner_environment``. An unlisted
    reference raises rather than defaulting, for the same reason: a reference
    this evaluator guesses at is a verdict it cannot vouch for.
    """
    contexts = contexts or {}
    tokens: list[str] = []
    position = 0
    expression = expression.strip()
    assert expression, (
        "the step carries no `if:` at all, so it runs unconditionally. That "
        "passes the coverage direction below for the wrong reason and fails "
        "the control direction; give it a condition or drop it from this test."
    )
    while position < len(expression):
        match = _EXPRESSION_TOKEN.match(expression, position)
        assert match is not None, (
            f"cannot read the step condition from offset {position}: "
            f"{expression[position:]!r}. This evaluator covers the expression "
            "shapes fast-gates uses today; extend it in the PR that introduces "
            "a new one rather than letting this assertion pass unparsed."
        )
        tokens.append(match.group(1))
        position = match.end()

    index = 0

    def peek() -> str | None:
        return tokens[index] if index < len(tokens) else None

    def take() -> str:
        nonlocal index
        assert index < len(tokens), f"the condition ends mid-expression: {expression!r}"
        token = tokens[index]
        index += 1
        return token

    def operand() -> str:
        token = take()
        if token.startswith("'"):
            return token[1:-1]
        if token.startswith("steps.") and ".outputs." in token:
            # An output the step never wrote is "" in GitHub too, which is what
            # makes `== 'true'` false for a flag the step stopped publishing.
            #
            # Two key shapes, because there are now two kinds of caller. A
            # single-step gate passes `{"run_heavy": "true"}` and its condition
            # only ever names one step. A chain — c13's six advisory steps —
            # has conditions that name several, so it passes
            # `{"backfill.rc": "0", "drift.rc": "4"}` and the bare name would be
            # ambiguous. The qualified key wins; the bare one stays for the
            # single-step callers.
            _, step_id, _, key = token.split(".", 3)
            # Ein uebersprungener Step hat KEINE Outputs — jede Lesung daran
            # ist `null`, nicht "". Wer `{"drift.outcome": "skipped"}` angibt,
            # bekommt das fuer alle Outputs dieses Steps automatisch; so muss
            # kein Aufrufer die Coercion-Regel selbst kennen.
            if outputs.get(f"{step_id}.outcome") == "skipped":
                return SKIPPED
            if f"{step_id}.{key}" in outputs:
                return outputs[f"{step_id}.{key}"]
            return outputs.get(key, "")
        if token.startswith("steps.") and token.endswith(".outcome"):
            # `outcome` is not an output — it is whether the step's shell
            # exited non-zero, which is exactly what running the block
            # measures. c13's six warn steps are gated on nothing else, so
            # without this they could not be asserted about at all.
            return outputs.get(token.split(".", 1)[1], "")
        if token == "github.event_name":
            return event_name
        if token in contexts:
            return contexts[token]
        raise AssertionError(
            f"the step condition reads {token!r}, which this evaluator cannot "
            "resolve. Teach it that context in the same PR — an unresolved "
            "operand silently decides the verdict otherwise."
        )

    def comparison() -> bool:
        # `always()` is a bare boolean term, not the left side of a comparison.
        # Steps that render or upload the gate report carry `always() && …` so
        # they still run after a failure; without this the evaluator would raise
        # on them and they could never be asserted about at all.
        if peek() == "always":
            take()
            assert take() == "(" and take() == ")", (
                f"expected `always()` in {expression!r}"
            )
            return True
        if peek() == "(":
            take()
            value = disjunction()
            closing = take()
            assert closing == ")", f"unbalanced parentheses in {expression!r}"
            return value
        left = operand()
        operator = take()
        right = operand()
        if operator == "==":
            return _gh_equals(left, right)
        if operator == "!=":
            return not _gh_equals(left, right)
        raise AssertionError(f"unsupported operator {operator!r} in {expression!r}")

    def conjunction() -> bool:
        value = comparison()
        while peek() == "&&":
            take()
            value = comparison() and value
        return value

    def disjunction() -> bool:
        value = conjunction()
        while peek() == "||":
            take()
            value = conjunction() or value
        return value

    verdict = disjunction()
    assert index == len(tokens), (
        f"trailing tokens {tokens[index:]} in {expression!r}; the condition was "
        "only partly evaluated"
    )
    return verdict


# --- the "installs nothing" half --------------------------------------------
#
# The pine-only lane skips every Python setup step, so a guard it shells must
# import stdlib and repo-local modules only. `test_check_r1_attested_sources.py`
# has enforced that for the R1 guard since 2026-08-04. On 2026-08-13 #4668 put
# a SECOND guard on the same lane (scripts/check_customer_surface_vocabulary.py)
# with no such test, so the walker is lifted here rather than copied -- same
# reasoning as evaluate_condition above.


def repo_module_path(dotted: str) -> Path | None:
    """The file a dotted name resolves to inside this repo, or None."""
    candidates = (
        ROOT / f"{dotted.replace('.', '/')}.py",
        ROOT / dotted.replace(".", "/") / "__init__.py",
    )
    return next((c for c in candidates if c.exists()), None)


def module_level_imports(path: Path) -> set[str]:
    """Imports that execute when the module is imported.

    Excludes two kinds that cannot break a bare interpreter: everything inside
    ``if TYPE_CHECKING:`` (deferred to strings by ``from __future__ import
    annotations``) and everything inside a function or class body (only paid if
    that code runs). ``try:`` blocks ARE descended into -- a module-level
    ``try: import x`` still executes.
    """
    imported: set[str] = set()

    def visit(body: list[ast.stmt]) -> None:
        for node in body:
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                # `level > 0` is a relative import: repo-local by construction.
                if node.module and node.level == 0:
                    imported.add(node.module)
            elif isinstance(node, ast.If):
                test = node.test
                name = getattr(test, "id", None) or getattr(test, "attr", None)
                if name != "TYPE_CHECKING":
                    visit(node.body)
                visit(node.orelse)
            elif isinstance(node, ast.Try):
                visit(node.body)
                visit(node.orelse)
                visit(node.finalbody)
                for handler in node.handlers:
                    visit(handler.body)

    visit(ast.parse(path.read_text(encoding="utf-8")).body)
    return imported


def third_party_import_chain(entry: str) -> dict[str, str]:
    """Every non-stdlib, non-repo module reachable at import time from ``entry``.

    Empty means the bare-interpreter lane can run it. The mapping is
    ``imported module -> the repo module that imports it`` so a failure names
    the edge to fix, not just the offender.
    """
    pending = [entry]
    seen: set[str] = set()
    third_party: dict[str, str] = {}

    while pending:
        dotted = pending.pop()
        if dotted in seen:
            continue
        seen.add(dotted)
        path = repo_module_path(dotted)
        if path is None:
            continue
        for imported in module_level_imports(path):
            if repo_module_path(imported) is not None:
                pending.append(imported)
            elif imported.split(".")[0] not in sys.stdlib_module_names:
                third_party[imported] = dotted

    return third_party
