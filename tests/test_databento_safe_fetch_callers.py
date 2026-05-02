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

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# Files that are allowed to call .timeseries.get_range() directly.
# Both define the retry-wrapped helper; everything else must call through them.
ALLOWED_DIRECT_CALLERS: frozenset[str] = frozenset({
    "databento_client.py",                # canonical helper definition
    "databento_volatility_screener.py",   # parallel helper (consolidation follow-up)
})


def _iter_top_level_python_files() -> list[Path]:
    """Top-level production *.py files only.

    Top-level test_*.py modules (e.g. ``test_compile.py``, ``test_usi_lint.py``)
    are excluded — they belong to the test tree even though they sit at the
    repo root for legacy reasons. The dedicated ``tests/`` directory is
    excluded by the glob (non-recursive)."""
    return sorted(
        p for p in REPO_ROOT.glob("*.py") if not p.name.startswith("test_")
    )


def _direct_get_range_call_lines(source: str, filename: str) -> list[int]:
    """Return line numbers of every ``<expr>.timeseries.get_range(...)`` call.

    Uses ast.parse so commented-out lines, string literals containing the
    pattern, and assignments like ``x = ".timeseries.get_range("`` do not
    produce false positives the way a textual regex would.
    """
    try:
        tree = ast.parse(source, filename=filename)
    except SyntaxError as exc:
        # Re-raise with filename context so the guard can never be silently
        # bypassed by an unparseable production file. Returning an empty
        # list here would let unwrapped get_range() callers slip through
        # whenever a syntax error existed elsewhere in the same module.
        raise AssertionError(
            f"Cannot AST-parse {filename} for direct-get_range scan; "
            f"fix the syntax error before re-running this guard. "
            f"Original error: {exc}"
        ) from exc

    hits: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        # Match `<anything>.timeseries.get_range(...)`.
        if (
            isinstance(func, ast.Attribute)
            and func.attr == "get_range"
            and isinstance(func.value, ast.Attribute)
            and func.value.attr == "timeseries"
        ):
            hits.append(getattr(node, "lineno", 0))
    return hits


def test_no_unwrapped_direct_databento_get_range_callers() -> None:
    """Every top-level ``.timeseries.get_range(`` call must be allow-listed."""
    offenders: list[str] = []
    for py in _iter_top_level_python_files():
        if py.name in ALLOWED_DIRECT_CALLERS:
            continue
        source = py.read_text(encoding="utf-8", errors="replace")
        for lineno in _direct_get_range_call_lines(source, py.name):
            offenders.append(f"{py.name}:{lineno}")
    assert not offenders, (
        "F-V4-E1: direct `.timeseries.get_range(` calls outside the allow-list "
        f"({sorted(ALLOWED_DIRECT_CALLERS)}). Route through "
        "`databento_client._databento_get_range_with_retry` for retry on "
        "transient TLS / RemoteDisconnected / 5xx errors:\n  "
        + "\n  ".join(offenders)
    )
