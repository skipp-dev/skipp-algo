"""SMC Alert Notifier — v5 event-risk aware alerting for generated library state changes.

Reads the generated Pine library (or its accompanying manifest) and fires
alerts when critical state changes are detected:

- MARKET_REGIME → RISK_OFF
- HIGH_IMPACT_MACRO_TODAY = true
- TRADE_STATE → BLOCKED
- Provider count drops to zero or stale providers appear
- EVENT_WINDOW_STATE transitions (PRE_EVENT, COOLDOWN, CLEAR)
- MARKET_EVENT_BLOCKED / SYMBOL_EVENT_BLOCKED activated

Duplicate suppression: a tiny JSON state file tracks the last-alerted values.
An alert only fires when the relevant field *changes* relative to the
previous run's persisted state.

Channels: Telegram (via Bot API) and SMTP/email.  Both are optional —
configure via env vars or CLI flags.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import smtplib
import sys
import urllib.request
import urllib.error
from datetime import UTC, datetime
from email.message import EmailMessage
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ── Alert rule definitions ────────────────────────────────────────

RULE_RISK_OFF = "risk_off"
RULE_MACRO_EVENT = "macro_event"
RULE_TRADE_BLOCKED = "trade_blocked"
RULE_PROVIDER_DEGRADED = "provider_degraded"
RULE_EVENT_INCOMING = "event_incoming"
RULE_EVENT_RELEASE = "event_release"
RULE_EVENT_COOLDOWN_START = "event_cooldown_start"
RULE_EVENT_COOLDOWN_END = "event_cooldown_end"
RULE_EVENT_MARKET_BLOCKED = "event_market_blocked"
RULE_EVENT_SYMBOL_BLOCKED = "event_symbol_blocked"
# v5.3 rules
RULE_STRUCTURE_SHIFT = "structure_shift"
RULE_IMBALANCE_SHIFT = "imbalance_shift"
RULE_SESSION_CONTEXT_SHIFT = "session_context_shift"
RULE_RANGE_BREAKOUT = "range_breakout"
RULE_SENTIMENT_SHIFT = "sentiment_shift"


def _parse_pine_exports(text: str) -> dict[str, str]:
    """Extract ``export const <type> NAME = <value>`` pairs from Pine source."""
    result: dict[str, str] = {}
    for match in re.finditer(
        r'^export\s+const\s+\w+\s+(\w+)\s*=\s*(.+)$',
        text,
        re.MULTILINE,
    ):
        key = match.group(1)
        raw = match.group(2).strip()
        # Strip surrounding quotes for string values
        if raw.startswith('"') and raw.endswith('"'):
            raw = raw[1:-1]
        result[key] = raw
    return result


def read_library_state(pine_path: Path) -> dict[str, str]:
    """Read the generated Pine library and return exported constants."""
    if not pine_path.is_file():
        logger.warning("Pine library not found: %s", pine_path)
        return {}
    text = pine_path.read_text(encoding="utf-8")
    return _parse_pine_exports(text)


# ── Alert evaluation ─────────────────────────────────────────────

def _to_bool(val: str) -> bool:
    return val.strip().lower() == "true"


def evaluate_alerts(
    state: dict[str, str],
    *,
    provider_alerts_enabled: bool = False,
    previous_event_state: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Return a list of alert dicts for any triggered rules.

    Each alert dict has keys: ``rule``, ``severity``, ``title``, ``detail``.

    *previous_event_state* is needed to detect cooldown-end transitions;
    pass the previous fingerprint or ``{}`` for first run.
    """
    if previous_event_state is None:
        previous_event_state = {}
    alerts: list[dict[str, Any]] = []

    regime = state.get("MARKET_REGIME", "NEUTRAL")
    if regime == "RISK_OFF":
        alerts.append({
            "rule": RULE_RISK_OFF,
            "severity": "critical",
            "title": "Market regime → RISK_OFF",
            "detail": f"VIX={state.get('VIX_LEVEL', '?')}, "
                      f"Sector breadth={state.get('SECTOR_BREADTH', '?')}",
        })

    if _to_bool(state.get("HIGH_IMPACT_MACRO_TODAY", "false")):
        event_name = state.get("MACRO_EVENT_NAME", "")
        event_time = state.get("MACRO_EVENT_TIME", "")
        alerts.append({
            "rule": RULE_MACRO_EVENT,
            "severity": "warning",
            "title": "High-impact macro event today",
            "detail": f"{event_name} at {event_time}" if event_name else "Details unavailable",
        })

    trade_state = state.get("TRADE_STATE", "ALLOWED")
    if trade_state == "BLOCKED":
        alerts.append({
            "rule": RULE_TRADE_BLOCKED,
            "severity": "critical",
            "title": "Trade state → BLOCKED",
            "detail": f"Tone={state.get('TONE', '?')}, "
                      f"Global heat={state.get('GLOBAL_HEAT', '?')}",
        })

    if provider_alerts_enabled:
        provider_count = int(state.get("PROVIDER_COUNT", "0") or "0")
        stale = state.get("STALE_PROVIDERS", "")
        if provider_count == 0 or stale:
            alerts.append({
                "rule": RULE_PROVIDER_DEGRADED,
                "severity": "warning",
                "title": "Provider degradation detected",
                "detail": f"Active providers={provider_count}, "
                          f"Stale={stale or 'none'}",
            })

    # ── v5 Event-risk rules ───────────────────────────────────────
    window_state = state.get("EVENT_WINDOW_STATE", "CLEAR")
    risk_level = state.get("EVENT_RISK_LEVEL", "NONE")
    next_name = state.get("NEXT_EVENT_NAME", "")
    next_time = state.get("NEXT_EVENT_TIME", "")
    next_impact = state.get("NEXT_EVENT_IMPACT", "NONE")
    market_blocked = _to_bool(state.get("MARKET_EVENT_BLOCKED", "false"))
    symbol_blocked = _to_bool(state.get("SYMBOL_EVENT_BLOCKED", "false"))

    event_detail = f"{next_name} at {next_time}" if next_name else "Details unavailable"

    if market_blocked:
        alerts.append({
            "rule": RULE_EVENT_MARKET_BLOCKED,
            "severity": "critical",
            "title": "Market-wide event block active",
            "detail": f"{event_detail} | Impact={next_impact}, Risk={risk_level}",
        })

    if symbol_blocked:
        tickers = state.get("EARNINGS_SOON_TICKERS", "")
        alerts.append({
            "rule": RULE_EVENT_SYMBOL_BLOCKED,
            "severity": "critical",
            "title": "Symbol event block active",
            "detail": f"Tickers={tickers or '?'} | {event_detail}",
        })

    if window_state == "PRE_EVENT" and risk_level in ("HIGH", "ELEVATED"):
        alerts.append({
            "rule": RULE_EVENT_INCOMING,
            "severity": "warning",
            "title": f"High-impact event incoming ({risk_level})",
            "detail": event_detail,
        })

    if window_state == "ACTIVE":
        alerts.append({
            "rule": RULE_EVENT_RELEASE,
            "severity": "warning",
            "title": "Event release window active",
            "detail": event_detail,
        })

    cooldown_active = _to_bool(state.get("EVENT_COOLDOWN_ACTIVE", "false"))
    if window_state == "COOLDOWN" or cooldown_active:
        alerts.append({
            "rule": RULE_EVENT_COOLDOWN_START,
            "severity": "info",
            "title": "Event cooldown started",
            "detail": event_detail,
        })

    if window_state == "CLEAR" and not cooldown_active and not market_blocked and not symbol_blocked:
        prev_window = previous_event_state.get("EVENT_WINDOW_STATE", "CLEAR")
        prev_cooldown = previous_event_state.get("EVENT_COOLDOWN_ACTIVE", "false")
        if prev_window in ("COOLDOWN", "ACTIVE") or prev_cooldown == "true":
            alerts.append({
                "rule": RULE_EVENT_COOLDOWN_END,
                "severity": "info",
                "title": "Event cooldown ended — trading clear",
                "detail": "All event restrictions lifted",
            })

    # ── v5.3 Structure / Imbalance / Session / Range rules ────────
    struct_state = state.get("STRUCTURE_STATE", "NEUTRAL")
    struct_event = state.get("STRUCTURE_LAST_EVENT", "NONE")
    prev_struct = previous_event_state.get("STRUCTURE_STATE", "NEUTRAL")
    if struct_state != prev_struct and struct_state != "NEUTRAL":
        alerts.append({
            "rule": RULE_STRUCTURE_SHIFT,
            "severity": "warning",
            "title": f"Structure shift → {struct_state}",
            "detail": f"Last event={struct_event}, "
                      f"Fresh={state.get('STRUCTURE_FRESH', '?')}",
        })

    imb_state = state.get("IMBALANCE_STATE", "NONE")
    prev_imb = previous_event_state.get("IMBALANCE_STATE", "NONE")
    if imb_state != prev_imb and imb_state != "NONE":
        bpr = state.get("BPR_ACTIVE", "false")
        liq_void = _to_bool(state.get("LIQ_VOID_BULL_ACTIVE", "false")) or _to_bool(state.get("LIQ_VOID_BEAR_ACTIVE", "false"))
        alerts.append({
            "rule": RULE_IMBALANCE_SHIFT,
            "severity": "info",
            "title": f"Imbalance state → {imb_state}",
            "detail": f"BPR={bpr}, LiqVoid={'active' if liq_void else 'none'}",
        })

    sess_ctx = state.get("SESSION_CONTEXT", "NONE")
    sess_kz = _to_bool(state.get("IN_KILLZONE", "false"))
    sess_mss_bull = _to_bool(state.get("SESSION_MSS_BULL", "false"))
    sess_mss_bear = _to_bool(state.get("SESSION_MSS_BEAR", "false"))
    prev_sess = previous_event_state.get("SESSION_CONTEXT", "NONE")
    if sess_ctx != prev_sess and sess_ctx != "NONE":
        alerts.append({
            "rule": RULE_SESSION_CONTEXT_SHIFT,
            "severity": "info",
            "title": f"Session context → {sess_ctx}",
            "detail": f"KZ={'yes' if sess_kz else 'no'}, "
                      f"MSS={'BULL' if sess_mss_bull else 'BEAR' if sess_mss_bear else 'none'}",
        })

    range_break = state.get("RANGE_BREAK_DIRECTION", "NONE")
    prev_break = previous_event_state.get("RANGE_BREAK_DIRECTION", "NONE")
    range_active = _to_bool(state.get("RANGE_ACTIVE", "false"))
    if range_break != prev_break and range_break != "NONE" and range_active:
        alerts.append({
            "rule": RULE_RANGE_BREAKOUT,
            "severity": "warning",
            "title": f"Range breakout → {range_break}",
            "detail": f"Width ATR={state.get('RANGE_WIDTH_ATR', '?')}",
        })

    sentiment = state.get("PROFILE_SENTIMENT_BIAS", "NEUTRAL")
    prev_sentiment = previous_event_state.get("PROFILE_SENTIMENT_BIAS", "NEUTRAL")
    liq_imbalance = state.get("LIQUIDITY_IMBALANCE", "0")
    if sentiment != prev_sentiment and sentiment != "NEUTRAL":
        alerts.append({
            "rule": RULE_SENTIMENT_SHIFT,
            "severity": "info",
            "title": f"Sentiment bias → {sentiment}",
            "detail": f"Liquidity imbalance={liq_imbalance}",
        })

    return alerts


