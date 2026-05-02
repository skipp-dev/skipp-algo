"""Plan 2.8 run stamp emitter.

Writes a small JSON stamp describing the current run context
(``run_id``, ``run_url``, ``sha``, ``ref``, ``actor``,
``captured_at``). Designed to be dropped alongside weekly digest
artifacts so the artifact bundle is self-describing.

Values are read from the ``--run-id`` / ``--run-url`` / ``--sha`` /
``--ref`` / ``--actor`` flags; any unset value falls back to the
corresponding ``GITHUB_*`` environment variable, then to ``null``.

Pure stdlib.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
from pathlib import Path
from typing import Any

from scripts.smc_atomic_write import atomic_write_text


def _opt(value: str | None, env_key: str) -> str | None:
    if value:
        return value
    env_value = os.environ.get(env_key)
    if env_value:
        return env_value
    return None


def build(
    *,
    run_id: str | None = None,
    run_url: str | None = None,
    sha: str | None = None,
    ref: str | None = None,
    actor: str | None = None,
    now: _dt.datetime | None = None,
) -> dict[str, Any]:
    now_ = now or _dt.datetime.now(tz=_dt.UTC)
    return {
        "schema_version": 1,
        "run_id":       _opt(run_id, "GITHUB_RUN_ID"),
        "run_url":      run_url,
        "sha":          _opt(sha, "GITHUB_SHA"),
        "ref":          _opt(ref, "GITHUB_REF"),
        "actor":        _opt(actor, "GITHUB_ACTOR"),
        "captured_at":  now_.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }

# F-V6-A1.1 (2026-05-02): bootstrap root logging so the logger.info(...)
# progress messages this entry point emits actually surface in CI logs
# (default WARNING-only handler would drop them). Extends F-V5-A1-2 / #2012
# from the priority entry-point set to plan_2_8 aggregators + showcase.
try:
    from scripts._logging_init import init_cli_logging
except ImportError:  # script-style invocation: `python scripts/X.py`
    import sys as _v6a11_sys
    from pathlib import Path as _v6a11_Path

    _v6a11_sys.path.insert(0, str(_v6a11_Path(__file__).resolve().parents[1]))
    from scripts._logging_init import init_cli_logging  # type: ignore[no-redef]




def main(argv: list[str] | None = None) -> int:
    init_cli_logging()  # F-V6-A1.1 (2026-05-02)
    parser = argparse.ArgumentParser(
        description="Write a Plan 2.8 run stamp JSON.",
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--run-url", default=None)
    parser.add_argument("--sha", default=None)
    parser.add_argument("--ref", default=None)
    parser.add_argument("--actor", default=None)
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    stamp = build(
        run_id=args.run_id, run_url=args.run_url,
        sha=args.sha, ref=args.ref, actor=args.actor,
    )
    body = json.dumps(stamp, indent=2) + "\n"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(body, args.output)
    if not args.quiet:
        print(body, end="")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
