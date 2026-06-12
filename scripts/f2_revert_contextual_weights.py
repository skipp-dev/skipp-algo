"""F2 contextual-weights automatic revert (plan §2.4 G2).

The §2.4 G2 rule explicitly requires "automatic Revert + GitHub-Issue-
Ping" when the contextual arm is worse than the static arm in 2
consecutive runs. The Issue-Ping side ships in
:mod:`scripts.f2_render_rollback_issue` and the daily workflow. This
script is the *Revert* side: it deterministically demotes the
contextual calibration artifact back to a shadow state and journals
the operation so the daily run that fired the rollback leaves a clean
audit trail.

What it does
------------
Given the F2 spec, the most recent promotion-gate report (which must
have ``decision == 'rollback'``), and the live treatment calibration
artifact:

  1. Validates the report's decision is ``rollback`` (refuses to demote
     on any other decision unless ``--force`` is passed).
  2. Reads the treatment calibration JSON pointed at by the spec
     (``arms.treatment.calibration_artifact``).
  3. If the artifact has a top-level ``status`` field equal to
     ``production``, archives the live file to
     ``artifacts/ci/f2/contextual_calibration.archive/<UTC-ISO>.json``
     and rewrites the live file with ``status=shadow`` and an appended
     ``revert_history`` entry. If the artifact is already shadow
     (or missing the status field), the script is a no-op for the
     artifact but still journals the run.
  4. Appends a JSON line to
     ``artifacts/ci/f2/revert_journal.jsonl`` with the timestamp,
     report path, decision, and the action taken.

Idempotent, atomic writes (tempfile + os.replace), no network.

Exit codes
----------
  0 = revert performed (or already shadow / journal-only no-op)
  1 = configuration error (missing spec/report/artifact, malformed
      JSON, decision != 'rollback' without --force)
"""

from __future__ import annotations

import argparse
import contextlib
import datetime as _dt
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

JOURNAL_DEFAULT = Path("artifacts/ci/f2/revert_journal.jsonl")
ARCHIVE_SUBDIR_DEFAULT = "contextual_calibration.archive"


# ---------------------------------------------------------------------------
# Atomic helpers
# ---------------------------------------------------------------------------


def _utc_iso_compact() -> str:
    return _dt.datetime.now(tz=_dt.UTC).strftime("%Y-%m-%dT%H-%M-%SZ")


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        os.write(fd, text.encode("utf-8"))
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


def _atomic_append_line(path: Path, line: str) -> None:
    """Append a line to a JSONL file using read+write+atomic-replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    if existing and not existing.endswith("\n"):
        existing += "\n"
    _atomic_write_text(path, existing + line + "\n")


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Core
# ---------------------------------------------------------------------------


def revert_contextual_weights(
    *,
    spec_path: Path,
    report_path: Path,
    journal_path: Path = JOURNAL_DEFAULT,
    archive_dir: Path | None = None,
    force: bool = False,
    timestamp: str | None = None,
) -> dict[str, Any]:
    """Demote the contextual calibration artifact and journal the action.

    Returns a dict describing the action taken (also written to the
    journal as a single JSONL line).
    """
    if not spec_path.exists():
        raise ValueError(f"spec does not exist: {spec_path}")
    if not report_path.exists():
        raise ValueError(f"report does not exist: {report_path}")

    spec = _load_json(spec_path)
    if not isinstance(spec, dict):
        raise ValueError(f"spec {spec_path} must contain a JSON object")
    report = _load_json(report_path)
    if not isinstance(report, dict):
        raise ValueError(f"report {report_path} must contain a JSON object")

    decision = report.get("decision")
    if decision != "rollback" and not force:
        raise ValueError(
            f"refusing to revert: report decision is {decision!r}, "
            "expected 'rollback' (pass --force to override)"
        )

    treatment = (spec.get("arms") or {}).get("treatment") or {}
    artifact_str = treatment.get("calibration_artifact")
    if not artifact_str:
        raise ValueError(
            "spec is missing arms.treatment.calibration_artifact"
        )
    artifact_path = Path(artifact_str)

    stamp = timestamp or _utc_iso_compact()

    record: dict[str, Any] = {
        "schema_version": 1,
        "timestamp_utc": stamp,
        "spec": str(spec_path),
        "report": str(report_path),
        "report_decision": decision,
        "treatment_artifact": str(artifact_path),
        "force": force,
    }

    if not artifact_path.exists():
        record["action"] = "noop_missing_artifact"
        _atomic_append_line(journal_path, json.dumps(record))
        return record

    artifact = _load_json(artifact_path)
    if not isinstance(artifact, dict):
        raise ValueError(
            f"treatment artifact {artifact_path} must contain a JSON object, "
            f"got {type(artifact).__name__}"
        )

    current_status = artifact.get("status")
    if current_status != "production":
        record["action"] = "noop_already_shadow"
        record["current_status"] = current_status
        _atomic_append_line(journal_path, json.dumps(record))
        return record

    # Archive the live file before mutating.
    if archive_dir is None:
        archive_dir = artifact_path.parent / ARCHIVE_SUBDIR_DEFAULT
    archive_path = archive_dir / f"{artifact_path.stem}_{stamp}.json"
    if archive_path.exists():
        raise ValueError(f"archive collision: {archive_path} already exists")
    _atomic_write_text(archive_path, json.dumps(artifact, indent=2) + "\n")

    # Mutate: status -> shadow, append revert_history entry.
    new_artifact = dict(artifact)
    new_artifact["status"] = "shadow"
    history = list(new_artifact.get("revert_history") or [])
    history.append({
        "reverted_at_utc": stamp,
        "from_status": "production",
        "report": str(report_path),
        "report_decision": decision,
        "archived_to": str(archive_path),
    })
    new_artifact["revert_history"] = history
    _atomic_write_text(artifact_path, json.dumps(new_artifact, indent=2) + "\n")

    record["action"] = "reverted"
    record["archived_to"] = str(archive_path)
    record["new_status"] = "shadow"
    _atomic_append_line(journal_path, json.dumps(record))
    return record


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Demote the F2 contextual calibration artifact after a rollback decision."
    )
    parser.add_argument("--spec", type=Path, required=True,
                        help="Path to the F2 experiment spec JSON.")
    parser.add_argument("--report", type=Path, required=True,
                        help="Path to the promotion-gate JSON report (decision=rollback).")
    parser.add_argument("--journal", type=Path, default=JOURNAL_DEFAULT,
                        help=f"JSONL journal to append to (default: {JOURNAL_DEFAULT}).")
    parser.add_argument("--archive-dir", type=Path, default=None,
                        help="Override archive directory for the live artifact "
                             f"(default: <artifact-parent>/{ARCHIVE_SUBDIR_DEFAULT}).")
    parser.add_argument("--force", action="store_true",
                        help="Allow revert even if report decision != 'rollback'.")
    args = parser.parse_args(argv)

    try:
        record = revert_contextual_weights(
            spec_path=args.spec,
            report_path=args.report,
            journal_path=args.journal,
            archive_dir=args.archive_dir,
            force=args.force,
        )
    except (ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(record, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
