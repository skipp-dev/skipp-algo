"""Unit tests for ``scripts/credential_health_check.py``.

The script is consumed by ``.github/workflows/credential-health-check.yml``
(Bundle C, audit follow-up from PR #2415 / #2418 / #2421, issue #2422).

We test the probe functions in isolation — no network. The GitHub-PAT
probe uses an in-process fake opener so we never hit api.github.com from
the test suite.
"""

from __future__ import annotations

import io
import json
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import MagicMock

import pytest

from scripts.credential_health_check import (
    WARN_FRACTION,
    ProbeResult,
    probe_databento,
    probe_fmp,
    probe_github_pat,
    probe_newsapi,
    probe_tv_storage_state,
)

# -- TV storage_state probe -------------------------------------------------


def _make_cookie(age_hours: float | None, *, drop_meta: bool = False) -> str:
    if drop_meta:
        return json.dumps({"cookies": [], "origins": []})
    if age_hours is None:
        return json.dumps({"meta": {}, "cookies": [], "origins": []})
    validated_at = datetime.now(UTC) - timedelta(hours=age_hours)
    return json.dumps(
        {
            "meta": {"authValidatedAt": validated_at.isoformat()},
            "cookies": [],
            "origins": [],
        }
    )


def test_tv_storage_state_ok_when_fresh() -> None:
    r = probe_tv_storage_state(_make_cookie(age_hours=1.0), max_age_hours=72.0)
    assert r.severity == "ok"
    assert "tv_storage_state_age" == r.name
    assert r.details["age_hours"] < 2.0


def test_tv_storage_state_warn_at_80_percent_of_ttl() -> None:
    # 72h * 0.80 = 57.6h ; pick something just above the warn fraction.
    r = probe_tv_storage_state(_make_cookie(age_hours=60.0), max_age_hours=72.0)
    assert r.severity == "warn", r
    assert r.details["age_hours"] == pytest.approx(60.0, abs=0.5)
    assert r.details["warn_at_hours"] == pytest.approx(72.0 * WARN_FRACTION, abs=0.1)


def test_tv_storage_state_error_when_expired() -> None:
    r = probe_tv_storage_state(_make_cookie(age_hours=90.0), max_age_hours=72.0)
    assert r.severity == "error"
    assert "EXPIRED" in r.message


def test_tv_storage_state_error_when_invalid_json() -> None:
    r = probe_tv_storage_state("{not json", max_age_hours=72.0)
    assert r.severity == "error"
    assert "not valid JSON" in r.message


def test_tv_storage_state_error_when_meta_missing() -> None:
    r = probe_tv_storage_state(_make_cookie(age_hours=1.0, drop_meta=True), max_age_hours=72.0)
    assert r.severity == "error"
    assert "missing meta" in r.message


def test_tv_storage_state_error_when_validated_at_missing() -> None:
    r = probe_tv_storage_state(_make_cookie(age_hours=None), max_age_hours=72.0)
    assert r.severity == "error"
    assert "authValidatedAt" in r.message


def test_tv_storage_state_error_when_validated_at_unparseable() -> None:
    payload = json.dumps({"meta": {"authValidatedAt": "not-a-date"}})
    r = probe_tv_storage_state(payload, max_age_hours=72.0)
    assert r.severity == "error"
    assert "ISO-8601" in r.message


def test_tv_storage_state_handles_trailing_z_iso_format() -> None:
    payload = json.dumps({"meta": {"authValidatedAt": "2026-05-28T12:00:00Z"}})
    # Don't care about result — only that the parser does not crash.
    r = probe_tv_storage_state(
        payload,
        max_age_hours=72.0,
        now=datetime(2026, 5, 28, 13, 0, 0, tzinfo=UTC),
    )
    assert r.severity == "ok"
    assert r.details["age_hours"] == pytest.approx(1.0, abs=0.05)


# -- GitHub PAT probe -------------------------------------------------------


