"""Tests for scripts/hold_customer_surfaces.py.

The change class under test is the 2026-08-12 incident (PR #4646 / refresh run
1192): the refresh committed customer surfaces out of a stale working tree and
thereby reverted #4639's operator-vocabulary removal 59 seconds after its
merge, on a green bot PR. The classifier tests below replay exactly that
signature on the REAL checked-in surfaces, not on a toy fixture: a pin bump
plus any other edit must classify ``other`` and be held; a pure pin bump must
classify ``pin-only`` and pass.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from scripts.check_customer_surface_vocabulary import PINE_FILES
from scripts.hold_customer_surfaces import (
    classify_pin_only_change,
    held_customer_surfaces,
    hold,
    main,
    render_notice,
    required_customer_surfaces,
)

_REPO = Path(__file__).resolve().parents[1]

_ANY_PIN = re.compile(
    r"^(import[ \t]+preuss_steffen/[A-Za-z0-9_]+/)(\d+)", re.MULTILINE
)


def _bump_every_pin(text: str) -> str:
    """What a refresh legitimately does: move every import pin, nothing else."""
    bumped = _ANY_PIN.sub(lambda m: f"{m.group(1)}{int(m.group(2)) + 1}", text)
    assert bumped != text, "fixture has no pin to bump — the test would be vacuous"
    return bumped


# ---------------------------------------------------------------------------
# Classifier, on the real customer surfaces (population, not a sample).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("surface", sorted(PINE_FILES))
def test_identical_content_classifies_identical(surface: str) -> None:
    text = (_REPO / surface).read_text(encoding="utf-8")
    assert classify_pin_only_change(text, text) == "identical"


@pytest.mark.parametrize("surface", sorted(PINE_FILES))
def test_a_pure_pin_bump_classifies_pin_only(surface: str) -> None:
    """Every pin in the file at once — SMC_Long_Dip_Suite.pine carries ten,
    which is exactly what the Event-Overlay classifier could not reconstruct."""
    text = (_REPO / surface).read_text(encoding="utf-8")
    assert classify_pin_only_change(text, _bump_every_pin(text)) == "pin-only"


@pytest.mark.parametrize("surface", sorted(PINE_FILES))
def test_the_incident_signature_classifies_other(surface: str) -> None:
    """Pin bump PLUS a content edit — the #4646 revert shape, per surface."""
    text = (_REPO / surface).read_text(encoding="utf-8")
    reverted = _bump_every_pin(text).replace("overlay = true", "overlay = false", 1)
    assert reverted != _bump_every_pin(text), (
        f"{surface} no longer contains the edited marker line; "
        "pick a new non-pin line for the incident replay"
    )
    assert classify_pin_only_change(text, reverted) == "other"


def test_a_content_edit_without_any_pin_bump_classifies_other() -> None:
    text = (_REPO / "SMC_Long_Dip_Dashboard.pine").read_text(encoding="utf-8")
    assert (
        classify_pin_only_change(text, text.replace("overlay = true", "overlay = false", 1))
        == "other"
    )


def test_an_added_line_classifies_other() -> None:
    text = (_REPO / "SMC_Long_Dip_Dashboard.pine").read_text(encoding="utf-8")
    assert (
        classify_pin_only_change(text, _bump_every_pin(text) + "\n// stray note\n")
        == "other"
    )


def test_a_removed_line_classifies_other() -> None:
    text = (_REPO / "SMC_Long_Dip_Dashboard.pine").read_text(encoding="utf-8")
    lines = _bump_every_pin(text).splitlines(keepends=True)
    assert classify_pin_only_change(text, "".join(lines[:-1])) == "other"


def test_an_added_import_classifies_other() -> None:
    """A pin nobody on main declared is not a repin — it is a new dependency."""
    base = 'import preuss_steffen/smc_utils/4 as u\nplot(u.x)\n'
    current = (
        "import preuss_steffen/smc_utils/5 as u\n"
        "import preuss_steffen/smc_draw/3 as d\n"
        "plot(u.x)\n"
    )
    assert classify_pin_only_change(base, current) == "other"


def test_a_changed_alias_classifies_other() -> None:
    base = "import preuss_steffen/smc_utils/4 as u\nplot(u.x)\n"
    current = "import preuss_steffen/smc_utils/5 as util\nplot(u.x)\n"
    assert classify_pin_only_change(base, current) == "other"


def test_a_base_without_any_pin_classifies_other() -> None:
    """Not a consumer: there is nothing a refresh may legitimately change."""
    assert classify_pin_only_change("plot(1)\n", "plot(2)\n") == "other"


