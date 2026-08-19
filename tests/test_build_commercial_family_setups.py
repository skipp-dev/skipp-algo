"""Tests for the prospective commercial-family setup producer."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.build_commercial_family_setups import (
    FAMILY_VARIANTS,
    build_commercial_family_setups,
    commercial_snapshot_id,
    main,
)

_ANCHOR = 1_800_000_000.0


def _payload() -> dict:
    return {
        "as_of": _ANCHOR,
        "bars": [
            {
                "timestamp": _ANCHOR - 900,
                "open": 99.0,
                "high": 101.0,
                "low": 98.0,
                "close": 100.0,
            },
            {
                "timestamp": _ANCHOR,
                "open": 100.0,
                "high": 103.0,
                "low": 99.0,
                "close": 102.0,
            },
        ],
        "structure": {
            "bos": [{
                "id": "bos-1", "time": _ANCHOR, "price": 102.0, "dir": "UP",
            }],
            "orderblocks": [{
                "id": "ob-1", "anchor_ts": _ANCHOR,
                "low": 98.0, "high": 100.0, "dir": "BULL", "valid": True,
            }],
            "fvg": [{
                "id": "fvg-1", "anchor_ts": _ANCHOR,
                "low": 100.0, "high": 101.0, "dir": "BULL", "valid": True,
            }],
            "liquidity_sweeps": [{
                "id": "sweep-1", "time": _ANCHOR,
                "price": 99.0, "side": "SELL_SIDE",
            }],
        },
        "provenance": {
            "symbol": "AAPL",
            "timeframe": "15m",
            "source": "databento",
            "dataset": "XNAS.ITCH",
            "schema": "ohlcv-1m",
            "structure_profile": "hybrid_default",
        },
    }


def test_builds_one_fresh_long_setup_per_family() -> None:
    setups, diagnostics = build_commercial_family_setups(
        _payload(), trade_date="2027-01-15"
    )

    assert [setup["family"] for setup in setups] == ["BOS", "OB", "FVG", "SWEEP"]
    assert {setup["variant"] for setup in setups} == set(FAMILY_VARIANTS.values())
    assert all(setup["evidence_class"] == "PAPER" for setup in setups)
    assert all(setup["producer_mode"] == "prospective_pit" for setup in setups)
    assert {setup["source_snapshot_id"] for setup in setups} == {
        diagnostics["source_snapshot_id"]
    }
    assert all(setup["take_profit"] > setup["entry"] > setup["stop_loss"] for setup in setups)
    assert diagnostics["setups_emitted"] == 4


def test_rejects_forward_window_input() -> None:
    payload = _payload()
    payload["structure"]["bos"][0]["forward_closes"] = [103.0]
    with pytest.raises(ValueError, match="forward evidence"):
        build_commercial_family_setups(payload, trade_date="2027-01-15")


def test_stale_events_emit_nothing() -> None:
    payload = _payload()
    payload["as_of"] = _ANCHOR + 1
    payload["bars"].append({
        "timestamp": _ANCHOR + 1,
        "open": 102.0,
        "high": 103.0,
        "low": 101.0,
        "close": 102.5,
    })
    setups, diagnostics = build_commercial_family_setups(
        payload,
        trade_date="2027-01-15",
        max_event_age_seconds=0,
    )
    assert setups == []
    assert diagnostics["skipped"]["stale"] == 4


def test_stale_snapshot_is_rejected_before_event_selection() -> None:
    payload = _payload()
    payload["as_of"] = _ANCHOR + 901
    with pytest.raises(ValueError, match="newest confirmed bar is stale"):
        build_commercial_family_setups(payload, trade_date="2027-01-15")


def test_short_events_are_not_converted_to_long_orders() -> None:
    payload = _payload()
    payload["structure"]["bos"][0]["dir"] = "DOWN"
    payload["structure"]["orderblocks"][0]["dir"] = "BEAR"
    payload["structure"]["fvg"][0]["dir"] = "BEAR"
    payload["structure"]["liquidity_sweeps"][0]["side"] = "BUY_SIDE"
    setups, diagnostics = build_commercial_family_setups(
        payload, trade_date="2027-01-15"
    )
    assert setups == []
    assert diagnostics["skipped"]["short"] == 4


def test_level_event_requires_exact_confirmed_anchor_bar() -> None:
    payload = _payload()
    payload["structure"]["bos"][0]["time"] = _ANCHOR - 1
    setups, diagnostics = build_commercial_family_setups(
        payload, trade_date="2027-01-15"
    )
    assert {setup["family"] for setup in setups} == {"OB", "FVG", "SWEEP"}
    assert diagnostics["skipped"]["invalid"] == 1


def test_rejects_bars_after_asof_even_when_event_itself_is_old() -> None:
    payload = _payload()
    payload["bars"].append({
        "timestamp": _ANCHOR + 60,
        "open": 102.0,
        "high": 103.0,
        "low": 101.0,
        "close": 102.5,
    })
    with pytest.raises(ValueError, match=r"after input\.as_of"):
        build_commercial_family_setups(payload, trade_date="2027-01-15")


def test_invalidated_event_is_not_emitted() -> None:
    payload = _payload()
    payload["structure"]["orderblocks"][0]["valid"] = False
    setups, diagnostics = build_commercial_family_setups(
        payload, trade_date="2027-01-15"
    )
    assert "OB" not in {setup["family"] for setup in setups}
    assert diagnostics["skipped"]["invalid"] == 1


def test_newest_malformed_event_falls_back_to_newest_valid_event() -> None:
    payload = _payload()
    payload["structure"]["orderblocks"].append({
        "id": "ob-malformed",
        "anchor_ts": _ANCHOR,
        "low": 101.0,
        "high": 100.0,
        "dir": "BULL",
        "valid": True,
    })
    setups, diagnostics = build_commercial_family_setups(
        payload, trade_date="2027-01-15"
    )
    ob_setup = next(setup for setup in setups if setup["family"] == "OB")
    assert ob_setup["source_event_id"] == "ob-1"
    assert diagnostics["skipped"]["invalid"] == 1


def test_trade_date_must_match_point_in_time_snapshot() -> None:
    with pytest.raises(ValueError, match=r"does not match input\.as_of UTC date"):
        build_commercial_family_setups(_payload(), trade_date="2027-01-16")


def test_order_ref_is_replay_stable_and_timeframe_scoped() -> None:
    first, _ = build_commercial_family_setups(
        _payload(), trade_date="2027-01-15"
    )
    replay, _ = build_commercial_family_setups(
        _payload(), trade_date="2027-01-15"
    )
    alternate_timeframe_payload = _payload()
    alternate_timeframe_payload["provenance"]["timeframe"] = "5m"
    alternate_timeframe, _ = build_commercial_family_setups(
        alternate_timeframe_payload,
        trade_date="2027-01-15",
    )

    assert [row["order_ref"] for row in first] == [
        row["order_ref"] for row in replay
    ]
    assert {row["order_ref"] for row in first}.isdisjoint(
        row["order_ref"] for row in alternate_timeframe
    )
    assert all(len(row["order_ref"]) <= 45 for row in first)


def test_snapshot_id_is_canonical_and_change_sensitive() -> None:
    payload = _payload()
    reordered = dict(reversed(list(payload.items())))
    changed = _payload()
    changed["bars"][0]["close"] = 100.5

    assert commercial_snapshot_id(payload) == commercial_snapshot_id(reordered)
    assert commercial_snapshot_id(payload).startswith("sha256:")
    assert commercial_snapshot_id(payload) != commercial_snapshot_id(changed)


def test_snapshot_id_rejects_non_json_numbers() -> None:
    payload = _payload()
    payload["bars"][0]["close"] = float("nan")

    with pytest.raises(ValueError, match="canonical JSON"):
        build_commercial_family_setups(payload, trade_date="2027-01-15")


def test_cli_writes_atomic_artifacts_without_broker_io(tmp_path: Path) -> None:
    source = tmp_path / "input.json"
    setups = tmp_path / "setups.jsonl"
    gates = tmp_path / "gates.json"
    diagnostics = tmp_path / "diagnostics.json"
    source.write_text(json.dumps(_payload()), encoding="utf-8")

    rc = main([
        "--input", str(source),
        "--setups-output", str(setups),
        "--gate-status-output", str(gates),
        "--diagnostics-output", str(diagnostics),
        "--trade-date", "2027-01-15",
    ])

    assert rc == 0
    assert len(json.loads(setups.read_text(encoding="utf-8"))) == 4
    assert set(json.loads(gates.read_text(encoding="utf-8"))) == set(FAMILY_VARIANTS.values())
    assert json.loads(diagnostics.read_text(encoding="utf-8"))["setups_emitted"] == 4


def test_source_asof_is_stamped_at_bar_close_not_bar_open() -> None:
    """19.8.-Incident: Open-Stempel + Wanduhr-Budget roetete jede Setup-Attempt
    (age=1218s > 900s). Wissenszeit eines BESTAETIGTEN Bars ist sein CLOSE:
    Payload-as_of (= Open des letzten Bars) + Timeframe-Spanne."""
    setups, diagnostics = build_commercial_family_setups(
        _payload(), trade_date="2027-01-15"
    )

    assert setups, "fixture must emit setups"
    assert all(s["source_asof_ts"] == _ANCHOR + 900 for s in setups)
    # Payload-Raum bleibt unberuehrt: Diagnostics echoen das Input-as_of.
    assert diagnostics["as_of_ts"] == _ANCHOR


def test_bar_close_stamp_keeps_measured_incident_inside_budget() -> None:
    """Messlage 18.8. nachgestellt: Validierung feuert 1218.5s nach dem Open
    des letzten Bars. Mit Close-Stempel bleibt das Setup-Alter 318.5s und
    das unveraenderte 900s-Contract-Budget haelt."""
    setups, _ = build_commercial_family_setups(_payload(), trade_date="2027-01-15")

    validation_now = _ANCHOR + 1218.5
    age = validation_now - setups[0]["source_asof_ts"]
    assert age == pytest.approx(318.5)
    assert age < 900
