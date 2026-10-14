"""Property invariants for ``smc_adapters.regime_bridge``.

Pins the documented adapter contract between an optional Open-Prep
``RegimeSnapshot`` (dict or object) and the local ``MarketRegimeContext``.
Pure-stdlib, fast, no production changes.
"""
from __future__ import annotations

from dataclasses import FrozenInstanceError, dataclass

import pytest

from smc_adapters.regime_bridge import _VALID_REGIMES, regime_snapshot_to_context
from smc_core.types import MarketRegimeContext

VALID_REGIMES = ("RISK_ON", "RISK_OFF", "ROTATION", "NEUTRAL")


class TestValidRegimeConstant:
    def test_exact_membership(self) -> None:
        assert set(VALID_REGIMES) == _VALID_REGIMES

    def test_size_pinned(self) -> None:
        assert len(_VALID_REGIMES) == 4

    def test_is_set(self) -> None:
        assert isinstance(_VALID_REGIMES, set)


class TestNoneInput:
    def test_none_returns_none(self) -> None:
        assert regime_snapshot_to_context(None) is None


class TestDictForm:
    @pytest.mark.parametrize("regime", VALID_REGIMES)
    def test_each_valid_regime_accepted(self, regime: str) -> None:
        ctx = regime_snapshot_to_context({"regime": regime})
        assert ctx is not None
        assert ctx.regime == regime

    @pytest.mark.parametrize("regime", VALID_REGIMES)
    def test_lowercase_regime_normalised_via_upper(self, regime: str) -> None:
        ctx = regime_snapshot_to_context({"regime": regime.lower()})
        assert ctx is not None
        assert ctx.regime == regime

    @pytest.mark.parametrize("regime", VALID_REGIMES)
    def test_mixed_case_regime_normalised(self, regime: str) -> None:
        mixed = "".join(c.lower() if i % 2 else c for i, c in enumerate(regime))
        ctx = regime_snapshot_to_context({"regime": mixed})
        assert ctx is not None
        assert ctx.regime == regime

    @pytest.mark.parametrize(
        "bad",
        [
            "",
            "UNKNOWN",
            "risk on",
            "RISK-ON",
            "RISK_ONN",
            "NEUTRA",
            "BULL",
            "BEAR",
        ],
    )
    def test_invalid_regime_string_returns_none(self, bad: str) -> None:
        assert regime_snapshot_to_context({"regime": bad}) is None

    def test_missing_regime_key_returns_none(self) -> None:
        assert regime_snapshot_to_context({}) is None

    def test_breadth_defaults_to_half_when_missing(self) -> None:
        ctx = regime_snapshot_to_context({"regime": "RISK_ON"})
        assert ctx is not None
        assert ctx.sector_breadth == 0.5

    def test_vix_defaults_to_none_when_missing(self) -> None:
        ctx = regime_snapshot_to_context({"regime": "RISK_ON"})
        assert ctx is not None
        assert ctx.vix_level is None

    def test_explicit_vix_none_preserved(self) -> None:
        ctx = regime_snapshot_to_context({"regime": "RISK_ON", "vix_level": None})
        assert ctx is not None
        assert ctx.vix_level is None

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            (14.0, 14.0),
            (14, 14.0),
            (0, 0.0),
            (0.0, 0.0),
            (99.5, 99.5),
        ],
    )
    def test_vix_coerced_to_float(self, raw: float, expected: float) -> None:
        ctx = regime_snapshot_to_context({"regime": "RISK_ON", "vix_level": raw})
        assert ctx is not None
        assert ctx.vix_level == expected
        assert isinstance(ctx.vix_level, float)

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            (0.0, 0.0),
            (1, 1.0),
            (0.25, 0.25),
            (0.999, 0.999),
        ],
    )
    def test_breadth_coerced_to_float(self, raw: float, expected: float) -> None:
        ctx = regime_snapshot_to_context(
            {"regime": "ROTATION", "sector_breadth": raw}
        )
        assert ctx is not None
        assert ctx.sector_breadth == expected
        assert isinstance(ctx.sector_breadth, float)

    def test_extra_keys_ignored(self) -> None:
        ctx = regime_snapshot_to_context(
            {
                "regime": "NEUTRAL",
                "vix_level": 17.0,
                "sector_breadth": 0.4,
                "extra": "ignored",
                "another": 42,
            }
        )
        assert ctx is not None
        assert ctx.regime == "NEUTRAL"
        assert ctx.vix_level == 17.0
        assert ctx.sector_breadth == 0.4

    def test_input_dict_not_mutated(self) -> None:
        payload = {"regime": "risk_on", "vix_level": 12.0, "sector_breadth": 0.7}
        snapshot = dict(payload)
        regime_snapshot_to_context(snapshot)
        assert snapshot == payload

    def test_determinism_same_input_same_output(self) -> None:
        payload = {"regime": "RISK_OFF", "vix_level": 28.0, "sector_breadth": 0.2}
        a = regime_snapshot_to_context(dict(payload))
        b = regime_snapshot_to_context(dict(payload))
        assert a == b

    def test_returns_market_regime_context_instance(self) -> None:
        ctx = regime_snapshot_to_context({"regime": "NEUTRAL"})
        assert isinstance(ctx, MarketRegimeContext)


