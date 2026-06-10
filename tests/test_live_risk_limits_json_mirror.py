"""F8 — ``configs/live_risk_limits.json`` must mirror the ``RiskLimits``
dataclass defaults.

The runner (``scripts.run_smc_live_incubation``) loads the kill-switch
thresholds from the JSON file via ``RiskLimits.from_json`` for live phases.
If the JSON ever drifts from the dataclass defaults, an operator editing one
but not the other would silently change (or fail to change) the live
kill-switch.  These tests pin the two representations together and exercise
the loader's validation contract.
"""

from __future__ import annotations

import json
from dataclasses import fields
from pathlib import Path

import pytest

from scripts.live_risk_limits import RiskLimits

_CONFIG = Path(__file__).resolve().parents[1] / "configs" / "live_risk_limits.json"
_LIMIT_FIELDS = {f.name for f in fields(RiskLimits)}


def _config_blob() -> dict:
    return json.loads(_CONFIG.read_text(encoding="utf-8"))


def test_config_file_exists():
    assert _CONFIG.is_file(), f"missing kill-switch config: {_CONFIG}"


def test_json_values_match_dataclass_defaults():
    """Every limit in the JSON equals the corresponding dataclass default."""
    blob = _config_blob()
    defaults = RiskLimits()
    for name in _LIMIT_FIELDS:
        assert name in blob, f"config is missing limit {name!r}"
        assert blob[name] == getattr(defaults, name), (
            f"limit {name!r} drift: JSON={blob[name]!r} "
            f"dataclass-default={getattr(defaults, name)!r}"
        )


def test_json_has_no_unknown_limit_keys():
    """Only known limits + documented metadata keys may appear (typo guard)."""
    blob = _config_blob()
    metadata = RiskLimits._JSON_METADATA_KEYS
    unknown = {
        k for k in blob
        if k not in _LIMIT_FIELDS and k not in metadata and not k.startswith("_")
    }
    assert not unknown, f"config has unknown keys: {sorted(unknown)!r}"


def test_from_json_roundtrips_to_defaults():
    """Loading the canonical config yields the dataclass defaults."""
    assert RiskLimits.from_json(_CONFIG) == RiskLimits()


def test_from_json_rejects_unknown_key(tmp_path):
    bad = tmp_path / "bad.json"
    # A typo in a safety-critical limit must fail loud, not silently default.
    bad.write_text(json.dumps({"max_daily_loss_pc": 2.0}), encoding="utf-8")
    with pytest.raises(ValueError, match="unknown keys"):
        RiskLimits.from_json(bad)


def test_from_json_rejects_non_object(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps([1, 2, 3]), encoding="utf-8")
    with pytest.raises(ValueError, match="must be a JSON object"):
        RiskLimits.from_json(bad)


def test_from_json_partial_falls_back_to_defaults(tmp_path):
    """An omitted limit falls back to the dataclass default."""
    partial = tmp_path / "partial.json"
    partial.write_text(json.dumps({"max_open_positions": 3}), encoding="utf-8")
    loaded = RiskLimits.from_json(partial)
    assert loaded.max_open_positions == 3
    assert loaded.max_daily_loss_pct == RiskLimits().max_daily_loss_pct


def test_from_json_tolerates_metadata_keys(tmp_path):
    """Documented metadata keys do not trip the unknown-key guard."""
    cfg = tmp_path / "meta.json"
    cfg.write_text(
        json.dumps(
            {
                "_comment": "provenance",
                "frozen_at": "2026-04-28",
                "frozen_for": "C13",
                "max_open_positions": 5,
            }
        ),
        encoding="utf-8",
    )
    assert RiskLimits.from_json(cfg).max_open_positions == 5