# ── Duplicate suppression ─────────────────────────────────────────

_TRACKED_FIELDS = [
    "MARKET_REGIME",
    "HIGH_IMPACT_MACRO_TODAY",
    "TRADE_STATE",
    "PROVIDER_COUNT",
    "STALE_PROVIDERS",
    "EVENT_WINDOW_STATE",
    "EVENT_RISK_LEVEL",
    "EVENT_COOLDOWN_ACTIVE",
    "MARKET_EVENT_BLOCKED",
    "SYMBOL_EVENT_BLOCKED",
    "NEXT_EVENT_NAME",
    "NEXT_EVENT_TIME",
    # v5.3 structure / imbalance / session / range
    "STRUCTURE_STATE",
    "STRUCTURE_LAST_EVENT",
    "IMBALANCE_STATE",
    "BPR_ACTIVE",
    "LIQ_VOID_BULL_ACTIVE",
    "LIQ_VOID_BEAR_ACTIVE",
    "SESSION_CONTEXT",
    "IN_KILLZONE",
    "SESSION_MSS_BULL",
    "SESSION_MSS_BEAR",
    "RANGE_ACTIVE",
    "RANGE_BREAK_DIRECTION",
    "PROFILE_SENTIMENT_BIAS",
    "LIQUIDITY_IMBALANCE",
]


