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
import sys
from contextlib import redirect_stderr, redirect_stdout
from datetime import date, timedelta
from pathlib import Path

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
