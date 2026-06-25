"""Tests for smc_core.smt_divergence (Phase E — SMT/Correlation scaffold).

Covers:
- ``KNOWN_SMT_PAIRS`` contains the four canonical pairs
- ``SMTPair`` is a NamedTuple with ``base_symbol`` and ``corr_symbol``
- ``classify_smt_divergence`` raises ``NotImplementedError`` (scaffold)
- ``SMTDivergenceResult`` is a frozen dataclass with all expected fields
"""

from __future__ import annotations

import pytest

from smc_core.smt_divergence import (
    KNOWN_SMT_PAIRS,
    SMTDivergenceResult,
    SMTPair,
    classify_smt_divergence,
)

# ---------------------------------------------------------------------------
# Known pairs
# ---------------------------------------------------------------------------


class TestKnownPairs:
    def test_four_pairs_defined(self) -> None:
        assert len(KNOWN_SMT_PAIRS) == 4

    @pytest.mark.parametrize("pair", [
        SMTPair("XAUUSD", "XAGUSD"),
        SMTPair("BTCUSD", "ETHUSD"),
        SMTPair("US100", "US500"),
        SMTPair("EURUSD", "GBPUSD"),
    ])
    def test_expected_pair_present(self, pair: SMTPair) -> None:
        assert pair in KNOWN_SMT_PAIRS

    def test_smt_pair_has_base_and_corr_fields(self) -> None:
        pair = KNOWN_SMT_PAIRS[0]
        assert hasattr(pair, "base_symbol")
        assert hasattr(pair, "corr_symbol")
        assert isinstance(pair.base_symbol, str)
        assert isinstance(pair.corr_symbol, str)


# ---------------------------------------------------------------------------
# Scaffold — NotImplementedError
# ---------------------------------------------------------------------------


def test_classify_smt_divergence_raises_not_implemented() -> None:
    with pytest.raises(NotImplementedError):
        classify_smt_divergence(
            base_symbol="XAUUSD",
            corr_symbol="XAGUSD",
            base_bars=object(),
            corr_bars=object(),
        )


def test_error_message_mentions_phase_e0() -> None:
    with pytest.raises(NotImplementedError, match=r"Phase E\.0"):
        classify_smt_divergence(
            base_symbol="BTCUSD",
            corr_symbol="ETHUSD",
            base_bars=None,
            corr_bars=None,
        )


# ---------------------------------------------------------------------------
# SMTDivergenceResult field existence
# ---------------------------------------------------------------------------


def test_smt_divergence_result_has_expected_fields() -> None:
    result = SMTDivergenceResult(
        pair_corr_window=20,
        pair_corr_value=0.87,
        smt_high_divergence=True,
        smt_low_divergence=False,
        smt_strength=0.75,
    )
    assert result.pair_corr_window == 20
    assert result.pair_corr_value == pytest.approx(0.87)
    assert result.smt_high_divergence is True
    assert result.smt_low_divergence is False
    assert result.smt_strength == pytest.approx(0.75)


def test_smt_divergence_result_is_frozen() -> None:
    result = SMTDivergenceResult(
        pair_corr_window=20,
        pair_corr_value=0.87,
        smt_high_divergence=False,
        smt_low_divergence=False,
        smt_strength=0.5,
    )
    with pytest.raises((AttributeError, TypeError)):
        result.smt_strength = 0.9  # type: ignore[misc]
