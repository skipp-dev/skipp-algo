"""Tests for release policy defaults, env/CLI overrides, stale thresholds,
evidence coverage, and failure diagnostics."""
from __future__ import annotations

import os
from typing import Any

import pytest

from smc_integration.release_policy import (
    EVIDENCE_MIN_SYMBOL_COVERAGE,
    EVIDENCE_MIN_TIMEFRAME_COVERAGE,
    REASON_INSUFFICIENT_RUNS,
    REASON_INSUFFICIENT_SYMBOLS,
    REASON_INSUFFICIENT_TIMEFRAMES,
    REASON_MISSING_ARTIFACT,
    REASON_SMOKE_FAILURE,
    REASON_STALE_DATA,
    RELEASE_REFERENCE_SYMBOLS,
    RELEASE_REFERENCE_TIMEFRAMES,
    RELEASE_STALE_AFTER_SECONDS,
    diagnose_gate_failure,
    parse_csv,
    resolve_release_policy,
)


# ---------------------------------------------------------------------------
# Default policy values
# ---------------------------------------------------------------------------

class TestDefaultPolicy:
    def test_reference_symbols_has_broad_coverage(self) -> None:
        assert len(RELEASE_REFERENCE_SYMBOLS) >= 10

    def test_reference_symbols_all_uppercase(self) -> None:
        for sym in RELEASE_REFERENCE_SYMBOLS:
            assert sym == sym.upper(), f"{sym} is not uppercase"

    def test_reference_symbols_no_duplicates(self) -> None:
        assert len(RELEASE_REFERENCE_SYMBOLS) == len(set(RELEASE_REFERENCE_SYMBOLS))

    def test_reference_timeframes_include_intraday_and_higher(self) -> None:
        tfs = set(RELEASE_REFERENCE_TIMEFRAMES)
        assert "5m" in tfs
        assert "15m" in tfs
        assert len(tfs) >= 3, "need at least 3 timeframes for breadth"

    def test_stale_threshold_is_7_days(self) -> None:
        assert RELEASE_STALE_AFTER_SECONDS == 7 * 24 * 60 * 60

    def test_coverage_thresholds_are_positive(self) -> None:
        assert EVIDENCE_MIN_SYMBOL_COVERAGE >= 1
        assert EVIDENCE_MIN_TIMEFRAME_COVERAGE >= 1


# ---------------------------------------------------------------------------
# resolve_release_policy — explicit > env > defaults
# ---------------------------------------------------------------------------

