"""Pin: ad-hoc ``httpx.Client(...)`` instantiation budget for the active
NewsAPI ingestion path.

``scripts/smc_newsapi_ai.py`` exposes 4 public fetch functions, each of
which accepts an injectable ``client: httpx.Client | None = None`` and
falls back to a locally-constructed client when the caller passes
``None``. The fallback pattern is::

    own_client = client is None
    if client is None:
        client = httpx.Client(timeout=HTTPX_REQUEST_TIMEOUT_SECONDS)
    try:
        ...
    finally:
        if own_client:
            client.close()

Because each fallback opens a fresh connection pool, the count of these
construction sites is a connection-pool-leak risk surface. Adding a 5th
fallback without justification almost always means: a new public fetch
function was added without first refactoring to a shared client helper.

This pin freezes:

1. The total count of ``httpx.Client(...)`` instantiations in the file
   (currently 4 — one per public fetch).
2. Every instantiation must be guarded by ``if client is None:`` (the
   established fallback pattern). A bare top-level ``httpx.Client(...)``
   would create a module-load-time pool, which is a known anti-pattern
   for ingestion modules that may be imported by short-lived CLIs.

Companion pin: when adding a new public fetch, prefer extracting a
shared ``_get_or_create_client(client)`` helper instead of bumping the
budget here.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TARGET_FILE = REPO_ROOT / "scripts" / "smc_newsapi_ai.py"

# Frozen budget: 4 fallback client constructions, one per public fetch.
_EXPECTED_CLIENT_INSTANTIATIONS: int = 4

_CLIENT_CTOR_RE = re.compile(r"\bhttpx\.Client\s*\(")
_GUARD_RE = re.compile(r"if\s+client\s+is\s+None\s*:")


def _read_target_lines() -> list[str]:
    return TARGET_FILE.read_text(encoding="utf-8").splitlines()


def test_target_file_exists() -> None:
    assert TARGET_FILE.is_file(), f"Expected {TARGET_FILE} to exist."


def test_httpx_client_instantiation_count_is_frozen() -> None:
    lines = _read_target_lines()
    hits = [
        (i + 1, line)
        for i, line in enumerate(lines)
        if _CLIENT_CTOR_RE.search(line)
    ]
    assert len(hits) == _EXPECTED_CLIENT_INSTANTIATIONS, (
        f"httpx.Client(...) instantiation count drifted: "
        f"observed={len(hits)} expected={_EXPECTED_CLIENT_INSTANTIATIONS}. "
        f"Each fallback opens a fresh connection pool. Before bumping "
        f"this budget, refactor to a shared _get_or_create_client(client) "
        f"helper. Hits:\n"
        + "\n".join(f"  L{ln}: {txt.strip()}" for ln, txt in hits)
    )


def test_every_httpx_client_instantiation_is_guarded() -> None:
    """Every ``httpx.Client(...)`` call must be preceded (within 3 lines)
    by an ``if client is None:`` guard, ensuring the construction is a
    fallback rather than a module-load-time pool."""
    lines = _read_target_lines()
    unguarded: list[tuple[int, str]] = []
    for i, line in enumerate(lines):
        if not _CLIENT_CTOR_RE.search(line):
            continue
        # Look back up to 3 lines for the guard.
        window = lines[max(0, i - 3) : i]
        if not any(_GUARD_RE.search(prev) for prev in window):
            unguarded.append((i + 1, line))
    assert not unguarded, (
        "Unguarded httpx.Client(...) instantiation(s) found "
        "(no `if client is None:` within 3 preceding lines):\n"
        + "\n".join(f"  L{ln}: {txt.strip()}" for ln, txt in unguarded)
        + "\nWrap each construction in the established fallback pattern."
    )
