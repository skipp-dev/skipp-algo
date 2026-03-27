from __future__ import annotations

from argparse import Namespace

from scripts import run_smc_ci_health_checks as ci_script
from scripts import run_smc_release_gates as release_script


class _Parser:
    def __init__(self, args: Namespace):
        self._args = args

    def parse_args(self) -> Namespace:
        return self._args


def test_ci_health_runner_warn_is_non_blocking_by_default(monkeypatch) -> None:
    monkeypatch.setattr(
        ci_script,
        "build_parser",
        lambda: _Parser(
            Namespace(
                symbols="IBG",
                timeframes="15m",
                stale_after_seconds=None,
                fail_on_warn=False,
                output="-",
            )
        ),
    )
    monkeypatch.setattr(ci_script, "run_provider_health_check", lambda **kwargs: {"overall_status": "warn"})
    monkeypatch.setattr(ci_script, "write_provider_health_report", lambda report, output: None)

    assert ci_script.main() == 0


def test_ci_health_runner_warn_can_be_forced_blocking(monkeypatch) -> None:
    monkeypatch.setattr(
        ci_script,
        "build_parser",
        lambda: _Parser(
            Namespace(
                symbols="IBG",
                timeframes="15m",
                stale_after_seconds=None,
                fail_on_warn=True,
                output="-",
            )
        ),
    )
    monkeypatch.setattr(ci_script, "run_provider_health_check", lambda **kwargs: {"overall_status": "warn"})
    monkeypatch.setattr(ci_script, "write_provider_health_report", lambda report, output: None)

    assert ci_script.main() == 2


def test_release_runner_is_fail_closed_on_core_failures(monkeypatch) -> None:
    captured_reports: list[dict] = []
    call_kwargs: list[dict] = []

    monkeypatch.setattr(
        release_script,
        "build_parser",
        lambda: _Parser(
            Namespace(
                symbols="IBG",
                timeframes="15m",
                stale_after_seconds=3600,
                fail_on_warn=False,
                allow_warn=False,
                skip_publish_contract=True,
                manifest="pine/generated/smc_micro_profiles_generated.json",
                core_engine="SMC_Core_Engine.pine",
                output="-",
            )
        ),
    )

    def _provider_stub(**kwargs):
        call_kwargs.append(kwargs)
        return {
            "overall_status": "fail",
            "failures": [{"code": "MISSING_ARTIFACT", "promoted_by": "release_strict_policy"}],
            "warnings": [],
            "degradations_detected": [],
            "smoke_test_results": [{"symbol": "IBG", "timeframe": "15m"}],
        }

    monkeypatch.setattr(release_script, "run_provider_health_check", _provider_stub)
    monkeypatch.setattr(release_script, "_run_reference_bundle_gate", lambda symbol, timeframe, generated_at: {"name": "reference_bundle", "status": "ok", "details": {}})
    monkeypatch.setattr(release_script, "_render", lambda report, output: captured_reports.append(report))

    rc = release_script.main()

    assert rc == 1
    assert captured_reports[-1]["overall_status"] == "fail"
    assert call_kwargs[-1]["strict_release_policy"] is True


def test_release_runner_report_and_exit_are_deterministic(monkeypatch) -> None:
    captured_reports: list[dict] = []
    times = [1700000000.0, 1700000000.0]

    monkeypatch.setattr(
        release_script,
        "build_parser",
        lambda: _Parser(
            Namespace(
                symbols="IBG",
                timeframes="15m",
                stale_after_seconds=3600,
                fail_on_warn=False,
                allow_warn=True,
                skip_publish_contract=True,
                manifest="pine/generated/smc_micro_profiles_generated.json",
                core_engine="SMC_Core_Engine.pine",
                output="-",
            )
        ),
    )
    monkeypatch.setattr(release_script.time, "time", lambda: times.pop(0))
    monkeypatch.setattr(
        release_script,
        "run_provider_health_check",
        lambda **kwargs: {
            "overall_status": "warn",
            "failures": [],
            "warnings": [{"code": "MISSING_ARTIFACT"}],
            "degradations_detected": [],
            "smoke_test_results": [{"symbol": "IBG", "timeframe": "15m"}],
        },
    )
    monkeypatch.setattr(release_script, "_run_reference_bundle_gate", lambda symbol, timeframe, generated_at: {"name": "reference_bundle", "status": "ok", "details": {"symbol": symbol, "timeframe": timeframe}})
    monkeypatch.setattr(release_script, "_render", lambda report, output: captured_reports.append(report))

    rc_one = release_script.main()
    rc_two = release_script.main()

    assert rc_one == 0
    assert rc_two == 0
    assert captured_reports[0] == captured_reports[1]