def test_an_alias_less_pin_is_still_a_pin() -> None:
    """Pine permits `import owner/lib/1` without an alias; the ownership guard
    (tests/test_pine_pin_repin_ownership.py) measured that alias-mandatory
    patterns let that form escape."""
    base = "import preuss_steffen/smc_utils/4\nplot(1)\n"
    current = "import preuss_steffen/smc_utils/5\nplot(1)\n"
    assert classify_pin_only_change(base, current) == "pin-only"


# ---------------------------------------------------------------------------
# Roster: parallel to the R1 roster, floor-checked, attested excluded.
# ---------------------------------------------------------------------------


def test_required_surfaces_are_the_vocabulary_guard_roster() -> None:
    """Single source: the four names come from the vocabulary guard, and the
    paid incident's four surfaces are all of them."""
    required = required_customer_surfaces()
    assert required == sorted(PINE_FILES)
    for surface in (
        "SMC_Long_Dip_Suite.pine",
        "SMC_Long_Dip_Dashboard.pine",
        "SMC_Long_Dip_Mobile.pine",
        "SMC_Long_Dip_Alerts.pine",
    ):
        assert surface in required, f"{surface} left the customer-surface roster"
    for surface in required:
        assert (_REPO / surface).is_file(), f"{surface} is rostered but not in the tree"


def test_roster_excludes_the_r1_attested_companions() -> None:
    """The R1 companions have their own, stricter hold; classifying them here
    as pin-only would re-open the door that hold closes."""
    candidates = [*sorted(PINE_FILES), "SMC_Event_Overlay.pine", "SMC_Exit_Signal.pine"]
    roster = held_customer_surfaces(candidates)
    assert "SMC_Event_Overlay.pine" not in roster
    assert "SMC_Exit_Signal.pine" not in roster
    assert set(sorted(PINE_FILES)) <= set(roster)


def test_roster_missing_a_customer_surface_is_refused() -> None:
    """Fail closed: a shrunken candidate list must never yield an all-clear."""
    candidates = [s for s in sorted(PINE_FILES) if s != "SMC_Long_Dip_Dashboard.pine"]
    with pytest.raises(ValueError, match=re.escape("SMC_Long_Dip_Dashboard.pine")):
        held_customer_surfaces(candidates)


# ---------------------------------------------------------------------------
# hold(): the tree afterwards, not the words.
# ---------------------------------------------------------------------------


def _tree(tmp_path: Path, name: str, files: dict[str, str]) -> Path:
    root = tmp_path / name
    root.mkdir()
    for rel, body in files.items():
        (root / rel).write_text(body, encoding="utf-8")
    return root


def test_hold_restores_other_and_keeps_pin_only(tmp_path: Path) -> None:
    base_dashboard = (
        "import preuss_steffen/smc_micro_profiles_generated/220 as mp\n"
        'var string g_bus_diag = "3. Chart Link - Context Signals"\n'
    )
    base_mobile = "import preuss_steffen/smc_micro_profiles_generated/220 as mp\nplot(1)\n"
    base_dir = _tree(
        tmp_path,
        "base",
        {"SMC_Long_Dip_Dashboard.pine": base_dashboard, "SMC_Long_Dip_Mobile.pine": base_mobile},
    )
    repo = _tree(
        tmp_path,
        "repo",
        {
            # The incident: pin bumped AND the vocabulary reverted.
            "SMC_Long_Dip_Dashboard.pine": (
                "import preuss_steffen/smc_micro_profiles_generated/221 as mp\n"
                'var string g_bus_diag = "3. Operator Only - Diagnostic Support"\n'
            ),
            # A legitimate refresh: pin bumped and nothing else.
            "SMC_Long_Dip_Mobile.pine": (
                "import preuss_steffen/smc_micro_profiles_generated/221 as mp\nplot(1)\n"
            ),
        },
    )

    held, advanced = hold(
        ["SMC_Long_Dip_Dashboard.pine", "SMC_Long_Dip_Mobile.pine"],
        base_dir=base_dir,
        repo=repo,
    )

    assert held == ["SMC_Long_Dip_Dashboard.pine"]
    assert advanced == ["SMC_Long_Dip_Mobile.pine"]
    # The held file is byte-identical to current main again...
    assert (repo / "SMC_Long_Dip_Dashboard.pine").read_text(encoding="utf-8") == base_dashboard
    # ...and the pin-only file keeps its bump. Holding must not be a revert of
    # the refresh.
    assert "/221 as mp" in (repo / "SMC_Long_Dip_Mobile.pine").read_text(encoding="utf-8")


def test_hold_restores_a_deleted_surface(tmp_path: Path) -> None:
    base_dir = _tree(tmp_path, "base", {"SMC_Long_Dip_Mobile.pine": "content\n"})
    repo = tmp_path / "repo"
    repo.mkdir()

    held, advanced = hold(["SMC_Long_Dip_Mobile.pine"], base_dir=base_dir, repo=repo)

    assert held == ["SMC_Long_Dip_Mobile.pine"]
    assert advanced == []
    assert (repo / "SMC_Long_Dip_Mobile.pine").read_text(encoding="utf-8") == "content\n"


