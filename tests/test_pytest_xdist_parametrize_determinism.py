"""Pin: ``@pytest.mark.parametrize`` argument sources are deterministically ordered.

Background
==========

PR #104 (Class #25) bug class: ``@pytest.mark.parametrize`` reading
its argument list from an unordered source (``set(...)``,
``dict.keys()`` on a non-ordered insertion, ``os.listdir(...)``,
``glob.glob(...)``) creates a worker-collection mismatch under
``pytest-xdist``: workers each evaluate the source independently and
may receive different orderings, leading to the controller dispatching
items the worker never collected.

This pin walks every test file's parametrize decorators and AST-checks
the argument expression: if it is a ``Call`` to ``set``, ``frozenset``,
``os.listdir``, ``glob.glob``, ``glob`` or a ``.keys()`` /
``.values()`` access without an enclosing ``sorted(...)``, the test
fails with the exact site.

Currently expected: 0 violations (verified by zero-hit grep at the
PR landing).
"""

from __future__ import annotations

import ast
from pathlib import Path

from tests._guard_corpus import parse_module

REPO_ROOT = Path(__file__).resolve().parent.parent
TESTS_DIR = REPO_ROOT / "tests"

# Calls whose result has a non-deterministic iteration order under xdist.
_NONDETERMINISTIC_CALL_NAMES: frozenset[str] = frozenset({
    "set",
    "frozenset",
    "listdir",  # os.listdir
    "glob",     # glob.glob OR plain glob
    "iterdir",  # Path.iterdir
    "scandir",  # os.scandir
})

# Method-attribute names that need wrapping in sorted() for determinism.
_NONDETERMINISTIC_METHODS: frozenset[str] = frozenset({
    "keys",
    "values",
    "items",
})


def _iter_test_files() -> list[Path]:
    return sorted(TESTS_DIR.rglob("test_*.py"))


def _is_parametrize_decorator(deco: ast.expr) -> bool:
    """Return True if ``deco`` is ``@pytest.mark.parametrize(...)``."""
    if not isinstance(deco, ast.Call):
        return False
    func = deco.func
    while isinstance(func, ast.Attribute):
        if func.attr == "parametrize":
            return True
        func = func.value
    return False


def _is_in_sorted(node: ast.AST, parents: dict[int, ast.AST]) -> bool:
    """Walk parents — return True if any ancestor is ``sorted(...)``."""
    current_id = id(node)
    while current_id in parents:
        parent = parents[current_id]
        if (
            isinstance(parent, ast.Call)
            and isinstance(parent.func, ast.Name)
            and parent.func.id == "sorted"
        ):
            return True
        current_id = id(parent)
    return False


def _build_parent_map(tree: ast.AST) -> dict[int, ast.AST]:
    out: dict[int, ast.AST] = {}
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            out[id(child)] = parent
    return out


def _classify_argument_source(arg: ast.expr) -> str | None:
    """Return a human-readable violation description, or None if OK."""
    if isinstance(arg, ast.Call):
        func = arg.func
        if isinstance(func, ast.Name) and func.id in _NONDETERMINISTIC_CALL_NAMES:
            return f"{func.id}(...)"
        if isinstance(func, ast.Attribute) and func.attr in _NONDETERMINISTIC_CALL_NAMES:
            return f"{func.attr}(...)"
        if isinstance(func, ast.Attribute) and func.attr in _NONDETERMINISTIC_METHODS:
            return f".{func.attr}()"
    if isinstance(arg, ast.Set | ast.SetComp):
        return "set literal/comprehension"
    return None


def _describe_reference_source(arg: ast.expr) -> str | None:
    """Return a human-readable description for a direct ``Name`` /
    ``Attribute`` source (e.g. ``REGIME_VALID_LABELS`` or
    ``mod.SOME_SET``)."""
    if isinstance(arg, ast.Name):
        return arg.id
    if isinstance(arg, ast.Attribute):
        parts: list[str] = []
        current: ast.expr = arg
        while isinstance(current, ast.Attribute):
            parts.append(current.attr)
            current = current.value
        if isinstance(current, ast.Name):
            parts.append(current.id)
        return ".".join(reversed(parts)) if parts else arg.attr
    return None


