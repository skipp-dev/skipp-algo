"""Contract pin for the manual overlay-publish workflow (step 3 fast/slow split).

``smc-overlay-library-publish.yml`` is the manual-only companion to
``smc-library-refresh.yml``: it re-bakes the lean ``smc_overlay_generated``
library from the committed micro-profiles artifact and publishes it to
TradingView via ``scripts/tv_publish_overlay_library.ts``.

TradingView is a single shared external target, so the workflow MUST stay
``workflow_dispatch``-only (never gain a cron/push trigger that could fire an
unattended publish). This test pins that posture plus the workflow-discipline
env contract (PYTHONPATH / PYTHONUNBUFFERED), so a future edit that loosens any
of it fails loudly.

The literal basename ``smc-overlay-library-publish`` in this file also gives the
workflow test coverage for ``test_workflow_orphan_inventory.py``.
"""

from __future__ import annotations

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = (
    REPO_ROOT / ".github" / "workflows" / "smc-overlay-library-publish.yml"
)


def _load() -> dict:
    return yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))


def _all_run_blocks(doc: dict) -> list[str]:
    runs: list[str] = []
    for job in (doc.get("jobs") or {}).values():
        if not isinstance(job, dict):
            continue
        for step in job.get("steps") or []:
            if isinstance(step, dict) and isinstance(step.get("run"), str):
                runs.append(step["run"])
    return runs


def test_workflow_file_exists() -> None:
    assert WORKFLOW_PATH.is_file(), f"missing workflow: {WORKFLOW_PATH}"


def test_workflow_name() -> None:
    assert _load().get("name") == "smc-overlay-library-publish"


def test_trigger_is_workflow_dispatch_only() -> None:
    doc = _load()
    # PyYAML parses the `on:` key as the boolean True.
    triggers = doc.get(True, doc.get("on"))
    assert isinstance(triggers, dict), f"unexpected on-block: {triggers!r}"
    assert set(triggers.keys()) == {"workflow_dispatch"}, (
        "Overlay publish must stay manual-only — TradingView is a shared "
        f"external target. Found triggers: {sorted(triggers.keys())}"
    )


def test_no_schedule_or_push_trigger() -> None:
    doc = _load()
    triggers = doc.get(True, doc.get("on"))
    assert isinstance(triggers, dict)
    for forbidden in ("schedule", "push", "pull_request", "workflow_run"):
        assert forbidden not in triggers, (
            f"Overlay publish must not declare a {forbidden!r} trigger "
            "(manual-only posture)."
        )


def test_permissions_are_read_only() -> None:
    assert _load().get("permissions") == {"contents": "read"}


def test_live_window_marker_is_manual_only() -> None:
    head = WORKFLOW_PATH.read_text(encoding="utf-8").splitlines()[:10]
    markers = [
        line.split(":", 1)[1].strip()
        for line in head
        if line.startswith("# live-window:")
    ]
    assert markers == ["manual-only"], (
        "Workflow must declare `# live-window: manual-only` within the first "
        f"10 lines (found markers: {markers})."
    )


def test_top_level_env_sets_pythonpath_and_unbuffered() -> None:
    env = _load().get("env") or {}
    assert env.get("PYTHONUNBUFFERED") in ("1", 1, "true", True), (
        f"top-level env.PYTHONUNBUFFERED must be '1' (got {env.get('PYTHONUNBUFFERED')!r})"
    )
    assert "github.workspace" in str(env.get("PYTHONPATH", "")), (
        f"top-level env.PYTHONPATH must reference github.workspace (got {env.get('PYTHONPATH')!r})"
    )


def test_publish_job_has_bounded_timeout() -> None:
    job = (_load().get("jobs") or {}).get("publish-overlay")
    assert isinstance(job, dict), "missing publish-overlay job"
    assert job.get("timeout-minutes") == 30


def test_workflow_bakes_overlay_before_publishing() -> None:
    runs = _all_run_blocks(_load())
    assert any("scripts/bake_overlay_library.py" in r for r in runs), (
        "Expected a step that re-bakes via scripts/bake_overlay_library.py"
    )


def test_workflow_invokes_overlay_publisher() -> None:
    runs = _all_run_blocks(_load())
    assert any("scripts/tv_publish_overlay_library.ts" in r for r in runs), (
        "Expected a step that runs scripts/tv_publish_overlay_library.ts"
    )


def test_publish_report_is_uploaded_always() -> None:
    job = (_load().get("jobs") or {}).get("publish-overlay") or {}
    upload_steps = [
        step
        for step in job.get("steps") or []
        if isinstance(step, dict)
        and isinstance(step.get("uses"), str)
        and step["uses"].startswith("actions/upload-artifact@")
    ]
    assert upload_steps, "expected an actions/upload-artifact step"
    assert any(
        str(step.get("if", "")).strip() == "always()" for step in upload_steps
    ), "the publish-report upload must run with `if: always()`"
