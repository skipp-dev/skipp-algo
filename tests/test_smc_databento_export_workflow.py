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


def test_producer_writes_to_export_dir():
    text = PRODUCER_WF.read_text(encoding="utf-8")
    assert EXPORT_DIR in text, (
        f"Producer workflow must materialize exports under {EXPORT_DIR}/"
    )
    assert "--export-dir" in text, (
        "Producer workflow must pass --export-dir to databento_production_export.py"
    )


def test_producer_saves_cache_with_canonical_key_pattern():
    wf = _load_yaml(PRODUCER_WF)
    save_keys: list[str] = []
    for step in _flatten_steps(wf):
        uses = step.get("uses") or ""
        if uses.startswith("actions/cache/save"):
            with_block = step.get("with") or {}
            key = with_block.get("key", "")
            save_keys.append(key)
    assert save_keys, "Producer must save at least one cache entry"
    assert any(
        f"{CACHE_KEY_PREFIX}${{{{ runner.os }}}}-${{{{ env.EXPORT_DATE }}}}" in k
        and "github.run_id" not in k
        for k in save_keys
    ), (
        f"Producer must save under canonical date-only key "
        f"'{CACHE_KEY_PREFIX}<os>-<YYYY-MM-DD>'. Got: {save_keys}"
    )


def test_consumer_restores_with_matching_cache_key():
    wf = _load_yaml(CONSUMER_WF)
    restore_steps = [
        step for step in _flatten_steps(wf)
        if (step.get("uses") or "").startswith("actions/cache/restore")
        and EXPORT_DIR in str((step.get("with") or {}).get("path", ""))
        and CACHE_KEY_PREFIX in str((step.get("with") or {}).get("key", ""))
    ]
    assert restore_steps, (
        f"Consumer must include an actions/cache/restore step for {EXPORT_DIR} "
        f"using a key that starts with {CACHE_KEY_PREFIX}"
    )
    step = restore_steps[0]
    with_block = step["with"]
    key = str(with_block.get("key", ""))
    assert CACHE_KEY_PREFIX in key, (
        f"Consumer restore key must use prefix {CACHE_KEY_PREFIX}; got {key!r}"
    )
    # Date scoping may be expressed via env.REFRESH_DATE or another date
    # variable — accept either spelling so a future rename doesn't break us.
    assert "DATE" in key.upper(), (
        f"Consumer restore key must be date-scoped; got {key!r}"
    )
    restore_keys = str(with_block.get("restore-keys", ""))
    assert CACHE_KEY_PREFIX in restore_keys, (
        "Consumer must declare restore-keys fallback to most-recent same-OS bundle"
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
