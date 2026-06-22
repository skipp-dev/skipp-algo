"""F2 spec-status flip helper (closes #45).

Invoked on the `plumbing_only → live` transition of the F2 contextual
promotion spec. Without this reset, the SPRT/rollback state file would
retain pre-flip evidence and either:

  (a) leak shadow-corpus posteriors into the live decision, or
  (b) keep the live SPRT in an indeterminate state until enough fresh
      days arrive.

Behaviour
---------
On a true `plumbing_only → live` flip the script:

  1. Appends a JSONL journal entry to
     ``artifacts/ci/f2/status_flip_journal.jsonl``:

     .. code-block:: json

         {"action": "sprt_state_reset",
          "reason": "status_flip_to_live",
          "at": "<UTC ISO>",
          "from": "plumbing_only",
          "to": "live",
          "state_existed": true,
          "rollback_history_reset": false}

  2. Deletes ``artifacts/ci/f2/sprt_state.json`` if present (no error
     when missing — the F2 SPRT does not persist state today; the file
     will only exist once a future SPRT cross-day persistence lands).

  3. With ``--reset-rollback-history``, also truncates the numeric
     delta ring ``artifacts/ci/f2/rollback_history.json`` to ``[]``.

For every non-flip transition (including ``live → live`` reruns) the
script writes a ``{"action": "noop", "reason": "non_flip_transition",
...}`` entry and leaves the state files alone. The caller controls
cadence; the helper itself is idempotent.

The journal lives in its own JSONL file (mirrors the existing
``artifacts/ci/f2/revert_journal.jsonl`` pattern) so it does not
collide with the numeric ``rollback_history.json`` schema that
:mod:`scripts.f2_append_rollback_history` maintains.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import tempfile
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

DEFAULT_STATE_PATH = Path("artifacts") / "ci" / "f2" / "sprt_state.json"
DEFAULT_JOURNAL_PATH = Path("artifacts") / "ci" / "f2" / "status_flip_journal.jsonl"
DEFAULT_ROLLBACK_HISTORY_PATH = Path("artifacts") / "ci" / "f2" / "rollback_history.json"

FLIP_FROM = "plumbing_only"
FLIP_TO = "live"


def _utc_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _append_journal(path: Path, entry: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(entry, sort_keys=False, ensure_ascii=True) + "\n"
    with path.open("a", encoding="utf-8") as fh:
        fh.write(line)


def _reset_rollback_history(path: Path) -> None:
    # Atomic write via tempfile + os.replace (matches
    # scripts.f2_rotate_rollback_history). Path.write_text is banned in
    # scripts/ by tests/test_no_direct_to_csv_in_production.py.
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        os.write(fd, b"[]\n")
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


def _last_recorded_boundary(journal_path: Path) -> str | None:
    """Return the ``boundary`` field from the most-recent journal entry that has one."""
    if not journal_path.exists():
        return None
    last: str | None = None
    with journal_path.open(encoding="utf-8") as fh:
        for raw in fh:
            raw = raw.strip()
            if not raw:
                continue
            try:
                entry = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if "boundary" in entry:
                last = entry["boundary"]
    return last


def flip_status(
    *,
    from_status: str,
    to_status: str,
    state_path: Path = DEFAULT_STATE_PATH,
    journal_path: Path = DEFAULT_JOURNAL_PATH,
    rollback_history_path: Path = DEFAULT_ROLLBACK_HISTORY_PATH,
    reset_rollback_history: bool = False,
    deploy_boundary: str | None = None,
    now: str | None = None,
) -> dict[str, Any]:
    """Execute the flip-status workflow and return the journal entry."""
    at = now or _utc_iso()
    is_flip = from_status == FLIP_FROM and to_status == FLIP_TO

    # Deploy-boundary reset: fires on any non-flip transition when the caller
    # supplies a boundary marker that differs from the last *recorded* boundary.
    # On the very first boundary observation (no previous entry) the boundary is
    # simply established without resetting the corpus.
    if deploy_boundary is not None and not is_flip:
        last_boundary = _last_recorded_boundary(journal_path)
        if last_boundary is None:
            # First-ever boundary: record it, do not reset.
            entry: dict[str, Any] = {
                "action": "noop",
                "reason": "deploy_boundary_established",
                "from": from_status,
                "to": to_status,
                "at": at,
                "boundary": deploy_boundary,
            }
            _append_journal(journal_path, entry)
            return entry
        if last_boundary != deploy_boundary:
            state_existed = state_path.exists()
            if state_existed:
                with suppress(FileNotFoundError):
                    state_path.unlink()
            entry = {
                "action": "sprt_state_reset",
                "reason": "deploy_boundary_change",
                "from": from_status,
                "to": to_status,
                "at": at,
                "state_existed": state_existed,
                "rollback_history_reset": False,
                "boundary": deploy_boundary,
            }
            _append_journal(journal_path, entry)
            return entry
        # Same boundary → noop
        entry = {
            "action": "noop",
            "reason": "deploy_boundary_unchanged",
            "from": from_status,
            "to": to_status,
            "at": at,
            "boundary": deploy_boundary,
        }
        _append_journal(journal_path, entry)
        return entry

    if not is_flip:
        entry: dict[str, Any] = {
            "action": "noop",
            "reason": "non_flip_transition",
            "from": from_status,
            "to": to_status,
            "at": at,
        }
        _append_journal(journal_path, entry)
        return entry

    state_existed = state_path.exists()
    if state_existed:
        with suppress(FileNotFoundError):
            state_path.unlink()

    rollback_reset = False
    if reset_rollback_history:
        _reset_rollback_history(rollback_history_path)
        rollback_reset = True

    entry = {
        "action": "sprt_state_reset",
        "reason": "status_flip_to_live",
        "from": from_status,
        "to": to_status,
        "at": at,
        "state_existed": state_existed,
        "rollback_history_reset": rollback_reset,
    }
    _append_journal(journal_path, entry)
    return entry


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--from",
        dest="from_status",
        required=True,
        help="Previous spec.status value (e.g. plumbing_only).",
    )
    parser.add_argument(
        "--to",
        dest="to_status",
        required=True,
        help="Current spec.status value (e.g. live).",
    )
    parser.add_argument(
        "--state-file",
        type=Path,
        default=DEFAULT_STATE_PATH,
        help=f"SPRT state file to delete on flip (default: {DEFAULT_STATE_PATH.as_posix()}).",
    )
    parser.add_argument(
        "--journal",
        type=Path,
        default=DEFAULT_JOURNAL_PATH,
        help=f"JSONL journal file to append to (default: {DEFAULT_JOURNAL_PATH.as_posix()}).",
    )
    parser.add_argument(
        "--rollback-history",
        type=Path,
        default=DEFAULT_ROLLBACK_HISTORY_PATH,
        help=(
            "Numeric rollback-history ring path "
            f"(default: {DEFAULT_ROLLBACK_HISTORY_PATH.as_posix()})."
        ),
    )
    parser.add_argument(
        "--reset-rollback-history",
        action="store_true",
        help="Also truncate the numeric rollback-history ring on flip.",
    )
    parser.add_argument(
        "--deploy-boundary",
        default=None,
        dest="deploy_boundary",
        help=(
            "Deploy-boundary marker (e.g. git SHA or hash of gate-code files). "
            "Triggers sprt_state_reset with reason=deploy_boundary_change when "
            "the marker differs from the last recorded boundary, even if the "
            "spec status remains live."
        ),
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    entry = flip_status(
        from_status=args.from_status,
        to_status=args.to_status,
        state_path=args.state_file,
        journal_path=args.journal,
        rollback_history_path=args.rollback_history,
        reset_rollback_history=args.reset_rollback_history,
        deploy_boundary=args.deploy_boundary,
    )
    print(json.dumps(entry, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
