"""Smoke test for ``open_prep.feature_flags`` (audit-L-1 R4 SSOT).

Verifies the canonical readers behave as documented:

  * default-ON when env var unset
  * ``"0"`` disables
  * ``"1 "`` (trailing whitespace) is treated as enabled (lenient strip)
"""

from __future__ import annotations

import os

from open_prep.feature_flags import _bool_env, is_opra_uoa_enabled


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
