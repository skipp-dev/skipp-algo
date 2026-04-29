"""Defense-pin: zero-surface invariant for unsafe YAML loading + XML parsing.

Two adjacent CWE families that share a property worth pinning *jointly*
as a zero-surface invariant (sister of
``test_dynamic_exec_and_pickle_zero_surface.py``):

* **CWE-502 (unsafe YAML deserialization)**: ``yaml.load(...)``,
  ``yaml.load_all(...)``, ``yaml.full_load(...)``,
  ``yaml.full_load_all(...)``, ``yaml.unsafe_load(...)``,
  ``yaml.unsafe_load_all(...)``. PyYAML's ``yaml.load`` on untrusted
  input is arbitrary code execution; ``yaml.safe_load`` is the only
  generally safe variant.
* **CWE-611 (XML External Entity / XXE)**: any import of the standard
  ``xml.*`` family or third-party ``lxml`` / ``lxml.etree``. Python's
  stdlib XML parsers historically have XXE / billion-laughs / external
  DTD risks. Codebases that don't need XML at all are best off
  *forbidding* the import surface entirely.

Both surfaces are currently empty in this repo. The tests below pin
that fact so any reintroduction is a forced design decision.

Defense-only — no production code changes. Detection is conservative:

* YAML: only matches ``yaml.<unsafe_attr>(...)`` where ``yaml`` is a
  bare ``ast.Name``. Aliased imports (``import yaml as Y``) would
  bypass detection but are not used in this repo.
* XML: matches ``import <pkg>`` and ``from <pkg> import ...`` for any
  ``xml.*`` or ``lxml*`` module. This is intentionally broad — the
  whole family is XXE-adjacent and forbidding the import surface is
  the simplest invariant.
"""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

_DIR_EXCLUDE = frozenset(
    {
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
)

_YAML_UNSAFE_ATTRS = frozenset(
    {
        "load",
        "load_all",
        "full_load",
        "full_load_all",
        "unsafe_load",
        "unsafe_load_all",
    }
)


def _is_xml_family_module(module: str | None) -> bool:
    if not module:
        return False
    if module == "xml" or module.startswith("xml."):
        return True
    return bool(module == "lxml" or module.startswith("lxml."))


def _iter_first_party_py_files() -> list[Path]:
    out: list[Path] = []
    for path in ROOT.rglob("*.py"):
        try:
            rel_parts = path.relative_to(ROOT).parts
        except ValueError:
            continue
        if any(part in _DIR_EXCLUDE for part in rel_parts):
            continue
        out.append(path)
    return sorted(out)


def _scan_yaml_unsafe(tree: ast.AST) -> list[tuple[str, int]]:
    """Return [(attr, lineno), ...] for ``yaml.<unsafe>(...)`` calls."""
    out: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        if (
            isinstance(f, ast.Attribute)
            and f.attr in _YAML_UNSAFE_ATTRS
            and isinstance(f.value, ast.Name)
            and f.value.id == "yaml"
        ):
            out.append((f.attr, node.lineno))
    return out


def _scan_xml_imports(tree: ast.AST) -> list[tuple[str, int]]:
    """Return [(module_name, lineno), ...] for any xml/lxml imports."""
    out: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if _is_xml_family_module(alias.name):
                    out.append((alias.name, node.lineno))
        elif isinstance(node, ast.ImportFrom) and _is_xml_family_module(node.module):
            out.append((node.module or "", node.lineno))
    return out


def _parse(path: Path) -> ast.AST | None:
    try:
        source = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    try:
        return ast.parse(source, filename=str(path))
    except SyntaxError:
        return None


def test_no_yaml_unsafe_load_calls() -> None:
    """CWE-502 (YAML) invariant: no ``yaml.load(...)`` or related unsafe variants."""
    findings: list[str] = []
    for path in _iter_first_party_py_files():
        tree = _parse(path)
        if tree is None:
            continue
        rel = path.relative_to(ROOT).as_posix()
        for attr, lineno in _scan_yaml_unsafe(tree):
            findings.append(f"  - {rel}:{lineno}  yaml.{attr}(...)")
    assert not findings, (
        "YAML-unsafe surface re-opened — found unsafe yaml.load* call(s):\n"
        + "\n".join(findings)
        + "\n\nUse `yaml.safe_load(...)` / `yaml.safe_load_all(...)` "
        "instead. PyYAML's `yaml.load` on untrusted input is arbitrary "
        "code execution (CWE-502)."
    )


def test_no_xml_family_imports() -> None:
    """CWE-611 invariant: no imports of stdlib ``xml.*`` or ``lxml*``."""
    findings: list[str] = []
    for path in _iter_first_party_py_files():
        tree = _parse(path)
        if tree is None:
            continue
        rel = path.relative_to(ROOT).as_posix()
        for mod, lineno in _scan_xml_imports(tree):
            findings.append(f"  - {rel}:{lineno}  import {mod}")
    assert not findings, (
        "XML import surface re-opened — found xml.*/lxml* import(s):\n"
        + "\n".join(findings)
        + "\n\nThe stdlib `xml.*` parsers and `lxml` historically have "
        "XXE / billion-laughs / external-DTD risks (CWE-611). If XML "
        "parsing is genuinely required, prefer `defusedxml` and add the "
        "site to this test as an explicit exception with a justifying "
        "comment."
    )
