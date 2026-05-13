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
    R3-AST (planned for PR-D) replaces this regex with a proper AST
    walker. Until then this regex catch-all keeps drift visible without
    blocking the pipeline.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Iterator


_REPO_ROOT = Path(__file__).resolve().parent.parent
_CONFIG_PATH = _REPO_ROOT / "newsstack_fmp" / "config.py"
_DOC_PATH = _REPO_ROOT / "docs" / "CONFIG_DEFAULTS_TABLE.md"

_RE_GETENV_STR = re.compile(
    r'^\s+(\w+):\s*[^=\n]*=\s*field\(default_factory=lambda:\s*'
    r'os\.getenv\(\s*"([A-Z_][A-Z0-9_]*)"\s*,\s*"([^"]*)"\s*\)\s*\)',
    re.MULTILINE,
)
_RE_GETENV_BOOL = re.compile(
    r'^\s+(\w+):\s*bool\s*=\s*field\(default_factory=lambda:\s*'
    r'os\.getenv\(\s*"([A-Z_][A-Z0-9_]*)"\s*,\s*"([01])"\s*\)\s*==\s*"1"\s*\)',
    re.MULTILINE,
)
_RE_ENV_INT = re.compile(
    r'^\s+(\w+):\s*int\s*=\s*field\(default_factory=lambda:\s*'
    r'_env_int\(\s*"([A-Z_][A-Z0-9_]*)"\s*,\s*(-?\d+)\s*\)\s*\)',
    re.MULTILINE,
)
_RE_ENV_FLOAT = re.compile(
    r'^\s+(\w+):\s*float\s*=\s*field\(default_factory=lambda:\s*'
    r'_env_float\(\s*"([A-Z_][A-Z0-9_]*)"\s*,\s*([-\d.]+)\s*\)\s*\)',
    re.MULTILINE,
)


def _scan_config() -> list[tuple[str, str, str, str]]:
    """Return ``[(attr, env_var, default, kind), ...]``."""

    text = _CONFIG_PATH.read_text(encoding="utf-8")
    rows: list[tuple[str, str, str, str]] = []
    for kind, pattern in (
        ("bool", _RE_GETENV_BOOL),
        ("int", _RE_ENV_INT),
        ("float", _RE_ENV_FLOAT),
        ("str", _RE_GETENV_STR),
    ):
        for m in pattern.finditer(text):
            rows.append((m.group(1), m.group(2), m.group(3), kind))
    rows.sort()
    return rows


def _check_attr_envvar_alignment(rows: list[tuple[str, str, str, str]]) -> Iterator[str]:
    """Yield warnings when attr name and env-var name diverge non-trivially."""

    for attr, env_var, _default, _kind in rows:
        # Canonical mapping: ``foo_bar_baz`` <→ ``FOO_BAR_BAZ``. Common
        # provider prefixes (FMP_, BENZINGA_) may be present in the env
        # var but elided from the attr (history); accept that as aligned.
        expected_env = attr.upper()
        if env_var == expected_env:
            continue
        # Tolerate provider-prefix-elided attrs (e.g. attr=stock_latest_limit
        # ↔ env=FMP_STOCK_LATEST_LIMIT). Drift only when the trailing tail
        # of the env var doesn't match.
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
