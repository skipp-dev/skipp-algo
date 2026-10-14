"""Defense pin: every ``subprocess.run(...)`` call MUST pass an explicit
``check=`` keyword (CWE-754 — improper check of unusual or exceptional
condition).

Rationale
---------
``subprocess.run`` does **not** raise on non-zero exit by default. Forgetting
``check=`` therefore silently swallows command failures, which has caused
production regressions where the caller proceeded with an empty ``stdout``
under the illusion of success. By forcing every site to spell out
``check=True`` or ``check=False``, the intent is always explicit and reviewable.

Sister of the threading.Thread daemon= (#211), httpx timeout= (#208),
mkdir/makedirs exist_ok= (#216), tempfile.NamedTemporaryFile delete= (#207)
invariants. Today's surface: 7 sites, **100% compliant**.
"""
from __future__ import annotations

import ast
from pathlib import Path

from tests._guard_corpus import parse_module

_ROOT = Path(__file__).resolve().parents[1]

_DIR_EXCLUDE = {
    ".git",
    ".github",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "venv",
    "node_modules",
    "artifacts",
    "docs",
    "tests",
    "SMC++",
}


def _iter_python_files() -> list[Path]:
    out: list[Path] = []
    for path in _ROOT.rglob("*.py"):
        if any(part in _DIR_EXCLUDE for part in path.relative_to(_ROOT).parts):
            continue
        out.append(path)
    return out


def _scan_subprocess_run_without_check() -> list[tuple[str, int]]:
    offenders: list[tuple[str, int]] = []
    for path in _iter_python_files():
        tree = parse_module(path)
        if tree is None:
            continue
        rel = path.relative_to(_ROOT).as_posix()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not isinstance(func, ast.Attribute):
                continue
            if func.attr != "run":
                continue
            if not (isinstance(func.value, ast.Name) and func.value.id == "subprocess"):
                continue
            kw_names = {kw.arg for kw in node.keywords if kw.arg}
            if "check" not in kw_names:
                offenders.append((rel, node.lineno))
    return offenders


def test_subprocess_run_always_passes_check() -> None:
    offenders = _scan_subprocess_run_without_check()
    assert offenders == [], (
        "Every subprocess.run(...) call must pass an explicit check= keyword "
        f"(zero-surface invariant). Offenders: {offenders}"
    )