class TestObjectForm:
    @pytest.mark.parametrize("regime", VALID_REGIMES)
    def test_each_valid_regime_accepted(self, regime: str) -> None:
        @dataclass
        class _Snap:
            regime: str
            vix_level: float | None = None
            sector_breadth: float = 0.5

        ctx = regime_snapshot_to_context(_Snap(regime=regime))
        assert ctx is not None
        assert ctx.regime == regime

    @pytest.mark.parametrize("regime", VALID_REGIMES)
    def test_lowercase_regime_normalised(self, regime: str) -> None:
        class _Snap:
            pass

        snap = _Snap()
        snap.regime = regime.lower()  # type: ignore[attr-defined]
        ctx = regime_snapshot_to_context(snap)
        assert ctx is not None
        assert ctx.regime == regime

    def test_missing_regime_attr_returns_none(self) -> None:
        class _Snap:
            pass

        assert regime_snapshot_to_context(_Snap()) is None

    def test_invalid_regime_attr_returns_none(self) -> None:
        class _Snap:
            regime = "MAYBE"

        assert regime_snapshot_to_context(_Snap()) is None

    def test_breadth_defaults_to_half_when_missing(self) -> None:
        class _Snap:
            regime = "RISK_ON"

        ctx = regime_snapshot_to_context(_Snap())
        assert ctx is not None
        assert ctx.sector_breadth == 0.5

    def test_vix_defaults_to_none_when_missing(self) -> None:
        class _Snap:
            regime = "RISK_ON"

        ctx = regime_snapshot_to_context(_Snap())
        assert ctx is not None
        assert ctx.vix_level is None

    def test_vix_coerced_to_float(self) -> None:
        class _Snap:
            regime = "RISK_OFF"
            vix_level = 30  # int
            sector_breadth = 0.3

        ctx = regime_snapshot_to_context(_Snap())
        assert ctx is not None
        assert ctx.vix_level == 30.0
        assert isinstance(ctx.vix_level, float)

    def test_breadth_coerced_to_float(self) -> None:
        class _Snap:
            regime = "ROTATION"
            sector_breadth = 1  # int

        ctx = regime_snapshot_to_context(_Snap())
        assert ctx is not None
        assert ctx.sector_breadth == 1.0
        assert isinstance(ctx.sector_breadth, float)

    def test_returns_market_regime_context_instance(self) -> None:
        class _Snap:
            regime = "NEUTRAL"

        ctx = regime_snapshot_to_context(_Snap())
        assert isinstance(ctx, MarketRegimeContext)

    def test_dict_takes_dict_branch_not_object(self) -> None:
        """Subclasses of dict still hit the dict branch."""

        class _DictSub(dict):
            regime = "IGNORED_VIA_ATTR"

        snap = _DictSub({"regime": "RISK_ON"})
        ctx = regime_snapshot_to_context(snap)
        assert ctx is not None
        assert ctx.regime == "RISK_ON"


class TestReturnedContextIsFrozen:
    def test_cannot_mutate_regime(self) -> None:
        ctx = regime_snapshot_to_context({"regime": "RISK_ON"})
        assert ctx is not None
        with pytest.raises(FrozenInstanceError):
            ctx.regime = "RISK_OFF"  # type: ignore[misc]

    def test_cannot_mutate_vix(self) -> None:
        ctx = regime_snapshot_to_context({"regime": "RISK_ON", "vix_level": 14.0})
        assert ctx is not None
        with pytest.raises(FrozenInstanceError):
            ctx.vix_level = 99.0  # type: ignore[misc]
