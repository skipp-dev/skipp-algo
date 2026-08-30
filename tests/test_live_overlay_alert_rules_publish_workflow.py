"""Structural pin for ``.github/workflows/live-overlay-alert-rules-publish.yml``.

References the exact hyphenated basename ``live-overlay-alert-rules-publish`` so
the orphan-workflow inventory (tests/test_workflow_orphan_inventory.py) stays
closed. Mirrors tests/test_live_overlay_dashboard_publish_workflow.py.

The structural pins below say which strings the upsert step contains. They
cannot say what it decides, and on 2026-08-04 a sweep measured the difference:
inverting

    if [[ "${dry_run}" == "true" ]]; then   ->   if [[ "${dry_run}" == "false" ]]

leaves every assertion in ``test_upsert_step_contract`` green -- none of the
five names that line -- while every push to ``main`` exits before the upsert.
Committed alert-rule changes would stop reaching Grafana entirely, which is
verbatim the gap this workflow's own header says it was built to close. The
same one-token edit makes a manual ``dry_run=true`` perform a real network
upsert instead.

This file is on the required lane (``tests/_fast_inventory.py``), so that PR
would have merged green. The ``test_upsert_executes_*`` tests below run the
step's shell against a stubbed ``python`` and assert on what it actually
invoked.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from tests._workflow_step_shell import BASH, declares_bash_default, run_step

REPO_ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = "live-overlay-alert-rules-publish.yml"
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / WORKFLOW
ALERT_RULES = "services/live_overlay_daemon/infra/grafana/alert-rules.yaml"
UPSERT_STEP = "Upsert alert rules (or dry-run)"
UPSERT_SCRIPT = "scripts/grafana_alert_rules_upsert.py"


@pytest.fixture(scope="module")
def workflow_text() -> str:
    return WORKFLOW_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def workflow_doc(workflow_text: str) -> dict:
    data = yaml.safe_load(workflow_text)
    assert isinstance(data, dict), "workflow must parse as a mapping"
    return data


def test_trigger_contract_pinned(workflow_doc: dict) -> None:
    # PyYAML may parse bare `on:` as boolean True; tolerate both shapes.
    on_block = workflow_doc.get("on") if "on" in workflow_doc else workflow_doc.get(True)
    assert isinstance(on_block, dict), "workflow must declare `on:` mapping"

    push = on_block.get("push")
    assert isinstance(push, dict), "workflow must define push trigger"
    assert push.get("branches") == ["main"], "push trigger must remain pinned to main"
    # 2026-08-30: nicht mehr NUR die Datendatei. Der Publisher muss auch auf sein
    # eigenes SKRIPT triggern — sonst erreicht ein Umbau der Upsert-Logik die
    # Produktion nie von selbst (gemessen: der Fix aus #5204 lag 20 min
    # unausgeliefert auf main). Die Menge bleibt geschlossen: ein dritter Pfad
    # faellt weiter durch.
    assert push.get("paths") == [ALERT_RULES, "scripts/grafana_alert_rules_upsert.py"], (
        f"push path filter unerwartet: {push.get('paths')!r}"
    )

    dispatch = on_block.get("workflow_dispatch")
    assert isinstance(dispatch, dict), "workflow must support workflow_dispatch"
    dry_run = (dispatch.get("inputs") or {}).get("dry_run")
    assert isinstance(dry_run, dict), "dry_run input missing"
    assert dry_run.get("default") in (True, "true"), "dry_run must default to true for manual runs"


def test_permissions_and_concurrency_pinned(workflow_doc: dict) -> None:
    assert workflow_doc.get("permissions") == {"contents": "read"}, "must stay read-only at workflow scope"
    concurrency = workflow_doc.get("concurrency")
    assert isinstance(concurrency, dict)
    assert "${{ github.workflow }}" in concurrency.get("group", "")
    assert "${{ github.ref }}" in concurrency.get("group", "")
    assert concurrency.get("cancel-in-progress") is False, "publishes must not cancel each other"


def test_upsert_step_contract(workflow_text: str) -> None:
    # The token the upsert script reads (GRAFANA_API_KEY) must be mapped from the
    # existing GRAFANA_API_TOKEN secret, and a real (non-dry-run) upsert must
    # fail loud if it is absent.
    assert "GRAFANA_API_KEY: ${{ secrets.GRAFANA_API_TOKEN }}" in workflow_text
    assert "scripts/grafana_alert_rules_upsert.py --dry-run" in workflow_text, (
        "must preflight-validate with --dry-run before any network upsert"
    )
    assert 'test -n "${GRAFANA_API_KEY:-}"' in workflow_text, "real upsert must require the token"
    # No --prune: this workflow must never auto-delete rule groups absent from the file.
    assert "--prune" not in workflow_text, "auto-prune is unsafe for a push-triggered upsert"
    # Dry-run preflight must precede the mutating upsert.
    assert workflow_text.index("--dry-run") < workflow_text.rindex(
        "python scripts/grafana_alert_rules_upsert.py"
    ), "preflight dry-run must come before the real upsert"


def test_runner_and_python_pinned(workflow_text: str) -> None:
    assert "${{ vars.SMC_GH_HOSTED_RUNNER || 'ubuntu-latest' }}" in workflow_text
    assert "./.github/actions/setup-python-pinned" in workflow_text
    assert "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1" in workflow_text


def test_pyyaml_installed_before_upsert(workflow_text: str) -> None:
    """The upsert script parses alert-rules.yaml with PyYAML — set-up-python does
    NOT install it, so the workflow must `pip install pyyaml` before the upsert or
    it dies on `No module named 'yaml'` (regression guard for the 2026-07-11
    silent auto-publish failure)."""
    install_at = workflow_text.find("pip install")
    assert install_at != -1 and "pyyaml" in workflow_text, (
        "workflow must install PyYAML (the upsert's only third-party dep)"
    )
    # Anchor on the actual invocation, not the header comment that also names the script.
    upsert_at = workflow_text.index("python scripts/grafana_alert_rules_upsert.py")
    assert install_at < upsert_at, "PyYAML must be installed before the upsert step runs"


# --- what the step decides, measured rather than read ------------------------


@pytest.fixture
def upsert(tmp_path):
    """Run the real upsert step against a stubbed ``python``; report its calls."""

    def _run(
        event_name: str,
        *,
        dry_run: str = "",
        token: str = "grafana-token",
        python_exit: int = 0,
    ):
        return run_step(
            WORKFLOW,
            UPSERT_STEP,
            tmp_path,
            env={
                "EVENT_NAME": event_name,
                "INPUT_DRY_RUN": dry_run,
                "GRAFANA_API_KEY": token,
            },
            stubs={"python": python_exit},
        )

    return _run


def _network_upserts(result) -> tuple[str, ...]:
    """Invocations that actually mutate Grafana -- i.e. without ``--dry-run``."""
    return tuple(c for c in result.called_with(UPSERT_SCRIPT) if "--dry-run" not in c)


def test_upsert_executes_for_real_on_a_push(upsert) -> None:
    """A push to main must reach Grafana.

    The whole point of this workflow: before it existed, committed rule changes
    sat in the repo until someone remembered to run the script by hand.
    """
    result = upsert("push")
    assert result.returncode == 0, result.stderr
    assert _network_upserts(result), (
        "a push to main must perform a real upsert, not stop at the preflight; "
        f"the step only ran: {result.calls}"
    )


def test_upsert_preflights_before_it_mutates(upsert) -> None:
    """``--dry-run`` validation must come first -- in execution, not in source order."""
    calls = upsert("push").called_with(UPSERT_SCRIPT)
    assert len(calls) >= 2, calls
    assert "--dry-run" in calls[0], f"first invocation must be the preflight, got {calls[0]!r}"
    assert "--dry-run" not in calls[-1], f"last invocation must be the real upsert, got {calls[-1]!r}"


def test_a_manual_dry_run_never_reaches_grafana(upsert) -> None:
    """``dry_run=true`` (the manual default) must validate and stop."""
    result = upsert("workflow_dispatch", dry_run="true")
    assert result.returncode == 0, result.stderr
    assert not _network_upserts(result), (
        f"a dry run must not upsert; it ran: {result.calls}"
    )
    assert result.called_with(UPSERT_SCRIPT, "--dry-run"), "a dry run must still validate"


def test_a_manual_publish_reaches_grafana(upsert) -> None:
    """``dry_run=false`` is the deliberate manual publish."""
    assert _network_upserts(upsert("workflow_dispatch", dry_run="false"))


def test_an_unparseable_dry_run_input_fails_before_anything_runs(upsert) -> None:
    """Neither 'true' nor 'false' must be a hard stop, not a silent default."""
    result = upsert("workflow_dispatch", dry_run="maybe")
    assert result.returncode != 0, "an invalid dry_run input must fail the step"
    assert not result.calls, f"nothing may run before the input is validated: {result.calls}"


def test_a_real_upsert_without_the_token_fails_loud(upsert) -> None:
    """The claim ``test_upsert_step_contract`` makes in prose, executed.

    Fail-closed matters here specifically: an unauthenticated upsert that
    silently no-ops looks exactly like a successful one in the run log.
    """
    result = upsert("push", token="")
    assert result.returncode != 0, "a tokenless real upsert must fail, not skip"
    assert not _network_upserts(result), "it must fail BEFORE calling Grafana"


def test_a_failing_preflight_stops_the_upsert(upsert) -> None:
    """A rejected payload must never be upserted.

    Measured 2026-08-04, because the obvious explanation is the wrong one:
    deleting the block's own ``set -euo pipefail`` changes nothing here, since
    Actions already runs it as ``bash --noprofile --norc -eo pipefail`` via this
    workflow's ``defaults: run: shell: bash``. The line adds ``-u`` and nothing
    else to the abort behaviour.

    What this test does catch is the edit that really would swallow the
    preflight -- appending ``|| true`` to it. That leaves all five structural
    pins green while the step marches on to upsert the payload the preflight
    just rejected.
    """
    result = upsert("push", python_exit=1)
    assert result.returncode != 0, "a failed preflight must fail the step"
    assert not _network_upserts(result), (
        f"a rejected payload must never be upserted; the step ran: {result.calls}"
    )


def test_the_harness_runs_the_shell_this_workflow_declares(workflow_doc: dict) -> None:
    """Pin both sides.

    Pinning only the workflow's declaration leaves the harness tuple free to
    drift, and pinning only the tuple leaves the workflow free to. The step
    relies on ``pipefail``; measuring it under a plain ``bash -e`` would quietly
    weaken every assertion above.
    """
    assert declares_bash_default(WORKFLOW), "workflow must keep `defaults: run: shell: bash`"
    assert ((workflow_doc.get("defaults") or {}).get("run") or {}).get("shell") == "bash"
    assert BASH == ("bash", "--noprofile", "--norc", "-e", "-o", "pipefail")
