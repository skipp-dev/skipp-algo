from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


IMPORT_RE = re.compile(r"^\s*import\s+([A-Za-z0-9_/-]+)\s+as\s+([A-Za-z_][A-Za-z0-9_]*)\s*$")


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _parse_import(line: str) -> tuple[str, str] | None:
    match = IMPORT_RE.match(line.strip())
    if not match:
        return None
    return match.group(1), match.group(2)


def _find_first_import_line(text: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("//"):
            continue
        if stripped.startswith("import "):
            return stripped
    raise RuntimeError("No import line found")


def _find_import_path_for_alias(text: str, alias: str) -> str:
    for line in text.splitlines():
        parsed = _parse_import(line)
        if parsed and parsed[1] == alias:
            return parsed[0]
    raise RuntimeError(f"No import found for alias {alias}")


def _code_lines(text: str) -> list[str]:
    lines: list[str] = []
    for raw_line in text.splitlines():
        stripped = _strip_inline_comment(raw_line).strip()
        if not stripped or stripped.startswith("//"):
            continue
        lines.append(stripped)
    return lines


def _strip_inline_comment(line: str) -> str:
    quote: str | None = None
    escaped = False
    index = 0
    while index < len(line):
        current = line[index]
        nxt = line[index + 1] if index + 1 < len(line) else ""
        if quote is not None:
            if escaped:
                escaped = False
            elif current == "\\":
                escaped = True
            elif current == quote:
                quote = None
            index += 1
            continue
        if current in {'"', "'"}:
            quote = current
            index += 1
            continue
        if current == "/" and nxt == "/":
            return line[:index]
        index += 1
    return line


def _contains_ordered_code_block(haystack: list[str], needle: list[str]) -> bool:
    if not needle:
        return False
    for start in range(0, len(haystack) - len(needle) + 1):
        if haystack[start : start + len(needle)] == needle:
            return True
    return False


def verify_publish_contract(manifest_path: Path, core_path: Path) -> dict[str, str]:
    repo_root = core_path.resolve().parent
    manifest = json.loads(_read_text(manifest_path))

    recommended_import_path = str(manifest["recommended_import_path"])
    snippet_path = repo_root / str(manifest["core_import_snippet"])
    library_path = repo_root / str(manifest["pine_library"])

    if not snippet_path.exists():
        raise RuntimeError(f"Missing core import snippet: {snippet_path}")
    if not library_path.exists():
        raise RuntimeError(f"Missing generated Pine library: {library_path}")
    if not core_path.exists():
        raise RuntimeError(f"Missing core file: {core_path}")

    snippet_text = _read_text(snippet_path)
    snippet_lines = _code_lines(snippet_text)
    if not snippet_lines:
        raise RuntimeError("Core import snippet is empty")

    snippet_import = _parse_import(snippet_lines[0])
    if snippet_import is None:
        raise RuntimeError("Core import snippet does not start with a valid import line")
    snippet_import_path, snippet_alias = snippet_import
    if snippet_import_path != recommended_import_path:
        raise RuntimeError(
            f"Snippet import path mismatch: expected {recommended_import_path}, found {snippet_import_path}"
        )

    core_text = _read_text(core_path)
    core_import_path = _find_import_path_for_alias(core_text, snippet_alias)
    if core_import_path != recommended_import_path:
        raise RuntimeError(
            f"Core import path mismatch for alias {snippet_alias}: expected {recommended_import_path}, found {core_import_path}"
        )

    core_code_lines = _code_lines(core_text)
    if not _contains_ordered_code_block(core_code_lines, snippet_lines[1:]):
        raise RuntimeError(
            "Core file is missing the generated import snippet as a contiguous alias block. "
            f"Expected block: {snippet_lines}"
        )

    return {
        "manifest_path": str(manifest_path),
        "core_path": str(core_path),
        "snippet_path": str(snippet_path),
        "library_path": str(library_path),
        "recommended_import_path": recommended_import_path,
        "alias": snippet_alias,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Verify that the generated microstructure library manifest, import snippet, and SMC core import stay aligned."
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("pine/generated/smc_micro_profiles_generated.json"),
        help="Path to the generated microstructure manifest.",
    )
    parser.add_argument(
        "--core",
        type=Path,
        default=Path("SMC_Core_Engine.pine"),
        help="Path to the SMC core Pine file.",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    result = verify_publish_contract(args.manifest, args.core)
    print(json.dumps({"ok": True, **result}, indent=2))


if __name__ == "__main__":
    main()