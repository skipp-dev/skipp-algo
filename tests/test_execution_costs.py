"""Tests for ADR-0023 §5 empirical execution-cost calibration.

Covers the pure estimator (``governance.execution_costs``), the calibration
CLI (``scripts/calibrate_execution_costs.py``) and the ``--cost-calibration``
wiring of the §5 gate (``scripts/run_epnl_after_cost_gate.py``).
"""
from __future__ import annotations

import json

import pytest

from governance.execution_costs import (
    MIN_FILL_RATE,
    MIN_FILL_SAMPLES,
    calibrate_costs,
    commission_bps,
    extract_leg_costs,
    slippage_bps,
)
from scripts.calibrate_execution_costs import main as calibrate_main
from scripts.run_epnl_after_cost_gate import main as gate_main

# ---- synthetic session builder -------------------------------------------


def _order(ref: str, *, lmt: float | None, action: str = "BUY") -> dict:
    return {
        "order_ref": ref,
        "order_id": hash(ref) % 10_000,
        "action": action,
        "order_type": "LMT" if lmt is not None else "TRAIL",
        "lmt_price": lmt,
        "aux_price": None,
        "status": "Submitted",
    }


def _fill(ref: str, *, side: str, shares: float, price: float, time: str = "t0") -> dict:
    return {
        "symbol": "TST",
        "order_id": hash(ref) % 10_000,
        "perm_id": hash(ref) % 90_000,
        "order_ref": ref,
        "side": side,
        "shares": shares,
        "price": price,
        "time": time,
    }


def _session(orders: list[dict], fills: list[dict]) -> dict:
    return {
        "submission": {
            "placements": [{"symbol": "TST", "orders": orders}],
        },
        "supervisor": {
            "snapshots": [{"captured_at": "2026-06-11T14:30:00Z", "fills": fills}],
            "final": {"fills": fills},
        },
    }


# ---- commission model -----------------------------------------------------


def test_commission_minimum_dominates_small_orders():
    # 100 shares @ $50: per-share = $0.50 < $1.00 minimum -> $1.00 on $5000.
    assert commission_bps(100, 50.0) == pytest.approx(1.0 / 5000.0 * 1e4)


def test_commission_per_share_regime():
    # 1000 shares @ $50: per-share = $5.00 on $50_000 notional.
    assert commission_bps(1000, 50.0) == pytest.approx(5.0 / 50_000.0 * 1e4)


def test_commission_value_cap_for_penny_stocks():
    # 10_000 shares @ $0.05: per-share = $50 but 1% cap = $5 on $500.
    assert commission_bps(10_000, 0.05) == pytest.approx(0.01 * 1e4)


def test_commission_rejects_non_positive():
    with pytest.raises(ValueError):
        commission_bps(0, 50.0)
    with pytest.raises(ValueError):
        commission_bps(100, 0.0)


# ---- slippage model -------------------------------------------------------


def test_slippage_buy_above_limit_is_cost():
    assert slippage_bps("BOT", 100.10, 100.0) == pytest.approx(10.0)


def test_slippage_buy_price_improvement_is_negative():
    assert slippage_bps("BOT", 99.90, 100.0) == pytest.approx(-10.0)


def test_slippage_sell_sign_flips():
    # Selling below the limit is a cost for the seller.
    assert slippage_bps("SLD", 99.90, 100.0) == pytest.approx(10.0)
    assert slippage_bps("SLD", 100.10, 100.0) == pytest.approx(-10.0)


def test_slippage_unknown_side_raises():
    with pytest.raises(ValueError):
        slippage_bps("HOLD", 100.0, 100.0)


# ---- leg extraction -------------------------------------------------------


def test_partial_fills_aggregate_to_vwap():
    orders = [_order("X1-entry", lmt=100.0)]
    fills = [
        _fill("X1-entry", side="BOT", shares=60, price=100.0, time="t0"),
        _fill("X1-entry", side="BOT", shares=40, price=100.5, time="t1"),
    ]
    legs, n_orders, n_filled = extract_leg_costs([_session(orders, fills)])
    assert (n_orders, n_filled) == (1, 1)
    assert len(legs) == 1
    assert legs[0].fill_vwap == pytest.approx(100.2)
    assert legs[0].slippage_bps == pytest.approx((100.2 - 100.0) / 100.0 * 1e4)


