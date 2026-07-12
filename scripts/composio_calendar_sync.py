"""Synchronize reviewed repo reminders into the operator Outlook calendar."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

try:
    import composio_ops
except ImportError:
    from scripts import composio_ops


def sync(path: Path, *, now: datetime | None = None, lookahead_days: int = 45) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    current = now or datetime.now(UTC)
    cutoff = current + timedelta(days=lookahead_days)
    results = []
    for event in payload.get("events", []):
        start = datetime.fromisoformat(str(event["start"]).replace("Z", "+00:00"))
        if not current <= start.astimezone(UTC) <= cutoff:
            continue
        identity = f"{event['subject']}|{event['start']}|{event['end']}"
        transaction_id = "skipp-" + hashlib.sha256(identity.encode()).hexdigest()[:24]
        result = composio_ops.create_outlook_event(
            str(event["subject"]),
            str(event["start"]),
            str(event["end"]),
            time_zone=str(event.get("time_zone", "Europe/Berlin")),
            body=str(event.get("body", "Managed from configs/composio_calendar_events.json")),
            transaction_id=transaction_id,
        )
        results.append({"subject": event["subject"], "ok": result.delivered, "detail": result.detail})
    return {"ok": all(item["ok"] for item in results), "events": results}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--events", type=Path, default=Path("configs/composio_calendar_events.json"))
    parser.add_argument("--lookahead-days", type=int, default=45)
    args = parser.parse_args(argv)
    report = sync(args.events, lookahead_days=args.lookahead_days)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
