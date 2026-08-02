"""The TWS autostart must never leak the paper password.

Measured 2026-08-02 across the 19 recorded smoke days: 9 SUCCESS, 10
DEGRADED — every DEGRADED one a ConnectionRefused on 127.0.0.1:7497, i.e.
TWS not running. run-c13-tws-reminder.sh fired correctly on each of those
days (23 notifications in its log), so the reminder is not the gap; the
human acting on it is. This job removes the human from the loop.

IBC's own twsstartmacos.sh hands the password to java as ``--pw=...``,
which exposes it to ``ps`` for every process on the machine. These tests pin
that our launcher takes the other route IBC documents: credentials in a
location-protected ini, never on a command line, shredded after use.
"""
from __future__ import annotations

import plistlib
import re
import subprocess
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
_SCRIPT = _REPO / "automation" / "launchd" / "run-c13-tws-autostart.sh"
_PLIST = _REPO / "automation" / "launchd" / "com.skippalgo.c13.tws-autostart.plist"


def _source() -> str:
    return _SCRIPT.read_text(encoding="utf-8")


def _code() -> str:
    """Executable lines only.

    The pins below must not trip on the header comment, which quotes the very
    constructs it explains why we avoid (``--pw=``, ``twsstartmacos.sh``).
    A pin that forbids naming a hazard also forbids documenting it.
    """
    return "\n".join(
        line for line in _source().splitlines() if not line.lstrip().startswith("#")
    )


def test_the_password_never_reaches_a_command_line() -> None:
    code = _code()

    assert "--pw=" not in code, (
        "a --pw argument would expose the paper password to `ps`"
    )
    assert "--user=" not in code, (
        "credentials travel in the ini only, so --user has no business here"
    )
    # It must call IBC's inner entry point, not twsstartmacos.sh, precisely
    # because the stock wrapper builds that --pw argument itself.
    assert "twsstartmacos.sh" not in code
    assert "scripts/ibcstart.sh" in code


def test_the_runtime_ini_is_shredded_on_every_exit_path() -> None:
    source = _source()

    assert re.search(r"trap\s+'rm -f \"\$\{RUNTIME_INI\}\"'\s+EXIT", source), (
        "a failed login must not leave the credentials on disk"
    )
    assert "chmod 600" in source, "the ini itself must be owner-only"
    assert "chmod 700" in source, "and so must its directory"


def test_the_password_comes_from_the_keychain_not_the_repo() -> None:
    source = _source()

    assert "security find-generic-password" in source
    assert "skipp.ibkr.paper" in source
    # A hardcoded secret would be the whole point missed.
    assert not re.search(r'IbPassword=[^"%\n]', source), (
        "IbPassword must only ever be written from the Keychain value"
    )


def test_a_missing_keychain_item_fails_loudly_instead_of_hanging() -> None:
    # Under launchd there is no UI, so an interactive `security` prompt would
    # hang the job until launchd kills it — silently costing the trading day.
    source = _source()
    guard = source.split("PW=", 1)[1].split("PRIVATE_DIR=", 1)[0]

    assert "exit 1" in guard
    assert "_write_marker" in guard, "the failure must be machine-detectable"


def test_a_dark_port_is_a_failure_not_a_success() -> None:
    source = _source()
    tail = source.split("WAITED=0", 1)[1]

    assert "exit 1" in tail, (
        "a login that never opens the port is exactly what this job exists to "
        "surface — exiting 0 would be green without observation"
    )
    assert "DEGRADED" in tail


def test_the_job_is_idempotent_when_tws_is_already_up() -> None:
    source = _source()
    head = source.split("if [[ ! -x", 1)[0]

    assert "nc -z 127.0.0.1" in head
    assert "exit 0" in head, "an already-running TWS must not be restarted"


def test_the_plist_fires_before_the_smoke_window() -> None:
    plist = plistlib.loads(_PLIST.read_bytes())
    intervals = plist["StartCalendarInterval"]

    hours = sorted({entry["Hour"] for entry in intervals})
    minutes = {entry["Minute"] for entry in intervals}
    weekdays = sorted({entry["Weekday"] for entry in intervals})

    # Three DST-bracketing local hours, one per ET weekday passes the gate.
    assert hours == [12, 13, 14], hours
    assert minutes == {30}, minutes
    assert weekdays == [1, 2, 3, 4, 5], weekdays
    # The smoke fires at :00; starting at :30 of the previous hour leaves a
    # 30-minute login budget.
    assert len(intervals) == 15


def test_the_script_is_valid_bash_and_executable() -> None:
    assert _SCRIPT.stat().st_mode & 0o111, "launchd needs it executable"
    proc = subprocess.run(["bash", "-n", str(_SCRIPT)], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
