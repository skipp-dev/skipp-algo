"""Contract tests for the Databento producer/consumer workflow contract.

These tests guard the cache-key handshake between

    - .github/workflows/smc-databento-production-export-sharded.yml (canonical producer)
    - .github/workflows/smc-databento-production-export.yml         (legacy fallback)
    - .github/workflows/smc-library-refresh.yml                     (consumer)

so that we never reintroduce the failure mode that surfaced on
2026-04-30 (library-refresh red since 2026-04-24 because the canonical
``databento_volatility_production_*_manifest.json`` was only ever
produced on a developer workstation).

We also assert that the producer's CLI surface still exposes the
``--export-dir`` flag the workflow relies on, since reverting that flag
would silently revert the producer to writing into ``~/Downloads``
inside the runner.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
LEGACY_PRODUCER_WF = REPO_ROOT / ".github" / "workflows" / "smc-databento-production-export.yml"
SHARDED_PRODUCER_WF = REPO_ROOT / ".github" / "workflows" / "smc-databento-production-export-sharded.yml"
CONSUMER_WF = REPO_ROOT / ".github" / "workflows" / "smc-library-refresh.yml"
PRODUCER_SCRIPT = REPO_ROOT / "scripts" / "databento_production_export.py"

CACHE_KEY_PREFIX = "smc-prod-export-"
EXPORT_DIR = "artifacts/smc_microstructure_exports"
CANONICAL_MANIFEST_GLOB = "databento_volatility_production_*_manifest.json"


def _load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _flatten_steps(workflow: dict) -> list[dict]:
    steps: list[dict] = []
    for job in (workflow.get("jobs") or {}).values():
        for step in job.get("steps") or []:
            steps.append(step)
    return steps


def test_producer_workflows_exist():
    assert SHARDED_PRODUCER_WF.is_file(), (
        f"Missing canonical producer workflow: {SHARDED_PRODUCER_WF}"
    )
    assert LEGACY_PRODUCER_WF.is_file(), (
        f"Missing legacy producer workflow: {LEGACY_PRODUCER_WF}"
    )


def test_consumer_workflow_exists():
    assert CONSUMER_WF.is_file(), f"Missing consumer workflow: {CONSUMER_WF}"


def test_producer_uses_databento_api_key_secret():
    wf = _load_yaml(LEGACY_PRODUCER_WF)
    found = False
    for step in _flatten_steps(wf):
        env = step.get("env") or {}
        for value in env.values():
            if isinstance(value, str) and "secrets.DATABENTO_API_KEY" in value:
                found = True
                break
    assert found, "Producer workflow must inject secrets.DATABENTO_API_KEY"


def test_producer_prefers_priority_cron_self_hosted_runner() -> None:
    text = LEGACY_PRODUCER_WF.read_text(encoding="utf-8")

    assert '--custom-label "${{ vars.SMC_PRIORITY_CRON_SELF_HOSTED_LABEL || vars.SMC_SELF_HOSTED_LABEL }}"' in text
    # Legacy monolithic producer is workflow_dispatch-only emergency fallback.
    # When runner inventory is unavailable, it should route to github-hosted
    # instead of forcing required self-hosted queueing.
    assert "--inventory-unavailable-fallback hosted" in text
    assert "--inventory-unavailable-fallback required-self-hosted" not in text
    assert '--custom-label "${{ vars.SMC_SELF_HOSTED_LABEL }}"' not in text


def test_producer_writes_to_export_dir():
    text = LEGACY_PRODUCER_WF.read_text(encoding="utf-8")
    assert EXPORT_DIR in text, (
        f"Producer workflow must materialize exports under {EXPORT_DIR}/"
    )
    assert "--export-dir" in text, (
        "Producer workflow must pass --export-dir to databento_production_export.py"
    )


def test_producer_saves_cache_with_canonical_key_pattern():
    # 2026-05-03 (#2034): F-V5-D2 (PR #1958, 2026-05-01) intentionally
    # removed the actions/cache/save handoff and replaced it with
    # actions/upload-artifact, because the cache-based path was unreliable
    # across the producer→consumer workflow boundary on hosted runners.
    # The contract is now enforced by the artifact upload/download steps,
    # not by a cache key. This pin is therefore obsolete: it asserts a
    # contract that was deliberately retired and is blocking every PR on
    # `main` from going green. We keep the test but invert it to lock in
    # the absence of `actions/cache/save` in the producer workflow, so a
    # future accidental re-introduction would be caught.
    wf = _load_yaml(LEGACY_PRODUCER_WF)
    cache_save_steps = [
        step
        for step in _flatten_steps(wf)
        if (step.get("uses") or "").startswith("actions/cache/save")
    ]
    assert not cache_save_steps, (
        "Producer workflow must NOT use actions/cache/save for the "
        "producer→consumer handoff (retired by F-V5-D2 / PR #1958 in favor "
        "of actions/upload-artifact). Found: "
        f"{[s.get('uses') for s in cache_save_steps]}"
    )


def test_consumer_restores_with_matching_cache_key():
    # 2026-05-03 (#2034): F-V5-D2 (PR #1958) retired the cache-based handoff
    # in favor of actions/download-artifact. Same rationale as the producer-
    # side pin above: keep the test, invert it to lock in the absence of
    # actions/cache/restore for the producer→consumer handoff path.
    wf = _load_yaml(CONSUMER_WF)
    restore_steps = [
        step for step in _flatten_steps(wf)
        if (step.get("uses") or "").startswith("actions/cache/restore")
        and CACHE_KEY_PREFIX in str((step.get("with") or {}).get("key", ""))
    ]
    assert not restore_steps, (
        "Consumer workflow must NOT use actions/cache/restore for the "
        f"{EXPORT_DIR} handoff (retired by F-V5-D2 / PR #1958 in favor of "
        f"actions/download-artifact). Found: {[s.get('uses') for s in restore_steps]}"
    )


def test_consumer_release_reference_step_is_advisory_when_bundle_missing():
    wf = _load_yaml(CONSUMER_WF)
    for step in _flatten_steps(wf):
        if step.get("name") == "Refresh release reference artifacts (best-effort)":
            assert step.get("continue-on-error") is True, (
                "Refresh release reference artifacts (best-effort) must be advisory "
                "(continue-on-error: true) so a cold producer cache does "
                "not block the entire library refresh + TradingView publish."
            )
            run_block = step.get("run", "")
            assert "bundle_present" in run_block, (
                "Step must consult verify_export_bundle.outputs.bundle_present "
                "and skip cleanly when the bundle is missing."
            )
            return
    pytest.fail("Could not find 'Refresh release reference artifacts (best-effort)' step")


def test_producer_script_exposes_export_dir_flag():
    """Run the producer with --help to confirm the CLI surface."""
    proc = subprocess.run(
        [sys.executable, str(PRODUCER_SCRIPT), "--help"],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=90,
    )
    assert proc.returncode == 0, (
        f"Producer --help failed:\nstdout={proc.stdout}\nstderr={proc.stderr}"
    )
    assert "--export-dir" in proc.stdout, (
        "Producer must expose --export-dir so the producer workflow can "
        "redirect output away from default_export_directory() (~/Downloads)."
    )


def test_sharded_producer_drives_library_refresh_workflow_run():
    """Cutover contract: sharded producer is canonical, monolith is fallback.

    F-V8-cutover (2026-05-18) moved the canonical cron from the monolithic
    producer to the sharded producer. The new contract:

    1. Sharded producer keeps the live schedule.cron entries.
    2. Legacy monolithic producer remains workflow_dispatch-only fallback.
    3. Consumer declares `workflow_run` on the sharded producer and gates
       on conclusion=='success'.
    """
    producer = _load_yaml(SHARDED_PRODUCER_WF)
    legacy = _load_yaml(LEGACY_PRODUCER_WF)
    consumer = _load_yaml(CONSUMER_WF)

    # PyYAML parses bare `on:` as the boolean True. Look up either form.
    p_on = producer.get("on") or producer.get(True)
    l_on = legacy.get("on") or legacy.get(True)
    c_on = consumer.get("on") or consumer.get(True)

    def _crons(on_block) -> list[str]:
        sched = (on_block or {}).get("schedule") or []
        return [entry.get("cron", "") for entry in sched]

    p_crons = _crons(p_on)
    assert p_crons, "Canonical sharded producer must declare schedule.cron entries"

    legacy_triggers = set((l_on or {}).keys())
    assert "workflow_dispatch" in legacy_triggers, (
        "Legacy monolithic producer must keep workflow_dispatch as the "
        "emergency fallback trigger."
    )
    assert "schedule" not in legacy_triggers, (
        "Legacy monolithic producer must not keep schedule after the sharded "
        "cutover."
    )

    # F-V8-cutover: consumer must be workflow_run-coupled to the canonical
    # sharded producer, not the deprecated monolith.
    wfr = (c_on or {}).get("workflow_run")
    assert wfr, (
        "Consumer must declare a workflow_run trigger (F-V4-J3). "
        "Got on: " + repr(list((c_on or {}).keys()))
    )
    producer_name = producer.get("name") or SHARDED_PRODUCER_WF.stem
    assert producer_name in (wfr.get("workflows") or []), (
        f"Consumer workflow_run.workflows must reference producer "
        f"{producer_name!r}; got {wfr.get('workflows')!r}"
    )

    # The job-level `if:` must gate on conclusion=='success' so that
    # producer failures do not cascade into stale-data publishes.
    # Strict equality check: a substring match would accept truthy
    # noise like "!= 'success'", "succeeded()", or chained boolean
    # expressions whose effective gate isn't on success.
    refresh_if = (consumer.get("jobs", {}).get("refresh", {}) or {}).get("if", "")
    refresh_if_norm = " ".join(str(refresh_if).split())
    assert (
        "github.event.workflow_run.conclusion == 'success'" in refresh_if_norm
        or 'github.event.workflow_run.conclusion == "success"' in refresh_if_norm
    ), (
        f"Consumer jobs.refresh.if must gate workflow_run on "
        f"conclusion == 'success' (exact equality); got: {refresh_if!r}"
    )


def test_consumer_restores_artifacts_from_sharded_workflow() -> None:
    wf = _load_yaml(CONSUMER_WF)
    restore_steps = [
        step
        for step in _flatten_steps(wf)
        if step.get("name") in {
            "Restore Databento production export bundle (today)",
            "Restore Databento production export bundle (latest fallback)",
        }
    ]
    assert len(restore_steps) == 2, (
        "Expected both Databento export restore steps in the consumer workflow."
    )
    for step in restore_steps:
        workflow_name = str((step.get("with") or {}).get("workflow") or "")
        assert workflow_name == SHARDED_PRODUCER_WF.name, (
            f"{step.get('name')} must resolve artifacts from "
            f"{SHARDED_PRODUCER_WF.name!r}; got {workflow_name!r}"
        )


def test_export_dir_is_gitignored():
    """The export bundle is large, intermediate data — must not be committed."""
    gitignore = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "smc_microstructure_exports" in gitignore, (
        "artifacts/smc_microstructure_exports/ must remain in .gitignore "
        "so producer-generated bundles are not accidentally committed."
    )
