from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROOF = "scripts.verify_structure_artifact_availability"
EVIDENCE_BASENAME = "structure_artifact_availability.json"


def _workflow(name: str) -> str:
    return (ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")


def test_rolling_benchmark_proves_artifacts_after_export_and_before_consumption() -> None:
    text = _workflow("smc-measurement-benchmark-rolling.yml")
    export = text.index("scripts/export_smc_structure_artifacts_from_workbook.py")
    proof = text.index(PROOF)
    consume = text.index("scripts/run_smc_measurement_benchmark.py", proof)
    assert export < proof < consume
    assert '--timeframes "${SMC_BENCH_TIMEFRAMES}"' in text
    # Completeness: the gate must require the exact symbol set the exporter ran on.
    assert '--expect-symbols "${SMC_BENCH_SYMBOLS}"' in text
    # Evidence lands inside out_dir, which the existing uploader already persists.
    assert f"${{{{ steps.meta.outputs.out_dir }}}}/{EVIDENCE_BASENAME}" in text
    assert "--max-age-seconds" in text


def test_library_refresh_proves_all_canonical_timeframes_before_release_gate() -> None:
    text = _workflow("smc-library-refresh.yml")
    proof = text.index(PROOF)
    consume = text.index("scripts/run_smc_release_gates.py", proof)
    assert proof < consume
    assert '--timeframes "5m,10m,15m,30m,1H,4H,1D"' in text
    assert "--expect-release-reference-symbols" in text
    assert "--max-age-seconds" in text
    # Evidence path sits under artifacts/ci/, which the gate-evidence uploader persists.
    assert f"--output artifacts/ci/{EVIDENCE_BASENAME}" in text
    assert "artifacts/ci/" in text.split("Upload gate evidence + library artifacts", 1)[1]


def test_release_gates_persist_availability_evidence() -> None:
    text = _workflow("smc-release-gates.yml")
    proof = text.index(PROOF)
    assert "--expect-release-reference-symbols" in text
    assert "--max-age-seconds" in text
    assert f"--output artifacts/ci/{EVIDENCE_BASENAME}" in text[proof:]
    # The evidence file must be enumerated in the explicit upload path list.
    upload = text.split("Upload release gate report", 1)[1]
    assert f"artifacts/ci/{EVIDENCE_BASENAME}" in upload
