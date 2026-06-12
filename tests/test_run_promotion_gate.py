"""Sprint W1.b tests — `scripts.run_promotion_gate` CLI + helpers.

Includes the W1.c tripwire that fails if anyone removes the
``governance.promotion_gate`` import from the production entry point.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from governance.magnitude_stage_policy import MagnitudeStagePolicy
from governance.promotion_gate import DECISION_SCHEMA_VERSION
from governance.promotion_report import DEFAULT_PROMOTION_DECISIONS_PATH
from scripts import run_promotion_gate as runner

# ---------------------------------------------------------------------------
# Tripwire (W1.c) — keep the script wired to the X2 gate.
# ---------------------------------------------------------------------------


def test_runner_module_imports_promotion_gate() -> None:
    """If someone deletes the import, this test breaks instead of silently
    detaching the production pipeline from the X2 consolidator."""
    src = Path(runner.__file__).read_text(encoding="utf-8")
    assert "from governance.promotion_gate import" in src
    assert "PromotionGate" in src


# ---------------------------------------------------------------------------
# Bundle loader.
# ---------------------------------------------------------------------------


def test_load_bundle_rejects_unknown_family(tmp_path: Path) -> None:
    p = tmp_path / "bundle.json"
    p.write_text(json.dumps([{"family": "UNKNOWN"}]), encoding="utf-8")
    with pytest.raises(ValueError, match="unknown or missing 'family'"):
        runner._load_bundle(p)


def test_load_bundle_rejects_non_list(tmp_path: Path) -> None:
    p = tmp_path / "bundle.json"
    p.write_text(json.dumps({"family": "BOS"}), encoding="utf-8")
    with pytest.raises(ValueError, match="must be a JSON list"):
        runner._load_bundle(p)


def test_load_bundle_rejects_duplicate_family(tmp_path: Path) -> None:
    p = tmp_path / "bundle.json"
    p.write_text(
        json.dumps([{"family": "BOS"}, {"family": "BOS"}]),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="duplicate family"):
        runner._load_bundle(p)


def test_load_bundle_parses_numeric_and_provenance(tmp_path: Path) -> None:
    p = tmp_path / "bundle.json"
    p.write_text(
        json.dumps([
            {
                "family": "BOS",
                "brier": 0.18,
                "psi_slope": 0.01,
                "regime_degraded": False,
                "provenance": {"wf_scheme": "purged_kfold"},
                "extras": {"sharpe_oos": 1.23},
            }
        ]),
        encoding="utf-8",
    )
    snaps = runner._load_bundle(p)
    assert len(snaps) == 1
    snap = snaps[0]
    assert snap.family == "BOS"
    assert snap.brier == pytest.approx(0.18)
    assert snap.psi_slope == pytest.approx(0.01)
    assert snap.regime_degraded is False
    assert snap.provenance == {"wf_scheme": "purged_kfold"}
    assert snap.extras["sharpe_oos"] == pytest.approx(1.23)


# ---------------------------------------------------------------------------
# Report builder + exit code.
# ---------------------------------------------------------------------------


def _full_snapshot_dict(family: str) -> dict[str, object]:
    return {
        "family": family,
        "brier": 0.18,
        "brier_ci_upper": 0.21,
        "ece": 0.03,
        "fdr_pvalue": 0.01,
        "psr": 0.97,
        "mintrl_years": 1.4,
        "psi": 0.12,
        "live_brier": 0.19,
        "walkforward_brier": 0.18,
        "regime_degraded": False,
        "psi_slope": 0.01,
        "conformal_coverage": 0.92,
        "conformal_target": 0.90,
        "magnitude_resolution_pass": True,
        "magnitude_auc": 0.62,
        "provenance": {
            "wf_scheme": "purged_kfold",
            "wf_embargo_bars": 32,
            "bootstrap_method": "bca",
            "block_size": 64,
            "psr_method": "minIS",
            "stacked_used": True,
        },
    }


_NOW = datetime(2026, 5, 17, 18, 0, 0, tzinfo=UTC)


def _full_snapshot(family: str):
    return runner._family_metrics_from_dict(_full_snapshot_dict(family))


def test_build_report_strict_mode_promotes_full_snapshot(tmp_path: Path) -> None:
    bundle_path = tmp_path / "bundle.json"
    bundle_path.write_text(
        json.dumps([_full_snapshot_dict("BOS"), _full_snapshot_dict("OB")]),
        encoding="utf-8",
    )
    snaps = runner._load_bundle(bundle_path)
    report = runner.build_report(
        snaps,
        strict_provenance=True,
        now=datetime(2026, 5, 17, 18, 0, 0, tzinfo=UTC),
    )
    assert report["schema_version"] == runner.REPORT_SCHEMA_VERSION
    assert report["gate_schema_version"] == DECISION_SCHEMA_VERSION
    assert report["strict_provenance"] is True
    assert report["generated_at"] == "2026-05-17T18:00:00+00:00"
    assert len(report["decisions"]) == 2
    assert all(d["promoted"] for d in report["decisions"])
    assert runner._report_exit_code(report) == 0


def test_build_report_strict_mode_blocks_when_w1a_fields_missing(tmp_path: Path) -> None:
    bundle_path = tmp_path / "bundle.json"
    bundle_path.write_text(
        json.dumps([
            {
                "family": "BOS",
                "brier": 0.18,
                "ece": 0.03,
                "fdr_pvalue": 0.01,
                "psr": 0.97,
                "mintrl_years": 1.4,
                "psi": 0.12,
                "live_brier": 0.19,
                "walkforward_brier": 0.18,
            }
        ]),
        encoding="utf-8",
    )
    snaps = runner._load_bundle(bundle_path)
    report = runner.build_report(snaps, strict_provenance=True)
    assert report["decisions"][0]["promoted"] is False
    assert runner._report_exit_code(report) == 2


def test_build_report_no_strict_mode_keeps_legacy_compat(tmp_path: Path) -> None:
    bundle_path = tmp_path / "bundle.json"
    bundle_path.write_text(
        json.dumps([
            {
                "family": "BOS",
                "brier": 0.18,
                "ece": 0.03,
                "fdr_pvalue": 0.01,
                "psr": 0.97,
                "mintrl_years": 1.4,
                "psi": 0.12,
                "live_brier": 0.19,
                "walkforward_brier": 0.18,
            }
        ]),
        encoding="utf-8",
    )
    snaps = runner._load_bundle(bundle_path)
    report = runner.build_report(snaps, strict_provenance=False)
    assert report["decisions"][0]["promoted"] is True


# ---------------------------------------------------------------------------
# CLI end-to-end.
# ---------------------------------------------------------------------------


def test_cli_writes_report_and_returns_zero_when_promoted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    bundle_path = tmp_path / "bundle.json"
    output_path = tmp_path / "report.json"
    bundle_path.write_text(json.dumps([_full_snapshot_dict("BOS")]), encoding="utf-8")
    rc = runner.main(["--metrics", str(bundle_path), "--output", str(output_path)])
    assert rc == 0
    assert output_path.exists()
    report = json.loads(output_path.read_text(encoding="utf-8"))
    assert report["schema_version"] == runner.REPORT_SCHEMA_VERSION
    assert report["strict_provenance"] is True
    assert report["decisions"][0]["promoted"] is True


def test_cli_defaults_output_to_contract_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    bundle_path = tmp_path / "bundle.json"
    bundle_path.write_text(json.dumps([_full_snapshot_dict("BOS")]), encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    rc = runner.main(["--metrics", str(bundle_path)])
    output_path = tmp_path / DEFAULT_PROMOTION_DECISIONS_PATH
    assert rc == 0
    assert output_path.exists()


def test_cli_returns_two_when_any_family_blocked(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    bundle_path = tmp_path / "bundle.json"
    output_path = tmp_path / "report.json"
    bundle_path.write_text(json.dumps([{"family": "BOS", "brier": 0.18}]), encoding="utf-8")
    rc = runner.main(["--metrics", str(bundle_path), "--output", str(output_path)])
    assert rc == 2
    report = json.loads(output_path.read_text(encoding="utf-8"))
    assert report["decisions"][0]["promoted"] is False


def test_cli_returns_one_on_missing_input(tmp_path: Path) -> None:
    rc = runner.main([
        "--metrics",
        str(tmp_path / "missing.json"),
        "--output",
        str(tmp_path / "out.json"),
    ])
    assert rc == 1


def test_cli_no_strict_flag_promotes_legacy_snapshot(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    bundle_path = tmp_path / "bundle.json"
    output_path = tmp_path / "report.json"
    bundle_path.write_text(
        json.dumps([
            {
                "family": "BOS",
                "brier": 0.18,
                "ece": 0.03,
                "fdr_pvalue": 0.01,
                "psr": 0.97,
                "mintrl_years": 1.4,
                "psi": 0.12,
                "live_brier": 0.19,
                "walkforward_brier": 0.18,
            }
        ]),
        encoding="utf-8",
    )
    rc = runner.main([
        "--metrics",
        str(bundle_path),
        "--output",
        str(output_path),
        "--no-strict",
    ])
    assert rc == 0


# ---------------------------------------------------------------------------
# PQ Re-Audit A8 (#2354) — dashboard archive hook.
# ---------------------------------------------------------------------------


def test_cli_archives_timestamped_copy_for_dashboard(tmp_path: Path) -> None:
    bundle_path = tmp_path / "bundle.json"
    output_path = tmp_path / "report.json"
    archive_dir = tmp_path / "promotion_decisions"
    bundle_path.write_text(json.dumps([_full_snapshot_dict("BOS")]), encoding="utf-8")

    rc = runner.main([
        "--metrics", str(bundle_path),
        "--output", str(output_path),
        "--archive-dir", str(archive_dir),
    ])

    assert rc == 0
    archived = list(archive_dir.glob("promotion_decisions_*.json"))
    assert len(archived) == 1
    archived_payload = json.loads(archived[0].read_text(encoding="utf-8"))
    live_payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert archived_payload == live_payload


def test_cli_skips_archive_when_disabled(tmp_path: Path) -> None:
    bundle_path = tmp_path / "bundle.json"
    output_path = tmp_path / "report.json"
    archive_dir = tmp_path / "promotion_decisions"
    bundle_path.write_text(json.dumps([_full_snapshot_dict("BOS")]), encoding="utf-8")

    rc = runner.main([
        "--metrics", str(bundle_path),
        "--output", str(output_path),
        "--archive-dir", "",
    ])

    assert rc == 0
    assert not archive_dir.exists()


def test_archive_stamp_is_filename_safe_and_sortable() -> None:
    a = runner._archive_stamp("2026-05-25T06:00:00+00:00")
    b = runner._archive_stamp("2026-05-25T06:00:01+00:00")
    assert a == "20260525T060000Z"
    assert "/" not in a and ":" not in a and "+" not in a
    assert b > a


# ---------------------------------------------------------------------------
# ADR-0023 Stage 2 — ledger feed + per-family arming.
# ---------------------------------------------------------------------------


def _armed_policy(*families: str) -> MagnitudeStagePolicy:
    return MagnitudeStagePolicy(stage=2, armed_families=frozenset(families))


def _ledger_row(family: str, status: str, *, date: str = "2026-06-10") -> dict:
    return {
        "date": date,
        "family": family,
        "status": status,
        "magnitude_auc": 0.62,
        "auc_ci_low": 0.59,
    }


def _write_ledger(path: Path, rows: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")


def _lax_snapshot_dict(family: str) -> dict[str, object]:
    # Green in lax mode, magnitude deliberately unmeasured.
    return {
        "family": family,
        "brier": 0.18,
        "ece": 0.03,
        "fdr_pvalue": 0.01,
        "psr": 0.97,
        "mintrl_years": 1.4,
        "psi": 0.12,
        "live_brier": 0.19,
        "walkforward_brier": 0.18,
    }


def test_feed_injects_pass_verdict_for_armed_family(tmp_path: Path) -> None:
    ledger = tmp_path / "ledger.jsonl"
    _write_ledger(ledger, [_ledger_row("BOS", "PASS")])
    snaps = [runner._family_metrics_from_dict(_lax_snapshot_dict("BOS"))]
    out = runner.apply_magnitude_feed(
        snaps, policy=_armed_policy("BOS"), ledger_path=str(ledger)
    )
    assert out[0].magnitude_resolution_pass is True
    assert out[0].magnitude_auc == pytest.approx(0.62)


def test_feed_injects_fail_verdict_for_armed_family(tmp_path: Path) -> None:
    ledger = tmp_path / "ledger.jsonl"
    _write_ledger(ledger, [_ledger_row("BOS", "FAIL")])
    snaps = [runner._family_metrics_from_dict(_lax_snapshot_dict("BOS"))]
    out = runner.apply_magnitude_feed(
        snaps, policy=_armed_policy("BOS"), ledger_path=str(ledger)
    )
    assert out[0].magnitude_resolution_pass is False


def test_feed_bundle_explicit_value_wins_over_ledger(tmp_path: Path) -> None:
    ledger = tmp_path / "ledger.jsonl"
    _write_ledger(ledger, [_ledger_row("BOS", "FAIL")])
    payload = _lax_snapshot_dict("BOS")
    payload["magnitude_resolution_pass"] = True
    snaps = [runner._family_metrics_from_dict(payload)]
    out = runner.apply_magnitude_feed(
        snaps, policy=_armed_policy("BOS"), ledger_path=str(ledger)
    )
    assert out[0].magnitude_resolution_pass is True


def test_feed_never_injects_into_unarmed_family(tmp_path: Path) -> None:
    # FVG is a control: its by-design FAIL must not reach the gate.
    ledger = tmp_path / "ledger.jsonl"
    _write_ledger(
        ledger, [_ledger_row("BOS", "PASS"), _ledger_row("FVG", "FAIL")]
    )
    snaps = [
        runner._family_metrics_from_dict(_lax_snapshot_dict("BOS")),
        runner._family_metrics_from_dict(_lax_snapshot_dict("FVG")),
    ]
    out = runner.apply_magnitude_feed(
        snaps, policy=_armed_policy("BOS"), ledger_path=str(ledger)
    )
    assert out[0].magnitude_resolution_pass is True
    assert out[1].magnitude_resolution_pass is None


def test_feed_missing_ledger_is_fail_soft(tmp_path: Path) -> None:
    snaps = [runner._family_metrics_from_dict(_lax_snapshot_dict("BOS"))]
    out = runner.apply_magnitude_feed(
        snaps,
        policy=_armed_policy("BOS"),
        ledger_path=str(tmp_path / "missing.jsonl"),
    )
    assert out[0].magnitude_resolution_pass is None


def test_feed_noop_when_nothing_armed(tmp_path: Path) -> None:
    snaps = [runner._family_metrics_from_dict(_lax_snapshot_dict("BOS"))]
    out = runner.apply_magnitude_feed(
        snaps,
        policy=MagnitudeStagePolicy(),
        ledger_path=str(tmp_path / "missing.jsonl"),
    )
    assert out is snaps


def test_cli_armed_family_blocked_without_ledger_verdict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Armed + lax + no ledger row → fail-closed info blocker → rc 2.
    monkeypatch.chdir(tmp_path)
    bundle = tmp_path / "bundle.json"
    bundle.write_text(json.dumps([_lax_snapshot_dict("BOS")]), encoding="utf-8")
    policy = tmp_path / "policy.json"
    policy.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "stage": 2,
                "armed_families": ["BOS"],
                "k": 3,
                "n": 4,
                "history": [],
            }
        ),
        encoding="utf-8",
    )
    out = tmp_path / "report.json"
    rc = runner.main([
        "--metrics", str(bundle),
        "--output", str(out),
        "--archive-dir", "",
        "--no-strict",
        "--magnitude-policy", str(policy),
        "--magnitude-ledger", str(tmp_path / "missing.jsonl"),
    ])
    assert rc == 2
    report = json.loads(out.read_text(encoding="utf-8"))
    [decision] = report["decisions"]
    assert decision["promoted"] is False
    checks = {b["check"] for b in decision["blockers"]}
    assert checks == {"magnitude_resolution_floor"}


def test_cli_armed_family_promotes_with_ledger_pass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    bundle = tmp_path / "bundle.json"
    bundle.write_text(json.dumps([_lax_snapshot_dict("BOS")]), encoding="utf-8")
    policy = tmp_path / "policy.json"
    policy.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "stage": 2,
                "armed_families": ["BOS"],
                "k": 3,
                "n": 4,
                "history": [],
            }
        ),
        encoding="utf-8",
    )
    ledger = tmp_path / "ledger.jsonl"
    _write_ledger(ledger, [_ledger_row("BOS", "PASS")])
    out = tmp_path / "report.json"
    rc = runner.main([
        "--metrics", str(bundle),
        "--output", str(out),
        "--archive-dir", "",
        "--no-strict",
        "--magnitude-policy", str(policy),
        "--magnitude-ledger", str(ledger),
    ])
    assert rc == 0
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["decisions"][0]["promoted"] is True


def test_cli_corrupt_magnitude_ledger_is_config_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    """W7-1: a corrupt shadow ledger must abort the gate run (rc 1), not
    gate armed families on whatever rows happened to survive the parse."""
    monkeypatch.chdir(tmp_path)
    bundle = tmp_path / "bundle.json"
    bundle.write_text(json.dumps([_lax_snapshot_dict("BOS")]), encoding="utf-8")
    policy = tmp_path / "policy.json"
    policy.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "stage": 2,
                "armed_families": ["BOS"],
                "k": 3,
                "n": 4,
                "history": [],
            }
        ),
        encoding="utf-8",
    )
    ledger = tmp_path / "ledger.jsonl"
    ledger.write_text(
        json.dumps(_ledger_row("BOS", "PASS")) + "\nnot json\n", encoding="utf-8"
    )
    out = tmp_path / "report.json"
    rc = runner.main([
        "--metrics", str(bundle),
        "--output", str(out),
        "--archive-dir", "",
        "--no-strict",
        "--magnitude-policy", str(policy),
        "--magnitude-ledger", str(ledger),
    ])
    assert rc == 1
    assert "malformed ledger line" in capsys.readouterr().err
    assert not out.exists()  # no report written on config error


def test_cli_no_magnitude_feed_escape_hatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # --no-magnitude-feed disables BOTH the ledger feed and arming → the lax
    # gate stays dormant on unmeasured magnitude (legacy behaviour).
    monkeypatch.chdir(tmp_path)
    bundle = tmp_path / "bundle.json"
    bundle.write_text(json.dumps([_lax_snapshot_dict("BOS")]), encoding="utf-8")
    policy = tmp_path / "policy.json"
    policy.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "stage": 2,
                "armed_families": ["BOS"],
                "k": 3,
                "n": 4,
                "history": [],
            }
        ),
        encoding="utf-8",
    )
    out = tmp_path / "report.json"
    rc = runner.main([
        "--metrics", str(bundle),
        "--output", str(out),
        "--archive-dir", "",
        "--no-strict",
        "--magnitude-policy", str(policy),
        "--no-magnitude-feed",
    ])
    assert rc == 0


def test_cli_malformed_magnitude_policy_returns_1(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    bundle = tmp_path / "bundle.json"
    bundle.write_text(json.dumps([_lax_snapshot_dict("BOS")]), encoding="utf-8")
    policy = tmp_path / "policy.json"
    policy.write_text("{broken", encoding="utf-8")
    rc = runner.main([
        "--metrics", str(bundle),
        "--output", str(tmp_path / "report.json"),
        "--archive-dir", "",
        "--magnitude-policy", str(policy),
    ])
    assert rc == 1


def test_label_slug_is_filename_safe() -> None:
    assert runner._label_slug("aapl") == "AAPL"
    assert runner._label_slug("BRK.B") == "BRKB"
    assert runner._label_slug("es=f") == "ESF"
    assert runner._label_slug("a" * 40) == "A" * 24
    assert runner._label_slug(None) == ""
    assert runner._label_slug("///") == ""


def test_archive_filename_embeds_label_and_stays_globbable(tmp_path: Path) -> None:
    report = runner.build_report([_full_snapshot("BOS")], now=_NOW)
    path = runner._archive_report(report, tmp_path, label="aapl")
    assert path is not None
    assert path.name.startswith("promotion_decisions_AAPL_")
    # The shared consumer glob still matches the labelled filename.
    assert path in set(tmp_path.glob("promotion_decisions_*.json"))


def test_archive_filename_falls_back_without_label(tmp_path: Path) -> None:
    report = runner.build_report([_full_snapshot("BOS")], now=_NOW)
    path = runner._archive_report(report, tmp_path, label=None)
    assert path is not None
    assert path.name.startswith("promotion_decisions_2")  # timestamp-led


def test_build_report_embeds_context_when_provided() -> None:
    context = {"symbol": "AAPL", "dataset": "XNAS.ITCH", "schema": "ohlcv-1m"}
    report = runner.build_report([_full_snapshot("BOS")], now=_NOW, context=context)
    assert report["schema_version"] == 2
    assert report["context"] == context


def test_build_report_omits_context_key_when_absent() -> None:
    report = runner.build_report([_full_snapshot("BOS")], now=_NOW)
    assert "context" not in report

