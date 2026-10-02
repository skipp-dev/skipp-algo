"""Tests for scripts/accumulate_family_events.py (ADR-0023 Option B)."""
from __future__ import annotations

import json
import time
from pathlib import Path

from governance.family_returns import BAR_GRID, LEGACY_BAR_GRID
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
        "bar_grid": BAR_GRID,
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


def test_dedup_backfills_score_from_superseded_copy(tmp_path: Path):
    """A scored day-0 detection must survive an unscored day-k re-detection.

    This is the exact 2026-06/07 all_thin failure mode: the re-detected copy
    has the longer forward window but lost its score (anchor drifted below
    the trailing ATR window), and keeping only the longest-forward copy
    silently discarded every score in the pool.
    """
    ts = _ts_days_ago(5)
    scored_short = _event("BOS", ts, n_closes=2, score=1.7)
    scored_short["regime"] = "trend"
    scored_short["relative_volume"] = 1.3
    unscored_long = _event("BOS", ts, n_closes=9, score=None)
    del unscored_long["entry_price"]
    f1 = tmp_path / "day0.json"
    f2 = tmp_path / "day5.json"
    f1.write_text(json.dumps([scored_short]))
    f2.write_text(json.dumps([unscored_long]))
    result = accumulate([f1, f2], max_age_days=30)
    assert len(result) == 1
    merged = result[0]
    assert len(merged["forward_closes"]) == 9
    assert merged["score"] == 1.7
    assert merged["regime"] == "trend"
    assert merged["relative_volume"] == 1.3
    assert merged["entry_price"] == 100.0


def test_dedup_backfill_is_file_order_independent(tmp_path: Path):
    """Same merge result when the unscored long copy comes first."""
    ts = _ts_days_ago(5)
    scored_short = _event("SWEEP", ts, n_closes=1, score=2.4)
    unscored_long = _event("SWEEP", ts, n_closes=6, score=None)
    f1 = tmp_path / "a.json"
    f2 = tmp_path / "b.json"
    f1.write_text(json.dumps([unscored_long]))
    f2.write_text(json.dumps([scored_short]))
    result = accumulate([f1, f2], max_age_days=30)
    assert len(result) == 1
    assert len(result[0]["forward_closes"]) == 6
    assert result[0]["score"] == 2.4


def test_dedup_winner_fields_not_overwritten_by_loser(tmp_path: Path):
    """When both copies carry a field, the longest-forward copy wins it."""
    ts = _ts_days_ago(2)
    short = _event("OB", ts, n_closes=2, score=9.9)
    long = _event("OB", ts, n_closes=5, score=1.1)
    f1 = tmp_path / "a.json"
    f2 = tmp_path / "b.json"
    f1.write_text(json.dumps([short]))
    f2.write_text(json.dumps([long]))
    result = accumulate([f1, f2], max_age_days=30)
    assert len(result) == 1
    assert result[0]["score"] == 1.1


def test_dedup_score_persists_across_chained_daily_merges(tmp_path: Path):
    """Rolling previous+current merges must not lose the score over days.

    Mirrors the production wiring: day N's accumulated output is day N+1's
    --previous input, so the merged (scored, long-forward) copy from day 1
    must keep beating later unscored re-detections.
    """
    ts = _ts_days_ago(10)
    day0 = _event("FVG", ts, n_closes=1, score=3.2)
    day1 = _event("FVG", ts, n_closes=4, score=None)
    day2 = _event("FVG", ts, n_closes=8, score=None)
    files = []
    for i, evt in enumerate((day0, day1, day2)):
        f = tmp_path / f"day{i}.json"
        f.write_text(json.dumps([evt]))
        files.append(f)
    # Chain: accumulated(day0, day1) -> prev.json; accumulate(prev, day2).
    prev = tmp_path / "prev.json"
    prev.write_text(json.dumps(accumulate(files[:2], max_age_days=30)))
    result = accumulate([prev, files[2]], max_age_days=30)
    assert len(result) == 1
    assert len(result[0]["forward_closes"]) == 8
    assert result[0]["score"] == 3.2


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


