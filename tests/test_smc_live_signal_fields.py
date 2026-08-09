"""Tests for the realtime-signal / trade-context fields on the /smc_live payload.

Covers ``compute._get_signal_fields`` (strongest-then-freshest selection, null
handling, producer-predates-fields tolerance, snapshot freshness gating) and
the build_payload ↔ minimal-stale-response key parity that keeps the two
payload shapes in sync.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import pytest

from services.live_overlay_daemon import compute
from services.live_overlay_daemon import main as main_mod

_REPO = Path(__file__).resolve().parents[1]


def _row(
    symbol: str, level: str, fired: float | None = None, **extra: Any
) -> dict[str, Any]:
    base: dict[str, Any] = {
        "symbol": symbol,
        "level": level,
        "direction": "LONG",
        "fired_epoch": time.time() - 10 if fired is None else fired,
        "trade_entry": 196.93, "trade_stop": 192.01, "trade_target": 206.78, "trade_r": 2.0,
    }
    base.update(extra)
    return base


def _patch_snapshot(
    monkeypatch: pytest.MonkeyPatch,
    rows: list[dict[str, Any]] | Any,
    *,
    updated_epoch: float | None = -1.0,
) -> None:
    """Patch the signals snapshot; a fresh ``updated_epoch`` is stamped by
    default (the producer stamps it on every save), ``None`` omits it."""
    if isinstance(rows, list):
        snap: Any = {"signals": rows}
        if updated_epoch == -1.0:
            snap["updated_epoch"] = time.time()
        elif updated_epoch is not None:
            snap["updated_epoch"] = updated_epoch
    else:
        snap = rows
    monkeypatch.setattr(compute, "_load_signals_snapshot", lambda: snap)


def test_stale_snapshot_yields_all_null(monkeypatch: pytest.MonkeyPatch) -> None:
    """A snapshot older than OVERLAY_SIGNALS_MAX_AGE_SECS must not serve
    signals: when the producer dies, its last write-through snapshot would
    otherwise keep an A0 + trade bracket live in the overlay forever."""
    stale_epoch = time.time() - (compute.config.signals_max_age_secs() + 120)
    _patch_snapshot(monkeypatch, [_row("NVDA", "A0")], updated_epoch=stale_epoch)
    assert compute._get_signal_fields("NVDA")["signal_level"] is None


def test_snapshot_without_updated_epoch_yields_all_null(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Freshness that cannot be proven is treated as stale (fail closed) —
    mirrors the exporter's snapshot-age-unknown critical alert posture."""
    _patch_snapshot(monkeypatch, [_row("NVDA", "A0")], updated_epoch=None)
    assert compute._get_signal_fields("NVDA")["signal_level"] is None


