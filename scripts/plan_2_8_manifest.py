"""Plan 2.8 script manifest.

Scans ``scripts/plan_2_8_*.py`` and ``tests/test_plan_2_8_*.py`` in
the repository root and emits a manifest JSON describing:

  - each script's path and paired test (if any)
  - CLI flags declared via ``argparse.ArgumentParser.add_argument``
    (discovered by static regex, not exec)
  - counts summary

This is a static documentation probe only; no scripts are imported
or executed. Pure stdlib.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import re
import sys
from pathlib import Path
from typing import Any

from scripts.smc_atomic_write import atomic_write_text

FLAG_RE = re.compile(r'add_argument\(\s*["\'](--?[A-Za-z0-9][A-Za-z0-9\-_]*)["\']')


def _extract_flags(src: str) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for m in FLAG_RE.finditer(src):
        flag = m.group(1)
        if flag in seen:
            continue
        seen.add(flag)
        out.append(flag)
    return out


def scan(repo_root: Path) -> dict[str, Any]:
    scripts_dir = repo_root / "scripts"
    tests_dir = repo_root / "tests"
    scripts = sorted(scripts_dir.glob("plan_2_8_*.py")) \
        if scripts_dir.exists() else []
    test_files: dict[str, Path] = {}
    if tests_dir.exists():
        for p in tests_dir.glob("test_plan_2_8_*.py"):
            test_files[p.stem] = p

    rows: list[dict[str, Any]] = []
    with_tests = 0
    for script in scripts:
        stem = script.stem  # e.g. plan_2_8_health
        test_stem = "test_" + stem
        paired = test_files.get(test_stem)
        flags: list[str] = []
        with contextlib.suppress(OSError):
            flags = _extract_flags(script.read_text(encoding="utf-8"))
        rows.append({
            "script":     script.relative_to(repo_root).as_posix(),
            "test":       paired.relative_to(repo_root).as_posix()
                          if paired is not None else None,
            "has_test":   paired is not None,
            "cli_flags":  flags,
        })
        if paired is not None:
            with_tests += 1

    return {
        "schema_version": 1,
        "repo_root":      str(repo_root),
        "counts": {
            "scripts":   len(scripts),
            "with_test": with_tests,
            "without":   len(scripts) - with_tests,
        },
        "entries": rows,
    }


def render_markdown(report: dict[str, Any]) -> str:
    c = report["counts"]
    lines = [
        "# Plan 2.8 script manifest",
        "",
        f"- scripts:     {c['scripts']}",
        f"- with tests:  {c['with_test']}",
        f"- without:     {c['without']}",
        "",
        "| script | test | flags |",
        "| --- | --- | --- |",
    ]
    for row in report["entries"]:
        flags = ", ".join(f"`{f}`" for f in row["cli_flags"]) or "-"
        test = f"`{row['test']}`" if row["test"] else "_missing_"
        lines.append(f"| `{row['script']}` | {test} | {flags} |")
    return "\n".join(lines) + "\n"

# F-V6-A1.1 (2026-05-02): bootstrap root logging so the logger.info(...)
# progress messages this entry point emits actually surface in CI logs
# (default WARNING-only handler would drop them). Extends F-V5-A1-2 / #2012
# from the priority entry-point set to plan_2_8 aggregators + showcase.
try:
    from scripts._logging_init import init_cli_logging
except ImportError:  # script-style invocation: `python scripts/X.py`
    import sys as _v6a11_sys
    from pathlib import Path as _v6a11_Path

    _v6a11_sys.path.insert(0, str(_v6a11_Path(__file__).resolve().parents[1]))
    from scripts._logging_init import init_cli_logging  # type: ignore[no-redef]




def main(argv: list[str] | None = None) -> int:
    init_cli_logging()  # F-V6-A1.1 (2026-05-02)
    parser = argparse.ArgumentParser(
        description="Scan plan_2_8 scripts and emit a manifest.",
    )
    parser.add_argument(
        "--repo-root", type=Path,
        default=Path(__file__).resolve().parents[1],
    )
    parser.add_argument("--format", choices=("md", "json"), default="json")
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--fail-on-missing-test", action="store_true")
    args = parser.parse_args(argv)

    if not args.repo_root.exists():
        print(f"ERROR: repo-root not found: {args.repo_root}",
              file=sys.stderr)
        return 1
    report = scan(args.repo_root)
    body = render_markdown(report) if args.format == "md" \
        else json.dumps(report, indent=2) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(body, args.output)
    print(body, end="")
    if args.fail_on_missing_test and report["counts"]["without"] > 0:
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
