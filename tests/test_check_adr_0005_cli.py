"""The ADR-0005 pre-push CLI must run in a stdlib-only interpreter.

Regression: the CLI used to ``exec_module`` the test file to reuse its
``RUNTIME_FILES`` / ``BANNED_ROOTS``, but that test imports ``pytest`` (for
``@parametrize``), so the pre-commit hook crashed with ``ModuleNotFoundError:
No module named 'pytest'`` under any interpreter without pytest (e.g. the bare
git-hook Python). The CLI now loads the pure-stdlib manifest instead.
"""

from __future__ import annotations

import sys

from scripts.adr_0005_runtime_manifest import BANNED_ROOTS, RUNTIME_FILES, imported_roots
from scripts.check_adr_0005_pure_stdlib import main


def test_cli_scans_runtime_files_green() -> None:
    assert main([]) == 0


def test_cli_ignores_non_runtime_files() -> None:
    # Pre-commit passes changed paths; a non-runtime file is a no-op (exit 0).
    assert main(["scripts/check_adr_0005_pure_stdlib.py"]) == 0


def test_cli_does_not_import_pytest(monkeypatch) -> None:
    # Make ``import pytest`` fail, mimicking the bare git-hook interpreter.
    monkeypatch.setitem(sys.modules, "pytest", None)
    # A fresh call re-loads the manifest by path; it must not need pytest.
    assert main([]) == 0


def test_manifest_is_pure_stdlib_itself() -> None:
    # The SSOT manifest must not pull in a banned heavy dep (or pytest).
    from pathlib import Path

    src = (Path(__file__).resolve().parent.parent
           / "scripts" / "adr_0005_runtime_manifest.py").read_text(encoding="utf-8")
    roots = imported_roots(src)
    assert not (roots & BANNED_ROOTS)
    assert "pytest" not in roots


def test_runtime_files_are_the_documented_pair() -> None:
    names = {p.name for p in RUNTIME_FILES}
    assert names == {"run_ab_comparison.py", "smc_sprt_stop_rule.py"}
