"""Pin-test for the fvg-quality-recal-shadow-daily workflow (Plan §D4).

The workflow must:
* run the recal script in shadow mode (NOT mutate production weights),
* parse the script's status / acceptance / sample-count tokens,
* upload the shadow JSON as a workflow artifact,
* be fail-soft (corpus discovery falls back to an empty dir so cron stays green).
"""
from __future__ import annotations

from pathlib import Path

WF = Path(".github/workflows/fvg-quality-recal-shadow-daily.yml")


def test_workflow_file_exists() -> None:
    assert WF.is_file(), f"missing workflow: {WF}"


def test_workflow_runs_recal_script_in_shadow_mode() -> None:
    text = WF.read_text()
    assert "scripts/fvg_quality_recalibration.py" in text
    # Output target is the shadow JSON, not the production calibration JSON.
    assert "fvg_quality_calibration_shadow.json" in text
    # The recal CLI must be invoked with --output pointing at the shadow path.
    assert "--output artifacts/reports/fvg_quality_calibration_shadow.json" in text
    # Production calibration JSON must not appear as a write target. Allow
    # comment-only mentions (the workflow header explains the boundary).
    code_lines = [
        ln for ln in text.splitlines()
        if ln.strip() and not ln.lstrip().startswith("#")
    ]
    code_only = "\n".join(code_lines)
    assert "zone_priority_calibration.json" not in code_only


def test_workflow_parses_recal_status_tokens() -> None:
    text = WF.read_text()
    # These tokens are emitted by scripts/fvg_quality_recalibration.py main().
    for token in ("status=", "acceptance=", "n_with_label=", "n_with_features="):
        assert token in text, f"workflow does not parse `{token}` from recal output"


def test_workflow_uploads_shadow_artifact() -> None:
    text = WF.read_text()
    assert "actions/upload-artifact@v7" in text
    assert "fvg-quality-recal-shadow-" in text
    assert "fvg_quality_calibration_shadow.json" in text


def test_workflow_writes_step_summary() -> None:
    text = WF.read_text()
    assert "GITHUB_STEP_SUMMARY" in text
    # Operator-visible status row.
    assert "recal status" in text
    assert "acceptance" in text


def test_workflow_is_fail_soft_on_empty_corpus() -> None:
    text = WF.read_text()
    # Corpus discovery has an explicit empty-dir fallback.
    assert "empty-fallback" in text
    assert "_empty_corpus" in text


def test_workflow_runs_after_rolling_bench() -> None:
    text = WF.read_text()
    # Cron must be later than rolling-bench (07:30 UTC) so its corpus
    # is available. Pin "0 8 * * 1-5" — change loud if schedule shifts.
    assert 'cron: "0 8 * * 1-5"' in text
    # Discovery references the rolling-bench workflow by filename.
    assert "smc-measurement-benchmark-rolling.yml" in text


def test_workflow_supports_dispatch_overrides() -> None:
    text = WF.read_text()
    for inp in ("corpus-dir", "label-source", "acceptance-mode"):
        assert inp in text, f"missing workflow_dispatch input: {inp}"
