"""Vendor-billing watcher — catch the failure class the API probes miss.

Post-mortem 2026-06-12: an unpaid Databento invoice went unnoticed for 12 days
because the credential probes kept returning HTTP 200 — ``list_publishers`` works
fine while billing is broken. The only early signal of "payment failed / account
about to be suspended" arrives as an *email* from the vendor, not as an API
status.

This script scans the operator's mailbox (Yahoo, via IMAP — Composio has no
Yahoo/IMAP toolkit, so we read the source directly with stdlib ``imaplib``) for
recent messages from the data vendors whose subject/body signals a billing
*problem* (failed payment, past due, suspension), and pings the operator on
Slack via ``composio_ops`` so it is seen before delivery stops.

Design: pure stdlib for the read (imaplib/email); the only non-stdlib hop is the
fail-soft Slack alert through ``composio_ops`` (REST). It is deliberately
*loud* on a broken watcher (bad credentials / unreachable IMAP exit non-zero so
the daily workflow shows red) but *quiet* when simply unconfigured.

Config (env):
    YAHOO_EMAIL             mailbox to read (default: the address on file)
    YAHOO_APP_PASSWORD      a Yahoo *app password* (not the login password); unset -> skip
    YAHOO_IMAP_HOST         default imap.mail.yahoo.com
    VENDOR_BILLING_DOMAINS  comma-separated sender domains (default: the data vendors)
    plus the COMPOSIO_/SLACK_ALERT_ envs consumed by composio_ops for the ping.
"""

from __future__ import annotations

import argparse
import email
import imaplib
import os
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from email.header import decode_header, make_header
from typing import Any

try:  # `python scripts/foo.py` puts scripts/ on sys.path[0]
    import composio_ops
except ImportError:  # imported as scripts.vendor_billing_watch (pytest pythonpath=".")
    from scripts import composio_ops

_DEFAULT_HOST = "imap.mail.yahoo.com"
_DEFAULT_DOMAINS = ("databento.com", "financialmodelingprep.com", "benzinga.com")

# Keywords that signal a billing *problem*, not a routine receipt/invoice. Kept
# failure-focused so a normal monthly receipt does not page the operator.
_PROBLEM_KEYWORDS = (
    "payment failed",
    "payment declined",
    "card declined",
    "unable to charge",
    "could not process",
    "past due",
    "overdue",
    "unpaid",
    "outstanding balance",
    "suspend",  # covers suspend / suspended / suspension
    "deactivat",  # deactivate / deactivated
    "action required",
    "update your payment",
    "update payment",
    "expired card",
    "billing problem",
    "billing issue",
    "failed to renew",
)


@dataclass
class BillingHit:
    vendor: str
    sender: str
    subject: str
    date: str
    matched: list[str] = field(default_factory=list)


def _decode(value: str | None) -> str:
    if not value:
        return ""
    try:
        return str(make_header(decode_header(value)))
    except (ValueError, LookupError):
        return value


def _extract_text(msg: email.message.Message) -> str:
    """Return a best-effort plain-text rendering of the message body."""
    parts: list[str] = []
    for part in msg.walk() if msg.is_multipart() else [msg]:
        if part.get_content_maintype() == "multipart":
            continue
        if part.get_content_type() not in ("text/plain", "text/html"):
            continue
        payload = part.get_payload(decode=True)
        if isinstance(payload, bytes):
            charset = part.get_content_charset() or "utf-8"
            try:
                parts.append(payload.decode(charset, errors="replace"))
            except LookupError:
                parts.append(payload.decode("utf-8", errors="replace"))
    return " ".join(parts)


def _imap_date(dt: datetime) -> str:
    # IMAP SINCE wants DD-Mon-YYYY (e.g. 08-Jul-2026).
    return dt.strftime("%d-%b-%Y")


