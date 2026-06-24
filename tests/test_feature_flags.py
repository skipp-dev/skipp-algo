"""Smoke test for ``open_prep.feature_flags`` (audit-L-1 R4 SSOT).

Verifies the canonical readers behave as documented:

  * default-ON when env var unset
  * ``"0"`` disables
  * ``"1 "`` (trailing whitespace) is treated as enabled (lenient strip)
"""

from __future__ import annotations

import os

from open_prep.feature_flags import (
    _bool_env,
    any_v2_feature_enabled,
    is_confluence_score_enabled,
    is_freshness_v2_enabled,
    is_opra_uoa_enabled,
    is_reaction_zone_enabled,
    is_smt_divergence_enabled,
    is_sweep_trap_enabled,
    signal_quality_model,
)


def _isolated(name: str):
    """Context guard that removes ``name`` from os.environ on enter+exit."""

    class _Guard:
        def __enter__(self) -> None:
            self._prev = os.environ.pop(name, None)

        def __exit__(self, *exc: object) -> None:
            os.environ.pop(name, None)
            if self._prev is not None:
                os.environ[name] = self._prev

    return _Guard()


def test_is_opra_uoa_enabled_default_on() -> None:
    with _isolated("ENABLE_OPRA_UOA"):
        assert is_opra_uoa_enabled() is True


def test_is_opra_uoa_enabled_explicit_zero() -> None:
    with _isolated("ENABLE_OPRA_UOA"):
        os.environ["ENABLE_OPRA_UOA"] = "0"
        assert is_opra_uoa_enabled() is False


def test_is_opra_uoa_enabled_strips_trailing_whitespace() -> None:
    with _isolated("ENABLE_OPRA_UOA"):
        os.environ["ENABLE_OPRA_UOA"] = "1 "
        assert is_opra_uoa_enabled() is True


def test_is_opra_uoa_enabled_strips_leading_whitespace() -> None:
    with _isolated("ENABLE_OPRA_UOA"):
        os.environ["ENABLE_OPRA_UOA"] = "\t1\n"
        assert is_opra_uoa_enabled() is True


def test_is_opra_uoa_enabled_other_value_disables() -> None:
    with _isolated("ENABLE_OPRA_UOA"):
        os.environ["ENABLE_OPRA_UOA"] = "true"
        assert is_opra_uoa_enabled() is False


def test_bool_env_respects_default_param() -> None:
    with _isolated("UNSET_FLAG_X"):
        assert _bool_env("UNSET_FLAG_X", "0") is False
        assert _bool_env("UNSET_FLAG_X", "1") is True


def test_config_consumes_ssot() -> None:
    """``newsstack_fmp.config.Config`` reads ENABLE_OPRA_UOA via the SSOT."""

    from newsstack_fmp.config import Config

    with _isolated("ENABLE_OPRA_UOA"):
        assert Config().enable_opra_uoa is True
        os.environ["ENABLE_OPRA_UOA"] = "0"
        assert Config().enable_opra_uoa is False


def test_smc_v2_flags_default_off() -> None:
    for name in (
        "ENABLE_SWEEP_TRAP",
        "ENABLE_REACTION_ZONE",
        "ENABLE_CONFLUENCE_SCORE",
        "ENABLE_FRESHNESS_V2",
        "ENABLE_SMT_DIVERGENCE",
    ):
        with _isolated(name):
            assert _bool_env(name, "0") is False


def test_smc_v2_flags_explicit_on() -> None:
    for name, fn in (
        ("ENABLE_SWEEP_TRAP", is_sweep_trap_enabled),
        ("ENABLE_REACTION_ZONE", is_reaction_zone_enabled),
        ("ENABLE_CONFLUENCE_SCORE", is_confluence_score_enabled),
        ("ENABLE_FRESHNESS_V2", is_freshness_v2_enabled),
        ("ENABLE_SMT_DIVERGENCE", is_smt_divergence_enabled),
    ):
        with _isolated(name):
            os.environ[name] = "1"
            assert fn() is True


def test_signal_quality_model_default_v1() -> None:
    with _isolated("SIGNAL_QUALITY_MODEL"):
        assert signal_quality_model() == "v1"


def test_signal_quality_model_normalized() -> None:
    with _isolated("SIGNAL_QUALITY_MODEL"):
        os.environ["SIGNAL_QUALITY_MODEL"] = " V2 "
        assert signal_quality_model() == "v2"


def test_signal_quality_model_empty_fallback() -> None:
    with _isolated("SIGNAL_QUALITY_MODEL"):
        os.environ["SIGNAL_QUALITY_MODEL"] = "  "
        assert signal_quality_model() == "v1"


def test_signal_quality_model_unknown_fallback() -> None:
    with _isolated("SIGNAL_QUALITY_MODEL"):
        os.environ["SIGNAL_QUALITY_MODEL"] = "v3"
        assert signal_quality_model() == "v1"


def test_any_v2_feature_enabled_default_false() -> None:
    assert any_v2_feature_enabled() is False


def test_any_v2_feature_enabled_true_when_one_on() -> None:
    with _isolated("ENABLE_CONFLUENCE_SCORE"):
        os.environ["ENABLE_CONFLUENCE_SCORE"] = "1"
        assert any_v2_feature_enabled() is True
