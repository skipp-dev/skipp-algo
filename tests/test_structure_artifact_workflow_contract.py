from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROOF = "scripts.verify_structure_artifact_availability"


def _workflow(name: str) -> str:
    return (ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")


def test_rolling_benchmark_proves_artifacts_after_export_and_before_consumption() -> None:
    text = _workflow("smc-measurement-benchmark-rolling.yml")
    export = text.index("scripts/export_smc_structure_artifacts_from_workbook.py")
    proof = text.index(PROOF)
    consume = text.index("scripts/run_smc_measurement_benchmark.py", proof)
    assert export < proof < consume
    assert '--timeframes "${SMC_BENCH_TIMEFRAMES}"' in text


def test_library_refresh_proves_all_canonical_timeframes_before_release_gate() -> None:
    text = _workflow("smc-library-refresh.yml")
    proof = text.index(PROOF)
    consume = text.index("scripts/run_smc_release_gates.py", proof)
    assert proof < consume
    assert '--timeframes "5m,10m,15m,30m,1H,4H,1D"' in text
