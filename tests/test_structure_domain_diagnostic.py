"""Truth-audit 2026-07-11 (ENG-WS2 follow-up): the micro-base pipeline now
diagnoses the STRUCTURE domain from the base snapshot's presence + freshness,
so the trust-ladder's WATCH_ONLY / UNAVAILABLE states finally fire end-to-end.

Before this, only regime/news/calendar/technical were diagnosed, so
attach_trust_state_from_provider_diagnostics could only reach DEGRADED/STALE.
"""
from __future__ import annotations

from datetime import date

from scripts.generate_smc_micro_base_from_databento import (
    build_structure_domain_diagnostic,
)
from scripts.smc_trust_state_export import (
    attach_trust_state_from_provider_diagnostics,
)

_TODAY = date(2026, 7, 13)  # a Monday


def test_empty_base_is_missing() -> None:
    d = build_structure_domain_diagnostic("2026-07-10", symbol_count=0, now_date=_TODAY)
    assert d["provider_status"] == "missing"
    assert d["domain"] == "structure"


def test_no_asof_is_missing() -> None:
    d = build_structure_domain_diagnostic(None, symbol_count=5, now_date=_TODAY)
    assert d["provider_status"] == "missing"


def test_fresh_asof_is_ok() -> None:
    # Friday 2026-07-10 vs Monday 2026-07-13 = 3 days, within the default 4d window.
    d = build_structure_domain_diagnostic("2026-07-10", symbol_count=5, now_date=_TODAY)
    assert d["provider_status"] == "ok"


def test_stale_asof_is_stale() -> None:
    d = build_structure_domain_diagnostic("2026-06-30", symbol_count=5, now_date=_TODAY)
    assert d["provider_status"] == "stale"
    assert "old" in d["status_detail"]


def test_env_override_threshold(monkeypatch) -> None:
    monkeypatch.setenv("SMC_STRUCTURE_SNAPSHOT_STALE_AFTER_DAYS", "1")
    # 3 days old now exceeds the 1-day window.
    d = build_structure_domain_diagnostic("2026-07-10", symbol_count=5, now_date=_TODAY)
    assert d["provider_status"] == "stale"


# ── End-to-end: structure diagnostic → trust_state (the whole point) ──


def _enr_with_structure(status: str) -> dict:
    return {
        "providers": {
            "stale_providers": "",
            "domain_diagnostics": {
                "technical": {"provider_status": "ok"},
                "structure": {"provider_status": status, "status_detail": "x"},
            },
        }
    }


def test_structure_missing_yields_unavailable_end_to_end() -> None:
    enr = _enr_with_structure("missing")
    attach_trust_state_from_provider_diagnostics(enr)
    assert enr["trust_state"]["state"] == "unavailable"


def test_structure_stale_yields_watch_only_end_to_end() -> None:
    enr = _enr_with_structure("stale")
    attach_trust_state_from_provider_diagnostics(enr)
    assert enr["trust_state"]["state"] == "watch_only"


def test_structure_ok_yields_healthy_end_to_end() -> None:
    enr = _enr_with_structure("ok")
    attach_trust_state_from_provider_diagnostics(enr)
    assert enr["trust_state"]["state"] == "healthy"


def test_structure_stale_renders_watch_only_in_pine() -> None:
    # Full render path (the Pine-side validation): a stale structure diagnostic
    # must surface as TRUST_STATE = "watch_only" in the exported Pine lines,
    # with action_impact "no_new_entries".
    from scripts.smc_trust_state_export import render_trust_block_lines

    enr = _enr_with_structure("stale")
    attach_trust_state_from_provider_diagnostics(enr)
    lines = render_trust_block_lines(enr)
    joined = "\n".join(lines)
    assert 'TRUST_STATE = "watch_only"' in joined
    assert 'TRUST_ACTION_IMPACT = "no_new_entries"' in joined
    assert 'TRUST_CAUSE_DOMAIN = "structure"' in joined


def test_structure_missing_renders_unavailable_in_pine() -> None:
    from scripts.smc_trust_state_export import render_trust_block_lines

    enr = _enr_with_structure("missing")
    attach_trust_state_from_provider_diagnostics(enr)
    joined = "\n".join(render_trust_block_lines(enr))
    assert 'TRUST_STATE = "unavailable"' in joined
    assert 'TRUST_CAUSE_DOMAIN = "structure"' in joined
