"""Apply a snooze config to a Plan 2.8 trend digest.

Operations teams sometimes need to silence a known-noisy slice (e.g.
``5m/FVG``) for a bounded window while a fix ships. This helper
reads a simple JSON snooze file and strips matching entries from
``digest['alerts']`` in-place (returning a new dict; the input is not
mutated).

Snooze file shape::

    {
      "snoozes": [
        {
          "tf": "5m",
          "family": "FVG",
          "reason": "known ranging regime — see #1234",
          "expires": "2026-05-01T00:00:00Z"
        }
      ]
    }

Rules:

* ``tf`` / ``family`` are exact matches; missing keys match any.
* ``expires`` is optional; an absent or empty value snoozes
  indefinitely. An expired entry is ignored (i.e. the alert fires).
* ``reason`` is advisory only; surfaced in the digest's
  ``snoozed`` list for triage.

Pure stdlib.
"""

from __future__ import annotations

import argparse
import copy
import datetime as _dt
import json
import sys
from pathlib import Path
from typing import Any

from scripts.smc_atomic_write import atomic_write_text


def _parse_iso(ts: str) -> _dt.datetime:
    if ts.endswith("Z"):
        ts = ts[:-1] + "+00:00"
    return _dt.datetime.fromisoformat(ts)


def _now_utc() -> _dt.datetime:
    return _dt.datetime.now(_dt.UTC)


def _match(alert: dict[str, Any], entry: dict[str, Any]) -> bool:
    for key in ("tf", "family"):
        want = entry.get(key)
        if want is not None and alert.get(key) != want:
            return False
    return True


def _active(entry: dict[str, Any], *, now: _dt.datetime) -> bool:
    expires = entry.get("expires")
    if not expires:
        return True
    try:
        return _parse_iso(expires) > now
    except ValueError:
        # Invalid timestamps are treated as inactive so a typo can
        # never silently hide an alert.
        return False


def apply_snooze(
    digest: dict[str, Any],
    snooze_config: dict[str, Any],
    *,
    now: _dt.datetime | None = None,
) -> dict[str, Any]:
    """Return a copy of ``digest`` with snoozed alerts peeled off.

    Adds a ``snoozed`` key listing the (alert, reason) pairs that
    were suppressed, for downstream surfacing.
    """
    now_ = now or _now_utc()
    entries = [e for e in (snooze_config.get("snoozes") or [])
               if _active(e, now=now_)]
    alerts = digest.get("alerts") or []
    kept: list[dict[str, Any]] = []
    snoozed: list[dict[str, Any]] = []
    for alert in alerts:
        hit = next((e for e in entries if _match(alert, e)), None)
        if hit is None:
            kept.append(alert)
        else:
            snoozed.append({**alert, "snooze_reason": hit.get("reason") or "",
                            "snooze_expires": hit.get("expires") or ""})
    out = copy.deepcopy(digest)
    out["alerts"] = kept
    out["snoozed"] = snoozed
    return out

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
        description="Apply a snooze config to a Plan 2.8 trend digest JSON.",
    )
    parser.add_argument("--digest", type=Path, required=True,
                        help="Input digest JSON (from trend_digest --format json).")
    parser.add_argument("--snooze", type=Path, required=True,
                        help="Snooze config JSON file.")
    parser.add_argument("--output", type=Path, default=None,
                        help="Write the filtered digest to this path.")
    args = parser.parse_args(argv)

    try:
        digest = json.loads(args.digest.read_text(encoding="utf-8"))
        config = json.loads(args.snooze.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    out = apply_snooze(digest, config)
    body = json.dumps(out, indent=2) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(body, args.output)
    print(body, end="")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
