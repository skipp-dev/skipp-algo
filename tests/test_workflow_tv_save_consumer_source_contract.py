"""Contract pin: ``tv-save-consumer-source`` workflow.

Pins the dispatch-only trigger, the fail-fast-without-auth guard, the
tv_save_consumer_source entrypoint, and the graceful per-entry miss handling
(a wrong saved name is reported, not a wrong-script paste). Also satisfies
``test_workflow_orphan_inventory`` by referencing the stem ``tv-save-consumer-source``.
"""

from __future__ import annotations

from pathlib import Path

import yaml

_REPO_ROOT = Path(__file__).resolve().parents[1]
_WF_PATH = _REPO_ROOT / ".github" / "workflows" / "tv-save-consumer-source.yml"


def _load() -> dict:
    return yaml.safe_load(_WF_PATH.read_text(encoding="utf-8"))


def _steps() -> list[dict]:
    return _load()["jobs"]["save"]["steps"]


def test_workflow_file_exists() -> None:
    assert _WF_PATH.is_file(), f"missing workflow: {_WF_PATH}"


def test_dispatch_only_no_schedule() -> None:
    on_block = _load().get("on") or _load().get(True)
    assert "workflow_dispatch" in on_block
    # Writing to the operator's personal saved scripts is on-demand only.
    assert "schedule" not in on_block


def test_fails_fast_without_tv_auth() -> None:
    step = next(s for s in _steps() if "storage state" in s.get("name", "").lower())
    assert 'if [ -z "${TV_STORAGE_STATE_SECRET:-}" ]; then' in step["run"]
    assert "exit 1" in step["run"]


def test_runs_the_save_tool() -> None:
    body = " ".join(s.get("run", "") for s in _steps())
    assert "scripts/tv_save_consumer_source.ts" in body
    assert "--script-name" in body


def test_miss_is_graceful_but_zero_hits_fails() -> None:
    """An unknown saved name is a reported miss (run continues); zero hits is a
    hard failure so nothing is mistaken for success."""
    save = next(s for s in _steps() if s.get("id") == "save")
    run = save["run"]
    assert 'if [ "${hits}" -eq 0 ]; then' in run
    assert "exit 1" in run


def test_default_mapping_uses_grounded_core_engine_name() -> None:
    """SMC_Core_Engine's saved name is the operator-chosen 'SMC Core Engine',
    not its indicator title — pin that so a refactor cannot silently regress it."""
    body = "\n".join(s.get("run", "") for s in _steps())
    assert '{"source":"SMC_Core_Engine.pine","scriptName":"SMC Core Engine"}' in body
