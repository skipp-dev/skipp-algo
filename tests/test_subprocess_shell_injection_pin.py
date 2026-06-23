"""Defense-pin: ``subprocess.*`` call site ledger + ``shell=True`` invariant.

Pinning the surface of subprocess calls is a high-leverage defense:

* ``shell=True`` is the canonical CWE-78 (OS command injection) foot-gun.
  This repo currently has **zero** ``shell=True`` sites — that is a hard
  invariant we want to keep. ``test_no_shell_true_anywhere`` enforces it.
* New subprocess sites usually deserve review (auth surface, working dir,
  env propagation, signal handling). The per-file ledger forces an explicit
  bump when one is added.
* ``subprocess.run / Popen / check_call / check_output / call`` are pinned
  individually so swapping ``run`` → ``Popen`` (which has different
  default semantics for stdout/stderr) is also visible.

Defense-only — no production code changes.
"""

from __future__ import annotations

import ast
import functools
from collections import Counter
from pathlib import Path

import pytest

from tests._guard_corpus import iter_tracked_files, parse_module
from tests._pin_registry import subprocess_shell_sites

ROOT = Path(__file__).resolve().parent.parent

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
        "tests",
        "SMC++",
    }
)

# Methods on ``subprocess`` we treat as "spawning a process". This pins
# the API surface; a brand-new spawning method (``subprocess.foo``)
# would require an explicit allow-list bump.
_SPAWN_ATTRS = frozenset(
    {"run", "Popen", "call", "check_call", "check_output"}
)

# Per-(file, subprocess.attr) ledger of call counts in first-party
# production / scripts / streamlit code.
#
# Source of truth: pin_registry.toml (ADR-0009). Rationale per entry
# lives next to each entry in the registry.
#
# Convention on this repo today:
#   * ``run`` is the default — ``check=True`` is the recommended idiom.
#   * ``Popen`` is reserved for genuinely streaming or non-blocking flows
#     (``open_prep/realtime_signals.py`` background process,
#      ``scripts/start_open_prep_suite.py`` orchestrator).
#   * ``check_output`` only appears in ``scan_manifests_for_pytest_provenance``
#     because the script needs the captured stdout for grep-style scans.
#
# Adding/removing any site MUST update the registry in the same PR.
_FROZEN_SITES: dict[tuple[str, str], int] = subprocess_shell_sites()
_FROZEN_TOTAL = sum(_FROZEN_SITES.values())


def _iter_first_party_py_files() -> list[Path]:
    out = iter_tracked_files("*.py", _DIR_EXCLUDE, root=ROOT)
    return [path for path in out if not path.name.startswith("mutation_")]


def _is_subprocess_call(node: ast.Call) -> str | None:
    """Return the ``subprocess.<attr>`` name if the call matches, else ``None``."""
    func = node.func
    if not isinstance(func, ast.Attribute):
        return None
    if not (isinstance(func.value, ast.Name) and func.value.id == "subprocess"):
        return None
    return func.attr


def _has_shell_true(node: ast.Call) -> bool:
    for kw in node.keywords:
        if kw.arg == "shell" and isinstance(kw.value, ast.Constant) and kw.value.value is True:
            return True
    return False


def _scan_file(path: Path) -> tuple[Counter[tuple[str, str]], list[int]]:
    """Return ((site_counts, shell_true_lines)) for this file."""
    counts: Counter[tuple[str, str]] = Counter()
    shell_true_lines: list[int] = []
    tree = parse_module(path)
    if tree is None:
        return counts, shell_true_lines
    rel = path.relative_to(ROOT).as_posix()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        attr = _is_subprocess_call(node)
        if attr is None:
            continue
        counts[(rel, attr)] += 1
        if _has_shell_true(node):
            shell_true_lines.append(node.lineno)
    return counts, shell_true_lines


@functools.cache
def _observed_counts() -> dict[tuple[str, str], int]:
    out: Counter[tuple[str, str]] = Counter()
    for path in _iter_first_party_py_files():
        c, _ = _scan_file(path)
        out.update(c)
    return dict(out)


def _observed_shell_true() -> list[tuple[str, int]]:
    out: list[tuple[str, int]] = []
    for path in _iter_first_party_py_files():
        _, lines = _scan_file(path)
        rel = path.relative_to(ROOT).as_posix()
        for ln in lines:
            out.append((rel, ln))
    return sorted(out)


def test_no_shell_true_anywhere() -> None:
    """Hard invariant: no ``subprocess.X(..., shell=True)`` in first-party code (CWE-78)."""
    sites = _observed_shell_true()
    assert not sites, (
        "CWE-78 surface re-opened — subprocess(..., shell=True) sites "
        "found:\n"
        + "\n".join(f"  - {rel}:{ln}" for rel, ln in sites)
        + "\n\nUse a token list (``[arg, ...]``) instead, or wrap in "
        "``shlex.split`` only after explicit allow-list validation."
    )


def test_no_new_subprocess_attrs() -> None:
    """Refuse new ``subprocess.<attr>`` spawning methods without a ledger bump."""
    observed = _observed_counts()
    new_attrs = sorted({attr for (_, attr) in observed} - _SPAWN_ATTRS)
    assert not new_attrs, (
        "New subprocess spawning method(s) introduced — these escape the "
        "ledger contract:\n"
        + "\n".join(f"  - subprocess.{a}" for a in new_attrs)
        + "\n\nUpdate _SPAWN_ATTRS + _FROZEN_SITES with rationale."
    )


def test_no_new_subprocess_sites() -> None:
    """No new ``(file, subprocess.attr)`` site without a ledger bump."""
    observed = _observed_counts()
    new_sites = sorted(set(observed) - set(_FROZEN_SITES))
    assert not new_sites, (
        "New subprocess site(s) — process-spawn surface expanded:\n"
        + "\n".join(
            f"  - {rel} [subprocess.{attr}] count={observed[(rel, attr)]}"
            for (rel, attr) in new_sites
        )
        + "\n\nIf the site is genuinely needed, add it to _FROZEN_SITES "
        "with a justifying comment (no shell=True, token-list args)."
    )


def test_no_removed_subprocess_sites() -> None:
    """A site disappearing is great — drop it from the ledger explicitly."""
    observed = _observed_counts()
    missing = sorted(set(_FROZEN_SITES) - set(observed))
    assert not missing, (
        "Frozen subprocess site(s) no longer present — drop from "
        "_FROZEN_SITES in the same PR:\n"
        + "\n".join(f"  - {rel} [subprocess.{attr}]" for (rel, attr) in missing)
    )


@pytest.mark.parametrize(
    "rel,attr,expected",
    sorted((rel, attr, n) for (rel, attr), n in _FROZEN_SITES.items()),
)
def test_frozen_subprocess_count_still_matches(
    rel: str, attr: str, expected: int
) -> None:
    """Per-(file, subprocess.attr) count must match the ledger exactly."""
    path = ROOT / rel
    assert path.is_file(), f"frozen site missing on disk: {rel}"
    actual = _scan_file(path)[0].get((rel, attr), 0)
    assert actual == expected, (
        f"subprocess.{attr} count drifted in {rel}: "
        f"expected {expected}, got {actual}. "
        "Update _FROZEN_SITES in the same PR."
    )


def test_total_subprocess_count_pinned() -> None:
    """Aggregate cross-check against per-(file, attr) ledger drift."""
    observed = _observed_counts()
    total = sum(observed.values())
    assert total == _FROZEN_TOTAL, (
        f"subprocess call total drifted: expected {_FROZEN_TOTAL}, "
        f"got {total}. Per-site = {sorted(observed.items())}"
    )
