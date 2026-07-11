"""ENG-WS2-02 wire (truth-audit 2026-07-11): derive the Pine trust_state from
the enrichment's own per-domain provider diagnostics.

Before this, ``attach_trust_state_to_enrichment`` had no production caller, so
the Pine export always used the HEALTHY / stale_providers->STALE fallback.
``attach_trust_state_from_provider_diagnostics`` now derives the real state
from ``providers.domain_diagnostics`` (regime/news/calendar/technical) + the
legacy ``stale_providers`` list, without ever downgrading the fallback.
"""
from __future__ import annotations

from scripts.smc_trust_state_export import (
    attach_trust_state_from_provider_diagnostics,
)


def _enr(diags: dict | None = None, stale: str = "") -> dict:
    providers: dict = {"stale_providers": stale}
    if diags is not None:
        providers["domain_diagnostics"] = diags
    return {"providers": providers}


def test_all_ok_domains_yield_healthy() -> None:
    enr = _enr({"technical": {"provider_status": "ok"}, "news": {"provider_status": "ok"}})
    attach_trust_state_from_provider_diagnostics(enr)
    assert enr["trust_state"]["state"] == "healthy"


def test_technical_stale_yields_stale() -> None:
    # technical/stale -> ADVISORY + stale -> STALE.
    enr = _enr({"technical": {"provider_status": "stale", "status_detail": "old bars"}})
    attach_trust_state_from_provider_diagnostics(enr)
    ts = enr["trust_state"]
    assert ts["state"] == "stale"
    assert ts["action_impact"] == "advisory_only"


def test_structure_stale_yields_watch_only_when_present() -> None:
    # Proves the derivation is already correct for a structure domain, so the
    # moment a structure-provider-health source is added to domain_diagnostics
    # WATCH_ONLY fires. structure/stale -> SUPPRESS -> WATCH_ONLY.
    enr = _enr({"structure": {"provider_status": "stale", "status_detail": "manifest 30h old"}})
    attach_trust_state_from_provider_diagnostics(enr)
    assert enr["trust_state"]["state"] == "watch_only"


def test_structure_missing_yields_unavailable_when_present() -> None:
    enr = _enr({"structure": {"provider_status": "missing"}})
    attach_trust_state_from_provider_diagnostics(enr)
    assert enr["trust_state"]["state"] == "unavailable"


def test_stale_providers_only_still_stale_no_regression() -> None:
    # domain_diagnostics present but all-ok, yet stale_providers non-empty:
    # must still be STALE (folded in as an advisory-stale alert), matching the
    # old _fallback_trust_block behaviour.
    enr = _enr({"technical": {"provider_status": "ok"}}, stale="databento,fmp")
    attach_trust_state_from_provider_diagnostics(enr)
    assert enr["trust_state"]["state"] == "stale"


def test_existing_trust_state_is_preserved() -> None:
    enr = _enr({"technical": {"provider_status": "stale"}})
    enr["trust_state"] = {"state": "unavailable"}  # set upstream
    attach_trust_state_from_provider_diagnostics(enr)
    assert enr["trust_state"] == {"state": "unavailable"}  # untouched


def test_no_domain_diagnostics_leaves_trust_state_unset() -> None:
    # Legacy enrichment without domain_diagnostics -> fallback path handles it.
    enr = _enr(diags=None, stale="databento")
    attach_trust_state_from_provider_diagnostics(enr)
    assert "trust_state" not in enr
