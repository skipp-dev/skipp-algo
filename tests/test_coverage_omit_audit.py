"""Coverage omit audit contract.

Every entry in ``pyproject.toml::tool.coverage.run.omit`` must be documented in
``docs/coverage/coverage_omit_audit_2026-05-18.md``. This keeps omit-list debt
visible whenever the coverage gate is relaxed for a standalone CLI, probe, or
manual UI surface.
"""
from __future__ import annotations

import tomllib
from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parent.parent
_PYPROJECT = _REPO_ROOT / "pyproject.toml"
_AUDIT = _REPO_ROOT / "docs" / "coverage" / "coverage_omit_audit_2026-05-18.md"


def _coverage_omits() -> list[str]:
    with _PYPROJECT.open("rb") as fh:
        data = tomllib.load(fh)
    return list(data["tool"]["coverage"]["run"]["omit"])


def test_every_coverage_omit_is_audited() -> None:
    audit_text = _AUDIT.read_text(encoding="utf-8")
    missing = [pattern for pattern in _coverage_omits() if f"`{pattern}`" not in audit_text]
    assert missing == []


def test_coverage_omit_audit_declares_update_contract() -> None:
    audit_text = _AUDIT.read_text(encoding="utf-8")
    assert "A PR that changes `tool.coverage.run.omit` must also update this audit" in audit_text
