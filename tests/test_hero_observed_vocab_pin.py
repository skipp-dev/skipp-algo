"""Observed-vocabulary pin for ``HERO_BIAS`` and ``HERO_MARKET_MODE``.

Phase-6 / Bug-Class #17 (``HERO_MARKET_MODE`` UNKNOWN marker) and #20
(``HERO_TRUST`` / ``HERO_MARKET_TRUST`` overlap) from
``smc-system-review-2026-04-24.md``.

``scripts/smc_hero_state.py`` declares formal ``frozenset`` vocabularies
for ``HERO_TRUST``, ``HERO_SETUP_QUALITY`` and ``HERO_ACTION``. The two
remaining hero channels — ``HERO_BIAS`` and ``HERO_MARKET_MODE`` — are
documented in the module docstring (lines 8-9) but have **no formal
constant**. The bias derivation (``_derive_bias``) emits values from
``{"LONG", "SHORT", "FLAT"}`` and ``DEFAULTS["HERO_MARKET_MODE"] ==
"NEUTRAL"`` with the docstring listing ``BULLISH / BEARISH / NEUTRAL /
RISK_OFF``.

This module pins those **observed** value sets without modifying the
source (audit-only, additive). When ``smc_hero_state`` introduces a new
bias or market-mode value, this test fails and forces an explicit
update of either the formal vocab or this whitelist.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
_HERO_STATE_PATH = REPO_ROOT / "scripts" / "smc_hero_state.py"

# Pinned observed values.
_OBSERVED_BIAS_VALUES: frozenset[str] = frozenset({"LONG", "SHORT", "FLAT"})

# From module docstring (lines 8-9) and DEFAULTS:
_OBSERVED_MARKET_MODE_VALUES: frozenset[str] = frozenset({
    "BULLISH",
    "BEARISH",
    "NEUTRAL",
    "RISK_OFF",
})

# Helper-function names we walk for string-literal returns.
_BIAS_DERIVE_FN = "_derive_bias"


def _string_literal_returns(source: str, fn_name: str) -> set[str]:
    """Collect every string ``return`` literal inside ``fn_name``."""
    tree = ast.parse(source)
    out: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef) or node.name != fn_name:
            continue
        for sub in ast.walk(node):
            if isinstance(sub, ast.Return) and isinstance(sub.value, ast.Constant):
                if isinstance(sub.value.value, str):
                    out.add(sub.value.value)
    return out


def test_hero_bias_observed_values_match_pin() -> None:
    """Pin: ``_derive_bias`` emits exactly the documented bias vocabulary."""
    source = _HERO_STATE_PATH.read_text(encoding="utf-8")
    observed = _string_literal_returns(source, _BIAS_DERIVE_FN)
    assert observed, (
        f"Could not extract any string-literal returns from "
        f"{_BIAS_DERIVE_FN}() — file structure changed?"
    )
    assert observed == _OBSERVED_BIAS_VALUES, (
        f"HERO_BIAS observed-vocabulary drift in {_HERO_STATE_PATH.name}::"
        f"{_BIAS_DERIVE_FN}: returns={sorted(observed)}, "
        f"pinned={sorted(_OBSERVED_BIAS_VALUES)}.\n\n"
        "Either: (a) update the pin (and document via CHANGELOG with a "
        "schema-version bump if HERO_BIAS feeds a downstream Pine bus); "
        "or (b) introduce a formal HERO_BIAS_VOCAB frozenset alongside "
        "HERO_TRUST_VOCAB / HERO_SETUP_QUALITY_VOCAB / HERO_ACTION_VOCAB."
    )


def test_hero_market_mode_default_in_observed_set() -> None:
    """Pin: ``DEFAULTS['HERO_MARKET_MODE']`` is one of the observed values."""
    from scripts.smc_hero_state import DEFAULTS

    default_value = DEFAULTS["HERO_MARKET_MODE"]
    assert default_value in _OBSERVED_MARKET_MODE_VALUES, (
        f"DEFAULTS['HERO_MARKET_MODE']={default_value!r} not in pinned "
        f"observed set {sorted(_OBSERVED_MARKET_MODE_VALUES)}. Either "
        "the default drifted (update DEFAULTS or this pin) or the "
        "observed set is stale."
    )


def test_hero_market_mode_docstring_lists_observed_values() -> None:
    """Pin: the module docstring still enumerates the observed values.

    The line ``HERO_MARKET_MODE   : str   — e.g. "BULLISH", "BEARISH",
    "NEUTRAL", "RISK_OFF"`` is the closest thing to a formal vocab
    declaration. If it disappears or drifts, downstream consumers
    (Pine TV, Streamlit dashboards) lose the only contract anchor.
    """
    text = _HERO_STATE_PATH.read_text(encoding="utf-8")
    docstring_match = re.search(
        r'HERO_MARKET_MODE\s*:\s*str\s*\u2014\s*e\.g\.\s*("[^"]+"(?:\s*,\s*"[^"]+")*)',
        text,
    )
    assert docstring_match, (
        "HERO_MARKET_MODE docstring contract line missing or reformatted "
        "in scripts/smc_hero_state.py. The current pin relies on this "
        "line being the single source of truth for the value vocabulary."
    )
    quoted = re.findall(r'"([^"]+)"', docstring_match.group(1))
    documented = set(quoted)
    assert documented == _OBSERVED_MARKET_MODE_VALUES, (
        f"HERO_MARKET_MODE docstring lists {sorted(documented)}, pin "
        f"expected {sorted(_OBSERVED_MARKET_MODE_VALUES)}. Update one "
        "to match the other (and bump SCHEMA_VERSION if values changed)."
    )


def test_hero_module_still_lacks_formal_market_mode_and_bias_vocab() -> None:
    """Investigate-marker: this test PASSES today and documents the
    audit gap. When a future PR introduces ``HERO_BIAS_VOCAB`` and/or
    ``HERO_MARKET_MODE_VOCAB``, this assertion will fail and the PR
    author should: (a) delete this test, and (b) replace
    ``test_hero_bias_observed_values_match_pin`` with a strict
    ``set(_derive_bias literals) == HERO_BIAS_VOCAB`` test.
    """
    text = _HERO_STATE_PATH.read_text(encoding="utf-8")
    has_bias_vocab = "HERO_BIAS_VOCAB" in text
    has_market_mode_vocab = "HERO_MARKET_MODE_VOCAB" in text
    assert not has_bias_vocab and not has_market_mode_vocab, (
        "scripts/smc_hero_state.py now declares HERO_BIAS_VOCAB and/or "
        "HERO_MARKET_MODE_VOCAB. Migrate this test to a strict "
        "frozenset-equality pin and remove this guard. See the docstring "
        "of this test for the migration recipe."
    )
