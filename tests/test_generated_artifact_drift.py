"""Anti-drift test: checked-in generated artifacts must match generator output.

Regenerates all three Pine artifacts into a temp directory using the same
seed fixture and compares them against the checked-in versions under
``pine/generated/``.

* Pine and snippet files are compared byte-for-byte.
* The manifest is compared structurally (path fields are excluded since
  they contain machine-dependent absolute paths when output_root differs
  from the repo root).

If this test fails, run::

    python -m scripts.refresh_generated_artifacts

then commit the updated artifacts.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.refresh_generated_artifacts import GENERATED_DIR, refresh

REPO_ROOT = Path(__file__).resolve().parent.parent

# Files compared byte-for-byte
EXACT_ARTIFACTS = [
    "smc_micro_profiles_generated.pine",
    "smc_micro_profiles_core_import_snippet.pine",
]

# Manifest keys that contain machine-dependent paths — skip in comparison
_PATH_KEYS = {
    "input_path", "schema_path", "features_csv", "lists_csv",
    "state_csv", "diff_report_md", "pine_library", "core_import_snippet",
    # Governance fields depend on whether a prior manifest exists at the
    # target path.  When regenerating to a temp directory no prior exists,
    # so schema_version_previous / version_change_type / auto_commit_allowed
    # will differ from the checked-in manifest.
    "schema_version_previous", "version_change_type", "auto_commit_allowed",
}


class TestGeneratedArtifactDrift:
    """Fail if checked-in artifacts diverge from generator output."""

    @pytest.fixture(scope="class")
    def regenerated(self, tmp_path_factory: pytest.TempPathFactory) -> Path:
        """Regenerate artifacts into a temp directory once per class."""
        tmp = tmp_path_factory.mktemp("regen")
        refresh(output_root=tmp)
        return tmp

    @pytest.mark.parametrize("artifact", EXACT_ARTIFACTS)
    def test_artifact_matches(self, regenerated: Path, artifact: str):
        checked_in = GENERATED_DIR / artifact
        fresh = regenerated / "pine" / "generated" / artifact

        assert checked_in.exists(), (
            f"Checked-in artifact missing: {checked_in.relative_to(REPO_ROOT)}"
        )
        assert fresh.exists(), (
            f"Generator did not produce: {artifact}"
        )

        checked_in_text = checked_in.read_text(encoding="utf-8")
        fresh_text = fresh.read_text(encoding="utf-8")

        if checked_in_text != fresh_text:
            # Build a helpful diff summary (first 10 differing lines)
            old_lines = checked_in_text.splitlines()
            new_lines = fresh_text.splitlines()
            diffs: list[str] = []
            for i, (o, n) in enumerate(zip(old_lines, new_lines), 1):
                if o != n:
                    diffs.append(f"  L{i}:  checked-in: {o!r}")
                    diffs.append(f"  L{i}:  generator:  {n!r}")
                if len(diffs) >= 20:
                    break
            if len(old_lines) != len(new_lines):
                diffs.append(
                    f"  Line count: checked-in={len(old_lines)}, generator={len(new_lines)}"
                )
            diff_report = "\n".join(diffs)
            pytest.fail(
                f"Checked-in {artifact} is stale — run:\n\n"
                f"    python -m scripts.refresh_generated_artifacts\n\n"
                f"First differences:\n{diff_report}"
            )

    def test_manifest_structure_matches(self, regenerated: Path):
        """Compare manifest structurally, excluding machine-dependent path fields."""
        checked_in = json.loads(
            (GENERATED_DIR / "smc_micro_profiles_generated.json").read_text()
        )
        fresh = json.loads(
            (regenerated / "pine" / "generated" / "smc_micro_profiles_generated.json").read_text()
        )
        checked_filtered = {k: v for k, v in checked_in.items() if k not in _PATH_KEYS}
        fresh_filtered = {k: v for k, v in fresh.items() if k not in _PATH_KEYS}
        assert checked_filtered == fresh_filtered, (
            "Checked-in manifest is stale — run:\n\n"
            "    python -m scripts.refresh_generated_artifacts\n\n"
            f"Differences (excluding path fields):\n"
            f"  checked-in keys: {sorted(checked_filtered.keys())}\n"
            f"  generator  keys: {sorted(fresh_filtered.keys())}"
        )

    def test_v5_field_count(self, regenerated: Path):
        """Sanity check: the Pine library contains the expected v5.5 field count."""
        pine = (regenerated / "pine" / "generated" / "smc_micro_profiles_generated.pine").read_text()
        exports = [l for l in pine.splitlines() if l.startswith("export const")]
        # v5.5 Lean adds 32 new fields on top of the v5.3 base (256 → 288)
        assert len(exports) >= 280, (
            f"Expected at least 280 export const fields (v5.5 lean), got {len(exports)}"
        )

    def test_manifest_has_v5_meta_keys(self, regenerated: Path):
        """Manifest must contain the v5 top-level meta fields."""
        import json

        manifest = json.loads(
            (regenerated / "pine" / "generated" / "smc_micro_profiles_generated.json").read_text()
        )
        assert "library_field_version" in manifest
        assert manifest["library_field_version"] == "v5.5b"
        assert "asof_time" in manifest
        assert "refresh_count" in manifest
        assert "enrichment_blocks" in manifest

    def test_manifest_has_governance_fields(self, regenerated: Path):
        """Manifest must include governance metadata from the version policy."""
        manifest = json.loads(
            (regenerated / "pine" / "generated" / "smc_micro_profiles_generated.json").read_text()
        )
        for key in ("schema_version", "schema_version_previous",
                     "version_change_type", "auto_commit_allowed"):
            assert key in manifest, f"Manifest missing governance field: {key}"
