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


def test_the_rebind_config_pushes_no_pine_source(workflow: dict) -> None:
    """The rebind may touch bindings and the layout — not the saved sources."""
    inputs = _on_block(workflow)["workflow_dispatch"]["inputs"]
    config_path = Path(__file__).resolve().parents[1] / inputs["rebind_config"]["default"]
    config = json.loads(config_path.read_text(encoding="utf-8"))

    assert config["saveTargets"] == [], (
        "a non-empty saveTargets would push Pine sources to TradingView, which "
        "is a far larger action than the binding repair this run is for"
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
