"""Three-pin defense bundle:

1. **Mutable default argument** (zero-tripwire): ``def f(x=[])`` /
   ``def f(x={})`` / ``def f(x=set())`` etc. shares state across all
   calls — a classic Python footgun. Detected via AST.
2. **``json.load(...)`` site ledger** (frozen): every call is a
   parse-failure boundary. Frozen so new untrusted parse points need
   review.
3. **``os.environ[X]`` subscript ledger** (frozen): subscript raises
   ``KeyError`` on missing var. Frozen so new sites require explicit
   choice between hard-fail subscript vs ``.get(...)`` default.

Defense-only. Reductions encouraged.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

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


def _iter_prod_py() -> list[Path]:
    out: list[Path] = []
    for p in _REPO_ROOT.rglob("*.py"):
        if any(part in _DIR_EXCLUDE for part in p.relative_to(_REPO_ROOT).parts):
            continue
        out.append(p)
    return sorted(out)


# ─── 1. Mutable default arguments ────────────────────────────────────

_MUTABLE_FACTORY_NAMES = frozenset({"list", "dict", "set", "bytearray"})


def _is_mutable_default(node: ast.AST) -> str | None:
    if isinstance(node, ast.List):
        return "[]"
    if isinstance(node, ast.Dict):
        return "{}"
    if isinstance(node, ast.Set):
        return "set-literal"
    if isinstance(node, ast.Call):
        fn = node.func
        name = (
            fn.id
            if isinstance(fn, ast.Name)
            else (fn.attr if isinstance(fn, ast.Attribute) else None)
        )
        if name in _MUTABLE_FACTORY_NAMES:
            return f"{name}()"
    return None


def test_no_mutable_default_arguments() -> None:
    hits: list[tuple[str, int, str, str]] = []
    for path in _iter_prod_py():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, SyntaxError):  # pragma: no cover
            continue
        rel = path.relative_to(_REPO_ROOT).as_posix()
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for default in node.args.defaults + node.args.kw_defaults:
                    if default is None:
                        continue
                    kind = _is_mutable_default(default)
                    if kind:
                        hits.append((rel, default.lineno, node.name, kind))
    assert not hits, (
        "Mutable default argument detected — shares state across all calls. "
        "Use `None` sentinel + `if x is None: x = []`:\n  - "
        + "\n  - ".join(f"{f}:{ln} def {fn}(...={kind})" for f, ln, fn, kind in hits)
    )


# ─── 2. json.load site ledger ────────────────────────────────────────

_JSON_LOAD_RE = re.compile(r"\bjson\.load\s*\(")

_FROZEN_JSON_LOAD_SITES: frozenset[tuple[str, int]] = frozenset(
    {
        ("open_prep/alerts.py", 54),
        ("open_prep/diff.py", 79),
        ("open_prep/outcome_backfill.py", 61),
        ("open_prep/outcome_backfill.py", 81),
        ("open_prep/outcomes.py", 167),
        ("open_prep/realtime_signals.py", 1461),
        ("open_prep/realtime_signals.py", 2575),
        ("open_prep/scorer.py", 88),
        ("open_prep/watchlist.py", 53),
    }
)


def _measured_json_load_sites() -> set[tuple[str, int]]:
    out: set[tuple[str, int]] = set()
    for path in _iter_prod_py():
        rel = path.relative_to(_REPO_ROOT).as_posix()
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):  # pragma: no cover
            continue
        for ln, line in enumerate(text.splitlines(), start=1):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            if _JSON_LOAD_RE.search(line):
                out.add((rel, ln))
    return out


def test_no_new_json_load_sites() -> None:
    measured = _measured_json_load_sites()
    new = sorted(measured - _FROZEN_JSON_LOAD_SITES)
    assert not new, (
        "New `json.load(...)` site(s) introduced. Each is an untrusted parse "
        "boundary — review for try/except + size limits, then add to "
        "_FROZEN_JSON_LOAD_SITES:\n  - "
        + "\n  - ".join(f"{f}:{ln}" for f, ln in new)
    )


def test_no_stale_json_load_ledger_entries() -> None:
    measured = _measured_json_load_sites()
    stale = sorted(_FROZEN_JSON_LOAD_SITES - measured)
    assert not stale, (
        "Stale `json.load` ledger entries — remove from "
        "_FROZEN_JSON_LOAD_SITES:\n  - "
        + "\n  - ".join(f"{f}:{ln}" for f, ln in stale)
    )


# ─── 3. os.environ[X] subscript ledger ───────────────────────────────


_FROZEN_ENV_SUBSCRIPT_SITES: frozenset[tuple[str, int]] = frozenset(
    {
        ("databento_client.py", 60),
        ("databento_volatility_screener.py", 782),
        ("open_prep/macro.py", 149),
        ("open_prep/realtime_signals.py", 2611),
        ("open_prep/streamlit_monitor.py", 74),
        ("streamlit_terminal.py", 326),
    }
)


def _measured_env_subscript_sites() -> set[tuple[str, int]]:
    out: set[tuple[str, int]] = set()
    for path in _iter_prod_py():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, SyntaxError):  # pragma: no cover
            continue
        rel = path.relative_to(_REPO_ROOT).as_posix()
        for node in ast.walk(tree):
            if isinstance(node, ast.Subscript) and isinstance(
                node.value, ast.Attribute
            ):
                attr = node.value
                if (
                    attr.attr == "environ"
                    and isinstance(attr.value, ast.Name)
                    and attr.value.id == "os"
                ):
                    out.add((rel, node.lineno))
    return out


def test_no_new_os_environ_subscript_sites() -> None:
    measured = _measured_env_subscript_sites()
    new = sorted(measured - _FROZEN_ENV_SUBSCRIPT_SITES)
    assert not new, (
        "New `os.environ[X]` subscript site(s) — raises KeyError on missing "
        "var. Either use `.get(X, default)` or accept hard-fail and add to "
        "_FROZEN_ENV_SUBSCRIPT_SITES:\n  - "
        + "\n  - ".join(f"{f}:{ln}" for f, ln in new)
    )


def test_no_stale_env_subscript_ledger_entries() -> None:
    measured = _measured_env_subscript_sites()
    stale = sorted(_FROZEN_ENV_SUBSCRIPT_SITES - measured)
    assert not stale, (
        "Stale `os.environ[X]` ledger entries — remove from "
        "_FROZEN_ENV_SUBSCRIPT_SITES:\n  - "
        + "\n  - ".join(f"{f}:{ln}" for f, ln in stale)
    )


# ─── inventory sanity ────────────────────────────────────────────────


def test_prod_py_inventory_sane() -> None:
    assert len(_iter_prod_py()) >= 50


@pytest.mark.parametrize(
    "rel,_ln", sorted(_FROZEN_JSON_LOAD_SITES | _FROZEN_ENV_SUBSCRIPT_SITES)
)
def test_ledger_files_exist(rel: str, _ln: int) -> None:
    assert (_REPO_ROOT / rel).is_file(), f"Ledger references missing file: {rel}"
