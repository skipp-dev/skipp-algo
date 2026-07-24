"""M1: a hot Unemployment Rate print (higher unemployment = weaker labor) must
LOWER macro_bias (risk-off), matching jobless_claims — not raise it.

`unemployment_rate` was missing from the risk-off orientation list in
`_macro_orientation`, so it fell through to the +1.0 growth default: a
jobs-Friday unemployment miss pushed macro_bias risk-ON. macro_bias feeds
classify_regime AND the v2 scorer (macro_component / risk_off_penalty / the
macro_bias_short / macro_risk_off_extreme filter gates), so the sign is
trade-affecting. open_prep.macro is the production copy; scripts.smc_macro_bias
is a verbatim duplicate consumed by scripts/smc_provider_policy.py — both must
agree.
"""
from __future__ import annotations

import pytest

import open_prep.macro as open_prep_macro
import scripts.smc_macro_bias as scripts_macro

_MODULES = [open_prep_macro, scripts_macro]
_IDS = ["open_prep.macro", "scripts.smc_macro_bias"]


def _us_high(event: str, actual: float, consensus: float) -> dict:
    return {
        "event": event, "country": "US", "impact": "High",
        "actual": actual, "consensus": consensus, "date": "2026-07-24",
    }


@pytest.mark.parametrize("mod", _MODULES, ids=_IDS)
def test_hot_unemployment_rate_is_risk_off(mod) -> None:
    # 4.5% vs 4.1% consensus = worse labor -> risk-off (negative bias).
    bias = mod.macro_bias_with_components([_us_high("Unemployment Rate", 4.5, 4.1)])["macro_bias"]
    assert bias < 0, f"{mod.__name__}: hot unemployment must be risk-off, got {bias}"


@pytest.mark.parametrize("mod", _MODULES, ids=_IDS)
def test_unemployment_matches_jobless_claims_sign(mod) -> None:
    # Both are "higher = weaker labor"; their bias signs must agree (and be risk-off).
    unemp = mod.macro_bias_with_components([_us_high("Unemployment Rate", 4.5, 4.1)])["macro_bias"]
    claims = mod.macro_bias_with_components([_us_high("Initial Jobless Claims", 260000, 230000)])["macro_bias"]
    assert unemp < 0 and (unemp < 0) == (claims < 0)


@pytest.mark.parametrize("mod", _MODULES, ids=_IDS)
def test_hot_nfp_still_risk_on_control(mod) -> None:
    # Control (guards against over-correction): stronger payrolls stay risk-on.
    bias = mod.macro_bias_with_components([_us_high("Nonfarm Payrolls", 300000, 180000)])["macro_bias"]
    assert bias > 0
