#!/usr/bin/env python3
"""R3-regex (audit-L-1, 2026-05-12) — defaults-table consistency check.

Background
==========
``newsstack_fmp/config.py`` declares ~40 ``field(default_factory=lambda:
os.getenv(...))`` and ``_env_int/_env_float`` defaults. Each row pairs a
config attribute (``self.fmp_general_limit``) with an env-var name
(``"FMP_GENERAL_LIMIT"``) and a default value (``50``).

When operators tune defaults via PR they routinely:

  1. Update the literal default (``50 \u2192 100``) but forget to update
     ``docs/CONFIG_DEFAULTS_TABLE.md`` to match.
  2. Rename a config attr but leave the env-var name stale.
  3. Add a new field without a corresponding doc entry.

This script is **warn-only**: it scans ``newsstack_fmp/config.py`` for
the four canonical default patterns and emits a report. It is invoked
from CI as a non-blocking step and from PR description checklist
(``.github/PULL_REQUEST_TEMPLATE.md``).

Patterns recognised:

  * ``X = field(default_factory=lambda: os.getenv("KEY", "default"))``
  * ``X = field(default_factory=lambda: os.getenv("KEY", "1") == "1")``
  * ``X = field(default_factory=lambda: _env_int("KEY", N))``
  * ``X = field(default_factory=lambda: _env_float("KEY", N.M))``

Usage:
    python tools/check_defaults_table.py
    python tools/check_defaults_table.py --strict   # exit 1 on warnings

Notes:
    R3-AST (audit-L-1 PR-D, 2026-05-12) replaced the original four
    regex patterns with a proper AST walker. The walker is more robust
    against whitespace/formatter changes and adds a 5th kind ``ssot``
    for fields that delegate to ``open_prep.feature_flags`` helpers
    (which the regex couldn't recognise).
"""

from __future__ import annotations

import argparse
import ast
import sys
from collections.abc import Iterator
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_CONFIG_PATH = _REPO_ROOT / "newsstack_fmp" / "config.py"
_DOC_PATH = _REPO_ROOT / "docs" / "CONFIG_DEFAULTS_TABLE.md"


def _is_os_getenv(call: ast.AST) -> bool:
    """``os.getenv("KEY", "default")``."""

    return (
        isinstance(call, ast.Call)
        and isinstance(call.func, ast.Attribute)
        and call.func.attr == "getenv"
        and isinstance(call.func.value, ast.Name)
        and call.func.value.id == "os"
    )


