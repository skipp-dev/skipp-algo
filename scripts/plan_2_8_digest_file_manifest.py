"""Plan 2.8 file-manifest presence checker.

Lists every ``scripts/plan_2_8_*.py`` (excluding this script and
``plan_2_8_status.py``) and every matching
``tests/test_plan_2_8_*.py`` and reports the cross-product:

- scripts without a matching test  (``orphan_scripts``)
- tests without a matching script  (``orphan_tests``)
- total counts

Pure stdlib. Does not import any of the target scripts.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from scripts.smc_atomic_write import atomic_write_text

SELF_NAME = "plan_2_8_digest_file_manifest.py"
STATUS_NAME = "plan_2_8_status.py"


def _stems(glob_iter: list[Path], *, excludes: set[str]) -> set[str]:
    out: set[str] = set()
    for p in glob_iter:
        if p.name in excludes:
            continue
        out.add(p.stem)
    return out


def scan(repo_root: Path) -> dict[str, Any]:
    scripts_dir = repo_root / "scripts"
    tests_dir = repo_root / "tests"
    script_stems = _stems(
        sorted(scripts_dir.glob("plan_2_8_*.py")),
        excludes={SELF_NAME, STATUS_NAME},
    )
    test_stems = {
        name
        for p in sorted(tests_dir.glob("test_plan_2_8_*.py"))
        for name in [p.stem.removeprefix("test_")]
    }
    orphan_scripts = sorted(script_stems - test_stems)
    orphan_tests = sorted(test_stems - script_stems)
    return {
        "schema_version": 1,
        "counts": {
            "scripts":        len(script_stems),
            "tests":          len(test_stems),
            "orphan_scripts": len(orphan_scripts),
            "orphan_tests":   len(orphan_tests),
        },
        "orphan_scripts": orphan_scripts,
        "orphan_tests":   orphan_tests,
    }


def render_markdown(report: dict[str, Any]) -> str:
    c = report["counts"]
    lines = [
        "# Plan 2.8 file manifest",
        "",
        f"- scripts:        {c['scripts']}",
        f"- tests:          {c['tests']}",
        f"- orphan scripts: {c['orphan_scripts']}",
        f"- orphan tests:   {c['orphan_tests']}",
        "",
    ]
    if report["orphan_scripts"]:
        lines.append("## Scripts without tests")
        lines.extend(f"- `{s}`" for s in report["orphan_scripts"])
        lines.append("")
    if report["orphan_tests"]:
        lines.append("## Tests without scripts")
        lines.extend(f"- `{s}`" for s in report["orphan_tests"])
        lines.append("")
    if not report["orphan_scripts"] and not report["orphan_tests"]:
        lines.append("_All scripts have matching tests._")
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
        description="Check Plan 2.8 script/test file manifest.",
    )
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    parser.add_argument("--format", choices=("md", "json"), default="md")
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--fail-on-orphan", action="store_true")
    args = parser.parse_args(argv)

    if not (args.repo_root / "scripts").is_dir() \
            or not (args.repo_root / "tests").is_dir():
        print("ERROR: --repo-root must contain scripts/ and tests/",
              file=sys.stderr)
        return 1

    report = scan(args.repo_root)
    body = render_markdown(report) if args.format == "md" \
        else json.dumps(report, indent=2) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(body, args.output)
    print(body, end="")
    if args.fail_on_orphan and (
        report["counts"]["orphan_scripts"] > 0
        or report["counts"]["orphan_tests"] > 0
    ):
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
