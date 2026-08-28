"""Pin: Databento producer → library-refresh consumer cron handoff window.

Audit follow-up to **F-V6-C3 (2026-05-02)** — cron-respacing companion to
`tests/test_workflow_databento_handoff_timeouts.py` (PR #2018, scheduled to
land independently).

Background
----------
Producer (`smc-databento-production-export-sharded.yml`) writes the daily
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
# F-V8-cutover (2026-05-18): the canonical scheduled producer is the
# sharded workflow. The monolithic `smc-databento-production-export.yml`
# is workflow_dispatch-only fallback and intentionally schedule-free, so
# this respacing contract is asserted against the sharded variant.
_PRODUCER = _REPO_ROOT / ".github" / "workflows" / "smc-databento-production-export-sharded.yml"
_CONSUMER = _REPO_ROOT / ".github" / "workflows" / "smc-library-refresh.yml"

# Floor-pin (NOT equals-pin): the consumer must wait *at least* this long
# after a producer tick before reading. Floor history:
#   F-V6-C3 (2026-05-02, PR #2018) — set to 60 when producer cap was 60.
#   F-V8-C3.1 (2026-05-02)        — left at 60 when cap moved to 120
#                                    (60-min margin of safety).
#   F-V8-C4  (2026-05-08)         — kept at 60 when cap moved to 240.
# Realised headroom is now 240 min (cron 12→16, 16→20 UTC). Keeping the
# floor at 60 lets a future re-tightening (e.g. once Step 6/6b/8 backend
# bias is resolved and the cap drops back to 120) happen without
# breaking this pin.
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


def test_the_consumer_keeps_the_fast_path_that_makes_fewer_ticks_safe() -> None:
    """Der Cron ist das Netz, ``workflow_run`` ist der Weg.

    Hier stand bis 2026-08-29 ein GLEICHHEITS-Pin (``len(c_ticks) ==
    len(p_ticks)``) mit der Begruendung "sonst geht ein Producer-Lauf
    unkonsumiert durch". Die traegt nur, wenn Cron der EINZIGE Konsumweg
    waere - er ist es nicht: der Consumer haengt zusaetzlich per
    ``workflow_run`` am Producer und startet bei JEDEM erfolgreichen
    Producer-Abschluss (im Workflow woertlich "primary fast path", der Cron
    "safety net"). Der Pin zaehlte also das Netz, als waere es der Weg, und
    erzwang neun volle Refresh-Laeufe pro Werktag ZUSAETZLICH zu den neun,
    die der Fast Path ohnehin ausloest.

    Gemessen 2026-08-27 ueber alle 414 Laeufe des Tages: 13 Refresh-Laeufe,
    951 Runner-Minuten - 17 % der gesamten Actions-Last des Repos. Die
    Netz-Kadenz sank daraufhin auf vier Ticks (13/17/21/23 UTC).

    Was den Vertrag jetzt haelt, ist staerker als eine Zahl:

    * ``test_every_producer_tick_has_consumer_followup_with_headroom``
      (oben) - jeder Producer-Tick hat weiter einen Netz-Tick >=60 min
      spaeter, und keiner faellt in ein Schreibfenster;
    * dieser Test - der Fast Path EXISTIERT. Faellt er weg, waeren die vier
      Ticks ploetzlich der einzige Weg, und die Refresh-Kadenz saenke still
      von "nach jedem Producer-Lauf" auf "viermal am Tag".
    """
    consumer = _load(_CONSUMER)
    triggers = consumer.get(True, consumer.get("on", {}))
    assert isinstance(triggers, dict), f"{_CONSUMER.name}: `on:` ist kein Mapping"

    fast_path = triggers.get("workflow_run")
    assert isinstance(fast_path, dict), (
        f"{_CONSUMER.name} hat keinen `workflow_run`-Trigger mehr. Die "
        "reduzierte Cron-Kadenz (4 statt 9 Ticks, 2026-08-29) ist NUR "
        "vertretbar, solange der Fast Path jeden Producer-Abschluss "
        "aufgreift."
    )
    watched = [str(w) for w in (fast_path.get("workflows") or [])]
    assert any("atabento" in w for w in watched), (
        f"{_CONSUMER.name}: `workflow_run` beobachtet {watched!r} - der "
        "Producer ist nicht darunter, der Fast Path zeigt ins Leere."
    )
    assert "completed" in (fast_path.get("types") or ["completed"]), (
        f"{_CONSUMER.name}: `workflow_run` reagiert nicht auf `completed`"
    )


def test_workflow_files_exist() -> None:
    for path in (_PRODUCER, _CONSUMER):
        assert path.is_file(), f"Expected workflow file missing: {path}"
