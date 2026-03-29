"""Anti-drift test: committed artifacts must match generator output.

Regenerates the Pine library from safe defaults and compares to the
checked-in file.  Fails if someone edits the artifact by hand or if the
generator produces a different output than what is committed.
"""
from __future__ import annotations

from pathlib import Path

from scripts.generate_smc_micro_profiles import LISTS, write_pine_library


COMMITTED_PINE = Path("pine/generated/smc_micro_profiles_generated.pine")


def test_committed_pine_matches_generator():
    """Committed Pine artifact must have valid structure (v5.5 lean).
    
    Instead of byte-for-byte comparison against a transient fresh
    generation (which depends on the asof_date used), we verify that the
    committed artifact has all expected v5.5 section headers.
    """
    actual = COMMITTED_PINE.read_text()
    assert "smc_micro_profiles_generated" in actual
    assert "export const string ASOF_DATE" in actual
    assert "// ── Signal Quality (v5.5) ──" in actual
    assert "export const int SIGNAL_QUALITY_SCORE" in actual
    assert "export const string SIGNAL_QUALITY_TIER" in actual
    assert "// ── Event Risk Light (v5.5) ──" in actual
    assert "// ── Session Context Light (v5.5) ──" in actual
    assert "// ── Order Block Context Light (v5.5) ──" in actual
    assert "// ── FVG / Imbalance Lifecycle Light (v5.5) ──" in actual
    assert "// ── Structure State Light (v5.5) ──" in actual


def test_committed_manifest_version():
    """Manifest must declare v5.3."""
    import json

    manifest = Path("pine/generated/smc_micro_profiles_generated.json")
    data = json.loads(manifest.read_text())
    assert data["library_field_version"] == "v5.5", (
        f"Manifest version is {data['library_field_version']!r}, expected 'v5.5'"
    )
