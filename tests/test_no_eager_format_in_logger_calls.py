"""Audit pin: no f-strings as the message arg to ``logger.<level>(...)``.

Logger methods (``debug``, ``info``, ``warning``, ``error``, ``critical``,
``exception``, ``log``) accept a *format template* plus positional args
which are interpolated **lazily** — only when the record passes the
effective level filter.

Passing an f-string defeats this:

* the f-string is fully built, regardless of whether DEBUG is enabled;
* exception ``repr`` / ``str`` calls inside the f-string fire eagerly;
* structured-log handlers lose the template/argument separation.

Production codebase is currently at zero f-string-in-logger sites — this
pin freezes that invariant as a no-new-sites tripwire.

Detection: ``ast.Call`` whose ``func`` is an ``Attribute`` with attr in
the level set, and whose first positional argument is a ``JoinedStr``
(or a ``BinOp`` of ``%``/``+`` or a ``Call`` to ``str.format``).
This catches the three common eager-evaluation forms.
"""

from __future__ import annotations

import ast
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent

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
        "scripts",
        "tests",
        "SMC++",
    }
)

_LOGGER_NAMES = frozenset({"logger", "log", "_logger", "_log", "LOGGER", "LOG"})
_LOG_METHODS = frozenset(
    {"debug", "info", "warning", "warn", "error", "critical", "exception", "log"}
)


def _iter_prod_files() -> list[Path]:
    out: list[Path] = []
    for path in _REPO_ROOT.rglob("*.py"):
        if any(part in _DIR_EXCLUDE for part in path.relative_to(_REPO_ROOT).parts):
            continue
        out.append(path)
    return sorted(out)


def _is_logger_call(node: ast.Call) -> tuple[bool, str]:
    func = node.func
    if not isinstance(func, ast.Attribute):
        return False, ""
    if func.attr not in _LOG_METHODS:
        return False, ""
    value = func.value
    # ``logger.info(...)`` / ``self.logger.info(...)`` / ``cls._log.info(...)``
    if isinstance(value, ast.Name) and value.id in _LOGGER_NAMES:
        return True, f"{value.id}.{func.attr}"
    if isinstance(value, ast.Attribute) and value.attr in _LOGGER_NAMES:
        return True, f"<obj>.{value.attr}.{func.attr}"
    return False, ""


def _eager_format_kind(arg: ast.expr) -> str | None:
    """Return a label if ``arg`` is an eager-format expression, else None."""
    if isinstance(arg, ast.JoinedStr):
        return "f-string"
    if isinstance(arg, ast.BinOp) and isinstance(arg.op, (ast.Mod, ast.Add)):
        # ``"foo %s" % bar`` or ``"foo " + bar`` — both fully built before
        # the level filter sees them.
        return "%-format / + concatenation"
    if (
        isinstance(arg, ast.Call)
        and isinstance(arg.func, ast.Attribute)
        and arg.func.attr == "format"
    ):
        return ".format(...)"
    return None


def _violations() -> list[str]:
    out: list[str] = []
    for path in _iter_prod_files():
        rel = path.relative_to(_REPO_ROOT).as_posix()
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError as exc:  # pragma: no cover - defensive
            out.append(f"{rel}: parse error {exc!r}")
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            ok, label = _is_logger_call(node)
            if not ok or not node.args:
                continue
            # ``logger.log(LEVEL, msg, ...)`` — the template is args[1].
            msg_idx = 1 if (
                isinstance(node.func, ast.Attribute) and node.func.attr == "log"
            ) else 0
            if msg_idx >= len(node.args):
                continue
            kind = _eager_format_kind(node.args[msg_idx])
            if kind is None:
                continue
            out.append(
                f"{rel}:{node.lineno}: {label}({kind} ...) — use lazy "
                f"%-style formatting with positional args, e.g. "
                f"``logger.info('foo %s', bar)``; the f-string / .format "
                f"is built even when the level is filtered out, and "
                f"defeats structured-log handlers."
            )
    return out


def test_no_eager_format_in_logger_calls() -> None:
    violations = _violations()
    assert not violations, (
        "Eager log-message formatting detected (defeats lazy "
        "level-filtered interpolation):\n  - "
        + "\n  - ".join(violations)
    )


def test_prod_file_inventory_sane() -> None:
    files = _iter_prod_files()
    assert len(files) >= 50, (
        f"Production *.py scan only found {len(files)} files — "
        f"_DIR_EXCLUDE may be over-broad or sparse-checkout incomplete."
    )
