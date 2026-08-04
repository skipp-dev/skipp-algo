"""Pin: discipline rules for tracked requirements surfaces.

Three layers of defense against supply-chain regressions:

1. **Exact pins required.** Every non-comment, non-empty line is
    exact-pinned with ``==`` so a fresh ``pip install`` cannot silently
    pull in a brand-new (potentially compromised) release.

2. **No third-party index URLs.** Lines starting with ``--index-url`` or
   ``--extra-index-url`` would let pip resolve packages from outside
   PyPI — a known dependency-confusion vector. Today: 0 such lines.

3. **Line-count budgets.** Each tracked requirements surface has a frozen
    dep-line budget. New dependencies must update the relevant budget
    consciously, surfacing supply-chain surface growth in code review.

Companion lockfiles (for the surfaces that use them) carry
``--generate-hashes`` SHA-256 fingerprints. ``requirements.txt`` itself
remains the human-edited exact-pin source of truth for the root runtime
set.

OWASP A06 (Vulnerable & Outdated Components) +
OWASP A08 (Software & Data Integrity Failures).
"""
from __future__ import annotations

from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
_REQUIREMENT_FILES = {
    "requirements.txt": _REPO_ROOT / "requirements.txt",
    "requirements-gpu.txt": _REPO_ROOT / "requirements-gpu.txt",
}

# Frozen budgets — bump consciously when adding deps. Unit: dep-lines per file.
# 2026-05-12 (F-V8-Q5b, PR #2148): bumped 23 -> 24 to add psutil>=5.9.0
# for the per-sheet RSS/USS memory-snapshot diagnostic in
# scripts/databento_production_workbook.py::_memory_snapshot.
# 2026-06-07: bumped 25 -> 26 to add pytest-split>=0.11.0 for the
# duration-balanced 4-shard sharding of the `validate` CI job.
# 2026-07-01: bumped 27 -> 28 to include the pyyaml exact pin used by
# workflow/dependency-discipline tooling.
_DEP_LINE_BUDGETS = {
    # 2026-07-03: 28 → 29 for hypothesis==6.112.2 (property-based test lib,
    # exact-pinned) already present on main; budget bump was missing.
    # 2026-07-20: 29 → 30 for cisco-aidefense-sdk==2.1.2, the official
    # fail-closed request/response inspection boundary for LLM egress.
    # 2026-08-04: 30 → 31 for starlette==1.3.1. Previously unpinned and
    # floating to 1.x transitively via fastapi; pinned at the version
    # fast-gates and the deployed daemon already resolve to (confirmed
    # behaviour-neutral: 170 tests pass identically under both versions).
    "requirements.txt": 31,
    "requirements-gpu.txt": 1,
}


def _dep_lines(path: Path) -> list[tuple[int, str]]:
    """Return ``(1-based-line-number, content)`` for every dep line.

    A dep line is a non-empty, non-comment line that does not start
    with a pip option flag (``--index-url`` etc).
    """
    out: list[tuple[int, str]] = []
    for i, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith("--"):
            continue
        out.append((i, line))
    return out


def _option_lines(path: Path) -> list[tuple[int, str]]:
    """Return ``(1-based-line-number, content)`` for every pip-option line."""
    out: list[tuple[int, str]] = []
    for i, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if line.startswith("--"):
            out.append((i, line))
    return out


def _dep_cases() -> list[tuple[str, int, str]]:
    return [
        (name, lineno, line)
        for name, path in sorted(_REQUIREMENT_FILES.items())
        for lineno, line in _dep_lines(path)
    ]


@pytest.mark.parametrize(("name", "path"), sorted(_REQUIREMENT_FILES.items()))
def test_requirements_file_exists(name: str, path: Path) -> None:
    assert path.is_file(), f"missing {name}: {path}"


def _version_specifier(line: str) -> str:
    """Return the requirement's own version specifier, stripped of noise.

    A dep line may legitimately carry an inline comment and a PEP 508
    environment marker::

        cupy-cuda12x==14.0.0 ; platform_system == "Linux"   # GPU extra

    Both can contain ``==`` while saying nothing about the pin, so they are
    removed BEFORE the specifier is inspected (2026-07-15): the previous check
    was ``assert "==" in line``, a bare substring test that either of them
    satisfied while the package version floated freely.
    """
    body = line.split("#", 1)[0]  # inline comment
    body = body.split(";", 1)[0]  # PEP 508 environment marker
    return body.strip()


@pytest.mark.parametrize(("name", "lineno", "line"), _dep_cases())
def test_every_dep_has_version_specifier(name: str, lineno: int, line: str) -> None:
    """Every dep line must be exact-pinned with ``==`` on the package itself.

    A bare ``requests`` line — or even a floating lower bound like
    ``requests>=X.Y`` — would let a fresh install drift to a newly
    published release. For tracked requirements surfaces we freeze exact
    versions in source control.

    The check reads the requirement's OWN specifier. ``"==" in line`` was not
    that test: it passed on ``hypothesis>=6.112.2 ; python_version=="3.12"``,
    where the ``==`` belongs to the environment marker while ``hypothesis``
    floats to whatever PyPI serves at install time — precisely the drive-by
    supply-chain drift this pin's header says it exists to prevent. Verified:
    that line passed all 36 cases before this change.
    """
    spec = _version_specifier(line)
    assert "==" in spec, (
        f"{name} line {lineno} is not exact-pinned: {line!r}. "
        f"The requirement's own specifier is {spec!r} — a '==' in an inline "
        "comment or a PEP 508 environment marker does not pin the package. "
        "Use 'pkg==X.Y.Z' for deterministic root installs."
    )


@pytest.mark.parametrize(("name", "path"), sorted(_REQUIREMENT_FILES.items()))
def test_no_third_party_index_urls(name: str, path: Path) -> None:
    """No ``--index-url`` / ``--extra-index-url`` lines allowed.

    Third-party indexes are a dependency-confusion vector. PyPI is
    the only allowed source.
    """
    forbidden = ("--index-url", "--extra-index-url")
    offenders = [
        (n, line) for n, line in _option_lines(path)
        if any(line.startswith(f) for f in forbidden)
    ]
    assert offenders == [], (
        f"{name} must not declare third-party package indexes. "
        f"Offenders: {offenders}"
    )


@pytest.mark.parametrize(("name", "path"), sorted(_REQUIREMENT_FILES.items()))
def test_dep_line_count_budget(name: str, path: Path) -> None:
    """Frozen total dep-line count.

    Bumping this number requires conscious approval — surfaces
    supply-chain surface growth in code review.
    """
    actual = len(_dep_lines(path))
    expected = _DEP_LINE_BUDGETS[name]
    assert actual == expected, (
        f"{name} dep-line count drifted: expected "
        f"{expected}, got {actual}. If this is intentional, "
        f"update _DEP_LINE_BUDGETS in this test."
    )
