from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TV_SHARED = ROOT / "automation/tradingview/lib/tv_shared.ts"
TV_PREFLIGHT = ROOT / "scripts/tv_preflight.ts"
TV_STORAGE_CAPTURE = ROOT / "scripts/create_tradingview_storage_state.ts"
AUTH_MODES_DOC = ROOT / "docs/tradingview-auth-modes.md"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_page_auth_probe_emits_live_trace_line() -> None:
    source = _read(TV_SHARED)

    assert '"auth-state-probe"' in source
    assert "accountProbeStatuses=${statusSummary}" in source
    assert "accountProbeAuthenticated=${accountProbeAuthenticated}" in source
    assert "accountProbeAnonymous=${accountProbeAnonymous}" in source


def test_preflight_report_records_page_auth_probe_evidence() -> None:
    source = _read(TV_PREFLIGHT)

    assert "auth_reason: string | null;" in source
    assert "auth_probe_statuses: number[];" in source
    assert 'auth_reason: null' in source
    assert "targetResult.auth_reason = pageAuthState?.reason ?? \"auth_state_probe_failed\";" in source
    assert "targetResult.auth_probe_statuses = pageAuthState?.evidence.accountProbeStatuses ?? [];" in source


def test_storage_state_capture_persists_page_auth_probe_evidence() -> None:
    source = _read(TV_STORAGE_CAPTURE)

    assert "authProbeStatuses: number[];" in source
    assert "authProbeStatuses: pageAuthState?.evidence.accountProbeStatuses ?? []" in source
    assert "Auth probe statuses: ${probePreview}" in source
    assert "authProbeStatuses: authDiagnostics.authProbeStatuses" in source


def test_auth_modes_doc_mentions_probe_monitoring_fields() -> None:
    doc = _read(AUTH_MODES_DOC)

    assert "target-level `auth_reason`" in doc
    assert "target-level `auth_probe_statuses`" in doc
    assert "[tv-trace] auth-state-probe" in doc
