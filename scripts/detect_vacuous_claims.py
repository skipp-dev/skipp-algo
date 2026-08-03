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

#: Zero-argument constructors that produce an empty collection. Separate
#: from :data:`_TRANSPARENT_CALLS` on purpose: ``list(xs)`` passes ``xs``'s
#: emptiness through, while ``list()`` *is* the emptiness.
_EMPTY_CONSTRUCTORS: frozenset[str] = frozenset({"list", "set", "dict"})


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
    source: str,
    node: ast.expr,
    bindings: dict[str, str],
    helpers: dict[str, str],
) -> str | None:
    """Return a kind string when *node* can be empty at runtime, else ``None``.

    ``bindings`` maps local names *and dotted property names* to kinds,
    ``helpers`` maps function names to kinds; both are resolved by the caller
    so this stays a pure function. ``source`` is only used to render a dotted
    name through :func:`_render`, the module's single renderer, so that a
    binding and a lookup of the same property text always agree.
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
                return classify_iterable(source, node.args[0], bindings, helpers)
            if func.id in _EMPTY_CONSTRUCTORS and not node.args and not node.keywords:
                return "empty literal"
        return None
    if isinstance(node, (ast.ListComp, ast.SetComp, ast.GeneratorExp)):
        if any(generator.ifs for generator in node.generators):
            return "filtered comprehension"
        return classify_iterable(source, node.generators[0].iter, bindings, helpers)
    if isinstance(node, (ast.List, ast.Set, ast.Dict)):
        # An empty collection literal is the accumulator idiom's starting
        # point: ``calls = []``, something appends, a loop asserts. When the
        # code under test appends nothing, the loop runs zero times. A
        # literal *with* elements stays out for the reason the module
        # docstring gives for tuples — it cannot be empty at runtime.
        return None if _is_nonempty_literal(node) else "empty literal"
    if isinstance(node, ast.Name):
        return bindings.get(node.id)
    if isinstance(node, ast.Attribute):
        # Bounded on purpose, exactly as the TypeScript half is: only a dotted
        # name that :func:`_bind_assignments` actually *saw* being assigned
        # something emptiable resolves here. Classifying every property access
        # would report on objects whose contents the analyzer has never
        # observed — ``CONFIG.targets`` is not evidence of anything.
        return bindings.get(_render(source, node))
    return None


def _module_helpers(source: str, tree: ast.Module) -> dict[str, str]:
    """Map helper name -> kind for helpers that hand back an emptiable set."""
    helpers: dict[str, str] = {}
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for stmt in _walk_own(node):
            if isinstance(stmt, (ast.Return, ast.YieldFrom)) and stmt.value is not None:
                kind = classify_iterable(source, stmt.value, {}, helpers)
                if kind is not None:
                    helpers[node.name] = f"helper returns {kind}"
                    break
            if isinstance(stmt, ast.For) and any(
                isinstance(inner, (ast.Yield, ast.YieldFrom))
                for inner in _walk_own(stmt)
            ):
                kind = classify_iterable(source, stmt.iter, {}, helpers)
                if kind is not None:
                    helpers[node.name] = f"helper yields {kind}"
                    break
    return helpers


def _bind_assignments(
    source: str,
    stmts: Iterable[ast.AST],
    helpers: dict[str, str],
    seed: dict[str, str] | None = None,
) -> dict[str, str]:
    """Map assignment targets in *stmts* to the kind of what they hold.

    *seed* pre-populates the binding dict, and is how :func:`_local_bindings`
    hands in the produced properties. It has to be *in* the dict before the
    walk rather than merged into the result afterwards, because the
    classification of each assignment reads this same dict: ``keys =
    list(module._DERIVED_KEYS)`` only resolves if
    ``module._DERIVED_KEYS`` is already bound when that line is classified.
    A merge afterwards silently drops every value derived from a produced
    property. Assignments still win — they overwrite the seeded key.

    Shared by :func:`_module_bindings` and :func:`_local_bindings`: the
    ``Assign``/``AnnAssign`` handling and the ``classify_iterable`` call are
    identical between module scope and function scope — only which
    statements get fed in (``tree.body`` vs. :func:`_walk_own`) and what the
    result means differ. Keep that difference at the two named call sites,
    not duplicated in this logic.

    Two target shapes bind. A bare ``ast.Name`` is the obvious one. An
    ``ast.Attribute`` binds under its :func:`_render`ed dotted text, because
    a recording object is a lived idiom rather than a hypothetical: the
    TypeScript half found ``recording.filterCalls`` to be the *dominant*
    recording shape in ``automation/tradingview/tests`` and had to grow the
    same binding to see it. Without it, ``rec.calls = [p for p in
    ROOT.glob("*.py") if p.name]`` followed by ``for c in rec.calls: assert
    c`` reports nothing at all: :func:`classify_iterable` has an
    ``ast.Attribute`` branch, but no key it looks up could ever contain a
    dot, so the branch was unreachable.

    Boundedness is the same as the TypeScript half's and is the point: only
    a property the analyzer *watched* being assigned something emptiable
    becomes classifiable. An arbitrary attribute access whose producer was
    never seen stays unclassified rather than being guessed at.
    """
    bindings: dict[str, str] = dict(seed) if seed else {}
    for stmt in stmts:
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
        kind = classify_iterable(source, value, bindings, helpers)
        if kind is None:
            continue
        for target in targets:
            if isinstance(target, ast.Name):
                bindings[target.id] = f"local {kind}"
            elif isinstance(target, ast.Attribute):
                bindings[_render(source, target)] = f"local {kind}"
    return bindings


def _module_bindings(
    source: str, tree: ast.Module, helpers: dict[str, str]
) -> dict[str, str]:
    """Map module-level names to the kind of what they hold.

    ``argvalues`` is evaluated at import time, so module scope — not test
    scope — is what decides whether a parametrize set can be empty.
    """
    return _bind_assignments(source, tree.body, helpers)


def _parametrize_argvalues(
    node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef,
) -> Iterator[tuple[ast.expr, int]]:
    """Yield ``(argvalues expression, lineno)`` for every parametrize decorator.

    *node* is a function/method **or** a class: pytest applies a
    class-level ``@pytest.mark.parametrize`` to every test method on that
    class exactly as if each carried the decorator individually, so the
    class's own ``decorator_list`` must be inspected too — see
    :func:`scan_source`, which attributes a class-level hit to the class as
    a single claim rather than to each method.
    """
    for decorator in node.decorator_list:
        if not isinstance(decorator, ast.Call):
            continue
        target = decorator.func
        if not (isinstance(target, ast.Attribute) and target.attr == "parametrize"):
            continue
        # Only the positional ``argvalues`` form is recognised. The keyword
        # form ``parametrize("x", argvalues=CASES)`` is deliberately
        # unhandled: zero instances exist in tests/ today (verified by AST
        # scan), and adding a second lookup path for a shape nobody uses
        # would be speculative.
        if len(decorator.args) < 2:
            continue
        yield decorator.args[1], decorator.lineno


def _produced_names(func: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    """Names *func* bound to the result of a call, or to a ``with`` target.

    "Produced" is the whole boundedness rule of :func:`_produced_properties`
    and is deliberately narrow. ``out = run_walk_forward(...)`` produced an
    object here, so its fields hold runtime data. ``import x as mod`` and a
    module-level constant did not, and their attributes are source text the
    analyzer never watched being built — measured 2026-08-04, every such
    iterable in ``tests/`` resolves to a non-empty literal, so treating them
    as emptiable would only manufacture false positives.

    Tuple targets are excluded on purpose: ``(a,) = obj.instances`` unpacks
    an *attribute*, not a call, and following it would need the producer of
    ``obj`` — the very thing this rule refuses to guess at.
    """
    produced: set[str] = set()
    for stmt in _walk_own(func):
        if isinstance(stmt, ast.Assign) and isinstance(stmt.value, ast.Call):
            for target in stmt.targets:
                if isinstance(target, ast.Name):
                    produced.add(target.id)
        elif isinstance(stmt, ast.AnnAssign) and isinstance(stmt.value, ast.Call):
            if isinstance(stmt.target, ast.Name):
                produced.add(stmt.target.id)
        elif isinstance(stmt, (ast.With, ast.AsyncWith)):
            for item in stmt.items:
                if isinstance(item.optional_vars, ast.Name):
                    produced.add(item.optional_vars.id)
    return produced


def _produced_properties(
    source: str, func: ast.FunctionDef | ast.AsyncFunctionDef
) -> dict[str, str]:
    """Map ``obj.attr`` (rendered) -> kind for objects *func* produced.

    Returned as *bindings* rather than as a new argument to
    :func:`classify_iterable`, so the existing ``ast.Attribute`` branch
    there resolves them with no signature change — and so a real binding
    from :func:`_bind_assignments` always wins, because the caller merges
    these in with ``setdefault``.

    Every key goes through :func:`_render`, the module's single renderer.
    Rendering a binding one way and the lookup another is the defect this
    module was corrected for once already: the two sides stop matching on
    quote style alone and nothing says so.
    """
    produced = _produced_names(func)
    properties: dict[str, str] = {}
    for node in _walk_own(func):
        if not isinstance(node, ast.Attribute):
            continue
        base: ast.expr = node
        while isinstance(base, ast.Attribute):
            base = base.value
        if isinstance(base, ast.Name) and base.id in produced:
            properties[_render(source, node)] = "property of a produced object"
    return properties


def _subset_bindings(
    source: str, func: ast.FunctionDef | ast.AsyncFunctionDef
) -> dict[str, set[str]]:
    """Map a name assigned a comprehension -> the base that comprehension iterates.

    A non-empty *subset* proves the set it was drawn from non-empty: if
    ``[row for row in profile.rows if row.total > 0]`` has an element, then
    ``profile.rows`` had one. That direction is sound, and it is the exact
    inverse of the one :func:`_witness_candidates` refuses — a non-empty
    base says nothing about a filtered comprehension over it, because the
    filter can empty the result.

    Only the first generator's iterable is recorded. With a second ``for``
    clause a non-empty result proves that *some* inner iterable was
    non-empty, not the one any particular loop iterates, so accepting the
    rest would fabricate a witness.

    Generator expressions are excluded, and that is not an oversight. The
    witness this feeds is ``assert nonzero`` — and a generator *object* is
    truthy whether or not it will yield anything, so the assertion passes
    over an empty base and crediting it would manufacture the proof. A list
    or set comprehension is a real container whose truthiness is its
    non-emptiness. ``len()`` of a generator raises, so the length-check path
    cannot reach one either.
    """
    subsets: dict[str, set[str]] = {}
    for stmt in _walk_own(func):
        if not isinstance(stmt, ast.Assign):
            continue
        value = stmt.value
        if not isinstance(value, (ast.ListComp, ast.SetComp)):
            continue
        base = _render(source, value.generators[0].iter)
        for target in stmt.targets:
            if isinstance(target, ast.Name):
                subsets.setdefault(target.id, set()).add(base)
    return subsets


def _local_bindings(
    source: str,
    func: ast.FunctionDef | ast.AsyncFunctionDef,
    helpers: dict[str, str],
) -> dict[str, str]:
    """Map names assigned inside *func* to the kind of what they hold.

    The produced properties are *seeded* into :func:`_bind_assignments`
    rather than merged into its result. Merging afterwards looks equivalent
    and is not: each assignment is classified against the dict as it stands
    at that moment, so ``keys = list(module._DERIVED_KEYS)`` would be
    classified before ``module._DERIVED_KEYS`` existed as a binding and
    ``keys`` would bind to nothing at all. Seeding also keeps the intended
    precedence — a dotted name the function was seen assigning something
    emptiable carries a more specific kind than "some field of an object we
    produced", and that assignment overwrites the seeded entry.
    """
    return _bind_assignments(
        source, _walk_own(func), helpers, seed=_produced_properties(source, func)
    )


def _is_nonempty_length_check(op: ast.cmpop, right: ast.expr) -> bool:
    """True when ``len(x) <op> <right>`` proves ``x`` non-empty."""
    if not (isinstance(right, ast.Constant) and isinstance(right.value, int)):
        return False
    if isinstance(op, ast.Gt):
        return right.value >= 0
    if isinstance(op, (ast.GtE, ast.Eq)):
        return right.value >= 1
    return False


def _is_nonempty_literal(node: ast.expr) -> bool:
    """True for literals that cannot be empty."""
    if isinstance(node, (ast.List, ast.Set, ast.Tuple)):
        return bool(node.elts)
    if isinstance(node, ast.Dict):
        return bool(node.keys)
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return bool(node.value)
    return False


#: Context managers that may turn a failing ``assert`` into a passing test.
#: ``raises`` and its ``unittest`` spellings expect an exception; ``suppress``
#: discards one.
_ASSERTION_INVERTING_CONTEXTS: frozenset[str] = frozenset(
    {"raises", "assertRaises", "assertRaisesRegex", "assertRaisesRegexp", "suppress"}
)

#: Exception types that actually catch a failing ``assert``. Anything else
#: (``ValueError``, …) lets the ``AssertionError`` propagate, so the test
#: still goes red -- see :func:`_swallows_assertion_error`.
_ASSERTION_ERROR_TYPES: frozenset[str] = frozenset(
    {"AssertionError", "Exception", "BaseException"}
)


def _called_name(node: ast.expr) -> str | None:
    """The trailing name of a call target: ``pytest.raises`` -> ``raises``."""
    if not isinstance(node, ast.Call):
        return None
    target = node.func
    if isinstance(target, ast.Attribute):
        return target.attr
    if isinstance(target, ast.Name):
        return target.id
    return None


def _inverts_assertions(stmt: ast.With | ast.AsyncWith) -> bool:
    """True when *stmt* may turn a failing assertion into a passing test.

    Deliberately type-blind, and that is the right reading for the one thing
    it is used for: deciding whether an assert inside the block may be
    *hoisted out* of it as a witness for the enclosing block
    (:func:`_unconditional_asserts`). It may not, whatever exception is
    expected — an earlier statement in the block can raise that exception
    and exit before the assert is ever reached, leaving the enclosing block
    with a witness that never ran.

    For the narrower question "does a failing assert *inside* this block
    still fail the test", the exception type decides and the answer lives in
    :func:`_swallows_assertion_error`.
    """
    return any(_called_name(item.context_expr) in _ASSERTION_INVERTING_CONTEXTS
               for item in stmt.items)


def _swallows_assertion_error(stmt: ast.With | ast.AsyncWith) -> bool:
    """True when a failing ``assert`` inside *stmt* leaves the test green.

    This is the polarity inversion one scope level below the one
    :func:`_unconditional_asserts` rejects, and it is narrower than
    :func:`_inverts_assertions` on purpose. Measured, all five shapes::

        pytest.raises(AssertionError)   assert [] -> test GREEN
        pytest.raises(Exception)        assert [] -> test GREEN
        suppress(AssertionError)        assert [] -> test GREEN
        pytest.raises(ValueError)       assert [] -> test RED
        suppress(ValueError)            assert [] -> test RED

    Under ``pytest.raises(ValueError)`` the ``AssertionError`` does not
    match, propagates, and fails the run — so the witness is genuine and
    voiding it would be a fabricated claim. Only a context that catches
    ``AssertionError`` itself (directly, or via ``Exception`` /
    ``BaseException``) reads an assertion *expected to fail* as proof of
    non-emptiness.

    A bare ``suppress()`` or a non-literal exception expression yields
    ``False``: it catches nothing this analyzer can see, and guessing in the
    direction of voiding a real witness is the failure this module treats as
    the worse one.
    """
    for item in stmt.items:
        call = item.context_expr
        if _called_name(call) not in _ASSERTION_INVERTING_CONTEXTS:
            continue
        if any(
            name in _ASSERTION_ERROR_TYPES
            for argument in call.args  # type: ignore[union-attr]
            for name in _exception_names(argument)
        ):
            return True
    return False


def _exception_names(node: ast.expr) -> Iterator[str]:
    """Yield the trailing name of each exception type named by *node*.

    Handles the bare name, the dotted form, and the tuple form
    ``pytest.raises((AssertionError, ValueError))``.
    """
    if isinstance(node, ast.Tuple):
        for element in node.elts:
            yield from _exception_names(element)
    elif isinstance(node, ast.Attribute):
        yield node.attr
    elif isinstance(node, ast.Name):
        yield node.id


def _unconditional_asserts(
    body: Iterable[ast.stmt],
) -> Iterator[ast.Assert]:
    """Yield the asserts that run every time *body* runs.

    A witness has to be *executed* to prove anything, and it proves it only
    for the block it runs in — hence this is deliberately shallow. It takes
    one block's statements, not a whole function; :func:`_block_claims`
    walks the nesting and hands each block its own witnesses plus the ones
    inherited from the blocks above it.

    Accepted from *body*:

    * an ``assert`` written directly in it — unconditional by construction;
    * the asserts of a nested ``with`` whose context managers are not in
      :data:`_ASSERTION_INVERTING_CONTEXTS`. ``with
      tempfile.TemporaryDirectory() as d:`` is a lived witness site and
      entering the block does not make the assert conditional; hoisting
      those into the enclosing block costs nothing and keeps the idiom
      working.

    Not accepted, so they do not leak upwards: ``if``/``else``,
    ``for``/``while``, ``match`` and all four ``try`` limbs, plus any
    ``with`` that inverts assertion polarity. The first two are the
    reachability cases — a branch may not be taken and a loop may run zero
    times, and a "witness" that is itself vacuum-prone must not exonerate
    anything. ``with pytest.raises(AssertionError): assert hits`` is the
    polarity inversion: there the assertion is *expected to fail*, so
    reading it as proof of non-emptiness inverts its meaning — the same
    mistake the TypeScript half guards against explicitly. ``try`` is
    excluded even for its ``body``, which is reached: ``try: assert
    xs\\nexcept AssertionError: pass`` is that inversion one keyword
    further away.

    None of this stops the sound in-loop idiom
    ``for pat in PATTERNS: matched = ...; assert matched; for m in
    matched: ...``, because there the witness and the loop it covers share
    one block — see :func:`_block_claims`.

    Residual, stated rather than hidden: a custom context manager whose
    ``__exit__`` returns truthy also swallows the ``AssertionError`` while
    not being named in the set above. Resolving that needs the manager's
    definition, which this AST-only analyzer does not have.
    """
    for stmt in body:
        if isinstance(stmt, ast.Assert):
            yield stmt
        elif isinstance(stmt, (ast.With, ast.AsyncWith)) and not _inverts_assertions(stmt):
            yield from _unconditional_asserts(stmt.body)


def _comprehension_base(source: str, node: ast.expr) -> set[str]:
    """The base a *non-empty* comprehension *node* proves non-empty.

    If ``[f(x) for x in xs if p(x)]`` has an element, then some element of
    ``xs`` reached the filter, so ``xs`` was non-empty. Filters and further
    ``for`` clauses can only shrink the result, so the *first* generator's
    iterable is proven whatever they do — which makes this the inline
    spelling of the rule :func:`_subset_bindings` records for a
    comprehension that was given a name.

    The caller is responsible for having established that the comprehension
    really is non-empty. That is why this is not folded into
    :func:`_witnessed_by`: a bare ``assert (x for x in xs)`` establishes
    nothing at all, because a generator object is always truthy.
    """
    if isinstance(node, (ast.ListComp, ast.SetComp, ast.GeneratorExp)):
        return {_render(source, node.generators[0].iter)}
    return set()


def _witnessed_by(
    source: str, node: ast.expr, subsets: dict[str, set[str]] | None
) -> set[str]:
    """The keys proven non-empty by a witness written about *node*.

    Always the node's own rendering. Additionally, when *node* is a name
    bound to a comprehension, the base that comprehension was drawn from —
    see :func:`_subset_bindings` for why that direction is sound and the
    other one is not.
    """
    keys = {_render(source, node)}
    if subsets and isinstance(node, ast.Name):
        keys |= subsets.get(node.id, set())
    return keys


def witness_keys(
    source: str,
    body: Iterable[ast.stmt],
    subsets: dict[str, set[str]] | None = None,
) -> set[str]:
    """Return the expressions *body* itself proves non-empty.

    Four forms, all of them already lived in this repo (spec §5):
    ``assert xs``, ``assert len(xs) >= n``, ``assert xs == <non-empty
    literal>``, and — handled in :func:`_exhaustion_raises` — a ``raise``
    reached by exhausting the loop.

    Scoped to one block on purpose, and never across a function boundary. A
    witness for ``bool_lines`` says nothing about ``export_lines`` two lines
    above it, and one inside a branch that may not be taken says nothing at
    all — see :func:`_unconditional_asserts`.

    Every key is rendered through :func:`_render`, the same renderer
    :func:`scan_source` uses for the iterable it is compared against.
    ``ast.unparse`` normalises string quoting (``"*.py"`` -> ``'*.py'``), so
    rendering the two sides differently would make a witness for
    ``ROOT.glob("*.py")`` never match the identically-written loop.
    """
    keys: set[str] = set()
    for node in _unconditional_asserts(body):
        test = node.test
        if isinstance(test, ast.Compare) and len(test.ops) == 1:
            left = test.left
            op = test.ops[0]
            right = test.comparators[0]
            if (
                isinstance(left, ast.Call)
                and isinstance(left.func, ast.Name)
                and left.func.id == "len"
                and left.args
            ):
                if _is_nonempty_length_check(op, right):
                    keys |= _witnessed_by(source, left.args[0], subsets)
                    keys |= _comprehension_base(source, left.args[0])
                continue
            if isinstance(op, ast.Eq) and _is_nonempty_literal(right):
                keys |= _witnessed_by(source, left, subsets)
                keys |= _comprehension_base(source, left)
            elif isinstance(op, ast.In):
                # ``x in y`` cannot hold of an empty ``y``. The ``not in``
                # spelling is the opposite and must not land here: it is
                # true precisely when ``y`` is empty.
                keys |= _witnessed_by(source, right, subsets)
            continue
        if (
            isinstance(test, ast.Call)
            and isinstance(test.func, ast.Name)
            and test.func.id == "any"
            and test.args
        ):
            # ``any(())`` is ``False``, so a passing ``assert any(<comp>)``
            # proves the comprehension ranged over something. ``all`` is
            # deliberately absent: ``all(())`` is ``True``, which is the
            # very vacuity this module reports.
            keys |= _comprehension_base(source, test.args[0])
        keys |= _witnessed_by(source, test, subsets)
    return keys


def _raises_or_fails(node: ast.AST) -> bool:
    """True for ``raise ...`` and for an exact ``<expr>.fail(...)`` call.

    Only an attribute access literally named ``fail`` qualifies — that
    covers ``pytest.fail(...)`` and ``self.fail(...)`` on a
    ``unittest.TestCase``, both of which actually raise. A suffix match
    (the earlier, broader implementation) also matched any dotted call
    whose text merely *ends* in "fail" — ``logger.softfail(...)``,
    ``report_fail(...)`` — which do not necessarily raise. Treating those
    as witnesses would fabricate a guard: a loop that runs zero times could
    still look proven. A bare ``fail(...)`` name call is deliberately
    excluded too, for the same reason: without resolving what the name is
    bound to, there is no evidence it raises. Under-reporting a genuinely
    vacuous claim is the worse failure direction for this tool, so the
    narrower reading is preferred over the permissive one.
    """
    if isinstance(node, ast.Raise):
        return True
    return (
        isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Call)
        and isinstance(node.value.func, ast.Attribute)
        and node.value.func.attr == "fail"
    )


def _exhaustion_raises(body: list[ast.stmt], index: int) -> bool:
    """True when falling out of ``body[index]`` raises instead of continuing.

    ``for … else: raise`` and a ``raise`` as the loop's next sibling are the
    same contract: "finding nothing is a failure". That is the correct
    anti-vacuity idiom and must be recognised, not flagged.
    """
    loop = body[index]
    if isinstance(loop, ast.For) and any(_raises_or_fails(s) for s in loop.orelse):
        return True
    return index + 1 < len(body) and _raises_or_fails(body[index + 1])


def _iterating_asserts(body: list[ast.stmt]) -> Iterator[tuple[ast.expr, int]]:
    """Yield ``(iterated expression, lineno)`` for the claims *body* carries.

    Block-local on purpose: a claim belongs to the block it is written in,
    so that :func:`_block_claims` can hand it exactly the witnesses that are
    in scope for it. Nested blocks are visited by that walker, not here.

    Three syntactic positions carry the same semantics:

    * ``for x in Y: ... assert ...`` — zero iterations, zero assertions;
    * ``assert all(<genexp>)`` — ``all(())`` is ``True``;
    * ``assert not any(<genexp>)`` — ``any(())`` is ``False``.

    A bare ``assert any(<genexp>)`` is *not* included: over an empty
    iterable it is ``False``, so it fails loudly instead of silently.
    """
    for index, node in enumerate(body):
        if (
            isinstance(node, ast.For)
            and any(isinstance(inner, ast.Assert) for inner in _walk_own(node))
            and not _exhaustion_raises(body, index)
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


def _witness_candidates(source: str, node: ast.expr) -> set[str]:
    """Rendered expressions, any one of which proves *node* non-empty.

    The node's own text always qualifies — that is the loop form, where the
    iterated expression is what a witness is written about. The ``assert
    all(<genexp>)`` form needs one more: :func:`_iterating_asserts` hands
    back the *comprehension*, so comparing only its text could never match
    the repo's most common pairing, ``assert xs`` on the line directly above
    ``assert all(f(x) for x in xs)``.

    The base only stands in for a single unfiltered generator. An ``if``
    clause can empty the comprehension while the base is full, and with a
    second ``for`` clause the inner iterable can be empty for every element
    of the outer one. In both cases a non-empty base proves nothing, so
    accepting it would fabricate a witness — the failure direction this
    module treats as the worse one.
    """
    candidates = {_render(source, node)}
    if isinstance(node, (ast.ListComp, ast.SetComp, ast.GeneratorExp)):
        generators = node.generators
        if len(generators) == 1 and not generators[0].ifs:
            candidates.add(_render(source, generators[0].iter))
    return candidates


def _nested_blocks(stmt: ast.stmt) -> Iterator[list[ast.stmt]]:
    """Yield the statement blocks written directly inside *stmt*.

    Exactly one thing is skipped: the body of a nested ``def``. A claim or a
    witness inside a nested helper belongs to that helper, which is the same
    scope rule :func:`_walk_own` applies — and :func:`scan_source` visits
    every ``FunctionDef`` in the module in its own right, so nothing is lost
    by not descending here.

    Everything else is descended into, including three shapes that carry a
    block somewhere other than a plain ``list[ast.stmt]`` field and were
    silently invisible until they were named here:

    * ``except``/``except*`` handlers — the block hangs off an
      ``ast.ExceptHandler``, not off ``Try`` directly;
    * ``match`` cases — the block hangs off an ``ast.match_case``, so
      ``Match.cases`` is a list of *those*, not of statements;
    * a nested ``class`` body — which really does execute, unconditionally,
      when the enclosing function runs. :func:`_walk_own` descends into it
      (it skips only ``FunctionDef``/``AsyncFunctionDef``/``Lambda``), so
      refusing to here would have been a blind spot rather than a scope
      rule. Its *methods* are still skipped, by the ``def`` rule above.

    A guard against unobserved checks must not itself have somewhere it
    never looks, so the rule is stated as "descend into everything except a
    nested ``def``" rather than as a list of the shapes someone remembered.
    """
    if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return
    for _field, value in ast.iter_fields(stmt):
        if not isinstance(value, list):
            continue
        block = [item for item in value if isinstance(item, ast.stmt)]
        if block:
            yield block
        for item in value:
            if isinstance(item, (ast.ExceptHandler, ast.match_case)):
                yield item.body


def _block_claims(
    source: str,
    body: list[ast.stmt],
    inherited: set[str],
    bindings: dict[str, str],
    helpers: dict[str, str],
    *,
    witnesses_hold: bool = True,
    subsets: dict[str, set[str]] | None = None,
) -> Iterator[tuple[ast.expr, int, str]]:
    """Yield ``(iterable, lineno, kind)`` for the unwitnessed claims under *body*.

    Witnesses are block-scoped and inherited downwards, which is what makes
    the sound in-loop idiom work while the unsound shapes still fail::

        for pat in PATTERNS:          # PATTERNS is a literal: not a claim
            matched = sorted(dir.glob(pat))
            assert matched            # witness, in matched's own block
            for hit in matched:       # same block -> covered
                assert is_fast(hit)

    Nothing is inherited *upwards*: a witness written inside a branch, a
    loop, or a ``pytest.raises`` block says nothing about the block that
    contains it. That is the whole point of :func:`_unconditional_asserts`,
    and inheriting in one direction only is what keeps both properties.

    ``witnesses_hold`` carries the second half of that rule downwards. Once
    a block is inside a context that swallows ``AssertionError``
    (:func:`_swallows_assertion_error`), the asserts *written in it* prove
    nothing about anything: they are expected to fail. Reading them as
    proof of non-emptiness would be the same polarity inversion rejected
    one scope level up, so they are voided here and in every block nested
    below. Witnesses established *before* the block was entered are
    unaffected — they already ran — which is what makes the honest
    restructuring work::

        assert hits                        # real witness, outside
        with pytest.raises(AssertionError):
            for hit in hits:               # inherited witness still covers it
                assert hit.bad
    """
    visible = inherited | (witness_keys(source, body, subsets) if witnesses_hold else set())
    for iterated, lineno in _iterating_asserts(body):
        if visible & _witness_candidates(source, iterated):
            continue
        kind = classify_iterable(source, iterated, bindings, helpers)
        if kind is not None:
            yield iterated, lineno, kind
    for stmt in body:
        holds = witnesses_hold and not (
            isinstance(stmt, (ast.With, ast.AsyncWith)) and _swallows_assertion_error(stmt)
        )
        for block in _nested_blocks(stmt):
            yield from _block_claims(
                source, block, visible, bindings, helpers,
                witnesses_hold=holds, subsets=subsets,
            )


def _parametrize_claims(
    node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef,
    module_bindings: dict[str, str],
    helpers: dict[str, str],
    source: str,
    path: str,
) -> Iterator[VacuousClaim]:
    """Yield a claim for every emptiable ``argvalues`` decorating *node*.

    Shared between the function/method branch and the class branch of
    :func:`scan_source`'s node loop so the two report identically.
    """
    for argvalues, lineno in _parametrize_argvalues(node):
        kind = classify_iterable(source, argvalues, module_bindings, helpers)
        if kind is None:
            continue
        yield VacuousClaim(
            path=path,
            lineno=lineno,
            test=node.name,
            iterable=_render(source, argvalues),
            kind=f"parametrize {kind}",
        )


def scan_source(source: str, path: str) -> list[VacuousClaim]:
    """Return every vacuum-prone claim in *source*.

    *path* is used verbatim in :attr:`VacuousClaim.path`; pass a
    repo-relative posix path so the keys stay stable across checkouts.
    """
    tree = ast.parse(source)
    helpers = _module_helpers(source, tree)
    module_bindings = _module_bindings(source, tree, helpers)
    claims: list[VacuousClaim] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            # A class-level ``@pytest.mark.parametrize`` applies to every
            # method on the class; attribute one claim to the class itself
            # (``test`` = class name) rather than duplicating it per method.
            # This is also what fixes ``VacuousClaim.key`` for a later
            # exemption registry: one entry waives the whole class, matching
            # what a reviewer actually decided about.
            claims.extend(_parametrize_claims(node, module_bindings, helpers, source, path))
            continue
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        bindings = _local_bindings(source, node, helpers)
        subsets = _subset_bindings(source, node)
        for iterated, lineno, kind in _block_claims(
            source, node.body, set(), bindings, helpers, subsets=subsets
        ):
            claims.append(
                VacuousClaim(
                    path=path,
                    lineno=lineno,
                    test=node.name,
                    iterable=_render(source, iterated),
                    kind=kind,
                )
            )
        claims.extend(_parametrize_claims(node, module_bindings, helpers, source, path))
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
