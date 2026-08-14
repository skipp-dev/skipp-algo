"""The publish job must judge the tree the refresh measured, not the tip of main.

Measured on 2026-08-14: 7 of 7 `workflow_run` publishes of `smc-library-publish`
checked out a different commit than the refresh that produced their payload
(1 to 7 commits apart) — a refresh holds the TradingView session slot for up to
three hours while main keeps moving. Once it touched a measurement input:
publish 31770344682 read a newer `reports/smc_measurement_baseline_summary.json`
than refresh 31752985708, so pre-gate and post-gate described different trees.

The fix resolves the refresh's `head_sha` BEFORE checkout and pins the checkout
to it. The commit/PR step at the end already re-anchors on `origin/main` when
the checkout is behind ("main advanced since checkout"), so this makes a
documented recovery path the normal path rather than introducing a new state.

These tests execute the resolver script itself — including a `gh` shim on PATH
for the dispatch case — instead of matching strings against it.
"""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
PUBLISH = ROOT / ".github" / "workflows" / "smc-library-publish.yml"

RESOLVE_STEP = "Resolve the tree this payload was produced from"


def _publish_job_steps() -> list[dict[str, Any]]:
    workflow = yaml.safe_load(PUBLISH.read_text(encoding="utf-8"))
    return workflow["jobs"]["publish"]["steps"]


def _named(steps: list[dict[str, Any]], prefix: str) -> int:
    matches = [i for i, s in enumerate(steps) if str(s.get("name", "")).startswith(prefix)]
    if len(matches) != 1:
        raise AssertionError(f"expected exactly one step starting with {prefix!r}, found {len(matches)}")
    return matches[0]


def test_the_resolver_runs_before_the_checkout_and_needs_no_tree() -> None:
    """Order is load-bearing: the resolver cannot use anything from the repo,
    because the repo is not there yet."""
    steps = _publish_job_steps()

    resolve = _named(steps, RESOLVE_STEP)
    checkout = _named(steps, "Checkout")

    assert resolve < checkout, "the resolver must run before the checkout it parameterizes"
    assert "uses" not in steps[resolve], "the resolver must be a plain run step — no action needs the tree"
    script = str(steps[resolve]["run"])
    assert "python" not in script.lower(), (
        "the resolver runs before setup-python-pinned; it must not assume an interpreter"
    )


def test_the_checkout_is_pinned_to_the_resolved_ref() -> None:
    steps = _publish_job_steps()
    checkout = steps[_named(steps, "Checkout")]

    assert checkout["with"].get("ref") == "${{ steps.source_tree.outputs.ref }}", (
        "the publish checkout must take the ref the resolver produced; without it the job "
        "judges the tip of main — measured 2026-08-14 as a different tree on 7 of 7 runs"
    )


@pytest.fixture(name="resolver_script")
def _resolver_script() -> str:
    steps = _publish_job_steps()
    return str(steps[_named(steps, RESOLVE_STEP)]["run"])


def _run_resolver(
    script: str,
    tmp_path: Path,
    *,
    event: str,
    workflow_run_head_sha: str = "",
    source_run_id: str = "",
    gh_response: str | None = None,
) -> tuple[subprocess.CompletedProcess[str], dict[str, str]]:
    """Execute the step's own script with the env GitHub would give it."""
    output = tmp_path / "github_output"
    output.write_text("", encoding="utf-8")

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    gh = bin_dir / "gh"
    if gh_response is not None:
        gh.write_text(f"#!/bin/bash\necho '{gh_response}'\n", encoding="utf-8")
    else:
        # A gh that fails loudly: the workflow_run and no-input paths must never call it.
        gh.write_text("#!/bin/bash\necho 'gh must not be called on this path' >&2\nexit 97\n", encoding="utf-8")
    gh.chmod(gh.stat().st_mode | stat.S_IEXEC)

    completed = subprocess.run(
        ["bash", "-c", script],
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "GITHUB_OUTPUT": str(output),
            "GH_TOKEN": "test-token",
            "EVENT_NAME": event,
            "WORKFLOW_RUN_HEAD_SHA": workflow_run_head_sha,
            "SOURCE_RUN_ID": source_run_id,
            "REPOSITORY": "skipp-dev/skipp-algo",
        },
        check=False,
    )
    outputs = dict(
        line.split("=", 1)
        for line in output.read_text(encoding="utf-8").splitlines()
        if "=" in line
    )
    return completed, outputs


def test_workflow_run_resolves_to_the_triggering_head_sha(resolver_script: str, tmp_path: Path) -> None:
    """The production path: the refresh's own commit, no API call."""
    completed, outputs = _run_resolver(
        resolver_script,
        tmp_path,
        event="workflow_run",
        workflow_run_head_sha="de339a57d00000000000000000000000000000aa",
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert outputs["ref"] == "de339a57d00000000000000000000000000000aa"


def test_dispatch_with_source_run_id_asks_the_api_for_that_runs_tree(
    resolver_script: str, tmp_path: Path
) -> None:
    completed, outputs = _run_resolver(
        resolver_script,
        tmp_path,
        event="workflow_dispatch",
        source_run_id="31752985708",
        gh_response="2bab4c10200000000000000000000000000000bb",
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert outputs["ref"] == "2bab4c10200000000000000000000000000000bb"


def test_dispatch_without_source_run_id_falls_back_loudly(resolver_script: str, tmp_path: Path) -> None:
    """Empty ref = actions/checkout default (tip of main). Allowed, but never silent."""
    completed, outputs = _run_resolver(resolver_script, tmp_path, event="workflow_dispatch")

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert outputs["ref"] == ""
    assert "::warning::" in completed.stdout, (
        "the fallback to main must announce itself — a silent fallback recreates the skew invisibly"
    )


def test_a_failing_api_lookup_fails_the_step_instead_of_publishing_from_main(
    resolver_script: str, tmp_path: Path
) -> None:
    """set -e semantics, executed: if the run id cannot be resolved, the step must
    die rather than quietly produce an empty ref and publish from the wrong tree."""
    completed, _ = _run_resolver(
        resolver_script,
        tmp_path,
        event="workflow_dispatch",
        source_run_id="999999",
        gh_response=None,  # the failing gh shim
    )

    assert completed.returncode != 0, (
        "an unresolvable source_run_id must fail the resolver, not fall through to main: "
        + completed.stdout
        + completed.stderr
    )
