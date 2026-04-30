"""Defense pin: frozen ledger of ``# noqa`` lint-suppression markers in
first-party non-test code.

Rationale
---------
``# noqa`` (with or without specific code list) silences linter findings.
Each suppression is a deliberate decision that should require justification.
Without a ledger, suppressions accumulate silently and the codebase drifts
toward unmaintained-quality regions.

Sister of #213 (silent-error-swallow ledger), #218 (Path text-IO encoding),
#220 (built-in open encoding). The ledger may only **shrink**: removing
suppressions is welcome; adding new ones requires a deliberate ledger bump
in the same PR.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

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

_NOQA_RE = re.compile(r"#\s*noqa\b", re.IGNORECASE)

# Frozen ledger — exactly today's surface (2026-04-30).
#
# The following suppressions are intentional and registered here:
#
# * ``open_prep/realtime_signals.py`` (2 sites): SIM115 false positives
#   — file descriptors are intentionally held open beyond the function
#   scope (fcntl.flock for engine startup; log fh inherited by a
#   detached subprocess via ``start_new_session=True``).
# * ``scripts/ib_client_id.py`` (2 sites): SIM115 false positives —
#   lock fds held under fcntl.flock for client-id allocation (these are
#   captured in the per-file count even though this test's
#   ``_DIR_EXCLUDE`` set does not include ``scripts``; the sister
#   ledger ``test_noqa_budget.py`` excludes ``scripts`` from its
#   inventory and so does not list these entries).
#
# All other first-party noqa suppressions remain forbidden.
_FROZEN_SITES: dict[str, int] = {
    "open_prep/realtime_signals.py": 2,
    "scripts/ib_client_id.py": 2,
}
_FROZEN_TOTAL = sum(_FROZEN_SITES.values())


def _iter_python_files() -> list[Path]:
    out: list[Path] = []
    for path in _ROOT.rglob("*.py"):
        if any(part in _DIR_EXCLUDE for part in path.relative_to(_ROOT).parts):
            continue
        out.append(path)
    return out


def _observed_counts() -> dict[str, int]:
    counts: dict[str, int] = {}
    for path in _iter_python_files():
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        n = sum(1 for line in text.splitlines() if _NOQA_RE.search(line))
        if n:
            counts[path.relative_to(_ROOT).as_posix()] = n
    return counts


def test_noqa_total_does_not_grow() -> None:
    observed = _observed_counts()
    total = sum(observed.values())
    assert total <= _FROZEN_TOTAL, (
        f"Total `# noqa` suppressions grew: frozen={_FROZEN_TOTAL}, "
        f"observed={total}. Justify and update _FROZEN_SITES + _FROZEN_TOTAL "
        "in the same PR, or remove the suppression."
    )


def test_no_new_noqa_files() -> None:
    observed = _observed_counts()
    new_files = sorted(set(observed) - set(_FROZEN_SITES))
    assert not new_files, (
        "New file(s) introduced `# noqa` suppressions. Either fix the "
        f"underlying lint warning or update _FROZEN_SITES. New: {new_files}"
    )


@pytest.mark.parametrize("rel,expected", sorted(_FROZEN_SITES.items()))
def test_per_file_noqa_count_does_not_grow(rel: str, expected: int) -> None:
    observed = _observed_counts()
    actual = observed.get(rel, 0)
    assert actual <= expected, (
        f"{rel}: `# noqa` suppression count grew from {expected} to {actual}. "
        "Either fix the lint warning or bump _FROZEN_SITES in the same PR."
    )
