"""Smoke test for the default ``configs/c13/variant_family_map.json``.

Ensures the seed map shipped with the repo loads cleanly under the strict
:func:`scripts.build_families_telemetry.load_variant_family_map` validator,
covers all four canonical event families, and contains no entries pointing
to unknown families (regression guard for cron Step 5a).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.build_families_telemetry import (
    EVENT_FAMILIES,
    load_variant_family_map,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MAP_PATH = REPO_ROOT / "configs" / "c13" / "variant_family_map.json"


def test_default_variant_family_map_exists() -> None:
    assert DEFAULT_MAP_PATH.is_file(), f"Expected default seed map at {DEFAULT_MAP_PATH}"


def test_default_variant_family_map_loads_strict() -> None:
    mapping = load_variant_family_map(DEFAULT_MAP_PATH)
    assert mapping, "default variant->family map must not be empty"
    for variant, family in mapping.items():
        assert isinstance(variant, str) and variant
        assert family in EVENT_FAMILIES, f"variant {variant!r} → unknown family {family!r}"


def test_default_variant_family_map_covers_all_families() -> None:
    mapping = load_variant_family_map(DEFAULT_MAP_PATH)
    seen = set(mapping.values())
    missing = set(EVENT_FAMILIES) - seen
    assert not missing, f"default seed map missing coverage for families: {sorted(missing)}"


def test_default_variant_family_map_is_pure_json_object() -> None:
    raw = json.loads(DEFAULT_MAP_PATH.read_text(encoding="utf-8"))
    assert isinstance(raw, dict)
    # No metadata keys allowed — the strict loader rejects non-family values.
    for key in raw:
        assert not key.startswith("_"), f"meta key {key!r} would fail strict load_variant_family_map"


@pytest.mark.parametrize(
    "expected_variant",
    ["smc_breaker_btc", "smc_orderblock_btc", "smc_fvg_btc", "smc_sweep_btc"],
)
def test_default_variant_family_map_includes_canonical_btc_variants(
    expected_variant: str,
) -> None:
    mapping = load_variant_family_map(DEFAULT_MAP_PATH)
    assert expected_variant in mapping
