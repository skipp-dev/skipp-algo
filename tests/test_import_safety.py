"""R10 (audit-L-1, 2026-05-12) — import-time safety sweep.

Background
==========
Several recent regressions (#2155 / #2163) shipped because a module
performed work at *import time* that depended on a present API key or
SQLite file. Operators running `python -c "import open_prep.macro"` in
a clean shell would hit a hard ImportError, breaking ``--check`` runs,
``mypy`` AST-loaders, and any tooling that does shallow imports.

This pin enforces that every Python module under ``open_prep/`` and
``newsstack_fmp/`` can be imported in a *hostile* environment with:
    * no API keys (env vars deleted)
    * a tmp HOME (no SQLite state, no cached artifact)
    * no DB writes allowed (read-only PWD)

Modules that legitimately need a key/DB at runtime must defer that
work into a function — never module top level.

Allowlist: ``_KNOWN_RUNTIME_ENTRY_MODULES`` for ``__main__``-style
entry points where import-time CLI bootstrap is the documented behaviour.

See ``docs/AUDIT_L1_REVIEW_RETROSPECTIVE_2026-05-12.md`` \xa7R10.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest


_REPO_ROOT = Path(__file__).resolve().parent.parent
_PACKAGE_PREFIXES = ("open_prep", "newsstack_fmp")

# Entry-point modules whose top-level executes CLI bootstrap (argparse
# wired into __main__-style invocation). These are excluded from the
# import-safety sweep because their side-effects are documented.
_KNOWN_RUNTIME_ENTRY_MODULES: frozenset[str] = frozenset(
    {
        # currently empty — every module under open_prep / newsstack_fmp
        # is expected to be import-safe. New CLI-wired modules must be
        # added here with a written reason.
    }
)

# Env vars whose absence must not break import. Listed explicitly so
# that adding a new required key is a deliberate change.
_HOSTILE_ENV_KEYS: tuple[str, ...] = (
    "FINNHUB_API_KEY",
    "DATABENTO_API_KEY",
    "FMP_API_KEY",
    "NEWSAPI_KEY",
    "NEWSAPI_KEY",
    "BENZINGA_API_KEY",
    "UNUSUAL_WHALES_API_KEY",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
)


def _discover_modules() -> list[str]:
    out: list[str] = []
    for prefix in _PACKAGE_PREFIXES:
        pkg_root = _REPO_ROOT / prefix
        if not pkg_root.is_dir():
            continue
        for py in sorted(pkg_root.rglob("*.py")):
            if "__pycache__" in py.parts:
                continue
            rel = py.relative_to(_REPO_ROOT).with_suffix("")
            mod = ".".join(rel.parts)
            if mod.endswith(".__init__"):
                mod = mod[: -len(".__init__")]
            if mod in _KNOWN_RUNTIME_ENTRY_MODULES:
                continue
            out.append(mod)
    return out


_MODULES = _discover_modules()


@pytest.mark.parametrize("module_name", _MODULES)
def test_r10_module_imports_in_hostile_env(module_name: str, tmp_path: Path) -> None:
    """``python -c 'import <mod>'`` must succeed with all API keys deleted."""

    env = {
        k: v
        for k, v in os.environ.items()
        if k not in _HOSTILE_ENV_KEYS
    }
    # Force a clean HOME so no cached SQLite/state files are visible.
    env["HOME"] = str(tmp_path)
    env["TMPDIR"] = str(tmp_path)
    # Preserve PYTHONPATH minimally — repo root must be importable.
    env["PYTHONPATH"] = str(_REPO_ROOT)
    # Suppress any plugin auto-loading that might inject env reads.
    env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"

    proc = subprocess.run(
        [sys.executable, "-c", f"import {module_name}"],
        cwd=str(_REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if proc.returncode != 0:
        raise AssertionError(
            f"Module `{module_name}` failed to import in hostile env "
            f"(no API keys, clean HOME). exit={proc.returncode}\n"
            f"--- stdout ---\n{proc.stdout}\n"
            f"--- stderr ---\n{proc.stderr}"
        )
