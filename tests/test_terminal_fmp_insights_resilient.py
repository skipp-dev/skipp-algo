"""Tests for `_call_openai_chat` resilient migration in terminal_fmp_insights.

Closes follow-up E-3 v2: covers retry-on-ReadTimeout and fail-fast on
HTTPStatusError / empty-choices.
"""
from __future__ import annotations

import httpx
import pytest

import terminal_fmp_insights as fi


class _Resp:
    def __init__(self, status: int, payload: dict):
        self.status_code = status
        self._payload = payload

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"{self.status_code}",
                request=httpx.Request("POST", "https://api.openai.com/v1/chat/completions"),
                response=httpx.Response(self.status_code, request=httpx.Request("POST", "https://api.openai.com/v1/chat/completions")),
            )


class _Client:
    def __init__(self, behaviours):
        self._behaviours = list(behaviours)
        self.calls = 0

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def post(self, *_args, **_kwargs):
        self.calls += 1
        b = self._behaviours.pop(0)
        if isinstance(b, Exception):
            raise b
        return b


def _patch_httpx_client(monkeypatch, client):
    monkeypatch.setattr(fi.httpx, "Client", lambda *a, **kw: client)


def _no_sleep(monkeypatch):
    # @resilient default sleep is bound at decoration time, so patch
    # the time.sleep used inside resilient via the resilient module.
    import smc_core.resilient as r

    monkeypatch.setattr(r.time, "sleep", lambda *_: None)


def test_call_openai_chat_succeeds_after_one_timeout(monkeypatch):
    _no_sleep(monkeypatch)
    ok_resp = _Resp(200, {"choices": [{"message": {"content": " hi "}}]})
    client = _Client([httpx.ReadTimeout("t"), ok_resp])
    _patch_httpx_client(monkeypatch, client)

    out = fi._call_openai_chat({"x": 1}, api_key="sk-test")

    assert out == "hi"
    assert client.calls == 2


def test_call_openai_chat_reraises_after_exhaustion(monkeypatch):
    _no_sleep(monkeypatch)
    # @resilient(retries=2) -> 1 initial + 2 retries = 3 attempts total.
    client = _Client([httpx.ReadTimeout("t")] * 3)
    _patch_httpx_client(monkeypatch, client)

    with pytest.raises(httpx.ReadTimeout):
        fi._call_openai_chat({"x": 1}, api_key="sk-test")
    assert client.calls == 3


def test_call_openai_chat_fail_fast_on_http_status(monkeypatch):
    _no_sleep(monkeypatch)
    bad = _Resp(429, {})
    client = _Client([bad])
    _patch_httpx_client(monkeypatch, client)

    with pytest.raises(httpx.HTTPStatusError):
        fi._call_openai_chat({"x": 1}, api_key="sk-test")
    assert client.calls == 1  # no retry on HTTPStatusError


def test_call_openai_chat_empty_choices_raises_sentinel(monkeypatch):
    _no_sleep(monkeypatch)
    empty = _Resp(200, {"choices": []})
    client = _Client([empty])
    _patch_httpx_client(monkeypatch, client)

    with pytest.raises(fi._OpenAIEmptyChoicesError):
        fi._call_openai_chat({"x": 1}, api_key="sk-test")
    assert client.calls == 1
