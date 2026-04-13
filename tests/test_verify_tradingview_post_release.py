from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.verify_tradingview_post_release import verify_post_release_validation


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def test_verify_post_release_validation_updates_manifest_report_path(tmp_path: Path) -> None:
    release_manifest_path = tmp_path / "library_release_manifest.json"
    validation_report_path = tmp_path / "tv_post_release_validation.json"

    _write_json(
        release_manifest_path,
        {
            "library": {
                "publishStatus": "published",
                "expectedVersion": 12,
                "publishedVersion": 12,
            },
            "lastPreflightReport": None,
        },
    )
    _write_json(
        validation_report_path,
        {
            "execution_mode": "readonly",
            "auth_reused_ok": True,
            "auth_ok": True,
            "overall_preflight_ok": True,
            "targets": [
                {
                    "scriptName": "SMC Decision Board",
                    "overall_preflight_ok": True,
                }
            ],
        },
    )

    result = verify_post_release_validation(release_manifest_path, validation_report_path)
    updated_manifest = json.loads(release_manifest_path.read_text(encoding="utf-8"))

    assert result["ok"] is True
    assert result["validated_target_count"] == 1
    assert result["last_preflight_report"] == "tv_post_release_validation.json"
    assert updated_manifest["lastPreflightReport"] == "tv_post_release_validation.json"


def test_verify_post_release_validation_rejects_non_published_manifest(tmp_path: Path) -> None:
    release_manifest_path = tmp_path / "library_release_manifest.json"
    validation_report_path = tmp_path / "tv_post_release_validation.json"

    _write_json(
        release_manifest_path,
        {
            "library": {
                "publishStatus": "not_verified",
                "expectedVersion": 12,
                "publishedVersion": 12,
            },
            "lastPreflightReport": None,
        },
    )
    _write_json(
        validation_report_path,
        {
            "execution_mode": "readonly",
            "auth_reused_ok": True,
            "auth_ok": True,
            "overall_preflight_ok": True,
            "targets": [{"scriptName": "SMC Decision Board", "overall_preflight_ok": True}],
        },
    )

    with pytest.raises(RuntimeError, match="publishStatus"):
        verify_post_release_validation(release_manifest_path, validation_report_path)


def test_verify_post_release_validation_rejects_failed_target(tmp_path: Path) -> None:
    release_manifest_path = tmp_path / "library_release_manifest.json"
    validation_report_path = tmp_path / "tv_post_release_validation.json"

    _write_json(
        release_manifest_path,
        {
            "library": {
                "publishStatus": "published",
                "expectedVersion": 12,
                "publishedVersion": 12,
            },
            "lastPreflightReport": None,
        },
    )
    _write_json(
        validation_report_path,
        {
            "execution_mode": "readonly",
            "auth_reused_ok": True,
            "auth_ok": True,
            "overall_preflight_ok": True,
            "targets": [{"scriptName": "SMC Decision Board", "overall_preflight_ok": False, "error": "compile mismatch"}],
        },
    )

    with pytest.raises(RuntimeError, match="SMC Decision Board"):
        verify_post_release_validation(release_manifest_path, validation_report_path)