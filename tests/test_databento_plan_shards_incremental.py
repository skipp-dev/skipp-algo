"""Option-b cadence — unit tests for incremental scan-window narrowing.

These cover the opt-in ``--last-baked-date`` wiring added to the shard
planner's CLI, which composes the pure ``narrow_scan_window`` helper.
The default code path (flag omitted) must stay byte-for-byte unchanged;
that invariant is asserted directly against ``plan_shards``.
"""

from __future__ import annotations

import importlib.util
import io
import json
import sys
from contextlib import redirect_stderr, redirect_stdout
from datetime import date, timedelta
from pathlib import Path

import pytest

# Load the CLI script as a module without requiring scripts/ on sys.path.
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

_END = "2026-06-08"  # fixed end_date for deterministic windows


def _run_main(args: list[str]) -> tuple[int, str, str]:
    """Invoke ``main`` capturing (rc, stdout, stderr)."""
    out = io.StringIO()
    err = io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        rc = _MOD.main(args)
    return rc, out.getvalue(), err.getvalue()


def _base(*extra: str) -> list[str]:
    return ["--lookback-days", "30", "--num-shards", "6", "--end-date", _END, *extra]


# ---------------------------------------------------------- default path


def test_no_flag_matches_pure_plan_shards():
    """Without --last-baked-date the CLI output equals the pure planner."""
    rc, out, err = _run_main(_base())
    assert rc == 0
    shards = json.loads(out)
    expected = _MOD.plan_shards(
        lookback_days=30, num_shards=6, end_date=date(2026, 6, 8)
    )
    assert shards == expected
    # The default path must not emit the incremental diagnostic.
    assert "incremental:" not in err


def test_no_flag_full_window():
    rc, out, _ = _run_main(_base())
    assert rc == 0
    shards = json.loads(out)
    assert shards[0]["start_date"] == "2026-05-10"  # 30-day trailing window
    assert shards[-1]["end_date"] == _END
    assert len(shards) == 6


# ---------------------------------------------------------- incremental


def test_incremental_narrows_to_elapsed_window():
    rc, out, err = _run_main(_base("--last-baked-date", "2026-05-27"))
    assert rc == 0
    shards = json.loads(out)
    # watermark 2026-05-27, default overlap 1 -> start 2026-05-27.
    assert shards[0]["start_date"] == "2026-05-27"
    assert shards[-1]["end_date"] == _END
    assert len(shards) == 6
    # Narrower than the full 30-day window (which would start 2026-05-10).
    assert shards[0]["start_date"] > "2026-05-10"
    assert "reason=incremental" in err
    assert "effective_lookback_days=13" in err


def test_incremental_clamps_shards_to_small_window():
    rc, out, err = _run_main(_base("--last-baked-date", "2026-06-06"))
    assert rc == 0
    shards = json.loads(out)
    # watermark 2026-06-06, overlap 1 -> [2026-06-06, 2026-06-08] = 3 days.
    assert shards[0]["start_date"] == "2026-06-06"
    assert shards[-1]["end_date"] == _END
    assert len(shards) == 3  # clamped down from the requested 6
    assert all(s["shard_of"] == 3 for s in shards)


def test_incremental_watermark_ahead_floor():
    rc, out, err = _run_main(_base("--last-baked-date", "2026-06-20"))
    assert rc == 0
    shards = json.loads(out)
    assert len(shards) == 1
    assert shards[0]["start_date"] == _END
    assert shards[0]["end_date"] == _END
    assert "reason=watermark_ahead" in err


def test_incremental_cannot_widen_beyond_full_lookback():
    # Watermark far in the past must clamp to the full trailing lookback,
    # never widen the window.
    rc, out, err = _run_main(_base("--last-baked-date", "2026-04-01"))
    assert rc == 0
    shards = json.loads(out)
    assert shards[0]["start_date"] == "2026-05-10"  # == full 30-day start
    assert shards[-1]["end_date"] == _END
    assert len(shards) == 6


def test_incremental_safety_overlap_zero_shifts_start():
    rc, out, _ = _run_main(
        _base("--last-baked-date", "2026-05-27", "--safety-overlap-days", "0")
    )
    assert rc == 0
    shards = json.loads(out)
    # overlap 0 -> start = watermark + 1 = 2026-05-28.
    assert shards[0]["start_date"] == "2026-05-28"
    assert shards[-1]["end_date"] == _END


def test_incremental_min_refresh_floor():
    # Watermark already current -> minimum window honours --min-refresh-days.
    rc, out, _ = _run_main(
        _base("--last-baked-date", _END, "--min-refresh-days", "3")
    )
    assert rc == 0
    shards = json.loads(out)
    start = date.fromisoformat(str(shards[0]["start_date"]))
    end = date.fromisoformat(str(shards[-1]["end_date"]))
    assert (end - start).days + 1 == 3


def test_incremental_window_coverage_is_contiguous_and_complete():
    rc, out, _ = _run_main(_base("--last-baked-date", "2026-05-27"))
    assert rc == 0
    shards = json.loads(out)
    assert shards[0]["start_date"] == "2026-05-27"
    assert shards[-1]["end_date"] == _END
    # Disjoint, contiguous, gap-free coverage of the narrowed closed window.
    for a, b in zip(shards, shards[1:]):
        a_end = date.fromisoformat(str(a["end_date"]))
        b_start = date.fromisoformat(str(b["start_date"]))
        assert b_start == a_end + timedelta(days=1)
    # shard_id is 1-based and monotonically increasing.
    assert [s["shard_id"] for s in shards] == list(range(1, len(shards) + 1))


def test_incremental_emits_window_diagnostic_to_stderr():
    _, _, err = _run_main(_base("--last-baked-date", "2026-05-27"))
    assert "incremental: reason=" in err
    assert "window=2026-05-27..2026-06-08" in err
    assert "(full=30)" in err


@pytest.mark.parametrize("bad", ["not-a-date", "2026-13-01", "2026/05/27"])
def test_bad_last_baked_date_exits_2(bad: str):
    with pytest.raises(SystemExit) as excinfo:
        _run_main(["--lookback-days", "30", "--num-shards", "6", "--last-baked-date", bad])
    assert excinfo.value.code == 2
