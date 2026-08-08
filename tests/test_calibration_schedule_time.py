"""The nightly calibration must fire at the configured UTC time.

``RT_CALIBRATION_UTC_HHMM`` is an operator-set Railway variable listed in
``services/signals_producer/README.md`` under "Tuning (optional)" with no format
given. The scheduler used to compare it as a *string* against
``datetime.strftime("%H:%M")`` — chronological only while both sides are
zero-padded. This pins the parse and the resulting fire times.

Why it matters: this calibration loop has already silently not run for a month
once (see ``test_dockerfile_ships_the_nightly_calibrator_module`` — the lean
image was missing the calibrator and the fail-soft scheduler swallowed the
``ModuleNotFoundError``). An unpadded env value is a second, independent door to
the same silent non-run.
"""
from __future__ import annotations

from datetime import time

import pytest

from open_prep.calibration_scheduler import parse_calibration_hhmm

# Every wall-clock minute a poll can observe, zero-padded exactly as
# datetime.strftime("%H:%M") produces it.
_ALL_MINUTES = [f"{h:02d}:{m:02d}" for h in range(24) for m in range(60)]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("21:30", time(21, 30)),  # the padded form the code comment shows
        ("09:30", time(9, 30)),
        ("9:30", time(9, 30)),    # never fired under the string compare
        ("0:05", time(0, 5)),     # first fired at 10:00 under the string compare
        ("  21:30  ", time(21, 30)),
    ],
)
def test_a_configured_time_parses_padded_or_not(raw: str, expected: time) -> None:
    assert parse_calibration_hhmm(raw) == expected


@pytest.mark.parametrize("raw", ["", "   ", "abc", "25:00", "21:60", "2130", "21"])
def test_an_unusable_value_disables_rather_than_guesses(raw: str) -> None:
    """None lets the caller log "stays OFF" instead of appearing scheduled."""
    assert parse_calibration_hhmm(raw) is None


@pytest.mark.parametrize(("raw", "first_fire"), [("9:30", "09:30"), ("0:05", "00:05")])
def test_an_unpadded_time_fires_at_that_time_not_never_and_not_late(
    raw: str, first_fire: str,
) -> None:
    """The regression itself, over the whole 24h population rather than a sample.

    ``cal_last_day != today and now >= cal_at`` is the producer's trigger. The
    old string form of the right-hand side is kept here as the counter-example
    so this test fails loudly if anyone reverts to it.
    """
    cal_at = parse_calibration_hhmm(raw)
    assert cal_at is not None

    fires_now = [
        hhmm for hhmm in _ALL_MINUTES
        if time(int(hhmm[:2]), int(hhmm[3:])) >= cal_at
    ]
    fires_under_the_old_string_compare = [
        hhmm for hhmm in _ALL_MINUTES if hhmm >= raw
    ]

    assert fires_now[0] == first_fire
    assert fires_now != fires_under_the_old_string_compare
