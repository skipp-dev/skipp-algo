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


# --- the two decisions, executed rather than described -----------------------
#
# `download` decides status (ready/skipped) and `gates` decides produced; the
# ADR-0031 artifact steps hang on them. Measured 2026-08-04 with a
# value-preserving arm swap and a comparison inversion (the token multiset left
# unchanged in the first case, so any substring assertion is blind by
# construction): all 137 assertions across the 12 files that name this workflow
# stayed green for both.

import sys
from pathlib import Path

from tests._workflow_step_shell import Stub, run_step

_WF = "promotion-gate-daily.yml"
_DOWNLOAD_STEP = "Download rolling-benchmark artifact"
_GATES_STEP = "Build returns series + economic gates + regime report (ADR-0023/0031)"
_DATE = "2026-08-04"


def _gh(run_ids: str, succeeds_on_attempt: int) -> Stub:
    """`gh` answering per subcommand.

    The attempt counter lives in the step's own working directory, not /tmp:
    two xdist workers sharing one counter would make this test's verdict depend
    on scheduling.
    """
    return Stub(script=f"""
case "$1 $2" in
  "run list") printf '%s\\n' {run_ids or "''"} ;;
  "run download")
     n=$(cat ./_dl_attempts 2>/dev/null || echo 0); n=$((n+1)); echo $n > ./_dl_attempts
     if [ "$n" -ge {succeeds_on_attempt} ]; then exit 0; else exit 1; fi ;;
esac
exit 0
""")


def _download(tmp_path: Path, *, run_ids: str, succeeds_on_attempt: int = 1):
    return run_step(
        _WF, _DOWNLOAD_STEP, tmp_path,
        env={"DATE": _DATE, "GH_REPO": "skipp-dev/skipp-algo", "GH_TOKEN": "stub-token"},
        stubs={"gh": _gh(run_ids, succeeds_on_attempt)},
    )


def test_a_fetched_artifact_is_ready(tmp_path: Path) -> None:
    result = _download(tmp_path, run_ids="111 222 333")
    assert result.returncode == 0, result.stderr
    assert result.outputs["status"] == "ready"
    assert result.outputs["run_id"] == "111"
    assert result.outputs["scoring_root"].endswith(_DATE)


def test_the_download_keeps_trying_older_runs(tmp_path: Path) -> None:
    """Audit H7: the newest completed run may not carry the artifact.

    Stopping at the first run whose download fails is what H7 fixed. A test
    that only ever lets the first attempt succeed cannot tell the fix from its
    absence -- so here the first two fail and the third must still be found.
    """
    result = _download(tmp_path, run_ids="111 222 333", succeeds_on_attempt=3)
    assert result.outputs["status"] == "ready", (
        f"the step gave up before reaching an older run: {result.outputs}"
    )
    assert result.outputs["run_id"] == "333"


def test_no_recent_run_is_reported_as_such(tmp_path: Path) -> None:
    result = _download(tmp_path, run_ids="")
    assert result.outputs["status"] == "skipped"
    assert result.outputs["reason"] == "no_recent_run"


def test_an_unfindable_artifact_is_distinguished_from_no_run_at_all(tmp_path: Path) -> None:
    """Two different skips, two different reasons.

    Collapsing them loses the only signal that tells "the producer never ran"
    apart from "the producer ran and produced nothing" -- which are different
    outages with different owners.
    """
    result = _download(tmp_path, run_ids="111 222 333", succeeds_on_attempt=99)
    assert result.outputs["status"] == "skipped"
    assert result.outputs["reason"] == "artifact_not_found"


_PY_STUB = Stub(script='''
case "$1" in
  -c) exec "$REAL_PYTHON" "$@" ;;
esac
out=""; prev=""
for a in "$@"; do
  { [ "$prev" = "--output" ] || [ "$prev" = "--out" ]; } && out="$a"
  prev="$a"
done
case "$2" in
  scripts.build_returns_series)
     mkdir -p "$(dirname "$out")"
     printf '{"n_trades": %s}' "$N_TRADES" > "$out" ;;
  scripts.run_epnl_after_cost_gate)
     mkdir -p "$(dirname "$out")"
     printf '{}' > "$out"
     exit "${STUB_EPNL_RC:-0}" ;;
  *) [ -n "$out" ] && { mkdir -p "$(dirname "$out")"; printf '{}' > "$out"; } ;;
esac
exit 0
''')


# `head -n -90` (drop the last 90 lines) is a GNU extension. CI runs Ubuntu and
# has it; BSD head on macOS exits "illegal line count", which would fail this
# step for a reason that has nothing to do with its decision. This shim gives
# the step GNU semantics locally so the test measures the workflow rather than
# the developer's coreutils. It is NOT a claim about the workflow: on the real
# runner the real head does this natively.
_GNU_HEAD = Stub(script='''
exec "$REAL_PYTHON" -c '
import sys
args = sys.argv[1:]
n = 10
if args and args[0] == "-n":
    n = int(args[1])
elif args and args[0].startswith("-") and args[0][1:].lstrip("-").isdigit():
    n = int(args[0][1:])
lines = sys.stdin.read().splitlines(True)
sys.stdout.write("".join(lines[:n] if n >= 0 else lines[:len(lines) + n]))
' "$@"
''')


