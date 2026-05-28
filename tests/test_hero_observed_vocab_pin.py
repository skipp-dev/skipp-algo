"""Strict-vocabulary pin for ``HERO_BIAS`` and ``HERO_MARKET_MODE``.

History
=======

Previous incarnation (PR #123) was an *observed*-values pin because
``scripts/smc_hero_state.py`` had no formal frozenset for these two
hero channels. ADR-0006 (PR-AUDIT-2026-04-24) introduced
``HERO_BIAS_VOCAB`` and ``HERO_MARKET_MODE_VOCAB`` alongside the
pre-existing ``HERO_TRUST_VOCAB`` / ``HERO_SETUP_QUALITY_VOCAB`` /
``HERO_ACTION_VOCAB``.

This module now does **strict** vocab pinning: every string literal
that ``_derive_bias`` returns must appear in ``HERO_BIAS_VOCAB`` (and
vice versa); ``DEFAULTS["HERO_MARKET_MODE"]`` must appear in
``HERO_MARKET_MODE_VOCAB``; the docstring contract line must enumerate
exactly ``HERO_MARKET_MODE_VOCAB``; the formal vocabs themselves must
not silently drift.

Companion: ``tests/test_pine_library_version_consistency.py`` and
``docs/adr/0006-hero-vocab-discipline.md``.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
_HERO_STATE_PATH = REPO_ROOT / "scripts" / "smc_hero_state.py"

# Source-of-truth pin. Drift here = breaking change requiring CHANGELOG
# entry + library_field_version bump in smc_micro_profiles_generated.pine.
# Issue #55 — "UNKNOWN" sentinels added as waiting-state markers (v6.0a bump).
# The sentinels are emitted only by DEFAULTS[]; the derive functions never
# return them, so the derive-symmetric test pins the "active" subset.
_EXPECTED_BIAS_ACTIVE_VOCAB: frozenset[str] = frozenset({"LONG", "SHORT", "FLAT"})
_EXPECTED_BIAS_VOCAB: frozenset[str] = _EXPECTED_BIAS_ACTIVE_VOCAB | {"UNKNOWN"}
_EXPECTED_MARKET_MODE_VOCAB: frozenset[str] = frozenset({
    "BULLISH",
    "BEARISH",
    "NEUTRAL",
    "RISK_OFF",
    "UNKNOWN",
})

_BIAS_DERIVE_FN = "_derive_bias"


def _resolve_constant_returns(source: str, fn_name: str) -> set[str]:
    """Collect every ``return`` value inside ``fn_name``, resolving names.

    Handles two forms:
    * ``return "FLAT"`` — direct string literal.
    * ``return HERO_BIAS_FLAT`` — module-level string constant; resolved
      via a single-pass scan of top-level ``Name = "literal"`` assigns.
    """
    tree = ast.parse(source)
    name_to_value: dict[str, str] = {}
    for node in tree.body:
        if (
            isinstance(node, ast.Assign)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        ):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name):
                    name_to_value[tgt.id] = node.value.value
        elif (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        ):
            name_to_value[node.target.id] = node.value.value

    out: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef) or node.name != fn_name:
            continue
        for sub in ast.walk(node):
            if not isinstance(sub, ast.Return):
                continue
            val = sub.value
            if isinstance(val, ast.Constant) and isinstance(val.value, str):
                out.add(val.value)
            elif isinstance(val, ast.Name) and val.id in name_to_value:
                out.add(name_to_value[val.id])
    return out


def _load_vocab(name: str) -> frozenset[str]:
    """Load a module-level ``frozenset[str]`` constant from smc_hero_state."""
    import importlib

    module = importlib.import_module("scripts.smc_hero_state")
    value = getattr(module, name)
    assert isinstance(value, frozenset), f"{name} is not a frozenset"
    return value


def test_hero_bias_vocab_exists_and_matches_pin() -> None:
    """``HERO_BIAS_VOCAB`` must exist as a frozenset and equal the pin."""
    vocab = _load_vocab("HERO_BIAS_VOCAB")
    assert vocab == _EXPECTED_BIAS_VOCAB, (
        f"HERO_BIAS_VOCAB drift: actual={sorted(vocab)} "
        f"expected={sorted(_EXPECTED_BIAS_VOCAB)}. Either: (a) update the "
        "pin AND bump library_field_version in smc_micro_profiles_generated; "
        "or (b) revert the source change."
    )


def test_hero_market_mode_vocab_exists_and_matches_pin() -> None:
    """``HERO_MARKET_MODE_VOCAB`` must exist as a frozenset and equal the pin."""
    vocab = _load_vocab("HERO_MARKET_MODE_VOCAB")
    assert vocab == _EXPECTED_MARKET_MODE_VOCAB, (
        f"HERO_MARKET_MODE_VOCAB drift: actual={sorted(vocab)} "
        f"expected={sorted(_EXPECTED_MARKET_MODE_VOCAB)}. Same migration "
        "recipe as HERO_BIAS_VOCAB."
    )


def test_derive_bias_returns_only_vocab_members() -> None:
    """Every literal/constant ``_derive_bias`` returns must be in the vocab."""
    source = _HERO_STATE_PATH.read_text(encoding="utf-8")
    observed = _resolve_constant_returns(source, _BIAS_DERIVE_FN)
    assert observed, (
        f"Could not extract any return values from {_BIAS_DERIVE_FN}() — "
        "file structure changed?"
    )
    extra = observed - _EXPECTED_BIAS_ACTIVE_VOCAB
    missing = _EXPECTED_BIAS_ACTIVE_VOCAB - observed
    assert not extra, (
        f"{_BIAS_DERIVE_FN} returns NEW values outside the active bias "
        f"vocab: {sorted(extra)}. Add them to HERO_BIAS_VOCAB (with "
        "CHANGELOG + library_field_version bump) or remove from the function."
    )
    assert not missing, (
        f"Active bias vocab pins {sorted(missing)} that {_BIAS_DERIVE_FN} "
        "no longer emits. Either restore the branch or shrink the vocab."
    )


def test_hero_market_mode_default_is_in_vocab() -> None:
    """``DEFAULTS['HERO_MARKET_MODE']`` must be a member of the vocab."""
    from scripts.smc_hero_state import DEFAULTS, HERO_MARKET_MODE_VOCAB

    default_value = DEFAULTS["HERO_MARKET_MODE"]
    assert default_value in HERO_MARKET_MODE_VOCAB, (
        f"DEFAULTS['HERO_MARKET_MODE']={default_value!r} not in vocab "
        f"{sorted(HERO_MARKET_MODE_VOCAB)}."
    )


def test_hero_bias_default_is_in_vocab() -> None:
    """``DEFAULTS['HERO_BIAS']`` must be a member of the vocab."""
    from scripts.smc_hero_state import DEFAULTS, HERO_BIAS_VOCAB

    default_value = DEFAULTS["HERO_BIAS"]
    assert default_value in HERO_BIAS_VOCAB, (
        f"DEFAULTS['HERO_BIAS']={default_value!r} not in vocab "
        f"{sorted(HERO_BIAS_VOCAB)}."
    )


def test_hero_market_mode_docstring_lists_vocab() -> None:
    """Module docstring must enumerate exactly ``HERO_MARKET_MODE_VOCAB``."""
    text = _HERO_STATE_PATH.read_text(encoding="utf-8")
    docstring_match = re.search(
        r'HERO_MARKET_MODE\s*:\s*str\s*\u2014\s*e\.g\.\s*("[^"]+"(?:\s*,\s*"[^"]+")*)',
        text,
    )
    assert docstring_match, (
        "HERO_MARKET_MODE docstring contract line missing or reformatted "
        "in scripts/smc_hero_state.py."
    )
    quoted = re.findall(r'"([^"]+)"', docstring_match.group(1))
    documented = set(quoted)
    assert documented == _EXPECTED_MARKET_MODE_VOCAB, (
        f"HERO_MARKET_MODE docstring lists {sorted(documented)}, vocab "
        f"is {sorted(_EXPECTED_MARKET_MODE_VOCAB)}. Sync them."
    )


def test_all_hero_vocab_constants_are_frozensets() -> None:
    """Belt-and-braces: all 5 hero vocabs are immutable frozensets."""
    import scripts.smc_hero_state as hs

    expected_vocabs = (
        "HERO_TRUST_VOCAB",
        "HERO_SETUP_QUALITY_VOCAB",
        "HERO_ACTION_VOCAB",
        "HERO_BIAS_VOCAB",
        "HERO_MARKET_MODE_VOCAB",
    )
    for name in expected_vocabs:
        value = getattr(hs, name, None)
        assert isinstance(value, frozenset), (
            f"{name} must be exposed as a frozenset (got {type(value).__name__})."
        )
        assert value, f"{name} must not be empty."
        for item in value:
            assert isinstance(item, str), f"{name} contains non-str member: {item!r}"
