"""Tests for ``scripts.emit_public_calibration_report`` (Q3/Q4 §3.1.1)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from scripts.emit_public_calibration_report import (
    HISTORY_RETENTION,
    PUBLIC_SCHEMA_VERSION,
    _extract_calibration_metrics,
    _extract_n_events,
    _extract_weighted_hit_rate,
    _find_latest_calibration_artifact,
    append_public_history,
    build_public_report,
    main,
    write_report,
)

# ── Pure helpers ──────────────────────────────────────────────────


def test_extract_metrics_from_testable_block() -> None:
    payload = {
        "testable_calibration": {
            "n_events": 10025,
            "ece_binned_n10": 0.1332,
            "smooth_ece": 0.1349,
            "dce_upper_bound": 0.1260,
            "positive_rate": 0.612,
        },
    }
    metrics = _extract_calibration_metrics(payload)
    assert metrics["ece"] == 0.1332
    assert metrics["smooth_ece"] == 0.1349
    assert metrics["dce"] == 0.1260
    assert metrics["positive_rate"] == 0.612


def test_extract_metrics_falls_back_to_top_level() -> None:
    payload = {"brier_score": 0.21, "ece": 0.18}
    metrics = _extract_calibration_metrics(payload)
    assert metrics["brier"] == 0.21
    assert metrics["ece"] == 0.18


def test_extract_metrics_drops_invalid() -> None:
    payload = {"testable_calibration": {"smooth_ece": "not-a-number", "ece_binned_n10": None}}
    assert _extract_calibration_metrics(payload) == {}


def test_extract_n_events_prefers_testable() -> None:
    payload = {
        "testable_calibration": {"n_events": 999},
        "family_stats": {"OB": {"total_events": 500}, "FVG": {"total_events": 250}},
    }
    assert _extract_n_events(payload) == 999


def test_extract_n_events_falls_back_to_family_stats() -> None:
    payload = {
        "family_stats": {"OB": {"total_events": 500}, "FVG": {"total_events": 250}},
    }
    assert _extract_n_events(payload) == 750


def test_extract_n_events_handles_empty() -> None:
    assert _extract_n_events({}) is None


def test_extract_weighted_hit_rate_matches_history_formula() -> None:
    payload = {
        "family_stats": {
            "OB": {"total_events": 100, "total_hits": 85},
            "FVG": {"total_events": 200, "total_hits": 120},
            "BOS": {"total_events": 0, "total_hits": 0},  # skipped
        },
    }
    hr = _extract_weighted_hit_rate(payload)
    # (85 + 120) / (100 + 200) = 205/300
    assert hr == round(205 / 300, 6)


def test_extract_weighted_hit_rate_handles_empty() -> None:
    assert _extract_weighted_hit_rate({}) is None


# ── build_public_report ───────────────────────────────────────────


def test_build_public_report_awaiting_first_run_when_payload_none() -> None:
    report = build_public_report(
        None,
        source_path=None,
        source_commit_sha="abc1234",
        source_workflow_run="42",
    )
    assert report["status"] == "awaiting_first_run"
    assert report["schema_version"] == PUBLIC_SCHEMA_VERSION
    assert report["source"]["commit_sha"] == "abc1234"
    assert "n_events" not in report  # no metrics on placeholder


def test_build_public_report_full_payload() -> None:
    payload = {
        "family_weights": {"OB": 0.85, "FVG": 0.61, "BOS": 0.81, "SWEEP": 0.73},
        "family_stats": {
            "OB": {"total_events": 200, "total_hits": 170},
            "FVG": {"total_events": 100, "total_hits": 60},
        },
        "testable_calibration": {
            "n_events": 300,
            "ece_binned_n10": 0.12,
            "smooth_ece": 0.115,
        },
    }
    report = build_public_report(
        payload,
        source_path=Path("artifacts/reports/zone_priority_calibration.json"),
        source_commit_sha="deadbee",
        source_workflow_run="99",
    )
    assert report["status"] == "ok"
    assert report["n_events"] == 300
    assert report["weighted_hit_rate"] == round(230 / 300, 6)
    assert report["family_weights"]["OB"] == 0.85
    assert report["metrics"]["smooth_ece"] == 0.115
    assert report["source"]["path"].endswith("zone_priority_calibration.json")


def test_build_public_report_redacts_internal_fields() -> None:
    """Public report must not leak per-symbol breakdowns or source paths
    beyond the single 'source.path' descriptor.
    """
    payload = {
        "per_symbol_stats": {"AAPL": {"hr": 0.91}, "TSLA": {"hr": 0.55}},  # MUST NOT leak
        "raw_event_counts": [1, 2, 3, 4, 5],  # MUST NOT leak
        "family_weights": {"OB": 0.85},
    }
    report = build_public_report(
        payload,
        source_path=None,
        source_commit_sha=None,
        source_workflow_run=None,
    )
    serialized = json.dumps(report)
    assert "AAPL" not in serialized
    assert "per_symbol_stats" not in serialized
    assert "raw_event_counts" not in serialized


# ── _find_latest_calibration_artifact ─────────────────────────────


def test_find_latest_returns_none_when_dir_missing(tmp_path: Path) -> None:
    assert _find_latest_calibration_artifact(tmp_path / "missing") is None


def test_find_latest_prefers_newest_among_same_named_copies(tmp_path: Path) -> None:
    # mtime is the freshness signal for copies of the SAME artifact in different
    # subdirs — filenames carry no timestamp.
    import os

    older = tmp_path / "a" / "zone_priority_calibration.json"
    newer = tmp_path / "b" / "zone_priority_calibration.json"
    for p in (older, newer):
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("{}")
    # Bump explicitly to avoid filesystem timestamp resolution flakes.
    os.utime(newer, (newer.stat().st_atime, newer.stat().st_mtime + 5))
    assert _find_latest_calibration_artifact(tmp_path) == newer


def test_find_latest_prefers_flat_schema_over_newer_contextual(tmp_path: Path) -> None:
    # REGRESSION (2026-07-15): mtime must NOT decide across the two schemas. The
    # generator writes the contextual artifact last, so "newest wins" resolved to
    # the one schema this module cannot read — emitting an empty status="ok"
    # report. Schema order wins; freshness only breaks ties within a filename.
    import os

    flat = tmp_path / "zone_priority_calibration.json"
    flat.write_text("{}")
    contextual = tmp_path / "zone_priority_contextual_calibration.json"
    contextual.write_text("{}")
    os.utime(contextual, (contextual.stat().st_atime, contextual.stat().st_mtime + 5))
    assert _find_latest_calibration_artifact(tmp_path) == flat


# ── append_public_history ─────────────────────────────────────────


def test_append_public_history_writes_jsonl(tmp_path: Path) -> None:
    out = tmp_path / "calibration_report_public.json"
    report = {
        "status": "ok",
        "generated_at": "2026-04-23T21:00:00+00:00",
        "n_events": 10,
        "weighted_hit_rate": 0.7,
        "metrics": {"smooth_ece": 0.1, "ece": 0.11},
        "source": {"commit_sha": "abc"},
    }
    history_path = append_public_history(out, report)
    lines = history_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["n_events"] == 10
    assert entry["metrics"]["smooth_ece"] == 0.1


def test_append_public_history_skips_awaiting_first_run(tmp_path: Path) -> None:
    """awaiting_first_run reports must not pollute the trend feed."""
    out = tmp_path / "calibration_report_public.json"
    report = {"status": "awaiting_first_run"}
    history_path = append_public_history(out, report)
    assert history_path.read_text(encoding="utf-8") == ""


def test_append_public_history_truncates_to_retention(tmp_path: Path) -> None:
    out = tmp_path / "calibration_report_public.json"
    base = {
        "status": "ok",
        "n_events": 10,
        "weighted_hit_rate": 0.7,
        "metrics": {},
        "source": {},
    }
    for i in range(HISTORY_RETENTION + 5):
        report = {**base, "generated_at": f"2026-01-{(i % 28) + 1:02d}T00:00:00+00:00"}
        append_public_history(out, report)
    history_path = out.with_name("calibration_report_public_history.jsonl")
    lines = [line for line in history_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(lines) == HISTORY_RETENTION


# ── main() integration ────────────────────────────────────────────


def test_main_emits_awaiting_first_run_when_no_artifact(tmp_path: Path) -> None:
    output = tmp_path / "out" / "calibration_report_public.json"
    rc = main(
        [
            "--search-dir",
            str(tmp_path / "missing"),
            "--output",
            str(output),
        ]
    )
    assert rc == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["status"] == "awaiting_first_run"
    assert payload["schema_version"] == PUBLIC_SCHEMA_VERSION


def test_main_emits_ok_with_explicit_input(tmp_path: Path) -> None:
    cal_src = tmp_path / "zone_priority_calibration.json"
    cal_src.write_text(
        json.dumps(
            {
                "family_weights": {"OB": 0.85, "FVG": 0.61},
                "family_stats": {"OB": {"total_events": 100, "total_hits": 85}},
                "testable_calibration": {"n_events": 100, "smooth_ece": 0.10, "ece_binned_n10": 0.11},
            }
        )
    )
    output = tmp_path / "out" / "calibration_report_public.json"
    rc = main(
        [
            "--input-cal",
            str(cal_src),
            "--output",
            str(output),
            "--commit-sha",
            "abc1234",
            "--workflow-run",
            "42",
        ]
    )
    assert rc == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["status"] == "ok"
    assert payload["n_events"] == 100
    assert payload["source"]["commit_sha"] == "abc1234"
    history = output.with_name("calibration_report_public_history.jsonl")
    assert history.exists()
    history_lines = [line for line in history.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(history_lines) == 1


def test_main_returns_one_on_malformed_input(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    bad = tmp_path / "zone_priority_calibration.json"
    bad.write_text("{not-json")
    output = tmp_path / "out" / "calibration_report_public.json"
    rc = main(["--input-cal", str(bad), "--output", str(output)])
    assert rc == 1
    assert "ERROR" in capsys.readouterr().err


def test_write_report_is_atomic(tmp_path: Path) -> None:
    """No .tmp left behind after a successful write."""
    output = tmp_path / "out" / "report.json"
    write_report({"x": 1}, output)
    assert output.exists()
    assert not output.with_suffix(output.suffix + ".tmp").exists()


# ── track_record_gate (schema 1.1.0 additive field) ─────────────────


def test_build_public_report_omits_track_record_gate_when_not_provided() -> None:
    report = build_public_report(
        None,
        source_path=None,
        source_commit_sha="abc",
        source_workflow_run="1",
    )
    assert "track_record_gate" not in report


def test_build_public_report_includes_track_record_gate_on_placeholder() -> None:
    gate = {"status": "yellow", "n_trades": 50, "checks": [], "summary": {}}
    report = build_public_report(
        None,
        source_path=None,
        source_commit_sha="abc",
        source_workflow_run="1",
        track_record_gate=gate,
    )
    assert report["status"] == "awaiting_first_run"
    assert report["track_record_gate"] == gate


def test_build_public_report_includes_track_record_gate_on_ok_payload() -> None:
    payload = {
        "family_weights": {"OB": 0.85},
        "family_stats": {"OB": {"total_events": 100, "total_hits": 60}},
        "calibration": {"ece": 0.05, "smooth_ece": 0.05, "brier": 0.20},
    }
    gate = {"status": "green", "n_trades": 200, "checks": [], "summary": {}}
    report = build_public_report(
        payload,
        source_path=None,
        source_commit_sha="abc",
        source_workflow_run="1",
        track_record_gate=gate,
    )
    assert report["status"] == "ok"
    assert report["track_record_gate"]["status"] == "green"


def test_schema_version_is_1_3_0_after_families_addition() -> None:
    # Deep-Review 2026-04-27: bumped MINOR from 1.2.0 to 1.3.0 with
    # the additive ``families`` field. Pin renamed accordingly under
    # docs/calibration/schemas/v1.3.0_public_schema_pin.json.
    assert PUBLIC_SCHEMA_VERSION == "1.3.0"


# ── regime_stratified (schema 1.2.0 additive field) ─────────────────


def test_build_public_report_omits_regime_stratified_when_not_provided() -> None:
    report = build_public_report(
        None,
        source_path=None,
        source_commit_sha="abc",
        source_workflow_run="1",
    )
    assert "regime_stratified" not in report


def test_build_public_report_includes_regime_stratified_on_placeholder() -> None:
    regime = {
        "RISK_ON": {
            "sharpe": 0.93,
            "sharpe_ci_low": 0.42,
            "sharpe_ci_high": 1.31,
            "permutation_p_value": 0.018,
            "n_trades": 142,
            "regime_frequency_pct": 38.5,
        },
        "aggregate_freq_weighted_sharpe": 0.71,
        "regime_concentration_warning": False,
        "fdr_q": 0.05,
        "bh_rejected_cells": ["RISK_ON"],
    }
    report = build_public_report(
        None,
        source_path=None,
        source_commit_sha="abc",
        source_workflow_run="1",
        regime_stratified=regime,
    )
    assert report["status"] == "awaiting_first_run"
    assert report["regime_stratified"] == regime


def test_build_public_report_includes_regime_stratified_on_ok_payload() -> None:
    payload = {
        "family_weights": {"OB": 0.85},
        "family_stats": {"OB": {"total_events": 100, "total_hits": 60}},
        "calibration": {"ece": 0.05, "smooth_ece": 0.05, "brier": 0.20},
    }
    regime = {
        "RISK_OFF": {"sharpe": -0.2, "n_trades": 50, "regime_frequency_pct": 22.0},
        "aggregate_freq_weighted_sharpe": 0.55,
        "regime_concentration_warning": True,
    }
    report = build_public_report(
        payload,
        source_path=None,
        source_commit_sha="abc",
        source_workflow_run="1",
        regime_stratified=regime,
    )
    assert report["status"] == "ok"
    assert report["regime_stratified"]["regime_concentration_warning"] is True
    assert report["regime_stratified"]["RISK_OFF"]["sharpe"] == -0.2


def test_track_record_gate_and_regime_stratified_can_coexist() -> None:
    payload = {
        "family_weights": {"OB": 0.85},
        "family_stats": {"OB": {"total_events": 100, "total_hits": 60}},
        "calibration": {"ece": 0.05, "smooth_ece": 0.05, "brier": 0.20},
    }
    gate = {"status": "green", "n_trades": 200, "checks": [], "summary": {}}
    regime = {"NEUTRAL": {"sharpe": 0.4, "n_trades": 30}}
    report = build_public_report(
        payload,
        source_path=None,
        source_commit_sha="abc",
        source_workflow_run="1",
        track_record_gate=gate,
        regime_stratified=regime,
    )
    assert report["track_record_gate"]["status"] == "green"
    assert report["regime_stratified"]["NEUTRAL"]["sharpe"] == 0.4


# ── C13/T5 — --include-families CLI flag ────────────────────────────


def _valid_families_payload() -> dict[str, Any]:
    return {
        "schema_version": "1.0.0",
        "families": [
            {
                "name": "BOS",
                "live_days": 7,
                "n_trades": 12,
                "kill_switch_fires": 0,
                "drift_verdict": "pass",
            },
            {
                "name": "OB",
                "live_days": 7,
                "n_trades": 8,
                "kill_switch_fires": 1,
                "drift_verdict": "acceptable",
            },
        ],
    }


def _write_minimal_cal(tmp_path: Path) -> Path:
    cal = tmp_path / "zone_priority_calibration.json"
    cal.write_text(
        json.dumps(
            {
                "family_weights": {"OB": 0.85, "FVG": 0.61},
                "family_stats": {"OB": {"total_events": 100, "total_hits": 85}},
                "testable_calibration": {
                    "n_events": 100,
                    "smooth_ece": 0.10,
                    "ece_binned_n10": 0.11,
                },
            }
        )
    )
    return cal


def test_main_without_include_families_omits_families_block(tmp_path: Path) -> None:
    output = tmp_path / "report.json"
    rc = main(
        [
            "--input-cal",
            str(_write_minimal_cal(tmp_path)),
            "--output",
            str(output),
        ]
    )
    assert rc == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert "families" not in payload


def test_main_with_include_families_embeds_block(tmp_path: Path) -> None:
    fam_path = tmp_path / "families.json"
    fam_path.write_text(json.dumps(_valid_families_payload()))
    output = tmp_path / "report.json"
    rc = main(
        [
            "--input-cal",
            str(_write_minimal_cal(tmp_path)),
            "--output",
            str(output),
            "--include-families",
            str(fam_path),
        ]
    )
    assert rc == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert "families" in payload
    names = sorted(f["name"] for f in payload["families"])
    assert names == ["BOS", "OB"]


def test_main_with_malformed_families_returns_one(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    fam_path = tmp_path / "families.json"
    fam_path.write_text("{not-json")
    rc = main(
        [
            "--input-cal",
            str(_write_minimal_cal(tmp_path)),
            "--output",
            str(tmp_path / "report.json"),
            "--include-families",
            str(fam_path),
        ]
    )
    assert rc == 1
    err = capsys.readouterr().err
    assert "families telemetry" in err.lower() or "malformed" in err.lower()


def test_main_with_missing_families_key_returns_one(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    fam_path = tmp_path / "families.json"
    fam_path.write_text(json.dumps({"schema_version": "1.0.0"}))  # no "families"
    rc = main(
        [
            "--input-cal",
            str(_write_minimal_cal(tmp_path)),
            "--output",
            str(tmp_path / "report.json"),
            "--include-families",
            str(fam_path),
        ]
    )
    assert rc == 1
    assert "families" in capsys.readouterr().err.lower()


def test_main_with_invalid_family_record_returns_one(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    fam_path = tmp_path / "families.json"
    fam_path.write_text(
        json.dumps(
            {
                "schema_version": "1.0.0",
                "families": [
                    {"name": "BOS"}  # missing required keys
                ],
            }
        )
    )
    rc = main(
        [
            "--input-cal",
            str(_write_minimal_cal(tmp_path)),
            "--output",
            str(tmp_path / "report.json"),
            "--include-families",
            str(fam_path),
        ]
    )
    assert rc == 1
    err = capsys.readouterr().err
    assert "C12" in err or "missing required keys" in err


def test_append_public_history_retention_zero_keeps_nothing(tmp_path: Path) -> None:
    """Bug-hunt r4: existing[-0:] kept the whole file for retention=0."""
    out = tmp_path / "calibration_report_public.json"
    report = {
        "status": "ok",
        "generated_at": "2026-04-23T21:00:00+00:00",
        "n_events": 10,
        "weighted_hit_rate": 0.7,
        "metrics": {"smooth_ece": 0.1, "ece": 0.11},
        "source": {"commit_sha": "abc"},
    }
    history_path = append_public_history(out, report, retention=0)
    assert history_path.read_text(encoding="utf-8").strip() == ""


# ── Contextual-schema regression (2026-07-15) ────────────────────
#
# The generator writes the flat artifact first and the contextual one LAST, so
# max-by-mtime always selected the contextual variant — whose schema this
# emitter never implemented (global_weights / bucket_stats /
# frozen_provenance.n_events vs family_weights / family_stats /
# testable_calibration). The result was a status="ok" report with every headline
# field empty, and 49/49 history entries with n_events=null since 2026-05-04.


def _write_pair(root: Path) -> None:
    """Write both artifacts the way the generator does: contextual last."""
    root.mkdir(parents=True, exist_ok=True)
    flat = {
        "family_weights": {"OB": 0.4782, "FVG": 0.582, "BOS": 0.8488, "SWEEP": 0.6799},
        "family_stats": {
            "BOS": {"total_events": 988, "total_hits": 855},
            "FVG": {"total_events": 3388, "total_hits": 1931},
            "OB": {"total_events": 603, "total_hits": 200},
            "SWEEP": {"total_events": 1133, "total_hits": 746},
        },
        "testable_calibration": {
            "n_events": 6112,
            "ece_binned_n10": 0.132014,
            "smooth_ece": 0.134909,
            "dce_upper_bound": 0.122597,
            "positive_rate": 0.610602,
        },
        "total_events": 6112,
    }
    contextual = {
        "global_weights": {"OB": 0.4782, "FVG": 0.582, "BOS": 0.8488, "SWEEP": 0.6799},
        "bucket_stats": {"htf_bias": {}, "session": {}, "vol_regime": {}},
        "frozen_provenance": {"n_events": 6112, "status": "shadow"},
    }
    (root / "zone_priority_calibration.json").write_text(json.dumps(flat), encoding="utf-8")
    (root / "zone_priority_contextual_calibration.json").write_text(
        json.dumps(contextual), encoding="utf-8"
    )


def test_resolver_picks_schema_the_emitter_implements(tmp_path: Path) -> None:
    _write_pair(tmp_path)
    found = _find_latest_calibration_artifact(tmp_path)
    assert found is not None
    assert found.name == "zone_priority_calibration.json"


def test_ok_report_from_generator_pair_has_real_headline_numbers(tmp_path: Path) -> None:
    _write_pair(tmp_path)
    found = _find_latest_calibration_artifact(tmp_path)
    payload = json.loads(found.read_text(encoding="utf-8"))
    report = build_public_report(
        payload, source_path=found, source_commit_sha="abc", source_workflow_run="1"
    )
    # status="ok" must MEAN the headline fields are populated.
    assert report["status"] == "ok"
    assert report["n_events"] == 6112
    assert report["weighted_hit_rate"] == 0.610602
    assert len(report["family_weights"]) == 4
    assert report["metrics"]["ece"] == 0.132014


def test_contextual_only_checkout_still_yields_weights_and_events(tmp_path: Path) -> None:
    # A contextual-only artifact must not silently degrade to an empty report.
    (tmp_path / "zone_priority_contextual_calibration.json").write_text(
        json.dumps(
            {
                "global_weights": {"OB": 0.4782, "BOS": 0.8488},
                "frozen_provenance": {"n_events": 6112},
            }
        ),
        encoding="utf-8",
    )
    found = _find_latest_calibration_artifact(tmp_path)
    assert found is not None
    payload = json.loads(found.read_text(encoding="utf-8"))
    report = build_public_report(
        payload, source_path=found, source_commit_sha=None, source_workflow_run=None
    )
    assert report["n_events"] == 6112
    assert report["family_weights"] == {"OB": 0.4782, "BOS": 0.8488}


def test_history_never_records_an_empty_ok_entry(tmp_path: Path) -> None:
    # The sparkline feed is what silently died: 49/49 entries n_events=null.
    out = tmp_path / "calibration_report_public.json"
    empty_ok = {"status": "ok", "generated_at": "2026-07-15T00:00:00+00:00",
                "n_events": None, "weighted_hit_rate": None, "metrics": {}}
    history = append_public_history(out, empty_ok)
    assert history.read_text(encoding="utf-8").strip() == ""


# ---------------------------------------------------------------------------
# ADR-0031: gates-dir loader (track_record_gate / regime_stratified wiring)
# ---------------------------------------------------------------------------


def test_load_latest_gate_artifact_missing_dir_is_none(tmp_path: Path) -> None:
    from scripts.emit_public_calibration_report import _load_latest_gate_artifact

    assert _load_latest_gate_artifact(tmp_path / "gates", "track_record_gate", None) is None


def test_load_latest_gate_artifact_picks_newest_by_date_not_mtime(tmp_path: Path) -> None:
    from scripts.emit_public_calibration_report import _load_latest_gate_artifact

    older = tmp_path / "regime_stratified_2026-07-01.json"
    newer = tmp_path / "regime_stratified_2026-07-29.json"
    newer.write_text(json.dumps({"date": "2026-07-29"}), encoding="utf-8")
    older.write_text(json.dumps({"date": "2026-07-01"}), encoding="utf-8")
    # older file has the NEWER mtime — the date in the name must still win
    payload = _load_latest_gate_artifact(tmp_path, "regime_stratified", None)
    assert payload == {"date": "2026-07-29"}


def test_load_latest_gate_artifact_malformed_is_failsoft_none(tmp_path: Path) -> None:
    from scripts.emit_public_calibration_report import _load_latest_gate_artifact

    bad = tmp_path / "track_record_gate_2026-07-29.json"
    bad.write_text("{not json", encoding="utf-8")
    assert _load_latest_gate_artifact(tmp_path, "track_record_gate", None) is None


def test_main_embeds_gate_and_regime_artifacts(tmp_path: Path) -> None:
    """End-to-end: main() finds the gates dir and embeds both additive keys."""
    from scripts.emit_public_calibration_report import main

    gates = tmp_path / "gates"
    gates.mkdir()
    (gates / "track_record_gate_2026-07-29.json").write_text(
        json.dumps({"status": "red", "n_trades": 100}), encoding="utf-8"
    )
    (gates / "regime_stratified_2026-07-29.json").write_text(
        json.dumps({"status": "insufficient_data", "n_trades_with_regime": 39}),
        encoding="utf-8",
    )
    out = tmp_path / "public.json"
    rc = main(
        [
            "--search-dir", str(tmp_path / "no-cal-artifacts"),
            "--gates-dir", str(gates),
            "--output", str(out),
        ]
    )
    assert rc == 0
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["track_record_gate"]["status"] == "red"
    assert report["regime_stratified"]["n_trades_with_regime"] == 39


def test_main_without_gates_dir_omits_keys(tmp_path: Path) -> None:
    from scripts.emit_public_calibration_report import main

    out = tmp_path / "public.json"
    rc = main(
        [
            "--search-dir", str(tmp_path / "no-cal-artifacts"),
            "--gates-dir", str(tmp_path / "no-gates"),
            "--output", str(out),
        ]
    )
    assert rc == 0
    report = json.loads(out.read_text(encoding="utf-8"))
    assert "track_record_gate" not in report
    assert "regime_stratified" not in report
