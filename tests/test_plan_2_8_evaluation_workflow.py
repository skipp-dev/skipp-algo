"""Structural contract tests for the Plan 2.8 evaluation workflow."""

from __future__ import annotations

from pathlib import Path

import yaml

WORKFLOW = (
    Path(__file__).resolve().parents[1]
    / ".github"
    / "workflows"
    / "plan-2-8-evaluation.yml"
)


def _steps() -> list[dict]:
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    return workflow["jobs"]["evaluate"]["steps"]


def _step(name: str) -> dict:
    for step in _steps():
        if step.get("name") == name:
            return step
    raise AssertionError(f"step {name!r} not found")


def test_experiment_snapshot_publish_uses_explicit_force_with_lease_sha() -> None:
    run = _step("Publish snapshots to rolling bot branch")["run"]
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
    assert (
        "git push --force-with-lease=refs/heads/bot/live-experiment-snapshot"
        not in run
    )
