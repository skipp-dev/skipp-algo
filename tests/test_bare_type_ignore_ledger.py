"""Audit pin: bare ``# type: ignore`` site ledger.

A bare ``# type: ignore`` (no ``[code, ...]``) suppresses ALL type
errors on a line — that's a sledgehammer. New suppressions should be
narrowed to specific codes (``# type: ignore[return-value]`` etc.).
This pin freezes the current 29 bare-ignore sites and fails when new
ones appear.

Complements PR #152 (per-file `# type: ignore` count budget) by
disallowing the un-coded form for new sites.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent

_DIR_EXCLUDE = frozenset(
    {
        ".git",
        ".github",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".venv",
        "venv",
        "node_modules",
        "artifacts",
        "docs",
        "scripts",
        "tests",
        "SMC++",
    }
)

_BARE_TI_RE = re.compile(r"#\s*type:\s*ignore(?!\s*\[)")

_FROZEN_BARE_TYPE_IGNORE_SITES: frozenset[tuple[str, int]] = frozenset(
    {
        # ml.training.* trainers wrap optional 3rd-party deps. LightGBM
        # still needs the legacy bare-ignore import fallback shim here.
        # C10 ML-Layer.
        ("ml/training/lgbm_family_trainer.py", 11),
        ("ml/training/lgbm_family_trainer.py", 15),
        # rl.simulator.* env wrappers follow the same optional gymnasium
        # dependency pattern: bare ignores are limited to import-time fallback
        # shims and the ``None`` assignments in the ImportError path. C12 RL-Layer.
        ("rl/simulator/execution_env.py", 25),
        ("rl/simulator/execution_env.py", 26),
        ("rl/simulator/execution_env.py", 31),
        ("rl/simulator/execution_env.py", 32),
        ("rl/simulator/sb3_execution_env.py", 17),
        ("rl/simulator/sb3_execution_env.py", 18),
        ("rl/simulator/sb3_execution_env.py", 22),
        ("rl/simulator/sb3_execution_env.py", 23),
        ("terminal_bitcoin.py", 314),
        ("terminal_bitcoin.py", 398),
        ("terminal_bitcoin.py", 478),
        ("terminal_bitcoin.py", 483),
        ("terminal_bitcoin.py", 538),
        ("terminal_bitcoin.py", 552),
        ("terminal_bitcoin.py", 556),
        ("terminal_bitcoin.py", 565),
        ("terminal_bitcoin.py", 643),
        ("terminal_bitcoin.py", 698),
        ("terminal_bitcoin.py", 740),
        ("terminal_bitcoin.py", 765),
        ("terminal_bitcoin.py", 791),
        ("terminal_bitcoin.py", 844),
    }
)


def _iter_prod_py() -> list[Path]:
    out: list[Path] = []
    for p in _REPO_ROOT.rglob("*.py"):
        if any(part in _DIR_EXCLUDE for part in p.relative_to(_REPO_ROOT).parts):
            continue
        out.append(p)
    return sorted(out)


def _measured_sites() -> set[tuple[str, int]]:
    out: set[tuple[str, int]] = set()
    for path in _iter_prod_py():
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):  # pragma: no cover
            continue
        rel = path.relative_to(_REPO_ROOT).as_posix()
        for ln, line in enumerate(text.splitlines(), start=1):
            if _BARE_TI_RE.search(line):
                out.add((rel, ln))
    return out


def test_no_new_bare_type_ignore_sites() -> None:
    measured = _measured_sites()
    new = sorted(measured - _FROZEN_BARE_TYPE_IGNORE_SITES)
    assert not new, (
        "New bare `# type: ignore` site(s) introduced. Bare ignores suppress "
        "ALL errors on the line — narrow to codes "
        "(e.g. `# type: ignore[return-value]`) or, if intentional, add to "
        "_FROZEN_BARE_TYPE_IGNORE_SITES with justification:\n  - "
        + "\n  - ".join(f"{f}:{ln}" for f, ln in new)
    )


def test_no_stale_bare_type_ignore_ledger_entries() -> None:
    measured = _measured_sites()
    stale = sorted(_FROZEN_BARE_TYPE_IGNORE_SITES - measured)
    assert not stale, (
        "Stale bare `# type: ignore` ledger entries — remove from "
        "_FROZEN_BARE_TYPE_IGNORE_SITES (line shifted or suppression "
        "removed/narrowed):\n  - "
        + "\n  - ".join(f"{f}:{ln}" for f, ln in stale)
    )


@pytest.mark.parametrize("rel,_ln", sorted(_FROZEN_BARE_TYPE_IGNORE_SITES))
def test_ledger_files_exist(rel: str, _ln: int) -> None:
    assert (_REPO_ROOT / rel).is_file(), f"Ledger references missing file: {rel}"


def test_prod_py_inventory_sane() -> None:
    assert len(_iter_prod_py()) >= 50
