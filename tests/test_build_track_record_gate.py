"""Tests for ``scripts.build_track_record_gate`` (C7 producer for the
``track_record_gate_<date>.json`` cache file).
"""

from __future__ import annotations

import json
from pathlib import Path

from scripts.build_track_record_gate import (
    build_track_record_gate_payload,
    main,
)


def test_global_returns_payload_emits_status_and_no_per_variant() -> None:
    payload = build_track_record_gate_payload({"returns": [0.01] * 50 + [-0.005] * 30})
    assert payload["status"] in {"green", "yellow", "red"}
    assert "per_variant" not in payload  # global-only shape


def test_per_variant_returns_payload_emits_per_variant_block() -> None:
    payload = build_track_record_gate_payload(
        {
            "returns_by_variant": {
                "smc_breaker_btc": [0.01] * 60 + [-0.005] * 40,
                "smc_fvg_eth": [0.005] * 30 + [-0.003] * 30,
            }
        }
    )
    assert payload["status"] in {"green", "yellow", "red"}
    pv = payload["per_variant"]
    assert set(pv.keys()) == {"smc_breaker_btc", "smc_fvg_eth"}
    for entry in pv.values():
        assert entry["status"] in {"green", "yellow", "red"}
        assert isinstance(entry["failures"], list)


def test_main_writes_atomic_file(tmp_path: Path) -> None:
    src = tmp_path / "returns.json"
    src.write_text(json.dumps({"returns": [0.01] * 50 + [-0.01] * 50}), encoding="utf-8")
    out = tmp_path / "out" / "track_record_gate.json"
    rc = main(["--returns", str(src), "--output", str(out)])
    assert rc == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["status"] in {"green", "yellow", "red"}
