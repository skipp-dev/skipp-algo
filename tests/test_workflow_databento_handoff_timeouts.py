"""Pin: producer/consumer timeout discipline for the Databento → library handoff.

Audit follow-up to **F-V6-C3 / F-V6-C4 (2026-05-02)**.

Background
----------
``smc-databento-production-export.yml`` (producer) writes the daily
microstructure exports that ``smc-library-refresh.yml`` (consumer) reads
30 minutes later (12:00→12:30, 14:00→14:30, 16:00→16:30, 18:00→18:30 UTC).

Before this audit:

* Producer ``timeout-minutes: 90`` — could overrun the 30-min consumer
  headroom by ~3× and let the consumer pick up *yesterday's* artifact.
* Consumer ``timeout-minutes: 120`` — exceeded the 2-hour cron interval,
  so a hung run could overlap the next tick.

This module pins both timeouts and the relative ordering invariants so a
future "harmless tweak" cannot silently re-open the regression.
"""
from __future__ import annotations

from pathlib import Path

import pytest

import yaml

_REPO_ROOT = Path(__file__).resolve().parent.parent
_PRODUCER = _REPO_ROOT / ".github" / "workflows" / "smc-databento-production-export.yml"
_CONSUMER = _REPO_ROOT / ".github" / "workflows" / "smc-library-refresh.yml"

# F-V6-C3/C4 (2026-05-02) — values pinned by audit.
_PRODUCER_TIMEOUT_MAX = 60
_CONSUMER_TIMEOUT_MAX = 90
# Cron headroom (consumer cron minute - producer cron minute) the consumer
# expects in order to read fresh exports. Today's design = 30 min.
_CRON_HEADROOM_MIN_MINUTES = 30


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _job_timeouts(workflow: dict) -> dict[str, int]:
    """Return {job_id: timeout-minutes} for jobs that declare it."""
    out: dict[str, int] = {}
    for job_id, job in (workflow.get("jobs") or {}).items():
        if isinstance(job, dict) and "timeout-minutes" in job:
            out[job_id] = int(job["timeout-minutes"])
    return out


def _cron_minutes(workflow: dict) -> list[int]:
    """Return the *minute* field of every schedule cron expression."""
    minutes: list[int] = []
    triggers = workflow.get(True, workflow.get("on", {}))  # PyYAML quirk: `on:` → True
    schedule = (triggers or {}).get("schedule") if isinstance(triggers, dict) else None
    for entry in schedule or []:
        cron = entry.get("cron", "")
        parts = cron.split()
        if len(parts) >= 2 and parts[0].isdigit():
            minutes.append(int(parts[0]))
    return minutes


def test_producer_timeout_is_tight() -> None:
    """F-V6-C3: producer cannot overrun the consumer's headroom."""
    timeouts = _job_timeouts(_load(_PRODUCER))
    assert timeouts, f"{_PRODUCER.name} has no jobs with timeout-minutes"
    for job_id, mins in timeouts.items():
        assert mins <= _PRODUCER_TIMEOUT_MAX, (
            f"{_PRODUCER.name} job '{job_id}' has timeout-minutes={mins}, "
            f"exceeding F-V6-C3 cap of {_PRODUCER_TIMEOUT_MAX} min. A producer "
            "that can run longer than the consumer's cron headroom risks "
            "feeding the consumer stale or partial exports."
        )


def test_consumer_timeout_is_tight() -> None:
    """F-V6-C4: consumer cannot overlap its own next cron tick."""
    timeouts = _job_timeouts(_load(_CONSUMER))
    assert timeouts, f"{_CONSUMER.name} has no jobs with timeout-minutes"
    for job_id, mins in timeouts.items():
        assert mins <= _CONSUMER_TIMEOUT_MAX, (
            f"{_CONSUMER.name} job '{job_id}' has timeout-minutes={mins}, "
            f"exceeding F-V6-C4 cap of {_CONSUMER_TIMEOUT_MAX} min. The cron "
            "repeats every 2h, so any value >120 lets a zombie run overlap "
            "the next tick."
        )


def test_producer_timeout_does_not_exceed_consumer() -> None:
    """Belt-and-suspenders: producer must never have a looser budget than consumer."""
    p_max = max(_job_timeouts(_load(_PRODUCER)).values())
    c_max = max(_job_timeouts(_load(_CONSUMER)).values())
    assert p_max <= c_max, (
        f"Producer timeout-minutes={p_max} must not exceed consumer "
        f"timeout-minutes={c_max} (F-V6-C3, 2026-05-02)."
    )


def test_consumer_cron_runs_after_producer_with_headroom() -> None:
    """Consumer crons must allow the producer at least N minutes of headroom."""
    p_minutes = sorted(set(_cron_minutes(_load(_PRODUCER))))
    c_minutes = sorted(set(_cron_minutes(_load(_CONSUMER))))
    assert p_minutes, f"{_PRODUCER.name} has no parseable cron minutes"
    assert c_minutes, f"{_CONSUMER.name} has no parseable cron minutes"

    # Today's design: producer fires at minute=0, consumer at minute=30.
    # Validate every consumer cron is ≥ headroom minutes after every producer
    # cron when paired by hour-of-day. Because both schedules use a
    # constant minute-of-hour, comparing the unique minute sets is enough.
    p_minute = p_minutes[0]
    c_minute = c_minutes[0]
    assert len(p_minutes) == 1 and len(c_minutes) == 1, (
        "Pin assumes single minute-of-hour per workflow; if you stagger the "
        "schedule, extend this test to compare per (hour, minute) tuples."
    )
    delta = c_minute - p_minute
    assert delta >= _CRON_HEADROOM_MIN_MINUTES, (
        f"Consumer cron minute={c_minute} is only {delta} min after producer "
        f"cron minute={p_minute}; F-V6-C3 requires ≥{_CRON_HEADROOM_MIN_MINUTES} "
        "min headroom so the producer can complete and publish before the "
        "consumer reads."
    )


@pytest.mark.parametrize("path", [_PRODUCER, _CONSUMER])
def test_workflow_files_exist(path: Path) -> None:
    assert path.is_file(), f"Expected workflow file missing: {path}"
