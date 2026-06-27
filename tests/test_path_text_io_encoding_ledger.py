"""Defense pin: frozen ledger of ``Path.read_text(...) / Path.write_text(...)``
call sites that omit an explicit ``encoding=`` keyword.

Rationale
---------
Without an explicit ``encoding=``, ``pathlib.Path.read_text`` and
``Path.write_text`` rely on ``locale.getpreferredencoding(False)``, which
varies by platform (UTF-8 on Linux/macOS, cp1252 on Windows containers,
ASCII on stripped-down CI runners). This has caused production bugs where
the same JSON / Pine / TXT artifact decoded fine locally but corrupted on
deployment.

This pin freezes today's surface so the ledger can only **shrink**:

* No new ``read_text/write_text`` call without ``encoding=`` may appear in
  new code or be added to a frozen file.
* No frozen file may grow more sites without bumping ``_FROZEN_TOTAL``.
* If a file removes all of its sites, the parametrized line-drift test still
  guards the remaining ones.

Sister of the silent-error-swallow ledger (#213). All sites are
non-test, first-party, and currently passing because the offending behavior
hasn't manifested — but a future encoding mismatch is a one-line bug-fix
away from being a P1 incident.
"""
from __future__ import annotations

import ast
import functools
from pathlib import Path

import pytest

from tests._guard_corpus import parse_module

_ROOT = Path(__file__).resolve().parents[1]

_DIR_EXCLUDE = {
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
    "tests",
    "SMC++",
}

# Frozen ledger — rebaselined 2026-05-02 (was 2026-04-25 surface).
# Drift since last baseline:
#   - scripts/run_smc_e2e_smoke_test.py: 3 sites shifted by +3 lines
#     (53 → 56, 97 → 100, 133 → 136) due to header edits; count unchanged.
#   - scripts/phase5_perf_trend.py: FIXED (encoding="utf-8" added, line 163);
#     entry removed from _FROZEN_SITES.
_FROZEN_SITES: dict[str, frozenset[int]] = {
    # 2026-06-28 (semantic monitoring): shifted +20 lines by readiness metrics.
    "open_prep/realtime_signals.py": frozenset({200}),
    "pine_apply_surface_reduction.py": frozenset({53, 87, 397, 471, 502, 555}),
    "pine_input_surface.py": frozenset({129, 156, 187, 260, 270, 344}),
    "scripts/investigate_universe_delta.py": frozenset({28}),
    "streamlit_terminal.py": frozenset({1621}),
}
_FROZEN_TOTAL = sum(len(v) for v in _FROZEN_SITES.values())


def _iter_python_files() -> list[Path]:
    out: list[Path] = []
    for path in _ROOT.rglob("*.py"):
        rel_parts = path.relative_to(_ROOT).parts
        if any(part in _DIR_EXCLUDE for part in rel_parts):
            continue
        if path.name.startswith("mutation_"):
            continue
        out.append(path)
    return out


@functools.cache
def _collect_offenders() -> dict[str, set[int]]:
    offenders: dict[str, set[int]] = {}
    for path in _iter_python_files():
        tree = parse_module(path)
        if tree is None:
            continue
        rel = path.relative_to(_ROOT).as_posix()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not (isinstance(func, ast.Attribute) and func.attr in ("read_text", "write_text")):
                continue
            kw_names = {kw.arg for kw in node.keywords if kw.arg}
            if "encoding" not in kw_names:
                offenders.setdefault(rel, set()).add(node.lineno)
    return offenders


def test_path_text_io_total_does_not_grow() -> None:
    offenders = _collect_offenders()
    total = sum(len(v) for v in offenders.values())
    assert total == _FROZEN_TOTAL, (
        f"Path.read_text/write_text without encoding= total drifted: "
        f"frozen={_FROZEN_TOTAL}, observed={total}. "
        "Either fix new sites or, if intentional, update _FROZEN_SITES + _FROZEN_TOTAL."
    )


def test_no_new_files_join_the_ledger() -> None:
    offenders = _collect_offenders()
    new_files = sorted(set(offenders) - set(_FROZEN_SITES))
    assert not new_files, (
        "New files joined the Path text-IO encoding= ledger. Add encoding= or "
        f"update _FROZEN_SITES if intentional. New: {new_files}"
    )


def test_no_files_disappeared_unfixed() -> None:
    offenders = _collect_offenders()
    # If a file is in _FROZEN_SITES but not in offenders, that's *good* (fully fixed).
    # We only require: no file in offenders that's not in _FROZEN_SITES, which is
    # covered by test_no_new_files_join_the_ledger. Nothing extra to assert here,
    # but keep the placeholder so the ledger structure is symmetrical with #213.
    assert set(offenders).issubset(_FROZEN_SITES) or not offenders


@pytest.mark.parametrize(
    "rel,frozen_lines",
    sorted(_FROZEN_SITES.items()),
    ids=lambda v: v if isinstance(v, str) else "lines",
)
def test_per_file_lines_match(rel: str, frozen_lines: frozenset[int]) -> None:
    offenders = _collect_offenders()
    observed = offenders.get(rel, set())
    extra = observed - frozen_lines
    assert not extra, (
        f"{rel}: new Path text-IO call without encoding= at lines {sorted(extra)}. "
        f"Frozen lines were {sorted(frozen_lines)}. Add encoding= or update the ledger."
    )
