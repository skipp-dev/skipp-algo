"""Unit tests for the F-V8-D5 / A9b.5 partial-run guard.

``assert_bundle_is_complete`` makes the implicit complete-coverage
contract of consumers like ``databento_preopen_fast`` and
``databento_production_workbook`` explicit: the sharded producer can
emit a merged manifest with ``partial_run=true`` when one or more
shards die, and silently consuming such a bundle would produce
corrupted preopen scopes / underreported workbooks. The helper
fails-fast by default and supports an explicit
``SMC_ALLOW_PARTIAL_BUNDLE=1`` opt-in.
"""

from __future__ import annotations

import logging

import pytest

from scripts.load_databento_export_bundle import assert_bundle_is_complete


def test_complete_bundle_passes_without_error() -> None:
    payload = {"manifest": {"partial_run": False, "shard_count": 4, "expected_shard_count": 4}}
    # Should be a no-op; no exception, no log noise.
    assert assert_bundle_is_complete(payload) is None


def test_missing_manifest_treated_as_complete() -> None:
    # Bundles loaded from older producers may not expose `manifest` at all;
    # the helper must not crash on that — it only guards the explicit
    # partial_run=true case.
    assert assert_bundle_is_complete({}) is None
    assert assert_bundle_is_complete({"manifest": None}) is None


def test_partial_run_raises_runtime_error_with_diagnostics() -> None:
    payload = {
        "manifest": {
            "partial_run": True,
            "shard_count": 3,
            "expected_shard_count": 4,
            "failed_shard_ids": [2],
        }
    }
    with pytest.raises(RuntimeError) as excinfo:
        assert_bundle_is_complete(payload, scope="baseline export bundle")
    msg = str(excinfo.value)
    # Operator needs scope, counts, failed-ids, and the override hint.
    assert "baseline export bundle" in msg
    assert "partial_run=true" in msg
    assert "shard_count=3" in msg
    assert "expected_shard_count=4" in msg
    assert "failed_shard_ids=[2]" in msg
    assert "SMC_ALLOW_PARTIAL_BUNDLE=1" in msg


def test_env_override_downgrades_to_warning(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setenv("SMC_ALLOW_PARTIAL_BUNDLE", "1")
    payload = {"manifest": {"partial_run": True, "failed_shard_ids": [1, 2]}}
    with caplog.at_level(logging.WARNING, logger="scripts.load_databento_export_bundle"):
        # Must NOT raise under explicit operator override.
        assert assert_bundle_is_complete(payload, scope="workbook") is None
    assert any("partial_run=true" in r.message for r in caplog.records), (
        "override path must still emit a warning so degraded runs are auditable"
    )


def test_env_override_only_active_for_exact_value(monkeypatch: pytest.MonkeyPatch) -> None:
    # Truthy-but-not-"1" values like "true" or "yes" must NOT activate the
    # override — we want a single explicit token to avoid accidental
    # opt-in from generic feature-flag envs.
    monkeypatch.setenv("SMC_ALLOW_PARTIAL_BUNDLE", "true")
    payload = {"manifest": {"partial_run": True}}
    with pytest.raises(RuntimeError):
        assert_bundle_is_complete(payload)
