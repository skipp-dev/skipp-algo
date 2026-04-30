"""Tests for scripts.probe_providers preflight + notification logic.

Network is fully stubbed: every probe is replaced with a deterministic
in-memory function so the tests are hermetic and instant.
"""
from __future__ import annotations

import json
from unittest.mock import patch

import pytest

import scripts.probe_providers as pp

# ── Fixtures ────────────────────────────────────────────────────────


def _ok() -> tuple[str, str]:
    return ("OK", "fine")


def _warn() -> tuple[str, str]:
    return ("WARN", "stale")


def _fail() -> tuple[str, str]:
    return ("FAIL", "boom")


def _skip() -> tuple[str, str]:
    return ("SKIP", "no key")


def _raise() -> tuple[str, str]:
    raise RuntimeError("explosion")


# ── ProbeResult.is_blocking ─────────────────────────────────────────


def test_is_blocking_critical_non_ok():
    r = pp.ProbeResult("x", "FAIL", 1.0, "d", critical=True)
    assert r.is_blocking is True


def test_is_blocking_critical_ok():
    r = pp.ProbeResult("x", "OK", 1.0, "d", critical=True)
    assert r.is_blocking is False


def test_is_blocking_non_critical_fail():
    r = pp.ProbeResult("x", "FAIL", 1.0, "d", critical=False)
    assert r.is_blocking is False


@pytest.mark.parametrize("status", ["WARN", "SKIP", "FAIL"])
def test_is_blocking_critical_any_non_ok(status):
    r = pp.ProbeResult("x", status, 1.0, "d", critical=True)
    assert r.is_blocking is True


# ── run_probes / summarise ──────────────────────────────────────────


def test_run_probes_critical_only_filter():
    probes = [
        pp.Probe("crit", _ok, critical=True),
        pp.Probe("opt", _fail, critical=False),
    ]
    results = pp.run_probes(probes, critical_only=True, quiet=True)
    assert [r.name for r in results] == ["crit"]


def test_run_probes_quiet_suppresses_output(capsys):
    probes = [pp.Probe("crit", _ok, critical=True)]
    pp.run_probes(probes, quiet=True)
    assert capsys.readouterr().out == ""


def test_run_probes_pretty_emits_row(capsys):
    probes = [pp.Probe("crit", _ok, critical=True)]
    pp.run_probes(probes, quiet=False)
    out = capsys.readouterr().out
    assert "crit" in out
    assert "OK" in out


def test_run_probes_catches_exception_as_fail():
    probes = [pp.Probe("boom", _raise, critical=True)]
    [r] = pp.run_probes(probes, quiet=True)
    assert r.status == "FAIL"
    assert "RuntimeError" in r.detail
    assert r.is_blocking


def test_summarise_counts_blocking():
    results = [
        pp.ProbeResult("a", "OK", 1.0, "", critical=True),
        pp.ProbeResult("b", "WARN", 1.0, "", critical=True),
        pp.ProbeResult("c", "FAIL", 1.0, "", critical=False),
        pp.ProbeResult("d", "SKIP", 1.0, "", critical=True),
    ]
    counts = pp.summarise(results)
    assert counts["OK"] == 1
    assert counts["WARN"] == 1
    assert counts["FAIL"] == 1
    assert counts["SKIP"] == 1
    # b (WARN crit) + d (SKIP crit) — c is non-critical, doesn't count
    assert counts["BLOCKING"] == 2


# ── preflight_or_die ────────────────────────────────────────────────


def test_preflight_or_die_passes_when_all_critical_ok():
    probes = [
        pp.Probe("crit", _ok, critical=True),
        pp.Probe("opt", _fail, critical=False),
    ]
    with patch.object(pp, "PROBES", probes):
        results = pp.preflight_or_die(notify=False)
    assert all(r.status == "OK" for r in results if r.critical)


def test_preflight_or_die_raises_on_critical_fail():
    probes = [pp.Probe("crit", _fail, critical=True)]
    with patch.object(pp, "PROBES", probes), pytest.raises(SystemExit) as excinfo:
        pp.preflight_or_die(notify=False)
    assert excinfo.value.code == 1


def test_preflight_or_die_raise_on_block_false_returns_results():
    probes = [pp.Probe("crit", _fail, critical=True)]
    with patch.object(pp, "PROBES", probes):
        results = pp.preflight_or_die(notify=False, raise_on_block=False)
    assert len(results) == 1
    assert results[0].is_blocking


