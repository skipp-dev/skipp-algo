"""Contract pin: ``tv-save-consumer-source`` workflow.

Pins the manual save and scheduled read-only triggers, the fail-fast-without-auth
guard, the exact binding-verification entrypoints, and fail-closed coordinated
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


def test_schedule_is_daily_and_forces_read_only_mapping() -> None:
    on_block = _load().get("on") or _load().get(True)
    assert "workflow_dispatch" in on_block
    assert on_block["schedule"] == [{"cron": "17 5 * * *"}]
    rollout = next(s for s in _steps() if "scripts/tv_batch_consumer_rollout.ts" in s.get("run", ""))
    mapping = rollout["env"]["TV_CONSUMER_MAPPING_JSON"]
    assert "github.event_name == 'schedule'" in mapping
    assert "&& '[]'" in mapping
    assert "github.event_name == 'workflow_dispatch'" in rollout["env"]["TV_FORCE_REBIND"]


def test_fails_fast_without_tv_auth() -> None:
    step = next(s for s in _steps() if "storage state" in s.get("name", "").lower())
    assert 'if [ -z "${TV_STORAGE_STATE_SECRET:-}" ]; then' in step["run"]
    assert "exit 1" in step["run"]


def test_runs_the_shared_session_batch_tool() -> None:
    body = " ".join(s.get("run", "") for s in _steps())
    assert "scripts/tv_batch_consumer_rollout.ts" in body
    saver = (_REPO_ROOT / "scripts" / "tv_save_consumer_source.ts").read_text(encoding="utf-8")
    assert "setEditorContent(session.page, code, { editorAlreadyOpen: true })" in saver


def test_verifies_actual_consumer_source_selections_after_save() -> None:
    config = yaml.safe_load(
        (_REPO_ROOT / "automation/tradingview/config/consumer-rollout.json").read_text(encoding="utf-8")
    )
    names = {target["scriptName"] for target in config["verifyTargets"]}
    assert config["primaryChartUrl"] == "https://www.tradingview.com/chart/vWgAWyfC/"
    assert names == {
        "SMC Decision Board",
        "SMC Long-Dip Strategy",
        "SMC Long-Dip Alerts",
        "SMC Setup Check",
        "SMC Breakout Overlay",
        "SMC Confluence Hub",
        "SMC Long-Dip Mobile",
    }
    mobile = next(target for target in config["verifyTargets"] if target["scriptName"] == "SMC Long-Dip Mobile")
    assert mobile["chartUrl"] == "https://www.tradingview.com/chart/YcGLVHXR/"


def test_miss_is_reported_and_any_miss_fails_the_coordinated_rollout() -> None:
    """A binding migration must not report success with a mixed account state."""
    batch = (_REPO_ROOT / "scripts" / "tv_batch_consumer_rollout.ts").read_text(encoding="utf-8")
    assert "report.save.failed.length === 0" in batch
    assert "report.bindings.mismatches === 0" in batch
    assert "process.exitCode = 1" in batch


def test_default_mapping_uses_resolvable_suite_saved_name() -> None:
    config = (_REPO_ROOT / "automation/tradingview/config/consumer-rollout.json").read_text(encoding="utf-8")
    assert '"source": "SMC_Long_Dip_Suite.pine"' in config
    assert '"scriptName": "SMC Long-Dip Suite"' in config
    assert '"scriptName": "SMC Core Engine"' not in config


def test_transient_tradingview_save_failures_are_retried_once() -> None:
    batch = (_REPO_ROOT / "scripts" / "tv_batch_consumer_rollout.ts").read_text(encoding="utf-8")
    assert "for (let attempt = 1; attempt <= 2; attempt += 1)" in batch


def test_transient_binding_verification_failures_are_retried_once() -> None:
    batch = (_REPO_ROOT / "scripts" / "tv_batch_consumer_rollout.ts").read_text(encoding="utf-8")
    assert batch.count("for (let attempt = 1; attempt <= 2; attempt += 1)") == 2


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
    body = (_REPO_ROOT / "automation/tradingview/config/consumer-rollout.json").read_text(encoding="utf-8")
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
        assert f'"source": "{source}"' in body
        assert f'"scriptName": "{script_name}"' in body


def test_repair_e2e_is_explicit_and_uses_visible_dashboard_test_instance() -> None:
    dispatch = (_load().get("on") or _load().get(True))["workflow_dispatch"]["inputs"]
    assert dispatch["repair_e2e"]["default"] is False
    repair = next(s for s in _steps() if s.get("name") == "Controlled repair E2E")
    assert "repair_e2e == 'true'" in repair["if"]
    assert "scripts/tv_repair_binding_e2e.ts" in repair["run"]
    config = yaml.safe_load(
        (_REPO_ROOT / "automation/tradingview/config/consumer-rollout.json").read_text(encoding="utf-8")
    )
    assert config["repairE2ETarget"]["scriptName"] == "SMC Decision Board"
    e2e = (_REPO_ROOT / "scripts" / "tv_repair_binding_e2e.ts").read_text(encoding="utf-8")
    assert 'setConsumerBindingForTest(session, target, testLabel, "Close")' in e2e
    assert "verifyConsumerBindings(session, target, true)" in e2e


def test_binding_snapshot_is_uploaded_even_when_rollout_fails() -> None:
    upload = next(s for s in _steps() if s.get("name") == "Upload binding snapshot")
    assert upload["if"] == "${{ always() }}"
    assert upload["with"]["path"] == "artifacts/monitoring/tradingview_consumer_bindings.json"
    publish = next(s for s in _steps() if s.get("name") == "Publish latest binding snapshot")
    assert publish["if"] == "${{ always() }}"
    assert 'stable_dir="artifacts/monitoring/latest"' in publish["run"]
    assert '"${stable_dir}/tradingview_consumer_bindings.json"' in publish["run"]
    assert "bot/live-tradingview-bindings" in publish["run"]


def test_force_rebind_is_opt_in_and_reaches_the_rollout_script() -> None:
    """The dispatch input must not be decoration: it has to reach the script that reads it.

    Mutating away any single link below (input, env plumb, or the env read) has to fail
    this test, otherwise `force_rebind=true` would silently run a read-only verification.
    """
    dispatch = (_load().get("on") or _load().get(True))["workflow_dispatch"]["inputs"]
    assert dispatch["force_rebind"]["default"] is False, "rebinding must never be the default"

    rollout = next(s for s in _steps() if "scripts/tv_batch_consumer_rollout.ts" in s.get("run", ""))
    assert rollout["env"]["TV_FORCE_REBIND"] == (
        "${{ github.event_name == 'workflow_dispatch' && "
        "github.event.inputs.force_rebind || 'false' }}"
    )

    batch = (_REPO_ROOT / "scripts" / "tv_batch_consumer_rollout.ts").read_text(encoding="utf-8")
    assert 'process.env.TV_FORCE_REBIND === "true"' in batch
    assert "verifyConsumerBindings(session, target, forceRebind, forceRebind)" in batch


def test_scheduled_run_cannot_execute_repair_e2e() -> None:
    repair = next(s for s in _steps() if s.get("name") == "Controlled repair E2E")
    assert "github.event_name == 'workflow_dispatch'" in repair["if"]
    assert "repair_e2e == 'true'" in repair["if"]


def test_force_rebind_reselects_every_binding_not_just_mismatches() -> None:
    """A correct dropdown label can still hide a dead parent study id, so text equality
    is not a safe skip condition once the operator asked for a rebind."""
    verifier = (_REPO_ROOT / "scripts" / "tv_verify_consumer_bindings.ts").read_text(encoding="utf-8")
    assert "const bindingsToRepair = forceRebind ? bindings : mismatches;" in verifier
    assert "for (const binding of bindingsToRepair)" in verifier
    assert 'const forceRebind = hasFlag("--force-rebind");' in verifier
    assert 'const repair = hasFlag("--repair") || forceRebind;' in verifier


def test_unknown_parent_runtime_error_fails_closed() -> None:
    """Exact dropdown text is not proof of a live binding: a remaining runtime marker
    must sink `ok` and exit non-zero, not be reported alongside a green result."""
    verifier = (_REPO_ROOT / "scripts" / "tv_verify_consumer_bindings.ts").read_text(encoding="utf-8")
    assert "/unknown parent id/i.test(chartBody)" in verifier
    assert "ok: mismatches.length === 0 && !unknownParentRuntimeError," in verifier
    assert "if (result.unknownParentRuntimeError) {" in verifier


def test_cache_runs_on_native_node24_without_force_override() -> None:
    workflow = _WF_PATH.read_text(encoding="utf-8")
    assert "actions/cache@27d5ce7f107fe9357f9df03efb73ab90386fccae # v5" in workflow
    assert "FORCE_JAVASCRIPT_ACTIONS_TO_NODE24" not in workflow
    assert "actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a # v7" in workflow
