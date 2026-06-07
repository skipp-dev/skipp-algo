"""Fallback-safety tests for the live overlay (WP-D).

The Pine bridge augments its 2x/day baked ``mp.*`` baseline with the live
overlay served at ``GET /smc_live``. Any field the overlay does not serve
fresh must be ABSENT from the JSON so Pine reads ``na`` and silently falls
back to the baked ``mp.*`` value; a stale or unreachable endpoint degrades to
the baked baseline. These tests pin the CONTRACT-level guarantees that make
that fallback safe. The Pine-side ``request.get``/``na`` handling itself is
covered by the TypeScript bridge tests in CI.

Scenario table::

  server state          emitted payload                  Pine behavior
  --------------------  ------------------------------  -----------------------
  fully fresh (B1)      envelope + news_strength/bias   override news, mp.* rest
  partial (news only)   envelope + news_* only          mp.* for flow/squeeze
  nothing fresh         envelope only                   mp.* for ALL data fields
  self-declared stale   envelope(stale=True)            fallback-only baseline
  endpoint down         (no HTTP response)              mp.* for ALL (Pine na)
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from smc_tv_bridge.contracts.live_overlay import (
    ENVELOPE_FIELDS,
    LiveOverlayPayload,
    flatten_overlay,
)

_SCHEMA_PATH = Path(__file__).resolve().parents[1] / "spec" / "smc_live_overlay.schema.json"

# Every overlay (non-envelope) field: absence -> Pine falls back to baked mp.*.
_OPTIONAL_FIELDS = (
    "news_strength",
    "news_bias",
    "flow_rel_vol",
    "squeeze_on",
    "vix_level",
    "flow_delta_proxy_pct",
    "ats_state",
    "ats_zscore",
    "tone",
)

# A valid concrete value per optional field, for the "present -> emitted" case.
_SAMPLE_VALUES: dict[str, object] = {
    "news_strength": 0.7,
    "news_bias": "BULLISH",
    "flow_rel_vol": 1.4,
    "squeeze_on": 1,
    "vix_level": 18.5,
    "flow_delta_proxy_pct": 12.0,
    "ats_state": "RISK_ON",
    "ats_zscore": 1.2,
    "tone": "calm",
}


def _envelope_only() -> LiveOverlayPayload:
    """The minimal 'nothing fresh' payload: envelope set, all overlay fields None."""
    return LiveOverlayPayload(symbol="AAPL", tf="15m", asof_ts=1, stale=False)


def _schema() -> dict:
    return json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))


def test_nothing_fresh_emits_envelope_only() -> None:
    """All overlay fields None -> flatten yields exactly the five envelope keys."""
    flat = flatten_overlay(_envelope_only())
    assert set(flat) == set(ENVELOPE_FIELDS)
    for field in _OPTIONAL_FIELDS:
        assert field not in flat


@pytest.mark.parametrize("field", _OPTIONAL_FIELDS)
def test_none_optional_field_is_dropped(field: str) -> None:
    """A None overlay field is absent from JSON so Pine falls back to mp.*."""
    payload = _envelope_only().model_copy(update={field: None})
    assert field not in flatten_overlay(payload)


@pytest.mark.parametrize("field", _OPTIONAL_FIELDS)
def test_present_optional_field_is_emitted(field: str) -> None:
    """A fresh overlay field IS emitted so the overlay overrides the baked value."""
    payload = _envelope_only().model_copy(update={field: _SAMPLE_VALUES[field]})
    assert field in flatten_overlay(payload)


def test_partial_overlay_keeps_unserved_fields_absent() -> None:
    """Serving only news leaves flow/squeeze/B2 absent -> mp.* fallback for those."""
    payload = _envelope_only().model_copy(
        update={"news_strength": 0.7, "news_bias": "BEARISH"}
    )
    flat = flatten_overlay(payload)
    assert flat["news_strength"] == 0.7
    assert flat["news_bias"] == "BEARISH"
    for field in ("flow_rel_vol", "squeeze_on", "vix_level", "ats_state", "tone"):
        assert field not in flat


def test_stale_flag_roundtrips() -> None:
    """A self-declared stale payload round-trips so Pine treats it as fallback-only."""
    payload = _envelope_only().model_copy(update={"stale": True})
    flat = flatten_overlay(payload)
    assert flat["stale"] is True


def test_schema_requires_only_the_envelope() -> None:
    """Only the envelope is required; the overlay never forces a data field."""
    assert set(_schema()["required"]) == set(ENVELOPE_FIELDS)


@pytest.mark.parametrize("field", _OPTIONAL_FIELDS)
def test_schema_marks_overlay_field_nullable(field: str) -> None:
    """Every overlay field admits null so 'nothing fresher' is contract-legal."""
    props = _schema()["properties"]
    assert field in props, f"{field} missing from schema properties"
    types = props[field]["type"]
    assert isinstance(types, list) and "null" in types, (
        f"overlay field {field} must admit null (got type={types!r})"
    )
