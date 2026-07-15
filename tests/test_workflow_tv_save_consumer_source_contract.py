"""Contract pin: ``tv-save-consumer-source`` workflow.

Pins the dispatch-only trigger, the fail-fast-without-auth guard, the
save and exact binding-verification entrypoints, and fail-closed coordinated
rollout handling. Also satisfies
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


def test_verifies_actual_consumer_source_selections_after_save() -> None:
    body = "\n".join(s.get("run", "") for s in _steps())
    assert "scripts/tv_verify_consumer_bindings.ts" in body
    assert 'verify SMC_Long_Dip_Dashboard.pine "SMC Long-Dip Dashboard" "SMC Decision Board"' in body
    assert 'verify SMC_Long_Dip_Strategy.pine "SMC Long-Dip Strategy" "SMC Long-Dip Strategy"' in body
    assert 'verify SMC_Long_Dip_Alerts.pine "SMC Long-Dip Alerts" "SMC Long-Dip Alerts"' in body
    assert 'verify SMC_Setup_Check.pine "SMC Setup Check" "SMC Setup Check"' in body


def test_miss_is_reported_and_any_miss_fails_the_coordinated_rollout() -> None:
    """A binding migration must not report success with a mixed account state."""
    save = next(s for s in _steps() if s.get("id") == "save")
    run = save["run"]
    assert 'if [ "${misses}" -ne 0 ]; then' in run
    assert "exit 1" in run


def test_default_mapping_uses_resolvable_suite_saved_name() -> None:
    body = "\n".join(s.get("run", "") for s in _steps())
    assert '{"source":"SMC_Long_Dip_Suite.pine","scriptName":"SMC Long-Dip Suite"}' in body
    assert '"scriptName":"SMC Core Engine"' not in body


def test_transient_tradingview_save_failures_are_retried_once() -> None:
    save = next(s for s in _steps() if s.get("id") == "save")
    assert "for attempt in 1 2; do" in save["run"]
    assert 'if [ "${saved}" -eq 1 ]; then' in save["run"]


def test_transient_binding_verification_failures_are_retried_once() -> None:
    step = next(s for s in _steps() if "Verify existing consumer" in s.get("name", ""))
    assert "for attempt in 1 2; do" in step["run"]
    assert "binding verification attempt" in step["run"]


def test_binding_parser_accepts_single_and_double_quoted_pine_labels() -> None:
    verifier = (_REPO_ROOT / "scripts" / "tv_verify_consumer_bindings.ts").read_text(encoding="utf-8")
    assert '(["\'])' in verifier
    assert ".map((match) => match[2])" in verifier


def test_binding_repair_is_explicit_and_reverified_before_success() -> None:
    verifier = (_REPO_ROOT / "scripts" / "tv_verify_consumer_bindings.ts").read_text(encoding="utf-8")
    assert 'hasFlag("--repair")' in verifier
    assert "repairSelectedSource" in verifier
    assert 'getByRole("option", { name: expected, exact: true })' in verifier
    assert 'button[name="submit"]' in verifier
    assert "binding.actual = await readSelectedSource" in verifier


def test_default_mapping_covers_every_binding_order_consumer() -> None:
    body = "\n".join(s.get("run", "") for s in _steps())
    expected = {
        "SMC_Breakout_Overlay.pine": "SMC Breakout Overlay",
        "SMC_Confluence_Hub.pine": "SMC Confluence Hub",
        "SMC_Long_Dip_Alerts.pine": "SMC Long-Dip Alerts",
        "SMC_Long_Dip_Dashboard.pine": "SMC Long-Dip Dashboard",
        "SMC_Long_Dip_Mobile.pine": "SMC Long-Dip Mobile",
        "SMC_Long_Dip_Strategy.pine": "SMC Long-Dip Strategy",
        "SMC_Setup_Check.pine": "SMC Setup Check",
    }
    for source, script_name in expected.items():
        assert f'{{"source":"{source}","scriptName":"{script_name}"}}' in body
