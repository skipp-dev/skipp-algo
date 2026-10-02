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


# --- ADR-0031 Nachtrag 2026-10-01: 15m observation + cumulative ledger --------
#
# Executed with the REAL producers (python is passed through, not stubbed):
# the step's whole point is what lands in the committed drop-zone, and a stub
# that writes `{}` cannot tell a ledger from an empty file.

import json

_LEDGER_STEP = "Build 15m observation series + cumulative returns ledger (ADR-0031 Nachtrag)"
_REPO_ROOT = Path(__file__).resolve().parents[1]
_M15 = 900.0
_DAY = 86_400.0
# 2026-10-05T14:30:00Z: the first day that counts as evidence under the return
# rule (governance.family_returns.RETURN_RULE_EVIDENCE_START). The workflow's
# own 15m flag (2026-10-01) is earlier and therefore no longer the binding one.
_OCT_5 = 1_791_210_600.0
_SEP_28 = _OCT_5 - 7 * _DAY  # before it

_REAL_PY = Stub(script='exec "$REAL_PYTHON" -B "$@"')


def _sweep(symbol: str, anchor_ts: float, *, step: float, timeframe: str, exit_close: float) -> dict:
    closes = [100.5, 101.0, exit_close]
    return {
        "family": "SWEEP",
        "event_id": f"sweep:{symbol}:{timeframe}:{int(anchor_ts)}:SELL_SIDE:100.00",
        "direction": "LONG",
        "entry_mode": "immediate",
        "entry_price": 100.0,
        "bar_grid": "exchange_aligned",
        "anchor_ts": anchor_ts,
        "regime": "RANGING",
        "forward_opens": [100.0, *closes[:-1]],
        "forward_closes": closes,
        "forward_highs": [c + 0.5 for c in closes],
        "forward_lows": [c - 0.5 for c in closes],
        "forward_timestamps": [anchor_ts + step * (i + 1) for i in range(3)],
    }


def _pool_events(*, forward_15m: int) -> list[dict]:
    # 1D: anchored 2026-10-03, -04, -05, -06 — two before the rule's start, two after.
    events = [
        _sweep(f"D{i}", _OCT_5 - 2 * _DAY + i * _DAY, step=_DAY, timeframe="1D", exit_close=101.0 + i)
        for i in range(4)
    ]
    events += [
        _sweep(f"OLD{i}", _SEP_28 + i * _M15, step=_M15, timeframe="15m", exit_close=99.0 + i)
        for i in range(5)
    ]
    events += [
        _sweep(f"NEW{i}", _OCT_5 + i * _M15, step=_M15, timeframe="15m", exit_close=100.0 + i)
        for i in range(forward_15m)
    ]
    return events


def _ledger_step(tmp_path: Path, events: list[dict] | None, *, date: str = "2026-10-05"):
    if events is not None:
        pool = tmp_path / "artifacts/ci/scored_family_events_accumulated"
        pool.mkdir(parents=True, exist_ok=True)
        (pool / "accumulated_family_events.json").write_text(json.dumps(events), encoding="utf-8")
    return run_step(
        _WF, _LEDGER_STEP, tmp_path,
        env={"DATE": date, "REAL_PYTHON": sys.executable, "PYTHONPATH": str(_REPO_ROOT)},
        stubs={"python": _REAL_PY, "head": _GNU_HEAD},
    )


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_the_ledger_step_commits_verdicts_and_ledgers_not_the_window_series(tmp_path: Path) -> None:
    result = _ledger_step(tmp_path, _pool_events(forward_15m=6))
    assert result.returncode == 0, result.stderr
    gates = tmp_path / "docs/calibration/gates"
    # The three directories this step may write to, listed — not walked.
    committed = sorted(
        str(path.relative_to(gates))
        for folder in (gates, gates / "15m", gates / "ledger")
        for path in folder.iterdir()
        if path.is_file()
    )
    assert committed == [
        "15m/regime_stratified_2026-10-05.json",
        "15m/track_record_gate_2026-10-05.json",
        "ledger/returns_ledger_15m.jsonl",
        "ledger/returns_ledger_1D.jsonl",
        "ledger/track_record_gate_15m.json",
        "ledger/track_record_gate_1D.json",
    ]
    # The 30-day window series is a run artifact, not a committed file.
    assert (tmp_path / "artifacts/ledger/returns_series_window_15m_2026-10-05.json").exists()


