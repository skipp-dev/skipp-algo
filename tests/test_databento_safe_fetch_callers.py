"""Defense ledger: every direct ``.timeseries.get_range(`` call site in
**production** code must either BE the canonical retry helper or be in
the explicit allow-list.

F-V4-E1 (2026-05-01): codifies the result of the databento safe-fetch
audit. Every other caller in the production tree must route through
``databento_client._databento_get_range_with_retry`` so transient TLS
failures, RemoteDisconnected, and 5xx errors get the bounded retry
treatment instead of poisoning a chunk that would have succeeded on a
second attempt.

Scope: top-level ``*.py`` files only (the actual production tree —
terminal_*, databento_*, streamlit_*, etc.). Excluded:
- ``tests/`` — test files mock the API and reference the regex itself.
- ``scripts/`` — research / one-shot dev tools, may legitimately call
  the SDK directly. (Two existing scripts caught: databento_preopen_fast.py,
  fvg_asia_real_sample.py — tracked as separate consolidation follow-up.)

Allow-list rationale (kept tight intentionally):
- ``databento_client.py`` — the canonical helper definition itself.
- ``databento_volatility_screener.py`` — has its OWN parallel
  ``_databento_get_range_with_retry`` definition (~L810). Tracked as
  consolidation follow-up; the call IS guarded today, just by a duplicate
  helper. Removing the duplicate is a separate refactor (different PR).

Anything else at the top level calling ``.timeseries.get_range(`` directly
fails this test. The fix is always: import
``_databento_get_range_with_retry`` from ``databento_client`` and pass
the existing kwargs plus a ``context=`` string for log attribution.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# Files that are allowed to call .timeseries.get_range() directly.
# Both define the retry-wrapped helper; everything else must call through them.
ALLOWED_DIRECT_CALLERS: frozenset[str] = frozenset({
    "databento_client.py",                # canonical helper definition
    "databento_volatility_screener.py",   # parallel helper (consolidation follow-up)
})

# Match `.timeseries.get_range(` as a method call.
_DIRECT_CALL_RE = re.compile(r"\.timeseries\.get_range\(")


def _iter_top_level_python_files() -> list[Path]:
    """Top-level *.py files only — the production tree."""
    return sorted(REPO_ROOT.glob("*.py"))


def test_no_unwrapped_direct_databento_get_range_callers() -> None:
    """Every top-level ``.timeseries.get_range(`` call must be allow-listed."""
    offenders: list[str] = []
    for py in _iter_top_level_python_files():
        if py.name in ALLOWED_DIRECT_CALLERS:
            continue
        text = py.read_text(encoding="utf-8", errors="replace")
        for lineno, line in enumerate(text.splitlines(), start=1):
            stripped = line.lstrip()
            if stripped.startswith("#"):
                continue
            if _DIRECT_CALL_RE.search(line):
                offenders.append(f"{py.name}:{lineno}")
    assert not offenders, (
        "F-V4-E1: direct `.timeseries.get_range(` calls outside the allow-list "
        f"({sorted(ALLOWED_DIRECT_CALLERS)}). Route through "
        "`databento_client._databento_get_range_with_retry` for retry on "
        "transient TLS / RemoteDisconnected / 5xx errors:\n  "
        + "\n  ".join(offenders)
    )
