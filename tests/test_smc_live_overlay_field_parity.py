"""Cross-language field-name parity for the live overlay (WP-F).

The overlay spans two languages with no shared compiler: the Python contract
(``smc_tv_bridge.contracts.live_overlay``) defines the wire field names the
``GET /smc_live`` endpoint emits, and the Pine bridge
(``SMC_TV_Bridge.pine``) reads them back via ``f_getField(body, "<key>")``.
A rename or typo on either side silently breaks the overlay in production
(Pine reads ``na`` -> permanent ``mp.*`` fallback, no error surfaced).

These tests pin the parity invariant:
  * Pine still reads every Phase-1 overlay key (guards a Pine-side removal
    or typo such as ``"newsStrength"``).
  * Every overlay key Pine reads is a valid contract wire-name (guards a
    contract-side rename).

Scope note: the Pine file also reads the legacy ``/smc_tv`` snapshot keys
(``bos``/``ob``/``fvg``/``sweeps``/``regime``/``tech``/``news``); those are
NOT live-overlay contract fields and are intentionally excluded here.
"""
from __future__ import annotations

import re
from pathlib import Path

from smc_tv_bridge.contracts.live_overlay import LiveOverlayPayload

_PINE_PATH = Path(__file__).resolve().parents[1] / "SMC_TV_Bridge.pine"

# Phase-1 overlay keys the Pine bridge reads from GET /smc_live (lines 72-76
# of SMC_TV_Bridge.pine). Kept explicit so adding an overlay field is a
# deliberate, reviewed change on BOTH sides.
_OVERLAY_KEYS_READ_BY_PINE = frozenset(
    {"asof_ts", "stale", "news_strength", "flow_rel_vol", "squeeze_on"}
)

# Matches f_getField(body, "<key>") calls; the helper definition
# `f_getField(string src, string key) =>` does not match (no quoted literal).
_F_GETFIELD = re.compile(r'f_getField\(\s*body\s*,\s*"([a-z_]+)"\s*\)')


def _pine_getfield_keys() -> set[str]:
    text = _PINE_PATH.read_text(encoding="utf-8")
    return set(_F_GETFIELD.findall(text))


def _contract_wire_names() -> set[str]:
    return {(f.alias or name) for name, f in LiveOverlayPayload.model_fields.items()}


def test_pine_reads_all_phase1_overlay_keys() -> None:
    """Pine must still read every Phase-1 overlay key (catches rename/removal)."""
    pine_keys = _pine_getfield_keys()
    missing = _OVERLAY_KEYS_READ_BY_PINE - pine_keys
    assert not missing, f"Pine no longer reads overlay key(s): {sorted(missing)}"


def test_overlay_keys_are_valid_contract_wire_names() -> None:
    """Every overlay key Pine reads must be a valid contract wire-name."""
    wire = _contract_wire_names()
    unknown = _OVERLAY_KEYS_READ_BY_PINE - wire
    assert not unknown, (
        f"Pine reads overlay key(s) absent from the contract: {sorted(unknown)}. "
        "A field was renamed on one side only."
    )


def test_no_camelcase_drift_for_shared_overlay_keys() -> None:
    """Guard the snake_case spelling: no camelCase near-miss leaked into Pine."""
    pine_keys = _pine_getfield_keys()
    # Any Pine key that lowercases-and-strips-underscores to a contract field
    # but is NOT an exact match would be a silent drift (e.g. newsStrength).
    wire = _contract_wire_names()
    normalized_wire = {w.replace("_", "").lower(): w for w in wire}
    for key in pine_keys:
        norm = key.replace("_", "").lower()
        if norm in normalized_wire:
            assert key == normalized_wire[norm], (
                f"Pine key {key!r} drifted from contract wire-name "
                f"{normalized_wire[norm]!r}"
            )
