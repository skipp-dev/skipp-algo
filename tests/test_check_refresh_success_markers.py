"""Tests for scripts/check_refresh_success_markers.py."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.check_refresh_success_markers import (
    check_markers,
)


def _write(path: Path, payload: dict) -> Path:
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def _complete_markers() -> dict:
    return {
        "generation_completed_at": "2026-04-18T14:00:00+00:00",
        "pipeline_completed_at": "2026-04-18T14:30:00+00:00",
        "run_number": 116,
        "runner_label": "ubuntu-24.04-4core",
        "resource_envelope": {},
        "stages": {
            "generation": "success",
            "gates": "success",
            "change_detected": "true",
            "publish": "success",
            "commit": "success",
            "post_release_gates": "success",
        },
    }


class TestCompleteMarkers:
    def test_complete_markers_pass(self, tmp_path: Path) -> None:
        result = check_markers(_write(tmp_path / "m.json", _complete_markers()))
        assert result.ok is True
        assert result.failures == []
        assert result.stages_missing == []

    def test_complete_with_skipped_stages(self, tmp_path: Path) -> None:
        payload = _complete_markers()
        payload["stages"]["publish"] = "skipped"
        payload["stages"]["commit"] = "skipped"
        payload["stages"]["post_release_gates"] = "skipped"
        result = check_markers(_write(tmp_path / "m.json", payload))
        assert result.ok is True

    def test_unchanged_library_run(self, tmp_path: Path) -> None:
        payload = _complete_markers()
        payload["stages"]["change_detected"] = "false"
        payload["stages"]["publish"] = "skipped"
        payload["stages"]["commit"] = "skipped"
        payload["stages"]["post_release_gates"] = "skipped"
        result = check_markers(_write(tmp_path / "m.json", payload))
        assert result.ok is True


class TestMissingFile:
    def test_missing_file_fails(self, tmp_path: Path) -> None:
        result = check_markers(tmp_path / "nonexistent.json")
        assert result.ok is False
        assert any("not found" in f for f in result.failures)

    def test_invalid_json_fails(self, tmp_path: Path) -> None:
        (tmp_path / "bad.json").write_text("not json", encoding="utf-8")
        result = check_markers(tmp_path / "bad.json")
        assert result.ok is False
        assert any("unreadable" in f.lower() for f in result.failures)


class TestIncompleteStages:
    def test_missing_generation_stage(self, tmp_path: Path) -> None:
        payload = _complete_markers()
        del payload["stages"]["generation"]
        result = check_markers(_write(tmp_path / "m.json", payload))
        assert result.ok is False
        assert "generation" in result.stages_missing

    def test_missing_multiple_stages(self, tmp_path: Path) -> None:
        payload = _complete_markers()
        del payload["stages"]["gates"]
        del payload["stages"]["commit"]
        result = check_markers(_write(tmp_path / "m.json", payload))
        assert result.ok is False
        assert "gates" in result.stages_missing
        assert "commit" in result.stages_missing

    def test_missing_pipeline_completed_at(self, tmp_path: Path) -> None:
        payload = _complete_markers()
        del payload["pipeline_completed_at"]
        result = check_markers(_write(tmp_path / "m.json", payload))
        assert result.ok is False
        assert any("pipeline_completed_at" in f for f in result.failures)


class TestInconsistentValues:
    def test_empty_stage_value_fails(self, tmp_path: Path) -> None:
        payload = _complete_markers()
        payload["stages"]["gates"] = ""
        result = check_markers(_write(tmp_path / "m.json", payload))
        assert result.ok is False
        assert any("empty" in f for f in result.failures)

    def test_failure_stage_is_warning(self, tmp_path: Path) -> None:
        payload = _complete_markers()
        payload["stages"]["gates"] = "failure"
        result = check_markers(_write(tmp_path / "m.json", payload))
        assert result.ok is True  # file is structurally complete
        assert any("failure" in w for w in result.warnings)

    def test_unrecognised_value_is_warning(self, tmp_path: Path) -> None:
        payload = _complete_markers()
        payload["stages"]["publish"] = "cancelled"
        result = check_markers(_write(tmp_path / "m.json", payload))
        assert result.ok is True
        assert any("unrecognised" in w for w in result.warnings)


class TestSerialization:
    def test_to_dict_is_json_serializable(self, tmp_path: Path) -> None:
        result = check_markers(_write(tmp_path / "m.json", _complete_markers()))
        d = result.to_dict()
        assert isinstance(d, dict)
        json.dumps(d)  # must not raise

    def test_checked_at_is_populated(self, tmp_path: Path) -> None:
        result = check_markers(_write(tmp_path / "m.json", _complete_markers()))
        assert result.checked_at != ""