def _state_fingerprint(state: dict[str, str]) -> dict[str, str]:
    return {k: state.get(k, "") for k in _TRACKED_FIELDS}


def load_previous_fingerprint(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def save_fingerprint(path: Path, state: dict[str, str]) -> None:
    fp = _state_fingerprint(state)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(fp, indent=2) + "\n", encoding="utf-8")


def suppress_duplicates(
    alerts: list[dict[str, Any]],
    current_state: dict[str, str],
    previous_fp: dict[str, str],
) -> list[dict[str, Any]]:
    """Remove alerts whose triggering fields have not changed since the last run."""
    if not previous_fp:
        return alerts  # first run — send everything

    current_fp = _state_fingerprint(current_state)
    kept: list[dict[str, Any]] = []
    for alert in alerts:
        rule = alert["rule"]
        if rule == RULE_RISK_OFF:
            if current_fp.get("MARKET_REGIME") != previous_fp.get("MARKET_REGIME"):
                kept.append(alert)
        elif rule == RULE_MACRO_EVENT:
            if current_fp.get("HIGH_IMPACT_MACRO_TODAY") != previous_fp.get("HIGH_IMPACT_MACRO_TODAY"):
                kept.append(alert)
        elif rule == RULE_TRADE_BLOCKED:
            if current_fp.get("TRADE_STATE") != previous_fp.get("TRADE_STATE"):
                kept.append(alert)
        elif rule == RULE_PROVIDER_DEGRADED:
            if (
                current_fp.get("PROVIDER_COUNT") != previous_fp.get("PROVIDER_COUNT")
                or current_fp.get("STALE_PROVIDERS") != previous_fp.get("STALE_PROVIDERS")
            ):
                kept.append(alert)
        elif rule in (
            RULE_EVENT_INCOMING,
            RULE_EVENT_RELEASE,
            RULE_EVENT_COOLDOWN_START,
            RULE_EVENT_COOLDOWN_END,
            RULE_EVENT_MARKET_BLOCKED,
            RULE_EVENT_SYMBOL_BLOCKED,
        ):
            event_keys = (
                "EVENT_WINDOW_STATE",
                "EVENT_RISK_LEVEL",
                "EVENT_COOLDOWN_ACTIVE",
                "MARKET_EVENT_BLOCKED",
                "SYMBOL_EVENT_BLOCKED",
            )
            if any(
                current_fp.get(k) != previous_fp.get(k)
                for k in event_keys
            ):
                kept.append(alert)
        else:
            kept.append(alert)  # unknown rule — always send
    return kept


