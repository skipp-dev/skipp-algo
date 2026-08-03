"""Unit tests for the ADR-0023 Stage-1 shadow-ledger runner."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import run_magnitude_shadow_ledger as shadow


def _result(
    *,
    passes: bool = False,
    min_sample_pass: bool = True,
    auc_floor_pass: bool = True,
    auc_ci_pass: bool = True,
    resolution_pass: bool = True,
    n_oos: int = 100,
    mag_auc: float = 0.58,
) -> dict:
    return {
        "n_oos": n_oos,
        "mag_auc": mag_auc,
        "auc_ci_low": 0.54,
        "baseline_resolution": 0.01,
        "perm_null_p95": 0.005,
        "perm_p_value": 0.02,
        "passes": passes,
        "min_sample_pass": min_sample_pass,
        "auc_floor_pass": auc_floor_pass,
        "auc_ci_pass": auc_ci_pass,
        "resolution_pass": resolution_pass,
    }


def _report(results: dict[str, dict], *, seed: int = 230_022) -> dict:
    return {
        "seed": seed,
        "families_measured": sorted(results),
        "families_passed": sorted(f for f, r in results.items() if r["passes"]),
        "results": results,
    }


# --------------------------------------------------------------------------- #
# classify_family
# --------------------------------------------------------------------------- #
def test_classify_pass() -> None:
    status, reasons = shadow.classify_family(_result(passes=True))
    assert status == "PASS"
    assert reasons == []


def test_classify_inconclusive_takes_priority_over_fail() -> None:
    # Too-thin sample is inconclusive even if other sub-checks also fail.
    status, reasons = shadow.classify_family(
        _result(min_sample_pass=False, auc_floor_pass=False)
    )
    assert status == "INCONCLUSIVE"
    assert reasons == ["n_oos_below_min"]


def test_classify_fail_collects_all_reasons() -> None:
    status, reasons = shadow.classify_family(
        _result(
            passes=False,
            auc_floor_pass=False,
            auc_ci_pass=False,
            resolution_pass=False,
        )
    )
    assert status == "FAIL"
    assert reasons == ["auc_floor", "auc_ci", "resolution_null"]


# --------------------------------------------------------------------------- #
# build_ledger_rows
# --------------------------------------------------------------------------- #
def test_build_rows_tags_roles_and_sorts() -> None:
    report = _report(
        {
            "OB": _result(),
            "BOS": _result(passes=True, mag_auc=0.62),
            "FVG": _result(),
            "SWEEP": _result(passes=True, mag_auc=0.66),
        }
    )
    rows = shadow.build_ledger_rows(report, date="2026-06-06", events_hash="abc")
    assert [r["family"] for r in rows] == ["BOS", "FVG", "OB", "SWEEP"]
    roles = {r["family"]: r["role"] for r in rows}
    assert roles == {
        "BOS": "candidate",
        "SWEEP": "candidate",
        "FVG": "control",
        "OB": "control",
    }
    bos = next(r for r in rows if r["family"] == "BOS")
    assert bos["status"] == "PASS"
    assert bos["passes"] is True
    assert bos["magnitude_auc"] == 0.62
    assert bos["seed"] == 230_022
    assert set(bos) == set(shadow.LEDGER_COLUMNS)


def test_build_rows_stamp_measurement_plane() -> None:
    """Rows record the plane their events were graded on (None when the
    caller cannot derive one). BOS@15m and BOS@1D are different experiments
    — the plane column is what keeps them distinguishable in the ledger."""
    report = _report({"BOS": _result(passes=True, mag_auc=0.62)})
    stamped = shadow.build_ledger_rows(
        report, date="2026-07-06", events_hash="abc", plane="1D"
    )
    assert stamped[0]["plane"] == "1D"
    unstamped = shadow.build_ledger_rows(
        report, date="2026-07-06", events_hash="abc"
    )
    assert unstamped[0]["plane"] is None
    assert set(stamped[0]) == set(shadow.LEDGER_COLUMNS)


# --------------------------------------------------------------------------- #
# build_heartbeat_rows (fresh-but-thin day)
# --------------------------------------------------------------------------- #
def _triggered_event(family: str, anchor_ts: float, n_forward: int = 10) -> dict:
    """An immediate-entry event that yields a triggered return + score."""
    closes = [100.0 + i for i in range(n_forward)]
    return {
        "family": family,
        "anchor_ts": anchor_ts,
        "direction": "UP",
        "entry_mode": "immediate",
        "entry_price": 100.0,
        "score": 1.5,
        "forward_closes": closes,
        "forward_highs": [c + 1 for c in closes],
        "forward_lows": [c - 1 for c in closes],
        "forward_timestamps": [anchor_ts + (i + 1) * 86_400 for i in range(n_forward)],
    }


def test_heartbeat_rows_one_inconclusive_per_family() -> None:
    events = [
        _triggered_event("BOS", 1_780_000_000.0),
        _triggered_event("BOS", 1_780_100_000.0),
        _triggered_event("SWEEP", 1_780_200_000.0),
    ]
    rows = shadow.build_heartbeat_rows(
        events, date="2026-07-06", events_hash="h", plane="1D", cost_bps=5.0
    )
    # One row per family, all four families present, all INCONCLUSIVE.
    assert [r["family"] for r in rows] == list(shadow.ALL_FAMILIES)
    assert all(r["status"] == "INCONCLUSIVE" for r in rows)
    assert all(r["fail_reasons"] == ["all_thin"] for r in rows)
    assert all(r["passes"] is False for r in rows)
    assert all(r["plane"] == "1D" for r in rows)
    # n_oos carries the per-family usable (score + triggered return) count.
    by_fam = {r["family"]: r["n_oos"] for r in rows}
    assert by_fam["BOS"] == 2
    assert by_fam["SWEEP"] == 1
    assert by_fam["OB"] == 0
    # Schema parity with measured rows.
    assert set(rows[0]) == set(shadow.LEDGER_COLUMNS)


def test_heartbeat_rows_roles_match_candidate_set() -> None:
    rows = shadow.build_heartbeat_rows(
        [], date="2026-07-06", events_hash="h", plane="1D", cost_bps=5.0
    )
    roles = {r["family"]: r["role"] for r in rows}
    assert roles == {
        "BOS": "candidate",
        "SWEEP": "candidate",
        "OB": "control",
        "FVG": "control",
    }
    assert all(r["n_oos"] == 0 for r in rows)


def test_main_thin_feed_appends_heartbeat_and_advances_ledger(tmp_path, capsys) -> None:
    """Regression: a fresh-but-thin feed must ADVANCE the committed ledger
    (heartbeat rows) instead of appending nothing and freezing it — the
    behaviour that made the gap guard fire red every day in 2026-07."""
    events = [_triggered_event("BOS", 1_780_000_000.0 + i * 90_000) for i in range(3)]
    events_path = tmp_path / "events.json"
    events_path.write_text(json.dumps(events))
    ledger = tmp_path / "shadow_1d.jsonl"
    rc = shadow.main([str(events_path), "--ledger", str(ledger), "--date", "2026-07-06"])
    assert rc == 3  # all_thin verdict code is unchanged...
    rows = [json.loads(ln) for ln in ledger.read_text().splitlines() if ln.strip()]
    # ...but the ledger now carries today's heartbeat rows (was: empty).
    assert rows, "the ledger stayed empty — the per-row checks below would pass vacuously"
    assert {r["family"] for r in rows} == set(shadow.ALL_FAMILIES)
    assert all(r["date"] == "2026-07-06" for r in rows)
    assert all(r["status"] == "INCONCLUSIVE" for r in rows)


def test_main_stale_feed_still_appends_nothing(tmp_path, capsys) -> None:
    """W7-2: a re-served frozen feed (same events_hash, earlier date) must
    STILL return rc=5 and NOT heartbeat — a genuinely stalled pipeline has to
    keep the gap guard escalating."""
    events = [_triggered_event("BOS", 1_780_000_000.0)]
    events_path = tmp_path / "events.json"
    events_path.write_text(json.dumps(events))
    ledger = tmp_path / "shadow_1d.jsonl"
    # Seed the ledger with the same events_hash under an EARLIER date.
    ehash = shadow.events_content_hash(events)
    seed_row = {**shadow.build_heartbeat_rows(events, date="2026-07-01", events_hash=ehash, plane="1D", cost_bps=5.0)[0]}
    ledger.write_text(json.dumps(seed_row, sort_keys=True) + "\n")
    rc = shadow.main([str(events_path), "--ledger", str(ledger), "--date", "2026-07-06"])
    assert rc == 5
    rows = [json.loads(ln) for ln in ledger.read_text().splitlines() if ln.strip()]
    # No 2026-07-06 row was appended — the frozen feed does not advance the
    # ledger. Pinning the seed row's survival keeps the check below from
    # passing over an empty file, which would look identical.
    assert len(rows) == 1
    assert all(r["date"] != "2026-07-06" for r in rows)


# --------------------------------------------------------------------------- #
# derive_measurement_plane
# --------------------------------------------------------------------------- #
def _plane_event(bar_seconds: float, n_forward: int = 4) -> dict:
    anchor = 1_780_000_000.0
    return {
        "family": "BOS",
        "anchor_ts": anchor,
        "forward_timestamps": [
            anchor + (i + 1) * bar_seconds for i in range(n_forward)
        ],
    }


def test_derive_plane_labels_daily_and_intraday() -> None:
    assert shadow.derive_measurement_plane([_plane_event(86_400.0)]) == "1D"
    assert shadow.derive_measurement_plane([_plane_event(900.0)]) == "15m"


def test_derive_plane_mode_survives_weekend_gaps() -> None:
    """Weekend gaps (3-day intervals) are rarer than the in-session cadence
    and must not flip the modal label."""
    daily = [_plane_event(86_400.0, n_forward=6) for _ in range(5)]
    weekend = _plane_event(86_400.0, n_forward=6)
    weekend["forward_timestamps"][3] += 2 * 86_400.0  # one Fri->Mon gap
    assert shadow.derive_measurement_plane([*daily, weekend]) == "1D"


def test_derive_plane_unknown_interval_renders_seconds() -> None:
    assert shadow.derive_measurement_plane([_plane_event(1234.0)]) == "1234s"


def test_derive_plane_empty_or_unusable_is_none() -> None:
    assert shadow.derive_measurement_plane([]) is None
    assert shadow.derive_measurement_plane([{"forward_timestamps": []}]) is None


# --------------------------------------------------------------------------- #
# load_ledger / merge_rows
# --------------------------------------------------------------------------- #
def test_load_ledger_missing_file_is_empty(tmp_path: Path) -> None:
    assert shadow.load_ledger(str(tmp_path / "nope.jsonl")) == []


def test_load_ledger_raises_on_malformed_line(tmp_path: Path) -> None:
    """W7-1: malformed lines fail CLOSED (ValueError with path:lineno).

    Silently skipping them was fail-open in three decision-bearing
    consumers at once: corrupt rows could flip the weekly k-of-n majority,
    keep an armed family's demotion window permanently partial, and let
    yesterday's PASS row mask today's corrupt FAIL in the gate wiring.
    """
    path = tmp_path / "led.jsonl"
    path.write_text(
        '{"date": "2026-06-01", "family": "BOS"}\n'
        "not json\n"
        "\n"
        '{"date": "2026-06-02", "family": "SWEEP"}\n',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match=r"led\.jsonl:2"):
        shadow.load_ledger(str(path))


def test_load_ledger_unreadable_file_raises_value_error(tmp_path: Path) -> None:
    """Review follow-up (W7-1): an EXISTING but unreadable ledger (here: a
    directory) is not a cold-start — it must raise the same ValueError the
    consumers map to rc 1, not propagate a raw OSError stacktrace."""
    path = tmp_path / "led.jsonl"
    path.mkdir()
    with pytest.raises(ValueError, match="unreadable ledger"):
        shadow.load_ledger(str(path))


def test_load_ledger_raises_on_non_object_line(tmp_path: Path) -> None:
    """W7-1: a parseable-but-non-object line (e.g. a bare list) is just as
    corrupt as unparseable JSON and must not be silently dropped."""
    path = tmp_path / "led.jsonl"
    path.write_text(
        '{"date": "2026-06-01", "family": "BOS"}\n[1, 2, 3]\n',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match=r"led\.jsonl:2"):
        shadow.load_ledger(str(path))


def test_load_ledger_tolerates_blank_lines(tmp_path: Path) -> None:
    path = tmp_path / "led.jsonl"
    path.write_text(
        '{"date": "2026-06-01", "family": "BOS"}\n'
        "\n"
        '{"date": "2026-06-02", "family": "SWEEP"}\n',
        encoding="utf-8",
    )
    rows = shadow.load_ledger(str(path))
    assert [r["family"] for r in rows] == ["BOS", "SWEEP"]


def test_merge_idempotent_on_date_family_hash() -> None:
    old = {"date": "2026-06-06", "family": "BOS", "events_hash": "h1", "status": "FAIL"}
    new = {"date": "2026-06-06", "family": "BOS", "events_hash": "h1", "status": "PASS"}
    merged = shadow.merge_rows([old], [new])
    assert len(merged) == 1
    assert merged[0]["status"] == "PASS"  # latest wins


def test_merge_keeps_distinct_keys_sorted() -> None:
    rows = shadow.merge_rows(
        [{"date": "2026-06-06", "family": "SWEEP", "events_hash": "h"}],
        [
            {"date": "2026-06-06", "family": "BOS", "events_hash": "h"},
            {"date": "2026-06-05", "family": "OB", "events_hash": "h"},
        ],
    )
    assert [(r["date"], r["family"]) for r in rows] == [
        ("2026-06-05", "OB"),
        ("2026-06-06", "BOS"),
        ("2026-06-06", "SWEEP"),
    ]


def test_merge_different_hash_same_day_keeps_both() -> None:
    rows = shadow.merge_rows(
        [{"date": "2026-06-06", "family": "BOS", "events_hash": "h1"}],
        [{"date": "2026-06-06", "family": "BOS", "events_hash": "h2"}],
    )
    assert len(rows) == 2


# --------------------------------------------------------------------------- #
# events_content_hash
# --------------------------------------------------------------------------- #
def test_events_hash_is_stable_and_order_sensitive() -> None:
    a = [{"family": "BOS", "x": 1}, {"family": "SWEEP", "x": 2}]
    assert shadow.events_content_hash(a) == shadow.events_content_hash(list(a))
    assert shadow.events_content_hash(a) != shadow.events_content_hash(a[::-1])


# --------------------------------------------------------------------------- #
# append_shadow_ledger
# --------------------------------------------------------------------------- #
def test_append_writes_and_is_idempotent(tmp_path: Path) -> None:
    ledger = str(tmp_path / "gov" / "shadow.jsonl")
    report = _report(
        {"BOS": _result(passes=True), "FVG": _result()}
    )
    first = shadow.append_shadow_ledger(
        report, ledger_path=ledger, date="2026-06-06", events_hash="h1"
    )
    assert {r["family"] for r in first} == {"BOS", "FVG"}

    on_disk = shadow.load_ledger(ledger)
    assert len(on_disk) == 2

    # Re-running the same day/data must not duplicate rows.
    shadow.append_shadow_ledger(
        report, ledger_path=ledger, date="2026-06-06", events_hash="h1"
    )
    assert len(shadow.load_ledger(ledger)) == 2

    # A new day appends without dropping history.
    shadow.append_shadow_ledger(
        report, ledger_path=ledger, date="2026-06-07", events_hash="h2"
    )
    rows = shadow.load_ledger(ledger)
    assert len(rows) == 4
    assert {r["date"] for r in rows} == {"2026-06-06", "2026-06-07"}


def test_append_emits_valid_jsonl(tmp_path: Path) -> None:
    ledger = tmp_path / "shadow.jsonl"
    shadow.append_shadow_ledger(
        _report({"BOS": _result(passes=True)}),
        ledger_path=str(ledger),
        date="2026-06-06",
        events_hash="h1",
    )
    for line in ledger.read_text(encoding="utf-8").splitlines():
        json.loads(line)  # must not raise


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #
def test_main_writes_ledger_and_returns_exit_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    events_path = tmp_path / "events.json"
    events_path.write_text(json.dumps([{"family": "BOS", "x": 1}]), encoding="utf-8")
    ledger = tmp_path / "shadow.jsonl"

    monkeypatch.setattr(
        shadow,
        "build_report",
        lambda events, **kw: _report({"BOS": _result(passes=True)}),
    )
    code = shadow.main(
        [str(events_path), "--ledger", str(ledger), "--date", "2026-06-06"]
    )
    assert code == 0
    rows = shadow.load_ledger(str(ledger))
    assert [r["family"] for r in rows] == ["BOS"]
    assert rows[0]["status"] == "PASS"


def test_main_corrupt_existing_ledger_is_usage_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    """W7-1: the runner must refuse to merge/rewrite on top of a corrupt
    ledger (rc 1) — the atomic rewrite would otherwise silently drop the
    unparseable history lines for good."""
    events_path = tmp_path / "events.json"
    events_path.write_text(json.dumps([{"family": "BOS", "x": 1}]), encoding="utf-8")
    ledger = tmp_path / "shadow.jsonl"
    corrupt = '{"date": "2026-06-05", "family": "BOS"}\nnot json\n'
    ledger.write_text(corrupt, encoding="utf-8")

    monkeypatch.setattr(
        shadow,
        "build_report",
        lambda events, **kw: _report({"BOS": _result(passes=True)}),
    )
    code = shadow.main(
        [str(events_path), "--ledger", str(ledger), "--date", "2026-06-06"]
    )
    assert code == 1
    assert "malformed ledger line" in capsys.readouterr().err
    # The corrupt ledger is left untouched — nothing was rewritten.
    assert ledger.read_text(encoding="utf-8") == corrupt


def test_main_empty_events_is_usage_error(tmp_path: Path) -> None:
    events_path = tmp_path / "events.json"
    events_path.write_text("[]", encoding="utf-8")
    assert shadow.main([str(events_path), "--ledger", str(tmp_path / "l.jsonl")]) == 1


def test_main_stale_feed_same_hash_earlier_date_returns_5(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    """W7-2: the same events content (identical ``events_hash``) already
    graded under an EARLIER date means the feed is frozen — re-grading it
    under today's date would manufacture an independent daily vote out of
    zero new evidence. The runner must refuse to append (rc 5) without
    even spending the bootstrap/permutation compute."""
    events = [{"family": "BOS", "x": 1}]
    events_path = tmp_path / "events.json"
    events_path.write_text(json.dumps(events), encoding="utf-8")
    ledger = tmp_path / "shadow.jsonl"
    stale_row = {
        "date": "2026-06-05",
        "family": "BOS",
        "status": "PASS",
        "events_hash": shadow.events_content_hash(events),
    }
    ledger.write_text(json.dumps(stale_row) + "\n", encoding="utf-8")
    before = ledger.read_text(encoding="utf-8")

    def _boom(*args: object, **kwargs: object) -> dict:
        raise AssertionError("build_report must not run on a stale feed")

    monkeypatch.setattr(shadow, "build_report", _boom)
    code = shadow.main(
        [str(events_path), "--ledger", str(ledger), "--date", "2026-06-06"]
    )
    assert code == 5
    err = capsys.readouterr().err
    assert "stale events feed" in err
    assert "2026-06-05" in err
    # Nothing appended, nothing rewritten.
    assert ledger.read_text(encoding="utf-8") == before


def test_main_same_date_same_hash_rerun_is_idempotent_not_stale(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """W7-2 boundary: a same-day re-run with the same hash is the normal
    idempotent merge (same merge key) — it must stay rc 0, not rc 5."""
    events_path = tmp_path / "events.json"
    events_path.write_text(json.dumps([{"family": "BOS", "x": 1}]), encoding="utf-8")
    ledger = tmp_path / "shadow.jsonl"
    monkeypatch.setattr(
        shadow,
        "build_report",
        lambda events, **kw: _report({"BOS": _result(passes=True)}),
    )
    args = [str(events_path), "--ledger", str(ledger), "--date", "2026-06-06"]
    assert shadow.main(args) == 0
    assert shadow.main(args) == 0
    assert len(shadow.load_ledger(str(ledger))) == 1


def test_main_backfill_onto_earlier_date_is_not_stale(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """W7-2 boundary (review follow-up): the stale-feed guard only fires on
    hashes graded under an EARLIER date. A backfill that re-grades the same
    events under a date BEFORE the existing row is a deliberate re-run of
    history, not a frozen feed — it must append normally (rc 0)."""
    events = [{"family": "BOS", "x": 1}]
    events_path = tmp_path / "events.json"
    events_path.write_text(json.dumps(events), encoding="utf-8")
    ledger = tmp_path / "shadow.jsonl"
    later_row = {
        "date": "2026-06-10",
        "family": "BOS",
        "status": "PASS",
        "events_hash": shadow.events_content_hash(events),
    }
    ledger.write_text(json.dumps(later_row) + "\n", encoding="utf-8")
    monkeypatch.setattr(
        shadow,
        "build_report",
        lambda events, **kw: _report({"BOS": _result(passes=True)}),
    )
    code = shadow.main(
        [str(events_path), "--ledger", str(ledger), "--date", "2026-06-06"]
    )
    assert code == 0
    assert {r["date"] for r in shadow.load_ledger(str(ledger))} == {
        "2026-06-06",
        "2026-06-10",
    }


def test_main_malformed_date_is_usage_error_not_verdict(tmp_path: Path) -> None:
    """A bad --date must exit 1 (error), NOT reach the ledger: downstream
    consumers compare parsed dates and a malformed value would silently
    drop out of latest-row selection. Exit 2/3 are reserved for verdicts.
    """
    events_path = tmp_path / "events.json"
    events_path.write_text(json.dumps([{"family": "BOS", "x": 1}]), encoding="utf-8")
    ledger = tmp_path / "shadow.jsonl"
    code = shadow.main(
        [str(events_path), "--ledger", str(ledger), "--date", "06.06.2026"]
    )
    assert code == 1
    assert not ledger.exists()


# --------------------------------------------------------------------------- #
# --plane governed-plane filter (issue #3872)
# --------------------------------------------------------------------------- #
def _intraday_event(family: str, anchor_ts: float, bar_seconds: float = 300.0) -> dict:
    event = _triggered_event(family, anchor_ts)
    event["forward_timestamps"] = [
        anchor_ts + (i + 1) * bar_seconds for i in range(10)
    ]
    return event


def test_event_measurement_plane_is_per_event() -> None:
    assert shadow.event_measurement_plane(_triggered_event("BOS", 1_780_000_000.0)) == "1D"
    assert shadow.event_measurement_plane(_intraday_event("BOS", 1_780_000_000.0)) == "5m"
    assert shadow.event_measurement_plane({"family": "BOS"}) is None


def test_main_plane_filter_grades_only_governed_plane_events(tmp_path) -> None:
    """A 5m-dominated pool must not flip the ledger's plane (2026-07-16..21):
    with --plane 1D only 1D-cadence events are graded, the row's events_hash
    is the FILTERED evidence hash, and the plane column stays 1D even though
    the pool's modal cadence is 5m."""
    one_d = [_triggered_event("BOS", 1_780_000_000.0 + i * 90_000) for i in range(3)]
    pool = one_d + [
        _intraday_event("BOS", 1_781_000_000.0 + i * 4_000) for i in range(20)
    ]
    events_path = tmp_path / "events.json"
    events_path.write_text(json.dumps(pool))
    ledger = tmp_path / "shadow_1d.jsonl"
    rc = shadow.main(
        [str(events_path), "--ledger", str(ledger), "--date", "2026-07-22", "--plane", "1D"]
    )
    assert rc == 3  # thin 1D subset -> all_thin heartbeat, a valid verdict
    rows = [json.loads(ln) for ln in ledger.read_text().splitlines() if ln.strip()]
    assert rows, "the ledger stayed empty — the per-row checks below would pass vacuously"
    assert {r["plane"] for r in rows} == {"1D"}
    # The graded evidence is exactly the 1D subset, not the raw pool.
    assert {r["events_hash"] for r in rows} == {shadow.events_content_hash(one_d)}
    assert all(r["fail_reasons"] == ["all_thin"] for r in rows)


