"""Defense-only pin: bound silent `except: pass` / `except: ...` sites.

Rationale (OWASP A09 Logging Failures + A04 Insecure Design):
- Silent except handlers swallow exceptions without log trail, hiding:
  - Auth/token failures, credential errors, network timeouts
  - Data-corruption bugs that should surface
  - Security-relevant exceptions (e.g. DecryptionError, SignatureError)
- Each new silent handler is a regression in observability + a
  potential MTTR amplifier under incident.
- This pin freezes today's count so any new silent handler requires
  explicit review (raise budget + justification or replace with
  `except SpecificError: logger.warning(...)`).

Drift detector: if total falls more than 5 below the budget, the test
fails and forces lowering the budget — preventing silent debt regrowth.
"""
from __future__ import annotations

import ast
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent

_DIR_EXCLUDE = frozenset({
    ".git", ".github", ".mypy_cache", ".pytest_cache", ".ruff_cache",
    ".venv", "venv", "node_modules", "artifacts", "docs", "scripts",
    "tests", "SMC++",
})

# Budget snapshot (2026-04-23): 66 silent except handlers across 28 files.
_SILENT_EXCEPT_BUDGET = 66
_DRIFT_TOLERANCE = 5


def _is_silent_handler(handler: ast.ExceptHandler) -> bool:
    body = handler.body
    if len(body) != 1:
        return False
    stmt = body[0]
    if isinstance(stmt, ast.Pass):
        return True
    if (
        isinstance(stmt, ast.Expr)
        and isinstance(stmt.value, ast.Constant)
        and stmt.value.value is Ellipsis
    ):
        return True
    return False


def _count_silent_excepts() -> int:
    total = 0
    for path in sorted(_REPO_ROOT.rglob("*.py")):
        if any(part in _DIR_EXCLUDE for part in path.relative_to(_REPO_ROOT).parts):
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError, OSError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ExceptHandler) and _is_silent_handler(node):
                total += 1
    return total


def test_silent_except_budget_not_exceeded() -> None:
    """Silent `except: pass`/`except: ...` count must not grow beyond budget."""
    actual = _count_silent_excepts()
    assert actual <= _SILENT_EXCEPT_BUDGET, (
        f"Silent except handler count {actual} exceeds budget "
        f"{_SILENT_EXCEPT_BUDGET}. New silent handlers swallow security-"
        "relevant exceptions (auth/token failures, decryption errors, network "
        "timeouts) and amplify incident MTTR. Either replace with "
        "`except SpecificError: logger.warning(...)`, or update "
        "_SILENT_EXCEPT_BUDGET with explicit justification."
    )


def test_silent_except_budget_drift_detector() -> None:
    """If actual count drops well below budget, force the budget to be lowered."""
    actual = _count_silent_excepts()
    assert actual >= _SILENT_EXCEPT_BUDGET - _DRIFT_TOLERANCE, (
        f"Silent except handler count {actual} is "
        f"{_SILENT_EXCEPT_BUDGET - actual} below budget "
        f"{_SILENT_EXCEPT_BUDGET} (tolerance={_DRIFT_TOLERANCE}). "
        "Lower _SILENT_EXCEPT_BUDGET to lock in the improvement and prevent "
        "silent regrowth."
    )
