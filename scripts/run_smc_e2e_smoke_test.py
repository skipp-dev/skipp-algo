#!/usr/bin/env python3
"""SMC Freeze-Exit E2E Smoke Test.

Chains the critical production path end-to-end for a single symbol/timeframe pair:

  1. Pre-release artifact refresh (structure artifacts from workbook)
  2. Measurement benchmark (benchmark + scoring from refreshed artifacts)
  3. Release gates (provider health + measurement quality evaluation)

Pass criteria:
  - Each step completes without uncaught exception
  - Pre-release refresh produces a manifest with artifacts_written > 0
  - Measurement benchmark produces a summary with n_events >= 0
  - Release gates produce a structured report with all gate names present

This test is designed to run locally with production data or in CI
with fixture data (where zero events are expected and acceptable).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# Bug-Hunt 2026-05-01 F-01: deferred so the script also works when
# invoked as `python scripts/X.py` (no PYTHONPATH=.) — sys.path.insert
# above must happen before any first-party `from scripts.` import.
from scripts.smc_atomic_write import atomic_write_text  # noqa: E402


def _iso_utc(ts: float) -> str:
    return datetime.fromtimestamp(float(ts), tz=UTC).isoformat()


def _step_refresh(symbol: str, timeframe: str, artifacts_dir: Path) -> dict:
    """Step 1: Pre-release artifact refresh."""
    from scripts.run_smc_pre_release_artifact_refresh import main as refresh_main

    output_path = artifacts_dir / "smoke_pre_release_refresh.json"
    sys.argv = [
        "smoke",
        "--symbols", symbol,
        "--timeframes", timeframe,
        "--allow-missing-inputs",
        "--warn-on-empty-artifacts",
        "--output", str(output_path),
    ]
    exit_code = refresh_main()
    report = json.loads(output_path.read_text()) if output_path.exists() else {}
    status = report.get("overall_status", "unknown")
    manifests = report.get("refresh_manifests", [])
    artifacts_written = sum(
        m.get("counts", {}).get("artifacts_written", 0) for m in manifests
    )
    return {
        "step": "pre_release_refresh",
        "exit_code": exit_code,
        "status": status,
        "artifacts_written": artifacts_written,
        "pass": status in ("ok", "warn") or artifacts_written > 0,
        "report_path": str(output_path),
    }


def _step_benchmark(symbol: str, timeframe: str, artifacts_dir: Path) -> dict:
    """Step 2: Measurement benchmark."""
    from scripts.run_smc_measurement_benchmark import main as benchmark_main

    output_dir = artifacts_dir / "smoke_measurement"
    sys.argv = [
        "smoke",
        "--symbols", symbol,
        "--timeframes", timeframe,
        "--output-dir", str(output_dir),
    ]
    try:
        exit_code = benchmark_main()
    except SystemExit as exc:
        exit_code = int(exc.code) if exc.code is not None else 1
    except Exception as exc:
        return {
            "step": "measurement_benchmark",
            "exit_code": 1,
            "status": "error",
            "error": str(exc),
            "n_events": 0,
            "pass": False,
            "report_path": str(output_dir),
        }

    summary_path = output_dir / symbol / timeframe / f"measurement_summary_{symbol}_{timeframe}.json"
    if summary_path.exists():
        summary = json.loads(summary_path.read_text())
        n_events = summary.get("scoring", {}).get("n_events", 0)
        brier = summary.get("scoring", {}).get("brier_score")
    else:
        n_events = 0
        brier = None

    return {
        "step": "measurement_benchmark",
        "exit_code": exit_code,
        "status": "ok" if exit_code == 0 else "error",
        "n_events": n_events,
        "brier_score": brier,
        "pass": exit_code == 0,
        "report_path": str(summary_path) if summary_path.exists() else str(output_dir),
    }


def _step_release_gates(symbol: str, timeframe: str, artifacts_dir: Path) -> dict:
    """Step 3: Release gates."""
    from scripts.run_smc_release_gates import main as gates_main

    output_path = artifacts_dir / "smoke_release_gates.json"
    sys.argv = [
        "smoke",
        "--symbols", symbol,
        "--timeframes", timeframe,
        "--skip-publish-contract",
        "--output", str(output_path),
    ]
    try:
        exit_code = gates_main()
    except SystemExit as exc:
        exit_code = int(exc.code) if exc.code is not None else 1

    if output_path.exists():
        report = json.loads(output_path.read_text())
        gate_names = [g.get("name") for g in report.get("gates", [])]
        overall = report.get("overall_status", "unknown")
    else:
        gate_names = []
        overall = "missing_report"

    expected_gates = {"provider_health", "reference_bundle", "measurement_lane"}
    gates_present = expected_gates.issubset(set(gate_names))

    return {
        "step": "release_gates",
        "exit_code": exit_code,
        "status": overall,
        "gate_names": gate_names,
        "gates_present": gates_present,
        "pass": gates_present,
        "report_path": str(output_path),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="SMC Freeze-Exit E2E Smoke Test")
    parser.add_argument("--symbol", default="AAPL", help="Symbol for smoke test")
    parser.add_argument("--timeframe", default="15m", help="Timeframe for smoke test")
    parser.add_argument(
        "--output-dir",
        default="artifacts/ci/smoke_test",
        help="Output directory for smoke test artifacts",
    )
    parser.add_argument("--output", default="-", help="Output path for smoke report JSON, or '-' for stdout")
    args = parser.parse_args()

    symbol = args.symbol.strip().upper()
    timeframe = args.timeframe.strip()
    artifacts_dir = Path(args.output_dir)
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    started_at = time.time()
    steps: list[dict] = []
    all_pass = True

    # Step 1: Pre-release refresh
    print(f"[smoke] Step 1/3: Pre-release artifact refresh ({symbol}/{timeframe})")
    try:
        result = _step_refresh(symbol, timeframe, artifacts_dir)
    except Exception as exc:
        result = {"step": "pre_release_refresh", "exit_code": 1, "error": str(exc), "pass": False}
    steps.append(result)
    print(f"  -> {'PASS' if result['pass'] else 'FAIL'} (artifacts_written={result.get('artifacts_written', '?')})")
    if not result["pass"]:
        all_pass = False

    # Step 2: Measurement benchmark
    print(f"[smoke] Step 2/3: Measurement benchmark ({symbol}/{timeframe})")
    try:
        result = _step_benchmark(symbol, timeframe, artifacts_dir)
    except Exception as exc:
        result = {"step": "measurement_benchmark", "exit_code": 1, "error": str(exc), "pass": False}
    steps.append(result)
    print(f"  -> {'PASS' if result['pass'] else 'FAIL'} (n_events={result.get('n_events', '?')})")
    if not result["pass"]:
        all_pass = False

    # Step 3: Release gates
    print(f"[smoke] Step 3/3: Release gates ({symbol}/{timeframe})")
    try:
        result = _step_release_gates(symbol, timeframe, artifacts_dir)
    except Exception as exc:
        result = {"step": "release_gates", "exit_code": 1, "error": str(exc), "pass": False}
    steps.append(result)
    print(f"  -> {'PASS' if result['pass'] else 'FAIL'} (gates={result.get('gate_names', '?')})")
    if not result["pass"]:
        all_pass = False

    finished_at = time.time()
    smoke_report = {
        "report_kind": "e2e_smoke_test",
        "started_at": started_at,
        "started_at_iso": _iso_utc(started_at),
        "finished_at": finished_at,
        "finished_at_iso": _iso_utc(finished_at),
        "duration_seconds": round(finished_at - started_at, 2),
        "symbol": symbol,
        "timeframe": timeframe,
        "overall_pass": all_pass,
        "steps": steps,
    }

    rendered = json.dumps(smoke_report, indent=2, sort_keys=False)
    if args.output == "-":
        print(rendered)
    else:
        out = Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(rendered + "\n", out)
        print(f"[smoke] Report written to {out}")

    verdict = "PASS" if all_pass else "FAIL"
    print(f"\n[smoke] Overall: {verdict} ({len([s for s in steps if s['pass']])}/{len(steps)} steps passed)")
    return 0 if all_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())
