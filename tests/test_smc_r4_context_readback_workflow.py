"""Contract for the ``smc-r4-context-readback`` workflow.

This workflow can drive a real TradingView account: at ``mutating`` execution
mode it creates or saves scripts and modifies a chart layout. The properties
pinned here are the ones that keep that safe, and every one of them is a
property that would be silently lost by an ordinary-looking edit:

* it must stay dispatch-only — an accidental ``schedule:`` or ``push:`` would
  mutate the account unattended;
* readonly must stay the DEFAULT, so the invasive mode is always a choice;
* it must share the TradingView concurrency group, because parallel runs fight
  over one account, one layout and the same saved scripts;
* it must not hold write permissions it does not need;
* the session must come from the ``TV_STORAGE_STATE`` secret, never a
  checked-in credential.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from tests._workflow_yaml import load_workflow

_WORKFLOW = (
    Path(__file__).resolve().parents[1]
    / ".github"
    / "workflows"
    / "smc-r4-context-readback.yml"
)


@pytest.fixture(scope="module")
def workflow() -> dict:
    assert _WORKFLOW.exists(), f"missing workflow: {_WORKFLOW}"
    return load_workflow(_WORKFLOW)


def _on_block(workflow: dict) -> dict:
    # PyYAML parses the bare `on:` key as the boolean True.
    on = workflow.get("on", workflow.get(True))
    assert isinstance(on, dict), "workflow has no parsed on-block"
    return on


def test_workflow_is_dispatch_only(workflow: dict) -> None:
    """A TradingView-mutating workflow must never fire on its own."""
    on = _on_block(workflow)
    assert set(on) == {"workflow_dispatch"}, (
        "smc-r4-context-readback may only run on manual dispatch; it can write "
        f"to a live TradingView account. Found triggers: {sorted(on)}"
    )


def test_readonly_is_the_default_execution_mode(workflow: dict) -> None:
    inputs = _on_block(workflow)["workflow_dispatch"]["inputs"]
    mode = inputs["execution_mode"]
    assert mode["default"] == "readonly"
    assert set(mode["options"]) == {"readonly", "mutating"}


def test_runs_are_serialised_against_every_other_tradingview_job(workflow: dict) -> None:
    concurrency = workflow["concurrency"]
    assert concurrency["group"] == "tradingview-session"
    # Cancelling mid-run can leave a half-modified layout behind.
    assert concurrency["cancel-in-progress"] is False


def test_workflow_holds_no_write_permission(workflow: dict) -> None:
    assert workflow["permissions"] == {"contents": "read"}


def test_python_output_is_unbuffered(workflow: dict) -> None:
    assert workflow["env"]["PYTHONUNBUFFERED"] == "1"


def test_session_comes_from_the_secret_and_records_its_authorization(
    workflow: dict,
) -> None:
    steps = workflow["jobs"]["readback"]["steps"]
    names = [step.get("name", "") for step in steps]
    assert "Write TradingView storage state" in names
    assert "Record what this run was authorized to do" in names

    write_step = next(s for s in steps if s.get("name") == "Write TradingView storage state")
    assert write_step["env"]["TV_STORAGE_STATE_SECRET"] == "${{ secrets.TV_STORAGE_STATE }}"

    auth_step = next(
        s for s in steps if s.get("name") == "Record what this run was authorized to do"
    )
    # The R2.4/R4 evidence artifacts record these two as explicitly withheld;
    # a CI-driven session must not quietly grant itself more.
    assert '"publicationAllowed": False' in auth_step["run"]
    assert '"alertCreationAllowed": False' in auth_step["run"]


def test_python_interpreter_is_resolved_before_anything_uses_it(workflow: dict) -> None:
    """``$SMC_PYTHON_BIN`` must be exported before the first step that runs it.

    ``setup-python-pinned`` installs the interpreter but exports no path. Run
    30683157375 expanded the variable to the empty string and the storage-state
    heredoc died with exit 127. It survived review because the step before it,
    ``uv pip install --python "$SMC_PYTHON_BIN"``, tolerated the empty value and
    reported success — so "the earlier Python step was green" proves nothing.
    """
    steps = workflow["jobs"]["readback"]["steps"]
    setter = next(
        (
            i
            for i, s in enumerate(steps)
            if "SMC_PYTHON_BIN=" in s.get("run", "") and "GITHUB_ENV" in s.get("run", "")
        ),
        None,
    )
    assert setter is not None, "no step exports SMC_PYTHON_BIN"

    users = [i for i, s in enumerate(steps) if "$SMC_PYTHON_BIN" in s.get("run", "")]
    # Floor: if nothing used the variable this rule would pass on nothing.
    assert users, "no step uses SMC_PYTHON_BIN — this pin is measuring nothing"
    assert min(users) > setter, (
        f"step {min(users)} uses $SMC_PYTHON_BIN before step {setter} exports it"
    )


def test_the_mutating_path_persists_and_is_re_read_by_a_separate_process(
    workflow: dict,
) -> None:
    """A rebind that is not saved, and not re-read fresh, proves nothing.

    ``tv_preflight.ts`` contains zero ``saveChangedChartLayout`` call sites, so
    running it in mutating mode rebinds inside its own session and discards the
    result — a green 62/62 that persists nothing. The rebind therefore goes
    through ``tv_batch_consumer_rollout.ts`` (which saves per layout), and the
    preflight that follows must run READONLY so it is an independent re-read in
    a fresh process rather than a second mutation.
    """
    steps = workflow["jobs"]["readback"]["steps"]
    names = [s.get("name", "") for s in steps]

    rebind_idx = names.index("Rebind the overlay and SAVE the layout (mutating only)")
    preflight_idx = names.index("Run TradingView preflight")
    assert rebind_idx < preflight_idx, "the re-read must follow the rebind"

    rebind = steps[rebind_idx]
    assert rebind["if"] == "inputs.execution_mode == 'mutating'"
    assert "tv_batch_consumer_rollout.ts" in rebind["run"]
    assert "tv_preflight.ts" not in rebind["run"], (
        "tv_preflight never saves the layout — it cannot be the rebind tool"
    )
    # Without this the plan resolves to repairBindings=false, saveLayout=false
    # and the step silently degrades into a no-op verify.
    assert rebind["env"]["TV_FORCE_REBIND"] == "true"

    preflight = steps[preflight_idx]
    assert "--execution-mode readonly" in preflight["run"], (
        "the verification pass must be readonly, otherwise a mutating dispatch "
        "mutates twice and never independently confirms the save"
    )


def test_the_rebind_config_saves_producer_before_consumer(workflow: dict) -> None:
    """Owner authorised the source save on 2026-08-01 — with a required order.

    Until then ``saveTargets`` was empty, on the premise that the TradingView
    sources were current. Run 30694013096 disproved it: the rebind died with
    "Source combobox not found for CTX SessionMssBull" because the saved
    overlay is still pre-#4263 and has no such input.

    The producer must be saved FIRST. The saved BUS is pre-#4263 too, so the
    two new CTX outputs do not exist until it is saved and its chart instance
    re-applied — and an input cannot be bound to an output that is not there.
    Reversing this order reproduces exactly the failure above, one level down.
    """
    inputs = _on_block(workflow)["workflow_dispatch"]["inputs"]
    config_path = Path(__file__).resolve().parents[1] / inputs["rebind_config"]["default"]
    config = json.loads(config_path.read_text(encoding="utf-8"))

    sources = [t["source"] for t in config["saveTargets"]]
    assert sources == ["SMC_Context_Bus.pine", "SMC_Context_Overlay.pine"], (
        "the R4 rebind saves exactly the two Context sources, producer first; "
        f"found {sources}"
    )

    steps = workflow["jobs"]["readback"]["steps"]
    rebind = next(
        s for s in steps if s.get("name", "").startswith("Rebind the overlay and SAVE")
    )
    assert rebind["env"]["TV_REFRESH_PRODUCER"] == "true", (
        "saving the BUS source leaves the ALREADY APPLIED instance on the old "
        "version, still exposing the old outputs; without the refresh the "
        "overlay's new inputs have nothing to bind to"
    )

    assert "repairE2ETarget" not in config, (
        "the repair drill deliberately drifts a binding first — not on a shadow "
        "layout being brought up to contract"
    )
    assert config["producerName"] == "SMC Context Bus"
    # Floor: an empty verifyTargets would make the rollout a no-op that still
    # reports success.
    assert config["verifyTargets"], "nothing would be rebound"
    for target in config["verifyTargets"]:
        assert "bindingLabels" not in target, (
            "labels must be parsed from the Pine source so the rebind follows "
            "the current contract instead of a frozen list"
        )


def test_evidence_is_uploaded_even_when_the_run_fails(workflow: dict) -> None:
    """A failed TradingView run is exactly when the screenshots matter."""
    steps = workflow["jobs"]["readback"]["steps"]
    upload = next(s for s in steps if s.get("name") == "Upload readback evidence")
    assert upload["if"] == "always()"
    assert "screenshots" in upload["with"]["path"]


# ---------------------------------------------------------------------------
# 2026-08-03: this workflow is a SECOND caller of tv_batch_consumer_rollout.ts
# (the first is tv-save-consumer-source.yml). It had none of that workflow's
# operator-window gate or out-of-band-drift baseline, and its proof step
# (preflight) was skipped by the very rebind failure it exists to catch —
# the shape of run 30700389375, which left a managed layout broken for 67
# minutes because the repair step was skipped by the failure it existed to
# handle. These tests pin the four properties that close that gap.
# ---------------------------------------------------------------------------

_GATE = "Refuse to mutate inside the operator's TradingView window"
_BASELINE_FETCH = "Fetch the published R4 binding baseline"
_REBIND = "Rebind the overlay and SAVE the layout (mutating only)"
_PUBLISH = "Publish latest R4 binding snapshot"
_PREFLIGHT = "Run TradingView preflight"


def test_operator_window_gate_exists_is_mutating_only_and_precedes_node_setup(
    workflow: dict,
) -> None:
    """A refusal must cost seconds, not a Playwright install, and must never
    suppress the readonly path (which writes nothing and stays safe
    regardless of the operator's claimed window)."""
    steps = workflow["jobs"]["readback"]["steps"]
    names = [s.get("name", "") for s in steps]
    assert _GATE in names, f"missing step: {_GATE}"
    assert names.index("Checkout") < names.index(_GATE) < names.index("Set up Node")
    # It must also precede the pinned-Python setup: that step still costs a
    # real download, and check_tv_operator_window.py needs nothing from it
    # (stdlib only), so there is no reason for a refusal to pay for it.
    assert names.index(_GATE) < names.index("Set up pinned Python")

    gate = next(s for s in steps if s.get("name") == _GATE)
    # Exact equality, not substring: this workflow's dispatch input is read
    # as `inputs.execution_mode`, not `github.event.inputs.execution_mode`
    # (see the existing "Rebind" step) — an edit that silently drifted the
    # accessor style, or inverted mutating/readonly, must fail here.
    assert gate["if"] == "inputs.execution_mode == 'mutating'"
    assert gate["env"]["TV_OPERATOR_ACTIVE"] == "${{ vars.TV_OPERATOR_ACTIVE }}"
    assert gate["run"].strip() == "python3 -m scripts.check_tv_operator_window"


def test_baseline_fetch_precedes_the_rebind_and_targets_the_r4_specific_path(
    workflow: dict,
) -> None:
    """R4 runs a DIFFERENT config against DIFFERENT verify targets than
    tv-save-consumer-source.yml's consumer-rollout, so comparing against
    THAT workflow's published snapshot would always read "unknown" — it
    never measured R4's targets. The fetch must target R4's own path, not
    the consumer-rollout one."""
    steps = workflow["jobs"]["readback"]["steps"]
    names = [s.get("name", "") for s in steps]
    assert _BASELINE_FETCH in names, f"missing step: {_BASELINE_FETCH}"
    assert names.index(_BASELINE_FETCH) < names.index(_REBIND)

    fetch = next(s for s in steps if s.get("name") == _BASELINE_FETCH)
    # Mutating only: a readonly dispatch never reaches the rebind step, so
    # nothing on that path would ever read the fetched file.
    assert fetch["if"] == "inputs.execution_mode == 'mutating'"
    assert "artifacts/monitoring/previous/tradingview_r4_context_bindings.json" in fetch["run"]
    assert "artifacts/monitoring/latest/tradingview_r4_context_bindings.json" in fetch["run"]
    assert "bot/live-tradingview-bindings" in fetch["run"]
    # Must NOT be the consumer-rollout path — that would silently compare R4
    # against a snapshot that never observed R4's targets.
    assert "tradingview_consumer_bindings.json" not in fetch["run"]


def test_a_missing_r4_baseline_warns_and_leaves_no_file_instead_of_failing(
    workflow: dict, tmp_path: Path
) -> None:
    """The first run (and any run before one has published) must not fail
    the step that has measured nothing — it is the "unknown" verdict,
    decided downstream by the rollout script, not a fetch-time error. This
    is also the honest-red bootstrap noted on the fetch step's comment:
    the mutating run's report.ok goes red on out-of-band drift == unknown
    until the first successful publish, which is expected, not a defect.

    Actually executes the extracted script (not a substring grep) so a
    differently-spelled failure (`exit 2`, `false`, a typo'd flag) would be
    caught rather than passed by a text match on "exit 1".
    """
    steps = workflow["jobs"]["readback"]["steps"]
    step = next(s for s in steps if s.get("name") == _BASELINE_FETCH)
    script = step["run"]

    mock_gh_dir = tmp_path / "mock_bin"
    mock_gh_dir.mkdir()
    mock_gh = mock_gh_dir / "gh"
    mock_gh.write_text("#!/bin/bash\nexit 1\n", encoding="utf-8")
    mock_gh.chmod(0o755)

    work_dir = tmp_path / "work"
    work_dir.mkdir()

    env = os.environ.copy()
    env["PATH"] = str(mock_gh_dir) + ":" + env.get("PATH", "")
    env["GH_TOKEN"] = "fake-token"
    env["GH_REPO"] = "fake/repo"

    result = subprocess.run(
        ["bash", "-c", script],
        cwd=work_dir,
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, f"Script failed with exit code {result.returncode}: {result.stderr}"
    assert "::warning::" in result.stdout, f"No warning found in stdout: {result.stdout}"
    baseline_file = work_dir / "artifacts/monitoring/previous/tradingview_r4_context_bindings.json"
    assert not baseline_file.exists(), f"Baseline file should not exist when fetch fails, but found: {baseline_file}"


def test_rebind_step_has_an_id_and_passes_the_r4_baseline_flag(workflow: dict) -> None:
    """Wiring: the fetched baseline reaches the CLI, and the step gets an
    `id:` — the publish and preflight steps below both need to read its
    `.conclusion`, which is unavailable on an unnamed step."""
    steps = workflow["jobs"]["readback"]["steps"]
    rebind = next(s for s in steps if s.get("name") == _REBIND)
    assert rebind.get("id") == "rebind"
    assert "--baseline artifacts/monitoring/previous/tradingview_r4_context_bindings.json" in rebind["run"]
    # The rollout writes its report to this --out path; that IS the snapshot
    # the publish step below pushes — not a second, separately-tracked file.
    assert "--out artifacts/tradingview/r4_rebind_rollout.json" in rebind["run"]


def test_publish_step_targets_the_r4_specific_path_and_skips_a_gate_blocked_run(
    workflow: dict,
) -> None:
    """A gate-blocked (or readonly) run must not republish stale content.

    Exact equality on the `if:`, not substring containment: a flipped
    operator (OR instead of AND, or always() with no conclusion check at
    all) would let a run with nothing fresh on disk force-push over the
    last real observation, and a substring check on a fragment of the
    condition would not catch that inversion.
    """
    steps = workflow["jobs"]["readback"]["steps"]
    names = [s.get("name", "") for s in steps]
    assert _PUBLISH in names, f"missing step: {_PUBLISH}"
    assert names.index(_REBIND) < names.index(_PUBLISH)

    publish = next(s for s in steps if s.get("name") == _PUBLISH)
    expected_if = "${{ always() && (steps.rebind.conclusion == 'success' || steps.rebind.conclusion == 'failure') }}"
    assert publish["if"] == expected_if
    # 'skipped' (readonly dispatch, or the operator-window gate refused) and
    # 'cancelled' are excluded by this condition — neither produced a fresh
    # snapshot, so publishing then would push stale or absent content.
    assert "'skipped'" not in publish["if"]

    assert "artifacts/tradingview/r4_rebind_rollout.json" in publish["run"]
    assert '"${stable_dir}/tradingview_r4_context_bindings.json"' in publish["run"]
    assert "bot/live-tradingview-bindings" in publish["run"]
    assert "force-with-lease" in publish["run"]
    assert publish["env"]["GH_TOKEN"] == "${{ secrets.GH_PAT }}"
    # Must not collide with tv-save-consumer-source.yml's published path —
    # that is exactly the "always unknown" trap this whole change avoids.
    assert "tradingview_consumer_bindings.json" not in publish["run"]


def test_publish_step_seeds_the_shared_directory_before_adding_its_own_file(
    workflow: dict,
) -> None:
    """artifacts/monitoring/latest/ on bot/live-tradingview-bindings is
    SHARED: tv-save-consumer-source.yml already publishes
    tradingview_consumer_bindings.json there, and live_overlay_daemon polls
    it in production (services/live_overlay_daemon/config.py,
    TRADINGVIEW_BINDINGS_SNAPSHOT_URL). A fresh `actions/checkout` does not
    carry that directory at all — it exists only on the bot branch — so a
    publish step that stages only its own new file would, on commit, make
    that the ENTIRE directory, deleting the sibling producer's file the
    moment the commit becomes the branch tip (ADR-0024 §5: a shared-branch
    publisher "must seed from the fetched remote tip and replace only their
    own owned paths").

    Pins the two properties that prevent that: the fetch happens BEFORE the
    directory is populated, and the fetched tip is checked out into the
    stable dir before this run's own file is copied in and the whole
    directory (not just one path) is staged.
    """
    publish = next(
        s for s in workflow["jobs"]["readback"]["steps"] if s.get("name") == _PUBLISH
    )
    run = publish["run"]

    fetch_idx = run.index("git fetch")
    seed_idx = run.index('git checkout "${expected_sha}" -- "${stable_dir}"')
    copy_idx = run.index('cp "${snapshot}"')
    add_idx = run.index("git add -f")
    commit_idx = run.index("git commit")

    assert fetch_idx < seed_idx < copy_idx < add_idx < commit_idx, (
        "the tip must be fetched, then checked out into the shared "
        "directory, BEFORE this run's own file overlays it and the "
        "directory is staged — any other order can commit a directory "
        "missing the sibling producer's file"
    )
    # The whole directory is staged, not one explicit filename — that is
    # what carries the seeded sibling file into this run's commit.
    assert 'git add -f "${stable_dir}"' in run
    assert 'git add -f "${stable_dir}/tradingview_r4_context_bindings.json"' not in run


def test_preflight_proof_step_still_runs_when_the_rebind_step_failed(
    workflow: dict,
) -> None:
    """2026-08-03 (Finding, run-30700389375-shaped): the proof step used to
    have no `if:` at all, which GitHub Actions treats as an implicit
    `success()` — so a rebind that mutated and then FAILED skipped the one
    step that could prove whether the layout it just touched was left
    broken. The next process to look would have been the next dispatch, not
    this run.

    Exact equality on the condition, not substring containment: a
    plausible-looking `always()` would pass a substring check for
    "steps.rebind.conclusion == 'failure'" while ALSO firing after an
    earlier setup step failed (no storage state, no browser dependencies —
    nothing to read with), which is precisely what must stay excluded.
    """
    steps = workflow["jobs"]["readback"]["steps"]
    names = [s.get("name", "") for s in steps]
    assert names.index(_REBIND) < names.index(_PREFLIGHT)

    preflight = next(s for s in steps if s.get("name") == _PREFLIGHT)
    expected_if = "${{ !cancelled() && (success() || steps.rebind.conclusion == 'failure') }}"
    assert preflight["if"] == expected_if
    assert "always()" not in preflight["if"]
