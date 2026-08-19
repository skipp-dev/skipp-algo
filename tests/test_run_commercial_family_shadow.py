"""Tests for the broker-free commercial-family shadow orchestrator."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from scripts.run_commercial_family_shadow import main, run_shadow_once

_ANCHOR = 1_800_000_000.0
_BAR_CLOSE = _ANCHOR + 900.0  # 2026-08-19: source_asof_ts = Bar-CLOSE; now-Fixtures leben in der Close-Welt, relative Alter bleiben identisch
_NOW = datetime.fromtimestamp(_BAR_CLOSE, UTC)


def _payload() -> dict:
    return {
        "as_of": _ANCHOR,
        "bars": [
            {
                "timestamp": _ANCHOR,
                "open": 100.0,
                "high": 103.0,
                "low": 98.0,
                "close": 102.0,
            }
        ],
        "structure": {
            "bos": [
                {
                    "id": "bos-1",
                    "time": _ANCHOR,
                    "price": 102.0,
                    "dir": "UP",
                }
            ],
            "orderblocks": [
                {
                    "id": "ob-1",
                    "anchor_ts": _ANCHOR,
                    "low": 98.0,
                    "high": 100.0,
                    "dir": "BULL",
                    "valid": True,
                }
            ],
            "fvg": [
                {
                    "id": "fvg-1",
                    "anchor_ts": _ANCHOR,
                    "low": 100.0,
                    "high": 101.0,
                    "dir": "BULL",
                    "valid": True,
                }
            ],
            "liquidity_sweeps": [
                {
                    "id": "sweep-1",
                    "time": _ANCHOR,
                    "price": 99.0,
                    "side": "SELL_SIDE",
                }
            ],
        },
        "provenance": {
            "symbol": "AAPL",
            "timeframe": "15m",
            "source": "databento",
            "dataset": "XNAS.ITCH",
        },
    }


def _paths(tmp_path: Path) -> dict:
    return {
        "setups_path": tmp_path / "setups.json",
        "gate_status_path": tmp_path / "gates.json",
        "diagnostics_path": tmp_path / "diagnostics.json",
        "audit_path": tmp_path / "audit.jsonl",
        "manifest_path": tmp_path / "manifest.json",
    }


def _audit(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_run_writes_one_complete_audit_only_snapshot(tmp_path: Path) -> None:
    paths = _paths(tmp_path)

    manifest = run_shadow_once(payload=_payload(), now=_NOW, **paths)

    assert manifest["status"] == "COMPLETED"
    assert manifest["broker_io"] is False
    assert manifest["network_io"] is False
    assert manifest["paper_orders_placed"] == 0
    rows = _audit(paths["audit_path"])
    assert len(rows) == 4
    assert {row["action"] for row in rows} == {"audit_only"}
    assert {row["source_snapshot_id"] for row in rows} == {manifest["source_snapshot_id"]}
    assert len(json.loads(paths["setups_path"].read_text(encoding="utf-8"))) == 4


def test_shadow_never_invokes_broker_order_placement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden_broker_call(*_args, **_kwargs):
        raise AssertionError("broker placement must be unreachable from shadow mode")

    monkeypatch.setattr(
        "scripts.run_smc_live_incubation.place_order_intents",
        forbidden_broker_call,
    )

    manifest = run_shadow_once(payload=_payload(), now=_NOW, **_paths(tmp_path))

    assert manifest["status"] == "COMPLETED"
    assert manifest["paper_orders_placed"] == 0


def test_restart_after_audit_repairs_manifest_without_duplicate_rows(
    tmp_path: Path,
) -> None:
    paths = _paths(tmp_path)
    first = run_shadow_once(payload=_payload(), now=_NOW, **paths)
    paths["manifest_path"].unlink()

    replay = run_shadow_once(payload=_payload(), now=_NOW, **paths)

    assert first["status"] == "COMPLETED"
    assert replay["status"] == "REPLAY_SKIPPED"
    assert len(_audit(paths["audit_path"])) == 4
    assert json.loads(paths["manifest_path"].read_text(encoding="utf-8"))["status"] == "REPLAY_SKIPPED"


def test_partial_snapshot_audit_fails_closed(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    run_shadow_once(payload=_payload(), now=_NOW, **paths)
    [first, *_] = _audit(paths["audit_path"])
    paths["audit_path"].write_text(json.dumps(first) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="partial or inconsistent audit"):
        run_shadow_once(payload=_payload(), now=_NOW, **paths)


@pytest.mark.parametrize(
    "override",
    [
        {"quantity": 100},
        {"stop_buffer_bps": 20.0},
        {"rr_target": 3.0},
    ],
)
def test_same_snapshot_with_changed_decision_contract_fails_closed(
    tmp_path: Path,
    override: dict,
) -> None:
    paths = _paths(tmp_path)
    run_shadow_once(payload=_payload(), now=_NOW, **paths)

    with pytest.raises(ValueError, match="partial or inconsistent audit"):
        run_shadow_once(payload=_payload(), now=_NOW, **override, **paths)


def test_fresh_lock_rejects_concurrent_run(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    lock_path = tmp_path / "shadow.lock"
    lock_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "token": "another-run",
                "pid": 123,
                "created_at_ts": datetime.now(UTC).timestamp(),
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="already locked"):
        run_shadow_once(
            payload=_payload(),
            now=_NOW,
            lock_path=lock_path,
            **paths,
        )


def test_stale_lock_is_recovered(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    lock_path = tmp_path / "shadow.lock"
    lock_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "token": "dead-run",
                "pid": 123,
                "created_at_ts": 1.0,
            }
        ),
        encoding="utf-8",
    )

    manifest = run_shadow_once(
        payload=_payload(),
        now=_NOW,
        lock_path=lock_path,
        **paths,
    )

    assert manifest["status"] == "COMPLETED"
    assert not lock_path.exists()


def test_no_setup_snapshot_is_recorded_without_creating_audit(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    payload = _payload()
    payload["structure"] = {
        "bos": [],
        "orderblocks": [],
        "fvg": [],
        "liquidity_sweeps": [],
    }

    manifest = run_shadow_once(payload=payload, now=_NOW, **paths)

    assert manifest["status"] == "NO_SETUPS"
    assert not paths["audit_path"].exists()


def test_cli_has_no_broker_or_network_switch(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    source = tmp_path / "input.json"
    payload = _payload()
    # 2026-08-19 (Close-Stempel): letzter Bar muss VOR jetzt schliessen; im
    # Mitternachtsfenster den Bar ganz in den Vortag schieben, sonst reisst
    # der trade_date-vs-Close-Datum-Check (deterministisch statt 15min-Flake).
    current_anchor = datetime.now(UTC).timestamp() - 901.0
    if (
        datetime.fromtimestamp(current_anchor, UTC).date()
        != datetime.fromtimestamp(current_anchor + 900.0, UTC).date()
    ):
        current_anchor -= 1800.0
    payload["as_of"] = current_anchor
    payload["bars"][0]["timestamp"] = current_anchor
    payload["structure"]["bos"][0]["time"] = current_anchor
    payload["structure"]["orderblocks"][0]["anchor_ts"] = current_anchor
    payload["structure"]["fvg"][0]["anchor_ts"] = current_anchor
    payload["structure"]["liquidity_sweeps"][0]["time"] = current_anchor
    source.write_text(json.dumps(payload), encoding="utf-8")

    rc = main(
        [
            "--input",
            str(source),
            "--setups-output",
            str(paths["setups_path"]),
            "--gate-status-output",
            str(paths["gate_status_path"]),
            "--diagnostics-output",
            str(paths["diagnostics_path"]),
            "--audit-output",
            str(paths["audit_path"]),
            "--manifest-output",
            str(paths["manifest_path"]),
            "--max-setup-age-seconds",
            "999999999",
        ]
    )

    assert rc == 0
    manifest = json.loads(paths["manifest_path"].read_text(encoding="utf-8"))
    assert manifest["broker_io"] is False
    assert manifest["network_io"] is False
