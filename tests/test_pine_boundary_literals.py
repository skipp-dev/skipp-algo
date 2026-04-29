"""Pine-boundary literal-pin tests (F-7, F-11).

These tests pin the *literal string values* of Python constants that
are consumed by Pine scripts via literal string comparison. The
rationale is captured in ADR 2026-04-23: a rename of the constant
(e.g. ``FRESH`` → ``OK``) is invisible to Python-only tests that use
``== TRUST_FRESH`` but silently breaks every ``== "FRESH"`` gate in
``SMC_Dashboard.pine``. We therefore maintain **two** assertions for
every cross-boundary string constant:

1. Deref-Test (in the regular unit-test file) — protects Python callers.
2. Literal-Pin-Test (this file) — protects the Pine-Boundary.

Each assertion cites the Pine file:line:literal it protects so a
reviewer seeing CI-red can find the corresponding Pine branch that
needs a simultaneous update.

Plan reference: ``BOUNDARY_CONTRACT_IMPROVEMENT_PLAN_2026-04-23.md``
§1 (F-7) and §2 (F-11).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from scripts.smc_zone_priority_consumer import (
    HR_SENTINEL_DEGRADED,
    TRUST_DEGRADED,
    TRUST_FRESH,
    TRUST_STALE,
    TRUST_UNAVAILABLE,
)

# ── ZONE_CAL_TRUST glyph gate — SMC_Dashboard.pine:1429-1434 ────────


def test_trust_fresh_pine_literal_is_ok() -> None:
    """Pin the literal value consumed by ``zone_cal_trust_glyph``.

    Source:  SMC_Dashboard.pine:1434  (``trust_state == "OK" ? "🔒"``)
    ADR:     2026-04-23 (FRESH → OK rename)

    If this test fails, update SMC_Dashboard.pine:1429-1434 in the
    same PR and bump the library_field_version.
    """
    assert TRUST_FRESH == "OK"


def test_trust_degraded_pine_literal_is_degraded() -> None:
    """Source: SMC_Dashboard.pine:1434 (``"DEGRADED" ? "⚠"``)."""
    assert TRUST_DEGRADED == "DEGRADED"


def test_trust_stale_pine_literal_is_stale() -> None:
    """TRUST_STALE is reserved for the WS2 freshness refactor and is
    not yet wired into ``zone_cal_trust_glyph``. Pin the literal so a
    rename during WS2 stays consistent with the future Pine branch.
    """
    assert TRUST_STALE == "STALE"


def test_trust_unavailable_pine_literal_is_unavailable() -> None:
    """Source: SMC_Dashboard.pine:1434 (``"UNAVAILABLE" ? "❓"``)."""
    assert TRUST_UNAVAILABLE == "UNAVAILABLE"


# ── HR sentinel — SMC_Dashboard.pine:1640-1642 (``<= 0.0`` guard) ───


def test_hr_sentinel_degraded_is_negative_one() -> None:
    """Pin the ``-1.0`` sentinel that Pine's ``<= 0.0`` guard treats
    as *no renderable value*. A drift to e.g. ``-0.5`` would still be
    caught by the guard, but a drift to ``+0.5`` would leak a fake
    high hit-rate into the Pine dashboard.

    Source: SMC_Dashboard.pine:1640 (``mp.ZONE_HR_FVG <= 0.0`` etc.)
    """
    assert HR_SENTINEL_DEGRADED == -1.0
    assert HR_SENTINEL_DEGRADED < 0.0


# ── Automated cross-check: every ``"..."`` literal in the Pine
# zone_cal_trust_glyph function must exist in the Python vocab set.


_PINE_GLYPH_FUNCTION_RE = re.compile(
    r"zone_cal_trust_glyph\s*\([^)]*\)\s*=>\s*(.+?)(?:\n\s*\n|\n//|\Z)",
    re.DOTALL,
)
_PINE_CASE_LITERAL_RE = re.compile(r'trust_state\s*==\s*"([A-Z_]+)"')


def _read_pine_dashboard() -> str:
    path = Path(__file__).resolve().parents[1] / "SMC_Dashboard.pine"
    return path.read_text(encoding="utf-8")


def test_zone_cal_trust_glyph_case_set_is_subset_of_python_vocab() -> None:
    """The set of trust-state literals in Pine's
    ``zone_cal_trust_glyph`` MUST be a subset of the Python TRUST_*
    constants. A Pine branch for a state Python never emits would
    match at most as a dead code path; a Pine *gap* for a state
    Python *does* emit is the ADR 2026-04-23 bug class.

    Note: the reverse (Python ⊆ Pine) is deliberately NOT asserted
    because ``TRUST_STALE`` is reserved ahead of its Pine wiring.
    """
    src = _read_pine_dashboard()
    m = _PINE_GLYPH_FUNCTION_RE.search(src)
    if not m:
        pytest.skip(
            "zone_cal_trust_glyph signature changed — update regex "
            "in tests/test_pine_boundary_literals.py before re-enabling."
        )
    pine_literals = set(_PINE_CASE_LITERAL_RE.findall(m.group(1)))
    python_vocab = {
        TRUST_FRESH,
        TRUST_DEGRADED,
        TRUST_STALE,
        TRUST_UNAVAILABLE,
    }
    # We expect at least the three currently-wired branches.
    assert pine_literals, (
        "Pine glyph regex matched no trust_state literals — regex "
        "likely out-of-date vs SMC_Dashboard.pine."
    )
    orphans = pine_literals - python_vocab
    assert not orphans, (
        f"Pine literals {orphans!r} have no Python producer constant. "
        f"Add the constant in scripts/smc_zone_priority_consumer.py "
        f"or remove the Pine case."
    )
