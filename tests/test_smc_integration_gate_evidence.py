from __future__ import annotations

import json
from argparse import Namespace
from pathlib import Path

from scripts import collect_smc_gate_evidence as evidence_script


class _Parser:
    def __init__(self, args: Namespace):
        self._args = args

    def parse_args(self) -> Namespace:
        return self._args


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_gate_evidence_marks_green_ready_for_minimum_success_series(monkeypatch, tmp_path: Path) -> None:
    now_ts = 1_700_000_000.0
    monkeypatch.setattr(evidence_script.time, "time", lambda: now_ts)

    for idx in range(3):
        _write_json(
            tmp_path / f"deeper_{idx}.json",
            {
                "report_kind": "ci_health",
                "checked_at": now_ts - 60.0 * (idx + 1),
                "overall_status": "ok",
                "reference_symbols": ["USAR", "TMQ"],
                "reference_timeframes": ["5m", "15m"],
                "runtime_metadata": {"git_commit": f"sha-deeper-{idx}"},
            },
        )

    for idx in range(2):
        _write_json(
            tmp_path / f"release_{idx}.json",
            {
                "report_kind": "release_gates",
                "checked_at": now_ts - 500.0 - 60.0 * idx,
                "overall_status": "ok",
                "reference_symbols": ["USAR", "TMQ"],
                "reference_timeframes": ["5m", "15m"],
                "runtime_metadata": {"git_commit": f"sha-release-{idx}"},
                "gates": [{"name": "provider_health", "status": "ok", "details": {}}],
            },
        )

    captured: list[dict] = []
    monkeypatch.setattr(
        evidence_script,
        "build_parser",
        lambda: _Parser(
            Namespace(
                input_glob=str(tmp_path / "*.json"),
                lookback_days=14,
                min_deeper_ok_runs=3,
                min_release_ok_runs=2,
                fail_on_not_ready=False,
                output="-",
            )
        ),
    )
    monkeypatch.setattr(evidence_script, "_render", lambda report, output: captured.append(report))

    rc = evidence_script.main()

    assert rc == 0
    assert captured[-1]["green_ready"] is True
    assert captured[-1]["deeper_ok_runs_in_window"] == 3
    assert captured[-1]["release_ok_runs_in_window"] == 2
    assert captured[-1]["unresolved_core_failures_in_window"] == 0


def test_gate_evidence_detects_unresolved_stale_failure(monkeypatch, tmp_path: Path) -> None:
    now_ts = 1_700_000_000.0
    monkeypatch.setattr(evidence_script.time, "time", lambda: now_ts)

    _write_json(
        tmp_path / "deeper_ok.json",
        {
            "report_kind": "ci_health",
            "checked_at": now_ts - 120.0,
            "overall_status": "ok",
            "runtime_metadata": {"git_commit": "sha-deeper"},
        },
    )
    _write_json(
        tmp_path / "release_fail.json",
        {
            "report_kind": "release_gates",
            "checked_at": now_ts - 60.0,
            "overall_status": "fail",
            "runtime_metadata": {"git_commit": "sha-release"},
            "gates": [
                {
                    "name": "provider_health",
                    "status": "fail",
                    "details": {
                        "failures": [
                            {
                                "code": "STALE_MANIFEST_GENERATED_AT",
                            }
                        ]
                    },
                }
            ],
        },
    )

    captured: list[dict] = []
    monkeypatch.setattr(
        evidence_script,
        "build_parser",
        lambda: _Parser(
            Namespace(
                input_glob=str(tmp_path / "*.json"),
                lookback_days=14,
                min_deeper_ok_runs=1,
                min_release_ok_runs=1,
                fail_on_not_ready=True,
                output="-",
            )
        ),
    )
    monkeypatch.setattr(evidence_script, "_render", lambda report, output: captured.append(report))

    rc = evidence_script.main()

    assert rc == 1
    assert captured[-1]["green_ready"] is False
    assert captured[-1]["unresolved_core_failures_in_window"] >= 1
    assert captured[-1]["stale_trend"].get("STALE_MANIFEST_GENERATED_AT") == 1


# ---------------------------------------------------------------------------
# Domain-Staleness aggregation in evidence summary
# ---------------------------------------------------------------------------


