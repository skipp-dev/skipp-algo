"""Sprint Day-1 inventory tool.

Lists existing functions, classes, and modules whose name (or docstring)
mentions the given topic keyword(s). Designed to be run as the first
action of a new sprint per ``spec/sprint_template.md`` — Section 2.
The output is intentionally Markdown so it can be pasted under
``spec/sprints/<C-id>_inventory.md``.

Why
---
Empirically (Q3/Q4 plan progression, repo-memory
``q3q4-plan-progress-2026-04-23-eod.md``) 30–50 % of every sprint turns
out to be hardening / extending an existing module rather than
greenfield. Doing the inventory inline at sprint start saves the
"oops, ``open_prep/outcomes.py`` already does that" mid-sprint pivot.

Usage
-----
::

    python scripts/sprint_inventory.py outcome backfill
    python scripts/sprint_inventory.py walk-forward --json
    python scripts/sprint_inventory.py bootstrap permutation \\
        --out spec/sprints/c3_inventory.md

The script is stdlib-only (``ast``, ``pathlib``, ``argparse``) so it
runs identically in CI, locally, or under a pre-commit hook.
"""
from __future__ import annotations

import argparse
import ast
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Production scope. Top-level standalone modules (``terminal_*``,
# ``databento_*``, ``streamlit_*`` and other repo-root ``*.py``) are
# picked up via the explicit ``root.glob("*.py")`` in
# ``_iter_python_files``. Sub-package directories listed below are
# the production package set surfaced by the layout in ``pyproject.toml``
# (``[tool.setuptools] packages``) plus ``scripts/`` for the standalone
# CLI entry points. ``tests/`` is excluded by design; ``__pycache__``,
# ``.venv``, and ``artifacts/`` are excluded for noise.
_INCLUDE_DIRS: tuple[str, ...] = (
    "newsstack_fmp",
    "open_prep",
    "smc_core",
    "smc_integration",
    "smc_adapters",
    "smc_tv_bridge",
    "terminal_tabs",
    "scripts",
)
_EXCLUDE_PARTS: frozenset[str] = frozenset({
    "__pycache__",
    ".venv",
    ".git",
    "artifacts",
    "reports",
    "node_modules",
    ".pytest_cache",
})


@dataclass(frozen=True)
class _Hit:
    """One inventory hit: a function/class/module-level match."""

    path: str           # repo-relative
    line: int           # 1-based
    kind: str           # "function" | "class" | "module-doc" | "filename"
    name: str           # symbol or filename
    docstring_first_line: str = ""


@dataclass
class _InventoryResult:
    keywords: tuple[str, ...]
    hits: list[_Hit] = field(default_factory=list)
    files_scanned: int = 0


def _iter_python_files(root: Path) -> list[Path]:
    """Return every production ``*.py`` under repo, excluding noise dirs."""
    out: list[Path] = []
    # Top-level standalone modules (terminal_*, databento_*, streamlit_*,
    # SMC_*.pine is excluded automatically by the .py glob).
    for py in sorted(root.glob("*.py")):
        if py.name.startswith("test_"):
            continue
        out.append(py)
    for sub in sorted(_INCLUDE_DIRS):
        sub_path = root / sub
        if not sub_path.is_dir():
            continue
        for py in sorted(sub_path.rglob("*.py")):
            # Use the repo-relative parts so a parent directory named like
            # an excluded segment (e.g. cwd under ``~/reports/...``)
            # cannot accidentally exclude in-repo files.
            if any(part in _EXCLUDE_PARTS for part in py.relative_to(root).parts):
                continue
            if py.name.startswith("test_"):
                continue
            out.append(py)
    # De-duplicate while preserving discovery order.
    seen: set[Path] = set()
    deduped: list[Path] = []
    for p in out:
        if p in seen:
            continue
        seen.add(p)
        deduped.append(p)
    return deduped


def _matches(text: str, keywords: tuple[str, ...]) -> bool:
    """Case-insensitive substring match: any keyword present."""
    if not text:
        return False
    lowered = text.lower()
    return any(kw.lower() in lowered for kw in keywords)


def _docstring_first_line(node: ast.AST) -> str:
    doc = ast.get_docstring(node)
    if not doc:
        return ""
    return doc.strip().splitlines()[0][:120]


def _scan_file(path: Path, keywords: tuple[str, ...], rel_root: Path) -> list[_Hit]:
    """Parse ``path`` and return every symbol matching any keyword."""
    try:
        source = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    # Normalize to posix separators so output is identical on Windows.
    rel = path.relative_to(rel_root).as_posix()

    hits: list[_Hit] = []

    # Filename match (catches modules whose body uses other terms but the
    # filename is the topic, e.g. open_prep/outcomes.py for "outcome").
    if _matches(path.stem, keywords):
        hits.append(_Hit(path=rel, line=1, kind="filename", name=path.name))

    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError:
        return hits

    # Module-level docstring
    mod_doc = ast.get_docstring(tree) or ""
    if _matches(mod_doc, keywords):
        hits.append(_Hit(
            path=rel, line=1, kind="module-doc",
            name=path.stem,
            docstring_first_line=mod_doc.strip().splitlines()[0][:120],
        ))

    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            if _matches(node.name, keywords) or _matches(ast.get_docstring(node) or "", keywords):
                hits.append(_Hit(
                    path=rel, line=node.lineno,
                    kind="function", name=node.name,
                    docstring_first_line=_docstring_first_line(node),
                ))
        elif isinstance(node, ast.ClassDef) and (
            _matches(node.name, keywords) or _matches(ast.get_docstring(node) or "", keywords)
        ):
            hits.append(_Hit(
                path=rel, line=node.lineno,
                kind="class", name=node.name,
                docstring_first_line=_docstring_first_line(node),
            ))
    return hits


def run_inventory(keywords: tuple[str, ...], rel_root: Path | None = None) -> _InventoryResult:
    """Scan the repository for symbols matching any of ``keywords``."""
    root = rel_root or REPO_ROOT
    result = _InventoryResult(keywords=keywords)
    for py in _iter_python_files(root):
        result.files_scanned += 1
        result.hits.extend(_scan_file(py, keywords, root))
    return result


def _format_markdown(result: _InventoryResult) -> str:
    """Format result as a Markdown report ready to drop into spec/sprints/."""
    lines: list[str] = []
    kw_str = ", ".join(f"`{k}`" for k in result.keywords)
    lines.append(f"# Sprint inventory — {kw_str}")
    lines.append("")
    lines.append(
        f"_Scanned {result.files_scanned} production Python files. "
        f"Generated by `scripts/sprint_inventory.py`._"
    )
    lines.append("")
    if not result.hits:
        lines.append("**No existing symbols matched.** Treat as greenfield.")
        lines.append("")
        return "\n".join(lines)

    # Group by file for readability
    by_file: dict[str, list[_Hit]] = {}
    for hit in result.hits:
        by_file.setdefault(hit.path, []).append(hit)

    lines.append(f"**{len(result.hits)} hit(s) across {len(by_file)} file(s).**")
    lines.append("")
    lines.append(
        "Day-1 rule: for every hit below, decide **extend** vs. **ignore** "
        "BEFORE writing new code. New files require a one-line justification "
        "in the sprint plan."
    )
    lines.append("")
    for file_path in sorted(by_file):
        lines.append(f"## `{file_path}`")
        lines.append("")
        lines.append("| Line | Kind | Name | Docstring |")
        lines.append("|------|------|------|-----------|")
        for hit in sorted(by_file[file_path], key=lambda h: h.line):
            doc = hit.docstring_first_line.replace("|", "\\|") or "—"
            lines.append(f"| {hit.line} | {hit.kind} | `{hit.name}` | {doc} |")
        lines.append("")
    return "\n".join(lines)


def _format_json(result: _InventoryResult) -> str:
    payload = {
        "keywords": list(result.keywords),
        "files_scanned": result.files_scanned,
        "hits": [
            {
                "path": h.path,
                "line": h.line,
                "kind": h.kind,
                "name": h.name,
                "docstring_first_line": h.docstring_first_line,
            }
            for h in result.hits
        ],
    }
    return json.dumps(payload, indent=2, sort_keys=True)


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sprint_inventory",
        description=(
            "List existing modules / functions / classes whose name or "
            "docstring mentions any of the given topic keyword(s). "
            "Run as Day-1 step of any new C-sprint."
        ),
    )
    parser.add_argument(
        "keywords", nargs="+",
        help="One or more topic keywords (case-insensitive substring match).",
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Emit JSON instead of Markdown.",
    )
    parser.add_argument(
        "--out", type=Path, default=None,
        help="Write to this path instead of stdout.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_arg_parser()
    args = parser.parse_args(argv)
    result = run_inventory(tuple(args.keywords))
    rendered = _format_json(result) if args.json else _format_markdown(result)
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        # ATOMIC-WRITE-EXEMPT: CLI-utility output to user-specified path; not a runtime consumer.
        args.out.write_text(rendered + ("\n" if not rendered.endswith("\n") else ""), encoding="utf-8")
        sys.stderr.write(f"Wrote {args.out} ({len(result.hits)} hits across {result.files_scanned} files)\n")
    else:
        print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
