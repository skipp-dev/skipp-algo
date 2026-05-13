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
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, SyntaxError):  # pragma: no cover
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

_XFAIL_RE = re.compile(r"@pytest\.mark\.xfail\b|pytest\.xfail\s*\(")


def test_no_pytest_xfail_anywhere() -> None:
    hits: list[tuple[str, int, str]] = []
    tests_dir = _REPO_ROOT / "tests"
    for path in sorted(tests_dir.rglob("*.py")):
        # Allow this file to mention the literal string in docs/comments
        if path.resolve() == Path(__file__).resolve():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):  # pragma: no cover
            continue
        rel = path.relative_to(_REPO_ROOT).as_posix()
        for ln, line in enumerate(text.splitlines(), start=1):
            if _XFAIL_RE.search(line):
                hits.append((rel, ln, line.strip()[:100]))
    assert not hits, (
        "`pytest.xfail` / `@pytest.mark.xfail` introduced. Tests must "
        "either pass or be skipped with a reason — xfail hides regressions:"
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
_SECRET_BASENAME_ALLOW = frozenset(
    {
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
