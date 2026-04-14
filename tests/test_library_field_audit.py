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


# ── WP-A6: Compatibility Fields Sunset ──────────────────────────


def test_deprecated_field_policy_has_sunset_date() -> None:
    """DEPRECATED_FIELD_POLICY must include a sunset_date (WP-A6)."""
    from scripts.smc_bus_manifest import DEPRECATED_FIELD_POLICY

    assert "sunset_date" in DEPRECATED_FIELD_POLICY
    sunset = DEPRECATED_FIELD_POLICY["sunset_date"]
    assert isinstance(sunset, str) and len(sunset) == 10, f"Invalid sunset_date: {sunset}"
    from datetime import date as _date
    _date.fromisoformat(sunset)  # must parse


def test_deprecated_field_policy_has_sunset_action() -> None:
    from scripts.smc_bus_manifest import DEPRECATED_FIELD_POLICY

    assert DEPRECATED_FIELD_POLICY.get("sunset_action") == "remove_from_export"


def test_generator_logs_sunset_warning(caplog) -> None:
    """write_pine_library logs a warning when sunset is near or past."""
    import logging
    from datetime import date as _date, timedelta
    from unittest.mock import patch

    from scripts.smc_bus_manifest import DEPRECATED_FIELD_POLICY

    past_date = (_date.today() - timedelta(days=1)).isoformat()
    patched_policy = {**DEPRECATED_FIELD_POLICY, "sunset_date": past_date}

    with (
        patch("scripts.smc_bus_manifest.DEPRECATED_FIELD_POLICY", patched_policy),
        caplog.at_level(logging.WARNING, logger="scripts.generate_smc_micro_profiles"),
    ):
        # We don't need to run the full library write — just import and trigger
        # the sunset check by calling write_pine_library with minimal args
        from scripts.generate_smc_micro_profiles import write_pine_library
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            try:
                write_pine_library(
                    Path(td) / "test.pine",
                    {name: [] for name in ["clean_reclaim", "stop_hunt_prone", "midday_dead", "rth_only", "weak_premarket", "weak_afterhours", "fast_decay"]},
                    "2026-04-15",
                    100,
                )
            except Exception:
                pass  # May fail on missing enrichment data, that's OK

    assert any("sunset" in r.message.lower() for r in caplog.records), (
        "Expected sunset warning in log"
    )
