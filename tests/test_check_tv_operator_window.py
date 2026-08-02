"""The operator window is a claim on the TradingView account, with an expiry.

The expiry is the design: a forgotten window blocks nothing past its own
timestamp, which is what makes a hard refusal safe to build at all. An
unreadable value fails closed because the variable only ever changes by
deliberate operator action -- but the message carries the one command that
clears it, so a typo costs seconds.
"""

from __future__ import annotations

from datetime import datetime, timezone

from scripts.check_tv_operator_window import evaluate

_NOW = datetime(2026, 8, 2, 20, 0, tzinfo=timezone.utc)


def test_unset_variable_lets_the_run_through() -> None:
    for raw in (None, "", "   "):
        assert evaluate(raw, _NOW)[0] == 0


def test_expired_window_lets_the_run_through_and_says_so() -> None:
    code, message = evaluate("2026-08-02T19:00:00Z", _NOW)
    assert code == 0
    assert "expired" in message


def test_open_window_blocks_and_names_the_expiry_and_the_remaining_time() -> None:
    code, message = evaluate("2026-08-02T22:00:00Z", _NOW)
    assert code == 1
    assert "2026-08-02T22:00:00+00:00" in message
    assert "120 min" in message


def test_unparsable_value_fails_closed_with_the_clearing_command() -> None:
    code, message = evaluate("tomorrow", _NOW)
    assert code == 1
    assert "gh variable delete TV_OPERATOR_ACTIVE" in message


def test_naive_timestamp_is_refused_rather_than_guessed() -> None:
    """Guessing a zone would silently shift the window by hours."""
    code, message = evaluate("2026-08-02T22:00:00", _NOW)
    assert code == 1
    assert "UTC offset" in message
