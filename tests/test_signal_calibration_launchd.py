"""Contract tests for the nightly signal-calibration launchd job.

Pins the wrapper↔plist↔script wiring so a rename on one side (the exact drift
class the C13 drivers suffered) fails CI instead of silently never firing, and
asserts the driver stays a measurement job: no git push, quiet no-op without
events, fail-loud without an FMP key.
"""
from __future__ import annotations

import plistlib
import re
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
_LAUNCHD = _REPO / "automation" / "launchd"
_WRAPPER = _LAUNCHD / "run-signal-calibration.sh"
_PLIST = _LAUNCHD / "com.skippalgo.signals.calibration.plist"
_CALIBRATOR = _REPO / "scripts" / "calibrate_signal_followthrough.py"


def test_plist_points_at_existing_wrapper() -> None:
    doc = plistlib.loads(_PLIST.read_bytes())
    assert doc["Label"] == "com.skippalgo.signals.calibration"
    program_args = doc["ProgramArguments"]
    assert program_args[0] == "/bin/bash"
    # The placeholder path must resolve to the committed wrapper.
    assert program_args[1].endswith("automation/launchd/run-signal-calibration.sh")
    assert _WRAPPER.is_file()


def test_plist_schedule_is_weeknights_after_reconcile() -> None:
    doc = plistlib.loads(_PLIST.read_bytes())
    slots = doc["StartCalendarInterval"]
    assert [s["Weekday"] for s in slots] == [1, 2, 3, 4, 5]
    # 23:15 local: after the US close in both DST regimes AND after the 23:05
    # C13 reconcile, so the two FMP-consuming night jobs never overlap.
    assert all((s["Hour"], s["Minute"]) == (23, 15) for s in slots)
    assert doc["RunAtLoad"] is False


def test_wrapper_invokes_calibrator_and_writes_latest() -> None:
    text = _WRAPPER.read_text(encoding="utf-8")
    assert "scripts/calibrate_signal_followthrough.py" in text
    assert _CALIBRATOR.is_file(), "wrapper references a script that does not exist"
    assert "calibration_latest.json" in text
    # Events dir honours the same env var the realtime engine logs under.
    assert "RT_SIGNAL_EVENT_LOG_DIR" in text


def test_wrapper_is_a_measurement_job_not_a_publisher() -> None:
    """No git mutation from this driver (the C13 branch-guard failure class),
    and the two failure modes stay distinct: missing events = quiet no-op
    (exit 0), missing FMP key = loud DEGRADED exit 1."""
    text = _WRAPPER.read_text(encoding="utf-8")
    assert not re.search(r"\bgit (push|commit)\b", text)
    assert "SKIPPED" in text and '"no-events"' in text.replace("'", '"')
    assert "no-fmp-key" in text
    # The key is read verbatim from .env — never eval'd as a command.
    assert not re.search(r"^\s*eval\b", text, re.MULTILINE)
