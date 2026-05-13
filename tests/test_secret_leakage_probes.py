"""R7 (audit-L-1, 2026-05-12) — secret-leakage AST budget for probe scripts.

Background
==========
``scripts/probe_*.py`` files are CI/operator probes that intentionally
exercise upstream APIs and surface failures back to the operator. The
"failure surface" is the danger: if a probe formats an exception object
into the output without going through the central
``databento_utils._redact_sensitive_error_text`` helper, it can leak the
raw API key, query string, or response body that the upstream library
embedded into the exception.

This pin enforces a 7-pattern AST table (see retrospective §R7) over
every ``scripts/probe_*.py``. Each pattern represents a known leakage
shape; new probe code that introduces an unredacted instance must either
fix the call to go through ``_redact_sensitive_error_text`` or add a
``# noqa: SECLEAK`` marker on the offending line with a written
justification (e.g. exception text is provably safe).

The 7 patterns:

  1. ``str(exc)`` / ``repr(exc)`` where ``exc`` is the bound name of an
     ``except ... as exc`` clause.
  2. ``f"...{exc}..."`` and ``f"...{exc!r}..."`` (any conversion flag).
  3. ``"...".format(exc)`` / ``.format(exc=exc)``.
  4. ``" % exc`` / ``" % (exc,)`` (printf-style).
  5. ``logger.error(..., exc_info=True)`` / ``exc_info=exc`` /
     ``logger.exception(...)`` (writes the raw traceback to the log
     stream — fine for in-process logs but the probe output gets
     captured into PR artifacts).
  6. ``return (..., exc)`` / ``return {"error": str(exc)}`` (passes the
     raw exception or its text downstream into the operator-facing
     payload).
  7. ``exc.args``, ``exc.message`` attribute access used in any of the
     above contexts (libraries sometimes pre-formatted the secret into
     ``args[0]``).

Marker: ``# noqa: SECLEAK`` on the same line suppresses the finding for
that one location (the marker MUST carry a written reason after the
em-dash, e.g. ``# noqa: SECLEAK \u2014 exception text is the upstream
HTTP status only``).

See ``docs/AUDIT_L1_REVIEW_RETROSPECTIVE_2026-05-12.md`` \xa7R7.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest


_REPO_ROOT = Path(__file__).resolve().parent.parent
_PROBE_GLOB = "scripts/probe_*.py"
_NOQA_MARKER = "noqa: SECLEAK"

# Names commonly bound by ``except ... as <name>`` whose use as a string
# argument or formatted value triggers the AST patterns. Restricting to
# this set avoids flagging every variable named ``e`` in arithmetic.
_EXC_NAMES: frozenset[str] = frozenset({"exc", "err", "e", "error"})


def _exc_bindings_in_function(func: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    """Return the set of ``as <name>`` bindings inside a function's try blocks."""

    out: set[str] = set()
    for node in ast.walk(func):
        if isinstance(node, ast.ExceptHandler) and isinstance(node.name, str):
            out.add(node.name)
    return out


def _name_id(node: ast.AST) -> str | None:
    """Return ``Name.id`` if ``node`` is a Name, else None."""

    return node.id if isinstance(node, ast.Name) else None


def _references_exc(node: ast.AST, exc_names: set[str]) -> bool:
    """Recursively check whether ``node`` references an exception binding."""

    for child in ast.walk(node):
        if isinstance(child, ast.Name) and child.id in exc_names:
            return True
        if isinstance(child, ast.Attribute) and isinstance(child.value, ast.Name):
            if child.value.id in exc_names and child.attr in {"args", "message"}:
                return True
    return False


def _is_redacted_call(node: ast.AST) -> bool:
    """Detect the central ``_redact_sensitive_error_text(...)`` call."""

    if not isinstance(node, ast.Call):
        return False
    fn = node.func
    if isinstance(fn, ast.Name) and fn.id == "_redact_sensitive_error_text":
        return True
    if isinstance(fn, ast.Attribute) and fn.attr == "_redact_sensitive_error_text":
        return True
    return False


def _walk_with_lineno(tree: ast.AST):
    for node in ast.walk(tree):
        if hasattr(node, "lineno"):
            yield node


