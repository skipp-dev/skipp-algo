"""WP-A5 contract: every Pine mp.* reference maps to a generated library field."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
_PINE_DIR = ROOT
_GENERATORS = [
    ROOT / "scripts" / "generate_smc_micro_profiles.py",
    ROOT / "scripts" / "smc_microstructure_base_runtime.py",
]

# Known orphan references that are tolerated until their Pine consumer is cleaned up.
_KNOWN_ORPHANS: set[str] = {
    "FVG_NET_IMBALANCE",  # SMC_Imbalance_Context.pine — stale, no generator
}


def _collect_generated_fields() -> set[str]:
    """Parse all generators for 'export const' field names and render_csv_export calls."""
    from scripts.generate_smc_micro_profiles import LIST_EXPORTS

    fields: set[str] = set()
    for gen in _GENERATORS:
        source = gen.read_text(encoding="utf-8")
        # Direct: export const float FIELD_NAME
        fields.update(re.findall(r"export const (?:float|int|bool|string) (\w+)", source))
        # render_csv_export("FIELD_NAME", ...)
        fields.update(re.findall(r'render_csv_export\(\s*"([A-Z_][A-Z0-9_]+)"', source))
        # f-string: f'export const {type} {FIELD_NAME}' — with literal field name in f-string
        fields.update(re.findall(r"export const (?:float|int|bool|string) ([A-Z_][A-Z0-9_]+)", source))
    # Dynamic list exports (render_list calls)
    fields.update(LIST_EXPORTS.values())
    return fields


def _collect_pine_mp_refs() -> dict[str, set[str]]:
    """Return {pine_file: {field_names}} for all mp.FIELD references."""
    result: dict[str, set[str]] = {}
    for pine in sorted(_PINE_DIR.glob("*.pine")):
        source = pine.read_text(encoding="utf-8")
        refs = set(re.findall(r"\bmp\.([A-Z_][A-Z0-9_]+)", source))
        if refs:
            result[pine.name] = refs
    return result


def test_all_pine_mp_refs_resolve_to_generated_fields() -> None:
    generated = _collect_generated_fields()
    pine_refs = _collect_pine_mp_refs()

    orphans: list[str] = []
    for fname, refs in sorted(pine_refs.items()):
        for ref in sorted(refs):
            if ref not in generated and ref not in _KNOWN_ORPHANS:
                orphans.append(f"  {fname} -> mp.{ref}")

    assert orphans == [], (
        f"Pine mp.* references to non-existent library fields:\n"
        + "\n".join(orphans)
    )


def test_known_orphans_are_still_orphans() -> None:
    """Prevent _KNOWN_ORPHANS from going stale — remove entries once the field is generated."""
    generated = _collect_generated_fields()
    for orphan in _KNOWN_ORPHANS:
        assert orphan not in generated, (
            f"{orphan} is now generated — remove it from _KNOWN_ORPHANS"
        )


def test_field_count_is_within_audit_bounds() -> None:
    """Total generated fields should be documented in the audit."""
    generated = _collect_generated_fields()
    assert len(generated) >= 250, f"Field count dropped unexpectedly: {len(generated)}"
    assert len(generated) <= 320, f"Field count grew unexpectedly: {len(generated)}"