def _const_str(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _const_number(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return repr(node.value)
    if (
        isinstance(node, ast.UnaryOp)
        and isinstance(node.op, ast.USub)
        and isinstance(node.operand, ast.Constant)
        and isinstance(node.operand.value, (int, float))
    ):
        return f"-{node.operand.value!r}"
    return None


def _decode_lambda_body(body: ast.AST) -> tuple[str, str, str] | None:
    """Decode a ``field(default_factory=lambda: <body>)`` body.

    Returns ``(env_var, default_repr, kind)`` or None if shape is unknown.
    """

    # Pattern 1: bool \u2014 ``os.getenv("KEY","0") == "1"``
    if isinstance(body, ast.Compare) and len(body.ops) == 1 and isinstance(body.ops[0], ast.Eq):
        left = body.left
        if isinstance(left, ast.Call) and _is_os_getenv(left) and len(left.args) >= 2:
            env_var = _const_str(left.args[0])
            default = _const_str(left.args[1])
            rhs = _const_str(body.comparators[0])
            if env_var and default is not None and rhs == "1":
                return (env_var, default, "bool")

    # Pattern 2: str — ``os.getenv("KEY","default")``
    if isinstance(body, ast.Call) and _is_os_getenv(body) and len(body.args) >= 2:
        env_var = _const_str(body.args[0])
        default = _const_str(body.args[1])
        if env_var and default is not None:
            return (env_var, default, "str")

    # Pattern 3/4: int / float \u2014 ``_env_int("KEY", N)`` / ``_env_float("KEY", N.M)``
    if (
        isinstance(body, ast.Call)
        and isinstance(body.func, ast.Name)
        and body.func.id in {"_env_int", "_env_float"}
        and len(body.args) >= 2
    ):
        env_var = _const_str(body.args[0])
        default = _const_number(body.args[1])
        if env_var and default is not None:
            kind = "int" if body.func.id == "_env_int" else "float"
            return (env_var, default, kind)

    # Pattern 5: ssot delegate \u2014 ``__import__("open_prep.feature_flags",
    # fromlist=["is_<flag>_enabled"]).is_<flag>_enabled()``. The env var is
    # not visible at the AST level here; we record the helper name as the
    # "env_var" so the doc-coverage check can verify the row exists.
    if (
        isinstance(body, ast.Call)
        and isinstance(body.func, ast.Attribute)
        and body.func.attr.startswith("is_")
        and body.func.attr.endswith("_enabled")
    ):
        helper = body.func.attr
        # Convention: ``is_opra_uoa_enabled`` \u2194 env var ``ENABLE_OPRA_UOA``.
        flag_part = helper[len("is_") : -len("_enabled")]
        env_var = f"ENABLE_{flag_part.upper()}"
        return (env_var, helper, "ssot")

    return None


def _scan_config() -> list[tuple[str, str, str, str]]:
    """Return ``[(attr, env_var, default, kind), ...]``."""

    tree = ast.parse(_CONFIG_PATH.read_text(encoding="utf-8"))
    rows: list[tuple[str, str, str, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        # Walk every class body \u2014 not just ``Config`` \u2014 because the file
        # may contain multiple dataclasses (sub-configs). Filter at the
        # field level by requiring the canonical ``field(default_factory=
        # lambda: ...)`` shape, which is unique to dataclass fields.
        for stmt in node.body:
            if not isinstance(stmt, ast.AnnAssign) or not isinstance(stmt.target, ast.Name):
                continue
            if stmt.value is None or not isinstance(stmt.value, ast.Call):
                continue
            if not (isinstance(stmt.value.func, ast.Name) and stmt.value.func.id == "field"):
                continue
            default_factory: ast.AST | None = None
            for kw in stmt.value.keywords:
                if kw.arg == "default_factory":
                    default_factory = kw.value
                    break
            if default_factory is None:
                continue
            # Two shapes are recognised:
            #   1. ``field(default_factory=lambda: <body>)`` \u2014 the
            #      historical pattern; decoded via _decode_lambda_body.
            #   2. ``field(default_factory=<helper_name>)`` \u2014 the new
            #      audit-L-1 R4 SSOT pattern (e.g.
            #      ``default_factory=is_opra_uoa_enabled``). The helper
            #      name encodes the env var by convention.
            decoded: tuple[str, str, str] | None = None
            if isinstance(default_factory, ast.Lambda):
                decoded = _decode_lambda_body(default_factory.body)
            elif (
                isinstance(default_factory, ast.Name)
                and default_factory.id.startswith("is_")
                and default_factory.id.endswith("_enabled")
            ):
                helper = default_factory.id
                flag_part = helper[len("is_") : -len("_enabled")]
                decoded = (f"ENABLE_{flag_part.upper()}", helper, "ssot")
            if decoded is None:
                continue
            env_var, default, kind = decoded
            rows.append((stmt.target.id, env_var, default, kind))
    rows.sort()
    return rows


def _check_attr_envvar_alignment(rows: list[tuple[str, str, str, str]]) -> Iterator[str]:
    """Yield warnings when attr name and env-var name diverge non-trivially."""

    for attr, env_var, _default, _kind in rows:
        expected_env = attr.upper()
        if env_var == expected_env:
            continue
        if env_var.endswith("_" + expected_env) or env_var.endswith(expected_env):
            continue
        yield (
            f"  drift: attr={attr!r} env={env_var!r} (expected {expected_env!r})"
        )


def _check_doc_coverage(rows: list[tuple[str, str, str, str]]) -> Iterator[str]:
    """Yield warnings when an env-var has no entry in the defaults table doc."""

    if not _DOC_PATH.is_file():
        yield f"  doc-missing: {_DOC_PATH.relative_to(_REPO_ROOT)} not found"
        return
    doc_text = _DOC_PATH.read_text(encoding="utf-8")
    for _attr, env_var, _default, _kind in rows:
        if env_var not in doc_text:
            yield f"  doc-missing-row: env={env_var!r} not referenced in CONFIG_DEFAULTS_TABLE.md"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit 1 on warnings (default: warn-only, exit 0).",
    )
    args = parser.parse_args(argv)

    rows = _scan_config()
    print(f"Scanned {_CONFIG_PATH.relative_to(_REPO_ROOT)}: {len(rows)} default-rows.")

    warnings: list[str] = []
    warnings.extend(_check_attr_envvar_alignment(rows))
    warnings.extend(_check_doc_coverage(rows))

    if not warnings:
        print("OK \u2014 all defaults aligned and documented.")
        return 0

    print(f"\n{len(warnings)} warning(s):")
    for w in warnings:
        print(w)

    if args.strict:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
