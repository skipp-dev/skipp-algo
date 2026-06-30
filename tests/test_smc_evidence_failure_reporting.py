"""WS1-FT-05 — Evidence Failure Reporting.

Pins the failure-classification surface added in WS1-FT-05 across both
the evidence-lane gate (``scripts/smc_pine_evidence_gate``) and the
post-release validation report (``scripts/run_smc_post_release_validation``).

Acceptance pinned here mirrors the ticket's Definition of Done:

- Failure-Reports nennen Szenario-ID, Drift-Typ und primaeren Blocker.
- missing-artifact, stale-manifest und semantic-drift sind getrennt
  lesbar.
- Operator muessen nicht erst rohe CI-Logs lesen, um den Fehlerpfad zu
  verstehen.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest import mock

import pytest

from scripts import run_smc_post_release_validation as post_release
from scripts import smc_pine_evidence_gate as evidence_gate
from scripts.run_smc_post_release_validation import (
    FAILURE_CLASS_AUTH,
    FAILURE_CLASS_MISSING_ARTIFACT,
    FAILURE_CLASS_OTHER,
    FAILURE_CLASS_POLICY,
    FAILURE_CLASS_SEMANTIC_DRIFT,
    FAILURE_CLASS_STALE_MANIFEST,
    FAILURE_CLASS_SURFACE_DRIFT,
    POST_RELEASE_FAILURE_CLASSES,
    _build_failure_classification,
    _classify_failure_code,
    run_post_release_validation,
)
from scripts.smc_pine_evidence_gate import (
    DRIFT_TYPE_MISSING_ARTIFACT,
    DRIFT_TYPE_SEMANTIC_DRIFT,
    DRIFT_TYPE_STALE_MANIFEST,
    DRIFT_TYPES,
    build_evidence_lane_gate,
)

# ──────────────────────────────────────────────────────────────────────
# Evidence-lane gate — drift_type + primary_blocker
# ──────────────────────────────────────────────────────────────────────


class TestEvidenceLaneFailureSurface:
    def test_ok_run_has_empty_failure_buckets_and_primary_blockers(self) -> None:
        gate = build_evidence_lane_gate()
        assert gate["status"] == "ok"
        details = gate["details"]
        assert details["primary_blockers"] == []
        # All buckets are present even when empty so consumers can iterate
        # the full vocabulary without key-existence checks.
        assert set(details["failure_buckets"]) == set(DRIFT_TYPES)
        assert all(v == [] for v in details["failure_buckets"].values())

    def test_missing_artifact_failure_classifies_correctly(self) -> None:
        # Drop every fixture builder so every scenario raises KeyError.
        original = dict(evidence_gate.build_evidence_fixture.__globals__["_FIXTURE_BUILDERS"])
        try:
            evidence_gate.build_evidence_fixture.__globals__["_FIXTURE_BUILDERS"] = {}
            gate = build_evidence_lane_gate()
        finally:
            evidence_gate.build_evidence_fixture.__globals__["_FIXTURE_BUILDERS"] = original

        assert gate["status"] == "fail"
        details = gate["details"]
        assert details["scenarios_failed"] == details["scenarios_checked"]
        assert details["failure_buckets"][DRIFT_TYPE_MISSING_ARTIFACT]
        assert not details["failure_buckets"][DRIFT_TYPE_STALE_MANIFEST]
        assert not details["failure_buckets"][DRIFT_TYPE_SEMANTIC_DRIFT]
        for failure in details["failures"]:
            assert failure["drift_type"] == DRIFT_TYPE_MISSING_ARTIFACT
            assert failure["primary_blocker"].startswith("missing fixture for scenario")
            assert failure["scenario_id"]
        # primary_blockers list mirrors failure rows (scenario_id + drift type).
        assert all(
            row["drift_type"] == DRIFT_TYPE_MISSING_ARTIFACT
            for row in details["primary_blockers"]
        )

    def test_stale_manifest_failure_when_fixture_misses_required_keys(self) -> None:
        # Replace the fixture builder for the BOS scenario with one that
        # returns a fixture missing the required ``regime`` key.
        builders = dict(evidence_gate.build_evidence_fixture.__globals__["_FIXTURE_BUILDERS"])
        sentinel_id = next(iter(builders))
        original = builders[sentinel_id]
        builders[sentinel_id] = lambda: {
            "layering": {"trade_state": "ALLOWED"},
            "providers": {"stale_providers": ""},
            "signal_quality": {"SIGNAL_FRESHNESS": "fresh", "SIGNAL_QUALITY_TIER": "high"},
        }
        evidence_gate.build_evidence_fixture.__globals__["_FIXTURE_BUILDERS"] = builders
        try:
            gate = build_evidence_lane_gate()
        finally:
            builders[sentinel_id] = original
            evidence_gate.build_evidence_fixture.__globals__["_FIXTURE_BUILDERS"] = builders

        assert gate["status"] == "fail"
        stale_ids = gate["details"]["failure_buckets"][DRIFT_TYPE_STALE_MANIFEST]
        assert sentinel_id in stale_ids
        # Find the row for sentinel_id and assert the primary_blocker names
        # the missing key.
        row = next(
            r for r in gate["details"]["scenario_results"] if r["scenario_id"] == sentinel_id
        )
        assert row["drift_type"] == DRIFT_TYPE_STALE_MANIFEST
        assert "regime" in row["primary_blocker"]
        assert row["missing_keys"] == ["regime"]

    def test_semantic_drift_failure_names_first_drifted_field(self) -> None:
        real_build = build_evidence_lane_gate.__globals__["build_hero_state"]

        def drifting_build_hero_state(enrichment):
            result = dict(real_build(enrichment))
            # Force one scenario (BULLISH+fresh+high) to drift on the action.
            regime = (enrichment.get("regime") or {}).get("regime")
            freshness = (enrichment.get("signal_quality") or {}).get("SIGNAL_FRESHNESS")
            quality_tier = (enrichment.get("signal_quality") or {}).get("SIGNAL_QUALITY_TIER")
            if regime == "BULLISH" and freshness == "fresh" and quality_tier == "high":
                result["HERO_ACTION"] = "WATCH"
            return result

        with mock.patch.object(evidence_gate, "build_hero_state", drifting_build_hero_state):
            gate = build_evidence_lane_gate()

        assert gate["status"] == "fail"
        semantic_ids = gate["details"]["failure_buckets"][DRIFT_TYPE_SEMANTIC_DRIFT]
        assert semantic_ids, "expected at least one semantic_drift failure"
        # Exactly one semantic drift expected; missing/stale buckets stay empty.
        assert gate["details"]["failure_buckets"][DRIFT_TYPE_MISSING_ARTIFACT] == []
        assert gate["details"]["failure_buckets"][DRIFT_TYPE_STALE_MANIFEST] == []
        first_failure = next(
            f for f in gate["details"]["failures"]
            if f["drift_type"] == DRIFT_TYPE_SEMANTIC_DRIFT
        )
        # primary_blocker mentions the first drifted field name.
        assert "HERO_ACTION" in first_failure["primary_blocker"]
        assert first_failure["drifts"][0]["field"] == "HERO_ACTION"

    def test_failure_buckets_keep_full_vocabulary_keys(self) -> None:
        """``failure_buckets`` always exposes every drift type."""
        gate = build_evidence_lane_gate()
        assert set(gate["details"]["failure_buckets"]) == set(DRIFT_TYPES)


# ──────────────────────────────────────────────────────────────────────
# Post-release validation — failure_classification block
# ──────────────────────────────────────────────────────────────────────


class TestPostReleaseFailureClassification:
    @pytest.mark.parametrize(
        "code,expected",
        [
            ("POST_RELEASE_VALIDATION_FAILED", FAILURE_CLASS_MISSING_ARTIFACT),
            ("NO_TARGETS", FAILURE_CLASS_MISSING_ARTIFACT),
            ("PUBLISH_STATUS_NOT_PUBLISHED", FAILURE_CLASS_STALE_MANIFEST),
            ("VERSION_MISMATCH", FAILURE_CLASS_STALE_MANIFEST),
            ("MANIFEST_STALE", FAILURE_CLASS_STALE_MANIFEST),
            ("MANIFEST_MISSING_TIMESTAMP", FAILURE_CLASS_STALE_MANIFEST),
            ("TARGET_FAILED", FAILURE_CLASS_SEMANTIC_DRIFT),
            ("AUTH_NOT_REUSED", FAILURE_CLASS_AUTH),
            ("AUTH_FAILED", FAILURE_CLASS_AUTH),
            ("PREFLIGHT_FAILED", FAILURE_CLASS_SURFACE_DRIFT),
            ("TARGET_PREFLIGHT_FAILED", FAILURE_CLASS_SURFACE_DRIFT),
            ("READONLY_MODE_REQUIRED", FAILURE_CLASS_POLICY),
            ("SOMETHING_NEW", FAILURE_CLASS_OTHER),
        ],
    )
    def test_classify_failure_code(self, code: str, expected: str) -> None:
        assert _classify_failure_code(code) == expected

    def test_empty_classification_has_no_primary_blocker(self) -> None:
        result = _build_failure_classification([])
        assert result["primary_class"] is None
        assert result["primary_blocker"] is None
        assert set(result["buckets"]) == set(POST_RELEASE_FAILURE_CLASSES)
        assert all(v == [] for v in result["buckets"].values())

    def test_primary_class_priority_missing_over_stale_over_semantic(self) -> None:
        # Order in input list must NOT influence priority — the classifier
        # picks missing_artifact > stale_manifest > semantic_drift.
        result = _build_failure_classification([
            "TARGET_FAILED",                # semantic_drift
            "MANIFEST_STALE",               # stale_manifest
            "POST_RELEASE_VALIDATION_FAILED",  # missing_artifact
        ])
        assert result["primary_class"] == FAILURE_CLASS_MISSING_ARTIFACT
        assert result["primary_blocker"] == (
            f"{FAILURE_CLASS_MISSING_ARTIFACT}: POST_RELEASE_VALIDATION_FAILED"
        )

    def test_buckets_separate_three_drift_types(self) -> None:
        result = _build_failure_classification([
            "POST_RELEASE_VALIDATION_FAILED",
            "MANIFEST_STALE",
            "VERSION_MISMATCH",
            "TARGET_FAILED",
            "AUTH_FAILED",
            "PREFLIGHT_FAILED",
        ])
        buckets = result["buckets"]
        assert buckets[FAILURE_CLASS_MISSING_ARTIFACT] == ["POST_RELEASE_VALIDATION_FAILED"]
        assert buckets[FAILURE_CLASS_STALE_MANIFEST] == ["MANIFEST_STALE", "VERSION_MISMATCH"]
        assert buckets[FAILURE_CLASS_SEMANTIC_DRIFT] == ["TARGET_FAILED"]
        assert buckets[FAILURE_CLASS_AUTH] == ["AUTH_FAILED"]
        assert buckets[FAILURE_CLASS_SURFACE_DRIFT] == ["PREFLIGHT_FAILED"]

    def test_unknown_code_lands_in_other_bucket(self) -> None:
        result = _build_failure_classification(["BRAND_NEW_CODE", "AUTH_FAILED"])
        assert result["buckets"][FAILURE_CLASS_OTHER] == ["BRAND_NEW_CODE"]
        # Auth still wins over "other" in priority order.
        assert result["primary_class"] == FAILURE_CLASS_AUTH


# ──────────────────────────────────────────────────────────────────────
# End-to-end: report carries failure_classification on both branches
# ──────────────────────────────────────────────────────────────────────


def _write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


class TestReportSurface:
    def test_failure_report_includes_failure_classification(self, tmp_path: Path) -> None:
        # Validation report missing → triggers the failure branch with
        # POST_RELEASE_VALIDATION_FAILED (missing_artifact bucket).
        manifest = tmp_path / "manifest.json"
        _write(manifest, {"published_targets": []})
        report = run_post_release_validation(manifest, tmp_path / "absent.json")

        assert report["overall_status"] == "fail"
        cls = report["failure_classification"]
        assert cls["primary_class"] == FAILURE_CLASS_MISSING_ARTIFACT
        assert cls["primary_blocker"].startswith(FAILURE_CLASS_MISSING_ARTIFACT + ":")
        # missing-artifact bucket explicitly carries the failure code.
        assert "POST_RELEASE_VALIDATION_FAILED" in cls["buckets"][
            FAILURE_CLASS_MISSING_ARTIFACT
        ]

    def test_ok_report_carries_empty_classification(self, tmp_path: Path) -> None:
        # Force the underlying verifier to succeed so we exercise the OK branch.
        manifest = tmp_path / "manifest.json"
        validation = tmp_path / "validation.json"
        _write(manifest, {"published_targets": []})
        _write(validation, {"ok": True})

        with mock.patch.object(
            post_release,
            "verify_post_release_validation",
            return_value={
                "ok": True,
                "validation_timestamp": 1.0,
                "validation_timestamp_iso": "1970-01-01T00:00:01+00:00",
                "validated_target_count": 0,
            },
        ):
            report = run_post_release_validation(manifest, validation)

        assert report["overall_status"] == "ok"
        cls = report["failure_classification"]
        assert cls["primary_class"] is None
        assert cls["primary_blocker"] is None
        assert all(v == [] for v in cls["buckets"].values())
