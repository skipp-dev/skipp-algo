"""Regression: singleton getters in newsstack_fmp.pipeline must rebuild
the wrapped adapter when the supplied credential changes.

Found via SMC bug-hunt v2 phase 4 — silent credential-rotation skip on
Streamlit refresh.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

import newsstack_fmp.pipeline as pipeline


@pytest.fixture(autouse=True)
def _reset_singletons():
    pipeline._fmp_adapter = None
    pipeline._fmp_adapter_key = None
    pipeline._bz_rest_adapter = None
    pipeline._bz_rest_adapter_key = None
    pipeline._bz_ws_adapter = None
    pipeline._bz_ws_adapter_key = None
    yield
    pipeline._fmp_adapter = None
    pipeline._fmp_adapter_key = None
    pipeline._bz_rest_adapter = None
    pipeline._bz_rest_adapter_key = None
    pipeline._bz_ws_adapter = None
    pipeline._bz_ws_adapter_key = None


class _CfgStub:
    def __init__(self, *, fmp="k1", bz="b1", bz_url="wss://x", bz_channels=None):
        self.fmp_api_key = fmp
        self.benzinga_api_key = bz
        self.benzinga_ws_url = bz_url
        self.benzinga_channels = bz_channels


def test_fmp_adapter_rebuilds_on_api_key_rotation():
    cfg1 = _CfgStub(fmp="key-old")
    cfg2 = _CfgStub(fmp="key-new")

    with patch("newsstack_fmp.pipeline.FmpAdapter") as ctor:
        ctor.side_effect = lambda key: type("A", (), {"key": key, "close": lambda self: None})()

        a1 = pipeline._get_fmp_adapter(cfg1)
        a1_again = pipeline._get_fmp_adapter(cfg1)
        a2 = pipeline._get_fmp_adapter(cfg2)

    assert a1 is a1_again, "same key must reuse the singleton"
    assert a1 is not a2, "rotated key must trigger rebuild"
    assert a1.key == "key-old"
    assert a2.key == "key-new"


def test_bz_rest_adapter_rebuilds_on_api_key_rotation():
    cfg1 = _CfgStub(bz="bz-old")
    cfg2 = _CfgStub(bz="bz-new")

    with patch("newsstack_fmp.ingest_benzinga.BenzingaRestAdapter", create=True) as ctor:
        ctor.side_effect = lambda key: type("B", (), {"key": key, "close": lambda self: None})()

        a1 = pipeline._get_bz_rest_adapter(cfg1)
        a1_again = pipeline._get_bz_rest_adapter(cfg1)
        a2 = pipeline._get_bz_rest_adapter(cfg2)

    assert a1 is a1_again
    assert a1 is not a2
    assert a1.key == "bz-old"
    assert a2.key == "bz-new"


def test_bz_ws_adapter_rebuilds_on_url_or_channel_change():
    cfg1 = _CfgStub(bz="k", bz_url="wss://a", bz_channels=["news"])
    cfg2_url = _CfgStub(bz="k", bz_url="wss://b", bz_channels=["news"])
    cfg2_ch = _CfgStub(bz="k", bz_url="wss://a", bz_channels=["news", "earnings"])

    with patch("newsstack_fmp.ingest_benzinga.BenzingaWsAdapter", create=True) as ctor:
        def _make(api_key, url, channels=None):
            stub = type("W", (), {"k": api_key, "u": url, "c": channels,
                                  "start": lambda self: None,
                                  "stop": lambda self: None})()
            return stub
        ctor.side_effect = _make

        a1 = pipeline._get_bz_ws_adapter(cfg1)
        a1_again = pipeline._get_bz_ws_adapter(cfg1)
        a2 = pipeline._get_bz_ws_adapter(cfg2_url)
        a3 = pipeline._get_bz_ws_adapter(cfg2_ch)

    assert a1 is a1_again
    assert a1 is not a2, "ws url change must trigger rebuild"
    assert a2 is not a3, "channels change must trigger rebuild"