# ── Delivery channels ────────────────────────────────────────────

def _format_message(alerts: list[dict[str, Any]], ts: str) -> str:
    lines = [f"🔔 SMC Library Alert — {ts}", ""]
    for a in alerts:
        sev = a["severity"]
        icon = "🔴" if sev == "critical" else "🟡" if sev == "warning" else "ℹ️"
        lines.append(f"{icon} {a['title']}")
        lines.append(f"   {a['detail']}")
        lines.append("")
    return "\n".join(lines).rstrip()


def send_telegram(
    alerts: list[dict[str, Any]],
    *,
    bot_token: str,
    chat_id: str,
    ts: str,
) -> bool:
    """Send alerts via Telegram Bot API.  Returns True on success."""
    text = _format_message(alerts, ts)
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = json.dumps({"chat_id": chat_id, "text": text}).encode()
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            ok = resp.status == 200
            if not ok:
                logger.warning("Telegram returned status %s", resp.status)
            return ok
    except (urllib.error.URLError, OSError) as exc:
        logger.warning("Telegram send failed: %s", exc)
        return False


def send_email(
    alerts: list[dict[str, Any]],
    *,
    smtp_host: str,
    smtp_port: int,
    smtp_user: str,
    smtp_pass: str,
    from_addr: str,
    to_addr: str,
    ts: str,
) -> bool:
    """Send alerts via SMTP/email.  Returns True on success."""
    body = _format_message(alerts, ts)
    msg = EmailMessage()
    msg["Subject"] = f"SMC Alert: {', '.join(a['title'] for a in alerts)}"
    msg["From"] = from_addr
    msg["To"] = to_addr
    msg.set_content(body)
    try:
        with smtplib.SMTP(smtp_host, smtp_port, timeout=15) as server:
            server.starttls()
            server.login(smtp_user, smtp_pass)
            server.send_message(msg)
        return True
    except (smtplib.SMTPException, OSError) as exc:
        logger.warning("Email send failed: %s", exc)
        return False