def test_preflight_or_die_optional_failure_does_not_block():
    probes = [
        pp.Probe("crit", _ok, critical=True),
        pp.Probe("opt", _fail, critical=False),
    ]
    with patch.object(pp, "PROBES", probes):
        results = pp.preflight_or_die(notify=False)  # must NOT raise
    statuses = {r.name: r.status for r in results}
    # critical_only filter drops the optional probe entirely from the result
    assert "opt" not in statuses
    assert statuses["crit"] == "OK"


def test_preflight_or_die_notify_called_on_failure():
    probes = [pp.Probe("crit", _fail, critical=True)]
    with patch.object(pp, "PROBES", probes), \
         patch.object(pp, "_notify_blocking") as mock_notify, pytest.raises(SystemExit):
        pp.preflight_or_die(notify=True)
    assert mock_notify.call_count == 1
    blocking_arg = mock_notify.call_args[0][0]
    assert len(blocking_arg) == 1
    assert blocking_arg[0].name == "crit"


def test_preflight_or_die_notify_skipped_when_disabled():
    probes = [pp.Probe("crit", _fail, critical=True)]
    with patch.object(pp, "PROBES", probes), \
         patch.object(pp, "_notify_blocking") as mock_notify, pytest.raises(SystemExit):
        pp.preflight_or_die(notify=False)
    mock_notify.assert_not_called()


def test_preflight_or_die_swallows_notification_failure():
    probes = [pp.Probe("crit", _fail, critical=True)]
    with (
        patch.object(pp, "PROBES", probes),
        patch.object(pp, "_notify_blocking", side_effect=RuntimeError("net down")),
        pytest.raises(SystemExit) as excinfo,
    ):
        # must still raise SystemExit, NOT the notification RuntimeError
        pp.preflight_or_die(notify=True)
    assert excinfo.value.code == 1


# ── _format_alert ───────────────────────────────────────────────────


def test_format_alert_includes_each_failure():
    blocking = [
        pp.ProbeResult("FMP /quote", "FAIL", 250.0, "HTTP 500", critical=True),
        pp.ProbeResult("Databento ohlcv", "WARN", 100.0, "empty", critical=True),
    ]
    title, body = pp._format_alert(blocking)
    assert "2 provider(s) down" in title
    assert "FMP /quote" in body
    assert "HTTP 500" in body
    assert "Databento ohlcv" in body
    assert "empty" in body


def test_format_alert_appends_databento_status_page():
    blocking = [
        pp.ProbeResult("Databento ohlcv-1d", "WARN", 100.0, "empty", critical=True),
    ]
    _, body = pp._format_alert(blocking)
    assert "Provider status pages:" in body
    assert "https://status.databento.com/" in body


def test_format_alert_dedupes_status_pages():
    blocking = [
        pp.ProbeResult("Databento metadata", "FAIL", 100.0, "503", critical=True),
        pp.ProbeResult("Databento ohlcv-1d", "WARN", 100.0, "empty", critical=True),
    ]
    _, body = pp._format_alert(blocking)
    # status.databento.com should appear exactly once even with two failures
    assert body.count("https://status.databento.com/") == 1


def test_format_alert_multiple_providers_get_multiple_status_pages():
    blocking = [
        pp.ProbeResult("FMP /quote", "FAIL", 100.0, "500", critical=True),
        pp.ProbeResult("Databento metadata", "FAIL", 100.0, "503", critical=True),
        pp.ProbeResult("OpenAI /v1/models", "FAIL", 100.0, "500", critical=True),
    ]
    _, body = pp._format_alert(blocking)
    assert "https://status.financialmodelingprep.com/" in body
    assert "https://status.databento.com/" in body
    assert "https://status.openai.com/" in body


def test_format_alert_omits_status_pages_section_when_unknown_provider():
    blocking = [
        pp.ProbeResult("SomeUnmapped service", "FAIL", 100.0, "x", critical=True),
    ]
    _, body = pp._format_alert(blocking)
    assert "Provider status pages:" not in body


def test_status_pages_for_preserves_first_seen_order():
    blocking = [
        pp.ProbeResult("Databento x", "FAIL", 1.0, "", critical=True),
        pp.ProbeResult("FMP y", "FAIL", 1.0, "", critical=True),
        pp.ProbeResult("Databento z", "FAIL", 1.0, "", critical=True),
    ]
    pages = pp._status_pages_for(blocking)
    assert pages == [
        "https://status.databento.com/",
        "https://status.financialmodelingprep.com/",
    ]


