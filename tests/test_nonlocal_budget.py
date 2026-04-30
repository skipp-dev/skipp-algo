"""Audit pin: ``nonlocal`` keyword frozen-inventory budget.

``nonlocal`` indicates closure-mutated state — almost always a hidden
state-machine in disguise.  We freeze the current 5 known sites and
trip on (a) any new site, (b) silent name additions to an existing
``nonlocal`` declaration.
"""

from __future__ import annotations

import ast
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


def _iter_prod_files() -> list[Path]:
    out: list[Path] = []
    for path in _REPO_ROOT.rglob("*.py"):
        if any(part in _DIR_EXCLUDE for part in path.relative_to(_REPO_ROOT).parts):
            continue
        out.append(path)
    return sorted(out)


def _all_nonlocal_sites() -> list[tuple[str, int, tuple[str, ...]]]:
    sites: list[tuple[str, int, tuple[str, ...]]] = []
    for path in _iter_prod_files():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, SyntaxError):  # pragma: no cover
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Nonlocal):
                rel = path.relative_to(_REPO_ROOT).as_posix()
                sites.append((rel, node.lineno, tuple(sorted(node.names))))
    return sorted(sites)


# Frozen ``nonlocal`` sites at the time this pin landed (5 total).
# Categories:
# * ``databento_volatility_screener._fast_progress_*`` — single-callback
#   progress-bar smoothing closure inside a one-shot Streamlit run.
# * ``smc_core/ensemble_quality.py`` — weighted-aggregate accumulator
#   within an ensemble scoring helper closure.
_FROZEN_SITES: frozenset[tuple[str, int, tuple[str, ...]]] = frozenset(
    {
        ("databento_volatility_screener.py", 4682, ("_fast_progress_pct",)),
        ("databento_volatility_screener.py", 4683, ("_fast_progress_step",)),
        ("databento_volatility_screener.py", 4684, ("_fast_progress_total",)),
        ("databento_volatility_screener.py", 4685, ("_fast_eta_smooth_seconds",)),
        ("smc_core/ensemble_quality.py", 172, ("active_weight", "weighted_total")),
    }
)


def test_no_new_nonlocal_sites() -> None:
    current = set(_all_nonlocal_sites())
    new = current - _FROZEN_SITES
    assert not new, (
        "New ``nonlocal`` sites — closure-mutated state is a code-smell, "
        "prefer an explicit class or @dataclass:\n  - "
        + "\n  - ".join(f"{f}:{ln} names={names}" for f, ln, names in sorted(new))
    )


@pytest.mark.parametrize("site", sorted(_FROZEN_SITES))
def test_frozen_nonlocal_site_still_present(
    site: tuple[str, int, tuple[str, ...]],
) -> None:
    rel, lineno, names = site
    path = _REPO_ROOT / rel
    assert path.is_file(), f"{rel} no longer exists — refresh _FROZEN_SITES"
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError as exc:
        pytest.fail(f"{rel} no longer parses: {exc}")
    found = [
        (n.lineno, tuple(sorted(n.names)))
        for n in ast.walk(tree)
        if isinstance(n, ast.Nonlocal)
    ]
    assert (lineno, names) in found, (
        f"Frozen ``nonlocal`` site drifted: {rel}:{lineno} names={names}. "
        f"Current sites in file: {sorted(found)}"
    )


def test_inventory_parity() -> None:
    current = set(_all_nonlocal_sites())
    missing = _FROZEN_SITES - current
    extra = current - _FROZEN_SITES
    assert not missing and not extra, (
        f"_FROZEN_SITES out of sync. missing={sorted(missing)} extra={sorted(extra)}"
    )


def test_prod_file_inventory_sane() -> None:
    files = _iter_prod_files()
    assert len(files) >= 50, (
        f"Production *.py scan only found {len(files)} files — "
        f"_DIR_EXCLUDE may be over-broad or sparse-checkout incomplete."
    )
