"""Tests for the per-event SMC ledger (Amendment A1.A)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from smc_core.event_ledger import (
    EVENT_LEDGER_SCHEMA_VERSION,
    EventLedgerRecord,
    EventLedgerSchemaError,
    ledger_heuristic_score,
    ledger_label,
    ledger_path_for_pair,
    read_event_ledger,
    read_event_ledger_dir,
    validate_event_ledger_record,
    write_event_ledger,
)


@dataclass(slots=True, frozen=True)
class _FakeScoredEvent:
    """Minimal duck-type for ScoredEvent without importing the heavy module."""

    event_id: str
    family: str
    predicted_prob: float
    outcome: bool
    timestamp: float
    context: dict = field(default_factory=dict)
    raw_score: float | None = None
    raw_score_name: str | None = None


def test_schema_version_pinned() -> None:
    assert EVENT_LEDGER_SCHEMA_VERSION == "1.2"


def test_record_default_features_empty() -> None:
    record = EventLedgerRecord(
        schema_version=EVENT_LEDGER_SCHEMA_VERSION,
        event_id="e1",
        symbol="AAPL",
        timeframe="15m",
        family="FVG",
        timestamp=1.0,
        heuristic_direction_score=0.5,
        outcome=True,
    )
    assert record.features == {}
    assert record.outcome_extras == {}
    assert record.context == {}
    assert record.calibrated_prob is None  # 1.2: optional, null until back-filled


def test_round_trip_jsonl(tmp_path: Path) -> None:
    events = [
        _FakeScoredEvent(
            event_id="bos-1",
            family="BOS",
            predicted_prob=0.75,
            outcome=True,
            timestamp=1.0,
            context={"session": "NY_AM", "vol_regime": "NORMAL"},
            raw_score=82.5,
            raw_score_name="SIGNAL_QUALITY_SCORE",
        ),
        _FakeScoredEvent(
            event_id="fvg-1",
            family="FVG",
            predicted_prob=0.42,
            outcome=False,
            timestamp=2.0,
            context={"session": "ASIA", "vol_regime": "HIGH_VOL"},
        ),
    ]
    path = tmp_path / "events_AAPL_15m.jsonl"
    n = write_event_ledger(
        events, output_path=path, symbol="AAPL", timeframe="15m"
    )
    assert n == 2
    rows = list(read_event_ledger(path))
    assert len(rows) == 2
    assert rows[0]["event_id"] == "bos-1"
    assert rows[0]["symbol"] == "AAPL"
    assert rows[0]["timeframe"] == "15m"
    assert rows[0]["family"] == "BOS"
    assert rows[0]["context"] == {"session": "NY_AM", "vol_regime": "NORMAL"}
    assert rows[0]["raw_score"] == pytest.approx(82.5)
    assert rows[0]["raw_score_name"] == "SIGNAL_QUALITY_SCORE"
    assert rows[0]["schema_version"] == "1.2"
    # 1.2: the persisted heuristic prior is under the new key; the old name is gone.
    assert rows[0]["heuristic_direction_score"] == pytest.approx(0.75)
    assert "predicted_prob" not in rows[0]
    assert rows[0]["calibrated_prob"] is None  # optional OOS field, null until back-filled
    assert rows[1]["raw_score"] is None
    assert rows[1]["features"] == {}


def test_empty_input_creates_empty_file(tmp_path: Path) -> None:
    path = tmp_path / "events_AAPL_15m.jsonl"
    n = write_event_ledger([], output_path=path, symbol="AAPL", timeframe="15m")
    assert n == 0
    assert path.exists()
    assert path.read_text(encoding="utf-8") == ""


def test_dict_input_supported(tmp_path: Path) -> None:
    events = [
        {
            "event_id": "ob-1",
            "family": "OB",
            "predicted_prob": 0.6,
            "outcome": True,
            "timestamp": 3.0,
            "context": {"session": "NY_PM"},
            "features": {"gap_size_atr": 0.42, "hurst_50": 0.561, "htf_aligned": 1},
        }
    ]
    path = tmp_path / "events.jsonl"
    write_event_ledger(events, output_path=path, symbol="MSFT", timeframe="1H")
    rows = list(read_event_ledger(path))
    assert rows[0]["features"]["gap_size_atr"] == pytest.approx(0.42)
    assert rows[0]["features"]["hurst_50"] == pytest.approx(0.561)
    assert rows[0]["features"]["htf_aligned"] == 1


def test_ledger_path_for_pair() -> None:
    p = ledger_path_for_pair(
        Path("/tmp/out/AAPL/15m"), symbol="AAPL", timeframe="15m"
    )
    assert p.name == "events_AAPL_15m.jsonl"


def test_context_string_coerced(tmp_path: Path) -> None:
    events = [
        _FakeScoredEvent(
            event_id="bos-2",
            family="BOS",
            predicted_prob=0.5,
            outcome=True,
            timestamp=1.0,
            context={"session": "NY_AM", "n_pings": 3},  # int value
        )
    ]
    path = tmp_path / "events.jsonl"
    write_event_ledger(events, output_path=path, symbol="X", timeframe="15m")
    row = next(read_event_ledger(path))
    assert row["context"] == {"session": "NY_AM", "n_pings": "3"}


def test_jsonl_each_row_independently_parseable(tmp_path: Path) -> None:
    events = [
        _FakeScoredEvent(
            event_id=f"id-{i}",
            family="FVG",
            predicted_prob=0.5,
            outcome=bool(i % 2),
            timestamp=float(i),
        )
        for i in range(5)
    ]
    path = tmp_path / "events.jsonl"
    write_event_ledger(events, output_path=path, symbol="X", timeframe="15m")
    for line in path.read_text(encoding="utf-8").splitlines():
        record = json.loads(line)
        assert record["schema_version"] == "1.2"
        assert "event_id" in record


def test_missing_predicted_prob_raises_value_error(tmp_path: Path) -> None:
    """Found via SMC bug-hunt v2 phase 5: a missing predicted_prob used to
    silently coerce to 0.0 (via ``float(get(..., 0.0) or 0.0)``), turning
    every such row into a 0% prediction in downstream scoring. The reader
    must now reject the event explicitly."""
    events = [
        {
            "event_id": "ob-noprob",
            "family": "OB",
            # predicted_prob intentionally omitted
            "outcome": True,
            "timestamp": 3.0,
        }
    ]
    path = tmp_path / "events.jsonl"
    with pytest.raises(ValueError, match="predicted_prob"):
        write_event_ledger(events, output_path=path, symbol="X", timeframe="15m")


# ── write-time domain enforcement (schema-contract bug-hunt) ─────────────────


def _one_event(**overrides: object) -> dict:
    base = {
        "event_id": "e1",
        "family": "FVG",
        "predicted_prob": 0.5,
        "outcome": True,
        "timestamp": 1.0,
    }
    base.update(overrides)
    return base


@pytest.mark.parametrize("bad_prob", [-0.1, 1.5, 2.0, float("nan"), float("inf"), float("-inf")])
def test_write_rejects_out_of_range_or_nonfinite_prob(tmp_path: Path, bad_prob: float) -> None:
    path = tmp_path / "events.jsonl"
    with pytest.raises(ValueError, match="heuristic_direction_score"):
        write_event_ledger(
            [_one_event(predicted_prob=bad_prob)],
            output_path=path, symbol="X", timeframe="15m",
        )
    # atomic writer must not leave a partial file behind on rejection
    assert not path.exists()


def test_write_rejects_nonfinite_raw_score(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    with pytest.raises(ValueError, match="raw_score"):
        write_event_ledger(
            [_one_event(raw_score=float("inf"))],
            output_path=path, symbol="X", timeframe="15m",
        )


def test_write_rejects_nonfinite_feature_value(tmp_path: Path) -> None:
    # allow_nan=False on the writer's json.dumps rejects NaN/Inf anywhere,
    # including inside the open-ended features dict.
    path = tmp_path / "events.jsonl"
    with pytest.raises(ValueError):
        write_event_ledger(
            [_one_event(features={"gap_size_atr": float("nan")})],
            output_path=path, symbol="X", timeframe="15m",
        )


@pytest.mark.parametrize("bad_outcome", ["false", "true", "0", 2, 1.0, None])
def test_write_rejects_non_bool_outcome(tmp_path: Path, bad_outcome: object) -> None:
    # bool("false") would be True — a type-invalid outcome must be rejected, not coerced.
    path = tmp_path / "events.jsonl"
    with pytest.raises(ValueError, match="outcome"):
        write_event_ledger(
            [_one_event(outcome=bad_outcome)],
            output_path=path, symbol="X", timeframe="15m",
        )


@pytest.mark.parametrize(("raw", "expected"), [(1, True), (0, False), (True, True), (False, False)])
def test_write_accepts_bool_and_explicit_0_1_outcome(tmp_path: Path, raw: object, expected: bool) -> None:
    path = tmp_path / "events.jsonl"
    write_event_ledger([_one_event(outcome=raw)], output_path=path, symbol="X", timeframe="15m")
    row = next(read_event_ledger(path))
    assert row["outcome"] is expected


def test_write_preserves_zero_probability(tmp_path: Path) -> None:
    # 0.0 is a valid probability and must survive the write unchanged.
    path = tmp_path / "events.jsonl"
    write_event_ledger([_one_event(predicted_prob=0.0)], output_path=path, symbol="X", timeframe="15m")
    row = next(read_event_ledger(path))
    assert row["heuristic_direction_score"] == 0.0


# ── validate_event_ledger_record ─────────────────────────────────────────────


def _valid_record() -> dict:
    return {
        "schema_version": EVENT_LEDGER_SCHEMA_VERSION,
        "event_id": "e1", "symbol": "AAPL", "timeframe": "15m",
        "family": "FVG", "timestamp": 1.0, "heuristic_direction_score": 0.5, "outcome": True,
    }


def test_validate_accepts_valid_record() -> None:
    rec = _valid_record()
    assert validate_event_ledger_record(rec) is rec


@pytest.mark.parametrize("bad", [[1, 2, 3], "a-json-string", 42, None])
def test_validate_rejects_non_object(bad: object) -> None:
    with pytest.raises(EventLedgerSchemaError, match="expected a JSON object"):
        validate_event_ledger_record(bad)


def test_validate_rejects_missing_required_field() -> None:
    rec = _valid_record()
    del rec["outcome"]
    with pytest.raises(EventLedgerSchemaError, match="missing required field"):
        validate_event_ledger_record(rec)


def test_validate_rejects_foreign_schema_version() -> None:
    rec = _valid_record()
    rec["schema_version"] = "9.9"
    with pytest.raises(EventLedgerSchemaError, match="schema_version"):
        validate_event_ledger_record(rec)


@pytest.mark.parametrize("bad_prob", [-1, 2, float("nan"), float("inf"), True, "0.5"])
def test_validate_rejects_bad_prob(bad_prob: object) -> None:
    rec = _valid_record()
    rec["heuristic_direction_score"] = bad_prob
    with pytest.raises(EventLedgerSchemaError, match="heuristic_direction_score"):
        validate_event_ledger_record(rec)


@pytest.mark.parametrize("bad_cal", [-1, 2, float("nan"), float("inf"), True, "0.5"])
def test_validate_rejects_bad_calibrated_prob(bad_cal: object) -> None:
    rec = _valid_record()
    rec["calibrated_prob"] = bad_cal
    with pytest.raises(EventLedgerSchemaError, match="calibrated_prob"):
        validate_event_ledger_record(rec)


def test_validate_accepts_null_or_valid_calibrated_prob() -> None:
    rec = _valid_record()
    rec["calibrated_prob"] = None  # not yet back-filled
    assert validate_event_ledger_record(rec) is rec
    rec["calibrated_prob"] = 0.73
    assert validate_event_ledger_record(rec) is rec


@pytest.mark.parametrize("bad_outcome", ["false", 1, 0, None])
def test_validate_rejects_non_bool_outcome(bad_outcome: object) -> None:
    rec = _valid_record()
    rec["outcome"] = bad_outcome
    with pytest.raises(EventLedgerSchemaError, match="outcome"):
        validate_event_ledger_record(rec)


# ── read_event_ledger strict vs lenient ──────────────────────────────────────


def test_read_lenient_skips_malformed_json(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    good = json.dumps(_valid_record())
    path.write_text(good + "\n{ this is not json\n" + good + "\n", encoding="utf-8")
    rows = list(read_event_ledger(path))  # default lenient
    assert len(rows) == 2  # the malformed middle line is skipped, others survive


def test_read_strict_raises_on_malformed_json(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    path.write_text(json.dumps(_valid_record()) + "\n{ not json\n", encoding="utf-8")
    with pytest.raises(EventLedgerSchemaError, match="malformed JSON"):
        list(read_event_ledger(path, strict=True))


def test_read_strict_raises_on_off_schema_record(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    bad = _valid_record()
    bad["outcome"] = "false"  # type-invalid outcome that lenient JSON would pass through
    path.write_text(json.dumps(bad) + "\n", encoding="utf-8")
    with pytest.raises(EventLedgerSchemaError, match="outcome"):
        list(read_event_ledger(path, strict=True))


def test_read_strict_accepts_writer_output(tmp_path: Path) -> None:
    # A file produced by the writer must pass strict validation end-to-end.
    path = tmp_path / "events.jsonl"
    write_event_ledger(
        [_one_event(event_id="a", outcome=True), _one_event(event_id="b", outcome=False, predicted_prob=0.0)],
        output_path=path, symbol="AAPL", timeframe="15m",
    )
    rows = list(read_event_ledger(path, strict=True))
    assert len(rows) == 2


# ── schema 1.1: label relocation + feature_schema_versions + compat ──────────


def test_writer_relocates_labels_to_outcome_extras(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    write_event_ledger(
        [_one_event(features={
            "gap_size_atr": 0.4,
            "label_partial_50": True,
            "reaction_outcome_late": False,
        })],
        output_path=path, symbol="X", timeframe="15m",
    )
    row = next(read_event_ledger(path))
    # labels moved out of features into outcome_extras; real feature stays
    assert "label_partial_50" not in row["features"]
    assert "reaction_outcome_late" not in row["features"]
    assert row["features"]["gap_size_atr"] == pytest.approx(0.4)
    assert row["outcome_extras"]["label_partial_50"] is True
    assert row["outcome_extras"]["reaction_outcome_late"] is False


def test_writer_populates_feature_schema_versions(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    write_event_ledger(
        [_one_event(features={"reaction_schema_version": 1, "reaction_direction": "bull"})],
        output_path=path, symbol="X", timeframe="15m",
    )
    row = next(read_event_ledger(path))
    assert row["feature_schema_versions"] == {"reaction": 1}
    # version counter stays in features too (1.0 consumers still read it)
    assert row["features"]["reaction_schema_version"] == 1


def test_explicit_outcome_extras_wins_over_features_label(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    ev = _one_event(features={"label_partial_50": False})
    ev["outcome_extras"] = {"label_partial_50": True}
    write_event_ledger([ev], output_path=path, symbol="X", timeframe="15m")
    row = next(read_event_ledger(path))
    assert row["outcome_extras"]["label_partial_50"] is True


def test_ledger_label_reads_both_generations() -> None:
    v11 = {"outcome_extras": {"label_partial_50": True}, "features": {}}
    v10 = {"features": {"label_partial_50": True}}  # legacy: label under features
    assert ledger_label(v11, "label_partial_50") is True
    assert ledger_label(v10, "label_partial_50") is True
    assert ledger_label({"features": {}}, "label_partial_50", default=None) is None


def test_validate_accepts_legacy_1_0_record() -> None:
    # A 1.0 record (labels under features, no feature_schema_versions, and the
    # OLD ``predicted_prob`` key instead of heuristic_direction_score) is still valid.
    rec = _valid_record()
    rec["schema_version"] = "1.0"
    del rec["heuristic_direction_score"]
    rec["predicted_prob"] = 0.5  # legacy key — validator accepts either
    rec["features"] = {"label_partial_50": True}
    assert validate_event_ledger_record(rec) is rec


def test_validate_rejects_record_missing_both_prob_keys() -> None:
    rec = _valid_record()
    del rec["heuristic_direction_score"]
    with pytest.raises(EventLedgerSchemaError, match="heuristic-prior"):
        validate_event_ledger_record(rec)


def test_ledger_heuristic_score_reads_both_generations() -> None:
    assert ledger_heuristic_score({"heuristic_direction_score": 0.7}) == 0.7  # 1.2
    assert ledger_heuristic_score({"predicted_prob": 0.4}) == 0.4            # legacy 1.0/1.1
    # new key wins if somehow both present
    assert ledger_heuristic_score({"heuristic_direction_score": 0.7, "predicted_prob": 0.4}) == 0.7
    assert ledger_heuristic_score({}, default=-1) == -1


def test_validate_rejects_unknown_future_version() -> None:
    rec = _valid_record()
    rec["schema_version"] = "2.0"
    with pytest.raises(EventLedgerSchemaError, match="schema_version"):
        validate_event_ledger_record(rec)


def test_validate_rejects_non_dict_feature_schema_versions() -> None:
    rec = _valid_record()
    rec["feature_schema_versions"] = ["reaction", 1]
    with pytest.raises(EventLedgerSchemaError, match="feature_schema_versions"):
        validate_event_ledger_record(rec)


# ── read_event_ledger_dir (central dir-walking collector) ────────────────────


def _write_pair(root: Path, symbol: str, tf: str, records: list[dict]) -> None:
    pair = root / symbol / tf
    pair.mkdir(parents=True)
    with (pair / f"events_{symbol}_{tf}.jsonl").open("w", encoding="utf-8") as fh:
        for r in records:
            fh.write(json.dumps(r) + "\n")


def test_read_dir_filters_family_and_reports_missing_root(tmp_path: Path) -> None:
    events, warnings = read_event_ledger_dir(tmp_path / "nope")
    assert events == []
    assert any("root not found" in w for w in warnings)


def test_read_dir_no_files_warns(tmp_path: Path) -> None:
    events, warnings = read_event_ledger_dir(tmp_path)
    assert events == []
    assert any("no events_" in w for w in warnings)


def test_read_dir_lenient_collects_warnings_and_filters(tmp_path: Path) -> None:
    fvg = {**_valid_record(), "family": "FVG"}
    ob = {**_valid_record(), "family": "OB"}
    pair = tmp_path / "AAPL" / "5m"
    pair.mkdir(parents=True)
    (pair / "events_AAPL_5m.jsonl").write_text(
        json.dumps(fvg) + "\n{ not json\n" + json.dumps(ob) + "\n", encoding="utf-8"
    )
    events, warnings = read_event_ledger_dir(tmp_path, family="FVG")
    assert [e["family"] for e in events] == ["FVG"]  # OB filtered out, bad line skipped
    assert any("malformed JSON" in w for w in warnings)


def test_read_dir_strict_raises_on_corrupt_line(tmp_path: Path) -> None:
    _write_pair(tmp_path, "AAPL", "5m", [_valid_record()])
    (tmp_path / "AAPL" / "5m" / "events_AAPL_5m.jsonl").write_text(
        "{ truncated\n", encoding="utf-8"
    )
    with pytest.raises(EventLedgerSchemaError):
        read_event_ledger_dir(tmp_path, strict=True)
