"""Freeze the bus-v2 (engine) contract before any bus-v3 (context) work begins.

The context-bus-v3 track (`docs/smc-bus-roadmap.md`, Option B) introduces a
*separate* domain-first producer (`SMC_Context_Bus.pine`, schema ``8001``) rather
than widening the engine bus. The engine bus is already at TradingView's 64-plot
cap (64/64), so v3 cannot grow v2 even if it wanted to.

This test is the machine-enforced guarantee that the v2 contract stays byte-for-byte
frozen while v3 is built alongside it. Any accidental mutation of the engine or
strategy channel surface — reorder, rename, add, drop — trips RED here. It also
guards against v3 (``CTX ...``) labels leaking into the v2 surface.

If a change to the engine bus is ever genuinely required, it must be a deliberate,
separately reviewed slice that updates the frozen tuples below with an explicit
rationale — never a silent side effect of context-bus work.
"""

from __future__ import annotations

from tests.smc_manifest_test_utils import ROOT, load_manifest, read_text

MANIFEST = load_manifest()
CORE_PATH = ROOT / 'SMC_Long_Dip_Suite.pine'

# --- Frozen v2 engine contract (64/64, at the TradingView plot cap) -----------
FROZEN_ENGINE_BUS_CHANNELS: tuple[str, ...] = (
    'SchemaVersion',
    'ZoneActive',
    'Armed',
    'Confirmed',
    'Ready',
    'EntryBest',
    'EntryStrict',
    'Trigger',
    'Invalidation',
    'QualityScore',
    'SourceKind',
    'StateCode',
    'TrendPack',
    'MetaPack',
    'LtfDeltaState',
    'SafeTrendState',
    'MicroProfileCode',
    'StopLevel',
    'Target1',
    'Target2',
    'SessionGateRow',
    'MarketGateRow',
    'VolaGateRow',
    'MicroSessionGateRow',
    'MicroFreshRow',
    'VolumeDataRow',
    'QualityEnvRow',
    'QualityStrictRow',
    'CloseStrengthRow',
    'EmaSupportRow',
    'AdxRow',
    'RelVolRow',
    'VwapRow',
    'ContextQualityRow',
    'QualityCleanRow',
    'QualityScoreRow',
    'SdConfluenceRow',
    'SdOscRow',
    'VolRegimeRow',
    'VolSqueezeRow',
    'ReadyBlockerCode',
    'StrictBlockerCode',
    'VolExpansionState',
    'DdviContextState',
    'ZoneObTop',
    'ZoneObBottom',
    'ZoneFvgTop',
    'ZoneFvgBottom',
    'SessionVwap',
    'AdxValue',
    'RelVolValue',
    'StretchZ',
    'StretchSupportMask',
    'LtfBullShare',
    'LtfBiasHint',
    'LtfVolumeDelta',
    'ObjectsCountPack',
    'LeanPackA',
    'LeanPackB',
    'PresetClassCode',
    'PresetRvolMin',
    'PresetHtfBiasMin',
    'PresetFvgQualGate',
    'PresetVolRegimeDef',
)

# Re-frozen — deliberate, reviewed change (not a side effect of context-bus work).
# QualityScore moved from position 6 to last so this tuple mirrors the engine's
# BUS plot order (channels 2..9). The *set* is unchanged (same 8 executable
# channels) and the 64-channel engine surface above is untouched.
# Rationale: TradingView lists a source study's outputs as ONE FLAT list in plot
# order, so the Strategy can only be bound straight down its settings panel if its
# rows follow that order. Order carries no semantics for the executable surface —
# unlike ENGINE_BUS_CHANNELS, whose order mirrors the Pine plot block and stays
# frozen. Landed with the BUS binding-order alignment slice.
FROZEN_STRATEGY_BUS_CHANNELS: tuple[str, ...] = (
    'Armed',
    'Confirmed',
    'Ready',
    'EntryBest',
    'EntryStrict',
    'Trigger',
    'Invalidation',
    'QualityScore',
)

# Engine producer schema. Context bus v3 must use a distinct schema (8001) so a
# consumer can never confuse the two producers.
ENGINE_BUS_SCHEMA_VERSION = 7001
RESERVED_CONTEXT_BUS_SCHEMA_VERSION = 8001


def test_engine_bus_is_frozen_at_64_channels() -> None:
    assert len(MANIFEST.ENGINE_BUS_CHANNELS) == 64
    assert MANIFEST.ENGINE_BUS_CHANNELS == FROZEN_ENGINE_BUS_CHANNELS


def test_strategy_bus_is_frozen_at_8_channels() -> None:
    assert len(MANIFEST.STRATEGY_BUS_CHANNELS) == 8
    assert MANIFEST.STRATEGY_BUS_CHANNELS == FROZEN_STRATEGY_BUS_CHANNELS


def test_dashboard_bus_stays_the_full_64_channel_engine_surface() -> None:
    # The dashboard binds the same 64-channel set as the engine exports, in its
    # own display-binding order (that order is pinned by
    # test_dashboard_binding_order_and_groups_match_manifest). The freeze
    # invariant here is only that the *set* is exactly the full engine surface —
    # the dashboard neither drops an engine channel nor binds a foreign one.
    assert len(MANIFEST.DASHBOARD_BUS_CHANNELS) == 64
    assert set(MANIFEST.DASHBOARD_BUS_CHANNELS) == set(MANIFEST.ENGINE_BUS_CHANNELS)


def test_engine_producer_still_declares_schema_7001() -> None:
    text = read_text(CORE_PATH)
    assert f"plot({ENGINE_BUS_SCHEMA_VERSION}, 'BUS SchemaVersion'" in text


def test_no_context_bus_labels_leak_into_the_engine_surface() -> None:
    # v3 channels carry the 'CTX ' prefix on their own producer; none may appear
    # on the v2 engine bus.
    assert not any(label.startswith('BUS CTX') for label in MANIFEST.ENGINE_BUS_LABELS)
    assert not any(channel.startswith('CTX') for channel in MANIFEST.ENGINE_BUS_CHANNELS)


def test_reserved_context_schema_is_distinct_from_engine_schema() -> None:
    assert RESERVED_CONTEXT_BUS_SCHEMA_VERSION != ENGINE_BUS_SCHEMA_VERSION