def test_nothing_of_the_15m_observation_is_visible_to_the_1d_consumers(tmp_path: Path) -> None:
    """The governed plane's consumers glob the gates dir NON-recursively.

    c13 Step 5a (`returns_series_*.json`), the public-report emitter
    (`<prefix>_*.json`) and the 1D retention loop must keep seeing 1D only.
    """
    _ledger_step(tmp_path, _pool_events(forward_15m=6))
    gates = tmp_path / "docs/calibration/gates"
    for prefix in ("returns_series", "track_record_gate", "regime_stratified", "epnl_after_cost"):
        assert list(gates.glob(f"{prefix}_*.json")) == [], prefix


def test_the_15m_window_verdict_counts_every_15m_trade_the_cumulative_one_only_forward(
    tmp_path: Path,
) -> None:
    result = _ledger_step(tmp_path, _pool_events(forward_15m=6))
    gates = tmp_path / "docs/calibration/gates"
    window = _read(gates / "15m/track_record_gate_2026-10-05.json")
    cumulative = _read(gates / "ledger/track_record_gate_15m.json")
    assert window["n_trades"] == 11  # 5 before + 6 after the evidence start
    assert cumulative["n_trades"] == 6  # only what arrived on or after 2026-10-05
    ledger_rows = (gates / "ledger/returns_ledger_15m.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(ledger_rows) == 11  # …but the ledger keeps all of them
    assert result.outputs == {"ledger_trades_1D": "2", "ledger_trades_15m": "6"}


def test_the_1d_ledger_starts_with_the_return_rule(tmp_path: Path) -> None:
    """The workflow passes no evidence start for 1D; the return rule has one.

    Four 1D trades are recorded, two of them anchored before 2026-10-05: they
    were on the table when the rule was chosen and do not count."""
    _ledger_step(tmp_path, _pool_events(forward_15m=6))
    gates = tmp_path / "docs/calibration/gates"
    assert len((gates / "ledger/returns_ledger_1D.jsonl").read_text(encoding="utf-8").splitlines()) == 4
    assert _read(gates / "ledger/track_record_gate_1D.json")["n_trades"] == 2


def test_an_empty_forward_series_emits_no_cumulative_15m_verdict(tmp_path: Path) -> None:
    """Day one, as measured 2026-10-01 on the real pool: no 15m trade yet
    anchored after the evidence start. No verdict over zero trades."""
    result = _ledger_step(tmp_path, _pool_events(forward_15m=0))
    assert result.returncode == 0, result.stderr
    gates = tmp_path / "docs/calibration/gates"
    assert not (gates / "ledger/track_record_gate_15m.json").exists()
    assert (gates / "ledger/returns_ledger_15m.jsonl").exists()
    assert result.outputs["ledger_trades_15m"] == "0"
    assert "cumulative 15m series still empty" in result.stdout


def test_the_ledger_grows_across_days_while_the_pool_window_moves(tmp_path: Path) -> None:
    _ledger_step(tmp_path, _pool_events(forward_15m=3), date="2026-10-05")
    day2 = [
        _sweep(f"LATER{i}", _OCT_5 + _DAY + i * _M15, step=_M15, timeframe="15m", exit_close=100.0 + i)
        for i in range(4)
    ]
    result = _ledger_step(tmp_path, day2, date="2026-10-06")  # yesterday's events aged out
    assert result.returncode == 0, result.stderr
    assert result.outputs["ledger_trades_15m"] == "7"
    gates = tmp_path / "docs/calibration/gates"
    assert _read(gates / "15m/track_record_gate_2026-10-06.json")["n_trades"] == 4  # window
    assert _read(gates / "ledger/track_record_gate_15m.json")["n_trades"] == 7  # memory


def test_a_missing_pool_fails_the_ledger_step_loudly(tmp_path: Path) -> None:
    """The step only runs when `gates` produced — a missing pool is a defect."""
    result = _ledger_step(tmp_path, None)
    assert result.returncode == 1
    assert "events pool is gone" in result.stdout


def test_a_failing_ledger_step_cannot_take_the_1d_artifacts_down_with_it() -> None:
    """The commit step must still run after a failed ledger step — and only then.

    `!cancelled()` lets it run past a failed predecessor; `produced == 'true'`
    keeps it off when a step BEFORE `gates` failed (then `produced` is empty).
    """
    steps = _load()["jobs"]["promotion-gate"]["steps"]
    names = [step.get("id") or step["name"] for step in steps]
    commit = next(s for s in steps if s["name"].startswith("Commit gate + regime artifacts"))
    assert names.index("gates") < names.index("ledger") < steps.index(commit)
    condition = str(commit["if"])
    assert "!cancelled()" in condition
    assert "steps.gates.outputs.produced == 'true'" in condition
    ledger = next(s for s in steps if s.get("id") == "ledger")
    assert "steps.gates.outputs.produced == 'true'" in str(ledger["if"])
    assert "continue-on-error" not in ledger, "a soft-failed ledger step would hide the defect"
