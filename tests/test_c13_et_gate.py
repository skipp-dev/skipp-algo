"""Tests for automation/launchd/lib_c13_et_gate.sh (DST-robust ET gate).

The gate exists because launchd `StartCalendarInterval` fires in the Mac's
LOCAL timezone, but the C13 jobs are scheduled against US market (ET) time. On
a non-ET Mac (e.g. Europe/Berlin) the plists therefore fire at three candidate
local times bracketing the Berlin<->ET offset, and this gate lets exactly one
per ET weekday proceed. Root-caused 2026-07-07 (paper orders placed ~6h early).
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
_LIB = _REPO / "automation" / "launchd" / "lib_c13_et_gate.sh"


def _run_gate(
    tmp_repo: Path,
    now_et: str,
    dow: int,
    thh: str,
    tmm: str,
    tol: str,
    scope: str = "",
) -> int:
    """Invoke the sourced gate with an injected ET clock; return its exit code."""
    script = (
        f'source "{_LIB}"; '
        f'c13_require_et_window "{tmp_repo}" {thh} {tmm} {tol} testjob {scope}'
    )
    proc = subprocess.run(
        ["bash", "-c", script],
        env={
            "PATH": "/usr/bin:/bin",
            "C13_GATE_NOW_ET": now_et,
            "C13_GATE_NOW_DOW": str(dow),
        },
        capture_output=True,
        text=True,
    )
    return proc.returncode


def test_gate_passes_inside_window(tmp_path: Path) -> None:
    assert _run_gate(tmp_path, "09:30", 1, "09", "28", "10") == 0


def test_gate_passes_at_tolerance_edge(tmp_path: Path) -> None:
    assert _run_gate(tmp_path, "09:38", 1, "09", "28", "10") == 0


def test_gate_skips_just_outside_tolerance(tmp_path: Path) -> None:
    assert _run_gate(tmp_path, "09:39", 1, "09", "28", "10") != 0


def test_gate_skips_far_out_of_window(tmp_path: Path) -> None:
    # The exact pre-fix symptom: 09:28 Berlin == 03:28 ET, hours before the open.
    assert _run_gate(tmp_path, "03:28", 1, "09", "28", "10") != 0


def test_gate_skips_weekend(tmp_path: Path) -> None:
    assert _run_gate(tmp_path, "09:28", 6, "09", "28", "10") != 0  # Saturday


def test_gate_runs_exactly_once_per_et_day(tmp_path: Path) -> None:
    # Two in-window candidate fires (or a launchd catch-up) must not double-run
    # -- for phase-a that would mean duplicate paper orders.
    assert _run_gate(tmp_path, "09:28", 1, "09", "28", "10") == 0
    assert _run_gate(tmp_path, "09:28", 1, "09", "28", "10") != 0


def test_hour_scope_allows_one_run_per_et_hour(tmp_path: Path) -> None:
    # The intraday observation drivers (commercial-shadow) fire once per RTH
    # hour BY DESIGN; the day-scoped marker turned their six daily slots into
    # one (and a failed 16:05 fire burned the whole 2026-08-17 session). Same
    # hour: second fire skips. Next hour: the fire proceeds again.
    assert _run_gate(tmp_path, "10:05", 1, "12", "45", "195", scope="hour") == 0
    assert _run_gate(tmp_path, "10:05", 1, "12", "45", "195", scope="hour") != 0
    assert _run_gate(tmp_path, "10:35", 1, "12", "45", "195", scope="hour") != 0
    assert _run_gate(tmp_path, "11:05", 1, "12", "45", "195", scope="hour") == 0


def test_hour_scope_still_skips_outside_window_and_on_weekends(tmp_path: Path) -> None:
    assert _run_gate(tmp_path, "08:05", 1, "12", "45", "195", scope="hour") != 0
    assert _run_gate(tmp_path, "10:05", 6, "12", "45", "195", scope="hour") != 0


def test_default_scope_is_day_when_the_sixth_argument_is_omitted(tmp_path: Path) -> None:
    # The order-placing chains keep exactly-once-per-day semantics untouched:
    # a second fire in a LATER hour must still skip without the hour scope.
    assert _run_gate(tmp_path, "09:28", 1, "09", "28", "60") == 0
    assert _run_gate(tmp_path, "10:05", 1, "09", "28", "60") != 0


def test_concurrent_in_window_fires_let_exactly_one_proceed(tmp_path: Path) -> None:
    # The exactly-once marker must hold under CONCURRENCY, not just sequential
    # calls: a launchd wake-from-sleep catch-up can race the regular fire. A
    # non-atomic check-then-write marker lets several racers past the [ -e ]
    # check at once -> duplicate paper orders for phase-a. The O_EXCL marker
    # create guarantees a single winner no matter how the racers interleave.
    from concurrent.futures import ThreadPoolExecutor

    racers = 16
    with ThreadPoolExecutor(max_workers=racers) as pool:
        codes = list(
            pool.map(
                lambda _: _run_gate(tmp_path, "09:28", 1, "09", "28", "10"),
                range(racers),
            )
        )
    assert codes.count(0) == 1, f"expected exactly one winner, got codes={codes}"
    # Every non-winner must have skipped cleanly (the gate's return 1), never
    # crashed or produced some other exit status.
    assert sorted(codes) == [0] + [1] * (racers - 1), f"codes={codes}"


def test_gate_surfaces_real_write_error_instead_of_faking_already_ran(tmp_path: Path) -> None:
    # A genuine filesystem failure on the marker write (disk full, missing or
    # unwritable cache dir) must be reported as a write error, not masqueraded
    # as the benign "already ran" exactly-once skip -- otherwise phase-a
    # silently does not run and the operator sees a message hiding the cause.
    #
    # Force the failure by putting a *file* where the gate expects the
    # ``cache/live`` directory: ``mkdir -p`` and the marker write then fail
    # with ENOTDIR (which even root cannot bypass), and the marker path cannot
    # exist -- so the gate must take the write-error branch, not "already ran".
    (tmp_path / "cache").mkdir()
    (tmp_path / "cache" / "live").write_text("")  # a file where a dir belongs

    proc = subprocess.run(
        [
            "bash",
            "-c",
            f'source "{_LIB}"; c13_require_et_window "{tmp_path}" 09 28 10 testjob',
        ],
        env={
            "PATH": "/usr/bin:/bin",
            "C13_GATE_NOW_ET": "09:28",
            "C13_GATE_NOW_DOW": "1",
        },
        capture_output=True,
        text=True,
    )
    assert proc.returncode != 0
    assert "FAILED to write marker" in proc.stderr
    assert "already ran" not in proc.stderr


# --------------------------------------------------------------------------- #
# The plist candidate LOCAL hours must bracket the ET target across DST so that
# exactly one candidate maps to the ET target regardless of the US/EU offset.
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "plist_name,et_hour",
    [
        ("com.skippalgo.c13.phase-a.plist", 9),            # 09:28 ET
        ("com.skippalgo.c13.ibkr-smoke.plist", 8),         # 08:00 ET
        ("com.skippalgo.c13.phase-a-export.plist", 9),     # 09:18 ET
        ("com.skippalgo.c13.collect-imbalance.plist", 9),  # 09:28 ET
        ("com.skippalgo.c13.wsh-earnings.plist", 16),      # 16:30 ET
        ("com.skippalgo.c13.audit-push.plist", 17),        # 17:30 ET (+7h wraps)
    ],
)
def test_plist_candidate_hours_cover_dst_offsets(plist_name: str, et_hour: int) -> None:
    # 2026-08-19 (Doppelgaenger): der Grund fuer den Regex-Workaround ist weg —
    # das ``--phase`` im XML-Kommentar der phase-a-Plist ist umformuliert, alle
    # 12 Plists parsen strikt (test_every_repo_plist_is_valid_xml haelt das).
    # Der Regex bleibt hier, weil er die Reihenfolge Weekday/Hour/Minute IN DER
    # DATEI prueft, was plistlib normalisiert wegwirft.
    text = (_REPO / "automation" / "launchd" / plist_name).read_text()
    entries = re.findall(
        r"<key>Weekday</key><integer>(\d+)</integer>"
        r"<key>Hour</key><integer>(\d+)</integer>"
        r"<key>Minute</key><integer>(\d+)</integer>",
        text,
    )
    assert entries, "no compact schedule entries found"
    hours = {int(h) for _w, h, _m in entries}
    weekdays = {int(w) for w, _h, _m in entries}
    # Berlin<->ET is +5h / +6h / +7h across the mismatched US/EU DST windows,
    # so exactly one candidate maps onto the ET target every day of the year.
    offsets = (5, 6, 7)
    assert hours == {(et_hour + off) % 24 for off in offsets}, hours
    # A candidate that crosses midnight (ET+off >= 24, e.g. audit-push 17:30 ET
    # +7h = 00:30 next-day Berlin) carries a Berlin weekday of ET-weekday + 1,
    # so the full set spans Mon..Sat; otherwise Mon..Fri.
    if any(et_hour + off >= 24 for off in offsets):
        assert weekdays == {1, 2, 3, 4, 5, 6}, weekdays
    else:
        assert weekdays == {1, 2, 3, 4, 5}, weekdays


def test_tws_reminder_plist_mixes_et_morning_and_local_evening() -> None:
    """The reminder has TWO windows on TWO clocks (realigned 2026-07-08).

    Morning: 07:45 ET (15 min before the 08:00 ET ibkr-smoke, which writes
    smoke_HALT when TWS is down) -> three DST-bracket candidates at
    12:45/13:45/14:45 local, disambiguated by the ET gate in the wrapper.
    Evening: 22:50 LOCAL, ungated, because the 23:05 fill reconcile is
    deliberately local-time. The old single 09:13 LOCAL fire hit ~03:13 ET
    and protected nothing — this pin prevents that regression."""
    text = (
        _REPO / "automation" / "launchd" / "com.skippalgo.c13.tws-reminder.plist"
    ).read_text()
    entries = re.findall(
        r"<key>Weekday</key><integer>(\d+)</integer>"
        r"<key>Hour</key><integer>(\d+)</integer>"
        r"<key>Minute</key><integer>(\d+)</integer>",
        text,
    )
    assert entries, "no compact schedule entries found"
    morning = {(int(w), int(h)) for w, h, m in entries if int(m) == 45}
    evening = {(int(w), int(h)) for w, h, m in entries if int(m) == 50}
    assert {h for _w, h in morning} == {7 + off for off in (5, 6, 7)}, morning
    assert {w for w, _h in morning} == {1, 2, 3, 4, 5}, morning
    assert evening == {(w, 22) for w in (1, 2, 3, 4, 5)}, evening
    assert len(entries) == len(morning) + len(evening), "unexpected extra entries"
    # The wrapper must gate the morning candidates on true ET.
    wrapper = (_REPO / "automation" / "launchd" / "run-c13-tws-reminder.sh").read_text()
    assert "lib_c13_et_gate.sh" in wrapper
    assert re.search(
        r"c13_require_et_window\s+\"\$REPO\"\s+07\s+45\s+\d+\s+tws-reminder", wrapper
    ), "morning reminder must target 07:45 ET via the shared gate"


def test_every_repo_plist_is_valid_xml() -> None:
    """Jede getrackte Plist muss von einem STRIKTEN Parser lesbar sein.

    2026-08-19 (Doppelgaenger): ``com.skippalgo.c13.phase-a.plist`` trug ein
    ``--phase`` in einem XML-Kommentar — in XML verboten. Apples toleranter
    Parser (launchd, ``plutil -lint``) akzeptierte es, Pythons ``plistlib``
    brach ab. Folge: jedes Python-Werkzeug ueber die Plist-Population stolpert
    ueber genau eine Datei, und der bequeme Ausweg ist ein Regex-Workaround,
    der die naechste Analyse wieder blind macht (so geschehen in
    ``test_plist_candidate_hours_cover_dst_offsets``). ``plutil -lint`` haette
    den Defekt NIE gemeldet — er muss hier gegen einen strikten Parser fallen.
    """
    import plistlib

    plists = sorted((_REPO / "automation" / "launchd").glob("*.plist"))
    assert len(plists) >= 10, f"Population unplausibel klein: {[p.name for p in plists]}"

    broken: dict[str, str] = {}
    for path in plists:
        try:
            plistlib.loads(path.read_bytes())
        except Exception as exc:  # jeder Parse-Fehler zaehlt, nicht nur ExpatError
            broken[path.name] = str(exc)[:80]
    assert not broken, f"Plists, die ein strikter XML-Parser ablehnt: {broken}"
