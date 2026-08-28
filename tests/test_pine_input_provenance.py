"""Drift guard for the Pine input-provenance artifact.

``reports/pine_input_provenance.json`` is a machine-readable parameter
reference for the entire active Pine suite — including *hidden*
(``display=display.none``) operator inputs. It gives every input explicit
provenance: declaring file, variable, label, group and policy visibility
class.

Schema v2 carries no line numbers: they shifted on any edit above an input
and drowned real drift in churn (#3683 refreshed 362 line-only records
against 7 semantic ones). Source-editing passes use the live
``InputInfo.lineno`` instead — see ``pine_input_surface.build_provenance``.

This test regenerates the provenance map from source and asserts it matches
the committed artifact. Any input added, removed, renamed, regrouped or
hidden/unhidden therefore requires a deliberate artifact refresh:

    python pine_input_surface.py provenance <suite *.pine> \
        --out reports/pine_input_provenance.json

Scope: top-level ``*.pine`` files in the repo root, excluding non-script
fragments. (This is narrower than ``tests/test_pine_version_directive.py``,
which additionally guards the ``pine/skipp_*.pine`` libraries.)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT))
from pine_input_surface import active_root_pine_scripts, build_provenance

_ARTIFACT = _REPO_ROOT / "reports" / "pine_input_provenance.json"

_REFRESH_HINT = (
    "Regenerate it with:\n"
    "    python pine_input_surface.py provenance "
    "<suite *.pine> --out reports/pine_input_provenance.json"
)


def _suite_files() -> list[Path]:
    # Reuse the contract's own selection rule — never rebuild it here.
    return active_root_pine_scripts(_REPO_ROOT)


def test_artifact_exists() -> None:
    assert _ARTIFACT.exists(), (
        f"Missing provenance artifact {_ARTIFACT.name}. {_REFRESH_HINT}"
    )


def test_provenance_matches_artifact() -> None:
    committed = json.loads(_ARTIFACT.read_text(encoding="utf-8"))
    regenerated = build_provenance(_suite_files(), repo_root=_REPO_ROOT)

    assert regenerated == committed, (
        "Pine input provenance drifted from the committed artifact "
        f"({_ARTIFACT.name}). An input was added, removed, renamed, "
        f"regrouped or hidden/unhidden without refreshing it. {_REFRESH_HINT}"
    )


def test_schema_and_totals_are_consistent() -> None:
    data = json.loads(_ARTIFACT.read_text(encoding="utf-8"))
    assert data["schema"] == "pine-input-provenance/v2"
    assert data["total_inputs"] == sum(f["input_count"] for f in data["files"])
    assert data["total_hidden"] == sum(f["hidden_count"] for f in data["files"])


def test_hidden_inputs_have_provenance() -> None:
    # The core value of the artifact: every hidden input is attributable.
    data = json.loads(_ARTIFACT.read_text(encoding="utf-8"))
    for f in data["files"]:
        for inp in f["inputs"]:
            if inp["has_display_none"]:
                assert inp["varname"], f"Hidden input without varname in {f['file']}"


def test_artifact_carries_no_line_numbers() -> None:
    # v2 contract: a line number must not re-enter the committed artifact —
    # it would drift on every edit above an input and drown real changes.
    data = json.loads(_ARTIFACT.read_text(encoding="utf-8"))
    offenders = [
        f"{f['file']}:{inp['varname']}"
        for f in data["files"]
        for inp in f["inputs"]
        if "lineno" in inp
    ]
    assert not offenders, (
        "Line numbers are back in the provenance artifact "
        f"({len(offenders)} input(s), e.g. {offenders[:3]}). Editing tools take "
        "the live InputInfo.lineno; the committed contract stays semantic."
    )


# --- the artifact must be blind to layout, and sharp on semantics -----------

_PROBE = "SMC_Setup_Check.pine"


def _provenance_of(tmp_root: Path) -> dict:
    return build_provenance(active_root_pine_scripts(tmp_root), repo_root=tmp_root)


@pytest.fixture
def probe_root(tmp_path: Path) -> Path:
    (tmp_path / _PROBE).write_text(
        (_REPO_ROOT / _PROBE).read_text(encoding="utf-8"), encoding="utf-8"
    )
    return tmp_path


def test_inserting_a_line_above_an_input_does_not_change_the_artifact(
    probe_root: Path,
) -> None:
    before = _provenance_of(probe_root)
    p = probe_root / _PROBE
    p.write_text("\n// pure layout churn\n" + p.read_text(encoding="utf-8"), encoding="utf-8")
    assert _provenance_of(probe_root) == before, (
        "Layout-only edit changed the provenance artifact — the v2 contract "
        "must be blind to line shifts."
    )


@pytest.mark.parametrize(
    "old,new,what",
    [
        ('"BUS Armed"', '"BUS Armed Renamed"', "label"),
        ("group = g_bus", "group = g_other", "group"),
        ("src_armed", "src_armed_renamed", "rename"),
    ],
)
def test_semantic_edits_are_detected(
    probe_root: Path, old: str, new: str, what: str
) -> None:
    before = _provenance_of(probe_root)
    p = probe_root / _PROBE
    src = p.read_text(encoding="utf-8")
    # No skip-on-missing: a probe that lost its marker must fail loudly, not
    # pass vacuously.
    assert old in src, f"probe {_PROBE} lacks {old!r} — fix the probe"
    p.write_text(src.replace(old, new, 1), encoding="utf-8")
    assert _provenance_of(probe_root) != before, f"{what} change went undetected"


def test_removing_an_input_is_detected(probe_root: Path) -> None:
    before = _provenance_of(probe_root)
    p = probe_root / _PROBE
    kept = [ln for ln in p.read_text(encoding="utf-8").splitlines() if "input." not in ln]
    p.write_text("\n".join(kept), encoding="utf-8")
    after = _provenance_of(probe_root)
    assert after != before and after["total_inputs"] < before["total_inputs"], (
        "Removing every input went undetected"
    )


"""2026-08-28: the hiding probe moved off SMC_Setup_Check.pine — the sibling
convention now hides ALL its binding rows (`display = display.none` on every
`g_bus` input), so that file no longer carries a visible input to hide and
the probe would inject a no-op duplicate. The Confluence Hub's first
`g_display` input is visible, so hiding it must move `total_hidden`."""

_HIDE_PROBE = "SMC_Confluence_Hub.pine"


@pytest.fixture
def hide_probe_root(tmp_path: Path) -> Path:
    (tmp_path / _HIDE_PROBE).write_text(
        (_REPO_ROOT / _HIDE_PROBE).read_text(encoding="utf-8"), encoding="utf-8"
    )
    return tmp_path


def test_hiding_an_input_is_detected(hide_probe_root: Path) -> None:
    before = _provenance_of(hide_probe_root)
    p = hide_probe_root / _HIDE_PROBE
    src = p.read_text(encoding="utf-8")
    marker = "group = g_display"
    assert marker in src, f"probe {_HIDE_PROBE} lacks {marker!r} — fix the probe"
    hidden = f"display = display.none, {marker}"
    assert hidden not in src, "probe input is already hidden — the probe is vacuous"
    p.write_text(src.replace(marker, hidden, 1), encoding="utf-8")
    after = _provenance_of(hide_probe_root)
    assert after["total_hidden"] > before["total_hidden"], "Hiding an input went undetected"
