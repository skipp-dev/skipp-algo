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

# F-V8-C3.1 (2026-05-02) — bumped both caps from 60/90 to 120/120 after the
# producer was killed 12 runs in a row by the 60-min cap. Cap is now 120,
# which equals the cron interval (2h) — anything >120 would let a zombie
# run overlap the next tick. Once F-V8-A1.x logging reveals the dominant
# step, a follow-up PR can tighten these caps again behind a real fix.
_PRODUCER_TIMEOUT_MAX = 120
_CONSUMER_TIMEOUT_MAX = 120
# Cron headroom (consumer cron offset - producer cron offset, hour-aware)
# the consumer expects in order to read fresh exports. PR #2020 respaced
# consumer to HH+1:00 so the realised headroom is 60 min, but we keep the
# floor at 30 min so a future re-tightening still has a margin of safety.
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


def _cron_offsets_minutes(workflow: dict) -> list[int]:
    """Return minute-of-day offsets (hour*60 + minute) for every cron entry.

    Hour-aware so workflows that respaced the consumer to HH+1:00 (F-V6-C3,
    PR #2020) report 60-min offsets relative to the previous-hour producer
    tick, not 0-min offsets from naive minute-of-hour comparison.
    """
    offsets: list[int] = []
    triggers = workflow.get(True, workflow.get("on", {}))
    schedule = (triggers or {}).get("schedule") if isinstance(triggers, dict) else None
    for entry in schedule or []:
        cron = entry.get("cron", "")
        parts = cron.split()
        if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
            offsets.append(int(parts[1]) * 60 + int(parts[0]))
    return offsets


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
    """Each producer tick must be followed by a consumer tick with ≥headroom.

    F-V6-C3 (PR #2020) respaced consumer to HH+1:00 so the comparison must
    be hour-aware. For every producer tick we look up the *next* consumer
    tick (wrapping by day) and assert delta ≥ _CRON_HEADROOM_MIN_MINUTES.
    """
    producer_offsets = sorted(set(_cron_offsets_minutes(_load(_PRODUCER))))
    consumer_offsets = sorted(set(_cron_offsets_minutes(_load(_CONSUMER))))
    assert producer_offsets, f"{_PRODUCER.name} has no parseable cron entries"
    assert consumer_offsets, f"{_CONSUMER.name} has no parseable cron entries"

    day_minutes = 24 * 60
    for p in producer_offsets:
        # Smallest forward delta to any consumer tick (mod day).
        forward_deltas = [(c - p) % day_minutes for c in consumer_offsets]
        forward_deltas = [d for d in forward_deltas if d > 0]
        assert forward_deltas, (
            f"Producer tick at minute-of-day={p} has no following consumer tick"
        )
        delta = min(forward_deltas)
        assert delta >= _CRON_HEADROOM_MIN_MINUTES, (
            f"Producer tick @ minute-of-day {p} is followed by next consumer "
            f"tick only {delta} min later; F-V6-C3 requires ≥"
            f"{_CRON_HEADROOM_MIN_MINUTES} min headroom so the producer can "
            "complete and publish before the consumer reads."
        )


@pytest.mark.parametrize("path", [_PRODUCER, _CONSUMER])
def test_workflow_files_exist(path: Path) -> None:
    assert path.is_file(), f"Expected workflow file missing: {path}"
