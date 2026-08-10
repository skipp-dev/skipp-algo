"""Cross-contract test for producer -> strict paper-incubation audit."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path

from scripts.build_commercial_family_setups import build_commercial_family_setups
from scripts.live_risk_limits import AccountState, RiskLimits
from scripts.run_smc_live_incubation import run_live_incubation
from scripts.smc_to_ibkr_adapter import IBKRExecutionConfig

_ANCHOR = 1_800_000_000.0


def test_producer_output_passes_strict_audit_only_incubation(tmp_path: Path) -> None:
    payload = {
        "as_of": _ANCHOR,
        "bars": [{
            "timestamp": _ANCHOR,
            "open": 100.0,
            "high": 103.0,
            "low": 98.0,
            "close": 102.0,
        }],
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
        },
    }
    setups, _ = build_commercial_family_setups(
        payload,
        trade_date="2027-01-15",
    )
    gates = {setup["variant"]: "amber" for setup in setups}
    audit = tmp_path / "audit.jsonl"

    summary = run_live_incubation(
        setup_records=setups,
        gate_status_by_variant=gates,
        risk_limits=RiskLimits(),
        account_state=AccountState(
            as_of=date(2027, 1, 15),
            equity=100_000.0,
            starting_equity_today=100_000.0,
            high_water_mark=100_000.0,
            open_positions=0,
            gross_exposure_pct=0.0,
            last_n_pnls=(),
        ),
        execution_cfg=IBKRExecutionConfig(),
        audit_path=audit,
        phase="paper",
        now=datetime.fromtimestamp(_ANCHOR, UTC),
        prospective_paper_pilot=True,
    )

    assert summary["intents_passed_to_submitter"] == 4
    records = [
        json.loads(line)
        for line in audit.read_text(encoding="utf-8").splitlines()
    ]
    assert {record["family"] for record in records} == {"BOS", "OB", "FVG", "SWEEP"}
    assert {record["action"] for record in records} == {"audit_only"}
    assert all(record["evidence_class"] == "PAPER" for record in records)
    assert all(record["source_provenance"]["source"] == "databento" for record in records)
