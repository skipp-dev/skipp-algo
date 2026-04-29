"""Operator helper for ``configs/plan_2_8_snoozes.json``.

Manages the drift-alert snooze config without hand-editing JSON. All
commands are idempotent, write atomically, and preserve the
``_comment`` field the scaffold ships with.

Subcommands:
    add     — append a new snooze entry (tf, family?, reason?, expires?).
    list    — show current entries, optionally filtered to active ones.
    expire  — drop expired entries relative to ``--now`` or ``utcnow()``.
    rm      — drop entries matching tf (+optional family).

Pure stdlib, no third-party deps.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any
import contextlib

DEFAULT_CONFIG = Path("configs/plan_2_8_snoozes.json")


def _now(now: str | None) -> _dt.datetime:
    if now is None:
        return _dt.datetime.now(tz=_dt.UTC)
    ts = now[:-1] + "+00:00" if now.endswith("Z") else now
    return _dt.datetime.fromisoformat(ts)


def _load(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"snoozes": []}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or "snoozes" not in data:
        raise ValueError(f"malformed snooze config: {path}")
    if not isinstance(data["snoozes"], list):
        raise ValueError("'snoozes' must be a list")
    return data


def _save(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # Atomic write with tempfile + os.replace.
    fd, tmp = tempfile.mkstemp(
        dir=path.parent, prefix=".snoozes.", suffix=".json",
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            # ATOMIC-WRITE-EXEMPT: target ``fh`` is the tempfile descriptor
            # opened above; ``os.replace(tmp, path)`` below makes the write
            # atomic. Equivalent to ``atomic_write_json`` but inline because
            # we need a trailing newline + sort_keys=False semantics.
            json.dump(data, fh, indent=2, sort_keys=False)
            fh.write("\n")
        os.replace(tmp, path)
    except Exception:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def _expired(entry: dict[str, Any], now: _dt.datetime) -> bool:
    exp = entry.get("expires")
    if not exp:
        return False
    try:
        ts = exp[:-1] + "+00:00" if exp.endswith("Z") else exp
        return _dt.datetime.fromisoformat(ts) <= now
    except ValueError:
        return False


def add_entry(
    data: dict[str, Any],
    *,
    tf: str,
    family: str | None = None,
    reason: str | None = None,
    expires: str | None = None,
) -> dict[str, Any]:
    entry: dict[str, Any] = {"tf": tf}
    if family:
        entry["family"] = family
    if reason:
        entry["reason"] = reason
    if expires:
        entry["expires"] = expires
    data.setdefault("snoozes", []).append(entry)
    return data


def list_entries(
    data: dict[str, Any],
    *,
    only_active: bool = False,
    now: _dt.datetime | None = None,
) -> list[dict[str, Any]]:
    entries = list(data.get("snoozes") or [])
    if not only_active:
        return entries
    n = now or _dt.datetime.now(tz=_dt.UTC)
    return [e for e in entries if not _expired(e, n)]


def expire_entries(
    data: dict[str, Any],
    *,
    now: _dt.datetime,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    entries = list(data.get("snoozes") or [])
    kept = [e for e in entries if not _expired(e, now)]
    dropped = [e for e in entries if _expired(e, now)]
    data["snoozes"] = kept
    return data, dropped


def remove_entries(
    data: dict[str, Any],
    *,
    tf: str,
    family: str | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    entries = list(data.get("snoozes") or [])
    kept: list[dict[str, Any]] = []
    dropped: list[dict[str, Any]] = []
    for e in entries:
        match_tf = e.get("tf") == tf
        match_fam = family is None or e.get("family") == family
        if match_tf and match_fam:
            dropped.append(e)
        else:
            kept.append(e)
    data["snoozes"] = kept
    return data, dropped


def _cmd_add(args: argparse.Namespace) -> int:
    data = _load(args.config)
    add_entry(
        data, tf=args.tf, family=args.family,
        reason=args.reason, expires=args.expires,
    )
    _save(args.config, data)
    print(f"added snooze: tf={args.tf} family={args.family or '*'}")
    return 0


def _cmd_list(args: argparse.Namespace) -> int:
    data = _load(args.config)
    entries = list_entries(
        data, only_active=args.active, now=_now(args.now) if args.active else None,
    )
    if args.json:
        print(json.dumps(entries, indent=2))
    else:
        if not entries:
            print("(no entries)")
        for e in entries:
            print(f"- tf={e.get('tf')} family={e.get('family', '*')} "
                  f"expires={e.get('expires', 'never')} "
                  f"reason={e.get('reason', '-')}")
    return 0


def _cmd_expire(args: argparse.Namespace) -> int:
    data = _load(args.config)
    data, dropped = expire_entries(data, now=_now(args.now))
    _save(args.config, data)
    print(f"expired {len(dropped)} entries")
    return 0


def _cmd_rm(args: argparse.Namespace) -> int:
    data = _load(args.config)
    data, dropped = remove_entries(data, tf=args.tf, family=args.family)
    _save(args.config, data)
    print(f"removed {len(dropped)} entries")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Manage plan_2_8_snoozes.json entries.",
    )
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_add = sub.add_parser("add", help="Add a snooze entry.")
    p_add.add_argument("--tf", required=True)
    p_add.add_argument("--family", default=None)
    p_add.add_argument("--reason", default=None)
    p_add.add_argument("--expires", default=None,
                       help="ISO timestamp (e.g. 2026-05-01T00:00:00Z).")
    p_add.set_defaults(func=_cmd_add)

    p_list = sub.add_parser("list", help="List entries.")
    p_list.add_argument("--active", action="store_true",
                        help="Filter out expired entries.")
    p_list.add_argument("--now", default=None, help="Override 'now' for --active.")
    p_list.add_argument("--json", action="store_true")
    p_list.set_defaults(func=_cmd_list)

    p_exp = sub.add_parser("expire", help="Drop expired entries in place.")
    p_exp.add_argument("--now", default=None)
    p_exp.set_defaults(func=_cmd_expire)

    p_rm = sub.add_parser("rm", help="Drop entries matching tf (+family).")
    p_rm.add_argument("--tf", required=True)
    p_rm.add_argument("--family", default=None)
    p_rm.set_defaults(func=_cmd_rm)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (ValueError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
