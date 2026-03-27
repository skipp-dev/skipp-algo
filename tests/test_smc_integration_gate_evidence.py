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
