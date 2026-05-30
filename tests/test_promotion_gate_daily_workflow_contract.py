"""Contract pin: ``promotion-gate-daily.yml`` (Bundle D-2 from issue #2422).

The W1.b advisory PromotionGate evaluation has non-trivial exit-code
semantics: rc=0 pass, rc=2 warning-not-fail (advisory), rc=1 config
error => fail. This file pins that policy and the stable-alias artefact
contract (``artifacts/promotion_decisions.json``) the Streamlit panel
reads by default.
"""

from __future__ import annotations

from pathlib import Path

import yaml

_REPO_ROOT = Path(__file__).resolve().parents[1]
_WF_PATH = _REPO_ROOT / ".github" / "workflows" / "promotion-gate-daily.yml"


def _load() -> dict:
    return yaml.safe_load(_WF_PATH.read_text(encoding="utf-8"))


def _on(data: dict) -> dict:
    return data.get("on") or data.get(True)


def test_workflow_file_exists() -> None:
    assert _WF_PATH.is_file(), f"missing workflow: {_WF_PATH}"


def test_live_window_marker_off_hours() -> None:
    head = _WF_PATH.read_text(encoding="utf-8").splitlines()[0]
    assert "live-window: off-hours-only" in head, (
        "first-line live-window marker required by F-V6-F2.1"
    )


def test_cron_runs_after_rolling_bench_mon_fri() -> None:
    """14:00 UTC Mon-Fri — must run AFTER smc-measurement-benchmark-rolling
    (13:00 UTC Mon-Fri). Pre-#2447 this job ran at 09:30 UTC daily, BEFORE
    the upstream Databento producer (12:00 UTC Mon-Fri) and rolling-bench
    (07:30 daily, also pre-producer) — always-skip pattern. Producer→consumer
    ordering is now enforced by
    tests/test_workflow_databento_consumer_cron_ordering.py.
    """
    crons = [e["cron"] for e in _on(_load())["schedule"]]
    assert crons == ["0 14 * * 1-5"], (
        f"promotion-gate-daily cron drifted to {crons}; must remain "
        "'0 14 * * 1-5' so rolling-bench (13:00 UTC Mon-Fri) has time to "
        "publish its artifact before this job downloads it"
    )


def test_concurrency_does_not_cancel() -> None:
    concurrency = _load()["concurrency"]
    assert concurrency["group"] == "promotion-gate-daily"
    assert concurrency["cancel-in-progress"] is False


def test_permissions_minimal_read_plus_actions_read() -> None:
    perms = _load()["permissions"]
    assert perms == {"contents": "read", "actions": "read"}, (
        "permissions drifted; ``actions:read`` is required for `gh run download`"
    )


def test_single_promotion_gate_job() -> None:
    jobs = _load()["jobs"]
    assert list(jobs.keys()) == ["promotion-gate"]
    job = jobs["promotion-gate"]
    assert job["timeout-minutes"] == 15
    assert "SMC_GH_HOSTED_RUNNER" in job["runs-on"]


def test_gate_step_exit_code_policy_advisory_rc2() -> None:
    """W1.b advisory: rc=0 pass, rc=2 warning+pass, rc=1 fail."""
    gate_step = next(
        s for s in _load()["jobs"]["promotion-gate"]["steps"]
        if s.get("id") == "gate"
    )
    body = gate_step["run"]
    # rc=2 must downgrade to warning, not fail
    assert "rc}\" -eq 2" in body and "::warning" in body, (
        "advisory rc=2 -> warning policy missing; honest red reports would "
        "start failing CI prematurely (Sprint W1.b first-cut contract)"
    )
    # rc=1 unexpected -> error
    assert "::error" in body, "rc=1 unexpected-rc handling missing"
    # set +e at top of step is intentional (rc capture)
    assert "set +e" in body, (
        "set +e removed; if you replaced it ensure rc capture still happens"
    )


def test_stable_alias_artifact_path() -> None:
    """Decision-First Streamlit panel reads artifacts/promotion_decisions.json."""
    body = "\n".join(
        s.get("run", "") for s in _load()["jobs"]["promotion-gate"]["steps"]
    )
    assert "artifacts/promotion_decisions.json" in body, (
        "stable alias path drifted; Streamlit Decision-First tab will lose its "
        "``latest`` pointer (only dated snapshots remain)"
    )


def test_download_step_iterates_last_8_runs() -> None:
    """Audit H7 fix: must scan recent rolling-bench runs, not assume today's."""
    dl = next(
        s for s in _load()["jobs"]["promotion-gate"]["steps"]
        if s.get("id") == "download"
    )
    assert "--limit 8" in dl["run"], (
        "8-run lookback removed; brittle to a single late rolling-bench day"
    )
    assert "smc-measurement-benchmark-rolling.yml" in dl["run"], (
        "upstream workflow rename detected"
    )