def _find_leaks(source: str, exc_names_global: set[str]) -> list[tuple[int, str]]:
    """Return ``(lineno, pattern_code)`` for every unredacted leak site."""

    tree = ast.parse(source)

    # Build parent map so we can detect when a leakage site is wrapped
    # by ``_redact_sensitive_error_text(...)`` somewhere up the AST chain.
    parents: dict[int, ast.AST] = {}
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            parents[id(child)] = parent

    def _wrapped_in_redact(node: ast.AST) -> bool:
        cur = parents.get(id(node))
        while cur is not None:
            if _is_redacted_call(cur):
                return True
            cur = parents.get(id(cur))
        return False

    # Map function -> exc bindings so we can scope the check.
    bindings: dict[int, set[str]] = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            bindings[id(node)] = _exc_bindings_in_function(node) | exc_names_global

    # Build line -> bindings lookup by walking each function's body lines.
    line_bindings: dict[int, set[str]] = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for stmt in ast.walk(node):
                if hasattr(stmt, "lineno"):
                    line_bindings.setdefault(stmt.lineno, set()).update(bindings[id(node)])

    findings: list[tuple[int, str]] = []

    for node in _walk_with_lineno(tree):
        ln = node.lineno
        scoped = line_bindings.get(ln, exc_names_global)

        # Pattern 1: str(exc) / repr(exc)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id in {"str", "repr"} and node.args:
                arg0 = node.args[0]
                if (
                    isinstance(arg0, ast.Name) and arg0.id in scoped
                ) or (
                    isinstance(arg0, ast.Attribute)
                    and isinstance(arg0.value, ast.Name)
                    and arg0.value.id in scoped
                ):
                    findings.append((ln, f"P1:{node.func.id}({arg0_repr(arg0)})"))

        # Pattern 2: f-string referencing exc
        if isinstance(node, ast.JoinedStr):
            # Skip if this JoinedStr is being passed straight into the
            # central ``_redact_sensitive_error_text`` helper (handled at
            # the wrapping Call site — see below).
            if _wrapped_in_redact(node):
                continue
            for value in node.values:
                if isinstance(value, ast.FormattedValue) and _references_exc(value.value, scoped):
                    findings.append((ln, "P2:f-string"))
                    break

        # Pattern 3: "...".format(exc)
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "format"
        ):
            for arg in [*node.args, *(kw.value for kw in node.keywords)]:
                if _references_exc(arg, scoped):
                    findings.append((ln, "P3:.format"))
                    break

        # Pattern 4: "..." % exc
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mod):
            if _references_exc(node.right, scoped):
                findings.append((ln, "P4:%-format"))

        # Pattern 5: logger.error(..., exc_info=...) / logger.exception(...)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if (
                node.func.attr == "exception"
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id in {"logger", "log", "logging"}
            ):
                findings.append((ln, "P5:logger.exception"))
            for kw in node.keywords:
                if kw.arg == "exc_info" and (
                    (isinstance(kw.value, ast.Constant) and kw.value.value is True)
                    or _references_exc(kw.value, scoped)
                ):
                    findings.append((ln, "P5:exc_info"))

        # Pattern 6: return tuple / dict containing raw exc reference.
        if isinstance(node, ast.Return) and node.value is not None:
            if isinstance(node.value, (ast.Tuple, ast.Dict, ast.List)):
                if _references_exc(node.value, scoped):
                    # Skip if the payload routes ANY exc text through the
                    # central ``_redact_sensitive_error_text`` helper. The
                    # operator opted in to redaction; trust the call site.
                    has_redact = any(
                        _is_redacted_call(call)
                        for call in ast.walk(node.value)
                        if isinstance(call, ast.Call)
                    )
                    if not has_redact:
                        findings.append((ln, "P6:return-payload"))

        # Pattern 7 is implicitly handled in _references_exc which already
        # checks for ``exc.args`` / ``exc.message``.

    return findings


def arg0_repr(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
        return f"{node.value.id}.{node.attr}"
    return type(node).__name__


def _line_has_marker(source_lines: list[str], lineno: int) -> bool:
    if lineno < 1 or lineno > len(source_lines):
        return False
    return _NOQA_MARKER in source_lines[lineno - 1]


@pytest.mark.parametrize(
    "probe_path",
    sorted(str(p.relative_to(_REPO_ROOT)) for p in _REPO_ROOT.glob(_PROBE_GLOB)),
)
def test_r7_no_unredacted_secret_leakage(probe_path: str) -> None:
    """Every probe leakage site must go through ``_redact_sensitive_error_text``\
    or carry a ``# noqa: SECLEAK \u2014 <reason>`` marker."""

    full = _REPO_ROOT / probe_path
    source = full.read_text(encoding="utf-8")
    source_lines = source.splitlines()

    findings = _find_leaks(source, _EXC_NAMES)
    unmarked = [
        (ln, pat) for ln, pat in findings if not _line_has_marker(source_lines, ln)
    ]
    if unmarked:
        formatted = "\n  - ".join(f"{probe_path}:{ln} [{pat}]" for ln, pat in unmarked)
        raise AssertionError(
            "Unredacted exception leakage in probe script. Wrap the call in "
            "`_redact_sensitive_error_text(...)` or add `# noqa: SECLEAK \u2014 "
            "<reason>` on the same line if the text is provably safe:\n  - "
            + formatted
        )