def _fake_opener(
    *,
    status: int = 200,
    body: dict[str, Any] | None = None,
    expiration_header: str | None = None,
    raise_exc: Exception | None = None,
):
    opener = MagicMock()
    if raise_exc is not None:
        opener.open.side_effect = raise_exc
        return opener
    body = body or {"login": "skipp-dev"}
    payload = json.dumps(body).encode("utf-8")
    resp = MagicMock()
    resp.getcode.return_value = status
    resp.read.return_value = payload
    headers: dict[str, str] = {}
    if expiration_header is not None:
        headers["github-authentication-token-expiration"] = expiration_header
    resp.headers.get.side_effect = lambda k, default=None: headers.get(k.lower(), headers.get(k, default))
    # urllib resp supports use as context manager.
    resp.__enter__ = lambda self: self
    resp.__exit__ = lambda self, *a: False
    opener.open.return_value = resp
    return opener


def test_github_pat_empty_token_is_error() -> None:
    r = probe_github_pat("")
    assert r.severity == "error"
    assert "empty" in r.message


def test_github_pat_ok_when_no_expiry_header() -> None:
    r = probe_github_pat("ghp_dummy", opener=_fake_opener())
    assert r.severity == "ok"
    assert r.details["login"] == "skipp-dev"


def test_github_pat_ok_when_far_from_expiry() -> None:
    future = (datetime.now(UTC) + timedelta(days=180)).isoformat()
    r = probe_github_pat("ghp_dummy", opener=_fake_opener(expiration_header=future))
    assert r.severity == "ok"
    assert r.details["days_left"] > 90


def test_github_pat_warn_at_30_days_left() -> None:
    future = (datetime.now(UTC) + timedelta(days=20)).isoformat()
    r = probe_github_pat("ghp_dummy", opener=_fake_opener(expiration_header=future))
    assert r.severity == "warn"
    assert "rotation" in r.message.lower() or "expires" in r.message.lower()


def test_github_pat_error_at_7_days_left() -> None:
    future = (datetime.now(UTC) + timedelta(days=3)).isoformat()
    r = probe_github_pat("ghp_dummy", opener=_fake_opener(expiration_header=future))
    assert r.severity == "error"
    assert "IMMEDIATELY" in r.message


def test_github_pat_error_when_already_expired() -> None:
    past = (datetime.now(UTC) - timedelta(days=1)).isoformat()
    r = probe_github_pat("ghp_dummy", opener=_fake_opener(expiration_header=past))
    assert r.severity == "error"
    assert "EXPIRED" in r.message


def test_github_pat_error_when_api_rejects_token() -> None:
    import urllib.error

    exc = urllib.error.HTTPError(
        url="https://api.github.com/user",
        code=401,
        msg="Unauthorized",
        hdrs=None,  # type: ignore[arg-type]
        fp=io.BytesIO(b""),
    )
    r = probe_github_pat("ghp_dummy", opener=_fake_opener(raise_exc=exc))
    assert r.severity == "error"
    assert "rejected" in r.message
    assert r.details["status"] == 401


def test_github_pat_warn_when_network_unreachable() -> None:
    import urllib.error

    exc = urllib.error.URLError("nodename nor servname provided")
    r = probe_github_pat("ghp_dummy", opener=_fake_opener(raise_exc=exc))
    assert r.severity == "warn"
    assert "inconclusive" in r.message


# -- ProbeResult shape ------------------------------------------------------


def test_probe_result_serializable() -> None:
    r = ProbeResult("name", "ok", "msg", {"k": 1})
    from dataclasses import asdict

    d = asdict(r)
    assert d == {"name": "name", "severity": "ok", "message": "msg", "details": {"k": 1}}


# -- Vendor-API probes ------------------------------------------------------
#
# Shared error model contract (see _probe_http_vendor docstring):
#   empty key -> error; 401/403 -> error; 429 -> warn; 5xx -> warn;
#   network -> warn; 200 -> ok; other -> warn.
# We test the contract once per vendor with the cheapest signal each.


@pytest.mark.parametrize(
    "probe, label, name",
    [
        (probe_databento, "Databento", "databento_api_key"),
        (probe_fmp, "FMP", "fmp_api_key"),
        (probe_newsapi, "NewsAPI", "newsapi_key"),
    ],
)
def test_vendor_empty_key_is_error(probe, label, name) -> None:
    r = probe("")
    assert r.severity == "error"
    assert r.name == name
    assert label in r.message
    assert "empty" in r.message or "missing" in r.message


@pytest.mark.parametrize("probe", [probe_databento, probe_fmp, probe_newsapi])
def test_vendor_http_200_is_ok(probe) -> None:
    r = probe("dummy-key", opener=_fake_opener(status=200, body={}))
    assert r.severity == "ok"
    assert r.details["status"] == 200


