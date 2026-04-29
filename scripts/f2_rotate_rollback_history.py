"""F2 rollback-history rotate/reset helper (plan §2.4 G2).

Operator-callable companion to :mod:`scripts.f2_append_rollback_history`.
After a rollback decision (gate exit code 2) fires and the operator has
performed the manual review checklist, the contextual arm's calibration
is either rolled back or held under review. Either way, the daily
feedback ring at ``artifacts/ci/f2/rollback_history.json`` MUST be reset
so the gate does not immediately re-fire on the next day's run from
stale history.

This helper:

  1. Archives the current history file to
     ``artifacts/ci/f2/rollback_history.archive/<UTC-ISO>.json`` (or a
     caller-supplied --archive-dir), preserving the audit trail.
  2. Replaces the live file with an empty list (default) or a caller-
     supplied seed (``--seed``).

Atomic write via tempfile + os.replace, same as the append helper.

Exit codes:
  0 = rotated successfully (or live file already empty/missing
      and --allow-empty was passed)
  1 = configuration error (e.g. live file missing without
      --allow-empty, malformed JSON, archive collision)
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import sys
import tempfile
from pathlib import Path
import contextlib

DEFAULT_ARCHIVE_SUBDIR = "rollback_history.archive"


def _utc_iso_compact() -> str:
    # 2026-04-21T10-00-00Z — colons swapped for dashes so it is a
    # safe filename on every filesystem.
    return _dt.datetime.now(tz=_dt.UTC).strftime("%Y-%m-%dT%H-%M-%SZ")


def _atomic_write_json(path: Path, data: list[float]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        os.write(fd, (json.dumps(data, indent=2) + "\n").encode("utf-8"))
        os.fsync(fd)
        os.close(fd)
        fd = -1
        os.replace(tmp, str(path))
    except BaseException:
        if fd >= 0:
            os.close(fd)
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def _load_history(path: Path) -> list[float]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError(
            f"history file {path} must contain a JSON list, got {type(raw).__name__}"
        )
    return [float(x) for x in raw]


def rotate_history(
    *,
    history_path: Path,
    archive_dir: Path | None = None,
    seed: list[float] | None = None,
    allow_empty: bool = False,
    timestamp: str | None = None,
) -> dict[str, object]:
    """Archive *history_path* and replace it with *seed* (default: empty).

    Returns a small dict describing the action taken (used by the CLI to
    print a JSON receipt).
    """
    if archive_dir is None:
        archive_dir = history_path.parent / DEFAULT_ARCHIVE_SUBDIR
    if seed is None:
        seed = []

    if not history_path.exists():
        if not allow_empty:
            raise ValueError(
                f"history file does not exist: {history_path} "
                f"(pass --allow-empty to create a fresh ring)"
            )
        _atomic_write_json(history_path, list(seed))
        return {
            "action": "created",
            "archived": None,
            "history_path": str(history_path),
            "new_len": len(seed),
        }

    existing = _load_history(history_path)

    stamp = timestamp or _utc_iso_compact()
    archive_path = archive_dir / f"{stamp}.json"
    if archive_path.exists():
        raise ValueError(f"archive collision: {archive_path} already exists")

    _atomic_write_json(archive_path, existing)
    _atomic_write_json(history_path, list(seed))

    return {
        "action": "rotated",
        "archived": str(archive_path),
        "archived_len": len(existing),
        "history_path": str(history_path),
        "new_len": len(seed),
    }


def _parse_seed(value: str | None) -> list[float] | None:
    if value is None:
        return None
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError(f"--seed must be valid JSON: {exc}") from exc
    if not isinstance(parsed, list):
        raise ValueError("--seed must be a JSON list of numbers")
    return [float(x) for x in parsed]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Archive and reset the F2 rollback-history ring."
    )
    parser.add_argument("--history", type=Path, required=True,
                        help="Path to the live rollback-history JSON list.")
    parser.add_argument("--archive-dir", type=Path, default=None,
                        help="Override archive directory "
                             f"(default: <history-parent>/{DEFAULT_ARCHIVE_SUBDIR}).")
    parser.add_argument("--seed", type=str, default=None,
                        help="Optional JSON list to seed the new ring (default: []).")
    parser.add_argument("--allow-empty", action="store_true",
                        help="Allow rotating when the live file does not exist "
                             "(creates a fresh ring instead of erroring).")
    args = parser.parse_args(argv)

    try:
        seed = _parse_seed(args.seed)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    try:
        receipt = rotate_history(
            history_path=args.history,
            archive_dir=args.archive_dir,
            seed=seed,
            allow_empty=args.allow_empty,
        )
    except (ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(receipt, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
