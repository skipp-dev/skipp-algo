"""Tests for ``scripts/build_backtest_slippage_samples.py`` (C13/T4)."""
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from scripts import build_backtest_slippage_samples as mod

# ---------------------------------------------------------------------------
# Real-fills extraction
# ---------------------------------------------------------------------------


def test_extract_real_fills_buy_long_positive_slippage() -> None:
    audit = [
        {
            "variant": "BOS_megacap",
            "action": "buy",
            "entry_price": 100.0,
            "fill_price": 100.05,  # paid 5 bps more
        },
    ]
    out = mod.extract_real_fills_from_audit(audit)
    assert pytest.approx(out["BOS"], rel=1e-9) == [5.0]
    assert out["OB"] == [] and out["FVG"] == [] and out["SWEEP"] == []


def test_extract_real_fills_short_inverts_sign() -> None:
    audit = [
        {
            "variant": "OB_largecap",
            "action": "sell_short",
            "entry_price": 200.0,
            "fill_price": 199.80,  # received 10 bps less ⇒ unfavourable on short
        },
    ]
    out = mod.extract_real_fills_from_audit(audit)
    # raw = (199.8-200)/200*1e4 = -10; short flips ⇒ +10 bps
    assert pytest.approx(out["OB"], rel=1e-9) == [10.0]


def test_extract_real_fills_skips_missing_fill() -> None:
    audit = [
        {"variant": "FVG_smallcap", "entry_price": 50.0},  # no fill_price
        {"variant": "FVG_smallcap", "entry_price": 50.0, "fill_price": 50.10},
    ]
    out = mod.extract_real_fills_from_audit(audit)
    assert len(out["FVG"]) == 1


def test_extract_real_fills_skips_unknown_family() -> None:
    audit = [
        {
            "variant": "UNKNOWN_xxx",
            "action": "buy",
            "entry_price": 10.0,
            "fill_price": 10.01,
        },
    ]
    out = mod.extract_real_fills_from_audit(audit)
    assert all(v == [] for v in out.values())


def test_extract_real_fills_skips_zero_or_negative_entry() -> None:
    audit = [
        {
            "variant": "SWEEP_megacap",
            "action": "buy",
            "entry_price": 0.0,
            "fill_price": 1.0,
        },
        {
            "variant": "SWEEP_megacap",
            "action": "buy",
            "entry_price": -5.0,
            "fill_price": 1.0,
        },
    ]
    out = mod.extract_real_fills_from_audit(audit)
    assert out["SWEEP"] == []


# ---------------------------------------------------------------------------
# Replay determinism
# ---------------------------------------------------------------------------


def test_replay_family_is_deterministic_per_family() -> None:
    a1 = mod.replay_family("BOS", n=20)
    a2 = mod.replay_family("BOS", n=20)
    assert a1 == a2


def test_replay_family_differs_across_families() -> None:
    bos = mod.replay_family("BOS", n=50)
    ob = mod.replay_family("OB", n=50)
    assert bos != ob


def test_replay_family_uses_seed_samples_for_fit() -> None:
    seeded = mod.replay_family("FVG", n=200, seed_samples=[100.0] * 50)
    # Mean of seed is 100 → replay mean should pull strongly toward 100.
    assert sum(seeded) / len(seeded) > 50.0


# ---------------------------------------------------------------------------
# Top-level builder
# ---------------------------------------------------------------------------


def test_build_payload_real_fills_only() -> None:
    real = {"BOS": [1.0, 2.0, 3.0], "OB": [], "FVG": [], "SWEEP": []}
    payload = mod.build_payload(
        real_fills_by_family=real,
        mode="real_fills",
        now=datetime(2026, 4, 28, tzinfo=UTC),
    )
    assert payload["schema_version"] == mod.SCHEMA_VERSION
    assert payload["families"]["BOS"]["n"] == 3
    assert payload["families"]["BOS"]["source"] == "real_fills"
    assert payload["families"]["OB"]["n"] == 0


