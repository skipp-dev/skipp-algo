"""Six-fold zero-tripwire bundle (defense-only):

1. **Python `from x import *`** — banned (linter-defeating, namespace
   opacity). 0 inventory.
2. **`pytest.mark.xfail` / `pytest.xfail()`** — banned outright. Either
   tests pass or they're skipped with reason. 0 inventory.
3. **Repo-tracked secret-shaped filenames** — `.env*`, `*.pem`, `*.key`,
   `id_rsa*`, `*_secret*`, `*.p12`, `*.pfx` must not be committed.
   0 inventory. Allowlist for `.env.example/.sample/.template`.
4. **Pine deprecated `study()`** — Pine v4 directive replaced by
   `indicator()` in v5+. 0 inventory.
5. **Pine `//@version` declaration** — every standalone `.pine` file
   must declare `//@version=N` with N >= 5. Generated import-snippet
   fragments are exempt (filename suffix `_snippet.pine`).
6. **YAML workflow / docker-compose parse** — every `.github/**/*.yml`,
   `.github/**/*.yaml`, and `docker-compose.yml` must parse via
   `yaml.safe_load`. Catches syntax bricks before CI does.
"""

from __future__ import annotations

import ast
import os
import re
import subprocess
from pathlib import Path

import pytest

from tests._guard_corpus import iter_production_py_files, parse_module

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
    return iter_production_py_files(_DIR_EXCLUDE)


def _iter_pine() -> list[Path]:
    out: list[Path] = []
    for p in _REPO_ROOT.rglob("*.pine"):
        parts = p.relative_to(_REPO_ROOT).parts
        if any(x in {".git", ".venv", "venv", "node_modules"} for x in parts):
            continue
        out.append(p)
    return sorted(out)


# ─── 1. Python star imports ──────────────────────────────────────────


def test_no_python_star_imports_in_prod() -> None:
    hits: list[tuple[str, int, str]] = []
    for path in _iter_prod_py():
        tree = parse_module(path)
        if tree is None:
            continue
        rel = path.relative_to(_REPO_ROOT).as_posix()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    if alias.name == "*":
                        hits.append((rel, node.lineno, node.module or "?"))
    assert not hits, (
        "`from x import *` introduced — linter-defeating, namespace-opaque. "
        "Import names explicitly:\n  - "
        + "\n  - ".join(f"{f}:{ln} from {mod} import *" for f, ln, mod in hits)
    )


# ─── 2. pytest.xfail ─────────────────────────────────────────────────
#
# The rule is "xfail hides regressions". That is true of a *non-strict* xfail:
# the test may start passing and nobody is told, so a fixed bug and a still-
# broken one look identical. It is the opposite of true for
# ``@pytest.mark.xfail(strict=True, reason=...)``: pytest FAILS the run the
# moment such a test passes, so it cannot hide anything — it pins a known,
# documented violation and demands attention exactly when the source is
# corrected. Banning that shape does not protect against the failure mode this
# rule names; it only pushes the known bug towards ``skip``, which really is
# silent.
#
# So the ban is scoped to what it can justify:
#   * ``pytest.xfail(...)``            — imperative, no strict mode exists. Banned.
#   * ``@pytest.mark.xfail``           — bare, non-strict by default. Banned.
#   * ``@pytest.mark.xfail(...)``      — banned unless BOTH strict=True and a
#                                        non-empty reason= are passed literally.
#
# 2026-07-15: previously a line regex, which could not see the keywords at all
# (a decorator spans lines) and so had to ban the whole shape. AST reads them.


def _is_pytest_attr(node: ast.expr, *path: str) -> bool:
    """True for the attribute chain ``pytest.<path…>`` (e.g. ``pytest.mark.xfail``)."""
    for part in reversed(path):
        if not isinstance(node, ast.Attribute) or node.attr != part:
            return False
        node = node.value
    return isinstance(node, ast.Name) and node.id == "pytest"


def _strict_xfail_with_reason(call: ast.Call) -> bool:
    """True iff the call passes literal ``strict=True`` and a non-empty ``reason=``."""
    strict = reason = False
    for kw in call.keywords:
        if kw.arg == "strict":
            strict = isinstance(kw.value, ast.Constant) and kw.value.value is True
        elif kw.arg == "reason":
            reason = bool(_static_str(kw.value))
    return strict and reason


