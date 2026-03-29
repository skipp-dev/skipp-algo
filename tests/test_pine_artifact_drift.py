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
    """Committed Pine artifact must equal freshly generated output."""
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        fresh = Path(td) / "fresh.pine"
        empty_lists = {k: [] for k in LISTS}
        write_pine_library(
            fresh,
            lists=empty_lists,
            asof_date="2026-01-01",
            universe_size=0,
            enrichment={},
        )
        expected = fresh.read_text()

    actual = COMMITTED_PINE.read_text()
    assert actual == expected, (
        "Committed pine/generated/smc_micro_profiles_generated.pine "
        "does not match generator output.  Re-run:\n"
        "  python3 -c 'from scripts.generate_smc_micro_profiles import ...'\n"
        "or delete the file and let CI regenerate it."
    )


def test_committed_manifest_version():
    """Manifest must declare v5.3."""
    import json

    manifest = Path("pine/generated/smc_micro_profiles_generated.json")
    data = json.loads(manifest.read_text())
    assert data["library_field_version"] == "v5.3", (
        f"Manifest version is {data['library_field_version']!r}, expected 'v5.3'"
    )
