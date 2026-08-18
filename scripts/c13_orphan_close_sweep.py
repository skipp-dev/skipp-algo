"""C13 orphan sweep — mark filled-but-never-closed audit records as documented orphans.

Context (#4848-Nacharbeit, 2026-08-19): before GTC exits + the EOD flatten
landed (#4848/#4852), the paper lane's bracket exits were DAY-tif and died at
the bell, so filled positions accumulated as zombies and were eventually
closed by a manual/global flatten that recorded **no per-fill close price**.
The originating ``cache/live/incubation_<DATE>.jsonl`` records therefore
carry ``action="filled"`` forever, and no later cron re-reads those day
files: measured on 2026-08-19, 38 such records across 12 day audits
(2026-07-13 .. 2026-08-18), zero in the commercial audits.

Their real close prices are unrecoverable (the fills exports carry only the
entry BUYs; the paper-TWS execution history is session-scoped), and
:mod:`scripts.backfill_live_outcomes` deliberately never invents an
execution. This sweep is the honest remainder: it stamps the records as
**documented orphans** — explicit ``outcome_status``, reason and timestamp —
so audits distinguish "never closed, accounted for" from "silently missing".

Rules:

* only records with ``action == "filled"`` and neither ``close_action`` nor
  any ``outcome_status`` are touched — closed, audit-only and already-marked
  records pass through byte-identical;
* only day files strictly BEFORE ``--before`` are touched (never the live
  trading day; the cutoff is explicit, this script reads no clock for it);
* no price, PnL or R-multiple key is ever written — orphans stay outcome-less;
* idempotent: a second run over the same tree changes nothing;
* dry-run by default, ``--apply`` writes (atomically, via the same writer as
  the backfill).
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import UTC, datetime
from pathlib import Path

from scripts.backfill_live_outcomes import (
    ORPHANED_STATUS,
    _atomic_write_jsonl,
    _load_jsonl,
)

# Phase-a day audits only; the commercial lane (incubation_commercial_*) has
# its own reconcile and carried zero orphans when this class was measured.
_DAY_AUDIT_RE = re.compile(r"^incubation_(\d{4}-\d{2}-\d{2})\.jsonl$")


def sweep(
    live_dir: Path,
    *,
    before: str,
    reason: str,
    apply: bool,
) -> dict[str, object]:
    """Scan day audits older than ``before`` and orphan-mark open fills."""
    files_scanned = 0
    files_changed = 0
    records_orphaned = 0
    records_left_open = 0  # filled-no-close ON/AFTER the cutoff: reported, never touched
    per_file: dict[str, int] = {}

    for path in sorted(live_dir.glob("incubation_*.jsonl")):
        match = _DAY_AUDIT_RE.match(path.name)
        if not match:
            continue
        file_date = match.group(1)
        records = _load_jsonl(path)
        files_scanned += 1
        changed = 0
        for record in records:
            is_open_fill = (
                record.get("action") == "filled"
                and not record.get("close_action")
                and not record.get("outcome_status")
            )
            if not is_open_fill:
                continue
            if file_date >= before:
                records_left_open += 1
                continue
            record["outcome_status"] = ORPHANED_STATUS
            record["orphan_reason"] = reason
            record["orphaned_at"] = datetime.now(UTC).isoformat()
            changed += 1
        if changed:
            per_file[path.name] = changed
            records_orphaned += changed
            files_changed += 1
            if apply:
                _atomic_write_jsonl(path, records)

    return {
        "orphan_sweep": {
            "live_dir": str(live_dir),
            "before": before,
            "dry_run": not apply,
            "files_scanned": files_scanned,
            "files_changed": files_changed,
            "records_orphaned": records_orphaned,
            "records_left_open_at_or_after_cutoff": records_left_open,
            "per_file": per_file,
        }
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--live-dir", type=Path, default=Path("cache/live"))
    parser.add_argument(
        "--before",
        required=True,
        help="ISO date (YYYY-MM-DD); only day audits strictly older are touched",
    )
    parser.add_argument(
        "--reason",
        required=True,
        help="explicit orphan_reason stamped onto every record (no default: "
        "each sweep run documents its own why)",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="write the stamps (default: dry-run, report only)",
    )
    args = parser.parse_args(argv)
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", args.before):
        parser.error("--before must be an ISO date (YYYY-MM-DD)")

    summary = sweep(
        args.live_dir,
        before=args.before,
        reason=args.reason,
        apply=args.apply,
    )
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