def test_future_snapshot_timestamp_yields_all_null(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_snapshot(monkeypatch, [_row("NVDA", "A0")], updated_epoch=time.time() + 1)
    assert compute._get_signal_fields("NVDA") == compute._NO_SIGNAL_FIELDS


def test_future_signal_timestamp_yields_all_null(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_snapshot(monkeypatch, [_row("NVDA", "A0", fired=time.time() + 1)])
    assert compute._get_signal_fields("NVDA") == compute._NO_SIGNAL_FIELDS


def test_fresh_snapshot_serves_signals(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_snapshot(monkeypatch, [_row("NVDA", "A0")])
    assert compute._get_signal_fields("NVDA")["signal_level"] == "A0"


def test_fresh_snapshot_does_not_revive_an_expired_signal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A fresh file timestamp cannot make an old row active again.

    The producer refreshes ``updated_epoch`` even when a quote poll returns no
    data. Individual rows still expire under the same eight-minute contract.
    """
    expired = time.time() - compute.config.signals_max_age_secs() - 1
    _patch_snapshot(monkeypatch, [_row("NVDA", "A0", fired=expired)])

    assert compute._get_signal_fields("NVDA") == compute._NO_SIGNAL_FIELDS


def test_no_snapshot_or_no_match_yields_all_null(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_snapshot(monkeypatch, {})  # snapshot unavailable
    fields = compute._get_signal_fields("NVDA")
    assert fields == {
        "signal_level": None, "signal_direction": None, "trade_entry": None,
        "trade_stop": None, "trade_target": None, "trade_r": None,
    }
    _patch_snapshot(monkeypatch, [_row("MSFT", "A0")])  # other symbol only
    assert compute._get_signal_fields("NVDA")["signal_level"] is None


def test_passes_trade_context_through_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_snapshot(monkeypatch, [_row("NVDA", "A0")])
    fields = compute._get_signal_fields("nvda")  # case-insensitive
    assert fields["signal_level"] == "A0" and fields["signal_direction"] == "LONG"
    assert (fields["trade_entry"], fields["trade_stop"], fields["trade_target"], fields["trade_r"]) == (
        196.93, 192.01, 206.78, 2.0,
    )


def test_non_finite_trade_field_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    # Defense-in-depth: a corrupt/overflowed producer value (float('inf')) must
    # not pass _pos_float — inf > 0.0 is True — so it never reaches the
    # allow_nan=False /smc_live payload. Finite siblings survive unchanged.
    _patch_snapshot(monkeypatch, [_row("NVDA", "A0", trade_entry=float("inf"))])
    fields = compute._get_signal_fields("NVDA")
    assert fields["trade_entry"] is None
    assert fields["trade_stop"] is None
    assert fields["trade_target"] is None
    assert fields["trade_r"] is None


def test_partial_trade_bracket_is_rejected_as_a_unit(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_snapshot(monkeypatch, [_row("NVDA", "A0", trade_target=None)])

    fields = compute._get_signal_fields("NVDA")

    assert fields["signal_level"] == "A0"
    assert fields["trade_entry"] is None
    assert fields["trade_stop"] is None
    assert fields["trade_target"] is None
    assert fields["trade_r"] is None


@pytest.mark.parametrize(
    "overrides",
    [
        {"trade_stop": 210.0, "trade_target": 190.0},
        {"direction": "SIDEWAYS"},
    ],
)
def test_incoherent_trade_bracket_is_rejected_as_a_unit(
    monkeypatch: pytest.MonkeyPatch, overrides: dict[str, object],
) -> None:
    _patch_snapshot(monkeypatch, [_row("NVDA", "A0", **overrides)])

    fields = compute._get_signal_fields("NVDA")

    assert fields["signal_level"] == "A0"
    assert fields["trade_entry"] is None
    assert fields["trade_stop"] is None
    assert fields["trade_target"] is None
    assert fields["trade_r"] is None


def test_boolean_direction_and_trade_fields_are_not_coerced(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_snapshot(
        monkeypatch,
        [
            _row(
                "NVDA",
                "A0",
                direction=True,
                trade_entry=True,
                trade_stop=True,
                trade_target=True,
                trade_r=True,
            )
        ],
    )

    fields = compute._get_signal_fields("NVDA")

    assert fields["signal_level"] == "A0"
    assert fields["signal_direction"] is None
    assert fields["trade_entry"] is None
    assert fields["trade_stop"] is None
    assert fields["trade_target"] is None
    assert fields["trade_r"] is None


def test_strongest_then_freshest_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    now = time.time()
    _patch_snapshot(monkeypatch, [
        _row("NVDA", "A1", fired=now - 20),
        _row("NVDA", "A0", fired=now - 30),   # weaker time, stronger level -> wins
        _row("NVDA", "A2", fired=now - 10),
    ])
    assert compute._get_signal_fields("NVDA")["signal_level"] == "A0"
    _patch_snapshot(monkeypatch, [
        _row("NVDA", "A1", fired=now - 20, direction="LONG"),
        _row("NVDA", "A1", fired=now - 10, direction="SHORT"),  # same level, fresher -> wins
    ])
    assert compute._get_signal_fields("NVDA")["signal_direction"] == "SHORT"


def test_producer_without_trade_fields_yields_null_trade(monkeypatch: pytest.MonkeyPatch) -> None:
    # A pre-trade-context producer snapshot has no trade_* keys — the signal
    # itself must still surface, the bracket stays null (no fabricated levels).
    row = {
        "symbol": "NVDA",
        "level": "A1",
        "direction": "LONG",
        "fired_epoch": time.time() - 10,
    }
    _patch_snapshot(monkeypatch, [row])
    fields = compute._get_signal_fields("NVDA")
    assert fields["signal_level"] == "A1"
    assert fields["trade_entry"] is None and fields["trade_r"] is None


def test_garbage_rows_and_non_positive_prices_are_null(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_snapshot(monkeypatch, [
        "not-a-dict",
        {"symbol": "NVDA", "level": "WATCH", "fired_epoch": 9.0},        # unknown level ignored
        _row("NVDA", "A1", trade_entry=0.0, trade_stop="n/a", trade_r=-1),  # unusable numbers
    ])
    fields = compute._get_signal_fields("NVDA")
    assert fields["signal_level"] == "A1"
    assert fields["trade_entry"] is None and fields["trade_stop"] is None and fields["trade_r"] is None


def test_build_payload_and_stale_response_share_the_signal_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    """The minimal stale response in main.py must carry every key build_payload
    serves (schema parity — a field added on one side only silently breaks the
    Pine consumer's nz/json.get fallback semantics)."""
    _patch_snapshot(monkeypatch, [_row("NVDA", "A0")])
    payload = compute.build_payload("NVDA", [], {"tone": None, "global_heat": None}, max_stale_secs=900)
    for key in ("signal_level", "signal_direction", "trade_entry", "trade_stop", "trade_target", "trade_r"):
        assert key in payload, f"build_payload missing {key}"
    # Parse the stale-response dict literal out of main.py via AST (no HTTP
    # needed): it is the only dict literal there carrying a "schema" key.
    import ast

    main_src = (_REPO / "services" / "live_overlay_daemon" / "main.py").read_text(encoding="utf-8")
    payload_keys = set(payload) - {"tf"}  # tf is injected per-request after build
    stale_key_sets = [
        {k.value for k in node.keys if isinstance(k, ast.Constant) and isinstance(k.value, str)}
        for node in ast.walk(ast.parse(main_src))
        if isinstance(node, ast.Dict)
    ]
    stale_keys = next((keys for keys in stale_key_sets if "schema" in keys), set())
    assert stale_keys, "could not locate the minimal stale-response dict in main.py"
    missing = payload_keys - stale_keys
    assert not missing, f"minimal stale response missing keys: {sorted(missing)}"


def test_default_5m_endpoint_refreshes_signal_fields_from_live_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The cached 5m technical payload must not freeze realtime signals.

    Full technical recomputation runs every 30 minutes, while a signal remains
    active for only eight. The request path therefore has to overlay the latest
    signal snapshot instead of returning the signal fields frozen in the
    technical cache.
    """
    cached = {
        "schema": "smc-live-overlay/1",
        "symbol": "NVDA",
        "stale": False,
        **compute._NO_SIGNAL_FIELDS,
    }
    current = {
        "signal_level": "A0",
        "signal_direction": "LONG",
        "trade_entry": 196.93,
        "trade_stop": 192.01,
        "trade_target": 206.78,
        "trade_r": 2.0,
    }
    monkeypatch.setattr(main_mod.config, "overlay_secret_token", lambda: "test-token")
    monkeypatch.setattr(main_mod.cache, "get_overlay", lambda _symbol: dict(cached))
    monkeypatch.setattr(main_mod.cache, "overlay_age_secs", lambda: 0.0)
    monkeypatch.setattr(
        main_mod.cache,
        "get_bars_snapshot",
        lambda _symbol: [{"ts_event": int((time.time() - 60) * 1_000_000_000)}],
    )
    monkeypatch.setattr(
        main_mod.library_context_bridge, "context_for_symbol", lambda _symbol: {}
    )
    monkeypatch.setattr(main_mod.compute, "_get_signal_fields", lambda _symbol: dict(current))

    response = main_mod.smc_live(
        token="test-token",
        symbol="NVDA",
        tf="5m",
    )
    payload = json.loads(response.body)

    assert {key: payload[key] for key in current} == current