# ---------------------------------------------------------------------------
# ADR-0023 Option B — design-intent / acceptance tests
#
# These tests verify the CORE PROMISE of Issue #2706: that repeatedly
# calling accumulate_family_events (simulating N daily benchmark runs)
# grows the event pool until it surpasses MIN_OOS_SAMPLES=40 — the
# threshold below which the walk-forward calibration emits no verdict
# (status=all_thin).  They also verify the precise Score-Persistenz
# property: a re-detected event's forward window is extended each day,
# and the accumulator always keeps the longest version.
# ---------------------------------------------------------------------------


def test_pool_grows_to_min_oos_after_n_days(tmp_path: Path) -> None:
    """Simulating N successive daily runs must produce a pool ≥ MIN_OOS_SAMPLES.

    ADR-0023 Option B design contract:
      - Each daily run contributes EVENTS_PER_DAY *distinct* events
        (different anchor_ts values → no deduplication between days).
      - After ceil(MIN_OOS_SAMPLES / EVENTS_PER_DAY) iterations the pool
        must contain ≥ MIN_OOS_SAMPLES events and all events must be within
        the 30-day window.

    This is a regression guard: if the deduplication logic accidentally
    collapses distinct events from different days, or the age filter is
    too aggressive, the threshold will not be reached and this test fails.
    """
    from governance.family_calibration import MIN_OOS_SAMPLES
    from scripts.accumulate_family_events import main

    EVENTS_PER_DAY = 3          # ~9% hit-rate heuristic: 3 usable per run
    MAX_AGE_DAYS = 30
    days_needed = -(-MIN_OOS_SAMPLES // EVENTS_PER_DAY)  # ceiling division

    prev_path: Path | None = None
    out_path = tmp_path / "accumulated.json"

    for day_idx in range(days_needed):
        # Each day has EVENTS_PER_DAY events anchored at a unique timestamp
        # spaced 1 day apart so no two days share an anchor_ts.
        day_offset = MAX_AGE_DAYS - 1 - day_idx  # oldest first
        curr_events = [
            _event(
                "BOS",
                _ts_days_ago(day_offset) + slot * 900,
                n_closes=5,
            )
            for slot in range(EVENTS_PER_DAY)
        ]
        curr_path = tmp_path / f"day_{day_idx:03d}.json"
        curr_path.write_text(json.dumps(curr_events))

        args = ["--current", str(curr_path), "--output", str(out_path),
                "--max-age-days", str(MAX_AGE_DAYS)]
        if prev_path is not None:
            args += ["--previous", str(prev_path)]

        rc = main(args)
        assert rc == 0, f"accumulate failed on day {day_idx}"

        # Rotate: today's output becomes tomorrow's previous
        prev_path = tmp_path / f"prev_{day_idx:03d}.json"
        out_path.rename(prev_path)
        out_path = tmp_path / "accumulated.json"

    # Final accumulated pool must meet the threshold
    result = json.loads(prev_path.read_text())  # type: ignore[union-attr]
    assert len(result) >= MIN_OOS_SAMPLES, (
        f"After {days_needed} simulated daily runs the pool has only "
        f"{len(result)} events — expected ≥ {MIN_OOS_SAMPLES} (MIN_OOS_SAMPLES). "
        "The accumulation logic may be discarding too many events."
    )
    # All retained events must be within the age window
    cutoff = _cutoff_ts(MAX_AGE_DAYS)
    too_old = [e for e in result if float(e["anchor_ts"]) < cutoff]
    assert not too_old, (
        f"{len(too_old)} events survived past the {MAX_AGE_DAYS}-day age filter."
    )


def test_score_persistenz_keeps_longest_window_across_days(tmp_path: Path) -> None:
    """Score-Persistenz: the same event re-detected on day N+k keeps the
    version with the most forward_closes (longest outcome window).

    Daily runs extend the realized-return window of still-open structures
    by appending one more bar each day.  The accumulator must always keep
    the longest version so downstream calibration sees the most complete
    return series — without this guarantee the pool would be systematically
    downgraded to the shortest window seen last.
    """
    from scripts.accumulate_family_events import main

    ts = _ts_days_ago(5)  # one fixed anchor_ts — same event every day
    prev_path: Path | None = None
    out_path = tmp_path / "out.json"

    for day_idx in range(8):
        n_closes = day_idx + 1  # grows by 1 each simulated day
        curr_path = tmp_path / f"day_{day_idx}.json"
        curr_path.write_text(json.dumps([_event("BOS", ts, n_closes=n_closes)]))

        args = ["--current", str(curr_path), "--output", str(out_path)]
        if prev_path is not None:
            args += ["--previous", str(prev_path)]
        main(args)

        prev_path = tmp_path / f"prev_{day_idx}.json"
        out_path.rename(prev_path)
        out_path = tmp_path / "out.json"

    result = json.loads(prev_path.read_text())  # type: ignore[union-attr]
    assert len(result) == 1, "Identical (family, anchor_ts) must stay as one entry"
    assert len(result[0]["forward_closes"]) == 8, (
        f"Expected 8 forward_closes (day-8 version, longest window); "
        f"got {len(result[0]['forward_closes'])}. Score-Persistenz broken."
    )


def test_age_pruning_prevents_unbounded_growth(tmp_path: Path) -> None:
    """Accumulating beyond max_age_days must NOT grow the pool without bound.

    If the age filter is absent or broken, the pool would grow indefinitely
    and eventually include stale events that no longer represent current
    market behaviour.  This test verifies that after 35 daily runs the pool
    stays bounded at ≤ max_age_days * events_per_day events.
    """
    from scripts.accumulate_family_events import main

    MAX_AGE_DAYS = 10           # small window so the test stays fast
    EVENTS_PER_DAY = 2
    TOTAL_RUNS = 35             # 3.5 × the window — must not keep all 35 × 2

    prev_path: Path | None = None
    out_path = tmp_path / "out.json"

    for day_idx in range(TOTAL_RUNS):
        # Space events so each day has a unique anchor_ts cluster
        base_ts = _ts_days_ago(TOTAL_RUNS - day_idx)  # oldest first
        curr_events = [
            _event("SWEEP", base_ts + slot * 900, n_closes=3)
            for slot in range(EVENTS_PER_DAY)
        ]
        curr_path = tmp_path / f"run_{day_idx:03d}.json"
        curr_path.write_text(json.dumps(curr_events))

        args = ["--current", str(curr_path), "--output", str(out_path),
                "--max-age-days", str(MAX_AGE_DAYS)]
        if prev_path is not None:
            args += ["--previous", str(prev_path)]
        main(args)

        prev_path = tmp_path / f"prev_{day_idx:03d}.json"
        out_path.rename(prev_path)
        out_path = tmp_path / "out.json"

    result = json.loads(prev_path.read_text())  # type: ignore[union-attr]
    max_expected = MAX_AGE_DAYS * EVENTS_PER_DAY
    assert len(result) <= max_expected, (
        f"Pool grew to {len(result)} events after {TOTAL_RUNS} runs; "
        f"expected ≤ {max_expected} (age-pruned to {MAX_AGE_DAYS} days × "
        f"{EVENTS_PER_DAY} events/day).  The age filter is not pruning correctly."
    )


# --------------------------------------------------------------------------- #
# --max-shrink-fraction pool-continuity guard (issue #3872 post-mortem)
# --------------------------------------------------------------------------- #
def _guard_args(tmp_path: Path, prev_events: list, curr_events: list) -> list[str]:
    prev = tmp_path / "prev.json"
    curr = tmp_path / "curr.json"
    prev.write_text(json.dumps(prev_events))
    curr.write_text(json.dumps(curr_events))
    return [
        "--current", str(curr),
        "--previous", str(prev),
        "--output", str(tmp_path / "out.json"),
        "--max-age-days", "30",
        "--max-shrink-fraction", "0.5",
    ]


def test_guard_refuses_empty_merge_of_nonempty_previous(tmp_path: Path):
    """2026-07-13 wipe: an all-aged-out merge produced a JSON '[]' that
    passed the workflow's file-size check and REPLACED the canonical pool;
    the lineage then rebuilt from single-day snapshots. The guard must
    refuse to write and leave the last-good artifact canonical."""
    from scripts.accumulate_family_events import main

    now = time.time()
    ancient = [_event("BOS", now - 90 * 86_400 + i) for i in range(10)]
    rc = main(_guard_args(tmp_path, prev_events=ancient, curr_events=[]))
    assert rc == 4
    assert not (tmp_path / "out.json").exists()


def test_guard_refuses_pathological_shrink(tmp_path: Path):
    from scripts.accumulate_family_events import main

    now = time.time()
    fresh = [_event("BOS", now - 86_400 + i) for i in range(10)]
    aged = [_event("BOS", now - 90 * 86_400 + i) for i in range(90)]
    # merged keeps 10 of 100 previous events -> below the 50% floor.
    rc = main(_guard_args(tmp_path, prev_events=fresh + aged, curr_events=[]))
    assert rc == 4
    assert not (tmp_path / "out.json").exists()


def test_guard_allows_normal_ageout_and_growth(tmp_path: Path):
    from scripts.accumulate_family_events import main

    now = time.time()
    prev = [_event("BOS", now - (2 + i) * 86_400) for i in range(8)]
    curr = [_event("SWEEP", now - 3_600 + i) for i in range(3)]
    rc = main(_guard_args(tmp_path, prev_events=prev, curr_events=curr))
    assert rc == 0
    result = json.loads((tmp_path / "out.json").read_text())
    assert len(result) == 11


def test_guard_off_by_default_keeps_previous_behaviour(tmp_path: Path):
    from scripts.accumulate_family_events import main

    now = time.time()
    ancient = [_event("BOS", now - 90 * 86_400 + i) for i in range(10)]
    prev = tmp_path / "prev.json"
    curr = tmp_path / "curr.json"
    prev.write_text(json.dumps(ancient))
    curr.write_text(json.dumps([]))
    rc = main([
        "--current", str(curr),
        "--previous", str(prev),
        "--output", str(tmp_path / "out.json"),
        "--max-age-days", "30",
    ])
    assert rc == 0
    assert json.loads((tmp_path / "out.json").read_text()) == []


def test_guard_rejects_invalid_fraction(tmp_path: Path):
    from scripts.accumulate_family_events import main

    rc = main([*_guard_args(tmp_path, prev_events=[], curr_events=[])[:-1], "1.5"])
    assert rc == 1


def test_rolling_workflow_arms_the_continuity_guard():
    workflow = (
        Path(__file__).resolve().parents[1]
        / ".github" / "workflows" / "smc-measurement-benchmark-rolling.yml"
    ).read_text(encoding="utf-8")
    assert '"--max-shrink-fraction" "0.5"' in workflow


# ---------------------------------------------------------------------------
# Event identity (2026-10-01): the key is the event, not the bar.
#
# The pool is multi-symbol and multi-timeframe; bars of different symbols
# share their timestamps. Keyed on ``(family, anchor_ts)`` the accumulator
# kept ONE survivor per family and bar — measured on the daily file of
# 2026-09-24: 11 586 events, 11 586 distinct event_ids, 1 570 distinct
# (family, anchor_ts). These tests build that situation synthetically.
# ---------------------------------------------------------------------------


def _event_with_id(
    family: str, symbol: str, timeframe: str, anchor_ts: float, *,
    n_closes: int = 5, score: float | None = 1.0, level: float = 100.0,
) -> dict:
    evt = _event(family, anchor_ts, n_closes=n_closes, score=score)
    evt["event_id"] = f"{family.lower()}:{symbol}:{timeframe}:{int(anchor_ts)}:UP:{level:.2f}"
    return evt


def test_same_bar_events_of_different_symbols_all_survive(tmp_path: Path) -> None:
    """The measured example: BOS on AAPL, GOOGL and NVDA in the same 5m bar."""
    ts = _ts_days_ago(1)
    f = tmp_path / "day.json"
    f.write_text(json.dumps([
        _event_with_id("BOS", "AAPL", "5m", ts, level=335.79),
        _event_with_id("BOS", "GOOGL", "5m", ts, level=350.52),
        _event_with_id("BOS", "NVDA", "5m", ts, level=223.45),
    ]))
    result = accumulate([f], max_age_days=30)
    assert sorted(e["event_id"].split(":")[1] for e in result) == ["AAPL", "GOOGL", "NVDA"]


def test_same_bar_events_of_different_timeframes_all_survive(tmp_path: Path) -> None:
    """A 5m and a 15m bar can start on the same timestamp."""
    ts = _ts_days_ago(1)
    f = tmp_path / "day.json"
    f.write_text(json.dumps([
        _event_with_id("FVG", "AAPL", "5m", ts),
        _event_with_id("FVG", "AAPL", "15m", ts),
    ]))
    assert len(accumulate([f], max_age_days=30)) == 2


def test_a_daily_plane_keeps_every_symbol_not_one_per_day(tmp_path: Path) -> None:
    """On 1D every symbol shares the daily bar timestamp.

    The old key therefore capped the governed 1D plane at one event per family
    and trading day (measured 2026-09-24: 293 -> 62) — the reason its track
    record never left ~20-30 trades.
    """
    symbols = [f"SYM{i:02d}" for i in range(20)]
    days = [_ts_days_ago(d) for d in (1, 2, 3)]
    f = tmp_path / "day.json"
    f.write_text(json.dumps([
        _event_with_id("OB", symbol, "1D", ts) for ts in days for symbol in symbols
    ]))
    assert len(accumulate([f], max_age_days=30)) == len(symbols) * len(days)


def test_the_same_event_redetected_is_still_one_entry(tmp_path: Path) -> None:
    """Score-Persistenz is unchanged — it now works per EVENT.

    Day 2 re-detects AAPL's event with a longer window but no score; the
    GOOGL event of the same bar must neither absorb it nor lend it a score.
    """
    ts = _ts_days_ago(2)
    day1 = tmp_path / "day1.json"
    day2 = tmp_path / "day2.json"
    day1.write_text(json.dumps([
        _event_with_id("BOS", "AAPL", "5m", ts, n_closes=3, score=0.9, level=335.79),
        _event_with_id("BOS", "GOOGL", "5m", ts, n_closes=3, score=0.2, level=350.52),
    ]))
    day2.write_text(json.dumps([
        _event_with_id("BOS", "AAPL", "5m", ts, n_closes=7, score=None, level=335.79),
    ]))
    result = {e["event_id"].split(":")[1]: e for e in accumulate([day1, day2], max_age_days=30)}
    assert sorted(result) == ["AAPL", "GOOGL"]
    assert len(result["AAPL"]["forward_closes"]) == 7
    assert result["AAPL"]["score"] == 0.9, "the score must come from AAPL's own earlier copy"
    assert result["GOOGL"]["score"] == 0.2
    assert len(result["GOOGL"]["forward_closes"]) == 3


def test_an_event_without_id_keeps_the_legacy_key(tmp_path: Path) -> None:
    """Id-less events (legacy, hand-built) still dedupe on (family, anchor_ts)."""
    ts = _ts_days_ago(1)
    f1 = tmp_path / "day1.json"
    f2 = tmp_path / "day2.json"
    f1.write_text(json.dumps([_event("BOS", ts, n_closes=3)]))
    f2.write_text(json.dumps([_event("BOS", ts, n_closes=6)]))
    result = accumulate([f1, f2], max_age_days=30)
    assert len(result) == 1
    assert len(result[0]["forward_closes"]) == 6


def test_id_and_legacy_key_spaces_do_not_collide(tmp_path: Path) -> None:
    ts = _ts_days_ago(1)
    f = tmp_path / "day.json"
    blank = _event("BOS", ts)
    blank["event_id"] = "   "  # blank id == no id
    f.write_text(json.dumps([_event("BOS", ts), blank, _event_with_id("BOS", "AAPL", "5m", ts)]))
    result = accumulate([f], max_age_days=30)
    # the two id-less copies are one legacy event; the id-bearing one is its own
    assert len(result) == 2


def test_output_order_is_deterministic_for_same_bar_events(tmp_path: Path) -> None:
    ts = _ts_days_ago(1)
    events = [_event_with_id("BOS", s, "5m", ts) for s in ("NVDA", "AAPL", "MSFT")]
    f1 = tmp_path / "a.json"
    f2 = tmp_path / "b.json"
    f1.write_text(json.dumps(events))
    f2.write_text(json.dumps(list(reversed(events))))
    first = [e["event_id"] for e in accumulate([f1], max_age_days=30)]
    second = [e["event_id"] for e in accumulate([f2], max_age_days=30)]
    assert first == second


# ---------------------------------------------------------------------------
# forward_opens (ADR-0031, Nachtrag 2026-10-02 II): the return rule enters at
# an open; pool copies recorded before the rule carry none.
# ---------------------------------------------------------------------------


def _with_opens(event: dict) -> dict:
    closes = event["forward_closes"]
    return {**event, "forward_opens": [closes[0] - 0.5, *closes[:-1]]}


def _pool_then_today(tmp_path: Path, pooled: dict, today: dict) -> list[dict]:
    prev = tmp_path / "prev.json"
    curr = tmp_path / "curr.json"
    prev.write_text(json.dumps([pooled]), encoding="utf-8")
    curr.write_text(json.dumps([today]), encoding="utf-8")
    return accumulate([prev, curr], max_age_days=30)


def test_a_pooled_event_takes_the_opens_of_its_redetected_copy(tmp_path: Path) -> None:
    """The pooled copy predates the rule (no opens) and wins the tie on
    forward length; the re-detection carries the opens of the SAME bars."""
    ts = _ts_days_ago(2)
    old = _event_with_id("BOS", "AAPL", "15m", ts)
    new = _with_opens(old)
    assert "forward_opens" not in old

    for first, second in ((old, new), (new, old)):  # file order must not matter
        merged = _pool_then_today(tmp_path, first, second)
        assert len(merged) == 1
        assert merged[0]["forward_opens"] == new["forward_opens"]


def test_opens_of_different_bars_are_not_taken_over(tmp_path: Path) -> None:
    """An open belongs to a bar. A copy whose forward bars differ — other
    timestamps, or the same timestamps with revised closes — cannot lend its
    opens: they would shift or falsify the entry."""
    ts = _ts_days_ago(2)
    old = _event_with_id("BOS", "AAPL", "15m", ts)

    shifted = _with_opens(old)
    shifted["forward_timestamps"] = [t + 900 for t in shifted["forward_timestamps"]]
    assert "forward_opens" not in _pool_then_today(tmp_path, old, shifted)[0]

    revised = _with_opens(old)
    revised["forward_closes"] = [c + 0.01 for c in revised["forward_closes"]]
    assert "forward_opens" not in _pool_then_today(tmp_path, old, revised)[0]

    short = _with_opens(old)
    short["forward_opens"] = short["forward_opens"][:-1]
    assert "forward_opens" not in _pool_then_today(tmp_path, old, short)[0]


def test_a_copy_that_has_opens_keeps_its_own(tmp_path: Path) -> None:
    ts = _ts_days_ago(2)
    mine = _with_opens(_event_with_id("BOS", "AAPL", "15m", ts))
    other = {**mine, "forward_opens": [o + 1.0 for o in mine["forward_opens"]]}
    assert _pool_then_today(tmp_path, mine, other)[0]["forward_opens"] == mine["forward_opens"]


# ---------------------------------------------------------------------------
# Bar grid (ADR-0031, Nachtrag 2026-10-02 III): events of the previous grid
# are different events and never share the pool.
# ---------------------------------------------------------------------------


def _legacy(event: dict) -> dict:
    """The same event as recorded before the grid was corrected: no stamp."""
    return {k: v for k, v in event.items() if k != "bar_grid"}


def test_events_of_another_bar_grid_are_not_pooled(tmp_path: Path) -> None:
    ts = _ts_days_ago(2)
    current = _event_with_id("BOS", "AAPL", "15m", ts)
    unstamped = _legacy(_event_with_id("BOS", "MSFT", "15m", ts))
    named_legacy = {**_event_with_id("BOS", "NVDA", "15m", ts), "bar_grid": LEGACY_BAR_GRID}
    path = tmp_path / "pool.json"
    path.write_text(json.dumps([current, unstamped, named_legacy]), encoding="utf-8")

    merged = accumulate([path], max_age_days=30)

    assert [e["event_id"] for e in merged] == [current["event_id"]]
    assert merged[0]["bar_grid"] == BAR_GRID == "exchange_aligned"


def test_the_same_id_on_both_grids_keeps_the_current_grids_bars(tmp_path: Path) -> None:
    """A break detected on both grids can carry the SAME id — same label, same
    level — while the bars behind it differ by a minute. The pooled copy of
    the old grid must not survive in place of the new one, in either order."""
    ts = _ts_days_ago(2)
    new = _event_with_id("BOS", "AAPL", "15m", ts)
    old = _legacy(new)
    old["forward_closes"] = [c + 0.07 for c in old["forward_closes"]]
    assert old["event_id"] == new["event_id"]

    for first, second in ((old, new), (new, old)):
        merged = _pool_then_today(tmp_path, first, second)
        assert len(merged) == 1
        assert merged[0]["bar_grid"] == BAR_GRID
        assert merged[0]["forward_closes"] == new["forward_closes"]


def test_the_grid_transition_is_not_a_pool_wipe(tmp_path: Path) -> None:
    """First run after the correction: the previous pool holds only old-grid
    events, today's run brings a handful on the new grid. The continuity
    guard compares like with like and lets the pool start over."""
    from scripts.accumulate_family_events import main

    now = time.time()
    previous = [_legacy(_event_with_id("BOS", f"S{i}", "15m", now - 86_400 - i)) for i in range(200)]
    today = [_event_with_id("BOS", f"S{i}", "15m", now - 3_600 - i) for i in range(5)]

    rc = main(_guard_args(tmp_path, prev_events=previous, curr_events=today))

    assert rc == 0
    result = json.loads((tmp_path / "out.json").read_text())
    assert len(result) == 5
    assert {e["bar_grid"] for e in result} == {BAR_GRID}


def test_the_guard_still_refuses_a_shrink_of_current_grid_events(tmp_path: Path) -> None:
    """The like-with-like count must not disarm the guard for the grid in use."""
    from scripts.accumulate_family_events import main

    now = time.time()
    fresh = [_event("BOS", now - 86_400 + i) for i in range(10)]
    aged = [_event("BOS", now - 90 * 86_400 + i) for i in range(90)]
    legacy = [_legacy(_event("SWEEP", now - 86_400 + i)) for i in range(500)]
    rc = main(_guard_args(tmp_path, prev_events=fresh + aged + legacy, curr_events=[]))
    assert rc == 4
    assert not (tmp_path / "out.json").exists()


def test_the_run_says_how_many_events_of_another_grid_it_dropped(tmp_path: Path, capsys) -> None:
    from scripts.accumulate_family_events import main

    now = time.time()
    previous = [_legacy(_event_with_id("BOS", f"S{i}", "15m", now - 86_400 - i)) for i in range(7)]
    today = [_event_with_id("BOS", "AAPL", "15m", now - 3_600)]
    assert main(_guard_args(tmp_path, prev_events=previous, curr_events=today)) == 0
    assert "dropped 7 input event(s) of another bar grid (pool grid: exchange_aligned)" in capsys.readouterr().err
