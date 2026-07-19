"""Unit tests for ``scripts/composio_ops.py`` — the fail-soft Composio REST client.

No network: an in-process fake ``urllib`` opener is injected (or ``build_opener``
is monkeypatched) so the wrapper's contract — skip-when-unconfigured,
never-raise, request shaping, response interpretation, DM channel resolution —
is asserted without a real API key.
"""

from __future__ import annotations

import io
import json
import urllib.error
from typing import Any

import pytest

from scripts import composio_ops


@pytest.fixture(autouse=True)
def _configured_env(monkeypatch):
    monkeypatch.setenv("COMPOSIO_ENVIRONMENT", "prod")
    monkeypatch.setenv("COMPOSIO_PROD_API_KEY", "ak_test")
    monkeypatch.setenv("COMPOSIO_PROD_USER_ID", "user-uuid")
    for toolkit in ("SLACK", "GITHUB", "OUTLOOK", "NOTION"):
        monkeypatch.setenv(f"COMPOSIO_{toolkit}_READ_ACCOUNT_ID", f"ca_{toolkit.lower()}_r")
        monkeypatch.setenv(f"COMPOSIO_{toolkit}_WRITE_ACCOUNT_ID", f"ca_{toolkit.lower()}_w")


class _FakeResp:
    def __init__(self, text: str) -> None:
        self._text = text

    def read(self) -> bytes:
        return self._text.encode("utf-8")

    def __enter__(self) -> _FakeResp:
        return self

    def __exit__(self, *_exc: object) -> bool:
        return False


class _FakeOpener:
    """Records requests and returns canned bodies; ``handler`` may raise."""

    def __init__(self, handler) -> None:
        self.handler = handler
        self.requests: list[Any] = []

    def open(self, request: Any, timeout: float | None = None) -> _FakeResp:
        self.requests.append(request)
        return _FakeResp(self.handler(request))


def _slug_of(request: Any) -> str:
    return request.full_url.rsplit("/", 1)[-1]


def _body_of(request: Any) -> dict[str, Any]:
    return json.loads(request.data.decode("utf-8"))


def test_skips_without_api_key(monkeypatch):
    monkeypatch.delenv("COMPOSIO_PROD_API_KEY", raising=False)
    result = composio_ops.execute_tool("SLACK_SEND_MESSAGE", {"channel": "x"})
    assert result.skipped and not result.ok and not result.delivered


def test_success_shapes_request(monkeypatch):
    opener = _FakeOpener(lambda req: json.dumps({"successful": True, "data": {"ok": True}}))
    result = composio_ops.execute_tool("SLACK_OPEN_DM", {"users": "U1"}, toolkit="slack", opener=opener)
    assert result.delivered
    req = opener.requests[0]
    assert _slug_of(req) == "SLACK_OPEN_DM"
    assert req.get_method() == "POST"
    assert req.headers.get("X-api-key") == "ak_test"
    body = _body_of(req)
    assert body["arguments"] == {"users": "U1"}
    assert body["user_id"] == "user-uuid"
    assert body["connected_account_id"] == "ca_slack_w"
    assert body["version"] == "20260717_00"


def test_connected_account_from_env(monkeypatch):
    monkeypatch.setenv("COMPOSIO_SLACK_WRITE_ACCOUNT_ID", "ca_1")
    opener = _FakeOpener(lambda req: json.dumps({"successful": True}))
    composio_ops.execute_tool("SLACK_SEND_MESSAGE", {"channel": "C1"}, toolkit="slack", opener=opener)
    assert _body_of(opener.requests[0])["connected_account_id"] == "ca_1"


def test_reports_provider_failure(monkeypatch):
    opener = _FakeOpener(lambda req: json.dumps({"successful": False, "error": {"message": "channel_not_found"}}))
    result = composio_ops.execute_tool("SLACK_SEND_MESSAGE", {"channel": "C1"}, opener=opener)
    assert not result.ok and not result.skipped and "channel_not_found" in result.detail


def test_http_error_is_soft(monkeypatch):
    body = io.BytesIO(json.dumps({"error": {"message": "Invalid API key"}}).encode())

    def boom(_req):
        raise urllib.error.HTTPError("u", 401, "Unauthorized", {}, body)

    result = composio_ops.execute_tool("SLACK_TEST_AUTH", {}, opener=_FakeOpener(boom))
    assert not result.ok and not result.skipped
    assert "401" in result.detail and "Invalid API key" in result.detail


def test_transport_error_is_soft(monkeypatch):

    def boom(_req):
        raise urllib.error.URLError("connection refused")

    result = composio_ops.execute_tool("SLACK_TEST_AUTH", {}, opener=_FakeOpener(boom))
    assert not result.ok and not result.skipped and "transport error" in result.detail


