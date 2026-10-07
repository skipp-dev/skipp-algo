"""Per-symbol enrichment on the global library (2026-10-07).

The generator calls 15 enrichment builders with ``symbol=""`` on the universe snapshot
(one row per symbol). Two failure modes are pinned here on synthetic state:

* bar-series builders must not read the rows of several symbols as one bar series;
* the generator must say explicitly that the symbol-dependent families were not computed.

The family list is derived from the generator source, not copied, so a new builder
called the same way cannot slip past the diagnostic.
"""
from __future__ import annotations

import ast
import importlib
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from scripts.smc_symbol_scope import (
    PER_SYMBOL_FAMILIES,
    per_symbol_scope_diagnostic,
    scope_to_symbol,
    snapshot_symbol_count,
)

ROOT = Path(__file__).resolve().parents[1]
GENERATOR = ROOT / "scripts" / "generate_smc_micro_base_from_databento.py"

BAR_BUILDERS = {
    "structure_state": "build_structure_state",
    "imbalance_lifecycle": "build_imbalance_lifecycle",
    "session_structure": "build_session_structure",
    "range_regime": "build_range_regime",
    "range_profile_regime": "build_range_profile_regime",
}


def _bars(symbol: str, start: float, step: float, n: int = 60) -> pd.DataFrame:
    rng = np.random.default_rng(sum(map(ord, symbol)))
    close = start + step * np.arange(n) + rng.normal(0, abs(step) * 2 + 0.5, n).cumsum() * 0.2
    open_ = np.r_[close[0], close[:-1]]
    high = np.maximum(open_, close) + 0.6
    low = np.minimum(open_, close) - 0.6
    ts = pd.date_range("2026-09-01 13:30", periods=n, freq="15min", tz="UTC")
    return pd.DataFrame({"symbol": symbol, "timestamp": ts, "open": open_, "high": high, "low": low,
                         "close": close, "volume": 1_000.0 + 10 * np.arange(n)})


def _two_symbols() -> pd.DataFrame:
    # Three symbols on different price levels, interleaved like a universe snapshot sorted by time:
    # rows i-2 and i always belong to different symbols, so a cross-symbol read sees fake gaps.
    # (With only two alternating symbols rows i-2 and i coincide and imbalance_lifecycle's
    # three-bar gap test stayed blind — found by the mutation probe on 2026-10-07.)
    parts = [_bars("AAA", 100.0, 0.8), _bars("BBB", 50.0, -0.5), _bars("CCC", 150.0, 0.3)]
    return pd.concat(parts).sort_values(["timestamp", "symbol"]).reset_index(drop=True)


def _builder(name: str):
    return getattr(importlib.import_module(f"scripts.smc_{name}"), BAR_BUILDERS[name])


# ── helper ──────────────────────────────────────────────────────────

def test_scope_to_symbol_cases():
    two = _two_symbols()
    assert scope_to_symbol(two, "").empty
    assert set(scope_to_symbol(two, "AAA")["symbol"]) == {"AAA"}
    one = two[two["symbol"] == "AAA"]
    assert scope_to_symbol(one, "").equals(one)
    no_col = one.drop(columns=["symbol"])
    assert scope_to_symbol(no_col, "").equals(no_col)
    assert snapshot_symbol_count(two) == 3
    assert snapshot_symbol_count(no_col) == 1
    assert snapshot_symbol_count(None) == 0


# ── bar-series builders: no cross-symbol series ─────────────────────

@pytest.mark.parametrize("name", sorted(BAR_BUILDERS))
def test_bar_builder_refuses_multi_symbol_snapshot_without_symbol(name):
    build = _builder(name)
    defaults = build(snapshot=None)
    assert build(snapshot=_two_symbols(), symbol="") == defaults


@pytest.mark.parametrize("name", sorted(BAR_BUILDERS))
def test_bar_builder_single_symbol_path_unchanged(name):
    """Positive control: the same rows of ONE symbol still derive, with or without the symbol argument."""
    build = _builder(name)
    two = _two_symbols()
    one = two[two["symbol"] == "AAA"].reset_index(drop=True)
    assert build(snapshot=two, symbol="AAA") == build(snapshot=one, symbol="")


def test_positive_control_builders_do_derive_from_these_bars():
    """At least most bar builders produce non-default output from the synthetic bars,
    so the two tests above are not passing on an all-defaults no-op."""
    one = _two_symbols().query("symbol == 'AAA'").reset_index(drop=True)
    derived = [n for n in BAR_BUILDERS if _builder(n)(snapshot=one) != _builder(n)(snapshot=None)]
    assert len(derived) >= 4, derived


# ── generator: family list is derived from the code ─────────────────

def _generator_symbolless_families() -> set[str]:
    """Enrichment keys assigned from a builder call with ``symbol=""`` in the generator."""
    tree = ast.parse(GENERATOR.read_text(encoding="utf-8"))
    keys: set[str] = set()
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Assign) and isinstance(node.value, ast.Call)):
            continue
        kw = {k.arg: k.value for k in node.value.keywords}
        sym = kw.get("symbol")
        if not (isinstance(sym, ast.Constant) and sym.value == "" and "snapshot" in kw):
            continue
        for tgt in node.targets:
            if (isinstance(tgt, ast.Subscript) and isinstance(tgt.value, ast.Name) and tgt.value.id == "enrichment"
                    and isinstance(tgt.slice, ast.Constant)):
                keys.add(tgt.slice.value)
    return keys


def test_per_symbol_family_list_matches_generator():
    found = _generator_symbolless_families()
    assert len(found) >= 15, found  # floor: the 15 families present on 2026-10-07
    assert found == set(PER_SYMBOL_FAMILIES)


def test_diagnostic_only_for_multi_symbol_snapshot():
    two = _two_symbols()
    d = per_symbol_scope_diagnostic(two, ["order_blocks", "regime"])
    assert d == {"status": "not_computed",
                 "reason": "global library has no chart symbol; symbol-dependent fields stay at their defaults",
                 "symbols_in_snapshot": 3, "families": ["order_blocks"]}
    assert per_symbol_scope_diagnostic(two[two["symbol"] == "AAA"], ["order_blocks"]) is None
    assert per_symbol_scope_diagnostic(two, ["regime"]) is None


def test_build_enrichment_marks_per_symbol_families_not_computed():
    from scripts.generate_smc_micro_base_from_databento import build_enrichment

    snap = pd.DataFrame({"symbol": ["AAA", "BBB", "CCC"], "adv_dollar_rth_20d": [1e9, 2e9, 3e9]})
    enrichment = build_enrichment(fmp_api_key="", symbols=["AAA", "BBB", "CCC"], base_snapshot=snap,
                                  enrich_order_blocks=True, enrich_imbalance_lifecycle=True)
    scope = enrichment["_diagnostics"]["per_symbol_scope"]
    assert scope["status"] == "not_computed"
    assert scope["symbols_in_snapshot"] == 3
    assert scope["families"] == ["order_blocks", "imbalance_lifecycle"]
    # outputs unchanged: still the defaults
    from scripts.smc_order_blocks import DEFAULTS as OB_DEFAULTS
    assert enrichment["order_blocks"] == OB_DEFAULTS