def test_gate_evidence_aggregates_stale_domain_codes(monkeypatch, tmp_path: Path) -> None:
    now_ts = 1_700_000_000.0
    monkeypatch.setattr(evidence_script.time, "time", lambda: now_ts)

    # Deeper run with stale technical
    _write_json(
        tmp_path / "deeper_stale_tech.json",
        {
            "report_kind": "ci_health",
            "checked_at": now_ts - 120.0,
            "overall_status": "warn",
            "runtime_metadata": {"git_commit": "sha-1"},
            "degradations_detected": [{"code": "STALE_META_TECHNICAL_DOMAIN"}],
        },
    )
    # Deeper run with stale volume and news
    _write_json(
        tmp_path / "deeper_stale_vol_news.json",
        {
            "report_kind": "ci_health",
            "checked_at": now_ts - 60.0,
            "overall_status": "warn",
            "runtime_metadata": {"git_commit": "sha-2"},
            "degradations_detected": [
                {"code": "STALE_META_VOLUME_DOMAIN"},
                {"code": "STALE_META_NEWS_DOMAIN"},
            ],
        },
    )
    # Release run with stale volume (promoted to failure)
    _write_json(
        tmp_path / "release_stale_vol.json",
        {
            "report_kind": "release_gates",
            "checked_at": now_ts - 30.0,
            "overall_status": "fail",
            "runtime_metadata": {"git_commit": "sha-3"},
            "gates": [
                {
                    "name": "provider_health",
                    "status": "fail",
                    "details": {
                        "failures": [{"code": "STALE_META_VOLUME_DOMAIN", "promoted_by": "release_strict_policy"}],
                    },
                }
            ],
        },
    )

    captured: list[dict] = []
    monkeypatch.setattr(
        evidence_script,
        "build_parser",
        lambda: _Parser(
            Namespace(
                input_glob=str(tmp_path / "*.json"),
                lookback_days=14,
                min_deeper_ok_runs=1,
                min_release_ok_runs=1,
                fail_on_not_ready=False,
                output="-",
            )
        ),
    )
    monkeypatch.setattr(evidence_script, "_render", lambda report, output: captured.append(report))

    evidence_script.main()
    summary = captured[-1]

    # stale_domain_trend counts
    assert summary["stale_domain_trend"]["STALE_META_TECHNICAL_DOMAIN"] == 1
    assert summary["stale_domain_trend"]["STALE_META_VOLUME_DOMAIN"] == 2
    assert summary["stale_domain_trend"]["STALE_META_NEWS_DOMAIN"] == 1

    # stale_domain_runs has path info
    vol_runs = summary["stale_domain_runs"]["STALE_META_VOLUME_DOMAIN"]
    assert len(vol_runs) == 2
    assert all("path" in r and "checked_at_iso" in r for r in vol_runs)

    tech_runs = summary["stale_domain_runs"]["STALE_META_TECHNICAL_DOMAIN"]
    assert len(tech_runs) == 1

    # These codes also appear in the generic stale_trend
    assert summary["stale_trend"]["STALE_META_VOLUME_DOMAIN"] == 2
    assert summary["stale_trend"]["STALE_META_TECHNICAL_DOMAIN"] == 1


def test_gate_evidence_no_domain_stale_produces_empty_aggregation(monkeypatch, tmp_path: Path) -> None:
    now_ts = 1_700_000_000.0
    monkeypatch.setattr(evidence_script.time, "time", lambda: now_ts)

    _write_json(
        tmp_path / "deeper_ok.json",
        {
            "report_kind": "ci_health",
            "checked_at": now_ts - 60.0,
            "overall_status": "ok",
            "runtime_metadata": {"git_commit": "sha-clean"},
        },
    )

    captured: list[dict] = []
    monkeypatch.setattr(
        evidence_script,
        "build_parser",
        lambda: _Parser(
            Namespace(
                input_glob=str(tmp_path / "*.json"),
                lookback_days=14,
                min_deeper_ok_runs=1,
                min_release_ok_runs=0,
                fail_on_not_ready=False,
                output="-",
            )
        ),
    )
    monkeypatch.setattr(evidence_script, "_render", lambda report, output: captured.append(report))

    evidence_script.main()
    summary = captured[-1]

    assert summary["stale_domain_trend"] == {}
    assert summary["stale_domain_runs"] == {}


def test_gate_evidence_domain_stale_aggregation_is_deterministic(monkeypatch, tmp_path: Path) -> None:
    now_ts = 1_700_000_000.0
    monkeypatch.setattr(evidence_script.time, "time", lambda: now_ts)

    _write_json(
        tmp_path / "deeper_warn.json",
        {
            "report_kind": "ci_health",
            "checked_at": now_ts - 60.0,
            "overall_status": "warn",
            "runtime_metadata": {"git_commit": "sha-det"},
            "degradations_detected": [
                {"code": "STALE_META_NEWS_DOMAIN"},
                {"code": "STALE_META_VOLUME_DOMAIN"},
            ],
        },
    )

    results = []
    for _ in range(2):
        captured: list[dict] = []
        monkeypatch.setattr(
            evidence_script,
            "build_parser",
            lambda: _Parser(
                Namespace(
                    input_glob=str(tmp_path / "*.json"),
                    lookback_days=14,
                    min_deeper_ok_runs=0,
                    min_release_ok_runs=0,
                    fail_on_not_ready=False,
                    output="-",
                )
            ),
        )
        monkeypatch.setattr(evidence_script, "_render", lambda report, output: captured.append(report))
        evidence_script.main()
        results.append(captured[-1])

    import json
    assert json.dumps(results[0]["stale_domain_trend"], sort_keys=True) == json.dumps(results[1]["stale_domain_trend"], sort_keys=True)
    assert json.dumps(results[0]["stale_domain_runs"], sort_keys=True) == json.dumps(results[1]["stale_domain_runs"], sort_keys=True)
