"""Strict-vocabulary pin for ``HERO_RISK`` + reachability pins for
the four HERO Producer-A vocabularies whose derive helpers we own.

Background
==========

PR #125 / ADR-0006 introduced :data:`HERO_BIAS_VOCAB` and
:data:`HERO_MARKET_MODE_VOCAB`. This module extends the discipline to
the remaining controlled-vocabulary axis:

* :data:`HERO_RISK_VOCAB` (5 values incl. the ``""`` sentinel) — pinned
  by :func:`_derive_risk`.

It also adds **reachability pins** for the **four** vocabularies whose
derive helpers we own — :data:`HERO_BIAS_VOCAB`,
:data:`HERO_RISK_VOCAB`, :data:`HERO_TRUST_VOCAB`, and
:data:`HERO_ACTION_VOCAB`: every vocab member must be returned from at
least one branch of the corresponding helper. Prevents dead vocab
entries.

The repo currently exposes **six** HERO vocabularies. The two
passthrough vocabularies (:data:`HERO_MARKET_MODE_VOCAB` and
:data:`HERO_SETUP_QUALITY_VOCAB`) are NOT subject to the reachability
pin because they pass through upstream values without a Python-side
derive function.

Why the empty string is a vocab member
======================================

``SMC_Dashboard.pine:1769`` reads::

    string _hero_blocker = mp.HERO_RISK != "" ? mp.HERO_RISK : ...

The empty string is a normative sentinel meaning *no dominant risk*.
Renaming it (e.g. to ``"NONE"``) would silently break the Pine
gating. Tests :file:`tests/test_smc_hero_state.py:100` and
:file:`tests/test_smc_pine_evidence_fixtures.py:100` document this.
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
_HERO_STATE_PATH = REPO_ROOT / "scripts" / "smc_hero_state.py"

# Source-of-truth pin for HERO_RISK_VOCAB (incl. the empty-string sentinel).
_EXPECTED_RISK_VOCAB: frozenset[str] = frozenset({
    "",  # HERO_RISK_NONE — Pine boundary contract sentinel
    "DATA_STALE",
    "EVENT_RISK",
    "VOLATILITY",
    "PROVIDER_GAPS",
})


def _resolve_returns(source: str, fn_name: str) -> set[str]:
    """Collect every literal/named-constant ``return`` in ``fn_name``."""
    tree = ast.parse(source)

    # First pass: top-level Name = "literal" assigns (handles bare and
    # AnnAssign forms).
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


def test_hero_risk_vocab_exists_and_matches_pin() -> None:
    """``HERO_RISK_VOCAB`` exists as a frozenset and equals the pin."""
    from scripts.smc_hero_state import HERO_RISK_VOCAB

    assert isinstance(HERO_RISK_VOCAB, frozenset)
    assert HERO_RISK_VOCAB == _EXPECTED_RISK_VOCAB, (
        f"HERO_RISK_VOCAB drift: actual={sorted(HERO_RISK_VOCAB)} "
        f"expected={sorted(_EXPECTED_RISK_VOCAB)}. Update the pin AND "
        "bump library_field_version (ADR-0006 §Versioning rule)."
    )


def test_hero_risk_none_sentinel_is_empty_string() -> None:
    """The Pine boundary contract: HERO_RISK_NONE must remain ``\"\"``."""
    from scripts.smc_hero_state import HERO_RISK_NONE

    assert HERO_RISK_NONE == "", (
        f"HERO_RISK_NONE drifted from \"\" to {HERO_RISK_NONE!r}. "
        "SMC_Dashboard.pine:1769 gates on `mp.HERO_RISK != \"\"`. "
        "Renaming requires a Pine-side migration."
    )


def test_derive_risk_returns_only_vocab_members() -> None:
    """Every value ``_derive_risk`` returns must be in HERO_RISK_VOCAB."""
    source = _HERO_STATE_PATH.read_text(encoding="utf-8")
    observed = _resolve_returns(source, "_derive_risk")
    extra = observed - _EXPECTED_RISK_VOCAB
    missing = _EXPECTED_RISK_VOCAB - observed
    assert not extra, (
        f"_derive_risk emits NEW values outside HERO_RISK_VOCAB: "
        f"{sorted(extra)}. Add to vocab or remove from function."
    )
    assert not missing, (
        f"HERO_RISK_VOCAB pins {sorted(missing)} that _derive_risk no "
        "longer emits. Either restore the branch or shrink the vocab."
    )


def test_derive_action_uses_named_constants_only() -> None:
    """``_derive_action`` must return only :data:`HERO_ACTION_VOCAB` values."""
    from scripts.smc_hero_state import HERO_ACTION_VOCAB

    source = _HERO_STATE_PATH.read_text(encoding="utf-8")
    observed = _resolve_returns(source, "_derive_action")
    extra = observed - HERO_ACTION_VOCAB
    missing = HERO_ACTION_VOCAB - observed
    assert not extra, (
        f"_derive_action emits values outside HERO_ACTION_VOCAB: "
        f"{sorted(extra)} (vocab: {sorted(HERO_ACTION_VOCAB)})."
    )
    # Reachability: every vocab member must appear in at least one branch.
    assert not missing, (
        f"HERO_ACTION_VOCAB pins {sorted(missing)} that _derive_action "
        "never returns. Dead vocab \u2014 either restore the branch or "
        "shrink the vocab."
    )


def test_derive_trust_reaches_every_vocab_member() -> None:
    """Reachability: every :data:`HERO_TRUST_VOCAB` member is returned somewhere."""
    from scripts.smc_hero_state import HERO_TRUST_VOCAB

    source = _HERO_STATE_PATH.read_text(encoding="utf-8")
    observed = _resolve_returns(source, "_derive_trust")
    extra = observed - HERO_TRUST_VOCAB
    missing = HERO_TRUST_VOCAB - observed
    assert not extra, (
        f"_derive_trust emits values outside HERO_TRUST_VOCAB: "
        f"{sorted(extra)} (vocab: {sorted(HERO_TRUST_VOCAB)})."
    )
    assert not missing, (
        f"HERO_TRUST_VOCAB pins {sorted(missing)} that _derive_trust "
        "never returns. Dead vocab member \u2014 confirm by walking the "
        "branches in scripts/smc_hero_state.py::_derive_trust and either "
        "restore the branch or remove the vocab member."
    )


def test_derive_bias_reaches_every_vocab_member() -> None:
    """Reachability: every :data:`HERO_BIAS_VOCAB` member is returned somewhere."""
    from scripts.smc_hero_state import HERO_BIAS_VOCAB

    source = _HERO_STATE_PATH.read_text(encoding="utf-8")
    observed = _resolve_returns(source, "_derive_bias")
    missing = HERO_BIAS_VOCAB - observed
    assert not missing, (
        f"HERO_BIAS_VOCAB pins {sorted(missing)} that _derive_bias "
        "never returns. Dead vocab member."
    )


def test_all_six_hero_vocab_constants_exposed() -> None:
    """Belt-and-braces: 6 hero vocabs are all exposed as frozensets."""
    import scripts.smc_hero_state as hs

    expected_vocabs = (
        "HERO_TRUST_VOCAB",
        "HERO_SETUP_QUALITY_VOCAB",
        "HERO_ACTION_VOCAB",
        "HERO_BIAS_VOCAB",
        "HERO_MARKET_MODE_VOCAB",
        "HERO_RISK_VOCAB",
    )
    for name in expected_vocabs:
        value = getattr(hs, name, None)
        assert isinstance(value, frozenset), f"{name} must be a frozenset"
        assert value, f"{name} must not be empty"
