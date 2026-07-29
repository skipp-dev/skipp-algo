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


def test_live_window_marker_mutating_on_cron() -> None:
    """2026-07-29 (ADR-0031): posture raised from off-hours-only — the
    workflow now commits gate/regime artifacts via a bot auto-merge PR."""
    head = _WF_PATH.read_text(encoding="utf-8").splitlines()[0]
    assert "live-window: mutating-on-cron" in head, (
        "first-line live-window marker required by F-V6-F2.1; "
        "mutating-on-cron since ADR-0031 (write permissions + commit-back)"
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


def test_permissions_minimal_for_download_plus_adr0031_commit_back() -> None:
    """Pin the exact permission set; every entry has a named consumer.

    2026-07-29 (ADR-0031): widened from read-only. ``contents: write`` +
    ``pull-requests: write`` are consumed by the "Commit gate + regime
    artifacts via auto-merge PR" step (push ``bot/promotion-gates-*`` +
    ``gh pr create``), mirroring ``run-open-prep-daily``. ``actions: read``
    remains required for ``gh run download`` against the rolling bench.
    Any further widening needs a consumer named here.
    """
    perms = _load()["permissions"]
    assert perms == {
        "contents": "write",
        "pull-requests": "write",
        "actions": "read",
    }, "permissions drifted from the ADR-0031 set — name the consumer before widening"


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


def test_bundle_step_feeds_magnitude_shadow_ledger() -> None:
    """ADR-0023 Stage-1 snapshot wiring (handover §5 item 2).

    The bundle step must feed the frozen 15m PROOF archive (the plane the
    armed BOS/SWEEP magnitude verdict was established on), NOT the active
    magnitude_resolution_shadow ledger — which is now the live 1D
    measurement track (thin heartbeats). Feeding the 1D track here would
    wrongly flip the gate's magnitude fields to "not measured".
    """
    bundle_step = next(
        s for s in _load()["jobs"]["promotion-gate"]["steps"]
        if s.get("id") == "bundle"
    )
    body = bundle_step["run"]
    assert "--magnitude-ledger" in body, (
        "bundle step no longer feeds the move-size shadow ledger; the "
        "promotion gate's magnitude fields would silently revert to dormant"
    )
    assert "artifacts/governance/magnitude_resolution_shadow_15m_seed.jsonl" in body, (
        "the gate must read the frozen 15m proof archive, not the live 1D "
        "measurement track (magnitude_resolution_shadow.jsonl)"
    )


def test_bundle_step_consumes_accumulated_events_pool() -> None:
    """Tier-1 direction wiring (2026-07-06).

    The gate's direction metrics (PSR/MinTRL/FDR) must be measured on the
    SAME accumulated FamilyEvent pool the magnitude axis consumes — the
    EV-20 Tier-1 verdicts exist only for the 15m plane and must not be the
    gate's sole direction evidence for the 1D pool. Without the download +
    --events flag the Tier-1 fields silently revert to permanent None."""
    steps = _load()["jobs"]["promotion-gate"]["steps"]
    download = next(
        (
            s
            for s in steps
            if "scored-family-events-accumulated"
            in str((s.get("with") or {}).get("name", ""))
        ),
        None,
    )
    assert download is not None, (
        "accumulated-events download step missing; Tier-1 direction "
        "metrics would silently stay unmeasured"
    )
    assert (download.get("with") or {}).get("if_no_artifact_found") == "warn", (
        "accumulated-events download must stay fail-soft (measure-only path)"
    )
    bundle_step = next(s for s in steps if s.get("id") == "bundle")
    assert "--events" in bundle_step["run"], (
        "bundle step no longer passes the accumulated pool; Tier-1 "
        "direction fields would silently revert to permanent None"
    )


def test_bundle_step_passes_universe_manifest() -> None:
    # Survivorship enforcement in production rides the bundle: the build step must
    # glob the databento export manifest (staged into the rolling-bench artifact by
    # smc-measurement-benchmark-rolling) and pass --universe-manifest. Fail-soft
    # (${VAR:+...}) so a thin day without a manifest still builds the bundle.
    text = _WF_PATH.read_text(encoding="utf-8")
    assert "databento_volatility_production_*_manifest.json" in text
    assert "--universe-manifest" in text
