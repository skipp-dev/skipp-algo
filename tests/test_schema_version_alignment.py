"""Pin: every sub-artifact schema version is sourced from the canonical
``smc_core.schema_version`` registry (H-6, system review 2026-04-24).

Why
---
Three modules previously each declared their own schema-version constant
in module-local literals:

  - ``smc_core/event_ledger.py::EVENT_LEDGER_SCHEMA_VERSION``
  - ``streamlit_terminal.py::_SESSION_SCHEMA_VERSION``
  - ``databento_volatility_screener.py::_DVS_SESSION_SCHEMA_VERSION``

Two of those (the Streamlit-app session-state cache busters) shared the
same value but were physically duplicated. A drift between them would
silently leave one app on the old value while the other invalidated —
so a derived cache could survive a schema bump in only one of the two.

Discipline
----------
Each downstream module must re-export from
``smc_core.schema_version`` rather than redefine the literal. This test
asserts:

  1. ``smc_core.schema_version`` exposes the canonical constants.
  2. The downstream-module aliases are the *same object* (string
     interning holds for the same literal but identity ``is`` is the
     stronger contract — they must come from the same import).
"""
from __future__ import annotations

import smc_core.schema_version as canonical


def test_canonical_module_exposes_subartifact_constants() -> None:
    assert hasattr(canonical, "SCHEMA_VERSION")
    assert hasattr(canonical, "EVENT_LEDGER_SCHEMA_VERSION")
    assert hasattr(canonical, "SESSION_SCHEMA_VERSION")


def test_event_ledger_uses_canonical_constant() -> None:
    from smc_core import event_ledger

    assert event_ledger.EVENT_LEDGER_SCHEMA_VERSION is canonical.EVENT_LEDGER_SCHEMA_VERSION, (
        "smc_core.event_ledger must re-export EVENT_LEDGER_SCHEMA_VERSION "
        "from smc_core.schema_version (H-6 alignment)"
    )


def test_streamlit_terminal_uses_canonical_session_version(monkeypatch) -> None:
    monkeypatch.setenv("_SMC_TERMINAL_TEST_MODE", "1")
    # Force a fresh import so the test-mode env var gates the streamlit import.
    import importlib
    import sys

    sys.modules.pop("streamlit_terminal", None)
    streamlit_terminal = importlib.import_module("streamlit_terminal")

    assert streamlit_terminal._SESSION_SCHEMA_VERSION is canonical.SESSION_SCHEMA_VERSION, (
        "streamlit_terminal._SESSION_SCHEMA_VERSION must be sourced from "
        "smc_core.schema_version.SESSION_SCHEMA_VERSION (H-6 alignment)"
    )


def test_databento_volatility_screener_uses_canonical_session_version() -> None:
    import databento_volatility_screener

    assert databento_volatility_screener._DVS_SESSION_SCHEMA_VERSION is canonical.SESSION_SCHEMA_VERSION, (
        "databento_volatility_screener._DVS_SESSION_SCHEMA_VERSION must be "
        "sourced from smc_core.schema_version.SESSION_SCHEMA_VERSION (H-6 alignment)"
    )


def test_no_duplicate_session_schema_literal_in_streamlit_modules() -> None:
    """Static guard: no ``"2026-04-...0"`` literal outside the canonical home."""
    from pathlib import Path
    import re

    repo_root = Path(__file__).resolve().parent.parent
    suspect = re.compile(r'"\d{4}-\d{2}-\d{2}\.\d+"')
    for name in ("streamlit_terminal.py", "databento_volatility_screener.py"):
        text = (repo_root / name).read_text(encoding="utf-8")
        # Strip comments before matching so doc-strings/comments don't fail.
        body_lines = [
            line.split("#", 1)[0]
            for line in text.splitlines()
        ]
        body = "\n".join(body_lines)
        matches = suspect.findall(body)
        assert not matches, (
            f"{name} contains an inline date-suffix schema literal "
            f"({matches}) — import SESSION_SCHEMA_VERSION from "
            "smc_core.schema_version instead (H-6 alignment)."
        )
