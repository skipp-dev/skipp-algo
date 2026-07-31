"""Freeze and truthfulness gates for Context BUS v3 and its shadow consumer."""

from __future__ import annotations

import json
import re
from pathlib import Path

from scripts.smc_context_bus_manifest import (
    CHANNEL_PREFIX,
    CONTEXT_BUS_CHANNELS,
    DEFAULT_OUTPUT,
    MAX_CHANNELS,
    MIN_RESERVED_CHANNELS,
    SCHEMA_VERSION,
    TRADINGVIEW_PLOT_LIMIT,
    build_manifest,
)

ROOT = Path(__file__).resolve().parents[1]
PRODUCER = ROOT / "SMC_Context_Bus.pine"
CONSUMER = ROOT / "SMC_Context_Overlay.pine"

PLOT_TITLE_RE = re.compile(r'^\s*plot\([^\n]*,\s*"(?P<title>CTX [^"]+)"', re.MULTILINE)
SOURCE_TITLE_RE = re.compile(
    r'input\.source\([^\n]*,\s*"(?P<title>CTX [^"]+)"',
    re.MULTILINE,
)


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_manifest_is_generated_from_the_canonical_contract() -> None:
    assert json.loads(DEFAULT_OUTPUT.read_text(encoding="utf-8")) == build_manifest()


def test_context_bus_budget_reserves_two_slots() -> None:
    # 2026-07-31: 60 -> 62, reserve 4 -> 2. Two reserved slots were spent on
    # the session-MSS channels (see the contract module for why the schema
    # stays 8001). The remaining two slots are the last additive headroom
    # before the TradingView plot limit forces a successor schema.
    assert len(CONTEXT_BUS_CHANNELS) == MAX_CHANNELS == 62
    assert TRADINGVIEW_PLOT_LIMIT - len(CONTEXT_BUS_CHANNELS) >= MIN_RESERVED_CHANNELS
    assert build_manifest()["reservedChannels"] == 2


def test_channel_names_and_labels_are_unique_and_domain_first() -> None:
    names = [channel.name for channel in CONTEXT_BUS_CHANNELS]
    labels = [channel.label for channel in CONTEXT_BUS_CHANNELS]
    assert len(names) == len(set(names))
    assert len(labels) == len(set(labels))
    assert all(label.startswith(CHANNEL_PREFIX) for label in labels)
    assert not any(label.startswith("BUS ") for label in labels)


def test_producer_plot_order_exactly_matches_manifest() -> None:
    labels = PLOT_TITLE_RE.findall(_text(PRODUCER))
    expected = [channel.label for channel in CONTEXT_BUS_CHANNELS]
    assert labels == expected
    assert len(labels) == 62


def test_consumer_binding_order_exactly_matches_manifest() -> None:
    labels = SOURCE_TITLE_RE.findall(_text(CONSUMER))
    expected = [channel.label for channel in CONTEXT_BUS_CHANNELS]
    assert labels == expected
    assert len(labels) == 62


def test_schema_is_distinct_and_fail_closed() -> None:
    producer = _text(PRODUCER)
    consumer = _text(CONSUMER)
    assert f"const int SCHEMA_VERSION = {SCHEMA_VERSION}" in producer
    assert f"const int SCHEMA_VERSION = {SCHEMA_VERSION}" in consumer
    assert 'plot(SCHEMA_VERSION, "CTX SchemaVersion"' in producer
    assert "schema_ok and producer_ready and producer_fresh" in consumer
    assert "src_mask >= 0 and src_mask <= 63" in consumer
    assert "mask_domain_count == int(math.round(src_domains))" in consumer
    assert "src_epoch >= 1577836800" in consumer
    assert "src_quality >= 0 and src_quality <= 100" in consumer
    assert SCHEMA_VERSION != 7001


def test_producer_uses_the_confirmed_r3_aggregate_once() -> None:
    producer = _text(PRODUCER)
    # 2026-07-31: /4 -> /5 (session-MSS fields added to the session seam).
    assert "preuss_steffen/smc_context_engine_private/5" in producer
    assert producer.count("ctx.build_context_frame(") == 1
    assert "request.security" not in producer
    assert "lookahead_on" not in producer
    assert "strategy(" not in producer
    assert "alertcondition(" not in producer
    assert "alert(" not in producer


def test_meta_contract_carries_availability_and_confirmed_age_provenance() -> None:
    names = {channel.name for channel in CONTEXT_BUS_CHANNELS}
    assert {"Ready", "AvailabilityMask", "ConfirmedEpoch"} <= names
    producer = _text(PRODUCER)
    consumer = _text(CONSUMER)
    assert "if barstate.isconfirmed" in producer
    assert "confirmed_epoch := int(time_close / 1000)" in producer
    assert "producer_age_seconds" in consumer
    assert "producer_fresh" in consumer


def test_overlay_has_static_performance_and_object_budgets() -> None:
    consumer = _text(CONSUMER)
    # Context drawings use bounded plots/fills/shapes plus one fixed table.
    # No per-bar line/box/label allocation is permitted in the shadow overlay.
    assert consumer.count("plot(") <= 24
    assert consumer.count("plotshape(") <= 12
    assert consumer.count("fill(") <= 8
    assert consumer.count("table.new(") == 1
    assert "line.new(" not in consumer
    assert "box.new(" not in consumer
    assert "label.new(" not in consumer


def test_overlay_keeps_every_domain_optional_and_non_gating() -> None:
    consumer = _text(CONSUMER)
    for toggle in (
        "show_structure",
        "show_imbalance",
        "show_zones",
        "show_sweeps",
        "show_pools",
        "show_session",
    ):
        assert f"{toggle} = input.bool(" in consumer
    assert "strategy(" not in consumer
    assert "alertcondition(" not in consumer
    assert "alert(" not in consumer
