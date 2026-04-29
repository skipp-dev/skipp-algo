"""Hero-state vocabulary tests for the release-gate and post-release scripts.

PR 4 of the 2026-04-20 Hero Surface deep-review introduces:

* :func:`scripts.run_smc_release_gates.classify_hero_product_state` — a
  read-only vocabulary that maps a release-gate failure to a Hero Surface
  product state, parallel to the existing TV-drift classifier.
* A ``hero_state`` block on every report emitted by
  :func:`scripts.run_smc_post_release_validation.run_post_release_validation`,
  with a stable shape regardless of whether the readonly TV validation has
  already started emitting hero-specific signals.

These tests pin the vocabulary so it cannot drift silently.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from scripts.run_smc_post_release_validation import (
    HERO_STATE_FIELDS,
    run_post_release_validation,
)
from scripts.run_smc_release_gates import classify_hero_product_state


def _gate(*codes: str) -> dict:
    return {"details": {"failures": [{"code": c} for c in codes]}}


# ---------------------------------------------------------------------------
# classify_hero_product_state
# ---------------------------------------------------------------------------


def test_no_failures_returns_hero_ok() -> None:
    assert classify_hero_product_state({"details": {"failures": []}}) == "hero_ok"


def test_pure_data_absent_codes_classify_as_data_absent() -> None:
    assert classify_hero_product_state(_gate("MISSING_ARTIFACT", "META_INPUT_LOAD_FAILED")) == "hero_data_absent"


def test_pure_stale_codes_classify_as_data_stale() -> None:
    assert classify_hero_product_state(_gate("STALE_MANIFEST_GENERATED_AT", "STALE_META_NEWS_DOMAIN")) == "hero_data_stale"


def test_pure_trust_degraded_codes_classify_as_trust_degraded() -> None:
    assert classify_hero_product_state(_gate("DOMAIN_DROPPED_NEWS", "FALLBACK_META_VOLUME_DOMAIN")) == "hero_trust_degraded"


def test_pure_external_tv_drift_codes_classify_as_external_drift() -> None:
    assert classify_hero_product_state(_gate("AUTH_FAILED", "PREFLIGHT_FAILED")) == "hero_external_tv_drift"


def test_unknown_codes_alone_classify_as_unclassified() -> None:
    assert classify_hero_product_state(_gate("BRAND_NEW_CODE")) == "hero_unclassified"


def test_codes_from_two_categories_classify_as_mixed() -> None:
    assert classify_hero_product_state(_gate("MISSING_ARTIFACT", "AUTH_FAILED")) == "hero_mixed"


def test_known_plus_unknown_codes_classify_as_mixed() -> None:
    assert classify_hero_product_state(_gate("MISSING_ARTIFACT", "BRAND_NEW_CODE")) == "hero_mixed"


# ---------------------------------------------------------------------------
# run_post_release_validation hero_state block
# ---------------------------------------------------------------------------


def test_hero_state_block_present_on_success(tmp_path: Path) -> None:
    rm = tmp_path / "release_manifest.json"
    rm.write_text("{}")
    vr = tmp_path / "validation_report.json"
    vr.write_text("{}")

    with patch(
        "scripts.run_smc_post_release_validation.verify_post_release_validation",
        return_value={"ok": True, "validated_target_count": 3},
    ):
        report = run_post_release_validation(rm, vr)

    assert report["overall_status"] == "ok"
    block = report["hero_state"]
    assert set(block) == {"ready", "source", "fields", "failure_codes"}
    assert set(block["fields"]) == set(HERO_STATE_FIELDS)
    assert all(value is None for value in block["fields"].values())
    assert block["source"] == "absent"
    assert block["ready"] is False
    assert block["failure_codes"] == []


def test_hero_state_block_present_on_failure(tmp_path: Path) -> None:
    rm = tmp_path / "release_manifest.json"
    rm.write_text("{}")
    vr = tmp_path / "validation_report.json"
    vr.write_text("{}")

    err = RuntimeError("boom")
    err.failure_codes = ["AUTH_FAILED"]
    with patch(
        "scripts.run_smc_post_release_validation.verify_post_release_validation",
        side_effect=err,
    ):
        report = run_post_release_validation(rm, vr)

    assert report["overall_status"] == "fail"
    block = report["hero_state"]
    assert block["ready"] is False
    assert block["failure_codes"] == ["AUTH_FAILED"]
    assert all(value is None for value in block["fields"].values())


def test_hero_state_block_pulls_validation_payload_when_present(tmp_path: Path) -> None:
    rm = tmp_path / "release_manifest.json"
    rm.write_text("{}")
    vr = tmp_path / "validation_report.json"
    vr.write_text("{}")

    payload = {
        "ok": True,
        "validated_target_count": 1,
        "hero_state": {
            "market_mode": "BULLISH",
            "bias": "LONG",
            "trust": "healthy",
            "setup_quality": "good",
            "why_now": "OB reclaim",
            "risk": "",
            "action": "ACTIVE",
        },
    }
    with patch(
        "scripts.run_smc_post_release_validation.verify_post_release_validation",
        return_value=payload,
    ):
        report = run_post_release_validation(rm, vr)

    block = report["hero_state"]
    assert block["source"] == "validation_report"
    assert block["ready"] is True
    assert block["fields"]["market_mode"] == "BULLISH"
    assert block["fields"]["action"] == "ACTIVE"
    # Empty string is treated the same as missing (kept as None) so downstream
    # consumers can distinguish "unknown" from "explicitly empty".
    assert block["fields"]["risk"] is None
