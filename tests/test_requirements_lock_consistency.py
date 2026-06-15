"""Pin: ``requirements.lock`` must stay consistent with ``requirements.txt``.

History (regression this guard prevents): on 2026-06-07 (#2604) the
``validate`` CI job started failing on every PR with
``error: unrecognized arguments: --testmon``. Root cause: ``pytest-testmon``
had been added to ``requirements.txt`` but ``requirements.lock`` was never
regenerated, so when ``SMC_USE_REQUIREMENTS_LOCK=true`` the CI runner installed
from the stale lock — the plugin was simply absent and the ``--testmon`` flag
was unknown to pytest.

The pre-existing guards did **not** catch this:

* ``test_requirements_discipline_pin`` only audits requirements-file hygiene
    (version specifiers, no third-party index URLs, dep-line budgets).
* ``test_workflow_dependency_hygiene`` only audits install *ordering* inside a
  handful of workflows.

Neither ever compares the two files. This module closes that gap with two
invariants that map exactly onto the ``#2604`` failure class:

1. **Every direct dependency is pinned in the lock.** A package present in
   ``requirements.txt`` but missing from ``requirements.lock`` means a
   lock-vs-source drift — exactly what happened to ``pytest-testmon``.

2. **Every lock pin satisfies the source specifier.** If
   ``requirements.txt`` says ``pytest-testmon>=2.1.0`` the lock must pin a
   version ``>=2.1.0``. A stale lock pinning an older, floor-violating version
   would install a build the project explicitly forbids.

The check is hermetic: it parses both files offline (no ``uv``, no network),
so it works on every platform and in every CI lane. Regenerate the lock with
``python scripts/regenerate_requirements_lock.py`` (add
``--python-platform linux`` to match the CI target) whenever a dep changes.

OWASP A06 (Vulnerable & Outdated Components) +
OWASP A08 (Software & Data Integrity Failures).
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
from packaging.version import Version

_REPO_ROOT = Path(__file__).resolve().parents[1]
_REQUIREMENTS = _REPO_ROOT / "requirements.txt"
_LOCK = _REPO_ROOT / "requirements.lock"

# Top-level lock pin: ``name==version`` at column 0. Indented ``# via ...``
# provenance lines and full-line comments are intentionally ignored.
_LOCK_PIN_RE = re.compile(r"^([A-Za-z0-9._-]+)==([^\s;]+)")


def _direct_requirements() -> list[Requirement]:
    """Parse ``requirements.txt`` into packaging ``Requirement`` objects.

    Skips blank lines, comments, and pip option flags (``--index-url`` etc).
    """
    out: list[Requirement] = []
    for raw in _REQUIREMENTS.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or line.startswith("--"):
            continue
        out.append(Requirement(line))
    return out


def _lock_pins() -> dict[str, str]:
    """Return ``{canonical_name: version}`` for every top-level lock pin."""
    pins: dict[str, str] = {}
    for raw in _LOCK.read_text(encoding="utf-8").splitlines():
        match = _LOCK_PIN_RE.match(raw)
        if match:
            pins[canonicalize_name(match.group(1))] = match.group(2)
    return pins


def _pinned_direct_requirements() -> list[Requirement]:
    """Direct deps that are present in the lock (drift is covered separately).

    Parametrizing the specifier check over this subset keeps it free of
    ``pytest.skip`` — the missing-pin case is asserted by
    ``test_direct_dep_is_pinned_in_lock``.
    """
    pins = _lock_pins()
    return [
        req
        for req in _direct_requirements()
        if canonicalize_name(req.name) in pins
    ]


def test_requirements_and_lock_exist() -> None:
    assert _REQUIREMENTS.is_file(), f"missing {_REQUIREMENTS}"
    assert _LOCK.is_file(), f"missing {_LOCK}"


def test_lock_is_non_trivial() -> None:
    """The lock must resolve to far more pins than direct deps (transitives).

    Guards against an empty/truncated lock silently passing the per-dep
    checks below.
    """
    pins = _lock_pins()
    direct = _direct_requirements()
    assert len(pins) >= len(direct), (
        f"requirements.lock has only {len(pins)} pins for {len(direct)} direct "
        f"deps — transitive closure is missing. Regenerate the lock."
    )


@pytest.mark.parametrize(
    "requirement",
    _direct_requirements(),
    ids=lambda r: canonicalize_name(r.name),
)
def test_direct_dep_is_pinned_in_lock(requirement: Requirement) -> None:
    """Every direct dependency must be pinned in ``requirements.lock``.

    This is the exact ``#2604`` failure class: ``pytest-testmon`` lived in
    ``requirements.txt`` but was absent from the lock, so ``SMC_USE_
    REQUIREMENTS_LOCK=true`` installs silently dropped it and pytest rejected
    ``--testmon``.
    """
    name = canonicalize_name(requirement.name)
    pins = _lock_pins()
    assert name in pins, (
        f"'{requirement.name}' is in requirements.txt but NOT pinned in "
        f"requirements.lock (lock drift — regression of #2604). Run "
        f"'python scripts/regenerate_requirements_lock.py --python-platform "
        f"linux' and commit the updated lock."
    )


@pytest.mark.parametrize(
    "requirement",
    _pinned_direct_requirements(),
    ids=lambda r: canonicalize_name(r.name),
)
def test_lock_pin_satisfies_source_specifier(requirement: Requirement) -> None:
    """The locked version must satisfy the ``requirements.txt`` specifier.

    A stale lock pinning a version below the declared floor (e.g.
    ``pytest-testmon>=2.1.0`` but lock ``==2.0.0``) would install a build the
    project explicitly forbids. Only deps actually present in the lock are
    parametrized here; missing pins are caught by
    ``test_direct_dep_is_pinned_in_lock``.
    """
    name = canonicalize_name(requirement.name)
    locked = _lock_pins()[name]
    # ``prereleases=True`` so a locked rc/post build is still evaluated
    # against the specifier rather than being silently excluded.
    assert requirement.specifier.contains(Version(locked), prereleases=True), (
        f"requirements.lock pins {requirement.name}=={locked}, which does NOT "
        f"satisfy requirements.txt specifier '{requirement.specifier}'. "
        f"Regenerate the lock."
    )
