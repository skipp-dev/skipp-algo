"""The smoke sentinel must block real danger, not a closed TWS port.

Measured 2026-08-02 from the operator's own launchd markers: 19 recorded
smoke days, 10 of them DEGRADED — every single one ``unexpected:EXIT=1``
(``ConnectionRefusedError`` on 127.0.0.1:7497, i.e. TWS simply not running).
``smoke_HALT`` is deliberately never auto-removed, so one such day left it
standing indefinitely.

That combination made the sentinel unusable as a gate: had the 09:28-ET
paper submit honoured it, the fills of 2026-07-14 (a DEGRADED day, sentinel
already standing since 07-10) could never have happened — and with them most
of the 23 fills that make up the entire track record. So the sharp path
ignored it, and the sentinel guarded only ``run_ibkr_open_execution.py``,
which no launchd job invokes.

The fix separates the two failure classes:

* EXIT=1 / unexpected — TWS unreachable. The 09:28 submit fails on its own
  if TWS is still down, and succeeds if it came back. Day marker only, no
  sticky sentinel.
* EXIT=2 (risk violation) and EXIT=3 (leftover non-terminal orders) — real
  danger with state a human must inspect. Sticky sentinel, and now actually
  honoured by the sharp path.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
_SMOKE = _REPO / "automation" / "launchd" / "run-c13-ibkr-smoke.sh"
_PHASE_A = _REPO / "automation" / "launchd" / "run-c13-phase-a.sh"


def _smoke_source() -> str:
    return _SMOKE.read_text(encoding="utf-8")


def _phase_a_source() -> str:
    return _PHASE_A.read_text(encoding="utf-8")


def _exit_branch(source: str, label: str) -> str:
    """Return the case-branch body for ``label`` from the smoke exit dispatch."""
    dispatch = source.split('case "${SMOKE_EXIT}" in', 1)[1]
    branch = dispatch.split(f"{label})", 1)[1]
    return branch.split(";;", 1)[0]


def test_connection_failure_does_not_write_a_sticky_sentinel() -> None:
    # The catch-all branch covers EXIT=1 (ConnectionRefused) — all ten
    # observed DEGRADED days landed here.
    catch_all = _exit_branch(_smoke_source(), "*")

    assert "_write_marker" in catch_all, "the day must still be recorded"
    assert "_write_halt" not in catch_all, (
        "a closed TWS port must not raise a sentinel that only a human can clear"
    )


@pytest.mark.parametrize("label", ["2", "3"])
def test_real_danger_still_writes_a_sticky_sentinel(label: str) -> None:
    branch = _exit_branch(_smoke_source(), label)

    assert "_write_halt" in branch, (
        f"EXIT={label} carries state a human must inspect — it stays sticky"
    )


def test_the_sharp_submit_path_now_honours_the_sentinel() -> None:
    # The whole point: the sentinel is only worth honouring once it is
    # reserved for danger. Before this change the 09:28 submit ignored it.
    source = _phase_a_source()

    assert "smoke_HALT" in source, "the paper submit must consult the sentinel"
    # The INVOCATION, not the header comment that also names the module.
    submit_index = source.find("-m scripts.run_smc_live_incubation")
    assert submit_index > 0, "expected the runner invocation in the sharp path"
    halt_index = source.find("smoke_HALT")
    assert 0 < halt_index < submit_index, (
        "the check must precede the submit, not follow it"
    )


def test_sentinel_blocks_the_submit_end_to_end(tmp_path: Path) -> None:
    """Behavioural check: with a sentinel present the guard refuses."""
    repo = tmp_path
    (repo / "cache" / "live").mkdir(parents=True)
    (repo / "cache" / "live" / "smoke_HALT").write_text(
        "HALT|leftover-orders:EXIT=3|2026-08-02T12:00:00Z\n", encoding="utf-8"
    )

    guard = _phase_a_source().split("# --- smoke-sentinel guard ---", 1)[1]
    guard = guard.split("# --- end smoke-sentinel guard ---", 1)[0]

    proc = subprocess.run(
        ["bash", "-c", f'REPO="{repo}"; _write_marker() {{ :; }}; {guard}'],
        env={"PATH": "/usr/bin:/bin"},
        capture_output=True,
        text=True,
    )

    assert proc.returncode != 0, "a standing sentinel must stop the submit"
    assert "smoke_HALT" in proc.stderr, "and must say why"


def test_guard_passes_when_no_sentinel_stands(tmp_path: Path) -> None:
    repo = tmp_path
    (repo / "cache" / "live").mkdir(parents=True)

    guard = _phase_a_source().split("# --- smoke-sentinel guard ---", 1)[1]
    guard = guard.split("# --- end smoke-sentinel guard ---", 1)[0]

    proc = subprocess.run(
        ["bash", "-c", f'REPO="{repo}"; _write_marker() {{ :; }}; {guard}'],
        env={"PATH": "/usr/bin:/bin"},
        capture_output=True,
        text=True,
    )

    assert proc.returncode == 0, (
        "the normal case — no sentinel — must not block the day's submit"
    )
