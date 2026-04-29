"""Tests for scripts/check_resource_envelope.py."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.check_resource_envelope import (
    check_envelope,
    format_summary_lines,
)


def _write(path: Path, payload: dict) -> Path:
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def _valid_envelope() -> dict:
    return {
        "pipeline_elapsed_s": 1200.0,
        "step_12_elapsed_s": 45.0,
        "symbol_day_features_rows": 18000,
        "symbol_day_features_mib": 12.0,
        "base_snapshot_rows": 920,
        "session_minute_rows": 1_500_000,
        "trade_days_covered": 15,
        "universe_symbols": 46,
        "batch_row_threshold": 2_000_000,
        "runner_label": "ubuntu-24.04-4core",
    }


class TestValidEnvelope:
    def test_valid_envelope_passes(self, tmp_path: Path) -> None:
        result = check_envelope(_write(tmp_path / "env.json", _valid_envelope()))
        assert result.ok is True
        assert result.envelope_found is True
        assert result.failures == []
        assert result.warnings == []
        assert result.hard_limit_violations == []

    def test_checked_at_populated(self, tmp_path: Path) -> None:
        result = check_envelope(_write(tmp_path / "env.json", _valid_envelope()))
        assert result.checked_at != ""


class TestMissingEnvelope:
    def test_missing_file_fails(self, tmp_path: Path) -> None:
        result = check_envelope(tmp_path / "nonexistent.json")
        assert result.ok is False
        assert result.envelope_found is False
        assert any("not found" in f for f in result.failures)

    def test_invalid_json_fails(self, tmp_path: Path) -> None:
        (tmp_path / "bad.json").write_text("{broken", encoding="utf-8")
        result = check_envelope(tmp_path / "bad.json")
        assert result.ok is False


class TestMissingFields:
    def test_missing_required_field(self, tmp_path: Path) -> None:
        payload = _valid_envelope()
        del payload["step_12_elapsed_s"]
        result = check_envelope(_write(tmp_path / "env.json", payload))
        assert result.ok is False
        assert any("step_12_elapsed_s" in f for f in result.failures)


class TestWarningThresholds:
    def test_session_minute_rows_warning(self, tmp_path: Path) -> None:
        payload = _valid_envelope()
        payload["session_minute_rows"] = 3_500_000
        result = check_envelope(_write(tmp_path / "env.json", payload))
        assert result.ok is True  # warning, not failure
        assert any("session_minute_rows" in w for w in result.warnings)

    def test_step_12_elapsed_warning(self, tmp_path: Path) -> None:
        payload = _valid_envelope()
        payload["step_12_elapsed_s"] = 200.0
        result = check_envelope(_write(tmp_path / "env.json", payload))
        assert result.ok is True
        assert any("step_12_elapsed_s" in w for w in result.warnings)


class TestHardLimits:
    def test_session_minute_rows_hard_limit(self, tmp_path: Path) -> None:
        payload = _valid_envelope()
        payload["session_minute_rows"] = 6_000_000
        result = check_envelope(_write(tmp_path / "env.json", payload))
        assert result.ok is False
        assert len(result.hard_limit_violations) >= 1
        assert any("session_minute_rows" in v for v in result.hard_limit_violations)

    def test_pipeline_elapsed_hard_limit(self, tmp_path: Path) -> None:
        payload = _valid_envelope()
        payload["pipeline_elapsed_s"] = 7000.0
        result = check_envelope(_write(tmp_path / "env.json", payload))
        assert result.ok is False
        assert any("pipeline_elapsed_s" in v for v in result.hard_limit_violations)


class TestSummaryFormatting:
    def test_format_summary_lines(self) -> None:
        lines = format_summary_lines(_valid_envelope())
        text = "\n".join(lines)
        assert "Resource Envelope" in text
        assert "Session minute rows" in text
        assert "Runner label" in text

    def test_empty_envelope(self) -> None:
        lines = format_summary_lines({})
        assert len(lines) == 4  # header only


class TestSerialization:
    def test_to_dict_is_json_serializable(self, tmp_path: Path) -> None:
        result = check_envelope(_write(tmp_path / "env.json", _valid_envelope()))
        d = result.to_dict()
        json.dumps(d)  # must not raise


class TestDriftAdvisories:
    def test_normal_values_no_drift(self, tmp_path: Path) -> None:
        result = check_envelope(_write(tmp_path / "env.json", _valid_envelope()))
        assert result.drift_advisories == []

    def test_approaching_threshold_triggers_drift(self, tmp_path: Path) -> None:
        payload = _valid_envelope()
        # session_minute_rows warn threshold is 3M, 60% = 1.8M
        payload["session_minute_rows"] = 2_000_000  # > 1.8M but < 3M
        result = check_envelope(_write(tmp_path / "env.json", payload))
        assert result.ok is True
        assert any("session_minute_rows" in d for d in result.drift_advisories)

    def test_below_drift_fraction_no_advisory(self, tmp_path: Path) -> None:
        payload = _valid_envelope()
        # 60% of 3M = 1.8M; 1.5M is below
        payload["session_minute_rows"] = 1_500_000
        result = check_envelope(_write(tmp_path / "env.json", payload))
        assert not any("session_minute_rows" in d for d in result.drift_advisories)

    def test_at_warning_is_warning_not_drift(self, tmp_path: Path) -> None:
        payload = _valid_envelope()
        payload["session_minute_rows"] = 3_500_000  # above warn, below hard
        result = check_envelope(_write(tmp_path / "env.json", payload))
        assert any("session_minute_rows" in w for w in result.warnings)
        assert not any("session_minute_rows" in d for d in result.drift_advisories)

    def test_step_12_elapsed_drift(self, tmp_path: Path) -> None:
        payload = _valid_envelope()
        # warn threshold = 180s, 60% = 108s
        payload["step_12_elapsed_s"] = 120.0
        result = check_envelope(_write(tmp_path / "env.json", payload))
        assert any("step_12_elapsed_s" in d for d in result.drift_advisories)
