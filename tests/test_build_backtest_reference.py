"""Tests for ``scripts.build_backtest_reference`` (C8/T6).

Pins the audit→drift schema bridge plus the backtest-reference
producer so the C8 cron pipeline can be exercised end-to-end without
re-introducing the 2026-04-26 ``backtest_reference`` lookup gap.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.build_backtest_reference import (
    build_backtest_reference,
    build_drift_input_from_audit,
    main_backtest_reference,
    main_drift_input,
)
from scripts.compute_live_drift import compute_live_drift


def test_build_backtest_reference_joins_walk_forward_and_bootstrap() -> None:
    wf = {
        "variants": [
            {
                "setup_type": "smc_breaker",
                "symbol_group": "btc",
                "sharpe": 0.93,
                "hit_rate": 0.58,
            }
        ]
    }
    bs = {
        "variants": [
            {
                "setup_type": "smc_breaker",
                "symbol_group": "btc",
                "sharpe_ci_low": 0.42,
                "sharpe_ci_high": 1.31,
                "hit_rate_ci_low": 0.50,
                "hit_rate_ci_high": 0.66,
            }
        ]
    }
    out = build_backtest_reference(walk_forward=wf, bootstrap_ci=bs)
    ref = out["backtest_reference"]
    assert "smc_breaker_btc" in ref
    slot = ref["smc_breaker_btc"]
    assert slot["sharpe"] == pytest.approx(0.93)
    assert slot["hit_rate_ci_low"] == pytest.approx(0.50)
    assert slot["hit_rate_ci_high"] == pytest.approx(0.66)


def test_build_backtest_reference_handles_direct_variant_key() -> None:
    """Rows that already carry a flat ``variant`` key (e.g. C8 audit-derived
    rollups) are accepted directly."""
    wf = {"variants": [{"variant": "smc_fvg_eth", "sharpe": 1.2}]}
    out = build_backtest_reference(walk_forward=wf)
    assert "smc_fvg_eth" in out["backtest_reference"]


def test_build_drift_input_from_audit_filters_unfilled() -> None:
    audit = [
        # filled + closed
        {
            "intent_id": "a",
            "variant": "smc_breaker_btc",
            "entry_price": 100.0,
            "fill_price": 100.5,
            "outcome_pnl_usd": 50.0,
            "outcome_r_multiple": 1.2,
            "action": "tp_hit",
        },
        # not closed yet — no outcome
        {"intent_id": "b", "variant": "smc_breaker_btc", "entry_price": 100.0},
        # closed loser
        {
            "intent_id": "c",
            "variant": "smc_breaker_btc",
            "entry_price": 100.0,
            "fill_price": 99.8,
            "outcome_pnl_usd": -25.0,
            "outcome_r_multiple": -0.5,
            "action": "stop_hit",
        },
        # missing variant — must be skipped
        {
            "intent_id": "d",
            "outcome_pnl_usd": 10.0,
            "outcome_r_multiple": 0.3,
            "entry_price": 100.0,
            "fill_price": 100.0,
        },
    ]
    rows = build_drift_input_from_audit(audit)
    assert len(rows) == 2
    a, c = rows
    assert a["variant"] == "smc_breaker_btc"
    assert a["return"] == pytest.approx(1.2)
    assert a["hit"] is True
    assert a["slippage"] == pytest.approx(0.005)
    assert c["hit"] is False
    assert c["slippage"] == pytest.approx(-0.002)


def test_audit_to_drift_to_compute_live_drift_e2e(tmp_path: Path) -> None:
    """End-to-end: audit JSONL → adapter → compute_live_drift report."""
    audit_path = tmp_path / "incubation.jsonl"
    audit_records = []
    for i in range(20):
        audit_records.append(
            {
                "intent_id": f"a{i}",
                "variant": "smc_breaker_btc",
                "entry_price": 100.0,
                "fill_price": 100.0 + 0.01 * (i % 3),
                "outcome_pnl_usd": 10.0 if i % 2 == 0 else -5.0,
                "outcome_r_multiple": 0.01 if i % 2 == 0 else -0.005,
                "action": "tp_hit" if i % 2 == 0 else "stop_hit",
            }
        )
    audit_path.write_text(
        "\n".join(json.dumps(r, sort_keys=True) for r in audit_records) + "\n",
        encoding="utf-8",
    )

    drift_path = tmp_path / "drift_input.jsonl"
    rc = main_drift_input(["--audit-jsonl", str(audit_path), "--output", str(drift_path)])
    assert rc == 0
    assert drift_path.exists()

    backtest_ref_path = tmp_path / "backtest_reference.json"
    backtest_ref_path.write_text(
        json.dumps({"backtest_reference": {"smc_breaker_btc": {"sharpe": 1.0}}}),
        encoding="utf-8",
    )

    report = compute_live_drift(
        live_jsonl=drift_path,
        backtest_calibration=backtest_ref_path,
        min_trades=5,
    )
    assert len(report["variants"]) == 1
    v = report["variants"][0]
    assert v["variant"] == "smc_breaker_btc"
    assert v["n_live_trades"] == 20
    assert v["verdict"] in {"pass", "acceptable", "concerning", "fail"}


def test_main_backtest_reference_writes_atomic_file(tmp_path: Path) -> None:
    wf = tmp_path / "walk_forward.json"
    wf.write_text(
        json.dumps({
            "variants": [
                {"setup_type": "a", "symbol_group": "x", "sharpe": 0.5},
            ]
        }),
        encoding="utf-8",
    )
    out = tmp_path / "out" / "backtest_reference.json"
    rc = main_backtest_reference(["--walk-forward", str(wf), "--output", str(out)])
    assert rc == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert "a_x" in payload["backtest_reference"]
