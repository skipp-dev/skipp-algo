"""Smoke test for the default ``configs/c13/variant_family_map.json``.

Ensures the seed map shipped with the repo loads cleanly under the strict
:func:`scripts.build_families_telemetry.load_variant_family_map` validator
and contains no entries pointing to unknown families (regression guard for
cron Step 5a).

Scope note: the seed map intentionally tracks only variants that are
actually produced by the live pipeline today (``smc_breaker_btc``). It
will grow as new SMC variants ship — at that point the coverage check
below can be tightened to require all of ``EVENT_FAMILIES``.
"""

from __future__ import annotations

import json
from pathlib import Path

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


def test_default_variant_family_map_uses_only_known_families() -> None:
    mapping = load_variant_family_map(DEFAULT_MAP_PATH)
    seen = set(mapping.values())
    unknown = seen - set(EVENT_FAMILIES)
    assert not unknown, f"default seed map references unknown families: {sorted(unknown)}"
    # At least one family must be represented. NOTE:
    # ``load_variant_family_map`` does *not* reject an empty ``{}`` (it
    # only validates key/value types and family membership), so this
    # assertion — together with ``assert mapping`` in the strict-load
    # test above — is what enforces non-emptiness for the seed map.
    assert seen, "default seed map covers no families"


def test_default_variant_family_map_is_pure_json_object() -> None:
    raw = json.loads(DEFAULT_MAP_PATH.read_text(encoding="utf-8"))
    assert isinstance(raw, dict)
    # No metadata keys allowed — the strict loader rejects non-family values.
    for key in raw:
        assert not key.startswith("_"), f"meta key {key!r} would fail strict load_variant_family_map"


def test_default_variant_family_map_includes_smc_breaker_btc() -> None:
    # ``smc_breaker_btc`` is currently the only variant produced by the live
    # pipeline (see scripts/compute_live_drift.py + scripts/build_dashboard_payload.py).
    # Additional canonical variants will be added here as they ship.
    mapping = load_variant_family_map(DEFAULT_MAP_PATH)
    assert "smc_breaker_btc" in mapping
    assert mapping["smc_breaker_btc"] == "BOS"
