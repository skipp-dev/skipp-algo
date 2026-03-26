from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import jsonschema

from scripts.export_smc_snapshot_bundle import export_snapshot_bundle
from smc_integration.service import build_snapshot_bundle_for_symbol_timeframe

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "spec" / "smc_snapshot.schema.json"


def _load_schema() -> dict:
    return cast(dict, json.loads(SCHEMA_PATH.read_text(encoding="utf-8")))


def test_build_snapshot_bundle_contains_expected_root_keys() -> None:
    bundle = build_snapshot_bundle_for_symbol_timeframe("IBG", "15m", generated_at=1709253600.0)

    assert set(["source", "snapshot", "dashboard_payload", "pine_payload"]).issubset(set(bundle.keys()))



def test_bundle_snapshot_is_schema_compatible() -> None:
    bundle = build_snapshot_bundle_for_symbol_timeframe("IBG", "15m", generated_at=1709253600.0)
    jsonschema.validate(instance=bundle["snapshot"], schema=_load_schema())



def test_bundle_is_deterministic_for_fixed_generated_at() -> None:
    one = build_snapshot_bundle_for_symbol_timeframe("IBG", "15m", generated_at=1709253600.0)
    two = build_snapshot_bundle_for_symbol_timeframe("IBG", "15m", generated_at=1709253600.0)
    assert one == two



def test_export_script_writes_json_file(tmp_path: Path) -> None:
    out = tmp_path / "bundle.json"
    written = export_snapshot_bundle(symbol="IBG", timeframe="15m", source="auto", output=out)

    assert written == out
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["snapshot"]["symbol"] == "IBG"



def test_export_script_uses_service_bundle_function(monkeypatch, tmp_path: Path) -> None:
    from scripts import export_smc_snapshot_bundle as module

    calls: list[tuple[str, str, str]] = []

    def _fake_bundle(symbol: str, timeframe: str, *, source: str = "auto", generated_at: float | None = None) -> dict:
        del generated_at
        calls.append((symbol, timeframe, source))
        return {
            "source": {"name": source, "path_hint": "fake", "capabilities": {}, "notes": []},
            "snapshot": {"symbol": symbol, "timeframe": timeframe},
            "dashboard_payload": {},
            "pine_payload": {},
        }

    monkeypatch.setattr(module, "build_snapshot_bundle_for_symbol_timeframe", _fake_bundle)

    out = tmp_path / "bundle.json"
    module.export_snapshot_bundle(symbol="AAA", timeframe="5m", source="auto", output=out)

    assert calls == [("AAA", "5m", "auto")]
    assert out.exists()