# ── CLI entry point ───────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Evaluate and send alerts for SMC library state changes.",
    )
    p.add_argument(
        "--library",
        default="pine/generated/smc_micro_profiles_generated.pine",
        help="Path to the generated Pine library.",
    )
    p.add_argument(
        "--state-file",
        default="artifacts/ci/alert_last_state.json",
        help="Path to the duplicate-suppression state file.",
    )
    p.add_argument(
        "--provider-alerts",
        action="store_true",
        help="Enable provider degradation alerts.",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Evaluate rules and print alerts without sending.",
    )
    # Telegram
    p.add_argument("--telegram-bot-token", default="")
    p.add_argument("--telegram-chat-id", default="")
    # Email
    p.add_argument("--smtp-host", default="")
    p.add_argument("--smtp-port", type=int, default=587)
    p.add_argument("--smtp-user", default="")
    p.add_argument("--smtp-pass", default="")
    p.add_argument("--email-from", default="")
    p.add_argument("--email-to", default="")
    return p


def main() -> int:
    args = build_parser().parse_args()
    ts = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    state = read_library_state(Path(args.library))
    if not state:
        logger.warning("Empty library state — nothing to evaluate.")
        return 0

    state_path = Path(args.state_file)
    prev_fp = load_previous_fingerprint(state_path)

    raw_alerts = evaluate_alerts(
        state,
        provider_alerts_enabled=args.provider_alerts,
        previous_event_state=prev_fp,
    )
    if not raw_alerts:
        logger.info("No alert conditions detected.")
        save_fingerprint(state_path, state)
        return 0

    alerts = suppress_duplicates(raw_alerts, state, prev_fp)

    # Always persist current fingerprint
    save_fingerprint(state_path, state)

    if not alerts:
        logger.info("All alerts suppressed (unchanged state since last run).")
        return 0

    if args.dry_run:
        print(_format_message(alerts, ts))
        return 0

    sent = False
    if args.telegram_bot_token and args.telegram_chat_id:
        if send_telegram(
            alerts,
            bot_token=args.telegram_bot_token,
            chat_id=args.telegram_chat_id,
            ts=ts,
        ):
            sent = True

    if args.smtp_host and args.email_to:
        if send_email(
            alerts,
            smtp_host=args.smtp_host,
            smtp_port=args.smtp_port,
            smtp_user=args.smtp_user,
            smtp_pass=args.smtp_pass,
            from_addr=args.email_from,
            to_addr=args.email_to,
            ts=ts,
        ):
            sent = True

    if not sent:
        # No channel configured — print to stdout as fallback
        print(_format_message(alerts, ts))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
