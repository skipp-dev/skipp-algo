"""Unit tests for ``scripts/vendor_billing_watch.py`` — no IMAP, no network."""

from __future__ import annotations

from datetime import UTC, datetime

from scripts import vendor_billing_watch as vbw
from scripts.composio_ops import DeliveryResult

_SINCE = datetime(2026, 7, 1, tzinfo=UTC)


def _raw(sender: str, subject: str, body: str) -> bytes:
    return (
        f"From: {sender}\r\n"
        f"Subject: {subject}\r\n"
        "Content-Type: text/plain; charset=utf-8\r\n"
        "Date: Fri, 10 Jul 2026 09:00:00 +0000\r\n"
        f"\r\n{body}"
    ).encode()


class _FakeIMAP:
    def __init__(self, by_domain: dict[str, list[bytes]]) -> None:
        self.by_domain: dict[str, list[bytes]] = {}
        self.raw: dict[bytes, bytes] = {}
        n = 0
        for domain, raws in by_domain.items():
            nums = []
            for raw in raws:
                n += 1
                numb = str(n).encode()
                self.raw[numb] = raw
                nums.append(numb)
            self.by_domain[domain] = nums

    def search(self, _charset, *criteria):
        domain = criteria[criteria.index("FROM") + 1]
        return "OK", [b" ".join(self.by_domain.get(domain, []))]

    def fetch(self, num, _spec):
        raw = self.raw.get(num)
        if raw is None:
            return "NO", [None]
        return "OK", [(num + b" (RFC822 {n}", raw)]

    def login(self, _u, _p):
        return "OK", [b"ok"]

    def select(self, _mbox, readonly=False):
        return "OK", [b"1"]

    def logout(self):
        return "BYE", [b"bye"]


def test_detects_payment_failure():
    conn = _FakeIMAP(
        {"databento.com": [_raw("billing@databento.com", "Payment failed", "We could not process your card.")]}
    )
    hits = vbw.find_billing_alerts(
        conn, domains=("databento.com",), keywords=vbw._PROBLEM_KEYWORDS, since=_SINCE
    )
    assert len(hits) == 1
    assert hits[0].vendor == "databento.com"
    assert "payment failed" in hits[0].matched
    assert "could not process" in hits[0].matched


def test_ignores_routine_receipt():
    conn = _FakeIMAP(
        {"databento.com": [_raw("billing@databento.com", "Your receipt", "Thanks for your payment. Receipt attached.")]}
    )
    hits = vbw.find_billing_alerts(
        conn, domains=("databento.com",), keywords=vbw._PROBLEM_KEYWORDS, since=_SINCE
    )
    assert hits == []


def test_matches_body_only_keyword():
    conn = _FakeIMAP(
        {"financialmodelingprep.com": [_raw("no-reply@financialmodelingprep.com", "Notice", "Your subscription is past due.")]}
    )
    hits = vbw.find_billing_alerts(
        conn, domains=("financialmodelingprep.com",), keywords=vbw._PROBLEM_KEYWORDS, since=_SINCE
    )
    assert len(hits) == 1 and "past due" in hits[0].matched


def test_multiple_domains_and_empty():
    conn = _FakeIMAP(
        {
            "databento.com": [_raw("b@databento.com", "Account suspended", "Your account will be suspended.")],
            "benzinga.com": [_raw("b@benzinga.com", "Weekly digest", "Top movers this week.")],
        }
    )
    hits = vbw.find_billing_alerts(
        conn,
        domains=("databento.com", "benzinga.com"),
        keywords=vbw._PROBLEM_KEYWORDS,
        since=_SINCE,
    )
    assert [h.vendor for h in hits] == ["databento.com"]


def test_build_alert_renders():
    hit = vbw.BillingHit(
        vendor="databento.com",
        sender="billing@databento.com",
        subject="Payment failed",
        date="Fri, 10 Jul 2026",
        matched=["payment failed"],
    )
    msg = vbw.build_alert([hit])
    assert "databento.com" in msg and "payment failed" in msg and "Vendor-Portal" in msg


def test_main_skips_without_password(monkeypatch, capsys):
    monkeypatch.delenv("YAHOO_APP_PASSWORD", raising=False)
    assert vbw.main([]) == 0
    assert "skipping" in capsys.readouterr().out


def test_main_loud_on_connect_failure(monkeypatch):
    monkeypatch.setenv("YAHOO_APP_PASSWORD", "pw")

    def boom(_host):
        raise OSError("connection refused")

    monkeypatch.setattr(vbw.imaplib, "IMAP4_SSL", boom)
    assert vbw.main([]) == 1  # blind watcher surfaces red


def test_main_alerts_on_hit(monkeypatch):
    monkeypatch.setenv("YAHOO_APP_PASSWORD", "pw")
    monkeypatch.setenv("VENDOR_BILLING_DOMAINS", "databento.com")
    conn = _FakeIMAP(
        {"databento.com": [_raw("billing@databento.com", "Payment failed", "card declined")]}
    )
    monkeypatch.setattr(vbw.imaplib, "IMAP4_SSL", lambda _host: conn)
    sent: list[str] = []

    def fake_notify(msg):
        sent.append(msg)
        return DeliveryResult(True, False, "ok")

    # Patch the module object vbw actually calls into (robust to which import
    # branch resolved), not the test's own composio_ops reference.
    monkeypatch.setattr(vbw.composio_ops, "notify_slack", fake_notify)
    assert vbw.main([]) == 0
    assert sent and "databento.com" in sent[0]


def test_main_no_hit_no_alert(monkeypatch):
    monkeypatch.setenv("YAHOO_APP_PASSWORD", "pw")
    monkeypatch.setenv("VENDOR_BILLING_DOMAINS", "databento.com")
    conn = _FakeIMAP({"databento.com": [_raw("billing@databento.com", "Receipt", "thank you")]})
    monkeypatch.setattr(vbw.imaplib, "IMAP4_SSL", lambda _host: conn)
    called: list[str] = []
    monkeypatch.setattr(vbw.composio_ops, "notify_slack", lambda m: called.append(m) or DeliveryResult(True, False, "ok"))
    assert vbw.main([]) == 0
    assert called == []


def test_workflow_wires_the_script():
    """Covers the vendor-billing-watch.yml workflow (orphan-inventory guard)."""
    from pathlib import Path

    wf = Path(__file__).resolve().parent.parent / ".github/workflows/vendor-billing-watch.yml"
    text = wf.read_text(encoding="utf-8")
    assert "scripts/vendor_billing_watch.py" in text
    assert "off-hours-only" in text  # schedule-only, no repo writes
    assert "YAHOO_APP_PASSWORD" in text
