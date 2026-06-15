"""Tests for the opt-in ``--place-paper-orders`` paper submitter (C8/T3).

These exercise the wiring of :func:`scripts.run_smc_live_incubation._build_paper_submit_fn`
and the ``--place-paper-orders`` CLI flag *without ever touching a live TWS
session*: ``place_order_intents`` is always replaced by a fake. The flag is
paper-only by construction — a live phase that passes it is refused outright.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from scripts.execute_ibkr_watchlist import (
    IBKRConnectionConfig,
)
from scripts.execute_ibkr_watchlist import (
    IBKRExecutionConfig as IBKRWatchlistExecutionConfig,
)
from scripts.run_smc_live_incubation import (
    _build_paper_submit_fn,
    main,
)
from scripts.smc_to_ibkr_adapter import (
    IBKRExecutionConfig,
    build_ibkr_intents_from_smc_setups,
)

_PAPER_PORT = 7497


def _setup(variant: str = "smc_breaker_btc", **overrides: Any) -> dict:
    base = {
        "variant": variant,
        "symbol": "BTC",
        "entry": 102.0,
        "stop_loss": 100.0,
        "take_profit": 104.0,
        "quantity": 100,
        "trade_date": "2026-04-26",
    }
    base.update(overrides)
    return base


def _read_audit(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _intents():
    return build_ibkr_intents_from_smc_setups(
        [_setup()], IBKRExecutionConfig(), size_scale=1.0
    )


class _FakePlacer:
    """Records calls and returns a placements payload 1:1 with intents."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def __call__(self, intents, *, connection_cfg, execution_cfg):
        intents = list(intents)
        self.calls.append(
            {
                "intents": intents,
                "connection_cfg": connection_cfg,
                "execution_cfg": execution_cfg,
            }
        )
        return {
            "placements": [
                {
                    "symbol": intent.symbol,
                    "orders": [
                        {
                            "order_ref": f"{intent.order_ref}-entry",
                            "status": "PreSubmitted",
                        }
                    ],
                }
                for intent in intents
            ]
        }


def _boom(*_args, **_kwargs):  # pragma: no cover - must never be invoked
    raise AssertionError("place_order_intents must not be called")


# ── unit: _build_paper_submit_fn ───────────────────────────────────


def test_paper_submit_fn_adapts_placements_to_audit_shape() -> None:
    intents = _intents()
    placer = _FakePlacer()
    submit = _build_paper_submit_fn(
        connection_cfg=IBKRConnectionConfig(),
        execution_cfg=IBKRWatchlistExecutionConfig(),
        place_fn=placer,
    )

    results = submit(intents)

    assert len(placer.calls) == 1
    assert placer.calls[0]["intents"] == list(intents)
    assert placer.calls[0]["connection_cfg"].port == _PAPER_PORT
    assert results == [
        {
            "intent_id": intent.order_ref,
            "action": "paper_submitted",
            "fill_price": None,
        }
        for intent in intents
    ]


def test_paper_submit_fn_skips_executor_when_no_intents() -> None:
    submit = _build_paper_submit_fn(
        connection_cfg=IBKRConnectionConfig(),
        execution_cfg=IBKRWatchlistExecutionConfig(),
        place_fn=_boom,
    )

    assert submit([]) == []


def test_paper_submit_fn_uses_paper_port_by_default() -> None:
    # Defense in depth: the default connection config must bind the paper
    # port so the DU* guard in place_order_intents is always engaged.
    assert IBKRConnectionConfig().port == _PAPER_PORT


# ── CLI: --place-paper-orders wiring ───────────────────────────────


def _write_inputs(tmp_path: Path) -> tuple[Path, Path, Path]:
    setups = tmp_path / "setups.json"
    statuses = tmp_path / "statuses.json"
    audit = tmp_path / "audit.jsonl"
    setups.write_text(json.dumps([_setup(variant="green_one")]), encoding="utf-8")
    statuses.write_text(json.dumps({"green_one": "green"}), encoding="utf-8")
    return setups, statuses, audit


def test_cli_place_paper_orders_invokes_executor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    setups, statuses, audit = _write_inputs(tmp_path)
    placer = _FakePlacer()
    monkeypatch.setattr(
        "scripts.run_smc_live_incubation.place_order_intents", placer
    )

    rc = main(
        [
            "--phase",
            "paper",
            "--setups",
            str(setups),
            "--gate-statuses",
            str(statuses),
            "--audit-output",
            str(audit),
            "--place-paper-orders",
        ]
    )

    assert rc == 0
    assert len(placer.calls) == 1
    assert placer.calls[0]["connection_cfg"].port == _PAPER_PORT
    audit_records = _read_audit(audit)
    assert audit_records
    assert all(rec["action"] == "paper_submitted" for rec in audit_records)


def test_cli_refuses_place_paper_orders_on_live_phase(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    setups, statuses, audit = _write_inputs(tmp_path)
    # Must refuse before ever reaching the executor.
    monkeypatch.setattr("scripts.run_smc_live_incubation.place_order_intents", _boom)

    with pytest.raises(SystemExit, match="place-paper-orders"):
        main(
            [
                "--phase",
                "live_small",
                "--setups",
                str(setups),
                "--gate-statuses",
                str(statuses),
                "--audit-output",
                str(audit),
                "--place-paper-orders",
            ]
        )


def test_cli_default_is_audit_only_no_op(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    setups, statuses, audit = _write_inputs(tmp_path)
    # Without the flag, the executor must never be reached.
    monkeypatch.setattr("scripts.run_smc_live_incubation.place_order_intents", _boom)

    rc = main(
        [
            "--phase",
            "paper",
            "--setups",
            str(setups),
            "--gate-statuses",
            str(statuses),
            "--audit-output",
            str(audit),
        ]
    )

    assert rc == 0
    audit_records = _read_audit(audit)
    assert audit_records
    assert all(rec["action"] == "audit_only" for rec in audit_records)
