"""Pin: every ``.pine`` literal in :file:`pine_apply_surface_reduction.py`
must route through :func:`scripts.pine_path_resolver.resolve_pine_file`.

Audit follow-up to :file:`docs/reviews/2026-04-24-system-review.md` finding
**M-4** (Klasse #35, "Pine legacy hardcoded paths"): direct ``Path("X.pine")``
or ``open("X.pine")`` would silently bypass the resolver's search-dir order
(repo-root + ``pine/legacy/``). After D-1 v2 physical migration, files like
``QuickALGO.pine`` live under ``pine/legacy/`` — only the resolver finds
them, so any direct-path code would silent-break.

The pin AST-walks the script and collects every ``"...pine"`` string
constant. A literal is **accepted** when:

* it is the first positional argument to ``resolve_pine_file(...)``, OR
* it is an element of a ``List`` / ``Tuple`` literal that is the iterable
  of a ``for``-loop whose loop-variable is later passed to
  ``resolve_pine_file(...)`` inside the loop body.

Any other position (e.g. ``Path("X.pine")``, ``open("X.pine")``, plain
string concatenation) is rejected.
"""
from __future__ import annotations

import ast
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_TARGET = _REPO_ROOT / "pine_apply_surface_reduction.py"
_RESOLVER_NAME = "resolve_pine_file"
_PINE_SUFFIX = ".pine"


def _resolver_call_name(call: ast.Call) -> str | None:
    """Return the function name of *call* if it is a simple ``Name`` or
    ``Attribute`` access, else ``None``."""
    func = call.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _collect_direct_resolver_literal_lines(tree: ast.AST) -> set[int]:
    """Line numbers of literal first-args to ``resolve_pine_file(<lit>, ...)``."""
    accepted: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if _resolver_call_name(node) != _RESOLVER_NAME:
            continue
        if not node.args:
            continue
        first = node.args[0]
        if isinstance(first, ast.Constant) and isinstance(first.value, str):
            accepted.add(first.lineno)
    return accepted


def _collect_loop_resolver_literal_lines(tree: ast.AST) -> set[int]:
    """Line numbers of literals inside ``for x in [...]: resolve_pine_file(x)``
    constructs."""
    accepted: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.For):
            continue
        if not isinstance(node.target, ast.Name):
            continue
        loop_var = node.target.id
        if not isinstance(node.iter, (ast.List, ast.Tuple)):
            continue
        # Does the loop body call resolve_pine_file(loop_var, ...) ?
        body_module = ast.Module(body=list(node.body), type_ignores=[])
        used = False
        for inner in ast.walk(body_module):
            if not isinstance(inner, ast.Call):
                continue
            if _resolver_call_name(inner) != _RESOLVER_NAME:
                continue
            if not inner.args:
                continue
            arg0 = inner.args[0]
            if isinstance(arg0, ast.Name) and arg0.id == loop_var:
                used = True
                break
        if not used:
            continue
        for elt in node.iter.elts:
            if (
                isinstance(elt, ast.Constant)
                and isinstance(elt.value, str)
                and elt.value.endswith(_PINE_SUFFIX)
            ):
                accepted.add(elt.lineno)
    return accepted


def _collect_pine_literals(tree: ast.AST) -> list[tuple[str, int]]:
    out: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and node.value.endswith(_PINE_SUFFIX)
        ):
            out.append((node.value, node.lineno))
    return out


def test_target_file_exists_and_is_parseable() -> None:
    assert _TARGET.is_file(), f"missing pin target: {_TARGET}"
    ast.parse(_TARGET.read_text(encoding="utf-8"))


def test_every_pine_literal_routes_through_resolver() -> None:
    src = _TARGET.read_text(encoding="utf-8")
    tree = ast.parse(src)
    accepted = _collect_direct_resolver_literal_lines(
        tree
    ) | _collect_loop_resolver_literal_lines(tree)
    literals = _collect_pine_literals(tree)
    violations = [
        f"line {lineno}: {value!r}"
        for value, lineno in literals
        if lineno not in accepted
    ]
    assert not violations, (
        f"Every '*.pine' literal in {_TARGET.name} must be the first arg to "
        f"{_RESOLVER_NAME}(...) (directly or via a for-loop variable) so the "
        "search dirs (repo-root + pine/legacy/) stay enforced after D-1 v2 "
        "physical migration. Audit finding M-4 (Klasse #35).\n"
        "Violations:\n  " + "\n  ".join(violations)
    )
