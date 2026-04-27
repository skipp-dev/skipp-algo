"""Tests for ``scripts.build_phase_a_inputs`` (C13 / Phase-A pre-open producer).

Covers the seed contract (no upstream data available), the happy-path
(setups + per-variant returns supplied), validation errors, and
idempotency.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.build_phase_a_inputs import (
    SCHEMA_VERSION,
    _build_gate_status,
    _normalise_gate_status,
    _validate_setup_record,
    main,
)

# --------------------------------------------------------------------------- #
# Helpers                                                                     #
# --------------------------------------------------------------------------- #


def _setup(**overrides) -> dict:
    base = {
        "symbol": "BTC",
        "entry": 102.34,
        "stop_loss": 100.50,
        "take_profit": 105.20,
        "quantity": 100,
        "trade_date": "2026-04-27",
        "variant": "smc_breaker_btc",
    }
    base.update(overrides)
    return base


# --------------------------------------------------------------------------- #
# _normalise_gate_status                                                      #
# --------------------------------------------------------------------------- #


def test_yellow_is_remapped_to_amber() -> None:
    # The gate emits "yellow"; the runner expects "amber" — same vocab
    # mapping the dashboard performs.
    assert _normalise_gate_status("yellow") == "amber"


def test_unknown_status_falls_back_to_skipped() -> None:
    # Defensive: any future status the gate adds must NOT silently
    # become tradable.
    assert _normalise_gate_status("turquoise") == "skipped"


def test_status_normalisation_is_case_insensitive() -> None:
    assert _normalise_gate_status("GREEN") == "green"
    assert _normalise_gate_status("  Amber  ") == "amber"


# --------------------------------------------------------------------------- #
# _validate_setup_record                                                      #
# --------------------------------------------------------------------------- #


def test_validate_setup_rejects_missing_variant() -> None:
    # The Phase-A runner filters by variant gate-status; a setup without
    # ``variant`` is silently dropped by ``_filter_tradable_setups``,
    # which is far worse than raising at producer-time.
    record = _setup()
    record.pop("variant")
    with pytest.raises(ValueError, match="variant"):
        _validate_setup_record(record, idx=0)


def test_validate_setup_rejects_non_object() -> None:
    with pytest.raises(ValueError, match="JSON object"):
        _validate_setup_record(["not", "an", "object"], idx=0)


# --------------------------------------------------------------------------- #
# _build_gate_status                                                          #
# --------------------------------------------------------------------------- #


def test_build_gate_status_seed_marks_every_known_variant_skipped() -> None:
    # No returns payload + a list of expected variants → every variant
    # is "skipped" so the runner rejects all setups (Phase-A safe-default).
    out = _build_gate_status(
        returns_payload=None,
        known_variants=["smc_breaker_btc", "smc_fvg_eth"],
    )
    assert out == {
        "smc_breaker_btc": "skipped",
        "smc_fvg_eth": "skipped",
    }


def test_build_gate_status_unions_known_and_returns_keys() -> None:
    # Variants that appear in ``known_variants`` but not in ``returns``
    # must still surface as "skipped" — never silently dropped.
    payload = {
        "returns_by_variant": {
            "smc_breaker_btc": [0.01] * 60 + [-0.005] * 40,
        }
    }
    out = _build_gate_status(
        returns_payload=payload,
        known_variants=["smc_breaker_btc", "smc_fvg_eth"],
    )
    assert set(out.keys()) == {"smc_breaker_btc", "smc_fvg_eth"}
    assert out["smc_fvg_eth"] == "skipped"
    assert out["smc_breaker_btc"] in {"green", "amber", "red"}


def test_build_gate_status_drops_non_numeric_returns() -> None:
    # Garbage in the returns list must not crash the producer (the
    # cron must keep running daily even if upstream emits a typo).
    payload = {
        "returns_by_variant": {
            "smc_breaker_btc": [0.01, "oops", None, 0.02] * 30,
        }
    }
    out = _build_gate_status(returns_payload=payload, known_variants=[])
    assert "smc_breaker_btc" in out
    assert out["smc_breaker_btc"] != "skipped"


# --------------------------------------------------------------------------- #
# main() — end-to-end CLI                                                     #
# --------------------------------------------------------------------------- #


def test_main_seed_mode_writes_empty_setups_and_skipped_gate(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = main(
        [
            "--trade-date",
            "2026-04-27",
            "--output-dir",
            str(tmp_path),
            "--known-variants",
            "smc_breaker_btc,smc_fvg_eth",
        ]
    )
    assert rc == 0

    setups = tmp_path / "setups_2026-04-27.jsonl"
    meta = tmp_path / "setups_2026-04-27.meta.json"
    gate = tmp_path / "gate_status_2026-04-27.json"

    assert setups.exists()
    assert setups.read_text(encoding="utf-8") == ""

    meta_payload = json.loads(meta.read_text(encoding="utf-8"))
    assert meta_payload["schema_version"] == SCHEMA_VERSION
    assert meta_payload["phase_a_seed"] is True
    assert meta_payload["n_setups"] == 0

    gate_payload = json.loads(gate.read_text(encoding="utf-8"))
    assert gate_payload == {
        "smc_breaker_btc": "skipped",
        "smc_fvg_eth": "skipped",
    }

    stdout = capsys.readouterr().out
    parsed = json.loads(stdout.strip())
    assert parsed["tradable_variants"] == []
    assert parsed["phase_a_seed"] is True


def test_main_with_setups_source_writes_jsonl_one_per_line(tmp_path: Path) -> None:
    src = tmp_path / "src.json"
    src.write_text(
        json.dumps(
            [
                _setup(symbol="BTC", variant="smc_breaker_btc"),
                _setup(symbol="ETH", variant="smc_fvg_eth"),
            ]
        ),
        encoding="utf-8",
    )
    rc = main(
        [
            "--trade-date",
            "2026-04-27",
            "--output-dir",
            str(tmp_path),
            "--setups-source",
            str(src),
        ]
    )
    assert rc == 0
    setups = tmp_path / "setups_2026-04-27.jsonl"
    lines = [line for line in setups.read_text(encoding="utf-8").splitlines() if line]
    assert len(lines) == 2
    parsed = [json.loads(line) for line in lines]
    assert {r["symbol"] for r in parsed} == {"BTC", "ETH"}
    # trade_date is stamped from the CLI arg, not from the source record.
    assert all(r["trade_date"] == "2026-04-27" for r in parsed)

    meta = json.loads((tmp_path / "setups_2026-04-27.meta.json").read_text(encoding="utf-8"))
    assert meta["phase_a_seed"] is False
    assert meta["n_setups"] == 2


def test_main_with_returns_emits_real_gate_verdicts(tmp_path: Path) -> None:
    returns_path = tmp_path / "returns.json"
    returns_path.write_text(
        json.dumps(
            {
                "returns_by_variant": {
                    "smc_breaker_btc": [0.01] * 60 + [-0.005] * 40,
                    "smc_fvg_eth": [-0.02] * 50 + [-0.01] * 50,
                }
            }
        ),
        encoding="utf-8",
    )
    rc = main(
        [
            "--trade-date",
            "2026-04-27",
            "--output-dir",
            str(tmp_path),
            "--returns",
            str(returns_path),
        ]
    )
    assert rc == 0
    gate = json.loads((tmp_path / "gate_status_2026-04-27.json").read_text(encoding="utf-8"))
    assert set(gate.keys()) == {"smc_breaker_btc", "smc_fvg_eth"}
    for status in gate.values():
        assert status in {"green", "amber", "red", "skipped"}


def test_main_is_idempotent_overwrites_prior_outputs(tmp_path: Path) -> None:
    # First run: seed mode.
    main(
        [
            "--trade-date",
            "2026-04-27",
            "--output-dir",
            str(tmp_path),
            "--known-variants",
            "v1",
        ]
    )
    gate_path = tmp_path / "gate_status_2026-04-27.json"
    assert json.loads(gate_path.read_text(encoding="utf-8")) == {"v1": "skipped"}

    # Second run with different known-variants: file is fully replaced,
    # no leftover keys from the first run.
    main(
        [
            "--trade-date",
            "2026-04-27",
            "--output-dir",
            str(tmp_path),
            "--known-variants",
            "v2,v3",
        ]
    )
    assert json.loads(gate_path.read_text(encoding="utf-8")) == {
        "v2": "skipped",
        "v3": "skipped",
    }


def test_main_rejects_malformed_setup_record_with_helpful_message(
    tmp_path: Path,
) -> None:
    src = tmp_path / "src.json"
    bad = _setup()
    bad.pop("stop_loss")
    src.write_text(json.dumps([bad]), encoding="utf-8")
    with pytest.raises(ValueError, match="stop_loss"):
        main(
            [
                "--trade-date",
                "2026-04-27",
                "--output-dir",
                str(tmp_path),
                "--setups-source",
                str(src),
            ]
        )
