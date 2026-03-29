"""Tests for scripts/smc_alert_notifier.py — v5 event-risk aware alert rules + suppression."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from scripts.smc_alert_notifier import (
    RULE_EVENT_COOLDOWN_END,
    RULE_EVENT_COOLDOWN_START,
    RULE_EVENT_INCOMING,
    RULE_EVENT_MARKET_BLOCKED,
    RULE_EVENT_RELEASE,
    RULE_EVENT_SYMBOL_BLOCKED,
    RULE_IMBALANCE_SHIFT,
    RULE_MACRO_EVENT,
    RULE_PROVIDER_DEGRADED,
    RULE_RANGE_BREAKOUT,
    RULE_RISK_OFF,
    RULE_SENTIMENT_SHIFT,
    RULE_SESSION_CONTEXT_SHIFT,
    RULE_STRUCTURE_SHIFT,
    RULE_TRADE_BLOCKED,
    _format_message,
    _parse_pine_exports,
    evaluate_alerts,
    load_previous_fingerprint,
    read_library_state,
    save_fingerprint,
    suppress_duplicates,
)


# ── Fixtures ──────────────────────────────────────────────────────

def _pine_content(**overrides: str) -> str:
    """Build a minimal Pine library string with exported constants."""
    defaults = {
        "MARKET_REGIME": "NEUTRAL",
        "VIX_LEVEL": "18.5",
        "SECTOR_BREADTH": "0.6",
        "HIGH_IMPACT_MACRO_TODAY": "false",
        "MACRO_EVENT_NAME": "",
        "MACRO_EVENT_TIME": "",
        "TRADE_STATE": "ALLOWED",
        "TONE": "NEUTRAL",
        "GLOBAL_HEAT": "0.3",
        "PROVIDER_COUNT": "3",
        "STALE_PROVIDERS": "",
        "EVENT_WINDOW_STATE": "CLEAR",
        "EVENT_RISK_LEVEL": "NONE",
        "NEXT_EVENT_NAME": "",
        "NEXT_EVENT_TIME": "",
        "NEXT_EVENT_IMPACT": "NONE",
        "MARKET_EVENT_BLOCKED": "false",
        "SYMBOL_EVENT_BLOCKED": "false",
        "EVENT_COOLDOWN_ACTIVE": "false",
        "EARNINGS_SOON_TICKERS": "",
    }
    defaults.update(overrides)
    lines = ['//@version=6', 'library("smc_micro_profiles_generated")', ""]
    for key, val in defaults.items():
        # Determine Pine type
        if val in ("true", "false"):
            lines.append(f'export const bool {key} = {val}')
        elif val.replace(".", "", 1).replace("-", "", 1).isdigit():
            if "." in val:
                lines.append(f'export const float {key} = {val}')
            else:
                lines.append(f'export const int {key} = {val}')
        else:
            lines.append(f'export const string {key} = "{val}"')
    return "\n".join(lines) + "\n"


def _state_from(**overrides: str) -> dict[str, str]:
    defaults = {
        "MARKET_REGIME": "NEUTRAL",
        "VIX_LEVEL": "18.5",
        "SECTOR_BREADTH": "0.6",
        "HIGH_IMPACT_MACRO_TODAY": "false",
        "MACRO_EVENT_NAME": "",
        "MACRO_EVENT_TIME": "",
        "TRADE_STATE": "ALLOWED",
        "TONE": "NEUTRAL",
        "GLOBAL_HEAT": "0.3",
        "PROVIDER_COUNT": "3",
        "STALE_PROVIDERS": "",
        "EVENT_WINDOW_STATE": "CLEAR",
        "EVENT_RISK_LEVEL": "NONE",
        "NEXT_EVENT_NAME": "",
        "NEXT_EVENT_TIME": "",
        "NEXT_EVENT_IMPACT": "NONE",
        "MARKET_EVENT_BLOCKED": "false",
        "SYMBOL_EVENT_BLOCKED": "false",
        "EVENT_COOLDOWN_ACTIVE": "false",
        "EARNINGS_SOON_TICKERS": "",
    }
    defaults.update(overrides)
    return defaults


# ── Pine parser ───────────────────────────────────────────────────

class TestParsePineExports:
    def test_string_export(self) -> None:
        text = 'export const string MARKET_REGIME = "RISK_OFF"'
        result = _parse_pine_exports(text)
        assert result["MARKET_REGIME"] == "RISK_OFF"

    def test_bool_export(self) -> None:
        text = "export const bool HIGH_IMPACT_MACRO_TODAY = true"
        result = _parse_pine_exports(text)
        assert result["HIGH_IMPACT_MACRO_TODAY"] == "true"

    def test_float_export(self) -> None:
        text = "export const float VIX_LEVEL = 32.5"
        result = _parse_pine_exports(text)
        assert result["VIX_LEVEL"] == "32.5"

    def test_int_export(self) -> None:
        text = "export const int PROVIDER_COUNT = 2"
        result = _parse_pine_exports(text)
        assert result["PROVIDER_COUNT"] == "2"

    def test_non_export_lines_ignored(self) -> None:
        text = (
            "// comment\n"
            'const string INTERNAL = "x"\n'
            'export const string VISIBLE = "y"\n'
        )
        result = _parse_pine_exports(text)
        assert "INTERNAL" not in result
        assert result["VISIBLE"] == "y"


class TestReadLibraryState:
    def test_reads_pine_file(self, tmp_path: Path) -> None:
        pine = tmp_path / "lib.pine"
        pine.write_text(_pine_content(MARKET_REGIME="RISK_OFF"), encoding="utf-8")
        state = read_library_state(pine)
        assert state["MARKET_REGIME"] == "RISK_OFF"

    def test_missing_file_returns_empty(self, tmp_path: Path) -> None:
        state = read_library_state(tmp_path / "missing.pine")
        assert state == {}


# ── Alert evaluation: no alert ────────────────────────────────────

class TestNoAlert:
    def test_neutral_regime_no_alerts(self) -> None:
        state = _state_from()
        alerts = evaluate_alerts(state)
        assert alerts == []

    def test_risk_on_no_alerts(self) -> None:
        state = _state_from(MARKET_REGIME="RISK_ON")
        assert evaluate_alerts(state) == []

    def test_healthy_providers_no_alert_when_enabled(self) -> None:
        state = _state_from(PROVIDER_COUNT="3", STALE_PROVIDERS="")
        assert evaluate_alerts(state, provider_alerts_enabled=True) == []

    def test_no_alerts_with_clear_event_state(self) -> None:
        state = _state_from(EVENT_WINDOW_STATE="CLEAR")
        assert evaluate_alerts(state) == []


# ── Alert evaluation: risk-off ────────────────────────────────────

class TestRiskOffAlert:
    def test_risk_off_fires(self) -> None:
        state = _state_from(MARKET_REGIME="RISK_OFF")
        alerts = evaluate_alerts(state)
        assert len(alerts) == 1
        assert alerts[0]["rule"] == RULE_RISK_OFF
        assert alerts[0]["severity"] == "critical"

    def test_risk_off_includes_vix(self) -> None:
        state = _state_from(MARKET_REGIME="RISK_OFF", VIX_LEVEL="35.2")
        alerts = evaluate_alerts(state)
        assert "35.2" in alerts[0]["detail"]


# ── Alert evaluation: macro event ─────────────────────────────────

class TestMacroAlert:
    def test_high_impact_macro_fires(self) -> None:
        state = _state_from(
            HIGH_IMPACT_MACRO_TODAY="true",
            MACRO_EVENT_NAME="FOMC",
            MACRO_EVENT_TIME="14:00",
        )
        alerts = evaluate_alerts(state)
        macro = [a for a in alerts if a["rule"] == RULE_MACRO_EVENT]
        assert len(macro) == 1
        assert macro[0]["severity"] == "warning"
        assert "FOMC" in macro[0]["detail"]
        assert "14:00" in macro[0]["detail"]

    def test_macro_without_name(self) -> None:
        state = _state_from(HIGH_IMPACT_MACRO_TODAY="true")
        alerts = evaluate_alerts(state)
        macro = [a for a in alerts if a["rule"] == RULE_MACRO_EVENT]
        assert macro[0]["detail"] == "Details unavailable"


# ── Alert evaluation: trade blocked ───────────────────────────────

class TestTradeBlockedAlert:
    def test_trade_blocked_fires(self) -> None:
        state = _state_from(TRADE_STATE="BLOCKED", TONE="BEARISH")
        alerts = evaluate_alerts(state)
        blocked = [a for a in alerts if a["rule"] == RULE_TRADE_BLOCKED]
        assert len(blocked) == 1
        assert blocked[0]["severity"] == "critical"
        assert "BEARISH" in blocked[0]["detail"]


# ── Alert evaluation: provider degraded ───────────────────────────

class TestProviderDegradedAlert:
    def test_provider_degraded_disabled_by_default(self) -> None:
        state = _state_from(PROVIDER_COUNT="0", STALE_PROVIDERS="fmp")
        assert evaluate_alerts(state) == []

    def test_provider_degraded_when_enabled_zero_count(self) -> None:
        state = _state_from(PROVIDER_COUNT="0")
        alerts = evaluate_alerts(state, provider_alerts_enabled=True)
        degraded = [a for a in alerts if a["rule"] == RULE_PROVIDER_DEGRADED]
        assert len(degraded) == 1
        assert degraded[0]["severity"] == "warning"

    def test_provider_degraded_when_stale(self) -> None:
        state = _state_from(PROVIDER_COUNT="2", STALE_PROVIDERS="fmp_vix,fmp_news")
        alerts = evaluate_alerts(state, provider_alerts_enabled=True)
        degraded = [a for a in alerts if a["rule"] == RULE_PROVIDER_DEGRADED]
        assert len(degraded) == 1
        assert "fmp_vix,fmp_news" in degraded[0]["detail"]


# ── Alert evaluation: event-risk incoming ─────────────────────────

class TestEventIncomingAlert:
    def test_pre_event_high_fires(self) -> None:
        state = _state_from(
            EVENT_WINDOW_STATE="PRE_EVENT",
            EVENT_RISK_LEVEL="HIGH",
            NEXT_EVENT_NAME="FOMC Rate Decision",
            NEXT_EVENT_TIME="14:00",
        )
        alerts = evaluate_alerts(state)
        incoming = [a for a in alerts if a["rule"] == RULE_EVENT_INCOMING]
        assert len(incoming) == 1
        assert incoming[0]["severity"] == "warning"
        assert "HIGH" in incoming[0]["title"]
        assert "FOMC" in incoming[0]["detail"]
        assert "14:00" in incoming[0]["detail"]

    def test_pre_event_elevated_fires(self) -> None:
        state = _state_from(
            EVENT_WINDOW_STATE="PRE_EVENT",
            EVENT_RISK_LEVEL="ELEVATED",
            NEXT_EVENT_NAME="CPI",
            NEXT_EVENT_TIME="08:30",
        )
        alerts = evaluate_alerts(state)
        incoming = [a for a in alerts if a["rule"] == RULE_EVENT_INCOMING]
        assert len(incoming) == 1

    def test_pre_event_low_no_alert(self) -> None:
        state = _state_from(
            EVENT_WINDOW_STATE="PRE_EVENT",
            EVENT_RISK_LEVEL="LOW",
        )
        alerts = evaluate_alerts(state)
        incoming = [a for a in alerts if a["rule"] == RULE_EVENT_INCOMING]
        assert incoming == []

    def test_pre_event_none_risk_no_alert(self) -> None:
        state = _state_from(
            EVENT_WINDOW_STATE="PRE_EVENT",
            EVENT_RISK_LEVEL="NONE",
        )
        alerts = evaluate_alerts(state)
        incoming = [a for a in alerts if a["rule"] == RULE_EVENT_INCOMING]
        assert incoming == []


# ── Alert evaluation: event release window ────────────────────────

class TestEventReleaseAlert:
    def test_active_window_fires(self) -> None:
        state = _state_from(
            EVENT_WINDOW_STATE="ACTIVE",
            NEXT_EVENT_NAME="NFP",
            NEXT_EVENT_TIME="08:30",
        )
        alerts = evaluate_alerts(state)
        release = [a for a in alerts if a["rule"] == RULE_EVENT_RELEASE]
        assert len(release) == 1
        assert release[0]["severity"] == "warning"
        assert "NFP" in release[0]["detail"]

    def test_clear_window_no_release(self) -> None:
        state = _state_from(EVENT_WINDOW_STATE="CLEAR")
        alerts = evaluate_alerts(state)
        release = [a for a in alerts if a["rule"] == RULE_EVENT_RELEASE]
        assert release == []


# ── Alert evaluation: cooldown start / end ────────────────────────

class TestEventCooldownAlerts:
    def test_cooldown_window_fires_start(self) -> None:
        state = _state_from(
            EVENT_WINDOW_STATE="COOLDOWN",
            EVENT_COOLDOWN_ACTIVE="true",
            NEXT_EVENT_NAME="FOMC",
            NEXT_EVENT_TIME="14:00",
        )
        alerts = evaluate_alerts(state)
        cd = [a for a in alerts if a["rule"] == RULE_EVENT_COOLDOWN_START]
        assert len(cd) == 1
        assert cd[0]["severity"] == "info"

    def test_cooldown_active_without_window_fires(self) -> None:
        state = _state_from(
            EVENT_WINDOW_STATE="CLEAR",
            EVENT_COOLDOWN_ACTIVE="true",
        )
        alerts = evaluate_alerts(state)
        cd = [a for a in alerts if a["rule"] == RULE_EVENT_COOLDOWN_START]
        assert len(cd) == 1

    def test_cooldown_end_fires_on_transition(self) -> None:
        state = _state_from(
            EVENT_WINDOW_STATE="CLEAR",
            EVENT_COOLDOWN_ACTIVE="false",
        )
        prev = {
            "EVENT_WINDOW_STATE": "COOLDOWN",
            "EVENT_COOLDOWN_ACTIVE": "true",
        }
        alerts = evaluate_alerts(state, previous_event_state=prev)
        end = [a for a in alerts if a["rule"] == RULE_EVENT_COOLDOWN_END]
        assert len(end) == 1
        assert end[0]["severity"] == "info"
        assert "clear" in end[0]["title"].lower()

    def test_cooldown_end_from_active_window(self) -> None:
        state = _state_from(
            EVENT_WINDOW_STATE="CLEAR",
            EVENT_COOLDOWN_ACTIVE="false",
        )
        prev = {"EVENT_WINDOW_STATE": "ACTIVE", "EVENT_COOLDOWN_ACTIVE": "false"}
        alerts = evaluate_alerts(state, previous_event_state=prev)
        end = [a for a in alerts if a["rule"] == RULE_EVENT_COOLDOWN_END]
        assert len(end) == 1

    def test_no_cooldown_end_when_still_clear(self) -> None:
        state = _state_from()
        prev = {"EVENT_WINDOW_STATE": "CLEAR", "EVENT_COOLDOWN_ACTIVE": "false"}
        alerts = evaluate_alerts(state, previous_event_state=prev)
        end = [a for a in alerts if a["rule"] == RULE_EVENT_COOLDOWN_END]
        assert end == []


# ── Alert evaluation: market event blocked ────────────────────────

class TestEventMarketBlockedAlert:
    def test_market_blocked_fires(self) -> None:
        state = _state_from(
            MARKET_EVENT_BLOCKED="true",
            NEXT_EVENT_NAME="FOMC",
            NEXT_EVENT_TIME="14:00",
            EVENT_RISK_LEVEL="HIGH",
            NEXT_EVENT_IMPACT="HIGH",
        )
        alerts = evaluate_alerts(state)
        blocked = [a for a in alerts if a["rule"] == RULE_EVENT_MARKET_BLOCKED]
        assert len(blocked) == 1
        assert blocked[0]["severity"] == "critical"
        assert "FOMC" in blocked[0]["detail"]
        assert "HIGH" in blocked[0]["detail"]

    def test_market_not_blocked_no_alert(self) -> None:
        state = _state_from(MARKET_EVENT_BLOCKED="false")
        alerts = evaluate_alerts(state)
        blocked = [a for a in alerts if a["rule"] == RULE_EVENT_MARKET_BLOCKED]
        assert blocked == []


# ── Alert evaluation: symbol event blocked ────────────────────────

class TestEventSymbolBlockedAlert:
    def test_symbol_blocked_fires(self) -> None:
        state = _state_from(
            SYMBOL_EVENT_BLOCKED="true",
            EARNINGS_SOON_TICKERS="AAPL,MSFT",
        )
        alerts = evaluate_alerts(state)
        blocked = [a for a in alerts if a["rule"] == RULE_EVENT_SYMBOL_BLOCKED]
        assert len(blocked) == 1
        assert blocked[0]["severity"] == "critical"
        assert "AAPL,MSFT" in blocked[0]["detail"]

    def test_symbol_not_blocked_no_alert(self) -> None:
        state = _state_from(SYMBOL_EVENT_BLOCKED="false")
        alerts = evaluate_alerts(state)
        blocked = [a for a in alerts if a["rule"] == RULE_EVENT_SYMBOL_BLOCKED]
        assert blocked == []


# ── V5 neutral defaults preserve v4 behavior ─────────────────────

class TestV5NeutralDefaults:
    def test_clear_defaults_produce_no_event_alerts(self) -> None:
        state = _state_from()
        alerts = evaluate_alerts(state)
        event_rules = {
            RULE_EVENT_INCOMING,
            RULE_EVENT_RELEASE,
            RULE_EVENT_COOLDOWN_START,
            RULE_EVENT_COOLDOWN_END,
            RULE_EVENT_MARKET_BLOCKED,
            RULE_EVENT_SYMBOL_BLOCKED,
        }
        event_alerts = [a for a in alerts if a["rule"] in event_rules]
        assert event_alerts == []


# ── Alert evaluation: multiple simultaneous ───────────────────────

class TestMultipleAlerts:
    def test_risk_off_and_macro_and_blocked(self) -> None:
        state = _state_from(
            MARKET_REGIME="RISK_OFF",
            HIGH_IMPACT_MACRO_TODAY="true",
            TRADE_STATE="BLOCKED",
        )
        alerts = evaluate_alerts(state)
        rules = {a["rule"] for a in alerts}
        assert rules == {RULE_RISK_OFF, RULE_MACRO_EVENT, RULE_TRADE_BLOCKED}


# ── Duplicate suppression ─────────────────────────────────────────

_BASE_FP = {
    "MARKET_REGIME": "NEUTRAL",
    "HIGH_IMPACT_MACRO_TODAY": "false",
    "TRADE_STATE": "ALLOWED",
    "PROVIDER_COUNT": "3",
    "STALE_PROVIDERS": "",
    "EVENT_WINDOW_STATE": "CLEAR",
    "EVENT_RISK_LEVEL": "NONE",
    "EVENT_COOLDOWN_ACTIVE": "false",
    "MARKET_EVENT_BLOCKED": "false",
    "SYMBOL_EVENT_BLOCKED": "false",
    "NEXT_EVENT_NAME": "",
    "NEXT_EVENT_TIME": "",
}


def _fp(**overrides: str) -> dict[str, str]:
    return {**_BASE_FP, **overrides}


class TestDuplicateSuppression:
    def test_first_run_sends_everything(self) -> None:
        state = _state_from(MARKET_REGIME="RISK_OFF")
        alerts = evaluate_alerts(state)
        result = suppress_duplicates(alerts, state, {})
        assert len(result) == 1

    def test_same_state_suppresses(self) -> None:
        state = _state_from(MARKET_REGIME="RISK_OFF")
        alerts = evaluate_alerts(state)
        result = suppress_duplicates(alerts, state, _fp(MARKET_REGIME="RISK_OFF"))
        assert result == []

    def test_changed_regime_fires(self) -> None:
        state = _state_from(MARKET_REGIME="RISK_OFF")
        alerts = evaluate_alerts(state)
        result = suppress_duplicates(alerts, state, _fp(MARKET_REGIME="NEUTRAL"))
        assert len(result) == 1
        assert result[0]["rule"] == RULE_RISK_OFF

    def test_macro_transition_fires(self) -> None:
        state = _state_from(HIGH_IMPACT_MACRO_TODAY="true")
        alerts = evaluate_alerts(state)
        result = suppress_duplicates(alerts, state, _fp())
        assert len(result) == 1

    def test_provider_change_fires(self) -> None:
        state = _state_from(STALE_PROVIDERS="fmp_vix")
        alerts = evaluate_alerts(state, provider_alerts_enabled=True)
        result = suppress_duplicates(alerts, state, _fp())
        assert len(result) == 1

    def test_event_incoming_suppressed_when_unchanged(self) -> None:
        state = _state_from(
            EVENT_WINDOW_STATE="PRE_EVENT",
            EVENT_RISK_LEVEL="HIGH",
            NEXT_EVENT_NAME="FOMC",
        )
        alerts = evaluate_alerts(state)
        prev = _fp(
            EVENT_WINDOW_STATE="PRE_EVENT",
            EVENT_RISK_LEVEL="HIGH",
        )
        result = suppress_duplicates(alerts, state, prev)
        incoming = [a for a in result if a["rule"] == RULE_EVENT_INCOMING]
        assert incoming == []

    def test_event_incoming_fires_on_window_change(self) -> None:
        state = _state_from(
            EVENT_WINDOW_STATE="PRE_EVENT",
            EVENT_RISK_LEVEL="HIGH",
            NEXT_EVENT_NAME="FOMC",
        )
        alerts = evaluate_alerts(state)
        result = suppress_duplicates(alerts, state, _fp(EVENT_WINDOW_STATE="CLEAR"))
        incoming = [a for a in result if a["rule"] == RULE_EVENT_INCOMING]
        assert len(incoming) == 1

    def test_market_blocked_suppressed_when_unchanged(self) -> None:
        state = _state_from(MARKET_EVENT_BLOCKED="true")
        alerts = evaluate_alerts(state)
        prev = _fp(MARKET_EVENT_BLOCKED="true")
        result = suppress_duplicates(alerts, state, prev)
        blocked = [a for a in result if a["rule"] == RULE_EVENT_MARKET_BLOCKED]
        assert blocked == []

    def test_market_blocked_fires_on_change(self) -> None:
        state = _state_from(MARKET_EVENT_BLOCKED="true")
        alerts = evaluate_alerts(state)
        result = suppress_duplicates(alerts, state, _fp())
        blocked = [a for a in result if a["rule"] == RULE_EVENT_MARKET_BLOCKED]
        assert len(blocked) == 1


# ── Fingerprint persistence ──────────────────────────────────────

class TestFingerprint:
    def test_save_and_load(self, tmp_path: Path) -> None:
        fp_path = tmp_path / "fp.json"
        state = _state_from(MARKET_REGIME="RISK_OFF")
        save_fingerprint(fp_path, state)
        loaded = load_previous_fingerprint(fp_path)
        assert loaded["MARKET_REGIME"] == "RISK_OFF"

    def test_save_includes_event_risk_fields(self, tmp_path: Path) -> None:
        fp_path = tmp_path / "fp.json"
        state = _state_from(
            EVENT_WINDOW_STATE="PRE_EVENT",
            EVENT_RISK_LEVEL="HIGH",
            MARKET_EVENT_BLOCKED="true",
        )
        save_fingerprint(fp_path, state)
        loaded = load_previous_fingerprint(fp_path)
        assert loaded["EVENT_WINDOW_STATE"] == "PRE_EVENT"
        assert loaded["EVENT_RISK_LEVEL"] == "HIGH"
        assert loaded["MARKET_EVENT_BLOCKED"] == "true"

    def test_load_missing_returns_empty(self, tmp_path: Path) -> None:
        assert load_previous_fingerprint(tmp_path / "nope.json") == {}

    def test_load_corrupt_returns_empty(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad.json"
        bad.write_text("not json{", encoding="utf-8")
        assert load_previous_fingerprint(bad) == {}


# ── Message formatting ────────────────────────────────────────────

class TestFormatMessage:
    def test_includes_timestamp(self) -> None:
        alerts = [{"severity": "critical", "title": "Test", "detail": "d"}]
        msg = _format_message(alerts, "2026-03-28T14:30:00Z")
        assert "2026-03-28T14:30:00Z" in msg

    def test_critical_icon(self) -> None:
        alerts = [{"severity": "critical", "title": "Crit", "detail": "d"}]
        msg = _format_message(alerts, "T")
        assert "🔴" in msg

    def test_warning_icon(self) -> None:
        alerts = [{"severity": "warning", "title": "Warn", "detail": "d"}]
        msg = _format_message(alerts, "T")
        assert "🟡" in msg

    def test_info_icon(self) -> None:
        alerts = [{"severity": "info", "title": "Info", "detail": "d"}]
        msg = _format_message(alerts, "T")
        assert "ℹ️" in msg


# ── End-to-end via CLI ────────────────────────────────────────────

class TestCLI:
    def test_dry_run_prints_alert(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        pine = tmp_path / "lib.pine"
        pine.write_text(_pine_content(MARKET_REGIME="RISK_OFF"), encoding="utf-8")
        state_file = tmp_path / "state.json"

        from scripts.smc_alert_notifier import main, build_parser

        with patch.object(
            __import__("scripts.smc_alert_notifier", fromlist=["build_parser"]),
            "build_parser",
            return_value=_cli_parser(
                library=str(pine),
                state_file=str(state_file),
                dry_run=True,
            ),
        ):
            rc = main()

        assert rc == 0
        out = capsys.readouterr().out
        assert "RISK_OFF" in out

    def test_no_alerts_returns_0(self, tmp_path: Path) -> None:
        pine = tmp_path / "lib.pine"
        pine.write_text(_pine_content(), encoding="utf-8")

        from scripts.smc_alert_notifier import main

        with patch.object(
            __import__("scripts.smc_alert_notifier", fromlist=["build_parser"]),
            "build_parser",
            return_value=_cli_parser(
                library=str(pine),
                state_file=str(tmp_path / "s.json"),
                dry_run=True,
            ),
        ):
            rc = main()

        assert rc == 0


def _cli_parser(**kw: Any) -> MagicMock:
    from argparse import Namespace

    defaults = {
        "library": "",
        "state_file": "",
        "provider_alerts": False,
        "dry_run": False,
        "telegram_bot_token": "",
        "telegram_chat_id": "",
        "smtp_host": "",
        "smtp_port": 587,
        "smtp_user": "",
        "smtp_pass": "",
        "email_from": "",
        "email_to": "",
    }
    defaults.update(kw)
    mock = MagicMock()
    mock.parse_args.return_value = Namespace(**defaults)
    return mock


from typing import Any


# ── v5.3 alert rule tests ────────────────────────────────────────

class TestStructureShift:
    def test_fires_on_bullish_shift(self) -> None:
        state = _state_from(STRUCTURE_STATE="BULLISH", STRUCTURE_LAST_EVENT="CHoCH")
        prev = _state_from(STRUCTURE_STATE="NEUTRAL")
        alerts = evaluate_alerts(state, previous_event_state=prev)
        rules = [a["rule"] for a in alerts]
        assert RULE_STRUCTURE_SHIFT in rules

    def test_no_fire_when_neutral(self) -> None:
        state = _state_from(STRUCTURE_STATE="NEUTRAL")
        prev = _state_from(STRUCTURE_STATE="BULLISH")
        alerts = evaluate_alerts(state, previous_event_state=prev)
        rules = [a["rule"] for a in alerts]
        assert RULE_STRUCTURE_SHIFT not in rules

    def test_no_fire_when_unchanged(self) -> None:
        state = _state_from(STRUCTURE_STATE="BULLISH")
        prev = _state_from(STRUCTURE_STATE="BULLISH")
        alerts = evaluate_alerts(state, previous_event_state=prev)
        rules = [a["rule"] for a in alerts]
        assert RULE_STRUCTURE_SHIFT not in rules


class TestImbalanceShift:
    def test_fires_on_state_change(self) -> None:
        state = _state_from(IMBALANCE_STATE="FVG_ACTIVE")
        prev = _state_from(IMBALANCE_STATE="NONE")
        alerts = evaluate_alerts(state, previous_event_state=prev)
        rules = [a["rule"] for a in alerts]
        assert RULE_IMBALANCE_SHIFT in rules

    def test_no_fire_to_none(self) -> None:
        state = _state_from(IMBALANCE_STATE="NONE")
        prev = _state_from(IMBALANCE_STATE="FVG_ACTIVE")
        alerts = evaluate_alerts(state, previous_event_state=prev)
        rules = [a["rule"] for a in alerts]
        assert RULE_IMBALANCE_SHIFT not in rules


class TestSessionContextShift:
    def test_fires_on_session_change(self) -> None:
        state = _state_from(SESSION_CONTEXT="LONDON", IN_KILLZONE="true")
        prev = _state_from(SESSION_CONTEXT="NONE")
        alerts = evaluate_alerts(state, previous_event_state=prev)
        rules = [a["rule"] for a in alerts]
        assert RULE_SESSION_CONTEXT_SHIFT in rules

    def test_no_fire_to_none(self) -> None:
        state = _state_from(SESSION_CONTEXT="NONE")
        prev = _state_from(SESSION_CONTEXT="LONDON")
        alerts = evaluate_alerts(state, previous_event_state=prev)
        rules = [a["rule"] for a in alerts]
        assert RULE_SESSION_CONTEXT_SHIFT not in rules


class TestRangeBreakout:
    def test_fires_on_break_up(self) -> None:
        state = _state_from(
            RANGE_BREAK_DIRECTION="UP", RANGE_ACTIVE="true", RANGE_WIDTH_ATR="1.5"
        )
        prev = _state_from(RANGE_BREAK_DIRECTION="NONE")
        alerts = evaluate_alerts(state, previous_event_state=prev)
        rules = [a["rule"] for a in alerts]
        assert RULE_RANGE_BREAKOUT in rules

    def test_no_fire_when_range_inactive(self) -> None:
        state = _state_from(RANGE_BREAK_DIRECTION="UP", RANGE_ACTIVE="false")
        prev = _state_from(RANGE_BREAK_DIRECTION="NONE")
        alerts = evaluate_alerts(state, previous_event_state=prev)
        rules = [a["rule"] for a in alerts]
        assert RULE_RANGE_BREAKOUT not in rules

    def test_no_fire_when_unchanged(self) -> None:
        state = _state_from(RANGE_BREAK_DIRECTION="UP", RANGE_ACTIVE="true")
        prev = _state_from(RANGE_BREAK_DIRECTION="UP")
        alerts = evaluate_alerts(state, previous_event_state=prev)
        rules = [a["rule"] for a in alerts]
        assert RULE_RANGE_BREAKOUT not in rules


class TestSentimentShift:
    def test_fires_on_bullish_shift(self) -> None:
        state = _state_from(PROFILE_SENTIMENT_BIAS="BULL", LIQUIDITY_IMBALANCE="0.6")
        prev = _state_from(PROFILE_SENTIMENT_BIAS="NEUTRAL")
        alerts = evaluate_alerts(state, previous_event_state=prev)
        rules = [a["rule"] for a in alerts]
        assert RULE_SENTIMENT_SHIFT in rules

    def test_no_fire_to_neutral(self) -> None:
        state = _state_from(PROFILE_SENTIMENT_BIAS="NEUTRAL")
        prev = _state_from(PROFILE_SENTIMENT_BIAS="BULL")
        alerts = evaluate_alerts(state, previous_event_state=prev)
        rules = [a["rule"] for a in alerts]
        assert RULE_SENTIMENT_SHIFT not in rules
