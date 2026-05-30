"""Pin: every downstream consumer of the Databento producer must schedule
its cron ticks AFTER the producer has written the day's artifact.

Chronic-failure root cause (2026-05-29 audit, this commit)
----------------------------------------------------------
``smc-measurement-benchmark-rolling.yml`` was firing at ``07:30 UTC`` daily
and ``f2-promotion-gate-daily.yml`` at ``10:00 UTC`` daily, but the
producer ``smc-databento-production-export-sharded.yml`` does not run
until ``12:00 UTC`` Mon-Fri. Both consumers therefore failed every single
day on the "Producer artifact missing for <date>" / "Missing dual-arm
artifact" guards, generating recurring red cron-failure issues.

This pin enforces the ordering invariant for every consumer that pulls
producer artifacts via the cross-workflow REST API:

  * the consumer's earliest cron tick must be >= producer's earliest
    cron tick + a small handoff headroom (so the producer has time to
    upload the artifact before the consumer queries for it), AND
  * the consumer must not schedule any tick on days the producer does
    not run (Mon-Fri only \u2014 weekend ticks would always fail).
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

_REPO_ROOT = Path(__file__).resolve().parent.parent
_PRODUCER = _REPO_ROOT / ".github" / "workflows" / "smc-databento-production-export-sharded.yml"

# Direct downstream consumers of the producer artifact. Add new consumers
# here as they are introduced.
_CONSUMERS = (
    _REPO_ROOT / ".github" / "workflows" / "smc-measurement-benchmark-rolling.yml",
    _REPO_ROOT / ".github" / "workflows" / "f2-promotion-gate-daily.yml",
    _REPO_ROOT / ".github" / "workflows" / "promotion-gate-daily.yml",
    _REPO_ROOT / ".github" / "workflows" / "fvg-quality-recal-shadow-daily.yml",
)

# Minutes of slack the producer needs to finish + upload its artifact
# before the consumer's `gh api /actions/artifacts` lookup will find it.
# The producer cap is currently 240 min (see
# test_workflow_databento_cron_respacing.py), but the consumers only
# need the first sharded artifact to appear, which happens well before
# the producer finishes. Keep this small and bump if reality diverges.
_HANDOFF_HEADROOM_MIN_MINUTES = 30


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _schedule_entries(workflow: dict) -> list[dict]:
    triggers = workflow.get(True, workflow.get("on", {}))  # PyYAML quirk
    if not isinstance(triggers, dict):
        return []
    return list(triggers.get("schedule") or [])


def _parse_cron(cron: str) -> tuple[int, int, str] | None:
    """Return (hour, minute, dow_field) for the simple ``M H * * D`` form."""
    parts = cron.split()
    if len(parts) != 5:
        return None
    minute_str, hour_str, _dom, _mon, dow = parts
    if not (minute_str.isdigit() and hour_str.isdigit()):
        return None
    return int(hour_str), int(minute_str), dow


def _earliest_minute(entries: list[dict]) -> int | None:
    minutes = []
    for entry in entries:
        parsed = _parse_cron(entry.get("cron", ""))
        if parsed is None:
            continue
        h, m, _dow = parsed
        minutes.append(h * 60 + m)
    return min(minutes) if minutes else None


def _producer_earliest_minute() -> int:
    entries = _schedule_entries(_load(_PRODUCER))
    earliest = _earliest_minute(entries)
    assert earliest is not None, (
        f"{_PRODUCER.name} has no parseable simple-form schedule entries"
    )
    return earliest


def _producer_dow_fields() -> set[str]:
    fields = set()
    for entry in _schedule_entries(_load(_PRODUCER)):
        parsed = _parse_cron(entry.get("cron", ""))
        if parsed is not None:
            fields.add(parsed[2])
    assert fields, f"{_PRODUCER.name} has no parseable schedule entries"
    return fields


@pytest.mark.parametrize("consumer_path", _CONSUMERS, ids=lambda p: p.name)
def test_consumer_first_tick_runs_after_producer(consumer_path: Path) -> None:
    """Consumer's earliest cron must be at least HEADROOM minutes after
    the producer's earliest cron, otherwise every scheduled run will
    abort on the missing-artifact guard."""
    consumer_entries = _schedule_entries(_load(consumer_path))
    consumer_first = _earliest_minute(consumer_entries)
    assert consumer_first is not None, (
        f"{consumer_path.name} has no parseable simple-form schedule entries"
    )
    producer_first = _producer_earliest_minute()
    min_required = producer_first + _HANDOFF_HEADROOM_MIN_MINUTES
    assert consumer_first >= min_required, (
        f"{consumer_path.name} earliest cron {consumer_first // 60:02d}:"
        f"{consumer_first % 60:02d} UTC fires before producer first tick "
        f"{producer_first // 60:02d}:{producer_first % 60:02d} UTC + "
        f"{_HANDOFF_HEADROOM_MIN_MINUTES} min handoff headroom \u2014 the "
        "downstream artifact-lookup will fail with 'Producer artifact "
        "missing for <date>'. Either shift the consumer cron later or "
        "switch it to a workflow_run trigger keyed on the producer."
    )


@pytest.mark.parametrize("consumer_path", _CONSUMERS, ids=lambda p: p.name)
def test_consumer_dow_matches_producer(consumer_path: Path) -> None:
    """Consumer must not schedule ticks on days the producer does not
    run. The producer is Mon-Fri only; a daily ('*') consumer cron will
    fail every Saturday and Sunday on the missing-artifact guard."""
    producer_dows = _producer_dow_fields()
    consumer_entries = _schedule_entries(_load(consumer_path))
    offenders: list[str] = []
    for entry in consumer_entries:
        parsed = _parse_cron(entry.get("cron", ""))
        if parsed is None:
            continue
        _h, _m, dow = parsed
        if dow not in producer_dows:
            offenders.append(f"cron={entry.get('cron')!r} dow={dow!r}")
    assert not offenders, (
        f"{consumer_path.name} schedules ticks on days the producer "
        f"(dow fields {sorted(producer_dows)!r}) does not run: "
        f"{offenders}. Restrict the consumer to the producer's day-of-week "
        "window or pivot to a workflow_run trigger."
    )
