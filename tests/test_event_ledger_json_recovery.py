"""Regression tests for PR-J2 (audit pass 2, 2026-05-10).

Pin the malformed-line tolerance of
``smc_core.event_ledger.read_event_ledger``. Pre-fix, a single corrupt
JSONL line raised ``json.JSONDecodeError`` from the generator and
silently lost every subsequent record for every caller (scoring
pipelines, F2 calibration, AB comparison).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from smc_core.event_ledger import read_event_ledger


def _write_jsonl(path: Path, lines: list[str]) -> None:
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_read_event_ledger_skips_malformed_line(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
):
    """One corrupt line in the middle MUST NOT lose tail records."""
    path = tmp_path / "events_AAPL_1D.jsonl"
    _write_jsonl(
        path,
        [
            json.dumps({"id": "evt1", "ok": True}),
            '{"id": "evt2", "ok":',  # truncated → JSONDecodeError
            json.dumps({"id": "evt3", "ok": True}),
            json.dumps({"id": "evt4", "ok": True}),
        ],
    )
    with caplog.at_level(logging.WARNING, logger="smc_core.event_ledger"):
        rows = list(read_event_ledger(path))

    ids = [r["id"] for r in rows]
    assert ids == ["evt1", "evt3", "evt4"], (
        "PR-J2: malformed line at line 2 must NOT abort the generator; "
        "tail records (evt3, evt4) must still be yielded."
    )
    # And the skip MUST be observable.
    assert any(
        "malformed JSON" in rec.message and "line 2" in rec.message
        for rec in caplog.records
    ), "PR-J2: malformed line must be logged at WARNING with line number."


def test_read_event_ledger_handles_all_clean(tmp_path: Path):
    path = tmp_path / "events_clean.jsonl"
    _write_jsonl(
        path,
        [json.dumps({"id": f"evt{i}"}) for i in range(5)],
    )
    rows = list(read_event_ledger(path))
    assert [r["id"] for r in rows] == [f"evt{i}" for i in range(5)]


def test_read_event_ledger_skips_blank_lines(tmp_path: Path):
    path = tmp_path / "events_blanks.jsonl"
    path.write_text(
        "\n"
        + json.dumps({"id": "evt1"}) + "\n"
        + "\n   \n"
        + json.dumps({"id": "evt2"}) + "\n",
        encoding="utf-8",
    )
    rows = list(read_event_ledger(path))
    assert [r["id"] for r in rows] == ["evt1", "evt2"]


def test_read_event_ledger_all_corrupt_yields_nothing(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
):
    """Even a fully corrupt file must NOT raise — must yield empty."""
    path = tmp_path / "events_corrupt.jsonl"
    _write_jsonl(path, ['{"truncated":', '{"also_bad":', "not even json"])
    with caplog.at_level(logging.WARNING, logger="smc_core.event_ledger"):
        rows = list(read_event_ledger(path))
    assert rows == []
    # Three corrupt lines → at least three warnings.
    assert sum("malformed JSON" in r.message for r in caplog.records) >= 3