class TestResolvePolicy:
    def test_defaults_when_no_overrides(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("SMC_RELEASE_SYMBOLS", raising=False)
        monkeypatch.delenv("SMC_RELEASE_TIMEFRAMES", raising=False)
        monkeypatch.delenv("SMC_RELEASE_STALE_SECONDS", raising=False)
        policy = resolve_release_policy()
        assert policy["symbols"] == list(RELEASE_REFERENCE_SYMBOLS)
        assert policy["timeframes"] == list(RELEASE_REFERENCE_TIMEFRAMES)
        assert policy["stale_after_seconds"] == RELEASE_STALE_AFTER_SECONDS

    def test_env_overrides_symbols(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SMC_RELEASE_SYMBOLS", "TSLA,NVDA")
        monkeypatch.delenv("SMC_RELEASE_TIMEFRAMES", raising=False)
        monkeypatch.delenv("SMC_RELEASE_STALE_SECONDS", raising=False)
        policy = resolve_release_policy()
        assert policy["symbols"] == ["TSLA", "NVDA"]
        assert policy["timeframes"] == list(RELEASE_REFERENCE_TIMEFRAMES)

    def test_env_overrides_timeframes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("SMC_RELEASE_SYMBOLS", raising=False)
        monkeypatch.setenv("SMC_RELEASE_TIMEFRAMES", "1m,5m")
        monkeypatch.delenv("SMC_RELEASE_STALE_SECONDS", raising=False)
        policy = resolve_release_policy()
        assert policy["timeframes"] == ["1m", "5m"]

    def test_env_overrides_stale_seconds(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("SMC_RELEASE_SYMBOLS", raising=False)
        monkeypatch.delenv("SMC_RELEASE_TIMEFRAMES", raising=False)
        monkeypatch.setenv("SMC_RELEASE_STALE_SECONDS", "3600")
        policy = resolve_release_policy()
        assert policy["stale_after_seconds"] == 3600

    def test_explicit_args_override_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SMC_RELEASE_SYMBOLS", "TSLA,NVDA")
        monkeypatch.setenv("SMC_RELEASE_TIMEFRAMES", "1m")
        monkeypatch.setenv("SMC_RELEASE_STALE_SECONDS", "9999")
        policy = resolve_release_policy(
            symbols="GOOG,AMZN",
            timeframes="4H",
            stale_after_seconds=1800,
        )
        assert policy["symbols"] == ["GOOG", "AMZN"]
        assert policy["timeframes"] == ["4H"]
        assert policy["stale_after_seconds"] == 1800

    def test_csv_with_whitespace_and_duplicates(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("SMC_RELEASE_SYMBOLS", raising=False)
        policy = resolve_release_policy(symbols=" AAPL , msft ,AAPL ")
        assert policy["symbols"] == ["AAPL", "MSFT"]


# ---------------------------------------------------------------------------
# Stale threshold semantics
# ---------------------------------------------------------------------------

class TestStaleThreshold:
    def test_seven_day_threshold_in_seconds(self) -> None:
        assert RELEASE_STALE_AFTER_SECONDS == 604800

    def test_env_can_tighten_threshold(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SMC_RELEASE_STALE_SECONDS", "86400")  # 1 day
        monkeypatch.delenv("SMC_RELEASE_SYMBOLS", raising=False)
        monkeypatch.delenv("SMC_RELEASE_TIMEFRAMES", raising=False)
        policy = resolve_release_policy()
        assert policy["stale_after_seconds"] == 86400


# ---------------------------------------------------------------------------
# diagnose_gate_failure
# ---------------------------------------------------------------------------

class TestDiagnoseGateFailure:
    def test_empty_report_yields_only_breadth_reasons(self) -> None:
        reasons = diagnose_gate_failure({})
        # No failure/gate codes, but missing reference_symbols/timeframes triggers breadth warnings.
        assert all(r["reason"] in {REASON_INSUFFICIENT_SYMBOLS, REASON_INSUFFICIENT_TIMEFRAMES} for r in reasons)

    def test_stale_failure_classified(self) -> None:
        report: dict[str, Any] = {
            "failures": [{"code": "STALE_MANIFEST_GENERATED_AT"}],
        }
        reasons = diagnose_gate_failure(report)
        assert any(r["reason"] == REASON_STALE_DATA for r in reasons)

    def test_missing_artifact_classified(self) -> None:
        report: dict[str, Any] = {
            "failures": [{"code": "MISSING_ARTIFACT"}],
        }
        reasons = diagnose_gate_failure(report)
        assert any(r["reason"] == REASON_MISSING_ARTIFACT for r in reasons)

    def test_smoke_failure_classified(self) -> None:
        report: dict[str, Any] = {
            "gates": [
                {
                    "name": "provider_health",
                    "status": "fail",
                    "details": {
                        "missing_smoke_failures": [
                            {"code": "MISSING_SMOKE_RESULT", "symbol": "AAPL", "timeframe": "15m"},
                        ],
                    },
                }
            ],
        }
        reasons = diagnose_gate_failure(report)
        assert any(r["reason"] == REASON_SMOKE_FAILURE for r in reasons)

    def test_insufficient_symbol_breadth(self) -> None:
        report: dict[str, Any] = {
            "reference_symbols": ["AAPL"],
            "reference_timeframes": ["5m", "15m", "1H", "4H"],
        }
        reasons = diagnose_gate_failure(report)
        assert any(r["reason"] == REASON_INSUFFICIENT_SYMBOLS for r in reasons)

    def test_sufficient_breadth_emits_no_breadth_reason(self) -> None:
        report: dict[str, Any] = {
            "reference_symbols": [f"SYM{i}" for i in range(EVIDENCE_MIN_SYMBOL_COVERAGE)],
            "reference_timeframes": [f"tf{i}" for i in range(EVIDENCE_MIN_TIMEFRAME_COVERAGE)],
        }
        reasons = diagnose_gate_failure(report)
        breadth_reasons = [r for r in reasons if r["reason"] in {REASON_INSUFFICIENT_SYMBOLS, REASON_INSUFFICIENT_TIMEFRAMES}]
        assert breadth_reasons == []

    def test_multiple_reasons_deduplicated(self) -> None:
        report: dict[str, Any] = {
            "failures": [
                {"code": "STALE_MANIFEST_GENERATED_AT"},
                {"code": "STALE_MANIFEST_GENERATED_AT"},
            ],
        }
        reasons = diagnose_gate_failure(report)
        stale = [r for r in reasons if r["reason"] == REASON_STALE_DATA]
        assert len(stale) == 1


# ---------------------------------------------------------------------------
# Evidence coverage expectations
# ---------------------------------------------------------------------------

class TestEvidenceCoverage:
    def test_default_symbols_satisfy_coverage(self) -> None:
        assert len(RELEASE_REFERENCE_SYMBOLS) >= EVIDENCE_MIN_SYMBOL_COVERAGE

    def test_default_timeframes_satisfy_coverage(self) -> None:
        assert len(RELEASE_REFERENCE_TIMEFRAMES) >= EVIDENCE_MIN_TIMEFRAME_COVERAGE