def test_build_payload_replay_floors_to_min_per_family() -> None:
    payload = mod.build_payload(
        real_fills_by_family=None,
        mode="replay",
        min_per_family=50,
    )
    for fam in mod.FAMILIES:
        assert payload["families"][fam]["n"] == 50
        assert payload["families"][fam]["source"] == "replay"


def test_build_payload_mixed_tops_up_short_families() -> None:
    real = {"BOS": [1.0] * 10, "OB": [], "FVG": [], "SWEEP": []}
    payload = mod.build_payload(
        real_fills_by_family=real, mode="mixed", min_per_family=20
    )
    assert payload["families"]["BOS"]["n"] == 20  # 10 real + 10 replay
    assert payload["families"]["BOS"]["source"] == "mixed"
    assert payload["families"]["OB"]["n"] == 20
    assert payload["families"]["OB"]["source"] == "replay"


def test_build_payload_rejects_unknown_mode() -> None:
    with pytest.raises(ValueError, match="unknown mode"):
        mod.build_payload(mode="bogus")


def test_build_payload_top_level_source_collapses_when_uniform() -> None:
    real = {f: [1.0] * 50 for f in mod.FAMILIES}
    payload = mod.build_payload(
        real_fills_by_family=real, mode="mixed", min_per_family=10
    )
    # All families had enough real → no replay top-up → uniform "real_fills".
    assert payload["source"] == "real_fills"


# ---------------------------------------------------------------------------
# Variant broadcasting
# ---------------------------------------------------------------------------


def test_expand_to_variant_samples_broadcasts_per_family() -> None:
    payload = {
        "families": {
            "BOS": {"slippage_bps": [1.0, 2.0], "n": 2, "source": "real_fills"},
            "OB": {"slippage_bps": [], "n": 0, "source": "real_fills"},
        }
    }
    out = mod.expand_to_variant_samples(
        payload, ["BOS_megacap", "BOS_largecap", "OB_megacap", "FVG_xxx"]
    )
    assert out["BOS_megacap"] == [1.0, 2.0]
    assert out["BOS_largecap"] == [1.0, 2.0]
    # OB has empty slippage_bps → variant is omitted (no ref to inject).
    assert "OB_megacap" not in out
    # FVG is missing entirely from payload → variant is omitted.
    assert "FVG_xxx" not in out


# ---------------------------------------------------------------------------
# CLI smoke
# ---------------------------------------------------------------------------


def test_cli_replay_writes_artifact(tmp_path: Path) -> None:
    out_path = tmp_path / "samples.json"
    rc = mod.main(
        [
            "--source",
            "replay",
            "--min-per-family",
            "30",
            "--output",
            str(out_path),
        ]
    )
    assert rc == 0
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert set(payload["families"].keys()) == set(mod.FAMILIES)
    for fam in mod.FAMILIES:
        assert payload["families"][fam]["n"] == 30


def test_cli_real_fills_from_audit_glob(tmp_path: Path) -> None:
    audit = tmp_path / "audit_2026-04-28.jsonl"
    audit.write_text(
        "\n".join(
            json.dumps(r)
            for r in [
                {
                    "variant": "BOS_megacap",
                    "action": "buy",
                    "entry_price": 100.0,
                    "fill_price": 100.10,
                },
                {
                    "variant": "OB_largecap",
                    "action": "buy",
                    "entry_price": 50.0,
                    "fill_price": 50.05,
                },
            ]
        ),
        encoding="utf-8",
    )
    out_path = tmp_path / "samples.json"
    rc = mod.main(
        [
            "--source",
            "real_fills",
            "--audit-glob",
            str(tmp_path / "audit_*.jsonl"),
            "--output",
            str(out_path),
        ]
    )
    assert rc == 0
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert payload["families"]["BOS"]["n"] == 1
    assert payload["families"]["OB"]["n"] == 1
    assert payload["families"]["FVG"]["n"] == 0
