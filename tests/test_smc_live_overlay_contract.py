"""Contract tests for the ``smc-live-overlay/1`` flat live-overlay payload.

These tests are pure JSON-Schema + pydantic checks with no live FMP/Databento
dependency, so they run in CI without provider keys. They lock the wire shape
that authenticated ``GET /smc_live`` clients depend on. The former Pine bridge
is retired because Pine cannot call arbitrary REST endpoints.
"""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest
from pydantic import ValidationError

from smc_tv_bridge.contracts.live_overlay import (
    ENVELOPE_FIELDS,
    NEWS_BIAS_VALUES,
    SCHEMA_ID,
    SUPPORTED_TIMEFRAMES,
    LiveOverlayPayload,
    flatten_overlay,
)

_REPO = Path(__file__).resolve().parents[1]
_SCHEMA_PATH = _REPO / "spec" / "smc_live_overlay.schema.json"
_GOLDEN_PATH = _REPO / "smc_tv_bridge" / "contracts" / "golden_sample.json"


def _load_schema() -> dict:
    return json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))


def _load_golden() -> dict:
    return json.loads(_GOLDEN_PATH.read_text(encoding="utf-8"))


def test_schema_has_no_duplicate_object_keys() -> None:
    def reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    json.loads(
        _SCHEMA_PATH.read_text(encoding="utf-8"),
        object_pairs_hook=reject_duplicates,
    )


def test_schema_is_valid_draft_2020_12() -> None:
    schema = _load_schema()
    jsonschema.Draft202012Validator.check_schema(schema)
    assert schema["$id"].endswith("smc_live_overlay.schema.json")


def test_golden_sample_validates_against_schema() -> None:
    jsonschema.validate(instance=_load_golden(), schema=_load_schema())


def test_golden_sample_declares_contract_id() -> None:
    assert _load_golden()["schema"] == SCHEMA_ID


def test_model_round_trips_golden_sample() -> None:
    golden = _load_golden()
    payload = LiveOverlayPayload.model_validate(golden)
    assert flatten_overlay(payload) == golden


def test_flattened_payload_validates_against_schema() -> None:
    payload = LiveOverlayPayload.model_validate(_load_golden())
    jsonschema.validate(instance=flatten_overlay(payload), schema=_load_schema())


def test_runtime_library_and_canonical_flow_fields_match_strict_contract() -> None:
    instance = _load_golden() | {
        "universe_member": True,
        "universe_size": 6929,
        "library_asof_date": "2026-07-22",
        "library_asof_time": "2026-07-22T16:40:00Z",
        "provider_trust_status": "degraded",
        "provider_stale_list": "benzinga",
        "price_candle_body_return_pct": 0.25,
        "volume_accumulation_distribution_state": "accumulation",
        "volume_current_bar_zscore": 1.5,
    }

    jsonschema.validate(instance=instance, schema=_load_schema())
    assert flatten_overlay(LiveOverlayPayload.model_validate(instance)) == instance


def test_flatten_drops_null_data_fields() -> None:
    payload = LiveOverlayPayload(symbol="AAPL", tf="5m", asof_ts=0, stale=True)
    flat = flatten_overlay(payload)
    assert flat == {
        "schema": SCHEMA_ID,
        "symbol": "AAPL",
        "tf": "5m",
        "asof_ts": 0,
        "stale": True,
    }


def test_schema_required_matches_envelope_constant() -> None:
    assert set(_load_schema()["required"]) == set(ENVELOPE_FIELDS)


def test_model_exposes_every_envelope_field() -> None:
    model_keys = {
        (field.alias or name)
        for name, field in LiveOverlayPayload.model_fields.items()
    }
    assert set(ENVELOPE_FIELDS) <= model_keys


def test_supported_timeframes_match_schema() -> None:
    assert list(SUPPORTED_TIMEFRAMES) == _load_schema()["properties"]["tf"]["enum"]


def test_news_bias_constant_matches_schema() -> None:
    enum = [v for v in _load_schema()["properties"]["news_bias"]["enum"] if v is not None]
    assert list(NEWS_BIAS_VALUES) == enum


@pytest.mark.parametrize("missing", sorted(ENVELOPE_FIELDS))
def test_missing_envelope_field_rejected_by_schema(missing: str) -> None:
    instance = _load_golden()
    del instance[missing]
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=instance, schema=_load_schema())


@pytest.mark.parametrize("bad_tf", ["1D", "5M", ""])
def test_invalid_timeframe_rejected_by_schema(bad_tf: str) -> None:
    instance = _load_golden()
    instance["tf"] = bad_tf
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=instance, schema=_load_schema())


def test_unknown_field_rejected_by_schema() -> None:
    instance = _load_golden()
    instance["totally_new_field"] = 1.0
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=instance, schema=_load_schema())


def test_bad_news_bias_rejected_by_schema() -> None:
    instance = _load_golden()
    instance["news_bias"] = "SIDEWAYS"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=instance, schema=_load_schema())


def test_news_strength_out_of_bounds_rejected_by_schema() -> None:
    instance = _load_golden()
    instance["news_strength"] = 1.5
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=instance, schema=_load_schema())


def test_model_rejects_unknown_field() -> None:
    instance = _load_golden()
    instance["totally_new_field"] = 1.0
    with pytest.raises(ValidationError):
        LiveOverlayPayload.model_validate(instance)


def test_model_rejects_invalid_timeframe() -> None:
    instance = _load_golden()
    instance["tf"] = "1D"
    with pytest.raises(ValidationError):
        LiveOverlayPayload.model_validate(instance)


def test_model_rejects_wrong_schema_id() -> None:
    instance = _load_golden()
    instance["schema"] = "smc-live-overlay/2"
    with pytest.raises(ValidationError):
        LiveOverlayPayload.model_validate(instance)


def test_stale_flag_is_boolean_in_model() -> None:
    payload = LiveOverlayPayload.model_validate(_load_golden())
    assert isinstance(payload.stale, bool)
