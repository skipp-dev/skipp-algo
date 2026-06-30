from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from scripts import verify_tradingview_post_release as verify_script
from scripts.verify_tradingview_post_release import verify_post_release_validation


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _valid_manifest(*, last_preflight_report: str | None = None, published_version: int = 12) -> dict:
    return {
        "generatedAt": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "library": {
            "publishStatus": "published",
            "expectedVersion": 12,
            "publishedVersion": published_version,
        },
        "lastPreflightReport": last_preflight_report,
    }


def _valid_report(*, execution_mode: str = "readonly") -> dict:
    return {
        "execution_mode": execution_mode,
        "auth_reused_ok": True,
        "auth_ok": True,
        "overall_preflight_ok": True,
        "targets": [
            {
                "scriptName": "SMC Long-Dip Dashboard v7",
                "overall_preflight_ok": True,
            }
        ],
    }


def test_verify_post_release_validation_updates_manifest_report_path(tmp_path: Path) -> None:
    release_manifest_path = tmp_path / "library_release_manifest.json"
    validation_report_path = tmp_path / "tv_post_release_validation.json"

    _write_json(release_manifest_path, _valid_manifest())
    _write_json(validation_report_path, _valid_report())

    result = verify_post_release_validation(release_manifest_path, validation_report_path)
    updated_manifest = json.loads(release_manifest_path.read_text(encoding="utf-8"))

    assert result["ok"] is True
    assert result["validated_target_count"] == 1
    assert result["last_preflight_report"] == "tv_post_release_validation.json"
    assert isinstance(result["validation_timestamp"], float)
    assert result["validation_timestamp_iso"]
    assert updated_manifest["lastPreflightReport"] == "tv_post_release_validation.json"


def test_verify_post_release_validation_rejects_non_published_manifest(tmp_path: Path) -> None:
    release_manifest_path = tmp_path / "library_release_manifest.json"
    validation_report_path = tmp_path / "tv_post_release_validation.json"

    manifest = _valid_manifest()
    manifest["library"]["publishStatus"] = "not_verified"
    _write_json(release_manifest_path, manifest)
    _write_json(validation_report_path, _valid_report())

    with pytest.raises(RuntimeError, match="publishStatus"):
        verify_post_release_validation(release_manifest_path, validation_report_path)


def test_verify_post_release_validation_rejects_version_mismatch(tmp_path: Path) -> None:
    release_manifest_path = tmp_path / "library_release_manifest.json"
    validation_report_path = tmp_path / "tv_post_release_validation.json"

    _write_json(release_manifest_path, _valid_manifest(published_version=11))
    _write_json(validation_report_path, _valid_report())

    with pytest.raises(RuntimeError, match="expectedVersion"):
        verify_post_release_validation(release_manifest_path, validation_report_path)


def test_verify_post_release_validation_rejects_non_readonly_mode(tmp_path: Path) -> None:
    release_manifest_path = tmp_path / "library_release_manifest.json"
    validation_report_path = tmp_path / "tv_post_release_validation.json"

    _write_json(release_manifest_path, _valid_manifest())
    _write_json(validation_report_path, _valid_report(execution_mode="mutating"))

    with pytest.raises(RuntimeError, match="readonly mode"):
        verify_post_release_validation(release_manifest_path, validation_report_path)


def test_verify_post_release_validation_rejects_failed_target(tmp_path: Path) -> None:
    release_manifest_path = tmp_path / "library_release_manifest.json"
    validation_report_path = tmp_path / "tv_post_release_validation.json"

    report = _valid_report()
    report["targets"] = [{"scriptName": "SMC Long-Dip Dashboard v7", "overall_preflight_ok": False, "error": "compile mismatch"}]
    _write_json(release_manifest_path, _valid_manifest())
    _write_json(validation_report_path, report)

    with pytest.raises(RuntimeError, match="SMC Long-Dip Dashboard v7"):
        verify_post_release_validation(release_manifest_path, validation_report_path)