def _static_str(node: ast.expr) -> str:
    """Best-effort literal text of a str expression (handles implicit concat)."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return "".join(
            v.value
            for v in node.values
            if isinstance(v, ast.Constant) and isinstance(v.value, str)
        )
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return _static_str(node.left) + _static_str(node.right)
    return ""


def _xfail_violations() -> list[tuple[str, int, str]]:
    hits: list[tuple[str, int, str]] = []
    tests_dir = _REPO_ROOT / "tests"
    for path in sorted(tests_dir.rglob("*.py")):
        # This file names the shapes it bans in its own prose.
        if path.resolve() == Path(__file__).resolve():
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError, UnicodeDecodeError):  # pragma: no cover
            continue
        rel = path.relative_to(_REPO_ROOT).as_posix()
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and _is_pytest_attr(
                node, "mark", "xfail"
            ):
                # Bare `@pytest.mark.xfail` — non-strict by default. An
                # ast.Call wraps its own func Attribute, so only report the
                # bare form here; the call form is handled below.
                parent_is_call = any(
                    isinstance(n, ast.Call) and n.func is node for n in ast.walk(tree)
                )
                if not parent_is_call:
                    hits.append((rel, node.lineno, "bare xfail marker (not strict)"))
            elif isinstance(node, ast.Call):
                if _is_pytest_attr(node.func, "xfail"):
                    hits.append(
                        (rel, node.lineno, "pytest.xfail(...) — imperative, never strict")
                    )
                elif _is_pytest_attr(
                    node.func, "mark", "xfail"
                ) and not _strict_xfail_with_reason(node):
                    hits.append(
                        (
                            rel,
                            node.lineno,
                            "@pytest.mark.xfail(...) without strict=True and reason=",
                        )
                    )
    return hits


def test_no_non_strict_pytest_xfail_anywhere() -> None:
    """Only ``@pytest.mark.xfail(strict=True, reason=…)`` may pin a known bug."""
    hits = _xfail_violations()
    assert not hits, (
        "Non-strict `pytest.xfail` / `@pytest.mark.xfail` introduced. A "
        "non-strict xfail hides regressions: it stays green whether the bug is "
        "fixed or not. Either make the test pass, or pin the known violation "
        "with `@pytest.mark.xfail(strict=True, reason=\"…\")` — strict fails the "
        "run the moment the source is corrected, so the xfail cannot outlive "
        "the bug:"
        "\n  - " + "\n  - ".join(f"{f}:{ln}  {snip}" for f, ln, snip in hits)
    )


# ─── 3. Repo-tracked secret-shaped files ─────────────────────────────

_SECRET_NAME_RE = re.compile(
    r"(^|/)(\.env(\..*)?|.*\.pem|.*\.key|id_rsa(\.pub)?|.*_secret.*|.*\.p12|.*\.pfx)$",
    re.IGNORECASE,
)
# ``test_secret_leakage_probes.py`` is itself a guard test that scans the
# repo for committed secrets; its filename matches ``.*_secret.*`` only by
# virtue of describing what it probes for. It contains no secret material
# and is allow-listed by basename here.
#
# 2026-07-15: the two TV_STORAGE_STATE rotation files below are the same class
# — they *rotate* a secret, so `.*_secret.*` matches their name. This guard has
# never run on the required path, so #3658 added them and merged green; the
# breach only surfaced when the guard was measured for gating. Verified before
# allow-listing: both scanned for base64/hex runs (40+ chars) and for the
# ghp_/sk-/xox/eyJhbGciOi token prefixes — zero matches. The script takes the
# secret from `gh secret set` stdin and never writes it to disk; the test drives
# it with a fixture string.
_SECRET_BASENAME_ALLOW = frozenset(
    {
        "tv_rotate_storage_state_secret.sh",
        "test_tv_rotate_storage_state_secret.py",
        ".env.example",
        ".env.sample",
        ".env.template",
        "test_secret_leakage_probes.py",
    }
)


def test_no_secret_shaped_files_tracked_in_git() -> None:
    try:
        result = subprocess.run(
            ["git", "ls-files"],
            capture_output=True,
            text=True,
            cwd=_REPO_ROOT,
            check=True,
            timeout=15,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
        pytest.skip("git ls-files unavailable")
    suspects: list[str] = []
    for line in result.stdout.splitlines():
        base = os.path.basename(line)
        if base in _SECRET_BASENAME_ALLOW:
            continue
        if _SECRET_NAME_RE.search(line):
            suspects.append(line)
    assert not suspects, (
        "Secret-shaped filename(s) tracked in git — never commit secrets:\n  - "
        + "\n  - ".join(suspects)
    )


# ─── 4. Pine deprecated study() ──────────────────────────────────────

_STUDY_CALL_RE = re.compile(r"\bstudy\s*\(")
_PINE_COMMENT_RE = re.compile(r"^\s*//")


def test_no_pine_study_calls() -> None:
    hits: list[tuple[str, int, str]] = []
    for path in _iter_pine():
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):  # pragma: no cover
            continue
        rel = path.relative_to(_REPO_ROOT).as_posix()
        for ln, line in enumerate(text.splitlines(), start=1):
            if _PINE_COMMENT_RE.match(line):
                continue
            if _STUDY_CALL_RE.search(line):
                hits.append((rel, ln, line.strip()[:100]))
    assert not hits, (
        "Pine deprecated `study(...)` directive used — replaced by "
        "`indicator(...)` in Pine v5+:\n  - "
        + "\n  - ".join(f"{f}:{ln}  {snip}" for f, ln, snip in hits)
    )


# ─── 5. Pine //@version declaration ──────────────────────────────────

_VERSION_RE = re.compile(r"//\s*@version\s*=\s*(\d+)")
_PINE_MIN_VERSION = 5


def _is_pine_snippet(path: Path) -> bool:
    name = path.name
    return name.endswith("_snippet.pine") or name.endswith("_import_snippet.pine")


def test_pine_files_declare_supported_version() -> None:
    missing: list[str] = []
    too_old: list[tuple[str, int]] = []
    for path in _iter_pine():
        if _is_pine_snippet(path):
            continue
        try:
            head = path.read_text(encoding="utf-8")[:500]
        except (OSError, UnicodeDecodeError):  # pragma: no cover
            continue
        rel = path.relative_to(_REPO_ROOT).as_posix()
        m = _VERSION_RE.search(head)
        if not m:
            missing.append(rel)
            continue
        ver = int(m.group(1))
        if ver < _PINE_MIN_VERSION:
            too_old.append((rel, ver))
    problems: list[str] = []
    if missing:
        problems.append(
            "Missing `//@version=N` declaration:\n  - " + "\n  - ".join(missing)
        )
    if too_old:
        problems.append(
            f"Pine version below minimum ({_PINE_MIN_VERSION}):\n  - "
            + "\n  - ".join(f"{f}: //@version={v}" for f, v in too_old)
        )
    assert not problems, "\n\n".join(problems)


# ─── 6. YAML workflow + compose parse ────────────────────────────────


def _yaml_files() -> list[Path]:
    out: list[Path] = []
    gh = _REPO_ROOT / ".github"
    if gh.exists():
        out.extend(gh.rglob("*.yml"))
        out.extend(gh.rglob("*.yaml"))
    compose = _REPO_ROOT / "docker-compose.yml"
    if compose.exists():
        out.append(compose)
    return sorted(out)


def test_workflow_and_compose_yaml_parses() -> None:
    yaml = pytest.importorskip("yaml")
    bad: list[tuple[str, str]] = []
    for path in _yaml_files():
        try:
            yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            rel = path.relative_to(_REPO_ROOT).as_posix()
            bad.append((rel, str(exc).splitlines()[0][:160]))
    assert not bad, (
        "YAML workflow / docker-compose file(s) failed to parse:\n  - "
        + "\n  - ".join(f"{f}: {err}" for f, err in bad)
    )


# ─── inventory sanity ────────────────────────────────────────────────


def test_prod_py_inventory_sane() -> None:
    assert len(_iter_prod_py()) >= 50


def test_pine_inventory_sane() -> None:
    assert len(_iter_pine()) >= 30


def test_yaml_inventory_sane() -> None:
    # Should find at least the workflows directory contents.
    assert len(_yaml_files()) >= 5
