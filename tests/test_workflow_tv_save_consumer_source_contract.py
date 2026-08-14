"""Contract pin: ``tv-save-consumer-source`` workflow.

Pins the manual save and scheduled read-only triggers, the fail-fast-without-auth
guard, the exact binding-verification entrypoints, and fail-closed coordinated
rollout handling. Also satisfies
``test_workflow_orphan_inventory`` by referencing the stem ``tv-save-consumer-source``.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest
import yaml

_REPO_ROOT = Path(__file__).resolve().parents[1]
_WF_PATH = _REPO_ROOT / ".github" / "workflows" / "tv-save-consumer-source.yml"


def _load() -> dict:
    return yaml.safe_load(_WF_PATH.read_text(encoding="utf-8"))


def _steps() -> list[dict]:
    return _load()["jobs"]["save"]["steps"]


def test_workflow_file_exists() -> None:
    assert _WF_PATH.is_file(), f"missing workflow: {_WF_PATH}"


def test_schedule_runs_twice_daily_and_invokes_explicit_verify_only_mode() -> None:
    on_block = _load().get("on") or _load().get(True)
    assert "workflow_dispatch" in on_block
    # Two read-only looks per day. The morning cron alone left operator-caused
    # drift undetected for up to 24h on a day with no other run; the evening one
    # halves that. Both sit after the US close, honouring this file's
    # off-hours-only live-window declaration. Read-only is structural, not
    # conventional: TV_VERIFY_ONLY and TV_CONSUMER_MAPPING_JSON both derive from
    # github.event_name == 'schedule', so no cron entry can mutate.
    assert on_block["schedule"] == [{"cron": "17 5 * * *"}, {"cron": "17 21 * * *"}]
    rollout = next(s for s in _steps() if "scripts/tv_batch_consumer_rollout.ts" in s.get("run", ""))
    verify_only = rollout["env"]["TV_VERIFY_ONLY"]
    assert "github.event_name == 'schedule'" in verify_only
    assert "&& 'true'" in verify_only
    assert 'args+=(--verify-only)' in rollout["run"]
    assert '"${args[@]}"' in rollout["run"]
    mapping = rollout["env"]["TV_CONSUMER_MAPPING_JSON"]
    assert "github.event_name == 'schedule'" in mapping
    assert "&& '[]'" in mapping
    assert "github.event_name == 'workflow_dispatch'" in rollout["env"]["TV_FORCE_REBIND"]
    assert "github.event_name == 'workflow_dispatch'" in rollout["env"]["TV_REFRESH_PRODUCER"]


def test_fails_fast_without_tv_auth() -> None:
    step = next(s for s in _steps() if "storage state" in s.get("name", "").lower())
    assert 'if [ -z "${TV_STORAGE_STATE_SECRET:-}" ]; then' in step["run"]
    assert "exit 1" in step["run"]


def test_runs_the_shared_session_batch_tool() -> None:
    body = " ".join(s.get("run", "") for s in _steps())
    assert "scripts/tv_batch_consumer_rollout.ts" in body
    saver = (_REPO_ROOT / "scripts" / "tv_save_consumer_source.ts").read_text(encoding="utf-8")
    assert "setEditorContent(session.page, code, { editorAlreadyOpen: true })" in saver


def test_save_is_model_pinned_before_write_and_hash_verified_after_save() -> None:
    """Write authority needs title + model transition; saved output needs its declaration/hash."""
    saver = (_REPO_ROOT / "scripts" / "tv_save_consumer_source.ts").read_text(encoding="utf-8")
    open_index = saver.index("const opened = await openExistingScript")
    pre_write_index = saver.index("assertConsumerPreWriteSource(target, preWriteSource)")
    paste_index = saver.index("await setEditorContent(session.page, code")
    staged_index = saver.index('assertConsumerEditorSource("staged source"')
    save_index = saver.index("await saveScript(session.page")
    post_save_index = saver.index('assertConsumerEditorSource("post-save source"')
    assert open_index < pre_write_index < paste_index < staged_index < save_index < post_save_index
    assert saver.count("expectedDeclarationTitle: target.scriptName") >= 3
    assert saver.count("requireVisibleEditor: true") == 4
    assert saver.count("requireVisibleDeclarationIdentity: true") == 2
    assert "allowDeclarationDriftRepair: true" in saver


def test_write_rollout_reloads_persisted_state_before_source_verification() -> None:
    """In-memory editor state must not count as persisted TradingView evidence."""
    batch = (_REPO_ROOT / "scripts" / "tv_batch_consumer_rollout.ts").read_text(encoding="utf-8")
    verification_block = batch.split("if (report.save.failed.length === 0)", 1)[1]
    reload_index = verification_block.index("await gotoChart(session.page, config.primaryChartUrl)")
    verify_index = verification_block.index("result = await verifyConsumerSource(session, target)")
    assert reload_index < verify_index
    assert "executionPlan.saveSources && report.save.succeeded.length > 0" in verification_block


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
        "SMC Event Overlay",
        "SMC Exit Signal",
    }
    # 2026-07-24: the dedicated Mobile layout (YcGLVHXR) no longer opens; the
    # Mobile consumer now lives on the primary chart alongside the others. With
    # no chartUrl override the rollout resolves it to primaryChartUrl
    # (tv_batch_consumer_rollout.ts: `target.chartUrl ?? config.primaryChartUrl`).
    mobile = next(target for target in config["verifyTargets"] if target["scriptName"] == "SMC Long-Dip Mobile")
    assert "chartUrl" not in mobile
    assert mobile.get("chartUrl", config["primaryChartUrl"]) == "https://www.tradingview.com/chart/vWgAWyfC/"
    for script_name in ("SMC Event Overlay", "SMC Exit Signal"):
        companion = next(
            target
            for target in config["verifyTargets"]
            if target["scriptName"] == script_name
        )
        assert companion["chartUrl"] == "https://www.tradingview.com/chart/hKHTmKhu/"


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


def test_timed_out_save_never_retries_while_the_first_picker_can_still_settle() -> None:
    """A Promise.race timeout does not cancel its Playwright action."""
    batch = (_REPO_ROOT / "scripts" / "tv_batch_consumer_rollout.ts").read_text(encoding="utf-8")
    saver = (_REPO_ROOT / "scripts" / "tv_save_consumer_source.ts").read_text(encoding="utf-8")
    assert "requireVisibleDeclarationIdentity: true,\n  }).catch" not in saver
    assert "saveSessionTimedOut = isTrackedStepTimeoutError(error) || session.page.isClosed()" in batch
    assert "if (saveSessionTimedOut) break" in batch


def test_transient_binding_verification_failures_are_retried_once() -> None:
    batch = (_REPO_ROOT / "scripts" / "tv_batch_consumer_rollout.ts").read_text(encoding="utf-8")
    assert batch.count("for (let attempt = 1; attempt <= 2; attempt += 1)") == 3


def test_scheduled_run_verifies_actual_saved_source_hashes_without_writing() -> None:
    batch = (_REPO_ROOT / "scripts" / "tv_batch_consumer_rollout.ts").read_text(encoding="utf-8")
    saver = (_REPO_ROOT / "scripts" / "tv_save_consumer_source.ts").read_text(encoding="utf-8")
    assert "sourceVerificationTargets = config.saveTargets" in batch
    assert "verifyConsumerSource(session, target)" in batch
    assert "report.sources.drifted === 0" in batch
    assert "normalizedPineSha256(source)" in saver
    evidence = (
        _REPO_ROOT / "automation/tradingview/lib/tv_consumer_rollout_evidence.ts"
    ).read_text(encoding="utf-8")
    assert 'createHash("sha256")' in evidence
    assert "readEditorContent(session.page" in saver


def test_saved_source_readback_focuses_monaco_input_and_rejects_stale_clipboard() -> None:
    """The clipboard fallback must not turn a failed copy into "verified source".

    Two independent failure modes, both observed in tv-save-consumer-source
    runs (8/8 sources "drifted" on 2026-07-21):

    * clicking a Monaco *container* does not focus its hidden input, so
      Ctrl+A/C grabs a viewport fragment or a stale selection — a healthy
      ~200KB source read back as 735-1,177 bytes;
    * a copy that never lands leaves the previous clipboard content in place,
      which the copy-until-stable check reads as "stable" (it never changes)
      and, absent an expected declaration title, would return as source.

    The marker guard makes that second case fail closed. Structure may change
    (``continue`` vs a negated return) as long as the marker can never be
    returned as source.
    """
    shared = (
        _REPO_ROOT / "automation" / "tradingview" / "lib" / "tv_shared.ts"
    ).read_text(encoding="utf-8")
    readback = shared.split("export async function readEditorContent", 1)[1].split(
        "export async function saveScript", 1
    )[0]
    # Focus the real Monaco input, never just the container.
    assert "candidate.locator('textarea, [contenteditable=\"true\"]')" in readback
    assert "const focused = await input.focus()" in readback
    assert "if (!focused) continue" in readback
    # Pre-seed a marker and never accept it as read-back evidence.
    assert "navigator.clipboard.writeText(marker)" in readback
    assert "if (!seededClipboard) continue" in readback
    assert "if (copied === clipboardMarker) continue" in readback
    # The marker must be rejected BEFORE the stability check can accept it.
    assert readback.index("if (copied === clipboardMarker) continue") < readback.index(
        "copied === previousCopy"
    )
    # Retained from the model-pinning work (#3858/#3866): a grab counts only
    # when two consecutive copies agree AND match this script's declaration.
    assert "copied === previousCopy" in readback
    assert "declarationPattern.test(copied)" in readback


def test_binding_parser_accepts_single_and_double_quoted_pine_labels() -> None:
    # The BUS label parser is the single source of truth shared by the runtime
    # verifier and the build-time packager, so the regex now lives in the shared
    # .mjs module rather than being copied into each consumer.
    parser = (
        _REPO_ROOT / "automation" / "tradingview" / "lib" / "bus_binding_labels.mjs"
    ).read_text(encoding="utf-8")
    assert '(["\'])' in parser
    assert ".map((match) => match[2])" in parser
    verifier = (_REPO_ROOT / "scripts" / "tv_verify_consumer_bindings.ts").read_text(encoding="utf-8")
    assert "parseBusBindingLabels" in verifier


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
        "SMC_Event_Overlay.pine": "SMC Event Overlay",
        "SMC_Exit_Signal.pine": "SMC Exit Signal",
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
    assert dispatch["verify_only"]["default"] is False
    repair = next(s for s in _steps() if s.get("name") == "Controlled repair E2E")
    assert "repair_e2e == 'true'" in repair["if"]
    assert "verify_only != 'true'" in repair["if"]
    assert "scripts/tv_repair_binding_e2e.ts" in repair["run"]
    config = yaml.safe_load(
        (_REPO_ROOT / "automation/tradingview/config/consumer-rollout.json").read_text(encoding="utf-8")
    )
    assert config["repairE2ETarget"]["scriptName"] == "SMC Decision Board"
    e2e = (_REPO_ROOT / "scripts" / "tv_repair_binding_e2e.ts").read_text(encoding="utf-8")
    assert 'setConsumerBindingForTest(session, target, testLabel, "Close")' in e2e
    assert "verifyConsumerBindings(session, target, true)" in e2e


def test_repair_e2e_proves_the_repair_across_a_reload_not_only_in_session() -> None:
    """2026-08-01: the drill could not observe the failure it exists for.

    It drifted, repaired and re-verified inside ONE session, never reloading the
    chart and never saving the layout. But an in-session read was green all
    through the 2026-07-25 incident too -- the rebinds were discarded the moment
    the layout was left. So the drill passed on every day the primary operator
    layout was never saved, which is precisely the regression it is meant to
    catch.

    Both halves must therefore cross a hard reload: the deliberate drift is
    saved and re-read (otherwise the repair has nothing real to fix), and the
    repair is saved and re-read (otherwise "repaired" means only "submitted").
    """
    e2e = (_REPO_ROOT / "scripts" / "tv_repair_binding_e2e.ts").read_text(encoding="utf-8")
    assert "saveChangedChartLayout(session.page)" in e2e
    # gotoChart is a hard page.goto: the reload is what makes the read-back
    # evidence rather than an echo of the session that wrote it.
    # Three in the happy path (open, after the drift save, after the repair
    # save) plus the one in the recovery block, which must also re-read.
    assert e2e.count("gotoChartAndAwaitScript(session.page, chartUrl, target.scriptName)") >= 4
    # And no navigation may bypass the settling wrapper. The wrapper itself
    # calls gotoChart(page, ...), so this only forbids the un-settled form.
    assert "gotoChart(session.page" not in e2e
    # Two DISTINCT failures, one per half. Asserting a shared substring twice
    # would pin only one of them while reading like it covered both.
    assert "drift did not survive the reload" in e2e
    assert "repaired in-session but the repair did not survive the reload" in e2e
    # Persisting a drift is a real exposure between the two saves; failing to
    # undo it must name the chart and the input instead of exiting quietly.
    assert "MANUAL REPAIR REQUIRED" in e2e


def test_repair_e2e_waits_for_the_chart_rather_than_costing_a_rerun() -> None:
    """2026-08-01: the drill's precondition was a timing race, not a check.

    gotoChart resolves on `domcontentloaded` plus a FIXED 3s wait. Sometimes
    TradingView has rebuilt the legend by then and sometimes it has not, so the
    first read died on `Existing chart instance not found` against a healthy
    chart (run 30684930443, 8s in) while the identical retry was green
    (30685141166). The remedy was a whole extra browser run each time.

    So the drill waits for the condition. The wait must use the SAME predicate
    that throws inside verifyConsumerBindings -- waiting on a stricter proxy
    would only relocate the guess -- and a wait that runs out must say how long
    it waited, so a genuinely absent indicator still reads as absent.
    """
    e2e = (_REPO_ROOT / "scripts" / "tv_repair_binding_e2e.ts").read_text(encoding="utf-8")
    verifier = (_REPO_ROOT / "scripts" / "tv_verify_consumer_bindings.ts").read_text(encoding="utf-8")
    # 2026-08-01: the wait moved into tv_shared because a second drill needs the
    # identical one, and two copies of a timing fix is how one of them stays
    # broken. The drill must USE it; the shared module must BE it.
    shared = (_REPO_ROOT / "automation" / "tradingview" / "lib" / "tv_shared.ts").read_text(encoding="utf-8")
    assert "gotoChartAndAwaitScript" in e2e
    assert "export async function gotoChartAndAwaitScript" in shared
    # The coupling is the point: if the verifier ever gates on something else,
    # this pin fails and names the wait that still watches the old signal.
    assert "isScriptVisibleOnChartSurface" in shared
    assert "isScriptVisibleOnChartSurface" in verifier
    assert "Existing chart instance not found" in verifier
    assert "TV_DRILL_SETTLE_TIMEOUT_MS" in shared
    assert "did not surface" in shared


def test_binding_snapshot_is_uploaded_even_when_rollout_fails() -> None:
    upload = next(s for s in _steps() if s.get("name") == "Upload binding snapshot")
    assert upload["with"]["path"] == "artifacts/monitoring/tradingview_consumer_bindings.json"
    publish = next(s for s in _steps() if s.get("name") == "Publish latest binding snapshot")
    assert 'stable_dir="artifacts/monitoring/latest"' in publish["run"]
    assert '"${stable_dir}/tradingview_consumer_bindings.json"' in publish["run"]
    assert "bot/live-tradingview-bindings" in publish["run"]
    # Both still run when the rollout ran and FAILED (run 30700389375 is why
    # the gate is `success() || failure()`, not `success()` alone) -- see
    # test_snapshot_steps_only_run_when_the_rollout_step_actually_executed
    # for the exact-equality pin on the condition itself.
    assert "steps.save.conclusion == 'failure'" in upload["if"]
    assert "steps.save.conclusion == 'failure'" in publish["if"]


def test_publish_step_seeds_the_shared_directory_before_adding_its_own_file() -> None:
    """artifacts/monitoring/latest/ on bot/live-tradingview-bindings is SHARED.

    2026-08-03 (Fix wave 1b): smc-r4-context-readback.yml publishes its own
    tradingview_r4_context_bindings.json to this exact branch, at the same
    shared directory. The old body here built its commit on top of a fresh
    `actions/checkout` (main, which does not carry this bot-branch-only
    directory at all), staged ONLY its own file, and force-pushed — so every
    run of this workflow made that commit the entire directory and silently
    deleted R4's file the moment it became the new tip. R4's fetch would then
    find nothing, report "unknown", and stay permanently red — this
    repository has a documented history with exactly this shape (a gate left
    permanently blind because two producers owned one output).

    Mirrors smc-r4-context-readback.yml's own "Publish latest R4 binding
    snapshot" step (which already carries the symmetric protection for THIS
    file) rather than inventing a second mechanism. Pins the two properties
    that prevent the deletion: the tip is fetched and checked out into the
    shared directory BEFORE this run's own file overlays it, and the WHOLE
    directory (not one explicit filename) is staged, which is what carries
    the seeded sibling file into this run's commit.
    """
    publish = next(s for s in _steps() if s.get("name") == "Publish latest binding snapshot")
    run = publish["run"]

    fetch_idx = run.index("git fetch")
    seed_idx = run.index('git checkout "${expected_sha}" -- "${stable_dir}"')
    copy_idx = run.index('cp "${snapshot}"')
    add_idx = run.index("git add -f")
    commit_idx = run.index("git commit")

    assert fetch_idx < seed_idx < copy_idx < add_idx < commit_idx, (
        "the tip must be fetched, then checked out into the shared directory, BEFORE this "
        "run's own file overlays it and the directory is staged — any other order can commit "
        "a directory missing the sibling producer's file"
    )
    assert 'git add -f "${stable_dir}"' in run
    assert 'git add -f "${stable_dir}/tradingview_consumer_bindings.json"' not in run
    # Must not collide with smc-r4-context-readback.yml's published path —
    # that is exactly the "always unknown" trap this whole change avoids.
    assert "tradingview_r4_context_bindings.json" not in run


def _publish_fragment() -> str:
    """The snapshot publish step's shell, verbatim and COMPLETE — push included.

    Executed rather than string-matched, because what this step does wrong is
    invisible in its text: on 2026-08-06 the automated R1 re-attestation
    (run 31088757063) measured a clean write pass and a clean independent
    verify pass and was then refused by ``scripts/smc_r1_generate_attestation``
    with "write and verify passes ran on different commits". The two passes
    disagreed because THIS step ran between them and its ``git commit`` moved
    the job's HEAD — the published commit ec6f61bde is literally the child of
    c8a33f92f, the commit the write pass reported. A step that pushes a
    snapshot to its own branch must give the checkout back as it found it.
    """
    step = next(
        s for s in _steps() if s.get("name") == "Publish latest binding snapshot"
    )
    return step["run"]


def _sandbox_env(home: Path, **extra: str) -> dict[str, str]:
    """An environment with NO ambient git state in it.

    Inheriting ``os.environ`` here is not a style question. The pre-push hook
    runs this suite with ``GIT_DIR`` pointing at the developer's own
    repository, so an inherited environment sends every fixture command there
    instead of into ``tmp_path``: measured 2026-08-06, ``git init --bare``
    flipped ``core.bare=true`` on the real checkout and the fixture's seed
    commit landed on the branch under test.
    """
    return {"PATH": os.environ["PATH"], "HOME": str(home), **extra}


def _git(*args: str, cwd: Path, env: dict[str, str]) -> str:
    done = subprocess.run(
        ["git", *args], cwd=cwd, env=env, capture_output=True, text=True
    )
    assert done.returncode == 0, f"git {' '.join(args)}: {done.stderr}"
    return done.stdout.strip()


def test_publishing_the_snapshot_leaves_the_jobs_head_where_it_found_it(
    tmp_path: Path,
) -> None:
    """EXECUTED: publish a snapshot twice and prove HEAD never moves.

    The second call also exercises the seed-and-lease path (a non-empty
    ``expected_sha``), so a "fix" that keeps HEAD still by breaking the
    publish itself cannot pass here.
    """
    env = _sandbox_env(tmp_path)
    origin = tmp_path / "origin"
    work = tmp_path / "work"
    origin.mkdir()
    work.mkdir()
    _git("init", "--bare", "-b", "main", ".", cwd=origin, env=env)
    _git("init", "-b", "main", ".", cwd=work, env=env)
    _git("config", "user.email", "t@example.invalid", cwd=work, env=env)
    _git("config", "user.name", "t", cwd=work, env=env)
    (work / "README.md").write_text("proposal\n", encoding="utf-8")
    # Tracked, exactly as in the repo: this run's freshly measured report is an
    # UNCOMMITTED modification of a tracked file, so a restore that reached the
    # working tree would silently swap the measurement for a stale one.
    snapshot = work / "artifacts" / "monitoring" / "tradingview_consumer_bindings.json"
    snapshot.parent.mkdir(parents=True)
    snapshot.write_text('{"stale": true}', encoding="utf-8")
    _git("add", "README.md", str(snapshot.relative_to(work)), cwd=work, env=env)
    _git(
        "commit", "-m", "the proposal commit the passes must agree on",
        cwd=work, env=env,
    )
    head_before = _git("rev-parse", "HEAD", cwd=work, env=env)

    for attempt, payload in enumerate(('{"ok": true}', '{"ok": false}')):
        snapshot.write_text(payload, encoding="utf-8")
        done = subprocess.run(
            ["/bin/bash", "-c", _publish_fragment()],
            cwd=work,
            env=_sandbox_env(
                tmp_path,
                GH_TOKEN="test-token",
                GITHUB_REPOSITORY="skipp-dev/skipp-algo",
                TV_SNAPSHOT_REMOTE=str(origin),
            ),
            capture_output=True,
            text=True,
        )
        assert done.returncode == 0, done.stdout + done.stderr

        assert _git("rev-parse", "HEAD", cwd=work, env=env) == head_before, (
            "the publish step moved the job's HEAD — the re-attestation chain "
            "compares its write and verify passes BY COMMIT, and its evidence "
            "step pushes HEAD to the proposal branch, so a stray commit here "
            "both refuses the attestation and contaminates the PR "
            f"(attempt {attempt + 1})"
        )
        published = _git(
            "show",
            "refs/heads/bot/live-tradingview-bindings:"
            "artifacts/monitoring/latest/tradingview_consumer_bindings.json",
            cwd=origin,
            env=env,
        )
        assert published == payload, "the snapshot must still reach its branch"
        assert snapshot.read_text(encoding="utf-8") == payload, (
            "restoring HEAD must not reach the working tree: the attestation "
            "reads this run's measured report right after this step"
        )


def test_snapshot_steps_only_run_when_the_rollout_step_actually_executed() -> None:
    """2026-08-03: a gate-blocked run publishes a stale GREEN snapshot.

    Both steps used to be `if: always()`. When the operator-window gate
    exits 1 -- before Node, Playwright, or any browser session -- `save`
    (the rollout step) never runs, so there is no fresh snapshot on disk.
    But `artifacts/monitoring/tradingview_consumer_bindings.json` is TRACKED
    IN GIT: the checkout leaves the repository's 2026-07-25 copy in place
    (ok: true, old schema, no executionMode, 7/7 consumers, 0 mismatches),
    and always() found and force-pushed THAT to bot/live-tradingview-bindings
    -- the branch the live overlay daemon polls -- producing a false green on
    a live monitoring surface with no rollout having run at all.

    Gating on `steps.save.conclusion` instead: 'skipped' (the gate refused,
    or any earlier step failed) and 'cancelled' never opened a browser, so
    neither has anything fresh to publish and both are excluded. 'success'
    and 'failure' both did open a browser and both keep the outer always()
    so a LATER optional step failing (Controlled repair E2E, the R1 rollback
    drill) still lets the snapshot through -- unchanged from before.
    """
    expected_if = "${{ always() && (steps.save.conclusion == 'success' || steps.save.conclusion == 'failure') }}"
    upload = next(s for s in _steps() if s.get("name") == "Upload binding snapshot")
    assert upload["if"] == expected_if
    publish = next(s for s in _steps() if s.get("name") == "Publish latest binding snapshot")
    assert publish["if"] == expected_if
    save_step = next(s for s in _steps() if s.get("name", "").startswith("Save or read-only verify"))
    assert save_step["id"] == "save"


def test_force_rebind_is_opt_in_and_reaches_the_rollout_script() -> None:
    """The dispatch input must not be decoration: it has to reach the script that reads it.

    Mutating away any single link below (input, env plumb, or the env read) has to fail
    this test, otherwise `force_rebind=true` would silently run a read-only verification.
    """
    dispatch = (_load().get("on") or _load().get(True))["workflow_dispatch"]["inputs"]
    assert dispatch["force_rebind"]["default"] is False, "rebinding must never be the default"

    rollout = next(s for s in _steps() if "scripts/tv_batch_consumer_rollout.ts" in s.get("run", ""))
    # 2026-07-22: the workflow_run (post-library-refresh) chain forces rebind
    # ON — refreshChartScriptInstance replaces the parent instance, which
    # invalidates every child BUS parent id. Dispatch stays opt-in; schedule
    # stays read-only 'false'.
    # 2026-08-04 (reattest chain): the automated re-attestation saves a
    # re-pinned companion source and therefore needs the same refresh+rebind
    # pair as the workflow_run chain; the dispatch/schedule arms are unchanged.
    assert rollout["env"]["TV_FORCE_REBIND"] == (
        "${{ (github.event_name == 'workflow_run' || "
        "github.event.inputs.reattest == 'true') && 'true' || "
        "github.event_name == 'workflow_dispatch' && "
        "github.event.inputs.force_rebind || 'false' }}"
    )

    batch = (_REPO_ROOT / "scripts" / "tv_batch_consumer_rollout.ts").read_text(encoding="utf-8")
    evidence = (
        _REPO_ROOT / "automation/tradingview/lib/tv_consumer_rollout_evidence.ts"
    ).read_text(encoding="utf-8")
    assert "env.TV_FORCE_REBIND" in evidence
    assert "executionPlan.repairBindings" in batch
    # 2026-08-01: pin the dataflow rather than an occurrence count. The old
    # `count(...) >= 3` pinned a shape in which the plan was re-read at each
    # rebind call site; the plan now seeds a local that the run may narrow to
    # false when a layout is abandoned (never widen -- see
    # test_a_layout_is_saved_whole_or_discarded_whole). What must not regress is
    # that TV_FORCE_REBIND still reaches BOTH arguments of the rebind call, so a
    # forced rebind cannot be dropped on the way in.
    assert "let repairBindings = executionPlan.repairBindings;" in batch
    assert "verifyConsumerBindings(session, target, repairBindings, repairBindings)" in batch


def test_force_rebind_persists_the_layout_so_bindings_survive_reload() -> None:
    """A force-rebind that isn't saved to the layout reverts on reload.

    2026-07-25: every force_rebind run read its own session back as bound
    (mismatches:0), but a fresh read-only session saw all sources on "Close" —
    the per-consumer settings "submit" mutates only the in-session instance and
    never persisted. The rollout must save the chart layout after rebinding, and
    a save failure must gate report.ok rather than reporting green.
    """
    batch = (_REPO_ROOT / "scripts" / "tv_batch_consumer_rollout.ts").read_text(encoding="utf-8")
    assert "saveChangedChartLayout(session.page)" in batch
    # 2026-07-31: the single trailing save was replaced by a per-LAYOUT decision.
    # The old shape --
    #   if (executionPlan.saveLayout && report.bindings.failed.length === 0)
    # -- ran once, on whichever chart the loop ended on, and persisted only
    # that one. Because gotoChart is a hard page.goto, the reload had ALREADY
    # discarded the rebinds of the layout being left, so the other layouts
    # could not be saved afterwards either: navigating back would have saved
    # the reverted state. With the shipped config that silently dropped the
    # seven consumers on the primary operator chart.
    assert "groupTargetsByLayout(config.verifyTargets, config.primaryChartUrl)" in batch
    # A failed save lands in bindings.failed, which gates report.ok below.
    assert '"chart-layout' in batch
    # Nothing may be reported green having persisted a strict subset.
    assert "resolveLayoutSavePoints(config.verifyTargets, config.primaryChartUrl)" in batch
    assert "layouts never saved" in batch


def test_a_layout_is_saved_whole_or_discarded_whole() -> None:
    """2026-08-01: saving at every boundary still persisted PARTIAL repairs.

    Saving once per layout stops whole layouts from being dropped, but the save
    was unconditional: repair consumers 1-4 of the primary chart, fail on 5, and
    the operator's traded chart was persisted half rebound.

    The layout is the unit that commits or discards atomically -- one save
    persists every rebind on it, one reload discards every rebind on it -- so
    the decision belongs to the layout, not the target. A layout is saved only
    when every target on it came back clean; otherwise it is abandoned and the
    reload rolls it back exactly.

    After an abandoned layout the run stops mutating, so what is persisted is
    always a complete PREFIX of the rollout. The shipped config visits the
    primary operator chart first, so a late failure leaves the traded chart
    repaired and the rest untouched, never the reverse.
    """
    batch = (_REPO_ROOT / "scripts" / "tv_batch_consumer_rollout.ts").read_text(encoding="utf-8")

    # Repair is narrowed by a mutable local, never widened; the immutable plan
    # still bounds the run because this only ever assigns false.
    assert "let repairBindings = executionPlan.repairBindings;" in batch
    assert "verifyConsumerBindings(session, target, repairBindings, repairBindings)" in batch
    assert batch.count("repairBindings = false;") >= 2, (
        "repair stops both on an abandoned layout and on an unconfirmed save"
    )
    assert "repairBindings = true" not in batch, "repair may only ever be narrowed mid-run"

    # The completeness predicate must match what makes report.ok true, per
    # target. result.ok additionally carries unknownParentRuntimeError, which is
    # evidence only: the residual window after a repair still collects
    # dead-parent errors from the consumers this run has NOT repaired yet, so
    # abandoning on it would abandon every layout of a healthy rollout.
    assert "if (!result || result.mismatches.length > 0) layoutRepairedCleanly = false;" in batch
    assert "!result.ok" not in batch

    # An incomplete layout is discarded, not saved, and recorded as such.
    assert "if (!layoutRepairedCleanly) {" in batch
    assert "abandonedChartUrls.push(layout.chartUrl);" in batch
    assert "report.mutations.abandonedChartUrls = abandonedChartUrls;" in batch
    # The rollback is the reload itself -- the same mechanism that used to
    # revert rebinds silently.
    assert "await gotoChart(session.page, layout.chartUrl).catch(() => undefined);" in batch

    # A layout that was never mutated is not a save point.
    assert "const mutatingLayout = repairBindings;" in batch
    assert "if (!executionPlan.saveLayout || !mutatingLayout) continue;" in batch

    shared = (_REPO_ROOT / "automation" / "tradingview" / "lib" / "tv_shared.ts").read_text(encoding="utf-8")
    assert "export async function saveChangedChartLayout(page: Page)" in shared
    assert 'data-qa-id="header-toolbar-save-load"' in shared
    assert "all changes saved" in shared


def test_producer_refresh_is_explicit_and_requires_full_rebind() -> None:
    dispatch = (_load().get("on") or _load().get(True))["workflow_dispatch"]["inputs"]
    assert dispatch["refresh_producer"]["default"] is False
    rollout = next(s for s in _steps() if "scripts/tv_batch_consumer_rollout.ts" in s.get("run", ""))
    assert "github.event.inputs.refresh_producer" in rollout["env"]["TV_REFRESH_PRODUCER"]
    batch = (_REPO_ROOT / "scripts" / "tv_batch_consumer_rollout.ts").read_text(encoding="utf-8")
    evidence = (
        _REPO_ROOT / "automation/tradingview/lib/tv_consumer_rollout_evidence.ts"
    ).read_text(encoding="utf-8")
    assert "env.TV_REFRESH_PRODUCER" in evidence
    assert "refreshProducer && !forceRebind" in evidence
    assert "refreshChartScriptInstance(session.page, config.producerName)" in batch


def test_verify_only_mode_structurally_gates_every_mutation_and_records_provenance() -> None:
    batch = (_REPO_ROOT / "scripts" / "tv_batch_consumer_rollout.ts").read_text(encoding="utf-8")
    evidence = (
        _REPO_ROOT / "automation/tradingview/lib/tv_consumer_rollout_evidence.ts"
    ).read_text(encoding="utf-8")
    assert 'args.includes("--verify-only")' in evidence
    assert 'mode: "verify-only"' in evidence
    assert "saveSources: false" in evidence
    assert "refreshProducer: false" in evidence
    assert "repairBindings: false" in evidence
    assert "saveLayout: false" in evidence
    assert "if (executionPlan.saveSources)" in batch
    assert "if (report.save.failed.length === 0 && executionPlan.refreshProducer)" in batch
    assert "if (!executionPlan.saveLayout || !mutatingLayout) continue;" in batch
    assert "schemaVersion: 2" in batch
    assert "repoCommitSha" in batch
    assert "rolloutConfigSha256" in batch
    assert "inputsMatchCommit" in batch
    assert "repositoryExpected.libraryRelease.matches" in batch
    assert "tradingViewObserved" in batch
    assert "mutations" in batch


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
    """The hidden WebSocket study_error must sink `ok` and exit non-zero."""
    verifier = (_REPO_ROOT / "scripts" / "tv_verify_consumer_bindings.ts").read_text(encoding="utf-8")
    assert "session.runtimeErrors.snapshot()" in verifier
    assert "/unknown parent id/i.test(error.message)" in verifier
    assert "locator(\"body\").innerText()" not in verifier
    assert "ok: mismatches.length === 0 && !unknownParentRuntimeError," in verifier
    assert "if (result.unknownParentRuntimeError) {" in verifier
    # The session-wide monitor must be cleared AFTER the committed rebind so a
    # successful repair is not sunk by its own pre-repair "unknown parent id"
    # (nor by errors from other not-yet-repaired consumers on the same session).
    assert "session.runtimeErrors.clear()" in verifier


def test_verifier_blocks_ambiguous_multi_pane_layouts_before_mutation() -> None:
    verifier = (_REPO_ROOT / "scripts" / "tv_verify_consumer_bindings.ts").read_text(encoding="utf-8")
    # Instance counting must NOT go through findLegendRowWrappers: it dedupes
    # matched wrappers by legend text, so two identically-named scripts collapse
    # to one and the ambiguity guard never fires. countChartScriptInstances
    # counts each legend row independently.
    assert "countChartScriptInstances(session.page, producerName)" in verifier
    assert "countChartScriptInstances(session.page, target.scriptName)" in verifier
    assert "findLegendRowWrappers" not in verifier
    assert "Ambiguous multi-pane SMC layout" in verifier


def test_cache_runs_on_native_node24_without_force_override() -> None:
    """This workflow must not need the Node-24 force override, so its cache
    action has to declare ``node24`` itself.

    The pin moved v5.0.5 → v6.1.0 on 2026-08-04 with #4425, and the property
    was re-measured rather than assumed: `action.yml` at
    55cc8345863c7cc4c66a329aec7e433d2d1c52a9 still declares `using: 'node24'`,
    and that SHA carries both the `v6` and `v6.1.0` tags upstream. Had v6
    regressed to node20 this assertion would have had to hold the old pin
    instead — the bump is only safe BECAUSE that was checked.
    """
    workflow = _WF_PATH.read_text(encoding="utf-8")
    assert "actions/cache@55cc8345863c7cc4c66a329aec7e433d2d1c52a9 # v6" in workflow
    assert "FORCE_JAVASCRIPT_ACTIONS_TO_NODE24" not in workflow
    assert "actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a # v7" in workflow


def _save_workflow_text() -> str:
    return (
        _REPO_ROOT / ".github" / "workflows" / "tv-save-consumer-source.yml"
    ).read_text(encoding="utf-8")


def test_library_refresh_completion_triggers_writing_save() -> None:
    """Closing the last manual gap in repo->TV: after every library refresh the
    consumers must be SAVED (not just cron-verified read-only) and the applied
    Suite chart instance must be refreshed, else the on-chart instance stays
    frozen on the old library version until an operator re-adds it by hand
    (the 'Library 9d alt' incident, 2026-07-22). Pine itself cannot help here:
    imports are mandatorily version-pinned and applied instances never
    re-resolve, so the automation owns the refresh."""
    text = _save_workflow_text()
    assert "workflow_run:" in text, "save workflow must chain off the library refresh"
    assert "- smc-library-refresh" in text or '"smc-library-refresh"' in text, (
        "workflow_run must reference the smc-library-refresh workflow by name"
    )
    # Only a SUCCESSFUL refresh may trigger a writing save: a failed refresh
    # means the repo pin/library state is unknown — saving then could roll
    # consumers onto a half-published state.
    assert "github.event.workflow_run.conclusion == 'success'" in text


def test_refresh_triggered_save_checks_out_the_refresh_commit_not_a_moving_tip() -> None:
    """2026-08-01: chaining off the workflow raced the commit it was chaining to.

    smc-library-refresh does not push its output. It opens
    ``bot/library-refresh-<run id>-*`` and auto-merges it, which lands SECONDS
    after the workflow completes -- and ``workflow_run`` fires on completion.
    Measured: this chain started 02:55:28Z, the refresh PR merged 02:55:48Z. So
    both the event's head_sha (the parent) and main's tip at checkout time were
    the pre-refresh tree, the run re-saved the OLD sources to TradingView, and
    it reported ``sources.drifted=0`` because it verified them against the OLD
    repo. Every consumer stayed one library version behind until a hand
    dispatch.

    The run could not have noticed: rollout provenance compares
    ``library.expectedVersion`` to ``library.publishedVersion`` and both are
    fields of the same manifest file in the checked-out tree, so a stale tree
    agrees with itself.

    Hence: resolve the refresh COMMIT and check that out. When the resolution
    cannot be trusted the job must fail, because continuing is precisely the
    silent-stale-write this closes.
    """
    steps = _steps()
    names = [step.get("name") for step in steps]
    assert "Await the refresh commit on main" in names
    # It must run BEFORE checkout, or the checkout has nothing to consume.
    assert names.index("Await the refresh commit on main") < names.index("Checkout")

    await_step = next(s for s in steps if s.get("name") == "Await the refresh commit on main")
    assert await_step["if"] == "github.event_name == 'workflow_run'"
    run = await_step["run"]
    # Identified by the refresh run id the event carries, not guessed from timing.
    assert "bot/library-refresh-${REFRESH_RUN_ID}-" in run
    assert "github.event.workflow_run.id" in await_step["env"]["REFRESH_RUN_ID"]
    # Both untrustworthy outcomes are fatal. A `|| true` here would restore the
    # old behaviour while looking like it had been fixed.
    assert run.count("exit 1") >= 2
    assert "was closed without merging" in run
    assert "did not merge within" in run
    # An absent PR is a real no-op: the refresh only opens one when the
    # regeneration changed something.
    assert "no post-publish changes" in run

    checkout = next(s for s in steps if s.get("name") == "Checkout")
    ref = checkout["with"]["ref"]
    assert "steps.refresh_commit.outputs.sha" in ref
    # The resolved commit must win over the moving branch tip, not the reverse.
    assert ref.index("steps.refresh_commit.outputs.sha") < ref.index("head_branch")

    # Reading the PR needs the scope; without it the step 404s and the job fails
    # closed rather than silently falling back.
    assert _load()["permissions"]["pull-requests"] == "read"


def test_refresh_triggered_save_enables_producer_refresh_and_rebind() -> None:
    """The workflow_run path must run with TV_REFRESH_PRODUCER=true AND
    TV_FORCE_REBIND=true: refreshChartScriptInstance replaces the applied
    parent instance, which invalidates every child BUS parent id, so the
    rollout script itself hard-fails on refresh-without-rebind. The cron
    stays read-only-verify and the dispatch inputs keep working."""
    text = _save_workflow_text()
    assert (
        "(github.event_name == 'workflow_run' || "
        "github.event.inputs.reattest == 'true') && 'true'" in text
    ), (
        "both TV_FORCE_REBIND and TV_REFRESH_PRODUCER must resolve to 'true' "
        "on the workflow_run path (and on a reattest dispatch, which saves a "
        "re-pinned companion source)"
    )
    force_rebind_line = next(
        line for line in text.splitlines() if "TV_FORCE_REBIND:" in line
    )
    refresh_producer_line = next(
        line for line in text.splitlines() if "TV_REFRESH_PRODUCER:" in line
    )
    for line in (force_rebind_line, refresh_producer_line):
        # 2026-08-04: workflow_run OR a reattest dispatch -- both save a
        # source whose parent instance must be refreshed and re-bound.
        assert (
            "(github.event_name == 'workflow_run' || "
            "github.event.inputs.reattest == 'true') && 'true'" in line
        ), line
        # dispatch inputs must still be honoured after the workflow_run branch
        assert "github.event.inputs.force_rebind" in line or (
            "github.event.inputs.refresh_producer" in line
        ), line
    # The read-only cron contract stays: schedule keeps the empty mapping.
    assert "github.event_name == 'schedule' && '[]'" in text


def test_the_attestation_holdback_runs_on_every_trigger_before_the_browser_opens() -> None:
    """2026-08-01: the un-attestation arrived through the workflow_run chain.

    #4286 guards the pull-request path. The chained save after a successful
    library refresh is not a pull request, so it walked straight past. Gating
    only the manual dispatch would leave the door that was actually used, and
    checking after the save would report a push that already happened.
    """
    steps = _steps()
    names = [step.get("name") for step in steps]
    detect = "Detect R1-attested sources this save would un-attest"
    guard = next(s for s in steps if s.get("name") == detect)

    assert "python -m scripts.check_tv_unattested_sources" in guard["run"].replace("python3", "python")
    # A step output, not $GITHUB_ENV: writing the environment file is a zizmor
    # `github-env` high finding, and it also let the value reach the rollout
    # implicitly -- so nothing pinned that it arrived at all.
    assert 'echo "unattested=${unattested}" >> "$GITHUB_OUTPUT"' in guard["run"]
    assert "GITHUB_ENV" not in guard["run"]
    # No `if:` at all -- schedule, dispatch and the workflow_run chain alike.
    assert "if" not in guard, "the detection must not be conditional on the trigger"
    assert names.index(detect) < names.index(
        "Save or read-only verify consumers in one browser session"
    )

    # The load-bearing wiring: a detection the rollout never receives would
    # leave the report green while the evidence goes stale.
    save = next(s for s in steps if s.get("name") == "Save or read-only verify consumers in one browser session")
    assert save["env"]["TV_UNATTESTED_SOURCES"] == "${{ steps.attestation.outputs.unattested }}"
    assert guard["id"] == "attestation"


def test_an_unattested_save_turns_the_run_red_after_the_snapshot_is_published() -> None:
    steps = _steps()
    names = [step.get("name") for step in steps]
    fail_step = "Fail the run when an R1-attested source was saved un-attested"
    fail = next(s for s in steps if s.get("name") == fail_step)

    assert "exit 1" in fail["run"]
    assert "steps.attestation.outputs.unattested != '[]'" in fail["if"]
    # Not always(): this step reports the un-attestation, it must not re-report
    # an unrelated failure as an attestation problem.
    assert "always()" not in fail["if"]
    # Last, so the binding snapshot is still uploaded and published.
    assert names.index(fail_step) > names.index("Publish latest binding snapshot")
    # The never-edit-the-artifact prohibition must reach the job summary. It
    # used to be pinned here as the literal phrase "falsifies a measurement",
    # which pinned a HAND-TYPED copy in place — and that copy then diverged
    # from scripts/check_tv_unattested_sources.RESOLUTION, which the same run's
    # stderr renders. The pin now follows the rendered constant instead; see
    # test_the_un_attestation_remedy_is_rendered_from_the_shared_constant.
    from scripts.check_tv_unattested_sources import RESOLUTION

    assert "RESOLUTION" in fail["run"]
    assert "replaces a measurement with a fabrication" in RESOLUTION


def test_the_rollout_reports_unattested_saves_without_skipping_them() -> None:
    """Operator decision 2026-08-01: save anyway, report loudly.

    Holding the drifted targets back was built first and dropped: it keeps the
    evidence literally true while freezing those scripts on an old pinned
    library as the producer moves on. So nothing may filter saveTargets, and
    the report has to carry the fact instead.
    """
    batch = (_REPO_ROOT / "scripts" / "tv_batch_consumer_rollout.ts").read_text(encoding="utf-8")

    override = batch.index("TV_CONSUMER_MAPPING_JSON")
    detected = batch.index("TV_UNATTESTED_SOURCES")
    assert override < detected, "the report must describe the targets the mapping override left"
    assert "savedWithoutAttestation" in batch
    # No skipping: a filter that drops these from saveTargets is the policy
    # that was rejected, and it would silently reintroduce itself here.
    assert "config.saveTargets = config.saveTargets.filter" not in batch
    # An un-attested save writes exactly what the repository holds, so every
    # other ok clause stays satisfied. This one carries the red alone.
    assert "report.ok = report.mutations.savedWithoutAttestation.length === 0" in batch


def test_the_r1_rollback_drill_is_opt_in_and_crosses_a_reload_on_both_halves() -> None:
    """The gate the 2026-08-01 re-attestation had to leave open (#4290).

    The 2026-07-29 rollback was performed by hand; nothing could repeat it. As
    with the repair drill (#4289), an in-session read proves only that the UI
    accepted a click -- so the removal must survive a reload before the restore
    can prove anything, and the restore must survive one before it may be
    called restored.
    """
    dispatch = (_load().get("on") or _load().get(True))["workflow_dispatch"]["inputs"]
    assert dispatch["r1_rollback_drill"]["default"] is False

    drill_step = next(s for s in _steps() if s.get("name") == "R1 companion rollback drill")
    assert "r1_rollback_drill == 'true'" in drill_step["if"]
    assert "verify_only != 'true'" in drill_step["if"]
    assert "github.event_name == 'workflow_dispatch'" in drill_step["if"]
    assert "scripts/tv_r1_companion_rollback_drill.ts" in drill_step["run"]

    drill = (_REPO_ROOT / "scripts" / "tv_r1_companion_rollback_drill.ts").read_text(encoding="utf-8")
    assert "saveChangedChartLayout(session.page)" in drill
    # Open, after the removal save, after the restore save, plus the recovery
    # block -- the wrapper calls a hard page.goto, which is what makes the
    # read-back evidence rather than an echo of the session that wrote it.
    assert drill.count("gotoChartAndAwaitScript(session.page, chartUrl") >= 4
    # No navigation may bypass the settling wrapper.
    assert "gotoChart(session.page" not in drill
    # Two DISTINCT failures, one per half.
    assert "removal did not survive the reload" in drill
    assert "restored in-session but the layout came back without" in drill
    # A rollback that takes the producer with it is not a rollback.
    assert "removed more than the companions" in drill
    # Leaving the layout without its companions must be loud, not silent.
    assert "MANUAL REPAIR REQUIRED" in drill


def test_the_rollback_drill_settles_on_the_producer_before_reading_absence() -> None:
    """The removal half asserts two scripts are GONE, which is the fragile direction.

    On a chart whose legend TradingView has not rebuilt yet, absence is
    indistinguishable from "not drawn" -- so the assertion would pass on a
    layout that still carries both companions, and the restore afterwards would
    prove nothing. Waiting for the companions themselves is impossible here (they
    are supposed to be gone), so the wait is on the producer, which is never
    removed and is therefore a real settling signal.

    The repair drill (#4295) hit the same race in the easier direction: there an
    unsettled chart merely threw. Here it would have passed.
    """
    drill = (_REPO_ROOT / "scripts" / "tv_r1_companion_rollback_drill.ts").read_text(encoding="utf-8")

    # Anchored on the removal itself, not on "the first saveChangedChartLayout
    # in the file". The save is no longer unique to this half -- the restore
    # path saves too -- and a helper moved above main() would silently point
    # this anchor at a different save, leaving the ordering assertion true for
    # the wrong reason.
    removal = drill.index("companionsRemoved = true;\n    await saveChangedChartLayout(session.page);")
    absence_read = drill.index("if (await isScriptVisibleOnChartSurface(session.page, name)) stillPresent.push(name);")
    settle = drill.index("gotoChartAndAwaitScript(session.page, chartUrl, config.producerName);", removal)
    assert removal < settle < absence_read, (
        "the absence read must come after a wait for the producer, not straight after the save"
    )


def test_the_restore_uses_the_insertion_path_that_actually_inserts() -> None:
    """Run 30700389375 removed both companions and could not put them back.

    The restore drove the indicators dialog. Its row locator reported no visible
    candidate, it fell back to the keyboard, and that dialog does not commit on
    Enter -- the footer button reads "Select". Four attempts logged
    ``add-to-chart-indicators-no-visible-script`` while the step still reported
    ok, and the managed layout stayed empty. The producer refresh inserts
    through the Pine editor instead, on every run, and that is the path here.
    """
    drill = (_REPO_ROOT / "scripts" / "tv_r1_companion_rollback_drill.ts").read_text(encoding="utf-8")

    assert "addExistingScriptToChartViaIndicators" not in drill
    assert "await refreshChartScriptInstance(session.page, name);" in drill
    # Presence is read from the chart, not taken from the insertion's own word.
    assert "if (await isScriptVisibleOnChartSurface(session.page, name)) restored.push(name);" in drill

    # A rebind against an instance that is not on the chart throws "Existing
    # chart instance not found", which reads as a binding fault and hides the
    # failed insertion underneath it. That is how the run reported itself.
    guard = drill.index("if (restored.length !== COMPANIONS.length) return restored;")
    rebind = drill.index("await verifyAll(session, targets, true);")
    assert guard < rebind


def test_repair_mode_can_restore_a_layout_the_drill_left_empty() -> None:
    """Re-running the full drill cannot repair its own damage.

    With the companions already gone it fails the baseline precondition, which
    is BEFORE ``companionsRemoved`` is set -- so the recovery block never runs
    and the layout stays empty. Run 30700389375 needed exactly this path and the
    repository did not have it.
    """
    dispatch = (_load().get("on") or _load().get(True))["workflow_dispatch"]["inputs"]
    assert dispatch["r1_restore_companions"]["default"] is False

    drill_step = next(s for s in _steps() if s.get("name") == "R1 companion rollback drill")
    assert "r1_restore_companions == 'true'" in drill_step["if"]
    assert "verify_only != 'true'" in drill_step["if"]
    assert drill_step["env"]["TV_DRILL_RESTORE_ONLY"] == "${{ github.event.inputs.r1_restore_companions }}"


def test_repair_survives_the_red_verification_it_exists_to_repair() -> None:
    """Run 30701657039: the repair was skipped by the damage it was dispatched for.

    With both companions missing, the save/verify step reports "Existing chart
    instance not found" for each and fails. A repair step that only runs after a
    green step is therefore unreachable in precisely the situation it was built
    for. The rollback drill keeps the opposite rule: a red verification means the
    layout is not in the state its baseline assumes.
    """
    drill_step = next(s for s in _steps() if s.get("name") == "R1 companion rollback drill")
    condition = " ".join(drill_step["if"].split())

    assert "!cancelled()" in condition
    assert (
        "github.event.inputs.r1_restore_companions == 'true' && "
        "(steps.save.conclusion == 'success' || steps.save.conclusion == 'failure')"
    ) in condition
    assert (
        "github.event.inputs.r1_rollback_drill == 'true' && steps.save.conclusion == 'success'"
    ) in condition
    # Not always(): with an earlier step red the save never ran, there is no
    # browser session, and the drill would only add a misleading second failure.
    assert "always()" not in condition
    # The step it depends on has to keep the id the condition reads.
    save_step = next(s for s in _steps() if s.get("name", "").startswith("Save or read-only verify"))
    assert save_step["id"] == "save"

    drill = (_REPO_ROOT / "scripts" / "tv_r1_companion_rollback_drill.ts").read_text(encoding="utf-8")
    assert 'process.env.TV_DRILL_RESTORE_ONLY ?? ""' in drill
    # The repair half arms the recovery block before it touches anything, so a
    # failed restore is still announced rather than exiting quietly.
    restore_only = drill.index("if (restoreOnly) {")
    arm = drill.index("companionsRemoved = true;", restore_only)
    restore = drill.index("await restoreCompanions(session, targets);", restore_only)
    assert restore_only < arm < restore

    # There is no live baseline in repair mode -- the companions are gone, so a
    # measured baseline would read zero and any comparison against it would pass
    # whatever came back. The number comes from the registered evidence instead.
    assert "attestedBindingCount()" in drill
    assert "tradingView?.bindingsChecked" in drill
    assert "smc_r1_live_rollout_evidence_" in drill


_GATE = "Refuse to mutate inside the operator's TradingView window"


def test_operator_window_gate_runs_before_the_expensive_setup() -> None:
    """A refusal must cost seconds, not a Playwright install.

    Placed after Checkout (it needs the script) and before Set up Node, so an
    open window ends the run in about a second instead of after three minutes
    of npm and browser downloads.
    """
    names = [step.get("name", "") for step in _steps()]
    assert _GATE in names, f"missing step: {_GATE}"
    assert names.index("Checkout") < names.index(_GATE) < names.index("Set up Node")


def test_operator_window_gate_exempts_read_only_runs() -> None:
    """An open window must not suppress the verification that makes it safe.

    Exact equality pin: any edit to the condition — including swapping the
    AND operator to OR — now forces a deliberate test change instead of
    passing silently. This catches the recurring failure mode of confusing
    AND/OR logic.

    Read-only runs write nothing, so they are never gated. The condition
    classifies the trigger paths exactly as the rollout step's TV_VERIFY_ONLY
    expression does: schedule is read-only, a dispatch with verify_only=true is
    read-only, and everything else -- including the workflow_run refresh chain,
    which is how 2026-08-01 reached the account -- mutates.
    """
    step = next(s for s in _steps() if s.get("name") == _GATE)
    condition = step["if"]
    assert condition == "${{ github.event_name != 'schedule' && github.event.inputs.verify_only != 'true' }}"
    assert step["env"]["TV_OPERATOR_ACTIVE"] == "${{ vars.TV_OPERATOR_ACTIVE }}"
    assert "scripts.check_tv_operator_window" in step["run"]


_BASELINE = "Fetch the published binding baseline"


def test_baseline_fetch_reads_the_published_branch_and_precedes_the_rollout() -> None:
    names = [step.get("name", "") for step in _steps()]
    assert _BASELINE in names, f"missing step: {_BASELINE}"
    rollout = next(
        i for i, s in enumerate(_steps()) if "scripts/tv_batch_consumer_rollout.ts" in s.get("run", "")
    )
    assert names.index(_BASELINE) < rollout

    step = next(s for s in _steps() if s.get("name") == _BASELINE)
    assert "bot/live-tradingview-bindings" in step["run"]
    assert "artifacts/monitoring/previous/tradingview_consumer_bindings.json" in step["run"]
    # Unconditional as of 2026-08-03 (Finding 3): a read-only run now compares
    # its own verification reading against the baseline too (report-only), so
    # it needs one fetched just as much as a mutating run does. See
    # test_the_three_trigger_classifying_conditions_are_pinned_and_may_now_differ.
    assert "if" not in step, "the baseline fetch must run on every trigger, not only mutating ones"


def test_the_three_trigger_classifying_conditions_are_pinned_and_may_now_differ() -> None:
    """Three expressions classify every trigger path the same way, or must not.

    The operator-window gate's `if:`, the baseline-fetch step's `if:`, and the
    rollout step's TV_VERIFY_ONLY env expression all decide "is this trigger
    read-only or mutating". Before 2026-08-03 all three agreed exactly
    (mutating-only). Finding 3 widened ONLY the fetch condition -- read-only
    runs now fetch a baseline to compare their own verification reading
    against (report-only, report.ok stays ungated by it) -- so it no longer
    equals the other two. Pinning each one here by exact equality, rather
    than by cross-checking them against each other, means a future edit to
    any single one of them fails HERE instead of silently drifting the three
    apart.
    """
    gate = next(s for s in _steps() if s.get("name") == _GATE)
    fetch = next(s for s in _steps() if s.get("name") == _BASELINE)
    rollout = next(s for s in _steps() if "scripts/tv_batch_consumer_rollout.ts" in s.get("run", ""))

    # Gate: mutating triggers only (schedule and dispatch verify_only=true are
    # exempt). Gating a read-only run would let an open operator window
    # suppress the very verification that makes declaring the window safe.
    assert gate["if"] == "${{ github.event_name != 'schedule' && github.event.inputs.verify_only != 'true' }}"

    # Fetch: every trigger, unconditionally. A read-only run compares too now
    # (report-only), so it needs the baseline on disk exactly as much as a
    # mutating run that will gate report.ok on the comparison.
    assert "if" not in fetch

    # TV_VERIFY_ONLY: the execution-mode boundary the rollout script itself
    # reads via executionPlan.mode, deciding whether to save/refresh/rebind/
    # save-layout at all. This one must keep classifying EXACTLY
    # schedule + dispatch(verify_only=true) as read-only -- widening it the
    # way the fetch condition was widened would turn a read-only trigger into
    # a writing one, which is a materially different kind of mistake than an
    # under-fetched baseline.
    assert rollout["env"]["TV_VERIFY_ONLY"] == (
        "${{ github.event_name == 'schedule' && 'true' || "
        "github.event_name == 'workflow_dispatch' && github.event.inputs.verify_only || 'false' }}"
    )


def test_a_missing_baseline_warns_and_leaves_no_file_instead_of_failing(tmp_path: Path) -> None:
    """Ensures the step gracefully handles a missing baseline by exiting 0 with a warning.

    The previous grep-based check ("exit 1" not in step["run"]) could not detect
    differently-spelled failures like `exit 2` or `false`. This test actually
    executes the script to verify it exits cleanly even when the baseline fetch
    fails. A red step here would report a failure it never measured; the rollout
    already turns an absent baseline into "unknown" and decides verdict downstream.
    """
    # Extract the script from the workflow
    step = next(s for s in _steps() if s.get("name") == _BASELINE)
    script = step["run"]

    # Create a mock gh command that exits 1 (simulating missing baseline)
    mock_gh_dir = tmp_path / "mock_bin"
    mock_gh_dir.mkdir()
    mock_gh = mock_gh_dir / "gh"
    mock_gh.write_text("#!/bin/bash\nexit 1\n", encoding="utf-8")
    mock_gh.chmod(0o755)

    # Create a working directory for the script
    work_dir = tmp_path / "work"
    work_dir.mkdir()

    # Run the script with the mock gh in PATH
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

    # Assertions
    assert result.returncode == 0, f"Script failed with exit code {result.returncode}: {result.stderr}"
    assert "::warning::" in result.stdout, f"No warning found in stdout: {result.stdout}"
    baseline_file = work_dir / "artifacts/monitoring/previous/tradingview_consumer_bindings.json"
    assert not baseline_file.exists(), f"Baseline file should not exist when fetch fails, but found: {baseline_file}"


def test_the_un_attestation_remedy_is_rendered_from_the_shared_constant() -> None:
    """One run must not state one remedy twice, in two wordings.

    The "Detect R1-attested sources this save would un-attest" step runs
    ``scripts/check_tv_unattested_sources``, whose stderr renders ``_REMEDY``
    — which now interpolates the shared :data:`RESOLUTION`. The failing step
    below writes the *job summary*, which the stderr never reaches, so the
    block has to exist. It must be RENDERED from the same constant rather than
    hand-typed.

    It was hand-typed, and it had already drifted: after ``RESOLUTION`` was
    extracted and corrected, this block still carried the pre-extraction
    wording ("re-run to push the attested content back", "that falsifies a
    measurement rather than repeating it"), so a single save run printed two
    different descriptions of one remedy. That is the
    hand-maintained-duplicate-goes-stale class the R1 gating work exists to
    close, one step downstream of where it was closed.
    """
    from scripts.check_tv_unattested_sources import RESOLUTION

    step = next(
        s
        for s in _steps()
        if str(s.get("name", "")).startswith("Fail the run when an R1-attested")
    )
    run = str(step["run"])

    # COMMENTS STRIPPED FIRST. Measured 2026-08-04 on the landed PR: deleting
    # the real command substitution, replacing it with `resolution="See the step
    # log."`, and leaving two comments that happened to carry the asserted
    # phrases left all 50 tests in this file green. The assertions forbade a
    # hand-typed copy but not the remedy's outright removal — the step would
    # have published a fenced block containing one sentence of prose.
    code = "\n".join(
        line for line in run.splitlines() if not line.lstrip().startswith("#")
    )

    assert "from scripts.check_tv_unattested_sources import RESOLUTION" in code, (
        "the remedy is no longer imported in executable code (only, at most, in "
        "a comment about importing it)"
    )

    # The variable the summary interpolates must be the one assigned from the
    # command substitution that renders RESOLUTION — an agreement between the
    # two, so neither half can be severed while the other keeps the test green.
    # 2026-08-04: the reattest carve-out prepended its own command
    # substitution (re-running check_tv_unattested_sources against the
    # extended chain), so the RESOLUTION render is no longer the FIRST
    # assignment in the step -- find it among all of them; the agreement
    # itself is unchanged.
    assignments = re.findall(r'(\w+)="\$\((.*?)\)"', code, re.S)
    assert assignments, (
        "nothing in this step assigns a variable from a command substitution, "
        "so the remedy cannot be rendered at run time"
    )
    rendering = [
        (var, sub)
        for var, sub in assignments
        if "RESOLUTION.format(evidence=" in sub
    ]
    assert rendering, (
        "no substitution in this step renders RESOLUTION -- the remedy would "
        f"be hand-typed or missing. Substitutions seen: {assignments}"
    )
    variable, _substitution = rendering[0]
    # The render must not be able to abort the step. The block runs under
    # `set -euo pipefail`, so a bare `x="$(...)"` that fails ends the step right
    # there — before the job summary naming the un-attested sources and before
    # the `::error::` line. The run stays red either way, so the gate holds; what
    # would be lost is the report, exactly when rendering the remedy is the thing
    # that broke.
    assert re.search(rf'{variable}="\$\(.*?\)"\s*\\?\s*\n?\s*\|\|\s*{variable}=', code, re.S), (
        f"${variable} is assigned from a command substitution with no `||` "
        "fallback. Under `set -euo pipefail` a failure there kills the step "
        "before it reports WHICH sources were saved un-attested."
    )

    assert f'"${{{variable}}}"' in code, (
        f"the step renders the remedy into ${variable} and then never publishes "
        "it; the fenced block in the job summary would be empty or carry "
        "something else"
    )

    # The prose itself must not be re-typed here, in either wording.
    for phrase in (
        "Re-attest with a NEW dated evidence artifact",
        "falsifies a measurement rather than repeating it",
        "Do not edit the existing dated artifact",
    ):
        assert phrase not in run, (
            f"the un-attestation remedy is hand-typed in this step ({phrase!r}); "
            "render it from scripts/check_tv_unattested_sources.RESOLUTION so "
            "one run cannot describe one remedy two different ways"
        )

    # …and the shared constant must still carry what this step promises.
    rendered = RESOLUTION.format(evidence="EVIDENCE_PATH")
    assert "Re-attest" in rendered
    assert "NEW dated evidence artifact" in rendered
    assert "Revert the source change" in rendered
    assert "replaces a measurement with a fabrication" in rendered


# ---------------------------------------------------------------------------
# 2026-08-13: the checkout is a snapshot for EVERY run, not just the proposal
# branch. Executed, not string-matched — the reattest sibling of this step died
# on its first production run because `origin` carries no credentials, and a
# read-only test could never have seen that.
# ---------------------------------------------------------------------------


def _fast_forward_step() -> dict:
    step = next(
        s
        for s in _steps()
        if s.get("name") == "Fast-forward to current main before measuring"
    )
    return step


def _fast_forward_fragment() -> str:
    return _fast_forward_step()["run"]


def _origin_and_clone(tmp_path: Path, *, old: int, new: int) -> Path:
    """An origin whose main advanced from manifest `old` to `new`, plus a clone
    parked on the OLD commit — the shape a queued run actually has."""
    origin = tmp_path / "origin"
    origin.mkdir()
    manifest = origin / "artifacts" / "tradingview"
    manifest.mkdir(parents=True)
    env = _sandbox_env(tmp_path)

    def run(argv: list[str], *, cwd: Path) -> None:
        subprocess.run(argv, cwd=cwd, env=env, check=True, capture_output=True)

    run(["git", "init", "-q", "-b", "main"], cwd=origin)
    run(["git", "config", "user.email", "t@t"], cwd=origin)
    run(["git", "config", "user.name", "t"], cwd=origin)
    target = manifest / "library_release_manifest.json"
    target.write_text(f'{{"library": {{"publishedVersion": {old}}}}}', encoding="utf-8")
    run(["git", "add", "-A"], cwd=origin)
    run(["git", "commit", "-qm", "old"], cwd=origin)

    work = tmp_path / "work"
    # --depth=1 mirrors the workflow's own `fetch-depth: 1`. A full clone here
    # would have hidden the first version of this step outright: shallow is
    # exactly the condition under which `merge-base --is-ancestor` has nothing
    # to answer from, and the step then skipped its own fast-forward.
    run(["git", "clone", "-q", "--depth=1", f"file://{origin}", str(work)], cwd=tmp_path)
    run(["git", "config", "user.email", "t@t"], cwd=work)
    run(["git", "config", "user.name", "t"], cwd=work)

    # main moves on AFTER the run was created — the library was republished.
    target.write_text(f'{{"library": {{"publishedVersion": {new}}}}}', encoding="utf-8")
    run(["git", "commit", "-qam", "new"], cwd=origin)
    return work


def _run_fast_forward(work: Path, tmp_path: Path) -> subprocess.CompletedProcess:
    # The fragment ends in `git reset --hard`. Refusing to point it at the real
    # checkout is cheap; discovering afterwards that it was pointed there is
    # not.
    assert work != _REPO_ROOT and _REPO_ROOT not in work.parents, (
        f"the fast-forward fragment would run against the real repository ({work})"
    )
    return subprocess.run(
        ["/bin/bash", "-c", _fast_forward_fragment()],
        cwd=work,
        env=_sandbox_env(
            tmp_path,
            GITHUB_REPOSITORY="skipp-dev/skipp-algo",
            GH_TOKEN="test-token",
            FF_REMOTE=str(tmp_path / "origin"),
        ),
        capture_output=True,
        text=True,
    )


def _manifest_version(work: Path) -> int:
    text = (work / "artifacts" / "tradingview" / "library_release_manifest.json").read_text(
        encoding="utf-8"
    )
    return int(re.search(r'"publishedVersion":\s*(\d+)', text).group(1))


def test_a_queued_run_measures_against_the_manifest_that_is_current_when_it_runs(
    tmp_path: Path,
) -> None:
    """The 2026-08-13 stall: a run created at 16:07 carried manifest 228 while
    TradingView already listed 230, so the rollout tool refused every save and
    the refusal re-armed itself through tv-post-mutation-verify."""
    work = _origin_and_clone(tmp_path, old=228, new=230)
    assert _manifest_version(work) == 228, "precondition: the clone starts stale"

    done = _run_fast_forward(work, tmp_path)

    assert done.returncode == 0, done.stdout + done.stderr
    assert _manifest_version(work) == 230, (
        "the run still measures against its stale checkout; the publish-drift "
        "refusal this step exists to remove would fire again"
    )


def test_a_checkout_that_is_not_on_mains_line_is_left_exactly_as_it_was(
    tmp_path: Path,
) -> None:
    """A proposal or PR branch must not be silently reset onto main — the
    reattest path rebuilds itself deliberately and would lose its own commit."""
    work = _origin_and_clone(tmp_path, old=228, new=230)
    # Every git call here goes through _git(..., env=...) for the same reason
    # _origin_and_clone does: an inherited environment carries the pre-push
    # hook's GIT_DIR/GIT_WORK_TREE, and `git checkout -b` + `git commit` then
    # land on the real repository. Measured twice on 2026-08-13 — the second
    # time from exactly these three lines, because the first fix reached the
    # helpers and not the call sites.
    env = _sandbox_env(tmp_path)
    _git("checkout", "-qb", "bot/side", cwd=work, env=env)
    (work / "artifacts" / "tradingview" / "library_release_manifest.json").write_text(
        '{"library": {"publishedVersion": 111}}', encoding="utf-8"
    )
    _git("commit", "-qam", "side work", cwd=work, env=env)
    head_before = _git("rev-parse", "HEAD", cwd=work, env=env)

    done = _run_fast_forward(work, tmp_path)

    assert done.returncode == 0, done.stdout + done.stderr
    head_after = _git("rev-parse", "HEAD", cwd=work, env=env)
    assert head_after == head_before, "a side branch was reset onto main"
    assert _manifest_version(work) == 111, "the branch's own work was discarded"


def test_the_step_is_skipped_for_the_reattest_path_that_rebuilds_itself(
    tmp_path: Path,
) -> None:
    """Two steps must never both decide what the tree is."""
    condition = _fast_forward_step()["if"]
    assert "reattest != 'true'" in condition, (
        "the fast-forward must stand down where the reattest rebuild takes over"
    )


def test_the_fast_forward_runs_before_anything_measures_tradingview() -> None:
    names = [s.get("name") for s in _steps()]
    assert names.index("Fast-forward to current main before measuring") < names.index(
        "Save or read-only verify consumers in one browser session"
    ), "the tree must be current BEFORE the rollout tool reads the manifest"


def test_the_helpers_cannot_commit_into_the_repository_that_runs_them(
    tmp_path: Path, monkeypatch
) -> None:
    """A pre-push hook exports GIT_DIR/GIT_WORK_TREE, and those beat cwd.

    Measured 2026-08-13: the first version of these helpers inherited that
    environment, so ``git init`` re-initialised the real checkout and the
    following ``git add -A``/``git commit`` landed a tree-wide deletion on the
    very branch under test. The damage was invisible to a plain pytest run and
    only appeared under the pre-push hook. This pins the fix by REPRODUCING the
    condition against a stand-in repository.
    """
    stand_in = tmp_path / "stand-in"
    stand_in.mkdir()
    env = _sandbox_env(tmp_path)
    for argv in (
        ["git", "init", "-q", "-b", "main"],
        ["git", "config", "user.email", "t@t"],
        ["git", "config", "user.name", "t"],
    ):
        subprocess.run(argv, cwd=stand_in, env=env, check=True, capture_output=True)
    (stand_in / "keep.txt").write_text("do not lose me", encoding="utf-8")
    subprocess.run(
        ["git", "add", "-A"], cwd=stand_in, env=env, check=True, capture_output=True
    )
    subprocess.run(
        ["git", "commit", "-qm", "the branch under test"],
        cwd=stand_in,
        env=env,
        check=True,
        capture_output=True,
    )

    def head_of(repo: Path) -> str:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo,
            env=env,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()

    head_before = head_of(stand_in)

    # Exactly what the pre-push hook puts into the environment.
    monkeypatch.setenv("GIT_DIR", str(stand_in / ".git"))
    monkeypatch.setenv("GIT_WORK_TREE", str(stand_in))

    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()
    work = _origin_and_clone(sandbox, old=228, new=230)
    _run_fast_forward(work, sandbox)

    assert head_of(stand_in) == head_before, (
        "the helpers committed into the repository that is running them — the "
        "2026-08-13 defect is back"
    )
    assert (stand_in / "keep.txt").is_file(), "the stand-in checkout was wiped"


@pytest.fixture(autouse=True)
def _the_repository_running_these_tests_must_not_move():
    """No test in this module may touch the checkout it is running from.

    This is a POPULATION guard, deliberately not a per-helper one. Twice on
    2026-08-13 a git call in this file landed on the real repository, because
    a pre-push hook exports ``GIT_DIR``/``GIT_WORK_TREE`` and those beat
    cwd-based discovery. The first repair reached the two helpers I was looking
    at and missed three inline calls in a test body — the same defect came
    straight back on the next push, this time committing a branch called
    ``bot/side`` onto the branch under test.

    Checking every call site by inspection is the approach that already failed.
    Asserting over the whole module is the one that cannot: any test that moves
    HEAD or rewrites the identity, whichever call does it, fails here.

    The identity half is not hypothetical either. The fixtures run
    ``git config user.email t@t``; leaked into the real checkout it persists in
    ``.git/config`` — shared by every worktree — and the NEXT commit is made by
    ``t@t``, which the repository's own commit-author gate rejects. That is how
    it surfaced: not as a red test, but as a red PR one step later.
    """
    head_file = _REPO_ROOT / ".git"
    if not head_file.exists():
        yield
        return
    env = _sandbox_env(_REPO_ROOT)

    def state() -> tuple[str, str]:
        identity = subprocess.run(
            ["git", "config", "--get", "user.email"],
            cwd=_REPO_ROOT,
            env=env,
            capture_output=True,
            text=True,
        ).stdout.strip()
        return _git("rev-parse", "HEAD", cwd=_REPO_ROOT, env=env), identity

    head_before, identity_before = state()
    yield
    head_after, identity_after = state()
    assert head_after == head_before, (
        f"this test moved the repository's HEAD ({head_before[:9]} -> {head_after[:9]}). "
        "A git call in it reached the real checkout instead of tmp_path — pass "
        "env=_sandbox_env(...) to every subprocess call, not only to the helpers."
    )
    assert identity_after == identity_before, (
        f"this test rewrote the repository's commit identity "
        f"({identity_before!r} -> {identity_after!r}); the next commit made here "
        "would be refused by the commit-author gate"
    )
