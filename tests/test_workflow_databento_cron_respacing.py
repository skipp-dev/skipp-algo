"""Pin: Databento producer → library-refresh consumer cron handoff window.

Audit follow-up to **F-V6-C3 (2026-05-02)** — cron-respacing companion to
`tests/test_workflow_databento_handoff_timeouts.py` (PR #2018, scheduled to
land independently).

Background
----------
Producer (`smc-databento-production-export.yml`) writes the daily
microstructure exports that the consumer (`smc-library-refresh.yml`)
reads on its next tick.

Pre-respacing layout was producer at HH:00 weekdays, consumer at HH:30 —
only 30 min of headroom even though the producer's permitted budget (after
F-V6-C3 timeout cap) is 60 min. A 60-min producer run would feed the
consumer stale data.

This pin enforces the new 60-min handoff: every producer cron tick must
have a consumer cron tick at least 60 minutes later (and within the same
trading day) that picks up its output.
"""
from __future__ import annotations

from pathlib import Path

import yaml

_REPO_ROOT = Path(__file__).resolve().parent.parent
_PRODUCER = _REPO_ROOT / ".github" / "workflows" / "smc-databento-production-export.yml"
_CONSUMER = _REPO_ROOT / ".github" / "workflows" / "smc-library-refresh.yml"

# F-V6-C3 (2026-05-02): producer's max budget is 60 min (PR #2018), so the
# consumer must wait at least that long before reading.
_CRON_HEADROOM_MIN_MINUTES = 60


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _cron_ticks(workflow: dict) -> list[tuple[int, int]]:
    """Return sorted (hour, minute) tuples for every schedule cron entry.

    Crons that aren't of the simple ``M H * * D`` form (e.g. ranges in the
    minute or hour field) are skipped, since pairing those by tick would
    require enumerating each hour they expand to. The pin is intentionally
    strict about the simple form because the production schedule uses it.
    """
    triggers = workflow.get(True, workflow.get("on", {}))  # PyYAML quirk
    schedule = (triggers or {}).get("schedule") if isinstance(triggers, dict) else None
    ticks: list[tuple[int, int]] = []
    for entry in schedule or []:
        cron = entry.get("cron", "")
        parts = cron.split()
        if len(parts) < 2:
            continue
        minute_str, hour_str = parts[0], parts[1]
        if not (minute_str.isdigit() and hour_str.isdigit()):
            continue
        ticks.append((int(hour_str), int(minute_str)))
    return sorted(set(ticks))


def _to_minute(tick: tuple[int, int]) -> int:
    return tick[0] * 60 + tick[1]


def test_every_producer_tick_has_consumer_followup_with_headroom() -> None:
    p_ticks = _cron_ticks(_load(_PRODUCER))
    c_ticks = _cron_ticks(_load(_CONSUMER))
    assert p_ticks, f"{_PRODUCER.name} has no parseable cron ticks"
    assert c_ticks, f"{_CONSUMER.name} has no parseable cron ticks"

    consumer_minutes = sorted(_to_minute(t) for t in c_ticks)
    failures: list[str] = []
    for p in p_ticks:
        p_min = _to_minute(p)
        # First consumer tick at or after producer + headroom.
        candidates = [c for c in consumer_minutes if c >= p_min + _CRON_HEADROOM_MIN_MINUTES]
        if not candidates:
            failures.append(
                f"producer @ {p[0]:02d}:{p[1]:02d} UTC has no consumer tick "
                f"\u2265{_CRON_HEADROOM_MIN_MINUTES} min later on the same day"
            )
            continue
        gap = candidates[0] - p_min
        # Sanity: also ensure no consumer tick fires inside the headroom
        # (which would mean the consumer reads while the producer is still
        # writing).
        encroachers = [
            c for c in consumer_minutes if p_min < c < p_min + _CRON_HEADROOM_MIN_MINUTES
        ]
        if encroachers:
            failures.append(
                f"producer @ {p[0]:02d}:{p[1]:02d} UTC is followed too "
                f"closely by consumer tick(s) at minute(s) "
                f"{[divmod(m, 60) for m in encroachers]} (need \u2265"
                f"{_CRON_HEADROOM_MIN_MINUTES} min gap; got {gap})"
            )

    assert not failures, (
        "F-V6-C3 (2026-05-02) handoff headroom violation:\n  "
        + "\n  ".join(failures)
    )


def test_consumer_tick_count_matches_producer() -> None:
    """Each producer tick should have exactly one consumer follow-up — no
    silent drops, no duplicates."""
    p_ticks = _cron_ticks(_load(_PRODUCER))
    c_ticks = _cron_ticks(_load(_CONSUMER))
    assert len(c_ticks) == len(p_ticks), (
        f"Producer has {len(p_ticks)} cron ticks but consumer has "
        f"{len(c_ticks)} \u2014 either a producer run goes unconsumed or a "
        "consumer run fires without fresh upstream data."
    )


def test_workflow_files_exist() -> None:
    for path in (_PRODUCER, _CONSUMER):
        assert path.is_file(), f"Expected workflow file missing: {path}"
