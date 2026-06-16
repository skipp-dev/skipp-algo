"""Tests for scripts/accumulate_family_events.py (ADR-0023 Option B)."""
from __future__ import annotations

import json
import time
from pathlib import Path

from scripts.accumulate_family_events import _cutoff_ts, _forward_len, accumulate

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ts_days_ago(n: float) -> float:
    """Epoch-seconds timestamp n days before now."""
    return time.time() - n * 86_400


def _event(
    family: str,
    anchor_ts: float,
    n_closes: int = 5,
    score: float | None = 1.0,
) -> dict:
    evt: dict = {
        "family": family,
        "anchor_ts": anchor_ts,
        "direction": "UP",
        "entry_mode": "immediate",
        "entry_price": 100.0,
        "forward_closes": [100.0 + i for i in range(n_closes)],
        "forward_highs": [101.0 + i for i in range(n_closes)],
        "forward_lows": [99.0 + i for i in range(n_closes)],
        "forward_timestamps": [anchor_ts + (i + 1) * 900 for i in range(n_closes)],
    }
    if score is not None:
        evt["score"] = score
    return evt


# ---------------------------------------------------------------------------
# _forward_len
# ---------------------------------------------------------------------------


def test_forward_len_with_list():
    assert _forward_len({"forward_closes": [1.0, 2.0, 3.0]}) == 3


def test_forward_len_absent():
    assert _forward_len({}) == 0


def test_forward_len_none_value():
    assert _forward_len({"forward_closes": None}) == 0


# ---------------------------------------------------------------------------
# _cutoff_ts
# ---------------------------------------------------------------------------


def test_cutoff_ts_is_past():
    before = time.time()
    cutoff = _cutoff_ts(30)
    after = time.time()
    # Must be 30 days ago, within a second of tolerance.
    assert before - 30 * 86_400 - 1 <= cutoff <= after - 30 * 86_400 + 1


# ---------------------------------------------------------------------------
# accumulate: basic merge
# ---------------------------------------------------------------------------


def test_accumulate_empty_files_list():
    result = accumulate([], max_age_days=30)
    assert result == []


def test_accumulate_nonexistent_file_is_ignored(tmp_path: Path):
    result = accumulate([tmp_path / "missing.json"], max_age_days=30)
    assert result == []


def test_accumulate_single_file(tmp_path: Path):
    ts = _ts_days_ago(1)
    events = [_event("BOS", ts, n_closes=4), _event("SWEEP", ts + 900, n_closes=4)]
    f = tmp_path / "day1.json"
    f.write_text(json.dumps(events))
    result = accumulate([f], max_age_days=30)
    assert len(result) == 2
    families = {e["family"] for e in result}
    assert families == {"BOS", "SWEEP"}


def test_accumulate_two_files_no_overlap(tmp_path: Path):
    ts1 = _ts_days_ago(2)
    ts2 = _ts_days_ago(1)
    f1 = tmp_path / "day1.json"
    f2 = tmp_path / "day2.json"
    f1.write_text(json.dumps([_event("BOS", ts1)]))
    f2.write_text(json.dumps([_event("BOS", ts2)]))
    result = accumulate([f1, f2], max_age_days=30)
    assert len(result) == 2


# ---------------------------------------------------------------------------
# accumulate: deduplication — Score-Persistenz
# ---------------------------------------------------------------------------


def test_dedup_keeps_longest_forward_closes(tmp_path: Path):
    """When the same (family, anchor_ts) appears in two files, keep the one with
    more forward_closes."""
    ts = _ts_days_ago(1)
    f1 = tmp_path / "day1.json"
    f2 = tmp_path / "day2.json"
    f1.write_text(json.dumps([_event("BOS", ts, n_closes=3)]))
    f2.write_text(json.dumps([_event("BOS", ts, n_closes=7)]))
    result = accumulate([f1, f2], max_age_days=30)
    assert len(result) == 1
    assert len(result[0]["forward_closes"]) == 7


def test_dedup_longer_in_first_file(tmp_path: Path):
    ts = _ts_days_ago(1)
    f1 = tmp_path / "day1.json"
    f2 = tmp_path / "day2.json"
    f1.write_text(json.dumps([_event("SWEEP", ts, n_closes=8)]))
    f2.write_text(json.dumps([_event("SWEEP", ts, n_closes=3)]))
    result = accumulate([f1, f2], max_age_days=30)
    assert len(result) == 1
    assert len(result[0]["forward_closes"]) == 8


def test_dedup_distinct_families_not_merged(tmp_path: Path):
    ts = _ts_days_ago(1)
    f = tmp_path / "day.json"
    f.write_text(json.dumps([
        _event("BOS", ts, n_closes=5),
        _event("SWEEP", ts, n_closes=5),
    ]))
    result = accumulate([f], max_age_days=30)
    assert len(result) == 2


# ---------------------------------------------------------------------------
# accumulate: age filter
# ---------------------------------------------------------------------------


def test_age_filter_drops_old_events(tmp_path: Path):
    old_ts = _ts_days_ago(45)  # older than 30 days
    recent_ts = _ts_days_ago(5)
    f = tmp_path / "mix.json"
    f.write_text(json.dumps([
        _event("BOS", old_ts),
        _event("BOS", recent_ts),
    ]))
    result = accumulate([f], max_age_days=30)
    assert len(result) == 1
    assert abs(result[0]["anchor_ts"] - recent_ts) < 1.0


