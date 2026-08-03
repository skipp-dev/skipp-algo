"""Find assertions that can pass without having observed anything.

A check that reports green while its loop ran zero times is not a passing
check — it is an unobserved one. The repo already knows the failure mode:
34 places in ``tests/`` say "would pass vacuously" in prose, and at least
one pair of neighbouring tests shows someone healing one instance by hand
and leaving the identical one directly above it alone. What is missing is
not the insight and not the idiom, but the enforcement.

The analyzer rates a *claim*, not a test: a test can prove three things
honestly and carry one vacuum-prone assertion at the same time.

A claim is vacuum-prone when

1. an assertion is carried by an iteration (a ``for`` body containing an
   ``assert``, an ``assert all(...)``, or an ``assert not any(...)``), and
2. the iterated expression can be empty at runtime (see
   :func:`classify_iterable`), and
3. nothing in the same scope proves *that* expression non-empty
   (see :func:`witness_keys`).

Literals are deliberately out of scope: ``for flag in ("--a", "--b")`` and
``for i in range(3)`` cannot be empty, and treating them as suspects is what
made the throwaway prototype report 922 hits instead of a reviewable set.

CLI::

    python -m scripts.detect_vacuous_claims tests/
"""

from __future__ import annotations

import argparse
import ast
import sys
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

#: Calls that discover things at runtime. Each can legitimately find nothing.
DISCOVERY_ATTRS: frozenset[str] = frozenset(
    {"glob", "rglob", "iterdir", "finditer", "findall", "scandir"}
)

#: Wrappers that pass emptiness straight through.
_TRANSPARENT_CALLS: frozenset[str] = frozenset(
    {"sorted", "list", "set", "tuple", "frozenset", "reversed"}
)


@dataclass(frozen=True)
class VacuousClaim:
    """One assertion that can pass without observing anything."""

    path: str
    lineno: int
    test: str
    iterable: str
    kind: str

    @property
    def key(self) -> str:
        """Stable identity used by the exemption registry."""
        return f"{self.path}::{self.test}::{self.iterable}"


@dataclass(frozen=True)
class ScanResult:
    """What a scan looked at, next to what it found.

    ``files`` exists so callers can prove the scan observed something. A
    guard that asserts on ``claims`` alone has the very shape this module
    exists to forbid.
    """

    files: tuple[str, ...]
    claims: tuple[VacuousClaim, ...]


def _walk_own(node: ast.AST) -> Iterator[ast.AST]:
    """Walk *node* without descending into nested function definitions.

    Scope matters: an assertion inside a nested helper belongs to that
    helper, not to the test that defines it.
    """
    for child in ast.iter_child_nodes(node):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            continue
        yield child
        yield from _walk_own(child)


def classify_iterable(
    node: ast.expr,
    bindings: dict[str, str],
    helpers: dict[str, str],
) -> str | None:
    """Return a kind string when *node* can be empty at runtime, else ``None``.

    ``bindings`` maps local names to kinds, ``helpers`` maps function names
    to kinds; both are resolved by the caller so this stays a pure function.
    """
    if isinstance(node, ast.Call):
        func = node.func
        if isinstance(func, ast.Attribute):
            if func.attr in DISCOVERY_ATTRS:
                return "discovery call"
            if func.attr in helpers:
                return helpers[func.attr]
        if isinstance(func, ast.Name):
            if func.id in helpers:
                return helpers[func.id]
            if func.id in _TRANSPARENT_CALLS and node.args:
                return classify_iterable(node.args[0], bindings, helpers)
        return None
    if isinstance(node, (ast.ListComp, ast.SetComp, ast.GeneratorExp)):
        if any(generator.ifs for generator in node.generators):
            return "filtered comprehension"
        return classify_iterable(node.generators[0].iter, bindings, helpers)
    if isinstance(node, ast.Name):
        return bindings.get(node.id)
    if isinstance(node, ast.Attribute):
        return bindings.get(ast.unparse(node))
    return None


def _module_helpers(tree: ast.Module) -> dict[str, str]:
    """Map helper name -> kind for helpers that hand back an emptiable set."""
    helpers: dict[str, str] = {}
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for stmt in _walk_own(node):
            if isinstance(stmt, (ast.Return, ast.YieldFrom)) and stmt.value is not None:
                kind = classify_iterable(stmt.value, {}, helpers)
                if kind is not None:
                    helpers[node.name] = f"helper returns {kind}"
                    break
            if isinstance(stmt, ast.For) and any(
                isinstance(inner, (ast.Yield, ast.YieldFrom))
                for inner in _walk_own(stmt)
            ):
                kind = classify_iterable(stmt.iter, {}, helpers)
                if kind is not None:
                    helpers[node.name] = f"helper yields {kind}"
                    break
    return helpers


def _local_bindings(
    func: ast.FunctionDef | ast.AsyncFunctionDef,
    helpers: dict[str, str],
) -> dict[str, str]:
    """Map names assigned inside *func* to the kind of what they hold."""
    bindings: dict[str, str] = {}
    for stmt in _walk_own(func):
        if isinstance(stmt, ast.Assign):
            targets: list[ast.expr] = list(stmt.targets)
            value: ast.expr | None = stmt.value
        elif isinstance(stmt, ast.AnnAssign):
            targets = [stmt.target]
            value = stmt.value
        else:
            continue
        if value is None:
            continue
        kind = classify_iterable(value, bindings, helpers)
        if kind is None:
            continue
        for target in targets:
            if isinstance(target, ast.Name):
                bindings[target.id] = f"local {kind}"
    return bindings