# ── _notify_blocking ────────────────────────────────────────────────


def test_notify_blocking_no_channels_configured(monkeypatch, caplog):
    """When no TERMINAL_* env is set, dispatch is a silent no-op."""
    for var in (
        "TERMINAL_TELEGRAM_BOT_TOKEN",
        "TERMINAL_TELEGRAM_CHAT_ID",
        "TERMINAL_DISCORD_WEBHOOK_URL",
        "TERMINAL_PUSHOVER_APP_TOKEN",
        "TERMINAL_PUSHOVER_USER_KEY",
    ):
        monkeypatch.delenv(var, raising=False)
    blocking = [pp.ProbeResult("x", "FAIL", 1.0, "d", critical=True)]
    pp._notify_blocking(blocking)  # should not raise


def test_notify_blocking_dispatches_to_configured_channels(monkeypatch):
    monkeypatch.setenv("TERMINAL_TELEGRAM_BOT_TOKEN", "tok")
    monkeypatch.setenv("TERMINAL_TELEGRAM_CHAT_ID", "chat")
    monkeypatch.setenv("TERMINAL_DISCORD_WEBHOOK_URL", "https://discord.com/api/webhooks/1/abc")
    monkeypatch.delenv("TERMINAL_PUSHOVER_APP_TOKEN", raising=False)
    monkeypatch.delenv("TERMINAL_PUSHOVER_USER_KEY", raising=False)

    blocking = [pp.ProbeResult("x", "FAIL", 1.0, "d", critical=True)]
    with patch("terminal_notifications._send_telegram", return_value=True) as tg, \
         patch("terminal_notifications._send_discord", return_value=True) as dc, \
         patch("terminal_notifications._send_pushover", return_value=True) as po:
        pp._notify_blocking(blocking)
    assert tg.call_count == 1
    assert dc.call_count == 1
    assert po.call_count == 0


# ── CLI ─────────────────────────────────────────────────────────────


def test_main_preflight_returns_0_on_all_ok(capsys):
    probes = [pp.Probe("crit", _ok, critical=True)]
    with patch.object(pp, "PROBES", probes):
        rc = pp.main(["--preflight"])
    assert rc == 0


def test_main_preflight_returns_1_on_blocking(capsys):
    probes = [pp.Probe("crit", _fail, critical=True)]
    with patch.object(pp, "PROBES", probes):
        rc = pp.main(["--preflight"])
    assert rc == 1


def test_main_default_mode_returns_0_when_only_warn(capsys):
    """Default mode (no --preflight) should NOT fail on WARN."""
    probes = [pp.Probe("opt", _warn, critical=False)]
    with patch.object(pp, "PROBES", probes):
        rc = pp.main([])
    assert rc == 0


def test_main_default_mode_returns_1_on_fail(capsys):
    probes = [pp.Probe("opt", _fail, critical=False)]
    with patch.object(pp, "PROBES", probes):
        rc = pp.main([])
    assert rc == 1


def test_main_json_emits_machine_readable(capsys):
    probes = [
        pp.Probe("a", _ok, critical=True),
        pp.Probe("b", _fail, critical=False),
    ]
    with patch.object(pp, "PROBES", probes):
        rc = pp.main(["--json"])
    assert rc == 1
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert "results" in payload
    assert "counts" in payload
    names = [r["name"] for r in payload["results"]]
    assert names == ["a", "b"]
    assert payload["counts"]["OK"] == 1
    assert payload["counts"]["FAIL"] == 1


def test_main_json_preflight_filters_critical(capsys):
    probes = [
        pp.Probe("a", _ok, critical=True),
        pp.Probe("b", _fail, critical=False),
    ]
    with patch.object(pp, "PROBES", probes):
        rc = pp.main(["--json", "--preflight"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert [r["name"] for r in payload["results"]] == ["a"]


def test_main_notify_invoked_only_on_blocking(capsys):
    probes = [pp.Probe("crit", _ok, critical=True)]
    with patch.object(pp, "PROBES", probes), \
         patch.object(pp, "_notify_blocking") as mock_notify:
        pp.main(["--preflight", "--notify"])
    mock_notify.assert_not_called()

    probes = [pp.Probe("crit", _fail, critical=True)]
    with patch.object(pp, "PROBES", probes), \
         patch.object(pp, "_notify_blocking") as mock_notify:
        pp.main(["--preflight", "--notify"])
    mock_notify.assert_called_once()