def _walk_arg_for_unsorted_source(arg: ast.expr, parents: dict[int, ast.AST]) -> list[str]:
    """Find non-deterministic sub-expressions not wrapped in sorted().

    Two flagged shapes:

    1. Direct calls / literals matched by :func:`_classify_argument_source`
       (``set(...)``, ``frozenset(...)``, ``os.listdir(...)``,
       ``glob.glob(...)``, ``.keys()`` / ``.values()`` / ``.items()``,
       set literals & comprehensions).
    2. ``list(<Name|Attribute>)`` / ``tuple(<Name|Attribute>)``
       pass-through wrappers around a non-literal source — the exact
       ``list(REGIME_VALID_LABELS)`` regression class from PR #104. The
       wrapper hides whether the inner iterable is ordered, and the AST
       cannot prove it; the wrapper itself is the smell.

    A bare ``Name`` / ``Attribute`` argument is **not** flagged on its
    own because a constant like ``parametrize('x', MY_LIST)`` is
    legitimately ordered. Wrap-detection covers the regression vector
    without false positives on ordered constants.

    Each unique kind is reported only once per parametrize site.
    """
    findings: list[str] = []
    seen: set[str] = set()
    for node in ast.walk(arg):
        kind: str | None = None

        # Shape 2: list(<Name|Attribute>) / tuple(<Name|Attribute>)
        # pass-through wrapper. We deliberately do NOT flag list([...])
        # / tuple((1,2,3)) — those wrap a literal-iterable inner that
        # is provably ordered.
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in {"list", "tuple"}
            and len(node.args) == 1
            and not node.keywords
            and isinstance(node.args[0], ast.Name | ast.Attribute)
        ):
            inner = _describe_reference_source(node.args[0])
            if inner is not None:
                kind = f"{node.func.id}({inner})"

        # Shape 1 fallback.
        if kind is None:
            kind = _classify_argument_source(node)
        if kind is None:
            continue
        if _is_in_sorted(node, parents):
            continue
        if kind in seen:
            continue
        seen.add(kind)
        findings.append(kind)
    return findings


def _collect_violations(path: Path) -> list[tuple[str, int, str, str]]:
    tree = parse_module(path)
    if tree is None:
        return []
    parents = _build_parent_map(tree)
    rel = str(path.relative_to(REPO_ROOT)).replace("\\", "/")
    out: list[tuple[str, int, str, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            # Decorators only attach to def/class — skip everything else.
            continue
        for deco in node.decorator_list:
            if not _is_parametrize_decorator(deco):
                continue
            assert isinstance(deco, ast.Call)
            # parametrize signature: parametrize("a,b", arg_source, ...)
            if len(deco.args) < 2:
                continue
            arg_source = deco.args[1]
            findings = _walk_arg_for_unsorted_source(arg_source, parents)
            for kind in findings:
                out.append((rel, deco.lineno, node.name, kind))
    return out


def test_no_parametrize_from_nondeterministic_source() -> None:
    """No parametrize decorator may consume an unordered iterable."""
    violations: list[str] = []
    for path in _iter_test_files():
        for rel, line, fn, kind in _collect_violations(path):
            violations.append(
                f"{rel}:{line} @pytest.mark.parametrize on `{fn}` reads "
                f"from {kind} without `sorted(...)`. Under pytest-xdist "
                "this is a worker-collection-mismatch trap (see PR #104). "
                "Wrap the source in `sorted(...)` to force deterministic order."
            )
    assert not violations, (
        "pytest-xdist determinism violations:\n  " + "\n  ".join(violations)
    )


def test_walker_visits_at_least_one_parametrize() -> None:
    """Belt-and-braces: walker must find at least one parametrize site."""
    total = 0
    for path in _iter_test_files():
        tree = parse_module(path)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
                for deco in node.decorator_list:
                    if _is_parametrize_decorator(deco):
                        total += 1
    assert total > 0, (
        "Walker found zero @pytest.mark.parametrize sites — the AST "
        "matcher may have drifted, or all parametrize tests were "
        "removed. Verify with: grep -rn '@pytest.mark.parametrize' tests/"
    )
