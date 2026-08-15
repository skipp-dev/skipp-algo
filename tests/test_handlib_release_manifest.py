"""Pin: consumer pins agree with the recorded published hand-lib versions.

The other half of ownership
===========================

Whether a pin *has an owner* is hermetically checkable. Whether a pin is
*current* was not: the hand-authored tier had no committed record of what
TradingView holds — every publisher verified the published version via the
facade and threw the number away into an uncommitted, timestamped report.
Only the generated library had such a record (`library_release_manifest.json`),
and its absence for the hand libs is exactly the blindness behind the 2026-07
chain (#3599/#3603): ``/1`` against a live ``/152`` for about four months,
CE10272 on every modern ``mp.*`` symbol, detected by nothing in CI.

``automation/tradingview/lib/tv_publish_hand_lib.ts`` now records each
verified publish into ``artifacts/tradingview/handlib_release_manifest.json``
(`recordHandLibRelease`), and ``pine-library-publish-handlibs.yml`` commits
that file in the same bot PR as the repinned consumers. This test is the
consumer half: once an entry exists, every live consumer pin must equal it.

Bootstrap honesty
=================

The manifest starts EMPTY. Seeding it from today's pins would fabricate an
observation nobody made — the repo has no record of what TradingView holds
for the nine libraries published before the manifest existed, and dated
evidence must never be back-filled (the vacuous-gates lesson). Entries appear
only from real, facade-or-exact-evidence-verified publishes; until a
library's first verified publish, this gate deliberately has nothing to say
about it. The accounting assertion below keeps that state visible instead of
silent: the number of entries checked must equal the number of entries the
manifest carries.

The R1 exemption mirrors ``test_pine_library_version_consistency.py``: an
attested source may lag its neighbours until a re-attestation PR moves it,
so attested files are excluded from the pin comparison — licence to lag,
covered elsewhere, not licence for this gate to ignore everyone.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
MANIFEST = REPO_ROOT / "artifacts" / "tradingview" / "handlib_release_manifest.json"
MODULE = REPO_ROOT / "automation" / "tradingview" / "lib" / "tv_publish_hand_lib.ts"
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "pine-library-publish-handlibs.yml"

# Alias optional, mirroring test_pine_pin_repin_ownership.py: Pine permits
# ``import owner/lib/1`` without ``as x``, and the repin mechanisms match that
# form — a currency gate narrower than the repinner would go blind exactly on
# the pin the repinner still moves (2026-08-15 review).
_IMPORT_RE = re.compile(
    r"^\s*import\s+[A-Za-z0-9_]+/(?P<lib>[A-Za-z0-9_]+)/(?P<ver>\d+)"
    r"(?!\S)(?:\s+as\s+\w+)?",
    re.MULTILINE,
)

sys.path.insert(0, str(Path(__file__).resolve().parent))
# Reused, not restated — the same parser the inventory guard already runs
# against the orchestrator's HAND_LIBS table.
from test_pine_handlib_publisher_inventory import _hand_libs


def _manifest() -> dict:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def _attested() -> frozenset[str]:
    from scripts.hold_r1_attested_sources import attested_paths

    return frozenset(attested_paths())


def _live_pins(lib: str) -> dict[str, int]:
    """Map live-surface file -> pinned version of *lib* (attested files out)."""
    attested = _attested()
    files = sorted(REPO_ROOT.glob("*.pine")) + sorted((REPO_ROOT / "SMC++").glob("*.pine"))
    out: dict[str, int] = {}
    for path in files:
        rel = path.relative_to(REPO_ROOT).as_posix()
        if rel in attested:
            continue
        for match in _IMPORT_RE.finditer(path.read_text(encoding="utf-8")):
            if match.group("lib") == lib:
                out[rel] = int(match.group("ver"))
    return out


def test_manifest_exists_with_schema_and_only_known_libraries() -> None:
    manifest = _manifest()
    assert manifest["schemaVersion"] == 1
    assert isinstance(manifest["libraries"], dict)
    known = set(_hand_libs())
    assert known, "HAND_LIBS parsed empty — the containment check would be vacuous"
    phantom = sorted(set(manifest["libraries"]) - known)
    assert not phantom, (
        f"manifest records libraries that are not in HAND_LIBS: {phantom} — "
        "either a renamed library left a stale entry behind, or something "
        "other than a hand-lib publisher wrote this file."
    )


def test_consumer_pins_match_every_recorded_published_version() -> None:
    """Once a publish is on record, no live pin may disagree with it."""
    manifest = _manifest()
    hand_libs = sorted(_hand_libs())
    assert hand_libs, "HAND_LIBS parsed empty — this test would pass vacuously"

    checked = 0
    mismatches: list[str] = []
    for lib in hand_libs:
        entry = manifest["libraries"].get(lib)
        if entry is None:
            # Bootstrap state: no verified publish recorded yet. The
            # accounting assertion below keeps this branch honest.
            continue
        checked += 1
        recorded = entry["publishedVersion"]
        for rel, pinned in sorted(_live_pins(lib).items()):
            if pinned != recorded:
                mismatches.append(
                    f"{rel} pins {lib}/{pinned} but the last verified publish "
                    f"recorded /{recorded} ({entry['publishedAt']}, "
                    f"{entry['versionVerificationMode']})"
                )

    assert checked == len(manifest["libraries"]), (
        "manifest entries exist that the loop above never checked — the "
        "containment test should have caught a phantom key first."
    )
    assert not mismatches, (
        "live consumer pins disagree with the recorded published versions:\n  - "
        + "\n  - ".join(mismatches)
        + "\n\nEither the weekly repin PR was split (pins moved without the "
        "manifest, or vice versa), or a manual repin bypassed "
        "`npm run tv:publish-handlibs`. Re-run the ordered publish+repin "
        "helper so the observation and the pins move together."
    )


def test_the_producer_side_is_wired_not_just_defined() -> None:
    """The manifest is only evidence if something writes and commits it.

    Three anchors, each a distinct way the record could silently die:
    the module could stop invoking the writer on the success path, the
    workflow could stop committing the file, or the changed-detection could
    stop noticing a manifest-only run (the FIRST verified run bumps no pin,
    so a porcelain check scoped to '*.pine' would read it as changed=false
    and drop the observation).
    """
    module_text = MODULE.read_text(encoding="utf-8")
    assert "export function recordHandLibRelease(" in module_text, (
        "recordHandLibRelease is gone from tv_publish_hand_lib.ts — nothing "
        "produces the manifest this gate consumes."
    )
    invocations = re.findall(r"(?<!function )\brecordHandLibRelease\s*\(", module_text)
    assert invocations, (
        "recordHandLibRelease is defined but never invoked — every publish "
        "would verify a version and keep throwing it away."
    )

    workflow_text = WORKFLOW.read_text(encoding="utf-8")
    add_lines = [
        line for line in workflow_text.splitlines()
        if "git add" in line and "handlib_release_manifest.json" in line
    ]
    assert add_lines, (
        "pine-library-publish-handlibs.yml no longer stages "
        "handlib_release_manifest.json — the publisher writes the record and "
        "the bot PR silently drops it."
    )
    porcelain_lines = [
        line for line in workflow_text.splitlines()
        if "porcelain" in line and "handlib_release_manifest.json" in line
    ]
    assert porcelain_lines, (
        "the changed-detection in pine-library-publish-handlibs.yml no longer "
        "watches handlib_release_manifest.json — a manifest-only run (first "
        "verified publish with no pin bump) would open no PR and lose the "
        "observation."
    )