def find_billing_alerts(
    conn: Any,
    *,
    domains: tuple[str, ...],
    keywords: tuple[str, ...],
    since: datetime,
) -> list[BillingHit]:
    """Scan the selected mailbox for problem-signalling vendor billing mail.

    ``conn`` is any object exposing IMAP ``search`` / ``fetch`` (injected in
    tests). Each hit records which keywords matched so the alert is explainable.
    """
    since_str = _imap_date(since)
    hits: list[BillingHit] = []
    for domain in domains:
        typ, data = conn.search(None, "SINCE", since_str, "FROM", domain)
        if typ != "OK" or not data or not data[0]:
            continue
        for num in data[0].split():
            typ2, msg_data = conn.fetch(num, "(RFC822)")
            if typ2 != "OK" or not msg_data:
                continue
            raw = next((p[1] for p in msg_data if isinstance(p, tuple) and len(p) == 2), None)
            if not isinstance(raw, (bytes, bytearray)):
                continue
            msg = email.message_from_bytes(bytes(raw))
            subject = _decode(msg.get("Subject"))
            haystack = f"{subject} {_extract_text(msg)}".lower()
            matched = [k for k in keywords if k in haystack]
            if matched:
                hits.append(
                    BillingHit(
                        vendor=domain,
                        sender=_decode(msg.get("From")),
                        subject=subject,
                        date=msg.get("Date", ""),
                        matched=sorted(set(matched)),
                    )
                )
    return hits


def build_alert(hits: list[BillingHit]) -> str:
    lines = [f"🔴 *Vendor-Billing-Warnung* — {len(hits)} verdächtige Mail(s) im Postfach"]
    for h in hits:
        lines.append(f"🔴 *{h.vendor}* — {h.subject or '(kein Betreff)'}  ·  {h.date}")
        lines.append(f"    Treffer: {', '.join(h.matched)}  ·  von {h.sender}")
    lines.append(
        "\nDie API-Proben bleiben bei einem Zahlungsproblem grün — prüfe JETZT das "
        "Vendor-Portal auf offene Rechnung / fehlgeschlagene Zahlung, bevor die Datenlieferung stoppt."
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else "")
    parser.add_argument("--days", type=int, default=2, help="Look-back window in days (default 2).")
    parser.add_argument(
        "--always-notify",
        action="store_true",
        help="Send a Slack heartbeat even when no billing problems are found.",
    )
    args = parser.parse_args(argv)

    # Yahoo shows the 16-char app password in 4 space-separated groups for
    # readability; the real value has no spaces. Strip ALL whitespace so a
    # copy-with-spaces still authenticates (imaplib quotes the arg, so inner
    # spaces would otherwise reach Yahoo as a wrong password).
    password = "".join(os.getenv("YAHOO_APP_PASSWORD", "").split())
    if not password:
        print("vendor_billing_watch: YAHOO_APP_PASSWORD unset — skipping (no-op).")
        return 0

    # ``or <default>`` (not getenv's default arg) — GitHub Actions passes an
    # unset ``${{ vars.X }}`` as an *empty string*, so the key is present but
    # blank and getenv's default never applies.
    host = os.getenv("YAHOO_IMAP_HOST", "").strip() or _DEFAULT_HOST
    user = os.getenv("YAHOO_EMAIL", "").strip() or "preuss.steffen@yahoo.com"
    domains = tuple(
        d.strip()
        for d in (os.getenv("VENDOR_BILLING_DOMAINS", "").strip() or ",".join(_DEFAULT_DOMAINS)).split(",")
        if d.strip()
    )
    since = datetime.now(UTC) - timedelta(days=max(1, args.days))

    try:
        conn = imaplib.IMAP4_SSL(host)
        conn.login(user, password)
        conn.select("INBOX", readonly=True)
    except (imaplib.IMAP4.error, OSError) as exc:
        # A blind watcher is worse than a loud one — surface it red.
        print(f"::error::vendor-billing-watch: IMAP connect/login failed: {exc}", file=sys.stderr)
        return 1

    try:
        hits = find_billing_alerts(conn, domains=domains, keywords=_PROBLEM_KEYWORDS, since=since)
    finally:
        try:
            conn.logout()
        except (imaplib.IMAP4.error, OSError):
            pass

    if not hits:
        print(f"vendor_billing_watch: no billing-problem mail from {domains} in the last {args.days}d.")
        if args.always_notify:
            composio_ops.notify_slack(
                f"🟢 Vendor-Billing-Watcher: keine Auffälligkeiten (letzte {args.days} Tage)."
            )
        return 0

    result = composio_ops.notify_slack(build_alert(hits))
    if result.delivered:
        print(f"vendor_billing_watch: {len(hits)} hit(s) — Slack alert delivered.")
    elif result.skipped:
        print(f"vendor_billing_watch: {len(hits)} hit(s) — Slack skipped ({result.detail}).")
    else:
        print(f"vendor_billing_watch: {len(hits)} hit(s) — Slack FAILED ({result.detail}).", file=sys.stderr)
    # Hits found is not itself a job failure — the alert is the product.
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
