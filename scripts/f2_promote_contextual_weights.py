"""F2 contextual-weights manual promote (plan §2.3 F2 ``on_promote``).

Symmetric counterpart to :mod:`scripts.f2_revert_contextual_weights`.
Where Revert is automatic (fired by the daily workflow on rc=2),
Promote is intentionally **operator-driven**: the spec's
``on_promote`` action list is a manual follow-up after a clean SPRT
``accept_h1`` plus a clean rollback-history ring. This helper makes
the actual artifact mutation auditable and idempotent.

What it does
------------
Given the F2 spec, the most recent promotion-gate report (which must
have ``decision == 'promote'``), and the live treatment calibration
artifact:

  1. Validates the report's decision is ``promote`` (refuses otherwise
     unless ``--force`` is passed).
  2. Reads the treatment calibration JSON pointed at by the spec
     (``arms.treatment.calibration_artifact``).
  3. If the artifact has a top-level ``status`` field equal to
     ``shadow``, archives the live file to
     ``artifacts/ci/f2/contextual_calibration.archive/<stem>_<UTC-ISO>.json``
     and rewrites the live file with ``status=production`` and an
     appended ``promote_history`` entry. If the artifact is already
     ``production`` (or missing the status field), the script is a
     no-op for the artifact but still journals the run.
  4. Appends a JSON line to
     ``artifacts/ci/f2/promote_journal.jsonl`` with the timestamp,
     report path, decision, and the action taken.

Idempotent, atomic writes (tempfile + os.replace), no network.

Exit codes
----------
  0 = promote performed (or already production / journal-only no-op)
  1 = configuration error (missing spec/report/artifact, malformed
      JSON, decision != 'promote' without --force)
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

JOURNAL_DEFAULT = Path("artifacts/ci/f2/promote_journal.jsonl")
ARCHIVE_SUBDIR_DEFAULT = "contextual_calibration.archive"


# ---------------------------------------------------------------------------
# Atomic helpers (mirrors f2_revert_contextual_weights)
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


def promote_contextual_weights(
    *,
    spec_path: Path,
    report_path: Path,
    journal_path: Path = JOURNAL_DEFAULT,
    archive_dir: Path | None = None,
    force: bool = False,
    timestamp: str | None = None,
) -> dict[str, Any]:
    """Promote the contextual calibration artifact and journal the action."""
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

    # Spec-status guard (audit C1/C2/C3 follow-up). The `--force` switch
    # may bypass a non-promote *report* decision (e.g. operator override
    # during a known transient SPRT noise event), but it MUST NOT bypass
    # the spec-status gate: while `status != "live"`, the statistical
    # apparatus is known-broken and any "promote" outcome is meaningless.
    spec_status = spec.get("status", "registered")
    if spec_status != "live":
        raise ValueError(
            f"refusing to promote: spec.status={spec_status!r} "
            "(expected 'live'). Promote pathway is gated until the "
            "frozen treatment artifact (PR #43) and paired Brier-SPRT "
            "with cross-day state (PR #44) land. See "
            "docs/f2_contextual_promotion_decision_2026-04-21.md."
        )

    decision = report.get("decision")
    if decision != "promote" and not force:
        raise ValueError(
            f"refusing to promote: report decision is {decision!r}, "
            "expected 'promote' (pass --force to override)"
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
    if current_status != "shadow":
        record["action"] = "noop_already_production"
        record["current_status"] = current_status
        _atomic_append_line(journal_path, json.dumps(record))
        return record

    # Archive the live shadow file before mutating.
    if archive_dir is None:
        archive_dir = artifact_path.parent / ARCHIVE_SUBDIR_DEFAULT
    archive_path = archive_dir / f"{artifact_path.stem}_{stamp}.json"
    if archive_path.exists():
        raise ValueError(f"archive collision: {archive_path} already exists")
    _atomic_write_text(archive_path, json.dumps(artifact, indent=2) + "\n")

    # Mutate: status -> production, append promote_history entry.
    new_artifact = dict(artifact)
    new_artifact["status"] = "production"
    history = list(new_artifact.get("promote_history") or [])
    history.append({
        "promoted_at_utc": stamp,
        "from_status": "shadow",
        "report": str(report_path),
        "report_decision": decision,
        "archived_to": str(archive_path),
    })
    new_artifact["promote_history"] = history
    _atomic_write_text(artifact_path, json.dumps(new_artifact, indent=2) + "\n")

    record["action"] = "promoted"
    record["archived_to"] = str(archive_path)
    record["new_status"] = "production"
    _atomic_append_line(journal_path, json.dumps(record))
    return record


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Promote the F2 contextual calibration artifact after a clean promote decision."
    )
    parser.add_argument("--spec", type=Path, required=True,
                        help="Path to the F2 experiment spec JSON.")
    parser.add_argument("--report", type=Path, required=True,
                        help="Path to the promotion-gate JSON report (decision=promote).")
    parser.add_argument("--journal", type=Path, default=JOURNAL_DEFAULT,
                        help=f"JSONL journal to append to (default: {JOURNAL_DEFAULT}).")
    parser.add_argument("--archive-dir", type=Path, default=None,
                        help="Override archive directory for the live artifact "
                             f"(default: <artifact-parent>/{ARCHIVE_SUBDIR_DEFAULT}).")
    parser.add_argument("--force", action="store_true",
                        help="Allow promote even if report decision != 'promote'.")
    args = parser.parse_args(argv)

    try:
        record = promote_contextual_weights(
            spec_path=args.spec,
            report_path=args.report,
            journal_path=args.journal,
            archive_dir=args.archive_dir,
            force=args.force,
        )
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(record, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