def test_hold_refuses_a_candidate_without_a_base_copy(tmp_path: Path) -> None:
    """A missing base means the caller's materialisation is broken; skipping
    would report a file as checked that nothing looked at."""
    base_dir = _tree(tmp_path, "base", {})
    repo = _tree(tmp_path, "repo", {"SMC_Long_Dip_Mobile.pine": "x\n"})

    with pytest.raises(FileNotFoundError, match=re.escape("SMC_Long_Dip_Mobile.pine")):
        hold(["SMC_Long_Dip_Mobile.pine"], base_dir=base_dir, repo=repo)


# ---------------------------------------------------------------------------
# main(): outputs, notice, fail-closed floor.
# ---------------------------------------------------------------------------


def _surface_fixture(tmp_path: Path) -> tuple[Path, Path, dict[str, str]]:
    """All four real surface names, Dashboard carrying the incident edit."""
    bases = {
        name: f"import preuss_steffen/smc_micro_profiles_generated/220 as mp\n// {name}\n"
        for name in sorted(PINE_FILES)
    }
    base_dir = _tree(tmp_path, "base", bases)
    worktree = {
        name: body.replace("/220 as mp", "/221 as mp") for name, body in bases.items()
    }
    worktree["SMC_Long_Dip_Dashboard.pine"] += "// reverted vocabulary\n"
    repo = _tree(tmp_path, "repo", worktree)
    return base_dir, repo, bases


def test_main_holds_reports_and_keeps_the_rest(tmp_path: Path) -> None:
    base_dir, repo, bases = _surface_fixture(tmp_path)
    output = tmp_path / "gh_output"
    output.write_text("", encoding="utf-8")

    code = main(
        [
            "--base-dir", str(base_dir),
            "--repo", str(repo),
            "--github-output", str(output),
            *sorted(PINE_FILES),
        ]
    )

    assert code == 0
    outputs = output.read_text(encoding="utf-8")
    assert json.loads(outputs.splitlines()[0].removeprefix("held=")) == [
        "SMC_Long_Dip_Dashboard.pine"
    ]
    assert "Customer surfaces held" in outputs
    # The outputs are a claim; the tree is the fact.
    assert (repo / "SMC_Long_Dip_Dashboard.pine").read_text(encoding="utf-8") == bases[
        "SMC_Long_Dip_Dashboard.pine"
    ]
    for name in sorted(PINE_FILES):
        if name == "SMC_Long_Dip_Dashboard.pine":
            continue
        assert "/221 as mp" in (repo / name).read_text(encoding="utf-8"), name


def test_main_emits_no_notice_when_everything_is_pin_only(tmp_path: Path) -> None:
    base_dir, repo, _ = _surface_fixture(tmp_path)
    (repo / "SMC_Long_Dip_Dashboard.pine").write_text(
        (base_dir / "SMC_Long_Dip_Dashboard.pine")
        .read_text(encoding="utf-8")
        .replace("/220 as mp", "/221 as mp"),
        encoding="utf-8",
    )
    output = tmp_path / "gh_output"
    output.write_text("", encoding="utf-8")

    code = main(
        [
            "--base-dir", str(base_dir),
            "--repo", str(repo),
            "--github-output", str(output),
            *sorted(PINE_FILES),
        ]
    )

    assert code == 0
    outputs = output.read_text(encoding="utf-8")
    assert "held=[]" in outputs
    assert "Customer surfaces held" not in outputs


def test_main_fails_closed_when_a_surface_is_missing_from_the_candidates(
    tmp_path: Path,
) -> None:
    base_dir, repo, _ = _surface_fixture(tmp_path)
    output = tmp_path / "gh_output"
    output.write_text("", encoding="utf-8")
    candidates = [s for s in sorted(PINE_FILES) if s != "SMC_Long_Dip_Alerts.pine"]

    code = main(
        [
            "--base-dir", str(base_dir),
            "--repo", str(repo),
            "--github-output", str(output),
            *candidates,
        ]
    )

    assert code == 1
    # Nothing claimed, nothing touched: the incident file keeps its bad edit,
    # visibly, rather than being half-processed under a shrunken roster.
    assert output.read_text(encoding="utf-8") == ""
    assert "reverted vocabulary" in (repo / "SMC_Long_Dip_Dashboard.pine").read_text(
        encoding="utf-8"
    )


def test_notice_names_every_held_path_and_the_incident_class() -> None:
    notice = render_notice(["SMC_Long_Dip_Dashboard.pine"])
    assert "SMC_Long_Dip_Dashboard.pine" in notice
    assert "pin" in notice.lower()
    # A reviewer must learn this is the anti-revert mechanism, not a bug.
    assert "#4646" in notice
