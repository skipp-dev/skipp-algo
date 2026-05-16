"""Contract tests for the smc-databento-production-export workflow.

These tests guard the cache-key handshake between

  - .github/workflows/smc-databento-production-export.yml   (producer)
  - .github/workflows/smc-library-refresh.yml               (consumer)

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

import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
PRODUCER_WF = REPO_ROOT / ".github" / "workflows" / "smc-databento-production-export.yml"
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


def test_producer_workflow_exists():
    assert PRODUCER_WF.is_file(), f"Missing producer workflow: {PRODUCER_WF}"


def test_consumer_workflow_exists():
    assert CONSUMER_WF.is_file(), f"Missing consumer workflow: {CONSUMER_WF}"


def test_producer_uses_databento_api_key_secret():
    wf = _load_yaml(PRODUCER_WF)
    found = False
    for step in _flatten_steps(wf):
        env = step.get("env") or {}
        for value in env.values():
            if isinstance(value, str) and "secrets.DATABENTO_API_KEY" in value:
                found = True
                break
    assert found, "Producer workflow must inject secrets.DATABENTO_API_KEY"


def test_producer_prefers_priority_cron_self_hosted_runner() -> None:
    text = PRODUCER_WF.read_text(encoding="utf-8")

    assert '--custom-label "${{ vars.SMC_PRIORITY_CRON_SELF_HOSTED_LABEL || vars.SMC_SELF_HOSTED_LABEL }}"' in text
    assert "--inventory-unavailable-fallback required-self-hosted" in text
    assert '--custom-label "${{ vars.SMC_SELF_HOSTED_LABEL }}"' not in text


def test_producer_writes_to_export_dir():
    text = PRODUCER_WF.read_text(encoding="utf-8")
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
    wf = _load_yaml(PRODUCER_WF)
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
        timeout=30,
    )
    assert proc.returncode == 0, (
        f"Producer --help failed:\nstdout={proc.stdout}\nstderr={proc.stderr}"
    )
    assert "--export-dir" in proc.stdout, (
        "Producer must expose --export-dir so the producer workflow can "
        "redirect output away from default_export_directory() (~/Downloads)."
    )


def test_producer_schedule_runs_before_library_refresh():
    """Producer→Consumer coupling.

    Originally enforced cron-before-cron timing. After F-V4-J3 (2026-05-01)
    the consumer (smc-library-refresh) was switched from 4 daily crons to
    `workflow_run` triggered by the producer; the producer keeps its own
    crons and gates the cascade. The new contract:

    1. Producer must still declare schedule.cron entries.
    2. Consumer must declare a `workflow_run` trigger naming the producer
       and gating on conclusion=='success'.
    """
    producer = _load_yaml(PRODUCER_WF)
    consumer = _load_yaml(CONSUMER_WF)

    # PyYAML parses bare `on:` as the boolean True. Look up either form.
    p_on = producer.get("on") or producer.get(True)
    c_on = consumer.get("on") or consumer.get(True)

    def _crons(on_block) -> list[str]:
        sched = (on_block or {}).get("schedule") or []
        return [entry.get("cron", "") for entry in sched]

    p_crons = _crons(p_on)
    assert p_crons, "Producer must declare schedule.cron entries"

    # F-V4-J3: consumer must be workflow_run-coupled to the producer.
    wfr = (c_on or {}).get("workflow_run")
    assert wfr, (
        "Consumer must declare a workflow_run trigger (F-V4-J3). "
        "Got on: " + repr(list((c_on or {}).keys()))
    )
    producer_name = producer.get("name") or PRODUCER_WF.stem
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


def test_export_dir_is_gitignored():
    """The export bundle is large, intermediate data — must not be committed."""
    gitignore = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "smc_microstructure_exports" in gitignore, (
        "artifacts/smc_microstructure_exports/ must remain in .gitignore "
        "so producer-generated bundles are not accidentally committed."
    )
