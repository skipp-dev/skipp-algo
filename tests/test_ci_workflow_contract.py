"""Contract pin: ``ci.yml`` workflow (Bundle D-2 from issue #2422).

Pins the structural invariants of the main CI workflow so silent drift
of the trigger surface, the event gate, runner policy, or pytest lane
selection is caught at validate-time.

Note: since 2026-08-27 the four ``validate (N)`` shard contexts ARE
required on main (ADR-0012 Operator-Punkt 1, ``main-governance``
ruleset) alongside ``fast-gates``. The invariants pinned here therefore
protect an enforcing gate, not just the audit trail.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from tests._fast_gates_gate import gh_was_called, run_ci_gate

_REPO_ROOT = Path(__file__).resolve().parents[1]
_WF_PATH = _REPO_ROOT / ".github" / "workflows" / "ci.yml"


def _load() -> dict:
    return yaml.safe_load(_WF_PATH.read_text(encoding="utf-8"))


def _condition(raw: object) -> str:
    """A step condition, normalised for the differences that carry no meaning.

    Collapses whitespace (so a YAML fold cannot fail a pin) and strips an
    optional ``${{ }}`` wrapper, which GitHub accepts either way on ``if:`` and
    requires on ``cancel-in-progress``. Both were measured on 2026-08-04 to
    break a raw-equality pin without changing what the workflow does.

    What is NOT normalised: the order and the presence of operands. Those carry
    the meaning, and an equality pin over them is the point — a substring pin
    here survived ``&& false`` appended to the coverage lane and ``|| true``
    appended to ``cancel-in-progress``, both of which change the workflow
    materially while leaving every test in this file green.

    The remaining false-positive is a semantically equal REORDERING of
    conjuncts. That is rare enough to accept the failure and cheap enough to
    fix in the same commit; the durable answer is evaluating the expression the
    way ``tests/test_fast_gates_attested_pine_coverage.py`` does, which belongs
    in the shared harness rather than a third copy here.
    """
    text = " ".join(str(raw).split())
    if text.startswith("${{") and text.endswith("}}"):
        text = text[3:-2].strip()
    return text


def _on(data: dict) -> dict:
    # PyYAML parses bare ``on`` as boolean True.
    return data.get("on") or data.get(True)


def test_workflow_file_exists() -> None:
    assert _WF_PATH.is_file(), f"missing workflow: {_WF_PATH}"


def test_live_window_marker_any_trigger() -> None:
    head = _WF_PATH.read_text(encoding="utf-8").splitlines()[0]
    assert "live-window: any-trigger" in head, (
        "first-line live-window marker required by F-V6-F2.1"
    )


def test_triggers_pinned() -> None:
    on_block = _on(_load())
    assert set(on_block.keys()) == {"push", "pull_request", "workflow_dispatch"}, (
        "ci.yml trigger surface drifted; expected push + pull_request + workflow_dispatch"
    )
    assert on_block["push"].get("branches-ignore") == ["data/**"], (
        "push must cover all branches EXCEPT data/** — Orphan-Datenbaeume "
        "(stuendliche c13-Snapshots) tragen einen eingefrorenen Code-Schnappschuss, "
        "dessen Datums-Anker dort nie wieder heilen koennen "
        "(failed-runs-Triage 2026-08-25)"
    )
    assert "branches" not in on_block["push"], (
        "branches und branches-ignore schliessen sich in Actions aus; ein "
        "wieder eingefuegtes branches wuerde die data/**-Ausnahme still kippen"
    )
    paths_ignore = on_block["pull_request"].get("paths-ignore", [])
    assert "**/*.md" in paths_ignore and "docs/**" in paths_ignore, (
        "doc-only PR short-circuit must keep ignoring **/*.md and docs/** "
        "(F-V8-C5-A, 2026-05-07)"
    )


def test_concurrency_cancel_only_for_pr() -> None:
    """Push runs are the audit trail and must never be cancelled.

    Asserted by EQUALITY, not by substring. ``"… == 'pull_request'" in cond``
    is satisfied by ``… == 'pull_request' || true``, which cancels every push
    run. Measured 2026-08-04: that mutation left every test in this file green
    while the audit trail became interruptible.
    """
    data = _load()
    concurrency = data["concurrency"]
    assert concurrency["group"].startswith("ci-")
    cancel = _condition(concurrency["cancel-in-progress"])
    assert cancel == "github.event_name == 'pull_request'", (
        "cancel-in-progress must remain exactly the PR-only expression; push "
        f"runs are audit trail. Found: {cancel!r}. If this is being changed on "
        "purpose, change it here in the same commit — an added disjunct is how "
        "it would silently start cancelling pushes."
    )


def test_pythonunbuffered_env_pinned() -> None:
    data = _load()
    assert data["env"].get("PYTHONUNBUFFERED") == "1", (
        "F-V5-A2 (2026-05-01) requires PYTHONUNBUFFERED=1"
    )
    assert "PYTHONPATH" in data["env"]


def test_single_validate_job_with_event_gate() -> None:
    data = _load()
    assert list(data["jobs"].keys()) == ["validate"], (
        "ci.yml must expose exactly one job named ``validate`` "
        "(this name is also a status-check context candidate; see PR #2427)"
    )
    job = data["jobs"]["validate"]
    # 2026-08-20: aus der glatten 45 wurde ein Ausdruck mit ZWEI Kappen —
    # 15 min fuer die PR-Lane, 45 min fuer die main-Lane. Beide Zahlen sind in
    # tests/test_ci_workflow_structural_pin.py::test_timeout_minutes_caps_both_lanes
    # einzeln gepinnt; hier genuegt, dass ueberhaupt eine Kappe steht (ohne sie
    # gilt der GHA-Default von 6 h).
    assert str(job["timeout-minutes"]).strip() != ""
    gate_step = next(
        (s for s in job["steps"] if s.get("id") == "gate"), None
    )
    assert gate_step is not None, "validate gate step missing"
    # What the gate DECIDES is asserted by executing it, in
    # test_the_gate_decides_by_event_not_by_the_words_in_its_source below.
    # Matching phrases in its source cannot tell "returns false for a pull
    # request" from "contains the sentence 'Pull request CI is status-only'".
    # The fall-through below stays a source assertion on purpose: it is a claim
    # about the step's SHAPE — that no arm was appended after the last one —
    # and executing it could only ever cover the events the test thought to try.
    #
    # The gate's LAST word must be the expensive one. Anything the arms above do
    # not claim — an event this workflow does not declare today, or a trigger
    # added later — has to run the full suite rather than skip it in silence.
    assert gate_step["run"].rstrip().endswith(
        'echo "run_heavy=true" >> "$GITHUB_OUTPUT"'
    ), (
        "the gate no longer falls through to run_heavy=true. An unhandled event "
        "would then skip the repo's only full-suite run without saying so."
    )


# What used to stand here: three assertions pinning a ``bot/*`` path allow-list
# in this gate -- ``bot/*``, ``.filename``, ``run_heavy=$heavy``. That block was
# UNREACHABLE and was removed on 2026-08-04. ci.yml triggers on push,
# pull_request and workflow_dispatch only, and each exits in one of the four arms
# above; measured by executing the block for all three, plus a hypothetical
# merge_group, before and after removal -- identical verdicts in all seven cases.
#
# Those assertions were worse than dead weight: they read as "ci.yml path-checks
# bot PRs", and a maintainer could reasonably conclude bot PRs get a narrower
# lane here. They never did. In ci.yml ALL pull requests are status-only, bot or
# not, and the file-level protection is the outcome witnesses in
# tests/test_fast_gates_silent_skip_coverage.py, which execute this gate rather
# than reading it.


def test_runs_on_uses_github_hosted_var() -> None:
    job = _load()["jobs"]["validate"]
    assert "SMC_GH_HOSTED_RUNNER" in job["runs-on"], (
        "runner policy 2026-05-20: CI must default to GitHub-hosted via "
        "vars.SMC_GH_HOSTED_RUNNER (fallback ubuntu-latest)"
    )
    assert "ubuntu-latest" in job["runs-on"], "fallback ubuntu-latest required"


def test_two_pytest_invocation_lanes_present() -> None:
    """Coverage-on-main and no-coverage PR/non-main are distinct gates."""
    steps = _load()["jobs"]["validate"]["steps"]
    runs = [s.get("run", "") for s in steps if "pytest" in s.get("run", "")]
    assert len(runs) == 2, (
        f"expected exactly 2 pytest lanes (no-cov, with-cov); got {len(runs)}"
    )
    joined = "\n".join(runs)
    assert "--testmon" not in joined, "testmon must stay out of merge-critical validate lanes"
    assert "--cov" in joined and "--cov-report=term-missing:skip-covered" in joined, (
        "coverage lane removed or report format changed"
    )
    assert joined.count("-n auto --dist=loadscope --splits 4 --group") == 1, (
        "xdist parallelism should remain only on the main coverage lane"
    )
    assert joined.count("--splits 4 --group") == 2, "pytest-split sharding dropped from validate lanes"


def test_coverage_lane_gated_on_main_push_only() -> None:
    """Coverage runs on main push only — pinned by EQUALITY, not by substring.

    ``"… == 'push'" in cond`` survives ``cond && false``, which disables the
    lane outright. Measured 2026-08-04: that mutation left every test in this
    file green while coverage stopped running anywhere. Both lanes are pinned
    whole, so a lost conjunct, an added one, or a swapped comparison all fail.
    """
    steps = _load()["jobs"]["validate"]["steps"]
    cov_step = next(s for s in steps if "--cov" in s.get("run", ""))
    cond = _condition(cov_step["if"])
    assert cond == (
        "steps.gate.outputs.run_heavy == 'true' && github.event_name == 'push' "
        "&& github.ref == 'refs/heads/main'"
    ), (
        "coverage must only run on main push; otherwise the PR feedback loop "
        f"slows. Found: {cond!r}"
    )

    no_cov = next(
        s
        for s in steps
        if "pytest" in s.get("run", "") and "--cov" not in s.get("run", "")
    )
    other = _condition(no_cov["if"])
    assert other == (
        "steps.gate.outputs.run_heavy == 'true' && (github.event_name == "
        "'pull_request' || github.ref != 'refs/heads/main')"
    ), (
        "the no-coverage lane must stay the exact complement of the coverage "
        f"lane, or some event runs both lanes or neither. Found: {other!r}"
    )


def test_the_gate_decides_by_event_not_by_the_words_in_its_source(
    tmp_path: Path,
) -> None:
    """Execute the gate for every pinned trigger and pin the verdict it writes.

    This replaces a block of substring assertions on the step's source. Those
    could not distinguish "makes this decision" from "contains this sentence";
    measured 2026-08-04, three separate mutations to what this file claims to
    guard each left all nine of its tests green.

    The policy pinned here (2026-08-20): pull requests run heavy — the slow
    complement, so the lane can become a required check without being vacuous —
    non-main pushes stay status-only, main pushes and manual dispatches run
    heavy. Executed through the shared harness in ``tests/_fast_gates_gate.py``
    rather than a second local copy — one gate, one harness.
    """
    cases = {
        ("pull_request", "feature"): "true",
        ("push", "feature"): "false",
        ("push", "main"): "true",
        ("workflow_dispatch", "main"): "true",
    }
    for index, ((event, ref), expected) in enumerate(cases.items()):
        work = tmp_path / f"case{index}"
        work.mkdir()
        outputs = run_ci_gate(work, event_name=event, ref_name=ref)
        assert outputs["run_heavy"] == expected, (
            f"{event} on {ref!r} wrote run_heavy={outputs['run_heavy']!r}, "
            f"expected {expected!r}"
        )


def test_no_branch_name_buys_a_different_verdict(tmp_path: Path) -> None:
    """No branch name buys a different verdict, and nothing calls ``gh``.

    Until #4396 this gate carried a ``bot/*`` path allow-list that inspected the
    PR's changed files. It was UNREACHABLE — every declared event returned at an
    earlier arm — and the previous version of this file pinned its presence as
    an "Audit P2 HIGH" invariant, which read as evidence of a check that could
    not run. #4396 deleted the arm; this pins the behaviour that replaced it, so
    the allow-list cannot return unexamined.

    The second half is MEASURED, not inferred. Until 2026-08-20 it read: a
    ``gh`` that cannot list the PR's files would take a fail-closed branch and
    write ``run_heavy=true``, so a verdict of ``false`` proved the gate never
    called ``gh``. Since pull requests now legitimately return ``true``, that
    discriminator tells the two cases apart no longer — both sides look the
    same. The stubbed ``gh`` therefore leaves a trace and the test reads it.
    """
    source_path = tmp_path / "source"
    source_path.mkdir()
    bot_pr = run_ci_gate(
        source_path,
        event_name="pull_request",
        ref_name="feature",
        head_ref="bot/library-refresh-1094-1",
        changed_files=["src/smc_integration/engine.py"],
    )
    assert bot_pr["run_heavy"] == "true", (
        "a bot/* pull request came back with a verdict of its own; the branch "
        "name is deciding pull requests again"
    )
    assert not gh_was_called(source_path), (
        "the gate invoked `gh`; a path allow-list is inspecting pull requests "
        "again (the arm #4396 removed as unreachable)"
    )

    broken_gh = tmp_path / "broken_gh"
    broken_gh.mkdir()
    fail_closed = run_ci_gate(
        broken_gh,
        event_name="pull_request",
        ref_name="feature",
        head_ref="bot/library-refresh-1094-1",
        changed_files=["src/smc_integration/engine.py"],
        gh_exit_code=1,
    )
    assert fail_closed["run_heavy"] == "true", (
        "a failing `gh` changed the verdict, so the gate is calling `gh` on "
        "pull requests again; see above"
    )
    assert not gh_was_called(broken_gh), (
        "the gate invoked `gh` even with it broken -- the verdict happening to "
        "match is not evidence that it did not"
    )


def test_the_pull_request_lane_runs_only_the_slow_complement() -> None:
    """Ohne Marker liefe hier die volle Suite und doppelte die schnelle Lane.

    ADR-0012 Option B teilt die Suite exakt: gemessen 2026-08-20 sind es
    5480 (not slow) + 20428 (slow) = 25908 = die ganze Suite. ``fast-gates``
    faehrt die Nicht-slow-Haelfte, diese Lane den Rest. Faellt das ``-m slow``
    weg, wiederholt jeder der ~36 PRs pro Tag die 5480 der schnellen Lane --
    reine Rechenzeit ohne zusaetzliches Signal, und das Actions-Budget ist ein
    dokumentierter Ausfallgrund (einmal alles rot).

    Die Mutationsprobe zu diesem Test fand die Luecke: das Entfernen des
    Markers liess vorher alle 50 Tests der drei Wach-Dateien gruen.

    Die main-Push-Lane bleibt ABSICHTLICH ungefiltert -- sie erzeugt das
    Coverage-Artefakt ueber die ganze Suite und ist kein Gate.
    """
    data = _load()
    steps = data["jobs"]["validate"]["steps"]

    def _step(name_fragment: str) -> dict:
        found = [s for s in steps if name_fragment in str(s.get("name", ""))]
        assert len(found) == 1, f"{name_fragment!r} matcht {len(found)} Schritte"
        return found[0]

    # Kommentarzeilen ausschliessen: die Schritte BESCHREIBEN ihren Aufruf im
    # Kommentar darueber, und ein blosses `"pytest" in ln` trifft die
    # Beschreibung statt des Verhaltens (beim ersten Lauf dieses Tests genau so
    # passiert). Gefiltert wird auf die Aufruf-Form, nicht auf das Wort.
    def _invocations(block: str) -> list[str]:
        return [
            ln for ln in block.splitlines()
            if "python -m pytest" in ln and not ln.lstrip().startswith("#")
        ]

    pr_lane = _step("(PR / non-main push")["run"]
    invocations = _invocations(pr_lane)
    assert invocations, "die PR-Lane hat keinen pytest-Aufruf mehr"
    for line in invocations:
        args = line.split("pytest", 1)[1]
        assert "-m slow" in args, (
            "die PR-Lane faehrt nicht mehr nur das slow-Komplement; ohne den "
            "Marker wiederholt sie die kuratierte fast-gates-Menge auf jedem "
            f"PR.\n  Zeile: {line.strip()}"
        )

    main_lane = _step("(main push")["run"]
    main_calls = _invocations(main_lane)
    assert main_calls, "die main-Lane hat keinen pytest-Aufruf mehr"
    for line in main_calls:
        args = line.split("pytest", 1)[1]
        assert "-m slow" not in args, (
            "die main-Push-Lane misst Coverage ueber die GANZE Suite; ein "
            "slow-Filter dort halbierte das Audit-Artefakt stillschweigend."
        )
