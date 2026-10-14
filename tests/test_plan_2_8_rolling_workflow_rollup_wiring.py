"""Structural pin-test for the Plan 2.8 rollup wiring in the rolling bench.

Guards that the smc-measurement-benchmark-rolling workflow:

  * runs the Plan 2.8 rollup step after the FVG audit and before the
    upload step,
    * passes the canonical 5m,10m,15m,30m,1H,4H,1D TF list,
  * writes the manifest into the benchmark output dir,
  * streams the Markdown view to the step summary,
  * is fail-soft so a rollup hiccup cannot mask the benchmark outcome,
  * runs on always() (so it fires even when the benchmark step fails).
"""

from __future__ import annotations

from pathlib import Path

import yaml

WORKFLOW = (
    Path(__file__).resolve().parents[1]
    / ".github"
    / "workflows"
    / "smc-measurement-benchmark-rolling.yml"
)


def _steps() -> list[dict]:
    wf = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    return wf["jobs"]["rolling-benchmark"]["steps"]


def _step(name: str) -> dict:
    for s in _steps():
        if s.get("name", "").startswith(name):
            return s
    raise AssertionError(f"step starting with {name!r} not found")


def test_rollup_step_present() -> None:
    step = _step("Plan 2.8 Phase 1 per-TF family rollup")
    assert step["if"].strip() == "always()"


def test_rollup_step_order_after_audit_before_upload() -> None:
    names = [s.get("name", "") for s in _steps()]

    def idx(prefix: str) -> int:
        for i, n in enumerate(names):
            if n.startswith(prefix):
                return i
        raise AssertionError(f"no step starts with {prefix!r}")

    i_audit  = idx("FVG label audit")
    i_roll   = idx("Plan 2.8 Phase 1 per-TF family rollup")
    i_upload = idx("Upload rolling benchmark artifacts")
    assert i_audit < i_roll < i_upload


def test_rollup_step_passes_all_seven_tfs() -> None:
    run = _step("Plan 2.8 Phase 1 per-TF family rollup")["run"]
    assert '"5m,10m,15m,30m,1H,4H,1D"' in run
    assert "scripts/plan_2_8_tf_family_rollup.py" in run


def test_rollup_step_streams_markdown_to_step_summary() -> None:
    run = _step("Plan 2.8 Phase 1 per-TF family rollup")["run"]
    assert "GITHUB_STEP_SUMMARY" in run
    assert "/tmp/rollup.md" in run
    assert "--format       md" in run


def test_rollup_step_is_fail_soft() -> None:
    step = _step("Plan 2.8 Phase 1 per-TF family rollup")
    run = step["run"]
    assert "set +e" in run
    assert run.rstrip().endswith("true")


def test_rollup_manifest_lands_in_benchmark_dir_for_upload() -> None:
    run = _step("Plan 2.8 Phase 1 per-TF family rollup")["run"]
    # The manifest must live under the same out_dir so the Upload step
    # picks it up via the directory-level glob.
    assert "${{ steps.meta.outputs.out_dir }}/plan_2_8_tf_family_rollup.json" in run


def test_experiment_snapshot_publish_uses_explicit_force_with_lease_sha() -> None:
    run = _step("Publish experiment snapshot to rolling bot branch")["run"]
    assert '_remote_ref="refs/heads/bot/live-experiment-snapshot"' in run
    assert (
        '_tracking_ref="refs/remotes/origin/bot/live-experiment-snapshot"'
        in run
    )
    assert 'git fetch "${_remote_url}" "+${_remote_ref}:${_tracking_ref}"' in run
    assert (
        '_expected_sha="$(git rev-parse --verify "${_tracking_ref}" 2>/dev/null)"'
        in run
    )
    assert '_zero_sha="0000000000000000000000000000000000000000"' in run
    assert '_lease_expected="${_expected_sha}"' in run
    assert '_lease_expected="${_zero_sha}"' in run
    assert (
        'git push "--force-with-lease=${_remote_ref}:${_lease_expected}" '
        '"${_remote_url}" "HEAD:${_remote_ref}"'
        in run
    )
