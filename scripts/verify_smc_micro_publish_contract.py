from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from scripts.smc_payload_volume import (
    PayloadVolume,
    measure_payload_volume,
    payload_blocking_reasons,
)

IMPORT_RE = re.compile(r"^\s*import\s+([A-Za-z0-9_/-]+)\s+as\s+([A-Za-z_][A-Za-z0-9_]*)\s*$")
IMPORT_PATH_RE = re.compile(r"^([A-Za-z0-9_-]+)/([A-Za-z0-9_-]+)/(\d+)$")
EXPECTED_DEPRECATED_POLICY_MODE = "compatibility_only"
EXPECTED_DEPRECATED_FIELD_VERSION = "v8.0a"


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _parse_import(line: str) -> tuple[str, str] | None:
    match = IMPORT_RE.match(line.strip())
    if not match:
        return None
    return match.group(1), match.group(2)


def _import_identity(import_path: str) -> tuple[str, str]:
    match = IMPORT_PATH_RE.match(import_path)
    if not match or int(match.group(3)) < 1:
        raise RuntimeError(f"Invalid versioned Pine import path: {import_path}")
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
    return any(haystack[start:start + len(needle)] == needle for start in range(0, len(haystack) - len(needle) + 1))


def _count_ordered_code_block_occurrences(haystack: list[str], needle: list[str]) -> int:
    if not needle:
        return 0
    matches = 0
    for start in range(0, len(haystack) - len(needle) + 1):
        if haystack[start : start + len(needle)] == needle:
            matches += 1
    return matches


def _load_productivity_gate(manifest: dict[str, object]) -> dict[str, object]:
    payload = manifest.get("productivity_gate")
    if not isinstance(payload, dict):
        raise RuntimeError("Generated manifest is missing productivity_gate metadata")

    required = (
        "publish_ready",
        "blocking_reasons",
        "fixture_input_detected",
        "default_event_risk_detected",
        "placeholder_symbols",
        # ADR-0029 — required, not optional: a manifest that omits its payload
        # measurement must fail rather than skip the cross-check.
        "payload_known",
        "universe_tickers_count",
        "list_total",
    )
    missing = [field for field in required if field not in payload]
    if missing:
        raise RuntimeError(
            "Generated manifest productivity_gate is incomplete: " + ", ".join(missing)
        )

    return payload


def _load_deprecated_field_policy(manifest: dict[str, object]) -> dict[str, object]:
    payload = manifest.get("deprecated_field_policy")
    if not isinstance(payload, dict):
        raise RuntimeError("Generated manifest is missing deprecated_field_policy metadata")

    required = (
        "mode",
        "preferred_field_version",
        "extension_allowed",
        "deprecated_groups",
    )
    missing = [field for field in required if field not in payload]
    if missing:
        raise RuntimeError(
            "Generated manifest deprecated_field_policy is incomplete: " + ", ".join(missing)
        )

    if payload.get("mode") != EXPECTED_DEPRECATED_POLICY_MODE:
        raise RuntimeError(
            "Generated manifest deprecated_field_policy.mode must stay compatibility_only"
        )
    if payload.get("preferred_field_version") != EXPECTED_DEPRECATED_FIELD_VERSION:
        raise RuntimeError(
            "Generated manifest deprecated_field_policy.preferred_field_version must stay v8.0a"
        )
    if payload.get("extension_allowed") is not False:
        raise RuntimeError(
            "Generated manifest deprecated_field_policy.extension_allowed must stay false"
        )
    if not isinstance(payload.get("deprecated_groups"), list):
        raise RuntimeError(
            "Generated manifest deprecated_field_policy.deprecated_groups must be a list"
        )

    return payload


def _verify_payload_matches_manifest(
    productivity_gate: dict[str, object],
    payload: PayloadVolume,
) -> None:
    """Fail when the manifest's recorded payload volume is not what shipped."""
    claimed_known = bool(productivity_gate.get("payload_known"))
    measured_known = payload.known
    if claimed_known != measured_known:
        raise RuntimeError(
            "Generated manifest productivity_gate.payload_known does not match the "
            f"library: manifest={claimed_known}, library={measured_known}"
        )
    if not measured_known:
        return

    for field, measured in (
        ("universe_tickers_count", payload.universe_tickers_count),
        ("list_total", payload.list_total),
    ):
        claimed = productivity_gate.get(field)
        if claimed != measured:
            raise RuntimeError(
                f"Generated manifest productivity_gate.{field} does not match the "
                f"library: manifest={claimed}, library={measured}"
            )


