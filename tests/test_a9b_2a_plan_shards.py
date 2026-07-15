"""A9b.2a — unit tests for the shard planner.

The planner is invoked as a CLI in the sharded GHA workflow, but we test
the pure ``plan_shards`` function directly plus a thin CLI smoke test
through ``main`` to catch arg-parsing regressions.
"""

from __future__ import annotations

import importlib.util
import io
import itertools
import json
import re
import subprocess
import sys
from contextlib import redirect_stderr, redirect_stdout
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

# Load the script as a module without requiring scripts/ on sys.path.
# Per /memories/python-testing.md: insert into sys.modules before
# exec_module so any annotation introspection inside the module sees a
# resolved entry.
_SPEC = importlib.util.spec_from_file_location(
    "databento_plan_shards",
    Path(__file__).resolve().parents[1] / "scripts" / "databento_plan_shards.py",
)
assert _SPEC is not None and _SPEC.loader is not None
_MOD = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _MOD


def test_defer_cli_does_not_require_pandas() -> None:
    """The dependency-free plan job must not import the producer's pandas stack."""
    repo_root = Path(__file__).resolve().parents[1]
    blocker = (
        "import builtins,runpy,sys; "
        "real_import=builtins.__import__; "
        "builtins.__import__=lambda name,*a,**kw: "
        "(_ for _ in ()).throw(ModuleNotFoundError(\"pandas blocked\")) "
        "if name == \"pandas\" else real_import(name,*a,**kw); "
        "sys.argv=[\"databento_plan_shards.py\",\"--lookback-days\",\"2\","
        "\"--num-shards\",\"2\",\"--defer-current-day-until-intraday-window\"]; "
        "runpy.run_path(\"scripts/databento_plan_shards.py\",run_name=\"__main__\")"
    )
    completed = subprocess.run(
        [sys.executable, "-c", blocker],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
_SPEC.loader.exec_module(_MOD)


# ---------------------------------------------------------------- plan_shards


def _coverage_invariants(
    shards: list[dict[str, object]],
    *,
    expected_start: date,
    expected_end: date,
    expected_num: int,
) -> None:
    """Assert disjoint, contiguous, complete coverage of the closed window."""
    assert len(shards) == expected_num

    # shard_id is 1-based, monotonically increasing.
    assert [s["shard_id"] for s in shards] == list(range(1, expected_num + 1))
    assert all(s["shard_of"] == expected_num for s in shards)

    # First start, last end match the requested window.
    assert shards[0]["start_date"] == expected_start.isoformat()
    assert shards[-1]["end_date"] == expected_end.isoformat()

    # Each shard spans a positive number of days.
    for s in shards:
        start = date.fromisoformat(str(s["start_date"]))
        end = date.fromisoformat(str(s["end_date"]))
        assert start <= end

    # Contiguous and disjoint: shard[i+1].start == shard[i].end + 1day.
    for prev, nxt in itertools.pairwise(shards):
        prev_end = date.fromisoformat(str(prev["end_date"]))
        nxt_start = date.fromisoformat(str(nxt["start_date"]))
        assert nxt_start - prev_end == timedelta(days=1)

    # Total day-count == expected window size.
    total = sum(
        (
            date.fromisoformat(str(s["end_date"]))
            - date.fromisoformat(str(s["start_date"]))
        ).days
        + 1
        for s in shards
    )
    assert total == (expected_end - expected_start).days + 1


def test_even_split_lookback10_n2() -> None:
    end = date(2026, 5, 8)
    shards = _MOD.plan_shards(lookback_days=10, num_shards=2, end_date=end)
    assert shards == [
        {
            "shard_id": 1,
            "shard_of": 2,
            "start_date": "2026-04-29",
            "end_date": "2026-05-03",
        },
        {
            "shard_id": 2,
            "shard_of": 2,
            "start_date": "2026-05-04",
            "end_date": "2026-05-08",
        },
    ]
    _coverage_invariants(
        shards, expected_start=date(2026, 4, 29), expected_end=end, expected_num=2
    )


def test_uneven_split_lookback10_n3_distributes_remainder_first() -> None:
    """lookback=10, N=3 -> sizes 4,3,3 (remainder placed on the leading shard)."""
    end = date(2026, 5, 8)
    shards = _MOD.plan_shards(lookback_days=10, num_shards=3, end_date=end)
    sizes = [
        (
            date.fromisoformat(str(s["end_date"]))
            - date.fromisoformat(str(s["start_date"]))
        ).days
        + 1
        for s in shards
    ]
    assert sizes == [4, 3, 3]
    _coverage_invariants(
        shards, expected_start=date(2026, 4, 29), expected_end=end, expected_num=3
    )


def test_single_shard_is_full_window() -> None:
    end = date(2026, 5, 8)
    shards = _MOD.plan_shards(lookback_days=30, num_shards=1, end_date=end)
    assert shards == [
        {
            "shard_id": 1,
            "shard_of": 1,
            "start_date": "2026-04-09",
            "end_date": "2026-05-08",
        }
    ]


def test_default_30_into_6_each_5_days() -> None:
    end = date(2026, 5, 8)
    shards = _MOD.plan_shards(lookback_days=30, num_shards=6, end_date=end)
    sizes = [
        (
            date.fromisoformat(str(s["end_date"]))
            - date.fromisoformat(str(s["start_date"]))
        ).days
        + 1
        for s in shards
    ]
    assert sizes == [5, 5, 5, 5, 5, 5]
    _coverage_invariants(
        shards, expected_start=date(2026, 4, 9), expected_end=end, expected_num=6
    )


def test_lookback_below_num_shards_raises() -> None:
    with pytest.raises(ValueError, match=r"--lookback-days \(2\).*--num-shards \(3\)"):
        _MOD.plan_shards(lookback_days=2, num_shards=3, end_date=date(2026, 5, 8))


def test_num_shards_zero_raises() -> None:
    with pytest.raises(ValueError, match=r"--num-shards must be >= 1"):
        _MOD.plan_shards(lookback_days=10, num_shards=0, end_date=date(2026, 5, 8))


def test_num_shards_negative_raises() -> None:
    with pytest.raises(ValueError, match=r"--num-shards must be >= 1"):
        _MOD.plan_shards(lookback_days=10, num_shards=-1, end_date=date(2026, 5, 8))


# ----------------------------------------------------------------------- main


def _run_main(argv: list[str]) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        rc = _MOD.main(argv)
    return rc, out.getvalue(), err.getvalue()


def test_main_emits_valid_json_array() -> None:
    rc, out, _err = _run_main(
        ["--lookback-days", "10", "--num-shards", "2", "--end-date", "2026-05-08"]
    )
    assert rc == 0
    payload = json.loads(out)
    assert isinstance(payload, list) and len(payload) == 2
    assert payload[0]["shard_id"] == 1 and payload[1]["shard_id"] == 2


def test_main_default_end_date_is_today_utc(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_MOD, "_today_utc", lambda: date(2026, 5, 8))
    rc, out, _err = _run_main(["--lookback-days", "10", "--num-shards", "2"])
    assert rc == 0
    payload = json.loads(out)
    assert payload[-1]["end_date"] == "2026-05-08"


def test_main_invalid_args_returns_2_with_stderr() -> None:
    rc, out, err = _run_main(["--lookback-days", "2", "--num-shards", "3"])
    assert rc == 2
    assert out == ""
    assert "must be >=" in err


def test_main_required_args_missing_exits_2_via_argparse() -> None:
    """argparse exits with code 2 when required args are missing."""
    with pytest.raises(SystemExit) as exc:
        _run_main([])
    assert exc.value.code == 2


# -------------------------------------------- weekday-coverage validator (WF-011)


def test_weekday_only_window_emits_no_warning() -> None:
    # Window 2026-05-04 .. 2026-05-08 is Mon-Fri (all weekdays).
    rc, _out, err = _run_main(
        ["--lookback-days", "5", "--num-shards", "5", "--end-date", "2026-05-08"]
    )
    assert rc == 0
    assert "weekend-only" not in err


def test_weekend_only_shard_emits_stderr_warning_but_rc0() -> None:
    # 2026-05-09 is Saturday, 2026-05-10 is Sunday. lookback=2,num=2 gives one
    # 1-day shard per side: Sat (weekend-only) + Sun (weekend-only).
    rc, out, err = _run_main(
        ["--lookback-days", "2", "--num-shards", "2", "--end-date", "2026-05-10"]
    )
    assert rc == 0
    assert out  # still emits the plan
    assert "weekend-only" in err
    assert "shard_ids=[1, 2]" in err


def test_weekend_only_shard_with_require_flag_fails_rc2() -> None:
    rc, out, err = _run_main(
        [
            "--lookback-days", "2", "--num-shards", "2", "--end-date", "2026-05-10",
            "--require-weekday-coverage",
        ]
    )
    assert rc == 2
    assert out == ""
    assert "weekend-only" in err


# ------------------------------------------- --drop-weekend-only-shards (#3645)


def test_drop_weekend_only_shards_reproduces_and_fixes_monday_deadlock() -> None:
    """Regression: the exact plan that deadlocked the export cron 2026-07-13..15.

    The watermark sat on Friday 2026-07-10, so the incremental window
    2026-07-10..2026-07-14 narrowed to 1 calendar day per shard and isolated
    Sat 07-11 and Sun 07-12 into shards 2 and 3. Both resolved to zero trading
    days, so the producer exited 1 and the scheduled run hard-failed on the
    partial merged manifest -- which meant asof_date never advanced past that
    Friday and every later tick replanned the same broken window.
    """
    argv = ["--lookback-days", "5", "--num-shards", "5", "--end-date", "2026-07-14"]
    # Without the flag the weekend shards are still planned (default unchanged).
    rc, out, err = _run_main(argv)
    assert rc == 0
    assert [s["start_date"] for s in json.loads(out)] == [
        "2026-07-10", "2026-07-11", "2026-07-12", "2026-07-13", "2026-07-14",
    ]
    assert "shard_ids=[2, 3]" in err

    rc, out, err = _run_main([*argv, "--drop-weekend-only-shards"])
    assert rc == 0
    payload = json.loads(out)
    # Sat + Sun are gone; only the three trading days survive.
    assert [s["start_date"] for s in payload] == [
        "2026-07-10", "2026-07-13", "2026-07-14",
    ]
    # Renumbered 1..M with a matching shard_of, so the reduce step's
    # `shard_id > expected_shard_count` guard cannot trip.
    assert [s["shard_id"] for s in payload] == [1, 2, 3]
    assert {s["shard_of"] for s in payload} == {3}
    assert "dropped weekend-only shard(s) [2, 3]" in err


def test_drop_weekend_only_shards_is_noop_when_every_shard_has_a_weekday() -> None:
    # 2026-05-04 .. 2026-05-08 is Mon-Fri.
    argv = ["--lookback-days", "5", "--num-shards", "5", "--end-date", "2026-05-08"]
    _rc, baseline, _err = _run_main(argv)
    rc, out, err = _run_main([*argv, "--drop-weekend-only-shards"])
    assert rc == 0
    assert json.loads(out) == json.loads(baseline)
    assert "dropped weekend-only" not in err


def test_drop_weekend_only_shards_all_weekend_emits_empty_matrix() -> None:
    """Every shard weekend-only -> empty matrix.

    The workflow guards both the producer and reduce jobs with
    ``shard_count != '0'``, so an empty plan skips them cleanly instead of
    fanning out shards that are guaranteed to exit 1.
    """
    rc, out, _err = _run_main(
        [
            "--lookback-days", "2", "--num-shards", "2", "--end-date", "2026-05-10",
            "--drop-weekend-only-shards",
        ]
    )
    assert rc == 0
    assert json.loads(out) == []


def test_require_weekday_coverage_takes_precedence_over_drop() -> None:
    rc, out, _err = _run_main(
        [
            "--lookback-days", "2", "--num-shards", "2", "--end-date", "2026-05-10",
            "--require-weekday-coverage", "--drop-weekend-only-shards",
        ]
    )
    assert rc == 2
    assert out == ""


def test_drop_weekend_only_shards_keeps_every_weekday_covered() -> None:
    """Dropping must not lose coverage: every weekday stays inside some shard."""
    argv = ["--lookback-days", "30", "--num-shards", "20", "--end-date", "2026-07-14"]
    _rc, baseline, _err = _run_main(argv)
    rc, out, _err = _run_main([*argv, "--drop-weekend-only-shards"])
    assert rc == 0

    def _weekdays(payload: str) -> set[date]:
        days: set[date] = set()
        for shard in json.loads(payload):
            cur = date.fromisoformat(str(shard["start_date"]))
            end = date.fromisoformat(str(shard["end_date"]))
            while cur <= end:
                if cur.weekday() < 5:
                    days.add(cur)
                cur += timedelta(days=1)
        return days

    assert _weekdays(out) == _weekdays(baseline)


# ------------------------- --defer-current-day-until-intraday-window (#3649)

_ET = ZoneInfo("America/New_York")


def _pin_clock(monkeypatch: pytest.MonkeyPatch, now_et: datetime) -> None:
    """Pin both clocks the planner reads.

    ``_today_utc`` feeds the default end date, ``_now_et`` feeds the cap. The
    crons never run late enough ET for the two dates to diverge, so pinning
    ``_today_utc`` to the ET date mirrors production.
    """
    monkeypatch.setattr(_MOD, "_now_et", lambda: now_et)
    monkeypatch.setattr(_MOD, "_today_utc", lambda: now_et.date())


def test_defer_before_window_excludes_current_day(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Tue 2026-07-14 at 08:20 ET — the 12:00 UTC tick in summer. Pre-window.
    _pin_clock(monkeypatch, datetime(2026, 7, 14, 8, 20, tzinfo=_ET))
    rc, out, err = _run_main(
        [
            "--lookback-days", "2", "--num-shards", "2",
            "--defer-current-day-until-intraday-window",
        ]
    )
    assert rc == 0
    ends = [s["end_date"] for s in json.loads(out)]
    assert "2026-07-14" not in ends
    assert max(ends) == "2026-07-13"
    assert "capping end date 2026-07-14 -> 2026-07-13" in err


def test_defer_at_exactly_window_start_still_excludes_current_day(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Boundary is STRICT: the producer bails on ``we <= ws``, so 09:20:00 is out.

    Including the current day here would plan a shard the producer then raises
    on — the exact failure #3649 is about.
    """
    _pin_clock(monkeypatch, datetime(2026, 7, 14, 9, 20, 0, tzinfo=_ET))
    rc, out, _err = _run_main(
        [
            "--lookback-days", "2", "--num-shards", "2",
            "--defer-current-day-until-intraday-window",
        ]
    )
    assert rc == 0
    assert "2026-07-14" not in [s["end_date"] for s in json.loads(out)]


def test_defer_just_after_window_start_includes_current_day(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _pin_clock(monkeypatch, datetime(2026, 7, 14, 9, 20, 1, tzinfo=_ET))
    rc, out, err = _run_main(
        [
            "--lookback-days", "2", "--num-shards", "2",
            "--defer-current-day-until-intraday-window",
        ]
    )
    assert rc == 0
    assert max(s["end_date"] for s in json.loads(out)) == "2026-07-14"
    assert "capping end date" not in err


def test_defer_trims_multiday_shard_rather_than_dropping_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A Mon..Tue shard must lose only Tue — Monday's coverage stays."""
    _pin_clock(monkeypatch, datetime(2026, 7, 14, 4, 0, tzinfo=_ET))
    rc, out, _err = _run_main(
        [
            "--lookback-days", "4", "--num-shards", "2",
            "--defer-current-day-until-intraday-window",
        ]
    )
    assert rc == 0
    payload = json.loads(out)
    # --lookback-days is a width relative to the end date, so capping the end to
    # Mon 07-13 shifts the whole 4-day window to 07-10..07-13 (still 4 days).
    assert payload[0]["start_date"] == "2026-07-10"
    assert payload[-1]["end_date"] == "2026-07-13"
    # The last shard is Sun..Mon: Monday is trimmed down to, not dropped with,
    # the deferred Tuesday.
    assert payload[-1]["start_date"] == "2026-07-12"


def test_defer_monday_pre_window_caps_to_sunday_and_weekend_filter_applies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Mon pre-window + a Friday watermark: cap to Sun, then weekend-drop."""
    _pin_clock(monkeypatch, datetime(2026, 7, 13, 4, 0, tzinfo=_ET))
    rc, out, _err = _run_main(
        [
            "--lookback-days", "3", "--num-shards", "3",
            "--defer-current-day-until-intraday-window",
            "--drop-weekend-only-shards",
        ]
    )
    assert rc == 0
    # Window 07-11..07-13 caps to 07-10..07-12 (Fri/Sat/Sun); Sat+Sun are
    # weekend-only and get dropped, leaving the Friday safety-overlap shard.
    payload = json.loads(out)
    assert [s["start_date"] for s in payload] == ["2026-07-10"]
    assert payload[0]["shard_of"] == 1


def test_defer_leaves_explicit_historical_end_date_untouched(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _pin_clock(monkeypatch, datetime(2026, 7, 14, 4, 0, tzinfo=_ET))
    argv = ["--lookback-days", "5", "--num-shards", "5", "--end-date", "2026-05-08"]
    _rc, baseline, _err = _run_main(argv)
    rc, out, err = _run_main([*argv, "--defer-current-day-until-intraday-window"])
    assert rc == 0
    assert json.loads(out) == json.loads(baseline)
    assert "capping end date" not in err


def test_defer_flag_absent_leaves_planner_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Default path stays byte-compatible even mid-pre-market."""
    _pin_clock(monkeypatch, datetime(2026, 7, 14, 4, 0, tzinfo=_ET))
    rc, out, err = _run_main(["--lookback-days", "2", "--num-shards", "2"])
    assert rc == 0
    assert max(s["end_date"] for s in json.loads(out)) == "2026-07-14"
    assert "capping end date" not in err


def test_defer_caps_incremental_window_before_narrowing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The cap must land BEFORE narrow_scan_window, not after.

    Reproduces the steady state #3649 predicts once the watermark is current:
    watermark on Mon, tick on Tue pre-window -> without the cap the 2-day window
    narrows to a 1-day-per-shard split that isolates Tue.
    """
    _pin_clock(monkeypatch, datetime(2026, 7, 14, 8, 0, tzinfo=_ET))
    argv = [
        "--lookback-days", "30", "--num-shards", "6",
        "--last-baked-date", "2026-07-13",
    ]
    _rc, baseline, _err = _run_main(argv)
    assert "2026-07-14" in [s["end_date"] for s in json.loads(baseline)]

    rc, out, err = _run_main([*argv, "--defer-current-day-until-intraday-window"])
    assert rc == 0
    payload = json.loads(out)
    assert "2026-07-14" not in [s["end_date"] for s in payload]
    assert "window=2026-07-13..2026-07-13" in err


def test_planner_window_start_matches_producer_bridge() -> None:
    """Contract: planner cap time == producer FMP-bridge window start.

    The producer mirrors the pre-open constant locally instead of importing the
    SSOT. If that mirror drifts, the planner would defer on a different boundary
    than the producer enforces and #3649 would silently come back.
    """
    session = pytest.importorskip("databento_session")
    ws = _MOD._intraday_window_start_et(session.DEFAULT_INTRADAY_PRE_OPEN_MINUTES)
    assert ws == time(9, 20)

    producer = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "databento_production_export.py"
    ).read_text()
    assert "_market_open_et = time(9, 30)" in producer, (
        "producer market open moved; update _MARKET_OPEN_ET in databento_plan_shards.py"
    )
    mirror = re.search(r"_pre_open_minutes = (\d+)\s*#\s*mirrors", producer)
    assert mirror is not None, "producer's pre-open mirror line not found"
    assert int(mirror.group(1)) == session.DEFAULT_INTRADAY_PRE_OPEN_MINUTES, (
        "producer's _pre_open_minutes mirror drifted from "
        "databento_session.DEFAULT_INTRADAY_PRE_OPEN_MINUTES"
    )
    planner_market_open = _MOD._MARKET_OPEN_ET
    assert planner_market_open == time(9, 30)


# --------------------------------------------------------------- workflow YAML

# Module-level constant kept here so the orphan-inventory guard
# (tests/test_workflow_orphan_inventory.py) sees the basename reference.
_SHARDED_WORKFLOW_BASENAME = "smc-databento-production-export-sharded"


def test_sharded_workflow_yaml_keeps_dispatch_inputs() -> None:
    """workflow_dispatch must remain available across probe/cutover phases.

    The sharded producer graduated from dispatch-only to scheduled probe/
    live-cron phases, but manual dispatch remains part of the operational
    contract for ad-hoc recovery and smoke runs. The trigger surface is
    therefore limited to ``workflow_dispatch`` plus optional ``schedule``.
    """
    yaml = pytest.importorskip("yaml")
    path = (
        Path(__file__).resolve().parents[1]
        / ".github"
        / "workflows"
        / f"{_SHARDED_WORKFLOW_BASENAME}.yml"
    )
    assert path.exists(), f"Expected sharded workflow at {path}"
    doc = yaml.safe_load(path.read_text())
    # PyYAML parses bare `on:` keys as the boolean True.
    on_key = True if True in doc else "on"
    triggers = doc[on_key]
    assert isinstance(triggers, dict)
    assert "workflow_dispatch" in triggers, (
        f"sharded workflow must keep workflow_dispatch; got {list(triggers.keys())}"
    )
    assert set(triggers.keys()).issubset({"workflow_dispatch", "schedule"}), (
        f"sharded workflow may only expose workflow_dispatch plus optional schedule; "
        f"got {list(triggers.keys())}"
    )
    inputs = triggers["workflow_dispatch"].get("inputs") or {}
    assert "lookback_days" in inputs
    assert "num_shards" in inputs


def test_sharded_workflow_plan_job_invokes_planner_script() -> None:
    """A9b.2a wiring: the plan-job must call scripts/databento_plan_shards.py."""
    path = (
        Path(__file__).resolve().parents[1]
        / ".github"
        / "workflows"
        / f"{_SHARDED_WORKFLOW_BASENAME}.yml"
    )
    text = path.read_text()
    assert "scripts/databento_plan_shards.py" in text
    assert "a9b-2a-shard-plan" in text  # artifact name pin


def test_sharded_workflow_plan_job_drops_weekend_only_shards() -> None:
    """Every planner invocation must pass --drop-weekend-only-shards (#3645).

    Without it the incremental path re-enters the Monday deadlock: the Friday
    watermark puts Sat/Sun in the window, they narrow into their own shards,
    the producer exits 1 on them, the scheduled run fails on the partial merged
    manifest, and asof_date never advances to replan a healthy window.
    """
    path = (
        Path(__file__).resolve().parents[1]
        / ".github"
        / "workflows"
        / f"{_SHARDED_WORKFLOW_BASENAME}.yml"
    )
    text = path.read_text()
    invocations = text.count("scripts/databento_plan_shards.py \\")
    assert invocations == 3, (
        f"expected 3 planner invocations (preview + incremental + full-lookback); "
        f"got {invocations} — update this pin if the plan job was restructured"
    )
    # Count the flag only where it is an actual argument on its own
    # continuation line, so prose mentioning it does not satisfy the pin.
    flag_args = [
        line for line in text.splitlines()
        if line.strip() in {"--drop-weekend-only-shards \\", "--drop-weekend-only-shards"}
    ]
    assert len(flag_args) == invocations, (
        f"every databento_plan_shards.py invocation in the plan job must pass "
        f"--drop-weekend-only-shards; found {len(flag_args)} for {invocations} "
        f"invocations"
    )


def test_sharded_workflow_plan_job_defers_current_day() -> None:
    """Every planner invocation must pass the current-day deferral (#3649).

    Without it the early ticks (08:00/10:00/12:00 UTC = 04:00/06:00/08:00 ET in
    summer) plan a shard for a day the producer cannot rank yet, which raises
    'No ranked results' and fails the scheduled run on the partial manifest.
    """
    path = (
        Path(__file__).resolve().parents[1]
        / ".github"
        / "workflows"
        / f"{_SHARDED_WORKFLOW_BASENAME}.yml"
    )
    text = path.read_text()
    invocations = text.count("scripts/databento_plan_shards.py \\")
    flag_args = [
        line for line in text.splitlines()
        if line.strip() in {
            "--defer-current-day-until-intraday-window \\",
            "--defer-current-day-until-intraday-window",
        }
    ]
    assert len(flag_args) == invocations, (
        f"every databento_plan_shards.py invocation in the plan job must pass "
        f"--defer-current-day-until-intraday-window; found {len(flag_args)} for "
        f"{invocations} invocations"
    )
