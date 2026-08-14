"""The build number is only worth as much as its binding to a source hash.

A Pine script cannot state its own hash — the value is self-referential — so
the shadow payload names a build instead and the receiver resolves the hash
from the contract. That indirection is safe only while "build N belongs to
hash X" is a fact somebody enforces, and it cannot be checked from a single
state: two different sources could carry the same number if an increment is
forgotten.

`buildHistory` supplies the missing dimension, and the invariants below turn
"hash changed, build not incremented" into a red test. The mechanism is worth
spelling out because it is not obvious: the pinned hash must equal the hash of
the current Pine file, and the current `(build, sha256)` pair must appear in
the history, and no build may carry two hashes. A semantic edit to the Pine
therefore forces a new pair into the history, and reusing the old build number
for it violates the third rule. No date, no clock, no human diligence needed.

See docs/superpowers/specs/2026-08-13-hold-manager-alert-decoupling-design.md.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from pathlib import Path
from typing import Any

import pytest

from scripts.smc_hold_manager_replay import freeze_library_pin
from services.live_overlay_daemon.hold_manager_shadow_receiver import (
    _load_contract,
)

ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = (
    ROOT / "artifacts" / "governance" / "smc_hold_manager_shadow_contract.json"
)
SOURCE_PATH = ROOT / "SMC_Hold_Manager.pine"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

# Build 1 is not an internal bookkeeping number: it is the source attested on
# 2026-07-28 and running on TradingView, and it is the hash the six live alerts
# carry in their hand-typed bodies. Pinning it here closes the one way the
# other invariants could be satisfied dishonestly — rewriting a history entry
# in place instead of appending a new one.
BUILD_1_SHA256 = "1761e96aaf5e62412329bb7be10383c36fce4e471b98467f86e1ce63ba360813"


def _contract() -> dict[str, Any]:
    return json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))


def _pine_sha256() -> str:
    source = freeze_library_pin(SOURCE_PATH.read_text(encoding="utf-8"))
    return hashlib.sha256(source.encode()).hexdigest()


def _write(tmp_path: Path, contract: dict[str, Any]) -> Path:
    path = tmp_path / "contract.json"
    path.write_text(json.dumps(contract), encoding="utf-8")
    return path


def test_the_history_is_not_empty() -> None:
    """Every assertion below quantifies over the history.

    An empty list satisfies all of them vacuously, so the population is
    checked before anything is claimed about it.
    """
    assert len(_contract()["buildHistory"]) >= 1


def test_every_history_entry_has_exactly_a_build_and_a_hash() -> None:
    for entry in _contract()["buildHistory"]:
        assert set(entry) == {"build", "sha256"}, entry
        assert isinstance(entry["build"], int) and entry["build"] >= 1, entry
        assert _SHA256_RE.match(entry["sha256"]), entry


def test_no_build_number_carries_two_different_hashes() -> None:
    """The load-bearing rule.

    This is what makes a forgotten increment impossible rather than merely
    unlikely: the pinned hash must track the Pine file, so a semantic edit
    forces a new pair, and reusing the old number collides here.
    """
    seen: dict[int, str] = {}
    for entry in _contract()["buildHistory"]:
        previous = seen.setdefault(entry["build"], entry["sha256"])
        assert previous == entry["sha256"], (
            f"build {entry['build']} is recorded with two different hashes: "
            f"{previous} and {entry['sha256']}"
        )


def test_no_hash_is_recorded_under_two_build_numbers() -> None:
    """The other direction, which would make the mapping ambiguous too."""
    seen: dict[str, int] = {}
    for entry in _contract()["buildHistory"]:
        previous = seen.setdefault(entry["sha256"], entry["build"])
        assert previous == entry["build"], (
            f"hash {entry['sha256']} is recorded under builds "
            f"{previous} and {entry['build']}"
        )


def test_the_current_pair_is_in_the_history_and_is_the_newest() -> None:
    contract = _contract()
    source = contract["source"]
    history = contract["buildHistory"]

    assert {
        "build": source["build"],
        "sha256": source["sha256"],
    } in history
    assert source["build"] == max(entry["build"] for entry in history)


def test_build_one_still_names_the_source_attested_on_2026_07_28() -> None:
    """History is append-only, and this is what makes that checkable.

    Without this pin, a semantic Pine edit could be absorbed by editing build
    1's hash in place: the current pair would still be in the history, no
    build would carry two hashes, and the increment would never happen.
    """
    history = {entry["build"]: entry["sha256"] for entry in _contract()["buildHistory"]}

    assert history[1] == BUILD_1_SHA256


def test_the_pinned_hash_is_the_hash_of_the_pine_file() -> None:
    """Recomputed, not read.

    Without this the history could be perfectly self-consistent and still
    describe a source nobody ships.
    """
    assert _contract()["source"]["sha256"] == _pine_sha256()


@pytest.mark.parametrize(
    ("label", "mutate"),
    [
        (
            "same build, two hashes",
            lambda c: c["buildHistory"].append(
                {"build": c["source"]["build"], "sha256": "f" * 64}
            ),
        ),
        (
            "current pair missing from the history",
            lambda c: c.__setitem__("buildHistory", [{"build": 99, "sha256": "a" * 64}]),
        ),
        (
            "build below one",
            lambda c: c["source"].__setitem__("build", 0),
        ),
    ],
)
def test_the_deployed_receiver_refuses_a_broken_history(
    tmp_path: Path,
    label: str,
    mutate: Any,
) -> None:
    """The same invariant, enforced where a bad deploy would land.

    The repository guard above cannot protect a container that was built from
    a corrupted tree, so `_load_contract` carries a fail-closed copy. Each
    case is a real mutation: the unmutated contract must load, or these three
    would pass by rejecting everything.
    """
    assert _load_contract(CONTRACT_PATH).source_build >= 1

    contract = copy.deepcopy(_contract())
    mutate(contract)

    with pytest.raises(RuntimeError):
        _load_contract(_write(tmp_path, contract))