def test_snapshot_duplicates_are_deduped():
    orders = [_order("X1-entry", lmt=100.0)]
    fill = _fill("X1-entry", side="BOT", shares=100, price=100.0)
    session = _session(orders, [fill])
    # final repeats the snapshot fill; extract must count it once.
    legs, _, _ = extract_leg_costs([session])
    assert len(legs) == 1
    assert legs[0].shares == 100


def test_trailing_stop_leg_is_fee_only():
    orders = [
        _order("X1-entry", lmt=100.0),
        _order("X1-trail", lmt=None, action="SELL"),
    ]
    fills = [
        _fill("X1-entry", side="BOT", shares=100, price=100.0),
        _fill("X1-trail", side="SLD", shares=100, price=101.0),
    ]
    legs, _, _ = extract_leg_costs([_session(orders, fills)])
    by_ref = {leg.order_ref: leg for leg in legs}
    assert by_ref["X1-entry"].slippage_bps is not None
    assert by_ref["X1-trail"].slippage_bps is None
    assert by_ref["X1-trail"].fee_bps > 0


def test_unfilled_entry_lowers_fill_rate():
    orders = [_order("X1-entry", lmt=100.0), _order("X2-entry", lmt=50.0)]
    fills = [_fill("X1-entry", side="BOT", shares=100, price=100.0)]
    _, n_orders, n_filled = extract_leg_costs([_session(orders, fills)])
    assert (n_orders, n_filled) == (2, 1)


# ---- calibration ----------------------------------------------------------


def _measurable_sessions(n: int = MIN_FILL_SAMPLES) -> list[dict]:
    """n filled entry legs with 5 bps slippage each, 100% fill rate."""
    orders, fills = [], []
    for i in range(n):
        ref = f"S{i}-entry"
        orders.append(_order(ref, lmt=100.0))
        fills.append(_fill(ref, side="BOT", shares=1000, price=100.05))
    return [_session(orders, fills)]


def test_calibration_measurable_and_conservative_is_ci_high():
    cal = calibrate_costs(_measurable_sessions(), n_bootstrap=200, seed=7)
    assert cal.measurable is True
    assert cal.fail_reasons == ()
    assert cal.fill_rate == 1.0
    # 5 bps slippage + 0.5 bps fee per side, identical legs -> degenerate CI.
    assert cal.per_side_cost_bps_mean == pytest.approx(5.5, abs=0.01)
    assert cal.round_turn_cost_bps == pytest.approx(11.0, abs=0.02)
    assert cal.conservative_cost_bps == cal.round_turn_ci_high
    # degenerate distribution: CI collapses onto the mean (float noise only)
    assert cal.round_turn_ci_low == pytest.approx(cal.round_turn_cost_bps)
    assert cal.round_turn_ci_high == pytest.approx(cal.round_turn_cost_bps)


def test_calibration_deterministic_under_seed():
    a = calibrate_costs(_measurable_sessions(30), n_bootstrap=200, seed=11)
    b = calibrate_costs(_measurable_sessions(30), n_bootstrap=200, seed=11)
    assert a == b


def test_calibration_too_few_samples_unmeasurable():
    cal = calibrate_costs(_measurable_sessions(MIN_FILL_SAMPLES - 1), n_bootstrap=50, seed=1)
    assert cal.measurable is False
    assert "min_fill_samples" in cal.fail_reasons
    assert cal.conservative_cost_bps == 0.0


def test_calibration_low_fill_rate_unmeasurable():
    sessions = _measurable_sessions()
    # Add unfilled entries until the fill rate drops below the floor.
    extra = [
        _order(f"U{i}-entry", lmt=10.0)
        for i in range(int(MIN_FILL_SAMPLES / MIN_FILL_RATE) + 1)
    ]
    sessions[0]["submission"]["placements"][0]["orders"].extend(extra)
    cal = calibrate_costs(sessions, n_bootstrap=50, seed=1)
    assert cal.measurable is False
    assert "min_fill_rate" in cal.fail_reasons


def test_price_improvement_reduces_cost():
    orders, fills = [], []
    for i in range(MIN_FILL_SAMPLES):
        ref = f"P{i}-entry"
        orders.append(_order(ref, lmt=100.0))
        fills.append(_fill(ref, side="BOT", shares=1000, price=99.95))
    cal = calibrate_costs([_session(orders, fills)], n_bootstrap=200, seed=7)
    # -5 bps improvement + 0.5 bps fee = net negative per-side cost.
    assert cal.per_side_cost_bps_mean == pytest.approx(-4.5, abs=0.01)


