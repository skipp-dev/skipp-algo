"""Tests for annotate_imbalance_outcomes / load_imbalance_index (C13/T8.3)."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.backfill_live_outcomes import (
    IMBALANCE_AVAILABLE_KEY,
    IMBALANCE_FEED_KEY,
    IMBALANCE_NORMALIZED_KEY,
    IMBALANCE_SIDE_KEY,
    annotate_imbalance_outcomes,
    load_imbalance_index,
)


def _write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for r in records:
            fh.write(json.dumps(r) + "\n")


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


# ---------------------------------------------------------------------------
# load_imbalance_index
# ---------------------------------------------------------------------------


def test_load_imbalance_index_keys_uppercased(tmp_path: Path) -> None:
    p = tmp_path / "imb.jsonl"
    _write_jsonl(p, [
        {"symbol": "zim", "auction_imbalance_side": "BUY",
         "auction_imbalance_shares": 50000.0, "imbalance_feed": "NYSE",
         "available": True},
        {"symbol": "lac", "auction_imbalance_side": "SELL",
         "auction_imbalance_shares": -25000.0, "imbalance_feed": "NYSE",
         "available": True},
    ])
    index = load_imbalance_index(p)
    assert set(index.keys()) == {"ZIM", "LAC"}
    assert index["ZIM"]["auction_imbalance_side"] == "BUY"


def test_load_imbalance_index_missing_file(tmp_path: Path) -> None:
    index = load_imbalance_index(tmp_path / "nope.jsonl")
    assert index == {}


# ---------------------------------------------------------------------------
# annotate_imbalance_outcomes
# ---------------------------------------------------------------------------


def test_annotate_writes_side_feed_and_available(tmp_path: Path) -> None:
    audit = tmp_path / "audit.jsonl"
    _write_jsonl(audit, [
        {"intent_id": "1", "symbol": "ZIM", "action": "filled"},
        {"intent_id": "2", "symbol": "MARA", "action": "filled"},  # NASDAQ
        {"intent_id": "3", "symbol": "ZZZZ", "action": "filled"},  # no data
    ])
    index = {
        "ZIM": {
            "auction_imbalance_side": "BUY",
            "auction_imbalance_shares": 80_000.0,
            "imbalance_feed": "NYSE",
            "available": True,
        },
        "MARA": {
            "auction_imbalance_side": "NEUTRAL",
            "auction_imbalance_shares": None,
            "imbalance_feed": "UNAVAILABLE",
            "available": False,
        },
    }
    summary = annotate_imbalance_outcomes(audit, imbalance_index=index)
    assert summary["records_total"] == 3
    assert summary["records_annotated"] == 1
    assert summary["records_skipped_unavailable"] == 1
    assert summary["records_skipped_no_data"] == 1

    rows = _read_jsonl(audit)
    by_id = {r["intent_id"]: r for r in rows}

    # ZIM annotated.
    z = by_id["1"]
    assert z[IMBALANCE_AVAILABLE_KEY] is True
    assert z[IMBALANCE_SIDE_KEY] == "BUY"
    assert z[IMBALANCE_FEED_KEY] == "NYSE"
    assert z[IMBALANCE_NORMALIZED_KEY] is None  # no avg_volume_lookup

    # MARA marked unavailable but feed propagated.
    m = by_id["2"]
    assert m[IMBALANCE_AVAILABLE_KEY] is False
    assert m[IMBALANCE_FEED_KEY] == "UNAVAILABLE"
    assert IMBALANCE_SIDE_KEY not in m

    # ZZZZ entirely untouched.
    z2 = by_id["3"]
    assert IMBALANCE_AVAILABLE_KEY not in z2
    assert IMBALANCE_FEED_KEY not in z2


def test_annotate_normalises_with_avg_volume(tmp_path: Path) -> None:
    audit = tmp_path / "audit.jsonl"
    _write_jsonl(audit, [
        {"intent_id": "1", "symbol": "ZIM", "action": "filled"},
    ])
    index = {
        "ZIM": {
            "auction_imbalance_side": "BUY",
            "auction_imbalance_shares": 100_000.0,
            "imbalance_feed": "NYSE",
            "available": True,
        },
    }
    summary = annotate_imbalance_outcomes(
        audit,
        imbalance_index=index,
        avg_volume_lookup={"ZIM": 1_000_000.0},
    )
    assert summary["records_annotated"] == 1
    rows = _read_jsonl(audit)
    assert rows[0][IMBALANCE_NORMALIZED_KEY] == 0.1


def test_annotate_is_idempotent(tmp_path: Path) -> None:
    audit = tmp_path / "audit.jsonl"
    _write_jsonl(audit, [
        {"intent_id": "1", "symbol": "ZIM", "action": "filled"},
    ])
    index = {
        "ZIM": {
            "auction_imbalance_side": "BUY",
            "auction_imbalance_shares": 80_000.0,
            "imbalance_feed": "NYSE",
            "available": True,
        },
    }
    s1 = annotate_imbalance_outcomes(audit, imbalance_index=index)
    rows1 = _read_jsonl(audit)
    s2 = annotate_imbalance_outcomes(audit, imbalance_index=index)
    rows2 = _read_jsonl(audit)
    assert s1 == s2
    assert rows1 == rows2


def test_annotate_zero_avg_volume_leaves_normalised_none(tmp_path: Path) -> None:
    audit = tmp_path / "audit.jsonl"
    _write_jsonl(audit, [
        {"intent_id": "1", "symbol": "ZIM", "action": "filled"},
    ])
    index = {
        "ZIM": {
            "auction_imbalance_side": "BUY",
            "auction_imbalance_shares": 80_000.0,
            "imbalance_feed": "NYSE",
            "available": True,
        },
    }
    annotate_imbalance_outcomes(
        audit,
        imbalance_index=index,
        avg_volume_lookup={"ZIM": 0.0},
    )
    rows = _read_jsonl(audit)
    assert rows[0][IMBALANCE_NORMALIZED_KEY] is None
