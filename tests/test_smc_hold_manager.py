"""Behavioral source contracts for the private SMC Hold Manager."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOLD_MANAGER = ROOT / "SMC_Hold_Manager.pine"


def _read_source() -> str:
    return HOLD_MANAGER.read_text(encoding="utf-8")


def _indented_body_after(source: str, condition: str) -> str:
    match = re.search(
        rf"^{re.escape(condition)}\n(?P<body>(?:    [^\n]*\n)+)",
        source,
        flags=re.MULTILINE,
    )
    assert match is not None, f"Missing Pine block: {condition}"
    return match.group("body")


def test_time_stop_clock_starts_at_entry_touch_not_arming() -> None:
    """Waiting in ARMED state must not consume the in-trade time-stop budget."""
    source = _read_source()
    arming_body = _indented_body_after(
        source,
        "if can_act and state == 0 and arm_edge_now and i_entry > 0 and "
        "i_stop > 0 and i_stop < i_entry",
    )
    entry_body = _indented_body_after(source, "if can_act and entry_touch")

    assert "entry_time_ms := time" not in arming_body
    assert "entry_bar     := bar_index" not in arming_body
    assert "state         := 2" in entry_body
    assert "entry_bar     := bar_index" in entry_body
    assert "entry_time_ms := time" in entry_body


def test_time_stop_requires_an_initialized_entry_clock() -> None:
    source = _read_source()

    assert re.search(
        r"bool time_stop_hit = state == 2 .* not na\(entry_time_ms\) and\n"
        r"\s+\(time - entry_time_ms\)",
        source,
    )