# ---- calibration CLI ------------------------------------------------------


def test_calibrate_cli_writes_report_exit_0(tmp_path, capsys):
    session_path = tmp_path / "session.json"
    session_path.write_text(json.dumps(_measurable_sessions()[0]), encoding="utf-8")
    out_path = tmp_path / "cal.json"
    rc = calibrate_main(
        [str(session_path), "--n-bootstrap", "100", "--seed", "3", "--out", str(out_path)]
    )
    assert rc == 0
    report = json.loads(out_path.read_text(encoding="utf-8"))
    assert report["measurable"] is True
    assert report["session_paths"] == [str(session_path)]


def test_calibrate_cli_unmeasurable_exit_2(tmp_path):
    session_path = tmp_path / "thin.json"
    session_path.write_text(
        json.dumps(_measurable_sessions(2)[0]), encoding="utf-8"
    )
    out_path = tmp_path / "cal.json"
    rc = calibrate_main([str(session_path), "--out", str(out_path)])
    assert rc == 2
    report = json.loads(out_path.read_text(encoding="utf-8"))
    assert report["measurable"] is False


def test_calibrate_cli_bad_path_exit_1(tmp_path):
    assert calibrate_main([str(tmp_path / "missing.json")]) == 1


# ---- §5 gate --cost-calibration wiring ------------------------------------


def _patch_extractor(monkeypatch, *, n: int = 60):
    """Route build_report through a fake extractor (wiring, not extraction)."""
    import scripts.run_epnl_after_cost_gate as gate

    scores = [float(i) for i in range(n)]
    returns = [(i - n / 2) / 1000.0 for i in range(n)]
    seen: dict = {}

    def fake_samples(events, *, cost_bps):
        seen["cost_bps"] = cost_bps
        return {"BOS": {"scores": scores, "returns": returns}}

    monkeypatch.setattr(gate, "extract_family_calibration_samples", fake_samples)
    return seen


def test_gate_uses_conservative_cost_from_calibration(tmp_path, monkeypatch):
    seen = _patch_extractor(monkeypatch)
    cal_path = tmp_path / "cal.json"
    session_path = tmp_path / "session.json"
    session_path.write_text(json.dumps(_measurable_sessions()[0]), encoding="utf-8")
    assert calibrate_main(
        [str(session_path), "--n-bootstrap", "100", "--seed", "3", "--out", str(cal_path)]
    ) == 0
    calibration = json.loads(cal_path.read_text(encoding="utf-8"))

    events_path = tmp_path / "events.json"
    events_path.write_text(json.dumps([{"family": "BOS"}]), encoding="utf-8")
    out_path = tmp_path / "gate.json"
    rc = gate_main(
        [
            str(events_path),
            "--n-bootstrap", "200",
            "--seed", "7",
            "--cost-calibration", str(cal_path),
            "--out", str(out_path),
        ]
    )
    report = json.loads(out_path.read_text(encoding="utf-8"))
    assert report["cost_source"] == "empirical_calibration"
    assert report["cost_bps"] == pytest.approx(calibration["conservative_cost_bps"])
    assert seen["cost_bps"] == pytest.approx(calibration["conservative_cost_bps"])
    assert report["cost_calibration"]["measurable"] is True
    assert rc in (0, 2)  # verdict depends on returns vs cost; wiring is the point


def test_gate_rejects_unmeasurable_calibration(tmp_path, capsys):
    cal_path = tmp_path / "cal.json"
    cal_path.write_text(
        json.dumps({"measurable": False, "fail_reasons": ["min_fill_samples"]}),
        encoding="utf-8",
    )
    events_path = tmp_path / "events.json"
    events_path.write_text(json.dumps([{"family": "BOS"}]), encoding="utf-8")
    rc = gate_main([str(events_path), "--cost-calibration", str(cal_path)])
    assert rc == 1
    assert "refusing to fall back" in capsys.readouterr().err


def test_gate_default_remains_flat_cost(tmp_path, monkeypatch):
    _patch_extractor(monkeypatch)
    events_path = tmp_path / "events.json"
    events_path.write_text(json.dumps([{"family": "BOS"}]), encoding="utf-8")
    out_path = tmp_path / "gate.json"
    gate_main([str(events_path), "--n-bootstrap", "100", "--seed", "7", "--out", str(out_path)])
    report = json.loads(out_path.read_text(encoding="utf-8"))
    assert report["cost_source"] == "flat_default"
    assert report["cost_calibration"] is None