def test_age_filter_keeps_event_just_inside_window(tmp_path: Path):
    # 29.9 days old — should survive a 30-day window
    ts = _ts_days_ago(29.9)
    f = tmp_path / "edge.json"
    f.write_text(json.dumps([_event("SWEEP", ts)]))
    result = accumulate([f], max_age_days=30)
    assert len(result) == 1


def test_age_filter_drops_event_just_outside_window(tmp_path: Path):
    # 30.1 days old — should be dropped by the 30-day window
    ts = _ts_days_ago(30.1)
    f = tmp_path / "edge.json"
    f.write_text(json.dumps([_event("SWEEP", ts)]))
    result = accumulate([f], max_age_days=30)
    assert len(result) == 0


# ---------------------------------------------------------------------------
# accumulate: output ordering
# ---------------------------------------------------------------------------


def test_output_sorted_by_anchor_ts(tmp_path: Path):
    ts_a = _ts_days_ago(10)
    ts_b = _ts_days_ago(5)
    ts_c = _ts_days_ago(2)
    f = tmp_path / "unsorted.json"
    f.write_text(json.dumps([
        _event("BOS", ts_c),
        _event("BOS", ts_a),
        _event("BOS", ts_b),
    ]))
    result = accumulate([f], max_age_days=30)
    timestamps = [e["anchor_ts"] for e in result]
    assert timestamps == sorted(timestamps)


# ---------------------------------------------------------------------------
# accumulate: malformed inputs
# ---------------------------------------------------------------------------


def test_malformed_json_skipped(tmp_path: Path):
    bad = tmp_path / "bad.json"
    bad.write_text("not json at all{{{")
    good = tmp_path / "good.json"
    ts = _ts_days_ago(1)
    good.write_text(json.dumps([_event("BOS", ts)]))
    result = accumulate([bad, good], max_age_days=30)
    assert len(result) == 1


def test_non_list_json_skipped(tmp_path: Path):
    f = tmp_path / "obj.json"
    f.write_text(json.dumps({"family": "BOS", "anchor_ts": _ts_days_ago(1)}))
    result = accumulate([f], max_age_days=30)
    assert result == []


def test_event_missing_family_skipped(tmp_path: Path):
    ts = _ts_days_ago(1)
    f = tmp_path / "nofamily.json"
    f.write_text(json.dumps([{"anchor_ts": ts, "forward_closes": [1.0]}]))
    result = accumulate([f], max_age_days=30)
    assert result == []


def test_event_missing_anchor_ts_skipped(tmp_path: Path):
    f = tmp_path / "nots.json"
    f.write_text(json.dumps([{"family": "BOS", "forward_closes": [1.0]}]))
    result = accumulate([f], max_age_days=30)
    assert result == []


def test_event_invalid_anchor_ts_type_skipped(tmp_path: Path):
    f = tmp_path / "bad_ts.json"
    f.write_text(json.dumps([{"family": "BOS", "anchor_ts": "not-a-float"}]))
    result = accumulate([f], max_age_days=30)
    assert result == []


# ---------------------------------------------------------------------------
# CLI: main()
# ---------------------------------------------------------------------------


def test_main_current_plus_previous(tmp_path: Path):
    from scripts.accumulate_family_events import main

    ts_old = _ts_days_ago(10)
    ts_new = _ts_days_ago(1)
    prev = tmp_path / "prev.json"
    curr = tmp_path / "curr.json"
    out = tmp_path / "out.json"

    prev.write_text(json.dumps([_event("BOS", ts_old, n_closes=3)]))
    curr.write_text(json.dumps([_event("BOS", ts_new, n_closes=5)]))

    rc = main([
        "--current", str(curr),
        "--previous", str(prev),
        "--output", str(out),
        "--max-age-days", "30",
    ])
    assert rc == 0
    result = json.loads(out.read_text())
    assert len(result) == 2


def test_main_current_only_no_previous(tmp_path: Path):
    from scripts.accumulate_family_events import main

    ts = _ts_days_ago(1)
    curr = tmp_path / "curr.json"
    out = tmp_path / "out.json"
    curr.write_text(json.dumps([_event("SWEEP", ts)]))

    rc = main(["--current", str(curr), "--output", str(out)])
    assert rc == 0
    result = json.loads(out.read_text())
    assert len(result) == 1


def test_main_input_files(tmp_path: Path):
    from scripts.accumulate_family_events import main

    ts1 = _ts_days_ago(5)
    ts2 = _ts_days_ago(2)
    f1 = tmp_path / "a.json"
    f2 = tmp_path / "b.json"
    out = tmp_path / "out.json"
    f1.write_text(json.dumps([_event("BOS", ts1)]))
    f2.write_text(json.dumps([_event("SWEEP", ts2)]))

    rc = main(["--input-files", str(f1), str(f2), "--output", str(out)])
    assert rc == 0
    result = json.loads(out.read_text())
    assert len(result) == 2


def test_main_invalid_max_age_days(tmp_path: Path):
    from scripts.accumulate_family_events import main

    out = tmp_path / "out.json"
    curr = tmp_path / "curr.json"
    curr.write_text("[]")
    rc = main(["--current", str(curr), "--output", str(out), "--max-age-days", "0"])
    assert rc == 1


def test_main_creates_parent_dir(tmp_path: Path):
    from scripts.accumulate_family_events import main

    ts = _ts_days_ago(1)
    curr = tmp_path / "curr.json"
    curr.write_text(json.dumps([_event("BOS", ts)]))
    out = tmp_path / "nested" / "deep" / "out.json"

    rc = main(["--current", str(curr), "--output", str(out)])
    assert rc == 0
    assert out.exists()
