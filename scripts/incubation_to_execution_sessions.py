"""ADR-0023 §5 — adapt the C8 incubation ledger to execution sessions (CLI).

``scripts/calibrate_execution_costs.py`` expects the audit JSON written by
``scripts/run_ibkr_open_execution.py --supervisor-json``. No such file has ever
been produced: no job invokes that script, which is why §5 has only ever run on
the flat placeholder cost. The realized paper fills live in
``cache/live/incubation_*.jsonl`` instead.

This CLI converts those ledger files into one session document per trading day
and writes them where the calibrator can read them:

    python -m scripts.incubation_to_execution_sessions \\
        cache/live/incubation_*.jsonl --out-dir artifacts/ci/execution_sessions
    python -m scripts.calibrate_execution_costs \\
        artifacts/ci/execution_sessions/*.json --out calibration.json
    python -m scripts.run_epnl_after_cost_gate ... --cost-calibration calibration.json

The conversion rules — and what they deliberately refuse to invent — live in
:mod:`governance.incubation_sessions`.

Exit codes
----------
* ``0`` -- at least one session written.
* ``2`` -- nothing usable (every day excluded); the report is still written.
* ``1`` -- usage error, unreadable input, or a row that cannot be converted
  without guessing.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from governance.incubation_sessions import (
    IncubationConversionError,
    build_sessions,
    load_incubation_rows,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ledgers", nargs="+", help="cache/live/incubation_*.jsonl files")
    parser.add_argument(
        "--out-dir",
        required=True,
        help="directory for the per-day execution-session JSON files",
    )
    parser.add_argument(
        "--report",
        default="-",
        help="path for the conversion report, or '-' for stdout (default: stdout)",
    )
    args = parser.parse_args(argv)

    try:
        rows = load_incubation_rows(list(args.ledgers))
        sessions, report = build_sessions(rows)
    except (OSError, IncubationConversionError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    out_dir = Path(args.out_dir).expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)
    from scripts.smc_atomic_write import atomic_write_text

    written: list[str] = []
    for session in sessions:
        path = out_dir / f"execution_session_{session['session_date']}.json"
        atomic_write_text(json.dumps(session, indent=2, sort_keys=True) + "\n", str(path))
        written.append(str(path))

    payload = report.as_dict()
    payload["session_paths"] = written
    rendered = json.dumps(payload, indent=2, sort_keys=True)
    if args.report == "-":
        print(rendered)
    else:
        atomic_write_text(rendered + "\n", args.report)

    return 0 if written else 2


if __name__ == "__main__":
    raise SystemExit(main())
