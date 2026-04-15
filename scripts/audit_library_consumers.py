"""WP-OV6: Audit library export fields against Pine consumer references.

Extracts all ``export const`` field names from the generated library,
scans all consumer .pine files for ``mp.FIELD`` references, and reports
the delta (exported but never consumed, consumed but not exported).
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import NamedTuple

REPO_ROOT = Path(__file__).resolve().parents[1]

# Pattern for export const lines in the generated library.
_EXPORT_RE = re.compile(
    r"^export\s+const\s+\w+\s+(\w+)\s*=", re.MULTILINE
)

# Pattern for mp.FIELD_NAME references in consumer scripts.
_CONSUMER_RE = re.compile(r"\bmp\.([A-Z_][A-Z0-9_]*)\b")


class AuditResult(NamedTuple):
    exported: set[str]
    consumed: set[str]
    no_consumer: set[str]  # exported but never consumed
    missing_export: set[str]  # consumed but not exported


def find_library_path(repo_root: Path | None = None) -> Path:
    root = repo_root or REPO_ROOT
    candidates = sorted(root.glob("pine/generated/smc_micro_profiles_generated.pine"))
    if not candidates:
        candidates = sorted(root.glob("**/smc_micro_profiles_generated.pine"))
    if not candidates:
        raise FileNotFoundError("smc_micro_profiles_generated.pine not found")
    return candidates[0]


def find_consumer_pines(repo_root: Path | None = None) -> list[Path]:
    """Return all .pine files that import the micro-profiles library."""
    root = repo_root or REPO_ROOT
    consumers: list[Path] = []
    import_pattern = re.compile(r"smc_micro_profiles_generated")
    for pine in sorted(root.rglob("*.pine")):
        if pine.name == "smc_micro_profiles_generated.pine":
            continue
        try:
            text = pine.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if import_pattern.search(text):
            consumers.append(pine)
    return consumers


def extract_exports(library_text: str) -> set[str]:
    return set(_EXPORT_RE.findall(library_text))


def extract_consumer_refs(pine_texts: list[str]) -> set[str]:
    refs: set[str] = set()
    for text in pine_texts:
        refs.update(_CONSUMER_RE.findall(text))
    return refs


def audit(
    repo_root: Path | None = None,
    *,
    library_path: Path | None = None,
    consumer_paths: list[Path] | None = None,
) -> AuditResult:
    root = repo_root or REPO_ROOT
    lib_path = library_path or find_library_path(root)
    library_text = lib_path.read_text(encoding="utf-8")
    exported = extract_exports(library_text)

    consumers = consumer_paths if consumer_paths is not None else find_consumer_pines(root)
    pine_texts = [p.read_text(encoding="utf-8", errors="replace") for p in consumers]
    consumed = extract_consumer_refs(pine_texts)

    return AuditResult(
        exported=exported,
        consumed=consumed,
        no_consumer=exported - consumed,
        missing_export=consumed - exported,
    )


def format_report(result: AuditResult) -> str:
    lines = [
        "# Library Field Audit",
        "",
        f"- Exported fields: {len(result.exported)}",
        f"- Consumed fields: {len(result.consumed)}",
        f"- No consumer (exported only): {len(result.no_consumer)}",
        f"- Missing export (consumed only): {len(result.missing_export)}",
        "",
    ]

    if result.no_consumer:
        lines.append("## Fields Without Consumer")
        lines.append("")
        for field_name in sorted(result.no_consumer):
            lines.append(f"- `{field_name}`")
        lines.append("")

    if result.missing_export:
        lines.append("## Missing Exports (referenced but not exported)")
        lines.append("")
        for field_name in sorted(result.missing_export):
            lines.append(f"- `{field_name}`")
        lines.append("")

    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit SMC library field consumers.")
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=REPO_ROOT,
        help="Repository root directory.",
    )
    args = parser.parse_args()
    result = audit(repo_root=args.repo_root)
    print(format_report(result))
    if result.missing_export:
        print(
            f"WARNING: {len(result.missing_export)} consumed field(s) have no export.",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