def verify_publish_contract(manifest_path: Path, core_path: Path) -> dict[str, str]:
    repo_root = core_path.resolve().parent
    manifest = json.loads(_read_text(manifest_path))
    productivity_gate = _load_productivity_gate(manifest)
    deprecated_field_policy = _load_deprecated_field_policy(manifest)

    recommended_import_path = str(manifest["recommended_import_path"])
    snippet_path = repo_root / str(manifest["core_import_snippet"])
    library_path = repo_root / str(manifest["pine_library"])

    blocking_reasons = productivity_gate.get("blocking_reasons")
    if productivity_gate.get("publish_ready") is not True:
        reasons_payload = blocking_reasons if isinstance(blocking_reasons, list) else []
        reasons = ", ".join(str(reason) for reason in reasons_payload) or "unspecified"
        placeholder_symbols = productivity_gate.get("placeholder_symbols") or []
        placeholder_suffix = ""
        if isinstance(placeholder_symbols, list) and placeholder_symbols:
            placeholder_suffix = f"; placeholder_symbols={','.join(str(symbol) for symbol in placeholder_symbols)}"
        raise RuntimeError(
            f"Generated library source is not publish-ready: {reasons}{placeholder_suffix}"
        )

    if not snippet_path.exists():
        raise RuntimeError(f"Missing core import snippet: {snippet_path}")
    if not library_path.exists():
        raise RuntimeError(f"Missing generated Pine library: {library_path}")
    if not core_path.exists():
        raise RuntimeError(f"Missing core file: {core_path}")

    # ADR-0029: check the library against the manifest's claim about it. Until
    # now this verifier only compared paths, so a manifest could vouch for a
    # library it contradicted — which is how an empty payload shipped green.
    payload = measure_payload_volume(_read_text(library_path))
    _verify_payload_matches_manifest(productivity_gate, payload)
    payload_reasons = payload_blocking_reasons(
        payload,
        static_control_plane=manifest.get("generation_mode") == "static_control_plane",
    )
    if payload_reasons:
        raise RuntimeError(
            "Generated Pine library carries no payload: " + ", ".join(payload_reasons)
        )

    snippet_text = _read_text(snippet_path)
    snippet_lines = _code_lines(snippet_text)
    if not snippet_lines:
        raise RuntimeError("Core import snippet is empty")

    snippet_import = _parse_import(snippet_lines[0])
    if snippet_import is None:
        raise RuntimeError("Core import snippet does not start with a valid import line")
    snippet_import_path, snippet_alias = snippet_import
    recommended_identity = _import_identity(recommended_import_path)
    if _import_identity(snippet_import_path) != recommended_identity:
        raise RuntimeError(
            f"Snippet library identity mismatch: expected {recommended_import_path}, found {snippet_import_path}"
        )

    core_text = _read_text(core_path)
    core_import_path = _find_import_path_for_alias(core_text, snippet_alias)
    if _import_identity(core_import_path) != recommended_identity:
        raise RuntimeError(
            f"Core import library identity mismatch for alias {snippet_alias}: expected {recommended_import_path}, found {core_import_path}"
        )

    core_code_lines = _code_lines(core_text)
    if not _contains_ordered_code_block(core_code_lines, snippet_lines[1:]):
        raise RuntimeError(
            "Core file is missing the generated import snippet as a contiguous alias block. "
            f"Expected block: {snippet_lines}"
        )
    occurrence_count = _count_ordered_code_block_occurrences(core_code_lines, snippet_lines[1:])
    if occurrence_count != 1:
        raise RuntimeError(
            "Core file must contain the generated import snippet alias block exactly once as real contiguous code. "
            f"Observed occurrences: {occurrence_count}"
        )

    return {
        "manifest_path": str(manifest_path),
        "core_path": str(core_path),
        "snippet_path": str(snippet_path),
        "library_path": str(library_path),
        "recommended_import_path": recommended_import_path,
        "alias": snippet_alias,
        "core_import_path": core_import_path,
        "deprecated_policy_mode": str(deprecated_field_policy["mode"]),
        "preferred_field_version": str(deprecated_field_policy["preferred_field_version"]),
        "publish_ready": "true",
        "payload_known": str(payload.known).lower(),
        "universe_tickers_count": str(payload.universe_tickers_count),
        "list_total": str(payload.list_total),
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
        default=Path("SMC_Long_Dip_Suite.pine"),
        help="Path to the SMC core Pine file.",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    result = verify_publish_contract(args.manifest, args.core)
    print(json.dumps({"ok": True, **result}, indent=2))


if __name__ == "__main__":
    main()