def test_verify_post_release_validation_emits_soft_code_for_settings_open_failure(tmp_path: Path) -> None:
    # A target that loaded on the chart but whose Settings/Inputs surface could
    # not be opened is a UI-interaction (surface) flake, not semantic drift. It
    # must emit the soft ``TARGET_PREFLIGHT_FAILED`` code so the release gate can
    # downgrade it — never the blocking ``TARGET_FAILED``. Regression for
    # smc-library-refresh run 628 (2026-06-30): "Could not open script menu for
    # settings: SMC Decision Board".
    release_manifest_path = tmp_path / "library_release_manifest.json"
    validation_report_path = tmp_path / "tv_post_release_validation.json"

    report = _valid_report()
    report["overall_preflight_ok"] = False
    report["targets"] = [
        {
            "scriptName": "SMC Decision Board",
            "overall_preflight_ok": False,
            "script_found_on_chart_ok": True,
            "settings_open_ok": False,
            "error": "Could not open script menu for settings: SMC Decision Board",
        }
    ]
    _write_json(release_manifest_path, _valid_manifest())
    _write_json(validation_report_path, report)

    with pytest.raises(RuntimeError) as exc_info:
        verify_post_release_validation(release_manifest_path, validation_report_path)

    codes = getattr(exc_info.value, "failure_codes", [])
    assert "TARGET_PREFLIGHT_FAILED" in codes
    assert "TARGET_FAILED" not in codes


def test_verify_post_release_validation_keeps_target_failed_for_chart_load_failure(tmp_path: Path) -> None:
    # A target that never became visible on the chart is a real load/runtime
    # failure (the published script could not be added), so it must remain the
    # blocking ``TARGET_FAILED`` and NOT be downgraded to the soft surface code.
    release_manifest_path = tmp_path / "library_release_manifest.json"
    validation_report_path = tmp_path / "tv_post_release_validation.json"

    report = _valid_report()
    report["overall_preflight_ok"] = False
    report["targets"] = [
        {
            "scriptName": "SMC Decision Board",
            "overall_preflight_ok": False,
            "script_found_on_chart_ok": False,
            "error": "Script did not become visible on chart after add-to-chart",
        }
    ]
    _write_json(release_manifest_path, _valid_manifest())
    _write_json(validation_report_path, report)

    with pytest.raises(RuntimeError) as exc_info:
        verify_post_release_validation(release_manifest_path, validation_report_path)

    codes = getattr(exc_info.value, "failure_codes", [])
    assert "TARGET_FAILED" in codes
    assert "TARGET_PREFLIGHT_FAILED" not in codes


def test_verify_post_release_validation_skips_manifest_rewrite_when_path_is_unchanged(tmp_path: Path) -> None:
    release_manifest_path = tmp_path / "library_release_manifest.json"
    validation_report_path = tmp_path / "tv_post_release_validation.json"

    _write_json(
        release_manifest_path,
        _valid_manifest(last_preflight_report="tv_post_release_validation.json"),
    )
    _write_json(validation_report_path, _valid_report())
    before = release_manifest_path.read_text(encoding="utf-8")

    result = verify_post_release_validation(release_manifest_path, validation_report_path)
    after = release_manifest_path.read_text(encoding="utf-8")

    assert result["manifest_updated"] is False
    assert before == after


def test_verify_post_release_validation_rejects_stale_manifest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    release_manifest_path = tmp_path / "library_release_manifest.json"
    validation_report_path = tmp_path / "tv_post_release_validation.json"

    stale_now = 1_700_000_000.0
    stale_generated = datetime.fromtimestamp(stale_now - 10_000.0, tz=UTC).isoformat().replace("+00:00", "Z")
    monkeypatch.setattr(verify_script.time, "time", lambda: stale_now)
    _write_json(release_manifest_path, {**_valid_manifest(), "generatedAt": stale_generated})
    _write_json(validation_report_path, _valid_report())

    with pytest.raises(RuntimeError, match="stale"):
        verify_post_release_validation(release_manifest_path, validation_report_path)


def test_verify_post_release_validation_accepts_fresh_manifest_and_surfaces_staleness_fields(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    release_manifest_path = tmp_path / "library_release_manifest.json"
    validation_report_path = tmp_path / "tv_post_release_validation.json"

    fresh_now = 1_700_000_000.0
    fresh_generated = datetime.fromtimestamp(fresh_now - 60.0, tz=UTC).isoformat().replace("+00:00", "Z")
    monkeypatch.setattr(verify_script.time, "time", lambda: fresh_now)
    _write_json(release_manifest_path, {**_valid_manifest(), "generatedAt": fresh_generated})
    _write_json(validation_report_path, _valid_report())

    result = verify_post_release_validation(release_manifest_path, validation_report_path)

    assert result["staleness_check"]["ok"] is True
    assert result["manifest_generated_field"] == "generatedAt"
    assert result["manifest_age_seconds"] == pytest.approx(60.0)
