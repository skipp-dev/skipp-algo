"""Tests for ``scripts.backfill_live_outcomes`` (C8/T5)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.backfill_live_outcomes import (
    PNL_KEY,
    R_MULTIPLE_KEY,
    backfill_live_outcomes,
    compute_trade_outcome,
)


def _write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for record in records:
            fh.write(json.dumps(record))
            fh.write("\n")


def _read_jsonl(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


# ── compute_trade_outcome ────────────────────────────────────────────


def test_compute_outcome_one_r_long_winner() -> None:
    # entry 102, stop 100, close 104 → +2/2 = +1R, PnL +1.96% × 1000 ≈ +19.6
    pnl, r = compute_trade_outcome(
        entry_price=102.0, stop_loss=100.0, close_price=104.0, size_usd=1000.0
    )
    assert r == pytest.approx(1.0)
    assert pnl == pytest.approx((104 - 102) / 102 * 1000)


def test_compute_outcome_minus_one_r_stop_out() -> None:
    pnl, r = compute_trade_outcome(
        entry_price=102.0, stop_loss=100.0, close_price=100.0, size_usd=1000.0
    )
    assert r == pytest.approx(-1.0)
    assert pnl < 0


def test_compute_outcome_zero_risk_rejected() -> None:
    with pytest.raises(ValueError, match="zero-risk"):
        compute_trade_outcome(
            entry_price=100.0,
            stop_loss=100.0,
            close_price=101.0,
            size_usd=1000.0,
        )


# ── backfill_live_outcomes ───────────────────────────────────────────


def _closed_record(**overrides) -> dict:
    base = {
        "intent_id": "i-1",
        "action": "closed",
        "entry_price": 102.0,
        "stop_loss": 100.0,
        "take_profit": 104.0,
        "fill_price": 102.0,
        "close_price": 104.0,
        "size_usd": 1000.0,
    }
    base.update(overrides)
    return base


def test_backfill_populates_pnl_and_r_for_closed_trades(tmp_path: Path) -> None:
    path = tmp_path / "incubation_2026-04-26.jsonl"
    _write_jsonl(path, [_closed_record()])

    summary = backfill_live_outcomes(path)

    assert summary["records_backfilled"] == 1
    [record] = _read_jsonl(path)
    assert record[R_MULTIPLE_KEY] == pytest.approx(1.0)
    assert record[PNL_KEY] is not None


def test_backfill_skips_pending_trades(tmp_path: Path) -> None:
    path = tmp_path / "x.jsonl"
    _write_jsonl(path, [_closed_record(action="submitted")])

    summary = backfill_live_outcomes(path)

    assert summary["records_pending_close"] == 1
    assert summary["records_backfilled"] == 0
    [record] = _read_jsonl(path)
    assert PNL_KEY not in record


def test_backfill_counts_audit_only_separately(tmp_path: Path) -> None:
    """F-V3-15 follow-up (2026-06-10): audit_only is not a backfill stall.

    audit_only intents never reached a broker (C13 T1 NO-GO) and can
    structurally never close. The summary must expose them separately
    so the cron's progress assertion fires only on CLOSABLE pending
    records — otherwise the known NO-GO condition masquerades as an
    auth/quota regression (and would hard-fail the cron daily once
    F-V3-15 phase 2 lands).
    """
    path = tmp_path / "x.jsonl"
    _write_jsonl(path, [
        _closed_record(action="audit_only"),
        _closed_record(action="audit_only"),
        _closed_record(action="submitted"),
    ])

    summary = backfill_live_outcomes(path)

    assert summary["records_pending_close"] == 3
    assert summary["records_audit_only"] == 2
    assert summary["records_backfilled"] == 0


def test_backfill_is_idempotent(tmp_path: Path) -> None:
    path = tmp_path / "x.jsonl"
    _write_jsonl(path, [_closed_record()])

    backfill_live_outcomes(path)
    second = backfill_live_outcomes(path)

    assert second["records_backfilled"] == 0
    assert second["records_already_resolved"] == 1


def test_backfill_handles_mixed_actions(tmp_path: Path) -> None:
    path = tmp_path / "x.jsonl"
    _write_jsonl(
        path,
        [
            _closed_record(intent_id="i-1", action="closed"),
            _closed_record(intent_id="i-2", action="submitted"),
            _closed_record(intent_id="i-3", action="stop_hit", close_price=100.0),
            _closed_record(intent_id="i-4", action="tp_hit", close_price=104.0),
            _closed_record(intent_id="i-5", action="flattened", close_price=101.0),
        ],
    )

    summary = backfill_live_outcomes(path)

    assert summary["records_total"] == 5
    assert summary["records_backfilled"] == 4
    assert summary["records_pending_close"] == 1
    out = _read_jsonl(path)
    closed = [r for r in out if r["action"] != "submitted"]
    assert all(PNL_KEY in r for r in closed)


def test_backfill_leaves_record_untouched_when_close_price_missing(
    tmp_path: Path,
) -> None:
    path = tmp_path / "x.jsonl"
    record = _closed_record()
    record.pop("close_price")
    _write_jsonl(path, [record])

    summary = backfill_live_outcomes(path)

    assert summary["records_backfilled"] == 0
    [out_record] = _read_jsonl(path)
    assert PNL_KEY not in out_record


def test_backfill_preserves_existing_extra_fields(tmp_path: Path) -> None:
    path = tmp_path / "x.jsonl"
    record = _closed_record(variant="smc_breaker_btc", phase="paper")
    _write_jsonl(path, [record])

    backfill_live_outcomes(path)

    [out_record] = _read_jsonl(path)
    assert out_record["variant"] == "smc_breaker_btc"
    assert out_record["phase"] == "paper"


def test_backfill_rejects_malformed_jsonl(tmp_path: Path) -> None:
    path = tmp_path / "x.jsonl"
    path.write_text('{"intent_id": "ok"}\nnot valid json\n', encoding="utf-8")

    with pytest.raises(ValueError, match="malformed JSON"):
        backfill_live_outcomes(path)


def test_atomic_write_leaves_no_tmp_file(tmp_path: Path) -> None:
    path = tmp_path / "x.jsonl"
    _write_jsonl(path, [_closed_record()])
    backfill_live_outcomes(path)
    leftovers = list(tmp_path.glob("*.tmp"))
    assert leftovers == []
