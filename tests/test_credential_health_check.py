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
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import MagicMock

import pytest

from scripts.credential_health_check import (
    WARN_FRACTION,
    ProbeResult,
    probe_github_pat,
    probe_tv_storage_state,
)


# -- TV storage_state probe -------------------------------------------------


def _make_cookie(age_hours: float | None, *, drop_meta: bool = False) -> str:
    if drop_meta:
        return json.dumps({"cookies": [], "origins": []})
    if age_hours is None:
        return json.dumps({"meta": {}, "cookies": [], "origins": []})
    validated_at = datetime.now(timezone.utc) - timedelta(hours=age_hours)
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
        now=datetime(2026, 5, 28, 13, 0, 0, tzinfo=timezone.utc),
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
    future = (datetime.now(timezone.utc) + timedelta(days=180)).isoformat()
    r = probe_github_pat("ghp_dummy", opener=_fake_opener(expiration_header=future))
    assert r.severity == "ok"
    assert r.details["days_left"] > 90


def test_github_pat_warn_at_30_days_left() -> None:
    future = (datetime.now(timezone.utc) + timedelta(days=20)).isoformat()
    r = probe_github_pat("ghp_dummy", opener=_fake_opener(expiration_header=future))
    assert r.severity == "warn"
    assert "rotation" in r.message.lower() or "expires" in r.message.lower()


def test_github_pat_error_at_7_days_left() -> None:
    future = (datetime.now(timezone.utc) + timedelta(days=3)).isoformat()
    r = probe_github_pat("ghp_dummy", opener=_fake_opener(expiration_header=future))
    assert r.severity == "error"
    assert "IMMEDIATELY" in r.message


def test_github_pat_error_when_already_expired() -> None:
    past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
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
