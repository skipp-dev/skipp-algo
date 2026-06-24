"""Defense-pin: loopback (`localhost`/`127.0.0.1`) site ledger + Dockerfile FROM form-sanity.

Two complementary defenses against silent network/runtime drift:

A. Loopback ledger
   --------------
   Every reference to ``localhost`` or ``127.0.0.1`` in first-party prod ``*.py`` is
   frozen by (file, count). New references must update this ledger via PR review
   so we cannot silently introduce a new server bound to loopback or a new
   client URL hard-coded against localhost. Equally, accidental removal trips
   the same check.

B. Dockerfile FROM form-sanity
   ---------------------------
   Single base-image discipline: every ``FROM`` line must have an explicit
   tag and must NOT use ``:latest``. The current ledger is exactly one FROM
   line (``python:3.13-slim AS base``); any addition is gated by this test.

Defense-only, no production code changes.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path

import pytest

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
        "scripts",
        "tests",
        "SMC++",
    }
)


def _iter_prod_py() -> Iterator[Path]:
    for p in ROOT.rglob("*.py"):
        if any(part in _DIR_EXCLUDE for part in p.relative_to(ROOT).parts):
            continue
        yield p


# ---------------------------------------------------------------------------
# Loopback ledger
# ---------------------------------------------------------------------------

_LOOPBACK = re.compile(r"localhost|127\.0\.0\.1", re.IGNORECASE)

# Frozen ledger: file -> number of lines containing localhost/127.0.0.1.
# Bump intentionally via PR review.
_FROZEN_LOOPBACK_COUNTS: dict[str, int] = {
    "streamlit_terminal_alerts.py": 1,
    "streamlit_terminal.py": 1,
    "open_prep/alerts.py": 1,
    "open_prep/realtime_signals.py": 1,
    "newsstack_fmp/enrich.py": 1,
}
_FROZEN_LOOPBACK_TOTAL = sum(_FROZEN_LOOPBACK_COUNTS.values())


def _scan_loopback() -> dict[str, int]:
    counts: dict[str, int] = {}
    for p in _iter_prod_py():
        try:
            src = p.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        n = 0
        for line in src.splitlines():
            if _LOOPBACK.search(line):
                n += 1
        if n:
            # POSIX form keeps the key stable across OSes (#2244).
            counts[p.relative_to(ROOT).as_posix()] = n
    return counts


def test_prod_inventory_sane() -> None:
    files = list(_iter_prod_py())
    assert len(files) >= 30, f"prod py inventory shrank: {len(files)}"


def test_loopback_total_budget_frozen() -> None:
    counts = _scan_loopback()
    total = sum(counts.values())
    assert total == _FROZEN_LOOPBACK_TOTAL, (
        f"Loopback total drifted: expected {_FROZEN_LOOPBACK_TOTAL}, got {total}; "
        f"per-file = {counts}"
    )


def test_loopback_per_file_ledger_no_new_files() -> None:
    counts = _scan_loopback()
    new_files = sorted(set(counts) - set(_FROZEN_LOOPBACK_COUNTS))
    assert not new_files, (
        "New prod files reference localhost/127.0.0.1 — review and append to "
        f"_FROZEN_LOOPBACK_COUNTS: {new_files}"
    )


def test_loopback_per_file_ledger_no_stale_entries() -> None:
    counts = _scan_loopback()
    stale = sorted(set(_FROZEN_LOOPBACK_COUNTS) - set(counts))
    assert not stale, (
        "Frozen ledger lists files with no remaining loopback hits — remove "
        f"from _FROZEN_LOOPBACK_COUNTS: {stale}"
    )


@pytest.mark.parametrize("rel,expected", sorted(_FROZEN_LOOPBACK_COUNTS.items()))
def test_loopback_per_file_count_exact(rel: str, expected: int) -> None:
    counts = _scan_loopback()
    actual = counts.get(rel, 0)
    assert actual == expected, (
        f"{rel}: loopback hits drifted (expected {expected}, got {actual}). "
        "Review the diff and update the ledger if intentional."
    )


@pytest.mark.parametrize("rel", sorted(_FROZEN_LOOPBACK_COUNTS))
def test_frozen_files_exist(rel: str) -> None:
    assert (ROOT / rel).is_file(), f"Ledger file missing: {rel}"


# ---------------------------------------------------------------------------
# Dockerfile FROM form-sanity
# ---------------------------------------------------------------------------

_FROM_RE = re.compile(r"^\s*FROM\s+(\S+)(?:\s+AS\s+\S+)?\s*$", re.IGNORECASE)


def _from_lines() -> list[tuple[int, str]]:
    p = ROOT / "Dockerfile"
    out: list[tuple[int, str]] = []
    if not p.is_file():
        return out
    for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), start=1):
        stripped = line.strip()
        if stripped.lower().startswith("from "):
            out.append((i, line.rstrip()))
    return out


def test_dockerfile_exists() -> None:
    assert (ROOT / "Dockerfile").is_file(), "Dockerfile missing"


def test_dockerfile_from_count_frozen() -> None:
    lines = _from_lines()
    assert len(lines) == 1, (
        f"Dockerfile FROM count drifted (expected 1, got {len(lines)}): {lines}. "
        "Multi-stage builds need an explicit ledger bump."
    )


def test_dockerfile_from_has_explicit_tag() -> None:
    for lineno, raw in _from_lines():
        m = _FROM_RE.match(raw)
        assert m, f"Dockerfile L{lineno}: malformed FROM line: {raw!r}"
        ref = m.group(1)
        # Reject scratch only if it sneaks in unannounced.
        if ref == "scratch":
            continue
        # Must contain ':' (tag) or '@sha256:' (digest).
        assert ":" in ref, (
            f"Dockerfile L{lineno}: base image {ref!r} lacks explicit tag or digest. "
            "Pin a tag like python:3.13-slim or a sha256 digest."
        )


def test_dockerfile_from_not_latest() -> None:
    for lineno, raw in _from_lines():
        m = _FROM_RE.match(raw)
        assert m, f"Dockerfile L{lineno}: malformed FROM line: {raw!r}"
        ref = m.group(1)
        # Reject :latest tag (silent drift on rebuild).
        assert not ref.endswith(":latest"), (
            f"Dockerfile L{lineno}: base image {ref!r} uses :latest. "
            "Pin a concrete tag or sha256 digest."
        )