@pytest.mark.parametrize("probe, label", [(probe_databento, "Databento"), (probe_fmp, "FMP"), (probe_newsapi, "NewsAPI")])
def test_vendor_401_is_error(probe, label) -> None:
    import urllib.error

    exc = urllib.error.HTTPError(
        url="https://example.com",
        code=401,
        msg="Unauthorized",
        hdrs=None,  # type: ignore[arg-type]
        fp=io.BytesIO(b""),
    )
    r = probe("dummy-key", opener=_fake_opener(raise_exc=exc))
    assert r.severity == "error"
    assert "rejected" in r.message
    assert label in r.message
    assert r.details["status"] == 401


@pytest.mark.parametrize("probe", [probe_databento, probe_fmp, probe_newsapi])
def test_vendor_403_is_error(probe) -> None:
    import urllib.error

    exc = urllib.error.HTTPError(
        url="https://example.com",
        code=403,
        msg="Forbidden",
        hdrs=None,  # type: ignore[arg-type]
        fp=io.BytesIO(b""),
    )
    r = probe("dummy-key", opener=_fake_opener(raise_exc=exc))
    assert r.severity == "error"


@pytest.mark.parametrize("probe", [probe_databento, probe_fmp, probe_newsapi])
def test_vendor_429_is_warn(probe) -> None:
    import urllib.error

    exc = urllib.error.HTTPError(
        url="https://example.com",
        code=429,
        msg="Too Many Requests",
        hdrs=None,  # type: ignore[arg-type]
        fp=io.BytesIO(b""),
    )
    r = probe("dummy-key", opener=_fake_opener(raise_exc=exc))
    assert r.severity == "warn"
    assert "rate-limited" in r.message
    assert r.details["status"] == 429


@pytest.mark.parametrize("probe", [probe_databento, probe_fmp, probe_newsapi])
def test_vendor_5xx_is_warn(probe) -> None:
    import urllib.error

    exc = urllib.error.HTTPError(
        url="https://example.com",
        code=503,
        msg="Service Unavailable",
        hdrs=None,  # type: ignore[arg-type]
        fp=io.BytesIO(b""),
    )
    r = probe("dummy-key", opener=_fake_opener(raise_exc=exc))
    assert r.severity == "warn"
    assert "vendor-side" in r.message
    assert r.details["status"] == 503


@pytest.mark.parametrize("probe", [probe_databento, probe_fmp, probe_newsapi])
def test_vendor_network_error_is_warn(probe) -> None:
    import urllib.error

    r = probe("dummy-key", opener=_fake_opener(raise_exc=urllib.error.URLError("dns fail")))
    assert r.severity == "warn"
    assert "inconclusive" in r.message


@pytest.mark.parametrize("probe", [probe_databento, probe_fmp, probe_newsapi])
def test_vendor_unexpected_status_is_warn(probe) -> None:
    import urllib.error

    exc = urllib.error.HTTPError(
        url="https://example.com",
        code=418,
        msg="I'm a teapot",
        hdrs=None,  # type: ignore[arg-type]
        fp=io.BytesIO(b""),
    )
    r = probe("dummy-key", opener=_fake_opener(raise_exc=exc))
    assert r.severity == "warn"
    assert "unexpected" in r.message


def test_databento_uses_basic_auth_header() -> None:
    opener = _fake_opener(status=200, body={})
    probe_databento("my-secret-key", opener=opener)
    req = opener.open.call_args[0][0]
    auth = req.headers.get("Authorization") or req.headers.get("authorization")
    assert auth is not None and auth.startswith("Basic "), f"got {auth!r}"
    import base64 as _b64

    decoded = _b64.b64decode(auth.split(" ", 1)[1]).decode()
    assert decoded == "my-secret-key:"


def test_fmp_puts_key_in_query_string() -> None:
    opener = _fake_opener(status=200, body={})
    probe_fmp("my-secret-key", opener=opener)
    req = opener.open.call_args[0][0]
    assert "apikey=my-secret-key" in req.full_url


def test_newsapi_uses_x_api_key_header() -> None:
    opener = _fake_opener(status=200, body={})
    probe_newsapi("my-secret-key", opener=opener)
    req = opener.open.call_args[0][0]
    # urllib normalises header names to title-case.
    assert req.headers.get("X-api-key") == "my-secret-key"
