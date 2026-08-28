"""Tests for scripts/hold_smcpp_sources.py.

The change class under test is the #5148 gap: the handlibs publish stages
``'SMC++'/*.pine`` wholesale out of a stale checkout after the publisher
rewrote pin lines in it, so a mid-run merge into a non-attested SMC++ source
would be reverted on the bot lane (the 2026-08-12 #4646 class, for library
sources). The classifier and the hold mechanics are the customer-surface
hold's — imported, not re-implemented — so this file tests only what is new:
the roster derivation from the publisher's own table, the attested
exclusion (no double responsibility with the R1 hold), and the fail-closed
floor. Classifier behaviour is executed by
``tests/test_hold_customer_surfaces.py``; the workflow composition by
``tests/test_hold_smcpp_sources_wiring.py``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import scripts.hold_smcpp_sources as hold_smcpp_sources
from scripts.hold_smcpp_sources import (
    hand_lib_sources,
    held_smcpp_sources,
    main,
    render_notice,
)

import scripts.hold_customer_surfaces as hold_customer_surfaces

_REPO = Path(__file__).resolve().parents[1]


def test_hand_lib_sources_derive_from_the_publisher_table() -> None:
    sources = hand_lib_sources()
    assert len(sources) >= 10, (
        "the HAND_LIBS derivation lost the population it exists to cover "
        "(10 sources measured 2026-08-28)"
    )
    for src in sources:
        assert src.startswith("SMC++/") and src.endswith(".pine"), src
        assert (_REPO / src).is_file(), (
            f"{src} is in the publisher's HAND_LIBS table but not in the "
            "tree — the parse or the table is wrong"
        )


def test_the_hold_mechanics_are_the_shared_ones() -> None:
    """One classifier, one restore — a second copy is the drift this repo
    already paid for (#5145's enumeration split)."""
    assert hold_smcpp_sources.hold is hold_customer_surfaces.hold


def test_roster_is_the_candidates_minus_the_attested_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No double responsibility with the R1 hold, derived not assumed.

    Today no SMC++ source is attested (both contract targets sit at the repo
    root), so the exclusion is exercised with a synthetic roster: if an SMC++
    source is ever attested, its stricter unconditional hold owns it and
    classifying it here as pin-only would re-open the door that hold closes.
    """
    candidates = sorted(hand_lib_sources())
    assert held_smcpp_sources(candidates, repo=_REPO) == candidates

    attested = candidates[0]
    monkeypatch.setattr(
        "scripts.hold_r1_attested_sources.attested_paths", lambda: [attested]
    )
    assert held_smcpp_sources(candidates, repo=_REPO) == candidates[1:]


def test_roster_missing_a_hand_lib_source_is_refused() -> None:
    candidates = sorted(hand_lib_sources())
    dropped = candidates.pop()
    with pytest.raises(ValueError, match=dropped.replace("+", r"\+")):
        held_smcpp_sources(candidates, repo=_REPO)


def test_a_source_gone_from_this_tree_is_not_required(tmp_path: Path) -> None:
    """Mid-run rename tolerance, mirroring required_customer_surfaces: a
    source the working tree does not carry cannot be demanded of it."""
    (tmp_path / "SMC++").mkdir()
    kept = sorted(hand_lib_sources())[0]
    (tmp_path / kept).parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / kept).write_text("export x() => 1\n", encoding="utf-8")
    assert held_smcpp_sources([kept], repo=tmp_path) == [kept]


def test_main_holds_reports_and_keeps_the_rest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The CLI seam end to end on a two-file roster: one stale-tree revert
    held to base content, one pure pin bump kept."""
    base = tmp_path / "base"
    repo = tmp_path / "repo"
    for root in (base, repo):
        (root / "SMC++").mkdir(parents=True)
    monkeypatch.setattr(
        hold_smcpp_sources,
        "hand_lib_sources",
        lambda: ["SMC++/smc_utils.pine", "SMC++/smc_profile_engine.pine"],
    )

    pin = "import preuss_steffen/smc_core_types/5 as ct\n"
    bumped = "import preuss_steffen/smc_core_types/6 as ct\n"
    fix = "export fixed_helper() => 42\n"
    (base / "SMC++" / "smc_utils.pine").write_text(
        pin + "export f() => 1\n" + fix, encoding="utf-8"
    )
    (repo / "SMC++" / "smc_utils.pine").write_text(
        bumped + "export f() => 1\n", encoding="utf-8"
    )
    (base / "SMC++" / "smc_profile_engine.pine").write_text(
        pin + "export g() => 2\n", encoding="utf-8"
    )
    (repo / "SMC++" / "smc_profile_engine.pine").write_text(
        bumped + "export g() => 2\n", encoding="utf-8"
    )

    out = tmp_path / "github_output"
    rc = main(
        [
            "--base-dir", str(base),
            "--repo", str(repo),
            "--github-output", str(out),
            "SMC++/smc_utils.pine",
            "SMC++/smc_profile_engine.pine",
        ]
    )
    assert rc == 0
    assert (repo / "SMC++" / "smc_utils.pine").read_text(encoding="utf-8") == (
        pin + "export f() => 1\n" + fix
    )
    assert (repo / "SMC++" / "smc_profile_engine.pine").read_text(
        encoding="utf-8"
    ) == (bumped + "export g() => 2\n")
    text = out.read_text(encoding="utf-8")
    assert 'held=["SMC++/smc_utils.pine"]' in text.replace("held=", "held=", 1)
    assert json.loads(text.split("held=", 1)[1].splitlines()[0]) == [
        "SMC++/smc_utils.pine"
    ]


def test_notice_names_every_held_path_and_the_incident_class() -> None:
    notice = render_notice(["SMC++/smc_utils.pine"])
    assert "SMC++/smc_utils.pine" in notice
    assert "revert" in notice
    assert "SMC++ library sources held" in notice
