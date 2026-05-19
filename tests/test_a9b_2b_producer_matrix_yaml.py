"""A9b.2b — YAML smoke tests for the matrix-fan-out producer job.

These tests guard the structural wiring of the sharded workflow's
``producer`` job:

* ``needs: plan`` chain (typo here = workflow_dispatch fails immediately)
* ``strategy.matrix`` consumes ``fromJson(needs.plan.outputs.matrix)``
* ``fail-fast: false`` (we MUST collect every shard manifest for A9b.3)
* per-shard ``timeout-minutes: 120`` (Q4 bumped 90→120 post-Probe-v3)
* per-shard artifact name template includes both shard-id and shard-of
* producer call carries the four sharding CLI flags introduced in A9b.1
* ``workflow_dispatch`` remains available even after scheduled phases land

The orphan-inventory guard already sees the workflow basename via the
A9b.2a smoke tests in ``test_a9b_2a_plan_shards.py``.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

_SHARDED_WORKFLOW_BASENAME = "smc-databento-production-export-sharded"
_REPO_ROOT = Path(__file__).resolve().parents[1]


def _yaml_doc() -> dict:
    yaml = pytest.importorskip("yaml")
    path = (
        Path(__file__).resolve().parents[1]
        / ".github"
        / "workflows"
        / f"{_SHARDED_WORKFLOW_BASENAME}.yml"
    )
    assert path.exists(), f"Expected sharded workflow at {path}"
    return yaml.safe_load(path.read_text())


def _producer_job() -> dict:
    doc = _yaml_doc()
    jobs = doc["jobs"]
    assert "producer" in jobs, "A9b.2b: producer job missing from sharded workflow"
    return jobs["producer"]


def test_producer_job_needs_plan() -> None:
    job = _producer_job()
    needs = job.get("needs")
    # ``needs:`` may be a single string or a list of strings.
    if isinstance(needs, str):
        assert needs == "plan"
    else:
        assert needs is not None and "plan" in needs


def test_producer_strategy_consumes_plan_matrix_output() -> None:
    job = _producer_job()
    strategy = job.get("strategy")
    assert isinstance(strategy, dict), "producer must have a strategy block"
    matrix_expr = strategy.get("matrix")
    # Stored as a string in YAML (GHA expression). Must reference plan output.
    assert isinstance(matrix_expr, str), f"matrix must be an expression, got {matrix_expr!r}"
    assert "fromJson" in matrix_expr
    assert "needs.plan.outputs.matrix" in matrix_expr


def test_producer_strategy_fail_fast_is_false() -> None:
    job = _producer_job()
    # PyYAML preserves false as Python False.
    assert job["strategy"].get("fail-fast") is False, (
        "A9b.2b: fail-fast MUST be false so all shard manifests are collected "
        "even when one shard OOMs (needed for A9b.3 reduce-fixture design)."
    )


def test_producer_per_shard_timeout_is_120() -> None:
    job = _producer_job()
    assert job.get("timeout-minutes") == 120, (
        "Q4 (post-Probe-v3): per-shard cap pinned at 120min (at the observed "
        "~120min platform wall). Bumped from 90 to absorb v3 cap-hit margin; "
        "any future bump must follow a fresh step-progress profile, not a guess."
    )


def test_producer_runs_on_pinned_runner_var() -> None:
    job = _producer_job()
    runs_on = job.get("runs-on")
    assert isinstance(runs_on, str) and "vars.SMC_GH_HOSTED_RUNNER" in runs_on, (
        "Producer must use the SMC_GH_HOSTED_RUNNER vars-pin (architectural "
        f"discipline guard); got runs-on={runs_on!r}"
    )


def test_producer_invokes_export_script_with_shard_args() -> None:
    """Raw-text check: the producer step must pass all 4 A9b.1 CLI flags."""
    path = (
        Path(__file__).resolve().parents[1]
        / ".github"
        / "workflows"
        / f"{_SHARDED_WORKFLOW_BASENAME}.yml"
    )
    text = path.read_text()
    assert "scripts/databento_production_export.py" in text
    for flag in ("--start-date", "--end-date", "--shard-id", "--shard-of"):
        assert flag in text, f"producer call missing required A9b.1 flag {flag}"
    # Per-shard artifact name template must include both axes.
    assert "a9b-2b-shard-${{ matrix.shard_id }}-of-${{ matrix.shard_of }}" in text


def test_producer_uploads_artifact_unconditionally() -> None:
    """if: always() so that OOM/timeout shards still publish stdout + manifest."""
    job = _producer_job()
    upload_steps = [
        s
        for s in job.get("steps", [])
        if isinstance(s, dict)
        and isinstance(s.get("uses"), str)
        and s["uses"].startswith("actions/upload-artifact@")
    ]
    assert upload_steps, "producer must have an upload-artifact step"
    for step in upload_steps:
        assert step.get("if") == "always()", (
            f"producer upload-artifact step must use `if: always()`; got {step.get('if')!r}"
        )
        # Accept both floating tag and its SHA-pinned equivalent so the
        # test keeps passing after actions are pinned to full commit SHAs.
        _UPLOAD_V7_SHA = "043fb46d1a93c77aae656e7c1c64a875d1fc6a0a"
        assert step["uses"] in {
            "actions/upload-artifact@v7",
            f"actions/upload-artifact@{_UPLOAD_V7_SHA}",
        }, (
            f"uniform-version guard: must use actions/upload-artifact@v7; got {step['uses']!r}"
        )


def test_workflow_keeps_dispatch_surface_after_2b() -> None:
    """A9b.2b regression-guard: producer addition must keep manual dispatch."""
    doc = _yaml_doc()
    on_key = True if True in doc else "on"
    triggers = doc[on_key]
    assert isinstance(triggers, dict)
    assert "workflow_dispatch" in triggers, (
        f"sharded workflow must keep workflow_dispatch; got {list(triggers.keys())}"
    )
    assert set(triggers.keys()).issubset({"workflow_dispatch", "schedule"}), (
        f"sharded workflow may only expose workflow_dispatch plus optional schedule; "
        f"got {list(triggers.keys())}"
    )


def test_producer_script_advertises_sharding_flags() -> None:
    """Pre-flight contract: producer script must expose all 4 A9b.1 sharding
    CLI flags that the workflow invokes — otherwise dispatch-time failure with
    ``unrecognized arguments`` (cost ~3min runner-time, hit on 2026-05-08
    when A9b.2b probe ran against main without #2081 yet merged)."""
    out = subprocess.run(
        [sys.executable, "scripts/databento_production_export.py", "--help"],
        capture_output=True,
        text=True,
        check=False,
        cwd=str(_REPO_ROOT),
    )
    assert out.returncode == 0, (
        f"producer --help exited rc={out.returncode}; stderr={out.stderr[:500]}"
    )
    for flag in ("--start-date", "--end-date", "--shard-id", "--shard-of"):
        assert flag in out.stdout, (
            f"producer/workflow contract broken: missing {flag} in --help output"
        )