def test_non_json_is_soft(monkeypatch):
    result = composio_ops.execute_tool("SLACK_TEST_AUTH", {}, opener=_FakeOpener(lambda req: "<html>502</html>"))
    assert not result.ok and not result.skipped and "non-JSON" in result.detail


def test_notify_slack_prefers_dm(monkeypatch):
    monkeypatch.setenv("SLACK_ALERT_USER_ID", "U9")
    monkeypatch.delenv("SLACK_ALERT_CHANNEL", raising=False)
    seq: list[str] = []

    def handler(req):
        slug = _slug_of(req)
        seq.append(slug)
        if slug == "SLACK_OPEN_DM":
            return json.dumps({"successful": True, "data": {"channel": {"id": "D9"}}})
        return json.dumps({"successful": True, "data": {}})

    opener = _FakeOpener(handler)
    monkeypatch.setattr(composio_ops.urllib.request, "build_opener", lambda: opener)
    result = composio_ops.notify_slack("hi")
    assert result.delivered
    assert seq == ["SLACK_OPEN_DM", "SLACK_SEND_MESSAGE"]
    assert _body_of(opener.requests[1])["arguments"]["channel"] == "D9"


def test_notify_slack_channel_fallback(monkeypatch):
    monkeypatch.delenv("SLACK_ALERT_USER_ID", raising=False)
    monkeypatch.setenv("SLACK_ALERT_CHANNEL", "ops-alerts")
    opener = _FakeOpener(lambda req: json.dumps({"successful": True}))
    monkeypatch.setattr(composio_ops.urllib.request, "build_opener", lambda: opener)
    result = composio_ops.notify_slack("hi")
    assert result.delivered
    assert _slug_of(opener.requests[0]) == "SLACK_SEND_MESSAGE"
    assert _body_of(opener.requests[0])["arguments"]["channel"] == "ops-alerts"


def test_notify_slack_skips_unconfigured(monkeypatch):
    monkeypatch.delenv("SLACK_ALERT_USER_ID", raising=False)
    monkeypatch.delenv("SLACK_ALERT_CHANNEL", raising=False)
    assert composio_ops.notify_slack("hi").skipped


def test_send_outlook_email_shapes_html(monkeypatch):
    opener = _FakeOpener(lambda req: json.dumps({"successful": True}))
    monkeypatch.setattr(composio_ops.urllib.request, "build_opener", lambda: opener)
    composio_ops.send_outlook_email("a@b.c", "Subj", "<p>hi</p>")
    req = opener.requests[0]
    assert _slug_of(req) == "OUTLOOK_SEND_EMAIL"
    assert _body_of(req)["arguments"] == {
        "to": "a@b.c",
        "subject": "Subj",
        "body": "<p>hi</p>",
        "is_html": True,
    }


def test_base_url_override(monkeypatch):
    monkeypatch.setenv("COMPOSIO_BASE_URL", "https://eu.composio.dev/")
    opener = _FakeOpener(lambda req: json.dumps({"successful": True}))
    composio_ops.execute_tool("SLACK_SEND_MESSAGE", {"channel": "C1"}, opener=opener)
    assert opener.requests[0].full_url == "https://eu.composio.dev/api/v3/tools/execute/SLACK_SEND_MESSAGE"


def test_is_configured(monkeypatch):
    monkeypatch.delenv("COMPOSIO_PROD_API_KEY", raising=False)
    assert composio_ops.is_configured() is False
    monkeypatch.setenv("COMPOSIO_PROD_API_KEY", "ak_test")
    assert composio_ops.is_configured() is True


def test_rejects_unregistered_tool():
    result = composio_ops.execute_tool("SLACK_DELETE_CHANNEL", {})
    assert result.skipped and "not allow-listed" in result.detail


def test_requires_explicit_access_account(monkeypatch):
    monkeypatch.delenv("COMPOSIO_SLACK_WRITE_ACCOUNT_ID")
    result = composio_ops.execute_tool("SLACK_SEND_MESSAGE", {"channel": "C1"})
    assert result.skipped and "WRITE_ACCOUNT_ID" in result.detail


def test_dev_and_prod_keys_are_isolated(monkeypatch):
    monkeypatch.setenv("COMPOSIO_ENVIRONMENT", "dev")
    monkeypatch.delenv("COMPOSIO_DEV_API_KEY", raising=False)
    result = composio_ops.execute_tool("SLACK_TEST_AUTH", {})
    assert result.skipped and "COMPOSIO_DEV_API_KEY" in result.detail
