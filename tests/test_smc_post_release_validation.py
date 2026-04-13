from __future__ import annotations

import json
from pathlib import Path

from scripts.run_smc_post_release_validation import run_post_release_validation


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def test_run_post_release_validation_returns_ok_and_updates_manifest(tmp_path: Path) -> None:
    release_manifest = tmp_path / "library_release_manifest.json"
    validation_report = tmp_path / "tv_post_release_validation.json"

    _write_json(
        release_manifest,
        {
            "library": {
                "publishStatus": "published",
                "expectedVersion": "6",
                "publishedVersion": "6",
            },
        },
    )
    _write_json(
        validation_report,
        {
            "execution_mode": "readonly",
            "auth_reused_ok": True,
            "auth_ok": True,
            "overall_preflight_ok": True,
            "targets": [
                {
                    "scriptName": "SMC_Core_Engine",
                    "overall_preflight_ok": True,
                }
            ],
        },
    )

    report = run_post_release_validation(release_manifest, validation_report)

    assert report["report_kind"] == "post_release_validation"
    assert report["overall_status"] == "ok"
    assert report["validated_target_count"] == 1
    updated_manifest = json.loads(release_manifest.read_text(encoding="utf-8"))
    assert updated_manifest["lastPreflightReport"] == "tv_post_release_validation.json"


def test_run_post_release_validation_normalizes_failure(tmp_path: Path) -> None:
    release_manifest = tmp_path / "library_release_manifest.json"
    validation_report = tmp_path / "tv_post_release_validation.json"

    _write_json(
        release_manifest,
        {
            "library": {
                "publishStatus": "draft",
                "expectedVersion": "6",
                "publishedVersion": "5",
            },
        },
    )
    _write_json(
        validation_report,
        {
            "execution_mode": "readonly",
            "auth_reused_ok": True,
            "auth_ok": True,
            "overall_preflight_ok": True,
            "targets": [{"scriptName": "SMC_Core_Engine", "overall_preflight_ok": True}],
        },
    )

    report = run_post_release_validation(release_manifest, validation_report)

    assert report["report_kind"] == "post_release_validation"
    assert report["overall_status"] == "fail"
    assert report["failures"][0]["code"] == "POST_RELEASE_VALIDATION_FAILED"
    assert "publishStatus" in report["failures"][0]["message"]