def test_main_plane_starved_pool_heartbeats_and_stays_single_plane(tmp_path) -> None:
    """Zero governed-plane events (the observed 2026-07-20 pool: 5m..1H, no
    1D) must append plane_starved heartbeats stamped with the GOVERNED plane
    — never grade foreign-cadence evidence, never rc 1."""
    pool = [_intraday_event("BOS", 1_780_000_000.0 + i * 4_000) for i in range(5)]
    events_path = tmp_path / "events.json"
    events_path.write_text(json.dumps(pool))
    ledger = tmp_path / "shadow_1d.jsonl"
    rc = shadow.main(
        [str(events_path), "--ledger", str(ledger), "--date", "2026-07-22", "--plane", "1D"]
    )
    assert rc == 3
    rows = [json.loads(ln) for ln in ledger.read_text().splitlines() if ln.strip()]
    assert rows, "the ledger stayed empty — the per-row checks below would pass vacuously"
    assert {r["family"] for r in rows} == set(shadow.ALL_FAMILIES)
    assert {r["plane"] for r in rows} == {"1D"}
    assert all(r["fail_reasons"] == ["plane_starved"] for r in rows)
    assert all(r["status"] == "INCONCLUSIVE" for r in rows)


def test_main_plane_starved_repeat_is_stale_skip(tmp_path) -> None:
    """Day 2 of an unchanged starved pool must rc-5-skip (empty filtered
    evidence hashes identically), so the ledger freezes and the gap guard —
    not silent heartbeats — escalates a persistent starvation."""
    pool = [_intraday_event("BOS", 1_780_000_000.0 + i * 4_000) for i in range(5)]
    events_path = tmp_path / "events.json"
    events_path.write_text(json.dumps(pool))
    ledger = tmp_path / "shadow_1d.jsonl"
    args = [str(events_path), "--ledger", str(ledger), "--plane", "1D"]
    assert shadow.main([*args, "--date", "2026-07-22"]) == 3
    assert shadow.main([*args, "--date", "2026-07-23"]) == 5
    rows = [json.loads(ln) for ln in ledger.read_text().splitlines() if ln.strip()]
    assert rows, "day 1 appended nothing — the freeze check below would pass vacuously"
    assert all(r["date"] == "2026-07-22" for r in rows)


def test_committed_live_ledger_is_single_plane_1d() -> None:
    """The committed live ledger must never mix planes again (issue #3872):
    a mix wedges the weekly evaluator for days before anyone notices. The
    2026-07-16..21 mixed-pool rows live in the 5m quarantine file, which
    nothing grades."""
    repo = Path(__file__).resolve().parents[1]
    live = repo / "artifacts/governance/magnitude_resolution_shadow.jsonl"
    rows = [json.loads(ln) for ln in live.read_text().splitlines() if ln.strip()]
    assert rows, "live ledger must not be empty"
    assert {r.get("plane") for r in rows} <= {"1D"}
    quarantine = repo / (
        "artifacts/governance/magnitude_resolution_shadow_5m_mixed_quarantine.jsonl"
    )
    qrows = [
        json.loads(ln) for ln in quarantine.read_text().splitlines() if ln.strip()
    ]
    assert {r.get("plane") for r in qrows} == {"5m"}
