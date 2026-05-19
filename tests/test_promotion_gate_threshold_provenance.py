"""F-007: every `DEFAULT_*` threshold constant in `governance.promotion_gate`
must be documented in ADR-0008 (`docs/adr/0008-promotion-gate-thresholds.md`).

This is a discoverability + audit contract: if a new threshold is added
without an ADR row, the gate is no longer auditable from a single
source. Failing this test means: extend ADR-0008 with a row for the
missing threshold in the same commit.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GATE_PATH = ROOT / "governance" / "promotion_gate.py"
ADR_PATH = ROOT / "docs" / "adr" / "0008-promotion-gate-thresholds.md"

_DEFAULT_RE = re.compile(r"^DEFAULT_([A-Z0-9_]+)\s*=", re.MULTILINE)


def _gate_defaults() -> list[str]:
    text = GATE_PATH.read_text(encoding="utf-8")
    return _DEFAULT_RE.findall(text)


def test_adr_0008_exists() -> None:
    assert ADR_PATH.exists(), f"missing ADR file: {ADR_PATH}"


def test_every_default_threshold_is_documented_in_adr_0008() -> None:
    defaults = _gate_defaults()
    assert defaults, (
        "no DEFAULT_* constants found in governance/promotion_gate.py - "
        "regex broke or file was renamed"
    )
    adr_text = ADR_PATH.read_text(encoding="utf-8").lower()
    missing = [
        name for name in defaults
        if name.lower() not in adr_text
    ]
    assert not missing, (
        "ADR-0008 does not document the following DEFAULT_* thresholds: "
        f"{sorted(missing)}. Add a row to "
        "docs/adr/0008-promotion-gate-thresholds.md in the same commit."
    )
