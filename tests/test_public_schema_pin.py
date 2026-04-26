"""Schema-pin guard for the public calibration report (Sprint C5/C7).

This test pins the SHA256 of the source-of-truth blocks
(``PUBLIC_SCHEMA_VERSION`` + ``build_public_report``) in
``scripts/emit_public_calibration_report.py``. Any change to the
public-report contract must bump the pinned SHA *and* append an entry
to ``docs/calibration/schemas/v1.2.0_public_schema_pin.json::additive_fields_introduced``.

Drift policy
------------
If the source blocks change, this test fails. Remediation:

1. Decide whether the change is intentional and whether it breaks the
   public-report contract.
2. If breaking: bump ``PUBLIC_SCHEMA_VERSION`` (MAJOR per
   ``docs/schema_versioning.md`` if a field is removed/renamed; MINOR
   if additive), append a new ``additive_fields_introduced`` entry,
   write a ``CHANGELOG`` line plus an ADR, then update the SHA in the
   pinned JSON.
3. If non-breaking (cosmetic docstring, type-only refactor): just
   update the SHA.

Companion to ``tests/test_ml_input_schema_pin.py`` (C10 input schema).
"""

from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PIN_PATH = (
    REPO_ROOT
    / "docs"
    / "calibration"
    / "schemas"
    / "v1.2.0_public_schema_pin.json"
)
SOURCE_PATH = REPO_ROOT / "scripts" / "emit_public_calibration_report.py"


def _public_report_blocks() -> list[str]:
    src = SOURCE_PATH.read_text(encoding="utf-8")
    tree = ast.parse(src)
    blocks: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "build_public_report":
            blocks["build_public_report"] = ast.unparse(node)
        if isinstance(node, ast.Assign):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name) and tgt.id == "PUBLIC_SCHEMA_VERSION":
                    blocks["PUBLIC_SCHEMA_VERSION"] = ast.unparse(node)
    # Deterministic order: VERSION first, then build_public_report.
    return [blocks["PUBLIC_SCHEMA_VERSION"], blocks["build_public_report"]]


def _hash_blocks(blocks: list[str]) -> str:
    joined = "\n\n".join(blocks)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


def _load_pin() -> dict:
    return json.loads(PIN_PATH.read_text(encoding="utf-8"))


def test_pin_file_exists() -> None:
    assert PIN_PATH.is_file(), f"missing pin file at {PIN_PATH}"


def test_pin_documents_the_correct_module() -> None:
    pin = _load_pin()
    assert pin["pinned_module"] == "scripts/emit_public_calibration_report.py"
    assert set(pin["pinned_blocks"]) == {"PUBLIC_SCHEMA_VERSION", "build_public_report"}


def test_public_schema_version_matches_pin() -> None:
    from scripts.emit_public_calibration_report import PUBLIC_SCHEMA_VERSION

    pin = _load_pin()
    assert PUBLIC_SCHEMA_VERSION == pin["schema_version"], (
        f"PUBLIC_SCHEMA_VERSION ({PUBLIC_SCHEMA_VERSION}) drifted from "
        f"the pin ({pin['schema_version']}). Bump the pin and add an "
        "additive_fields_introduced entry."
    )


def test_pinned_sha_matches_source() -> None:
    pin = _load_pin()
    expected = pin["pinned_source_sha256"]
    actual = _hash_blocks(_public_report_blocks())
    assert actual == expected, (
        "scripts/emit_public_calibration_report.py PUBLIC_SCHEMA_VERSION + "
        f"build_public_report drifted relative to {PIN_PATH.name}. "
        f"Expected SHA {expected}, got {actual}. See module docstring "
        "for remediation steps."
    )


def test_additive_fields_history_is_monotonic() -> None:
    """Each historic schema version must list at least one additive
    field. This pins the audit trail so a future contributor cannot
    silently rewrite the additive ledger.
    """
    pin = _load_pin()
    additive = pin["additive_fields_introduced"]
    assert "1.1.0" in additive and "track_record_gate" in additive["1.1.0"]
    assert "1.2.0" in additive and "regime_stratified" in additive["1.2.0"]
