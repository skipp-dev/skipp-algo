"""Tests for ``scripts/sprint_inventory.py``.

Behaviour pinned:
1. Functions, classes, and module docstrings whose text matches the
   keyword (case-insensitive substring) are reported.
2. Tests under ``tests/`` and files under noise dirs (``__pycache__``,
   ``.venv``, ``artifacts``) are NOT scanned.
3. Empty result reports "Treat as greenfield".
4. JSON output is parsable and contains all hits.
5. CLI ``--out`` writes a file and emits a stderr summary.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts import sprint_inventory


@pytest.fixture
def sample_repo(tmp_path: Path) -> Path:
    """Build a minimal repo tree exercising every match path."""
    (tmp_path / "open_prep").mkdir()
    (tmp_path / "open_prep" / "outcomes.py").write_text(
        '"""Outcome backfill helpers for walk-forward."""\n'
        "def compute_outcome(x):\n"
        "    return x\n"
        "class OutcomeBundle:\n"
        "    pass\n"
        "def unrelated_helper():\n"
        "    return 0\n",
        encoding="utf-8",
    )
    (tmp_path / "smc_core").mkdir()
    (tmp_path / "smc_core" / "scoring.py").write_text(
        '"""SMC scoring primitives."""\n'
        "def score_zone(z):\n"
        "    '''Score a zone using the outcome window.'''\n"
        "    return z\n",
        encoding="utf-8",
    )
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_outcomes.py").write_text(
        "def test_outcome_smoke(): pass\n", encoding="utf-8",
    )
    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "open_prep" / "__pycache__").mkdir()
    (tmp_path / "open_prep" / "__pycache__" / "outcomes.cpython-312.pyc").write_text("noise", encoding="utf-8")
    return tmp_path


def test_filename_match_reports_hit(sample_repo: Path) -> None:
    result = sprint_inventory.run_inventory(("outcome",), rel_root=sample_repo)
    kinds = {(h.kind, h.name) for h in result.hits}
    assert ("filename", "outcomes.py") in kinds


def test_function_and_class_matches(sample_repo: Path) -> None:
    result = sprint_inventory.run_inventory(("outcome",), rel_root=sample_repo)
    names = {(h.kind, h.name) for h in result.hits}
    assert ("function", "compute_outcome") in names
    assert ("class", "OutcomeBundle") in names


def test_docstring_match_picks_up_score_zone(sample_repo: Path) -> None:
    """``score_zone`` doesn't have 'outcome' in its name but in its docstring."""
    result = sprint_inventory.run_inventory(("outcome",), rel_root=sample_repo)
    assert any(h.name == "score_zone" and h.kind == "function" for h in result.hits)


def test_module_docstring_match(sample_repo: Path) -> None:
    """The module docstring of outcomes.py mentions 'walk-forward'."""
    result = sprint_inventory.run_inventory(("walk-forward",), rel_root=sample_repo)
    assert any(h.kind == "module-doc" and h.name == "outcomes" for h in result.hits)


def test_tests_dir_is_excluded(sample_repo: Path) -> None:
    result = sprint_inventory.run_inventory(("outcome",), rel_root=sample_repo)
    assert all("tests/" not in h.path for h in result.hits)


def test_pycache_is_excluded(sample_repo: Path) -> None:
    result = sprint_inventory.run_inventory(("outcome",), rel_root=sample_repo)
    assert all("__pycache__" not in h.path for h in result.hits)


def test_unrelated_symbol_not_reported(sample_repo: Path) -> None:
    result = sprint_inventory.run_inventory(("outcome",), rel_root=sample_repo)
    assert all(h.name != "unrelated_helper" for h in result.hits)


def test_empty_result_renders_greenfield_message(sample_repo: Path) -> None:
    result = sprint_inventory.run_inventory(("nonexistent_token_xyz",), rel_root=sample_repo)
    md = sprint_inventory._format_markdown(result)
    assert "Treat as greenfield" in md
    assert result.files_scanned > 0


def test_json_output_is_parsable(sample_repo: Path) -> None:
    result = sprint_inventory.run_inventory(("outcome",), rel_root=sample_repo)
    payload = json.loads(sprint_inventory._format_json(result))
    assert payload["keywords"] == ["outcome"]
    assert payload["files_scanned"] >= 1
    assert isinstance(payload["hits"], list)
    assert all({"path", "line", "kind", "name"} <= h.keys() for h in payload["hits"])


def test_case_insensitive_match(sample_repo: Path) -> None:
    upper = sprint_inventory.run_inventory(("OUTCOME",), rel_root=sample_repo)
    lower = sprint_inventory.run_inventory(("outcome",), rel_root=sample_repo)
    assert {(h.path, h.name, h.line) for h in upper.hits} == {
        (h.path, h.name, h.line) for h in lower.hits
    }


def test_multiple_keywords_are_or(sample_repo: Path) -> None:
    """Two keywords match if EITHER is present (OR, not AND)."""
    result = sprint_inventory.run_inventory(("outcome", "score_zone"), rel_root=sample_repo)
    names = {h.name for h in result.hits}
    assert "compute_outcome" in names
    assert "score_zone" in names


def test_cli_writes_to_out(tmp_path: Path) -> None:
    out = tmp_path / "spec" / "sprints" / "c2_inventory.md"
    rc = subprocess.run(
        [sys.executable, "-m", "scripts.sprint_inventory", "outcome", "--out", str(out)],
        check=False,
        capture_output=True,
        text=True,
        cwd=Path(__file__).resolve().parent.parent,
    )
    assert rc.returncode == 0, rc.stderr
    assert out.exists()
    body = out.read_text(encoding="utf-8")
    assert body.startswith("# Sprint inventory")


def test_cli_runs_against_real_repo() -> None:
    """Smoke-test against the actual repo to catch path regressions."""
    rc = subprocess.run(
        [sys.executable, "-m", "scripts.sprint_inventory", "outcome", "--json"],
        check=False,
        capture_output=True,
        text=True,
        cwd=Path(__file__).resolve().parent.parent,
    )
    assert rc.returncode == 0, rc.stderr
    payload = json.loads(rc.stdout)
    assert payload["files_scanned"] > 50, (
        f"Expected to scan many files, got {payload['files_scanned']}"
    )