def _gates(tmp_path: Path, *, events_pool: bool, n_trades: int, epnl_rc: int = 0):
    # Mirror production: docs/calibration/gates/ is a COMMITTED drop-zone and
    # carries prior files for all three families. That matters, because the
    # retention loop at the end of the step is not fail-safe -- `ls` on a glob
    # that matches nothing exits non-zero, and under `set -euo pipefail` that
    # kills the step before it writes `produced`. Measured 2026-08-04; latent
    # today (5 committed files per family, retention keeps 90) and left alone
    # rather than hardened, since nothing reaches it.
    gates_dir = tmp_path / "docs/calibration/gates"
    gates_dir.mkdir(parents=True, exist_ok=True)
    for prefix in (
        "returns_series",
        "epnl_after_cost",
        "track_record_gate",
        "regime_stratified",
    ):
        (gates_dir / f"{prefix}_2026-01-01.json").write_text("{}", encoding="utf-8")
    if events_pool:
        pool = tmp_path / "artifacts/ci/scored_family_events_accumulated"
        pool.mkdir(parents=True)
        (pool / "accumulated_family_events.json").write_text("[]", encoding="utf-8")
    return run_step(
        _WF, _GATES_STEP, tmp_path,
        env={
            "REAL_PYTHON": sys.executable,
            "N_TRADES": str(n_trades),
            "STUB_EPNL_RC": str(epnl_rc),
        },
        stubs={"python": _PY_STUB, "head": _GNU_HEAD},
        expressions={"steps.date.outputs.value": _DATE},
    )


def test_a_populated_events_pool_produces_the_artifacts(tmp_path: Path) -> None:
    result = _gates(tmp_path, events_pool=True, n_trades=12)
    assert result.returncode == 0, result.stderr
    assert result.outputs["produced"] == "true"
    gates_dir = tmp_path / "docs/calibration/gates"
    assert (gates_dir / f"track_record_gate_{_DATE}.json").exists()
    assert (gates_dir / f"epnl_after_cost_{_DATE}.json").exists()
    assert (gates_dir / f"regime_stratified_{_DATE}.json").exists()


def test_no_events_pool_produces_nothing_and_says_so(tmp_path: Path) -> None:
    result = _gates(tmp_path, events_pool=False, n_trades=0)
    assert result.returncode == 0, result.stderr
    assert result.outputs["produced"] == "false"
    assert not (tmp_path / "docs/calibration/gates" / f"returns_series_{_DATE}.json").exists()


def test_a_zero_trade_series_emits_no_verdict_file(tmp_path: Path) -> None:
    """The broken-feed tripwire, by design.

    A zero-trade series must NOT get a track_record_gate file -- the absence is
    the honest state, and a gate that emitted a verdict over zero trades would
    be scored as a real one. The regime report is still written, so this is not
    a blanket skip.
    """
    result = _gates(tmp_path, events_pool=True, n_trades=0)
    assert result.returncode == 0, result.stderr
    assert result.outputs["produced"] == "true"
    gates_dir = tmp_path / "docs/calibration/gates"
    assert not (gates_dir / f"track_record_gate_{_DATE}.json").exists(), (
        "a zero-trade series must not produce a track-record verdict"
    )
    assert (gates_dir / f"regime_stratified_{_DATE}.json").exists(), (
        "the regime report is not gated on n_trades and must still be written"
    )
    assert (gates_dir / f"epnl_after_cost_{_DATE}.json").exists(), (
        "the §5 report must record the honest below-floor state"
    )


def test_epnl_negative_and_inconclusive_verdicts_are_persisted(tmp_path: Path) -> None:
    for rc in (2, 3):
        run_root = tmp_path / str(rc)
        run_root.mkdir()
        result = _gates(run_root, events_pool=True, n_trades=12, epnl_rc=rc)
        assert result.returncode == 0, result.stderr
        assert (
            run_root
            / "docs/calibration/gates"
            / f"epnl_after_cost_{_DATE}.json"
        ).exists()


def test_epnl_configuration_error_fails_the_workflow_step(tmp_path: Path) -> None:
    result = _gates(tmp_path, events_pool=True, n_trades=12, epnl_rc=1)
    assert result.returncode == 1
    assert "§5 gate failed with rc=1" in result.stdout


def test_epnl_gate_uses_the_same_1d_plane_as_the_returns_series() -> None:
    body = next(
        step["run"]
        for step in _load()["jobs"]["promotion-gate"]["steps"]
        if step.get("id") == "gates"
    )
    invocation = body.split("python -m scripts.run_epnl_after_cost_gate", 1)[1]
    invocation = invocation.split("case ", 1)[0]
    assert "--plane 1D" in invocation
