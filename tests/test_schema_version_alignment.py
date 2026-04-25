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
    """AST guard: no ``YYYY-MM-DD.N`` literal outside the canonical home.

    Walks ``ast.Constant`` string values (so the scan is quote-style
    agnostic and ignores ``#`` comments automatically) and skips
    docstring constants on Module/Class/Function/AsyncFunction nodes
    (so descriptive prose remains free).
    """
    import ast
    import re
    from pathlib import Path

    repo_root = Path(__file__).resolve().parent.parent
    pattern = re.compile(r"\d{4}-\d{2}-\d{2}\.\d+")

    def _docstring_constant_ids(tree: ast.AST) -> set[int]:
        """Return id() of every Constant node that is a docstring."""
        ids: set[int] = set()
        for node in ast.walk(tree):
            if isinstance(
                node,
                (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef),
            ):
                body = getattr(node, "body", None)
                if not body:
                    continue
                first = body[0]
                if (
                    isinstance(first, ast.Expr)
                    and isinstance(first.value, ast.Constant)
                    and isinstance(first.value.value, str)
                ):
                    ids.add(id(first.value))
        return ids

    for name in ("streamlit_terminal.py", "databento_volatility_screener.py"):
        text = (repo_root / name).read_text(encoding="utf-8")
        tree = ast.parse(text, filename=name)
        docstring_ids = _docstring_constant_ids(tree)
        violations: list[str] = []
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
                continue
            if id(node) in docstring_ids:
                continue
            if pattern.search(node.value):
                violations.append(f"  {name}:{node.lineno}: {node.value!r}")
        assert not violations, (
            f"{name} contains an inline date-suffix schema literal — "
            "import SESSION_SCHEMA_VERSION from "
            "smc_core.schema_version instead (H-6 alignment).\n"
            + "\n".join(violations)
        )
