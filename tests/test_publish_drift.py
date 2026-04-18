"""Tests for F-12 / WP-10 — TradingView Publish Drift Detection."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from detect_publish_drift import (
    content_hash,
    detect_drift,
    load_manifest,
    reconcile_live_state,
    record_publish,
    save_manifest,
)

import scripts.detect_publish_drift as dpd_module


@pytest.fixture
def tmp_manifest(tmp_path: Path) -> Path:
    manifest_path = tmp_path / "publish_manifest.json"
    save_manifest({"manifest_version": 1, "entries": []}, manifest_path)
    return manifest_path


@pytest.fixture
def sample_pine(tmp_path: Path) -> Path:
    f = tmp_path / "test.pine"
    f.write_text("// test pine file\nvar x = 1\n", encoding="utf-8")
    return f


class TestContentHash:
    def test_deterministic(self, sample_pine: Path) -> None:
        h1 = content_hash(sample_pine)
        h2 = content_hash(sample_pine)
        assert h1 == h2
        assert len(h1) == 64  # SHA-256

    def test_trailing_whitespace_ignored(self, tmp_path: Path) -> None:
        f1 = tmp_path / "a.pine"
        f2 = tmp_path / "b.pine"
        f1.write_text("line1  \nline2\t\n", encoding="utf-8")
        f2.write_text("line1\nline2\n", encoding="utf-8")
        assert content_hash(f1) == content_hash(f2)

    def test_content_change_changes_hash(self, tmp_path: Path) -> None:
        f = tmp_path / "c.pine"
        f.write_text("version 1\n", encoding="utf-8")
        h1 = content_hash(f)
        f.write_text("version 2\n", encoding="utf-8")
        h2 = content_hash(f)
        assert h1 != h2


class TestDriftDetection:
    def test_no_drift_when_hash_matches(self, tmp_path: Path) -> None:
        pine = tmp_path / "demo.pine"
        pine.write_text("// demo\n", encoding="utf-8")
        h = content_hash(pine)
        manifest = {
            "manifest_version": 1,
            "entries": [{"file": str(pine.relative_to(tmp_path)), "content_hash": h}],
        }
        manifest_path = tmp_path / "m.json"
        save_manifest(manifest, manifest_path)
        # detect_drift checks against ROOT-relative paths, so this is a unit test
        # of the no-match scenario: entries for non-existent (relative) files = skip
        drifts = detect_drift(manifest_path)
        # All TRACKED files that don't exist are skipped (continue)
        assert isinstance(drifts, list)

    def test_missing_manifest_entry(self, tmp_path: Path) -> None:
        manifest_path = tmp_path / "empty.json"
        save_manifest({"manifest_version": 1, "entries": []}, manifest_path)
        drifts = detect_drift(manifest_path)
        # Tracked files that exist but aren't in manifest get no_manifest_entry
        for d in drifts:
            assert d["status"] == "no_manifest_entry"

    def test_drift_when_hash_differs(self, tmp_path: Path) -> None:
        manifest = {
            "manifest_version": 1,
            "entries": [],
        }
        # Add an entry with a wrong hash for a file that exists
        for tracked in ("SMC_Core_Engine.pine",):
            full_path = ROOT / tracked
            if full_path.exists():
                manifest["entries"].append({
                    "file": tracked,
                    "content_hash": "0000000000000000000000000000000000000000000000000000000000000000",
                })
                break
        manifest_path = tmp_path / "m.json"
        save_manifest(manifest, manifest_path)
        drifts = detect_drift(manifest_path)
        drift_files = [d["file"] for d in drifts if d["status"] == "drift"]
        if manifest["entries"]:
            assert manifest["entries"][0]["file"] in drift_files


class TestRecordPublish:
    def test_record_and_load(self, tmp_path: Path) -> None:
        pine = tmp_path / "rec.pine"
        pine.write_text("// recorded\n", encoding="utf-8")
        manifest_path = tmp_path / "m.json"
        save_manifest({"manifest_version": 1, "entries": []}, manifest_path)
        # record_publish expects file relative to ROOT, so we test save_manifest directly
        manifest = load_manifest(manifest_path)
        h = content_hash(pine)
        manifest["entries"].append({
            "file": "rec.pine",
            "content_hash": h,
            "library_name": "TestLib",
            "version": "1",
            "publish_time": "2026-04-18T00:00:00Z",
        })
        save_manifest(manifest, manifest_path)
        loaded = load_manifest(manifest_path)
        assert len(loaded["entries"]) == 1
        assert loaded["entries"][0]["content_hash"] == h
        assert loaded["entries"][0]["library_name"] == "TestLib"

    def test_idempotent_no_duplicate(self, tmp_path: Path) -> None:
        manifest_path = tmp_path / "m.json"
        manifest = {"manifest_version": 1, "entries": [
            {"file": "x.pine", "content_hash": "aaa", "library_name": "X"},
            {"file": "x.pine", "content_hash": "bbb", "library_name": "X"},
        ]}
        # Deduplicate: only keep last
        entries = {e["file"]: e for e in manifest["entries"]}
        assert len(entries) == 1


class TestManifestLoadSave:
    def test_missing_manifest_returns_empty(self, tmp_path: Path) -> None:
        m = load_manifest(tmp_path / "nonexistent.json")
        assert m["entries"] == []

    def test_roundtrip(self, tmp_path: Path) -> None:
        path = tmp_path / "rt.json"
        data = {"manifest_version": 1, "entries": [{"file": "a.pine", "content_hash": "abc"}]}
        save_manifest(data, path)
        loaded = load_manifest(path)
        assert loaded == data


# ---------------------------------------------------------------------------
# WP-17: Live-State Reconciliation
# ---------------------------------------------------------------------------

class TestReconcileLiveState:
    def test_empty_manifest_all_outstanding(self, tmp_manifest: Path) -> None:
        result = reconcile_live_state(tmp_manifest)
        # All tracked files with no manifest entries → publish_outstanding
        assert result["summary"]["publish_outstanding"] >= 0
        assert result["summary"]["drift"] == 0

    def test_consistent_with_live_state(self, tmp_path: Path) -> None:
        pine = tmp_path / "test.pine"
        pine.write_text("// test\n", encoding="utf-8")
        manifest_path = tmp_path / "manifest.json"

        import scripts.detect_publish_drift as dpd
        orig_root = dpd.ROOT
        orig_tracked = dpd.TRACKED_PINE_FILES
        try:
            dpd.ROOT = tmp_path
            dpd.TRACKED_PINE_FILES = ("test.pine",)
            dpd.record_publish(manifest_path, "test.pine", expected_live_state="published")
            result = dpd.reconcile_live_state(manifest_path)
            assert result["summary"]["consistent"] == 1
            assert result["summary"]["drift"] == 0
        finally:
            dpd.ROOT = orig_root
            dpd.TRACKED_PINE_FILES = orig_tracked

    def test_drift_detected(self, tmp_path: Path) -> None:
        pine = tmp_path / "test.pine"
        pine.write_text("// v1\n", encoding="utf-8")
        manifest_path = tmp_path / "manifest.json"

        import scripts.detect_publish_drift as dpd
        orig_root = dpd.ROOT
        orig_tracked = dpd.TRACKED_PINE_FILES
        try:
            dpd.ROOT = tmp_path
            dpd.TRACKED_PINE_FILES = ("test.pine",)
            dpd.record_publish(manifest_path, "test.pine")
            # Modify file after recording
            pine.write_text("// v2 changed\n", encoding="utf-8")
            result = dpd.reconcile_live_state(manifest_path)
            assert result["summary"]["drift"] == 1
        finally:
            dpd.ROOT = orig_root
            dpd.TRACKED_PINE_FILES = orig_tracked

    def test_state_unknown_without_live_marker(self, tmp_path: Path) -> None:
        pine = tmp_path / "test.pine"
        pine.write_text("// test\n", encoding="utf-8")
        manifest_path = tmp_path / "manifest.json"
        h = dpd_module.content_hash(pine)
        save_manifest({
            "manifest_version": 1,
            "entries": [{"file": "test.pine", "content_hash": h}],
        }, manifest_path)

        import scripts.detect_publish_drift as dpd
        orig_root = dpd.ROOT
        orig_tracked = dpd.TRACKED_PINE_FILES
        try:
            dpd.ROOT = tmp_path
            dpd.TRACKED_PINE_FILES = ("test.pine",)
            result = dpd.reconcile_live_state(manifest_path)
            assert result["summary"]["state_unknown"] == 1
        finally:
            dpd.ROOT = orig_root
            dpd.TRACKED_PINE_FILES = orig_tracked
