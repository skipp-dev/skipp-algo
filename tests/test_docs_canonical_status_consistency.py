"""Doc-consistency guards for canonical architecture / ADR status claims.

These pin the truth-fixes made when several "canonical" / ADR docs were found
stale relative to executed reality (2026-07-12):

- ``docs/v5_5b_architecture.md`` claimed the live schema/field version while the
  generated manifest had moved on; and mis-stated the detector count + phase.
- ``docs/SMC_V2_DETECTOR_WIRING_SCOPE_2026-07-11.md`` still read "not started"
  and carried the direction-inversion as an open landmine after it was wired
  (#3406/#3407/#3411/#3501).
- ``docs/LIVE_OVERLAY_SIGNALS_ARCHITECTURE_GAP.md`` still said PR #2962 was
  "pending merge" after it merged.
- The ADR index still listed ADR-0019/0022/0023 as bare "Proposed" after their
  decisions executed; ADR-0026 records the reconciliation.

They are regression pins: if a doc drifts back to the stale claim, the matching
assertion fails.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DOCS = REPO / "docs"
MANIFEST = REPO / "pine" / "generated" / "smc_micro_profiles_generated.json"


def _read(rel: str) -> str:
    return (DOCS / rel).read_text(encoding="utf-8")


# --- v5_5b_architecture.md ------------------------------------------------- #

def test_v5_5b_flags_itself_as_version_pinned_not_live_manifest() -> None:
    """The v5.5b doc must not present its pinned schema/field version as the
    live version-of-record; it must point at the generated manifest and cite
    the manifest's *current* values (dynamic drift guard)."""
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    schema = manifest["schema_version"]
    field = manifest["library_field_version"]
    text = _read("v5_5b_architecture.md")

    assert "version-of-record" in text.lower(), (
        "v5.5b doc must carry a version-of-record note pointing at the manifest"
    )
    assert "smc_micro_profiles_generated.json" in text, (
        "v5.5b doc must name the generated manifest as the version-of-record"
    )
    # The note must quote the manifest's CURRENT versions, so a future MAJOR
    # bump re-breaks this test until the note is refreshed.
    assert schema in text, f"v5.5b doc must cite current schema_version {schema!r}"
    assert field in text, f"v5.5b doc must cite current field version {field!r}"


def test_v5_5b_detector_count_prose_matches_table() -> None:
    """Prose says "five optional detectors"; the table lists exactly five."""
    text = _read("v5_5b_architecture.md")
    assert "five optional\ndetectors" in text or "five optional detectors" in text, (
        "detector count prose must read 'five optional detectors', not 'four'"
    )
    assert "folds four optional" not in text, "stale 'four optional' prose returned"
    for detector in (
        "| Freshness v2 ",
        "| Sweep Trap ",
        "| Reaction Context ",
        "| Confluence Score ",
        "| SMT Divergence ",
    ):
        assert detector in text, f"detector table row missing: {detector!r}"


def test_v5_5b_phase_1_not_labelled_current() -> None:
    text = _read("v5_5b_architecture.md")
    assert "Phase 1 (current)" not in text, "stale 'Phase 1 (current)' label returned"
    assert "Phase 1 (foundation)" in text


# --- SMC_V2_DETECTOR_WIRING_SCOPE ------------------------------------------ #

def test_wiring_scope_reflects_executed_status() -> None:
    text = _read("SMC_V2_DETECTOR_WIRING_SCOPE_2026-07-11.md")
    # No longer advertised as an untouched scope.
    assert "SCOPE / not started — decision doc" not in text, (
        "wiring-scope status still reads 'not started' after execution"
    )
    assert "Resolution status" in text
    # The workstreams that landed must be cited by PR.
    for pr in ("#3406", "#3407", "#3411", "#3501"):
        assert pr in text, f"resolution matrix must cite {pr}"
    # SMT remains the only deferred lane.
    assert "DEFERRED" in text


def test_wiring_scope_direction_inversion_marked_resolved() -> None:
    text = _read("SMC_V2_DETECTOR_WIRING_SCOPE_2026-07-11.md")
    assert "RESOLVED by #3406" in text, (
        "direction-inversion landmine must be marked resolved by #3406"
    )


# --- LIVE_OVERLAY_SIGNALS_ARCHITECTURE_GAP --------------------------------- #

def test_live_overlay_gap_marks_2962_merged() -> None:
    text = _read("LIVE_OVERLAY_SIGNALS_ARCHITECTURE_GAP.md")
    assert "pending merge" not in text.lower(), (
        "gap doc still says PR #2962 is 'pending merge' after it merged"
    )
    assert "⏳ Pending merge" not in text
    # Implementation-status table now marks Option A merged.
    assert "✅ Merged" in text


# --- ADR index + ADR-0026 -------------------------------------------------- #

def _adr_index() -> str:
    return (DOCS / "adr" / "README.md").read_text(encoding="utf-8")


def test_adr_0026_exists_and_indexed() -> None:
    adr = DOCS / "adr" / "0026-magnitude-retarget-executed-and-ohlcv-queue-closed.md"
    assert adr.exists(), "ADR-0026 records file must exist"
    index = _adr_index()
    assert "0026-magnitude-retarget-executed-and-ohlcv-queue-closed.md" in index, (
        "ADR-0026 must be listed in the index"
    )
    # Reservation counter advanced past 0026. Keep this invariant resilient to
    # later ADRs being accepted instead of pinning the next number forever.
    match = re.search(r"The next free ADR number is \*\*(\d{4})\*\*", index)
    assert match, "ADR index must publish the next free ADR number"
    assert int(match.group(1)) > 26


def test_adr_index_no_longer_lists_executed_adrs_as_bare_proposed() -> None:
    """ADR-0023 (executed) and ADR-0019 (queue closed) must not read as bare
    'Proposed' rows in the index."""
    index = _adr_index()
    lines = {line.split("|")[1].strip(): line for line in index.splitlines()
             if line.startswith("| 00")}

    row_23 = lines["0023"]
    assert "Executed" in row_23 or "Accepted" in row_23, row_23
    assert "ADR-0026" in row_23

    row_19 = lines["0019"]
    assert "Superseded by ADR-0026" in row_19, row_19
