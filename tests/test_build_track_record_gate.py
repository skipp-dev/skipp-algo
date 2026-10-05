"""Tests for ``scripts.build_track_record_gate`` (C7 producer for the
``track_record_gate_<date>.json`` cache file).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.build_track_record_gate import (
    build_track_record_gate_payload,
    main,
)

_DAY = 86_400.0
_FIRST_DAY = 1_788_220_800.0  # 2026-09-01T00:00:00Z


def _checks(verdict: dict) -> dict[str, dict]:
    return {check["name"]: check for check in verdict["checks"]}


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


def test_explicit_null_rr_target_does_not_crash() -> None:
    """Regression for PR #286 review: cron retries must survive a JSON
    payload that explicitly carries ``"rr_target": null``."""
    payload = build_track_record_gate_payload(
        {"returns": [0.01] * 50 + [-0.005] * 30, "rr_target": None}
    )
    assert payload["status"] in {"green", "yellow", "red"}


def test_wrong_typed_per_variant_scalars_are_dropped() -> None:
    """Regression for PR #286 review: a list/string posing as a
    per-variant scalar must not be passed through as truthy garbage."""
    payload = build_track_record_gate_payload(
        {
            "returns_by_variant": {
                "smc_breaker_btc": [0.01] * 60 + [-0.005] * 40,
            },
            # Wrong shape — must be silently dropped (no crash).
            "walk_forward_efficiency_by_variant": [0.7],
            "permutation_p_by_variant": "0.05",
        }
    )
    assert payload["status"] in {"green", "yellow", "red"}
    assert "smc_breaker_btc" in payload["per_variant"]


# ---------------------------------------------------------------------------
# Day checks (ADR-0031, Nachtrag 2026-10-02): anchors travel with the returns
# ---------------------------------------------------------------------------


def _two_family_series() -> dict:
    """BOS on days 0-2, OB on days 2-5: three and four days, six in total."""
    bos = [0.01, -0.004, 0.006] * 20
    ob = [0.008, -0.003, 0.004, 0.002] * 10
    return {
        "returns_by_variant": {"BOS": bos, "OB": ob},
        "anchor_ts_by_variant": {
            "BOS": [_FIRST_DAY + (i % 3) * _DAY for i in range(len(bos))],
            "OB": [_FIRST_DAY + (2 + i % 4) * _DAY for i in range(len(ob))],
        },
    }


def test_anchors_reach_every_family_and_the_pooled_verdict() -> None:
    payload = build_track_record_gate_payload(_two_family_series())
    assert _checks(payload["per_variant"]["BOS"])["trading_days"]["value"] == 3.0
    assert _checks(payload["per_variant"]["OB"])["trading_days"]["value"] == 4.0
    # Pooled: the UNION of days. Day 2 carries both families and counts once.
    assert _checks(payload)["trading_days"]["value"] == 6.0
    assert payload["summary"]["day_clustered"]["n_days"] == 6
    assert payload["status"] == "red"


def test_a_series_without_anchors_still_grades_and_skips_the_day_checks() -> None:
    series = _two_family_series()
    del series["anchor_ts_by_variant"]
    payload = build_track_record_gate_payload(series)
    verdicts = [payload, *payload["per_variant"].values()]
    assert len(verdicts) == 3
    for verdict in verdicts:
        assert _checks(verdict)["trading_days"]["status"] == "skipped"
        assert verdict["claimable"] is False


@pytest.mark.parametrize(
    ("anchors", "message"),
    [
        ({"BOS": [_FIRST_DAY] * 60}, "'OB'"),
        ({"BOS": [_FIRST_DAY] * 60, "OB": [_FIRST_DAY] * 39}, "expected 40"),
        ({"BOS": [_FIRST_DAY] * 60, "OB": "n/a"}, "no list"),
        ([[_FIRST_DAY]], "must map family"),
    ],
)
def test_a_partial_or_misshapen_anchor_block_is_refused(anchors, message: str) -> None:
    """Anchors for some families only would leave the others with skipped
    day checks and no trace of why — refuse the whole series instead."""
    series = _two_family_series()
    series["anchor_ts_by_variant"] = anchors
    with pytest.raises(ValueError, match=message):
        build_track_record_gate_payload(series)