def _iterating_asserts(
    func: ast.FunctionDef | ast.AsyncFunctionDef,
) -> Iterator[tuple[ast.expr, int]]:
    """Yield ``(iterated expression, lineno)`` for every assertion-bearing loop.

    Three syntactic positions carry the same semantics:

    * ``for x in Y: ... assert ...`` — zero iterations, zero assertions;
    * ``assert all(<genexp>)`` — ``all(())`` is ``True``;
    * ``assert not any(<genexp>)`` — ``any(())`` is ``False``.

    A bare ``assert any(<genexp>)`` is *not* included: over an empty
    iterable it is ``False``, so it fails loudly instead of silently.
    """
    for node in _walk_own(func):
        if isinstance(node, ast.For) and any(
            isinstance(inner, ast.Assert) for inner in _walk_own(node)
        ):
            yield node.iter, node.lineno
        if isinstance(node, ast.Assert):
            test = node.test
            negated = False
            if isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not):
                test, negated = test.operand, True
            if not (isinstance(test, ast.Call) and isinstance(test.func, ast.Name)):
                continue
            wanted = "any" if negated else "all"
            if test.func.id != wanted or not test.args:
                continue
            argument = test.args[0]
            if isinstance(argument, (ast.GeneratorExp, ast.ListComp, ast.SetComp)):
                yield argument, node.lineno


def _render(source: str, node: ast.expr) -> str:
    """Render *node* as the reviewer would read it: the source as written.

    This is the module's single rendering entry point. Anything that will be
    *compared* or used as an *identity* -- :attr:`VacuousClaim.iterable`,
    :attr:`VacuousClaim.key`, and (Task 2) a witness expression checked
    against an iterable string -- must go through this function and no
    other. Rendering an iterable through ``_render`` and a witness through
    ``ast.unparse`` would make matching ones fail silently on quote-style
    alone (``"*.py"`` vs ``'*.py'``); the guard must compare like with like.

    ``ast.unparse`` regenerates syntax from the tree and normalises string
    quoting along the way, so it cannot be used for a human-facing label. A
    bare generator expression that is the sole argument of a call (as in
    ``all(x for x in y)``) is one further wrinkle: CPython attributes the
    call's own parentheses to the ``GeneratorExp`` node's source span, so
    the raw segment reads ``(x for x in y)`` with parens nobody wrote around
    the generator itself; strip that one borrowed layer.

    Two more properties are required of the result, because it feeds both a
    one-line-per-claim CLI report and a "stable identity" key:

    * single-line -- an expression spanning several source lines (e.g. a
      generator expression whose ``for``/``if`` clauses are wrapped) must
      not turn into a multi-line label, so runs of whitespace (including
      the newlines and indentation ``get_source_segment`` preserves
      verbatim) collapse to one space;
    * total -- ``get_source_segment`` returns ``None`` for a synthesized
      node or when the source is unavailable; fall back to ``ast.unparse``
      rather than letting ``None`` reach a claim.
    """
    segment = ast.get_source_segment(source, node)
    if segment is None:
        segment = ast.unparse(node)
    elif isinstance(node, ast.GeneratorExp) and segment[0] == "(" and segment[-1] == ")":
        segment = segment[1:-1]
    return " ".join(segment.split())


def scan_source(source: str, path: str) -> list[VacuousClaim]:
    """Return every vacuum-prone claim in *source*.

    *path* is used verbatim in :attr:`VacuousClaim.path`; pass a
    repo-relative posix path so the keys stay stable across checkouts.
    """
    tree = ast.parse(source)
    helpers = _module_helpers(tree)
    claims: list[VacuousClaim] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        bindings = _local_bindings(node, helpers)
        for iterated, lineno in _iterating_asserts(node):
            kind = classify_iterable(iterated, bindings, helpers)
            if kind is None:
                continue
            claims.append(
                VacuousClaim(
                    path=path,
                    lineno=lineno,
                    test=node.name,
                    iterable=_render(source, iterated),
                    kind=kind,
                )
            )
    return claims


def scan_paths(paths: Iterable[Path]) -> ScanResult:
    """Scan every ``*.py`` file under *paths* (files are taken as given)."""
    files: list[str] = []
    claims: list[VacuousClaim] = []
    for entry in paths:
        candidates = sorted(entry.rglob("*.py")) if entry.is_dir() else [entry]
        for candidate in candidates:
            relative = candidate.resolve().relative_to(ROOT).as_posix()
            files.append(relative)
            claims.extend(
                scan_source(candidate.read_text(encoding="utf-8"), relative)
            )
    return ScanResult(files=tuple(files), claims=tuple(claims))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Find vacuum-prone assertions.")
    parser.add_argument(
        "paths",
        nargs="*",
        type=Path,
        default=[ROOT / "tests"],
        help="files or directories to scan (default: tests/)",
    )
    args = parser.parse_args(argv)
    result = scan_paths(args.paths)
    for claim in result.claims:
        print(f"{claim.path}:{claim.lineno}: {claim.test}: {claim.iterable} [{claim.kind}]")
    print(
        f"{len(result.files)} files scanned, {len(result.claims)} vacuum-prone claims",
        file=sys.stderr,
    )
    return 1 if result.claims else 0


if __name__ == "__main__":
    raise SystemExit(main())
