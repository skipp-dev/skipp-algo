"""Pins for the TEST ONLY R4 Context readback fixture.

The fixture exists to close ``R4-OVERLAY``: the Context channels are
``display.none`` in production, so their values render nowhere and the parity
comparison against Suite and Breakout evidence cannot be made. See
``docs/SMC_R4_CONTEXT_READBACK_DECISION.md``.

What must not slip:

* the checked-in fixture is what the generator produces from the current source
  (otherwise the TradingView evidence is pinned to a file nobody can reproduce);
* the readback never leaks into the production surface — that is the one
  constraint the R2.4 precedent really establishes;
* the generator fails closed on contract drift rather than emitting a fixture
  that reads back the wrong channel set.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scripts.generate_smc_context_bus_r4_readback_fixture import (
    FIXTURE_SCRIPT_NAME,
    PARITY_GROUPS,
    build_fixture,
    build_manifest,
    parity_channel_names,
)
from scripts.smc_context_bus_manifest import CONTEXT_BUS_CHANNELS, MAX_CHANNELS

_ROOT = Path(__file__).resolve().parents[1]
_SOURCE = _ROOT / "SMC_Context_Bus.pine"
_FIXTURE = _ROOT / "tests" / "fixtures" / "pine" / "smc_context_bus_r4_readback_fixture.pine"
_MANIFEST = (
    _ROOT / "artifacts" / "governance" / "smc_context_bus_r4_readback_fixture_manifest.json"
)


def _source() -> str:
    return _SOURCE.read_text(encoding="utf-8")


def test_checked_in_fixture_matches_the_generator() -> None:
    assert _FIXTURE.read_text(encoding="utf-8") == build_fixture(_source())


def test_checked_in_manifest_matches_the_generator() -> None:
    fixture_text = _FIXTURE.read_text(encoding="utf-8")
    assert json.loads(_MANIFEST.read_text(encoding="utf-8")) == build_manifest(
        _source(), fixture_text
    )


def test_manifest_pins_the_actual_canonical_source_hash() -> None:
    """A stale hash would let source drift pass as validated evidence."""
    manifest = json.loads(_MANIFEST.read_text(encoding="utf-8"))
    assert manifest["canonicalSource"]["sha256"] == hashlib.sha256(
        _source().encode("utf-8")
    ).hexdigest()


def test_fixture_is_marked_test_only_and_cannot_be_mistaken_for_production() -> None:
    text = _FIXTURE.read_text(encoding="utf-8")
    assert text.splitlines()[0] == "//@version=6", "version annotation must lead"
    assert "TEST ONLY — DO NOT PUBLISH" in text
    assert f'indicator("{FIXTURE_SCRIPT_NAME}", overlay = false)' in text
    assert 'indicator("SMC Context Bus", overlay = false)' not in text


def test_every_channel_is_readable_in_the_fixture() -> None:
    lines = _FIXTURE.read_text(encoding="utf-8").splitlines()
    readable = [
        ln for ln in lines if ln.startswith("plot(") and ln.endswith("display = display.data_window)")
    ]
    hidden = [ln for ln in lines if ln.startswith("plot(") and "display.none" in ln]
    assert len(readable) == MAX_CHANNELS
    assert hidden == [], "a hidden channel is exactly what blocked the gate"


def test_the_production_surface_keeps_no_readback() -> None:
    """The R2.4 constraint that actually holds: never in the product surface."""
    source = _source()
    assert "table.new" not in source
    assert "display.data_window" not in source
    hidden = [
        ln
        for ln in source.splitlines()
        if ln.startswith("plot(") and ln.endswith("display = display.none)")
    ]
    assert len(hidden) == MAX_CHANNELS


def test_parity_table_covers_exactly_the_gate_channels() -> None:
    names = parity_channel_names()
    expected = tuple(c.name for c in CONTEXT_BUS_CHANNELS if c.group in PARITY_GROUPS)
    assert names == expected
    # Floor: an empty selection would make every table assertion below vacuous,
    # and the gate names both groups explicitly.
    assert len(names) == 17
    assert {c.group for c in CONTEXT_BUS_CHANNELS if c.name in names} == set(PARITY_GROUPS)

    text = _FIXTURE.read_text(encoding="utf-8")
    for row, name in enumerate(names, start=1):
        assert f'table.cell(r4_parity, 0, {row}, "{name}")' in text


def test_table_renders_the_canonical_expression_not_a_reimplementation() -> None:
    """A second detector implementation would compare the fixture with itself."""
    source_exprs = {
        ln.split(', "CTX ')[0][len("plot(") :]
        for ln in _source().splitlines()
        if ln.startswith("plot(")
    }
    text = _FIXTURE.read_text(encoding="utf-8")
    rendered = [ln for ln in text.splitlines() if "str.tostring(" in ln and "r4_parity" in ln]
    # first cell is the bar_index header, the rest are channel values
    values = [ln for ln in rendered if "bar_index" not in ln]
    assert values, "fixture renders no channel value — the check below would pass vacuously"
    assert len(values) == len(parity_channel_names())
    for line in values:
        expr = line.split("str.tostring(", 1)[1].rsplit("))", 1)[0]
        assert expr in source_exprs, f"table renders an expression not in the producer: {expr}"


def test_generator_fails_closed_when_the_channel_set_drifts() -> None:
    dropped = "\n".join(
        ln for ln in _source().splitlines() if not ln.startswith('plot(SCHEMA_VERSION, "CTX SchemaVersion"')
    )
    with pytest.raises(ValueError, match="do not match the contract"):
        build_fixture(dropped)


def test_generator_fails_closed_without_the_canonical_indicator_name() -> None:
    renamed = _source().replace(
        'indicator("SMC Context Bus", overlay = false)',
        'indicator("Something Else", overlay = false)',
    )
    with pytest.raises(ValueError, match="canonical indicator declaration not found"):
        build_fixture(renamed)
