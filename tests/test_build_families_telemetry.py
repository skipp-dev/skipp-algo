"""Tests for scripts.build_families_telemetry (C13/T5)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.build_families_telemetry import (
    EVENT_FAMILIES,
    FAMILIES_SCHEMA_VERSION,
    BuildSummary,
    aggregate,
    build_payload,
    load_variant_family_map,
    main,
    rollup_verdict,
    to_strict_payload,
)

# ---------------------------------------------------------------------------
# Pinning: schema + family list mirror the consumer contract
# ---------------------------------------------------------------------------


def test_event_families_match_smc_core_scoring() -> None:
    # Mirrors smc_core/scoring.py:33 EventFamily literal.
    assert EVENT_FAMILIES == ("BOS", "OB", "FVG", "SWEEP")


def test_schema_version_pinned() -> None:
    assert FAMILIES_SCHEMA_VERSION == "1.0.0"


def test_strict_payload_keys_match_consumer_contract() -> None:
    # Mirrors scripts/emit_public_calibration_report.py:182
    # _C12_FAMILY_KEYS — keep the producer in lockstep.
    from scripts.emit_public_calibration_report import _C12_FAMILY_KEYS

    payload = to_strict_payload({})
    for fam in payload:
        assert set(_C12_FAMILY_KEYS).issubset(fam.keys())


# ---------------------------------------------------------------------------
# rollup_verdict — worst-case ordering
# ---------------------------------------------------------------------------


def test_rollup_verdict_picks_worst_case() -> None:
    assert rollup_verdict([]) == "unknown"
    assert rollup_verdict(["pass", "pass"]) == "pass"
    assert rollup_verdict(["pass", "acceptable"]) == "acceptable"
    assert rollup_verdict(["pass", "concerning", "acceptable"]) == "concerning"
    assert rollup_verdict(["pass", "fail"]) == "fail"
    assert rollup_verdict(["acceptable", "insufficient_sample"]) == "insufficient_sample"


# ---------------------------------------------------------------------------
# load_variant_family_map — strict validation
# ---------------------------------------------------------------------------


def test_load_variant_family_map_happy_path(tmp_path: Path) -> None:
    p = tmp_path / "vmap.json"
    p.write_text(json.dumps({"v_bos_1": "BOS", "v_ob_1": "OB"}))
    m = load_variant_family_map(p)
    assert m == {"v_bos_1": "BOS", "v_ob_1": "OB"}


def test_load_variant_family_map_rejects_unknown_family(tmp_path: Path) -> None:
    p = tmp_path / "vmap.json"
    p.write_text(json.dumps({"v": "FOOBAR"}))
    with pytest.raises(ValueError, match="unknown family"):
        load_variant_family_map(p)


def test_load_variant_family_map_rejects_non_object(tmp_path: Path) -> None:
    p = tmp_path / "vmap.json"
    p.write_text("[]")
    with pytest.raises(ValueError):
        load_variant_family_map(p)


# ---------------------------------------------------------------------------
# aggregate — audit + drift → accumulators
# ---------------------------------------------------------------------------


def _write_audit(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for r in records:
            fh.write(json.dumps(r) + "\n")


def _write_drift(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_aggregate_counts_trades_and_live_days(tmp_path: Path) -> None:
    a1 = tmp_path / "incubation_2026-04-25.jsonl"
    _write_audit(a1, [
        {"variant": "v_bos_1", "action": "closed"},
        {"variant": "v_bos_1", "action": "flattened"},
        {"variant": "v_ob_1", "action": "tp_hit"},
        # Non-terminal actions must NOT contribute to n_trades —
        # ``filled`` is the *entry* fill, not a closed trade.
        {"variant": "v_bos_1", "action": "filled"},
        {"variant": "v_bos_1", "action": "audit_only"},
        {"variant": "v_bos_1", "action": "created"},
    ])
    a2 = tmp_path / "incubation_2026-04-26.jsonl"
    _write_audit(a2, [
        {"variant": "v_bos_1", "action": "stop_hit"},
    ])

    vmap = {"v_bos_1": "BOS", "v_ob_1": "OB"}
    summary = BuildSummary()
    accs = aggregate(
        audit_paths=[a1, a2],
        drift_paths=[],
        variant_to_family=vmap,
        summary=summary,
    )
    assert summary.audit_files == 2
    assert summary.audit_records_total == 7
    assert accs["BOS"].n_trades == 3
    assert accs["BOS"].trade_days == {"2026-04-25", "2026-04-26"}
    assert accs["OB"].n_trades == 1
    assert accs["OB"].trade_days == {"2026-04-25"}


def test_aggregate_counts_outcome_pnl_as_closed_trade(tmp_path: Path) -> None:
    """Records carrying ``outcome_pnl_usd`` (post-backfill) must count."""
    a1 = tmp_path / "incubation_2026-04-25.jsonl"
    _write_audit(a1, [
        {"variant": "v_bos_1", "action": "audit_only", "outcome_pnl_usd": 12.5},
        {"variant": "v_bos_1", "action": "audit_only"},  # not closed
    ])
    summary = BuildSummary()
    accs = aggregate(
        audit_paths=[a1],
        drift_paths=[],
        variant_to_family={"v_bos_1": "BOS"},
        summary=summary,
    )
    assert accs["BOS"].n_trades == 1


def test_aggregate_counts_unknown_variants(tmp_path: Path) -> None:
    a1 = tmp_path / "incubation_2026-04-25.jsonl"
    _write_audit(a1, [
        {"variant": "v_bos_1", "action": "closed"},
        {"variant": "mystery", "action": "closed"},
    ])
    summary = BuildSummary()
    accs = aggregate(
        audit_paths=[a1],
        drift_paths=[],
        variant_to_family={"v_bos_1": "BOS"},
        summary=summary,
    )
    assert summary.audit_records_with_unknown_variant == 1
    assert "mystery" in summary.unknown_variants
    assert accs["BOS"].n_trades == 1


def test_aggregate_rolls_up_drift_verdicts(tmp_path: Path) -> None:
    d1 = tmp_path / "drift_2026-04-25.json"
    _write_drift(d1, {
        "variants": [
            {"variant": "v_bos_1", "verdict": "pass"},
            {"variant": "v_bos_2", "verdict": "concerning"},
            {"variant": "v_ob_1", "verdict": "acceptable"},
        ]
    })
    summary = BuildSummary()
    accs = aggregate(
        audit_paths=[],
        drift_paths=[d1],
        variant_to_family={
            "v_bos_1": "BOS", "v_bos_2": "BOS", "v_ob_1": "OB",
        },
        summary=summary,
    )
    assert rollup_verdict(accs["BOS"].drift_verdicts) == "concerning"
    assert rollup_verdict(accs["OB"].drift_verdicts) == "acceptable"


# ---------------------------------------------------------------------------
# to_strict_payload — emits zero-rows for unseen families
# ---------------------------------------------------------------------------


def test_to_strict_payload_emits_zero_rows_for_unseen_families() -> None:
    payload = to_strict_payload({})
    names = [f["name"] for f in payload]
    assert names == list(EVENT_FAMILIES)
    for f in payload:
        assert f["live_days"] == 0
        assert f["n_trades"] == 0
        assert f["kill_switch_fires"] == 0
        assert f["drift_verdict"] == "unknown"


# ---------------------------------------------------------------------------
# build_payload — end-to-end via globs + map
# ---------------------------------------------------------------------------


def test_build_payload_end_to_end(tmp_path: Path) -> None:
    a = tmp_path / "incubation_2026-04-25.jsonl"
    _write_audit(a, [
        {"variant": "v_bos_1", "action": "closed"},
    ])
    d = tmp_path / "drift_2026-04-25.json"
    _write_drift(d, {"variants": [{"variant": "v_bos_1", "verdict": "pass"}]})
    vmap = tmp_path / "vmap.json"
    vmap.write_text(json.dumps({"v_bos_1": "BOS"}))

    out = build_payload(
        audit_glob=str(tmp_path / "incubation_*.jsonl"),
        drift_glob=str(tmp_path / "drift_*.json"),
        variant_family_map=vmap,
    )
    assert out["schema_version"] == FAMILIES_SCHEMA_VERSION
    bos = next(f for f in out["families"] if f["name"] == "BOS")
    assert bos["n_trades"] == 1
    assert bos["live_days"] == 1
    assert bos["drift_verdict"] == "pass"
    # Untraded families still emitted as zero rows.
    ob = next(f for f in out["families"] if f["name"] == "OB")
    assert ob["n_trades"] == 0


# ---------------------------------------------------------------------------
# CLI happy path — writes output JSON + exit 0
# ---------------------------------------------------------------------------


def test_cli_writes_output_and_returns_zero(tmp_path: Path) -> None:
    a = tmp_path / "incubation_2026-04-25.jsonl"
    _write_audit(a, [{"variant": "v_bos_1", "action": "closed"}])
    d = tmp_path / "drift_2026-04-25.json"
    _write_drift(d, {"variants": [{"variant": "v_bos_1", "verdict": "pass"}]})
    vmap = tmp_path / "vmap.json"
    vmap.write_text(json.dumps({"v_bos_1": "BOS"}))
    out = tmp_path / "out.json"

    rc = main([
        "--audit-jsonl", str(tmp_path / "incubation_*.jsonl"),
        "--drift-jsonl", str(tmp_path / "drift_*.json"),
        "--variant-family-map", str(vmap),
        "--output", str(out),
    ])
    assert rc == 0
    payload = json.loads(out.read_text())
    assert payload["schema_version"] == FAMILIES_SCHEMA_VERSION
    assert any(f["name"] == "BOS" for f in payload["families"])


def test_cli_strict_mode_returns_two_on_unknown_variant(tmp_path: Path) -> None:
    a = tmp_path / "incubation_2026-04-25.jsonl"
    _write_audit(a, [{"variant": "rogue", "action": "closed"}])
    vmap = tmp_path / "vmap.json"
    vmap.write_text(json.dumps({"v_bos_1": "BOS"}))
    out = tmp_path / "out.json"

    rc = main([
        "--audit-jsonl", str(tmp_path / "incubation_*.jsonl"),
        "--drift-jsonl", str(tmp_path / "drift_*.json"),
        "--variant-family-map", str(vmap),
        "--output", str(out),
        "--strict-unknown-variants",
    ])
    assert rc == 2
