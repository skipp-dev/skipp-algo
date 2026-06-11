"""Drift guard for the Pine input-provenance artifact.

``reports/pine_input_provenance.json`` is a machine-readable parameter
reference for the entire active Pine suite — including *hidden*
(``display=display.none``) operator inputs. It gives every input explicit
provenance: declaring file, line, variable, label, group and policy
visibility class.

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
from pine_input_surface import build_provenance

_ARTIFACT = _REPO_ROOT / "reports" / "pine_input_provenance.json"
_EXCLUDE_NAMES = frozenset({"test_div.pine"})

_REFRESH_HINT = (
    "Regenerate it with:\n"
    "    python pine_input_surface.py provenance "
    "<suite *.pine> --out reports/pine_input_provenance.json"
)


def _suite_files() -> list[Path]:
    return sorted(
        p for p in _REPO_ROOT.glob("*.pine") if p.name not in _EXCLUDE_NAMES
    )


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
    assert data["schema"] == "pine-input-provenance/v1"
    assert data["total_inputs"] == sum(f["input_count"] for f in data["files"])
    assert data["total_hidden"] == sum(f["hidden_count"] for f in data["files"])


def test_hidden_inputs_have_provenance() -> None:
    # The core value of the artifact: every hidden input is attributable.
    data = json.loads(_ARTIFACT.read_text(encoding="utf-8"))
    for f in data["files"]:
        for inp in f["inputs"]:
            if inp["has_display_none"]:
                assert inp["varname"], f"Hidden input without varname in {f['file']}"
                assert inp["lineno"] >= 1
