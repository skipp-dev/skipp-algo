"""Credential health probe.

Audit 2026-05-28 follow-up (issue #2422): the 5-week silent publish-skip
regression was masked partly because the TradingView storage_state cookie
had silently aged out (45 days vs. 72h enforced TTL). The TTL was enforced
*reactively* at preflight time inside the publish workflow; there was no
proactive daily check.

This script is the proactive check. It runs as a standalone CLI from a
dedicated daily workflow so a cookie that is approaching its TTL — or a
GitHub PAT approaching expiry — surfaces as an operator alert BEFORE the
next publish attempt fails.

Design:

* One lightweight request per probed credential: GitHub-API for ``GH_PAT``,
  plus per-vendor metadata probes (Databento, FMP, Benzinga/Massive; NewsAPI
  exists but is workflow-skipped since its 2026-07-08 retirement) that burn
  at most ~1 quota call/day each. Databento additionally gets a DELIVERY
  probe (``metadata.get_dataset_range``, free): billing failures (HTTP
  402 / suspended account) keep the auth probe green while data silently
  stops flowing — post-mortem 2026-06-12, unpaid invoice unnoticed 12 days.
* Composio gets a *connected-account* probe per declared toolkit/access pin
  for the same reason one layer up: the project API key keeps working while
  an individual OAuth connection expires underneath it, and consumers then
  fail with ``HTTP 410 ... is in EXPIRED state``. Post-mortem 2026-08-03:
  the weekly Notion digest died on 2026-07-20 and stayed dead for two weeks
  while this check reported green, because Composio was not probed at all.
  The pin list comes from ``configs/composio_auth_policy.json``, so a
  declared-but-unconfigured account is a finding rather than silence.
* Pure stdlib (json / datetime / urllib / sys / os) so it works on any
  Python the daily runner provisions.
* Returns a structured report on stdout (JSON) and exits 0 / 1 / 2:
    0 = all probes ok
    1 = configuration error (no probes ran; treat as ::error::)
    2 = one or more probes warn or fail (treat as ::warning:: / ::error::
        based on the severity field in the report)
* Designed to be parsable by the daily workflow which converts the report
  to ``::warning::`` / ``::error::`` annotations and (optionally) opens an
  issue with the ``cron-failure`` label.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import gzip
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# Warn at 80% of TTL, fail (error) at 100%.
WARN_FRACTION = 0.80


@dataclass
class ProbeResult:
    name: str
    severity: str  # "ok" | "warn" | "error"
    message: str
    details: dict[str, Any] = field(default_factory=dict)


# Per-request HTTP budget for the credential probes.
#
# 2026-08-04 (#4382): hist.databento.com answers its metadata calls with a
# bimodal time-to-first-byte. Measured that morning against the production key,
# 5 samples: TTFB 0.44s / 0.90s / 17.4s / 24.3s / 29.4s, while TCP connect was
# 0.12s, TLS 0.24s and the payload 14 KB — so the wait is server-side, neither
# the network nor the response size. Against a single 10s attempt a *valid*
# key came back as `warn` and filed a cron issue on four separate days (#4382,
# #4196, #4075, #3804), and in each of them the SECOND Databento probe of the
# same run was `ok`. Nothing was ever wrong with the credential.
#
# Two levers, both measured: give Databento a timeout that covers its observed
# slow branch, and re-roll the inconclusive network/timeout class once. Keep
# both small — the daily cron probes ~14 endpoints serially inside one job
# timeout, and tests/test_credential_probe_consumers.py holds that arithmetic.
HTTP_TIMEOUT_SECONDS = 10.0
DATABENTO_TIMEOUT_SECONDS = 30.0
TRANSIENT_RETRY_ATTEMPTS = 2
TRANSIENT_RETRY_SLEEP_SECONDS = 1.0


def _open_with_transient_retry(opener: Any, req: Any, *, timeout: float) -> Any:
    """Open ``req``, re-rolling only the inconclusive network/timeout class.

    ``urllib.error.HTTPError`` subclasses ``URLError`` but carries a real
    server verdict (401 revoked, 402 unpaid, 429 quota, 5xx outage). Those are
    answers, not flakes — they are re-raised on the first attempt so the
    severity mapping and the operator's wall clock stay untouched.
    """
    last_exc: BaseException = TimeoutError("no attempt was made")
    for attempt in range(TRANSIENT_RETRY_ATTEMPTS):
        try:
            return opener.open(req, timeout=timeout)  # nosec B310 - URL is literal per call site
        except urllib.error.HTTPError:
            raise
        except (urllib.error.URLError, TimeoutError) as exc:
            last_exc = exc
            if attempt + 1 < TRANSIENT_RETRY_ATTEMPTS:
                time.sleep(TRANSIENT_RETRY_SLEEP_SECONDS)
    raise last_exc


def _parse_iso(value: str) -> datetime | None:
    """Permissive ISO-8601 parse — returns None on any failure."""
    try:
        # ``datetime.fromisoformat`` in 3.11+ handles trailing "Z".
        if value.endswith("Z"):
            value = value[:-1] + "+00:00"
        if value.endswith(" UTC"):
            return datetime.strptime(value, "%Y-%m-%d %H:%M:%S UTC").replace(tzinfo=UTC)
        dt = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _loads_tv_storage_state(payload: str) -> Any:
    """Load TV storage_state from plain JSON or gzip+base64 JSON."""
    try:
        return json.loads(payload)
    except json.JSONDecodeError:
        try:
            decoded = gzip.decompress(base64.b64decode(payload.strip(), validate=True)).decode("utf-8")
            return json.loads(decoded)
        except (binascii.Error, gzip.BadGzipFile, OSError, UnicodeDecodeError, json.JSONDecodeError) as decode_exc:
            raise ValueError(
                "storage_state is not valid JSON and gzip+base64 decode failed "
                f"({_storage_state_decode_failure_reason(decode_exc)})"
            ) from decode_exc


def _storage_state_decode_failure_reason(exc: Exception) -> str:
    """Return a payload-free decode diagnostic for operator debugging."""
    if isinstance(exc, json.JSONDecodeError):
        return f"JSONDecodeError at line {exc.lineno} column {exc.colno}"
    if isinstance(exc, UnicodeDecodeError):
        return f"UnicodeDecodeError at byte {exc.start}"
    return type(exc).__name__


def probe_tv_storage_state(
    payload: str,
    max_age_hours: float,
    now: datetime | None = None,
) -> ProbeResult:
    """Probe a TradingView storage_state JSON payload.

    The payload may be raw JSON or gzip+base64 encoded JSON, matching
    ``tradingview-storage-refresh.yml`` and ``smc-library-refresh.yml``.
    The decoded storage state is expected to contain ``meta.authValidatedAt``
    as an ISO-8601 UTC timestamp (the same field consumed by
    automation/tradingview/lib/tv_validation_model.ts).
    """
    now = now or datetime.now(UTC)
    name = "tv_storage_state_age"

    try:
        data = _loads_tv_storage_state(payload)
    except ValueError as exc:
        return ProbeResult(name, "error", str(exc))

    meta = data.get("meta") if isinstance(data, dict) else None
    if not isinstance(meta, dict):
        return ProbeResult(name, "error", "storage_state missing meta block")

    validated_at_raw = meta.get("authValidatedAt")
    if not isinstance(validated_at_raw, str) or not validated_at_raw.strip():
        return ProbeResult(
            name,
            "error",
            "storage_state missing meta.authValidatedAt — cannot determine age",
        )

    validated_at = _parse_iso(validated_at_raw.strip())
    if validated_at is None:
        return ProbeResult(
            name,
            "error",
            f"storage_state meta.authValidatedAt is not a valid ISO-8601 timestamp: {validated_at_raw!r}",
        )

    age_hours = (now - validated_at).total_seconds() / 3600.0
    details = {
        "validated_at": validated_at.isoformat(),
        "age_hours": round(age_hours, 2),
        "max_age_hours": max_age_hours,
        "warn_at_hours": round(max_age_hours * WARN_FRACTION, 2),
    }

    if age_hours >= max_age_hours:
        return ProbeResult(
            name,
            "error",
            f"TV storage_state is STALE ({age_hours:.1f}h ≥ {max_age_hours}h refresh TTL, NOT the real cookie expiry) — the login may still be valid, but the publish preflight enforces the same TTL and rejects it; re-capture the storage-state",
            details,
        )
    if age_hours >= max_age_hours * WARN_FRACTION:
        return ProbeResult(
            name,
            "warn",
            f"TV storage_state is approaching the {max_age_hours}h refresh TTL ({age_hours:.1f}h ≥ {max_age_hours * WARN_FRACTION:.1f}h; TTL is self-imposed, login likely still valid) — schedule a re-capture",
            details,
        )
    return ProbeResult(
        name,
        "ok",
        f"TV storage_state cookie age {age_hours:.1f}h (TTL {max_age_hours}h)",
        details,
    )


def probe_github_pat(token: str, opener: Any = None) -> ProbeResult:
    """Probe a GitHub PAT by hitting the /user endpoint.

    Surfaces token-expiry / scope / rate-limit issues. Uses
    ``urllib.request`` to avoid pulling ``requests`` into the runner.
    """
    name = "github_pat_validity"
    if not token or not token.strip():
        return ProbeResult(
            name,
            "error",
            "GH_PAT secret is empty or missing — bot/* push + gh pr create will fail",
        )

    req = urllib.request.Request(
        "https://api.github.com/user",
        headers={
            "Authorization": f"Bearer {token.strip()}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "skipp-algo-credential-health-check/1",
        },
    )
    _opener = opener or urllib.request.build_opener()
    try:
        with _open_with_transient_retry(_opener, req, timeout=HTTP_TIMEOUT_SECONDS) as resp:
            status = resp.getcode()
            github_token_expiration = (
                resp.headers.get("github-authentication-token-expiration")
                or resp.headers.get("GitHub-Authentication-Token-Expiration")
            )
            body = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        return ProbeResult(
            name,
            "error",
            f"GH_PAT rejected by api.github.com (HTTP {exc.code} — token expired, revoked, or scope insufficient)",
            {"status": exc.code, "reason": exc.reason},
        )
    except (urllib.error.URLError, TimeoutError) as exc:
        return ProbeResult(
            name,
            "warn",
            f"could not reach api.github.com: {exc} — probe inconclusive (network / GitHub status)",
        )

    details: dict[str, Any] = {"status": status}
    try:
        details["login"] = json.loads(body).get("login")
    except json.JSONDecodeError:
        pass

    if not github_token_expiration:
        return ProbeResult(
            name,
            "ok",
            f"GH_PAT valid (login={details.get('login')!r}, no expiry header — likely fine-grained or no-expiry PAT)",
            details,
        )

    expires_at = _parse_iso(github_token_expiration.strip())
    if expires_at is None:
        return ProbeResult(
            name,
            "warn",
            f"GH_PAT valid but expiry header unparseable: {github_token_expiration!r}",
            details,
        )

    days_left = (expires_at - datetime.now(UTC)).total_seconds() / 86400.0
    details["expires_at"] = expires_at.isoformat()
    details["days_left"] = round(days_left, 2)

    if days_left <= 0:
        return ProbeResult(
            name,
            "error",
            f"GH_PAT has EXPIRED ({expires_at.isoformat()}) — every workflow that uses secrets.GH_PAT is broken",
            details,
        )
    if days_left <= 7:
        return ProbeResult(
            name,
            "error",
            f"GH_PAT expires in {days_left:.1f} days ({expires_at.isoformat()}) — rotate IMMEDIATELY",
            details,
        )
    if days_left <= 30:
        return ProbeResult(
            name,
            "warn",
            f"GH_PAT expires in {days_left:.1f} days ({expires_at.isoformat()}) — schedule rotation",
            details,
        )
    return ProbeResult(
        name,
        "ok",
        f"GH_PAT valid; expires in {days_left:.1f} days",
        details,
    )


# -- Vendor-API probes ------------------------------------------------------
#
# Each vendor probe hits the lightest-weight endpoint that still exercises
# the auth path, so daily polling burns ~1 call/day against the vendor
# quota. The per-vendor error model is shared:
#
#   * empty key                  -> error (config gap; consuming jobs will fail)
#   * HTTP 401 / 403             -> error (key invalid / revoked / scope)
#   * HTTP 402                   -> error (billing problem — e.g. unpaid
#                                          invoice; Databento uses 402 for
#                                          "issue with your account payment
#                                          information". Post-mortem
#                                          2026-06-12: an unpaid Databento
#                                          invoice went unnoticed for 12 days
#                                          because 402 fell into the generic
#                                          "other -> warn" bucket.)
#   * HTTP 429                   -> warn  (rate-limit; probe inconclusive
#                                          but signals real upstream issue)
#   * HTTP 5xx                   -> warn  (vendor outage; inconclusive)
#   * network / timeout          -> warn  (inconclusive)
#   * HTTP 200                   -> ok
#   * other (e.g. 404, 422)      -> warn  (unexpected; should not happen on
#                                          the metadata endpoints we hit)
#
# This keeps "real key broken" loud (error) and noise from rate-limits or
# vendor outages quiet (warn) so a daily flap does not page the operator.


def _map_vendor_http_error(name: str, label: str, exc: urllib.error.HTTPError) -> ProbeResult:
    """Map an HTTPError from a vendor probe to the shared severity model."""
    status = exc.code
    if status == 402:
        return ProbeResult(
            name,
            "error",
            f"{label} reports a BILLING problem (HTTP 402 Payment Required) — "
            "check the vendor portal for an unpaid invoice / failed payment NOW",
            {"status": status, "reason": exc.reason},
        )
    if status in (401, 403):
        return ProbeResult(
            name,
            "error",
            f"{label} rejected the API key (HTTP {status} {exc.reason}) — rotate the secret",
            {"status": status, "reason": exc.reason},
        )
    if status == 429:
        # urllib.error.HTTPError carries headers on .headers directly;
        # httpx/requests exceptions carry them on .response.headers.
        _hdrs = getattr(exc, "headers", None) or getattr(
            getattr(exc, "response", None), "headers", None
        )
        retry_after: str | None = _hdrs.get("Retry-After") if _hdrs is not None else None
        # Retry-After can be seconds (integer string) or an HTTP-date.
        # Only append the 's' unit when the value is a plain integer.
        retry_after_display = (
            f"{retry_after}s" if retry_after and retry_after.isdigit() else retry_after
        )
        return ProbeResult(
            name,
            "warn",
            f"{label} rate-limited the probe (HTTP 429) — probe inconclusive, but quota pressure is real"
            + (f"; Retry-After={retry_after_display}" if retry_after_display else ""),
            {"status": status, "retry_after": retry_after or "unknown"},
        )
    if 500 <= status < 600:
        return ProbeResult(
            name,
            "warn",
            f"{label} returned HTTP {status} — vendor-side issue, probe inconclusive",
            {"status": status},
        )
    return ProbeResult(
        name,
        "warn",
        f"{label} returned unexpected HTTP {status} ({exc.reason}) — probe inconclusive",
        {"status": status, "reason": exc.reason},
    )


def _probe_http_vendor(
    *,
    name: str,
    label: str,
    key: str,
    url: str,
    headers: dict[str, str],
    opener: Any = None,
    timeout: float = HTTP_TIMEOUT_SECONDS,
) -> ProbeResult:
    """Generic vendor-credential probe.

    ``label`` is the human-readable vendor name used in the message
    (e.g. "Databento", "FMP", "NewsAPI"). ``headers`` MUST already
    contain the authenticated form of ``key`` — the caller decides
    whether the key goes in Basic-Auth, a query param, or a header.
    ``key`` is checked only for empty/whitespace before the request.
    """
    if not key or not key.strip():
        return ProbeResult(
            name,
            "error",
            f"{label} API key secret is empty or missing — consuming jobs will fail",
        )

    base_headers = {"User-Agent": "skipp-algo-credential-health-check/1"}
    base_headers.update(headers)
    req = urllib.request.Request(url, headers=base_headers)
    _opener = opener or urllib.request.build_opener()
    try:
        with _open_with_transient_retry(_opener, req, timeout=timeout) as resp:
            status = resp.getcode()
    except urllib.error.HTTPError as exc:
        return _map_vendor_http_error(name, label, exc)
    except (urllib.error.URLError, TimeoutError) as exc:
        return ProbeResult(
            name,
            "warn",
            f"could not reach {label}: {exc} — probe inconclusive (network / vendor status)",
        )

    if status == 200:
        return ProbeResult(
            name,
            "ok",
            f"{label} API key valid (HTTP 200)",
            {"status": status},
        )
    # 2xx other than 200 from a metadata endpoint is unexpected.
    return ProbeResult(
        name,
        "warn",
        f"{label} returned HTTP {status} — unexpected, probe inconclusive",
        {"status": status},
    )


def probe_databento(key: str, opener: Any = None) -> ProbeResult:
    """Probe a Databento API key against the metadata endpoint.

    ``list_publishers`` is a free, low-quota metadata call. Auth is
    HTTP Basic with the API key as the username and an empty password.
    """
    import base64

    token = base64.b64encode(f"{key.strip()}:".encode()).decode("ascii") if key and key.strip() else ""
    return _probe_http_vendor(
        name="databento_api_key",
        label="Databento",
        key=key,
        url="https://hist.databento.com/v0/metadata.list_publishers",
        headers={"Authorization": f"Basic {token}"} if token else {},
        opener=opener,
        timeout=DATABENTO_TIMEOUT_SECONDS,
    )


# Canonical end-of-day source included in US Equities Standard.
DATABENTO_DELIVERY_DATASET = "EQUS.SUMMARY"
# EQUS.SUMMARY advances after each completed session; weekends and holidays can stack to
# ~4 calendar days without new data. 5 days of silence is a real problem
# (e.g. account suspended for non-payment while metadata auth still works).
DATABENTO_DELIVERY_MAX_STALENESS_DAYS = 5.0


def probe_databento_delivery(
    key: str,
    opener: Any = None,
    *,
    dataset: str = DATABENTO_DELIVERY_DATASET,
    max_staleness_days: float = DATABENTO_DELIVERY_MAX_STALENESS_DAYS,
    now: datetime | None = None,
    timeout: float = DATABENTO_TIMEOUT_SECONDS,
) -> ProbeResult:
    """Probe Databento DELIVERY health, not just auth.

    Post-mortem 2026-06-12: an unpaid Databento invoice went unnoticed for
    12 days. ``list_publishers`` keeps returning HTTP 200 with broken
    billing, so the key probe alone cannot catch a suspended account.
    This probe calls ``metadata.get_dataset_range`` (free metadata call)
    for the canonical EOD dataset and alarms when its
    available ``end`` date stops advancing — the symptom of an account
    that silently stopped receiving data.
    """
    import base64

    name = "databento_delivery"
    label = "Databento"
    now = now or datetime.now(UTC)

    if not key or not key.strip():
        return ProbeResult(
            name,
            "error",
            f"{label} API key secret is empty or missing — cannot probe delivery",
        )

    token = base64.b64encode(f"{key.strip()}:".encode()).decode("ascii")
    query = urllib.parse.urlencode({"dataset": dataset})
    url = f"https://hist.databento.com/v0/metadata.get_dataset_range?{query}"
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "skipp-algo-credential-health-check/1",
            "Authorization": f"Basic {token}",
        },
    )
    _opener = opener or urllib.request.build_opener()
    try:
        with _open_with_transient_retry(_opener, req, timeout=timeout) as resp:
            status = resp.getcode()
            body = resp.read()
    except urllib.error.HTTPError as exc:
        return _map_vendor_http_error(name, label, exc)
    except (urllib.error.URLError, TimeoutError) as exc:
        return ProbeResult(
            name,
            "warn",
            f"could not reach {label}: {exc} — probe inconclusive (network / vendor status)",
        )

    if status != 200:
        return ProbeResult(
            name,
            "warn",
            f"{label} returned HTTP {status} on get_dataset_range — unexpected, probe inconclusive",
            {"status": status},
        )

    try:
        payload = json.loads(body)
        end_raw = payload.get("end") if isinstance(payload, dict) else None
    except (json.JSONDecodeError, UnicodeDecodeError):
        end_raw = None
    end = _parse_iso(end_raw) if isinstance(end_raw, str) else None
    if end is None:
        return ProbeResult(
            name,
            "warn",
            f"{label} get_dataset_range({dataset}) returned no parseable 'end' date — probe inconclusive",
            {"status": status},
        )

    staleness_days = (now - end).total_seconds() / 86400.0
    details = {
        "dataset": dataset,
        "end": end.isoformat(),
        "staleness_days": round(staleness_days, 2),
        "max_staleness_days": max_staleness_days,
    }
    if staleness_days > max_staleness_days:
        return ProbeResult(
            name,
            "error",
            f"{label} dataset {dataset} stopped advancing — last available data "
            f"{end.date().isoformat()} ({staleness_days:.1f}d ago, threshold "
            f"{max_staleness_days:.0f}d). Check billing (unpaid invoice suspends "
            "delivery) and entitlement in the Databento portal",
            details,
        )
    return ProbeResult(
        name,
        "ok",
        f"{label} delivering: {dataset} end={end.date().isoformat()} ({staleness_days:.1f}d old)",
        details,
    )


def probe_fmp(key: str, opener: Any = None) -> ProbeResult:
    """Probe a Financial-Modeling-Prep API key.

    Uses ``/stable/quote?symbol=AAPL`` — the endpoint family the
    production pipeline actually depends on (counts as one call
    against the daily quota).  The previous probe endpoint
    ``/stable/is-the-market-open`` is plan-gated and returns HTTP 404
    *with a valid key* on this subscription (observed 2026-06-11,
    issue #2682), making every probe inconclusive.  The legacy
    ``/api/v3/`` path was retired by FMP on 2025-08-31 and returns
    HTTP 403 for non-legacy subscriptions.
    """
    safe_key = (key or "").strip()
    query = urllib.parse.urlencode({"symbol": "AAPL", "apikey": safe_key})
    url = f"https://financialmodelingprep.com/stable/quote?{query}"
    return _probe_http_vendor(
        name="fmp_api_key",
        label="FMP",
        key=key,
        url=url,
        headers={},
        opener=opener,
    )


def probe_benzinga(key: str, opener: Any = None) -> ProbeResult:
    """Probe a Benzinga News API key (load-bearing since 2026-07-08:
    open_prep Core News lane + hourly live-news cron both depend on it).

    Transport follows ``BENZINGA_PROVIDER`` (mirrors
    ``newsstack_fmp.ingest_benzinga.benzinga_provider``): ``massive`` probes
    the Massive reseller route with ``apiKey=`` (the paid key is a Massive
    key — api.benzinga.com answers it 401 "anonymous", verified 2026-07-09);
    ``direct`` keeps the legacy ``token=`` call. Cheapest authenticated call
    on either route (one news item).
    """
    safe_key = key.strip() if key else ""
    provider = os.getenv("BENZINGA_PROVIDER", "direct").strip().lower()
    if provider == "massive":
        url = f"https://api.massive.com/benzinga/v2/news?apiKey={safe_key}&limit=1"
    else:
        url = f"https://api.benzinga.com/api/v2/news?token={safe_key}&pageSize=1&displayOutput=abstract"
    return _probe_http_vendor(
        name="benzinga_key",
        label="Benzinga News API" + (" (via Massive)" if provider == "massive" else ""),
        key=key,
        url=url,
        headers={"Accept": "application/json"},
        opener=opener,
    )


def probe_finnhub(key: str, opener: Any = None) -> ProbeResult:
    """Probe a Finnhub API key.

    Uses ``/quote?symbol=AAPL`` — the cheapest authenticated call and the
    endpoint family ``terminal_finnhub`` / ``open_prep.macro`` depend on.
    Finnhub returns HTTP 401 for an invalid/revoked token. Finnhub is an
    optional provider: ``main`` only invokes this probe when the key is
    configured, so an unset ``FINNHUB_API_KEY`` never fails the daily cron.
    """
    safe_key = (key or "").strip()
    query = urllib.parse.urlencode({"symbol": "AAPL", "token": safe_key})
    url = f"https://finnhub.io/api/v1/quote?{query}"
    return _probe_http_vendor(
        name="finnhub_api_key",
        label="Finnhub",
        key=key,
        url=url,
        headers={"Accept": "application/json"},
        opener=opener,
    )


def probe_newsapi(key: str, opener: Any = None) -> ProbeResult:
    """Probe a NewsAPI (Event Registry / newsapi.ai) key.

    Uses the ``/api/v1/article/getArticles`` endpoint with
    ``articlesCount=1`` — the cheapest authenticated call.
    Auth is via the ``apiKey`` query parameter (not a header).
    """
    safe_key = key.strip() if key else ""
    return _probe_http_vendor(
        name="newsapi_key",
        label="NewsAPI (Event Registry)",
        key=key,
        url=f"https://eventregistry.org/api/v1/article/getArticles?apiKey={safe_key}&resultType=articles&articlesCount=1",
        headers={},
        opener=opener,
    )


COMPOSIO_AUTH_POLICY_PATH = Path(__file__).resolve().parents[1] / "configs" / "composio_auth_policy.json"
COMPOSIO_HEALTHY_STATUS = "ACTIVE"


def _composio_declared_pins(policy_path: Path | None = None) -> list[tuple[str, str]]:
    """Return the ``(toolkit, access)`` pairs the repo declares it depends on.

    Driven by ``configs/composio_auth_policy.json`` rather than by scanning
    the environment. That direction is the whole point: an account pin that
    is *supposed* to exist but was never configured is a finding, and an
    env-scan would render exactly that case invisible.
    """
    path = policy_path or COMPOSIO_AUTH_POLICY_PATH
    with path.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    configs = payload.get("auth_configs")
    if not isinstance(configs, dict):
        return []
    pins: list[tuple[str, str]] = []
    for key in configs:
        toolkit, _, access = str(key).rpartition("_")
        if toolkit and access in {"read", "write"}:
            pins.append((toolkit, access))
    return sorted(set(pins))


def _composio_account_result(
    *,
    name: str,
    toolkit: str,
    access: str,
    account_id: str,
    payload: Any,
) -> ProbeResult:
    """Turn one connected-account payload into a ProbeResult."""
    if not isinstance(payload, dict):
        return ProbeResult(
            name,
            "warn",
            f"Composio returned an unreadable body for {toolkit}/{access} — probe inconclusive",
            {"account_id": account_id},
        )
    status = str(payload.get("status") or "").upper()
    disabled = bool(payload.get("is_disabled"))
    reason = payload.get("status_reason")
    live_toolkit = payload.get("toolkit")
    live_slug = str(live_toolkit.get("slug") or "").lower() if isinstance(live_toolkit, dict) else ""
    details = {
        "account_id": account_id,
        "toolkit": toolkit,
        "access": access,
        "status": status or "unknown",
        "is_disabled": disabled,
        "status_reason": reason,
    }
    if live_slug and live_slug != toolkit.lower():
        return ProbeResult(
            name,
            "error",
            f"Composio account pin for {toolkit}/{access} points at a '{live_slug}' account "
            f"({account_id}) — COMPOSIO_{toolkit.upper()}_{access.upper()}_ACCOUNT_ID is wired to the wrong toolkit",
            {**details, "live_toolkit": live_slug},
        )
    if disabled:
        return ProbeResult(
            name,
            "error",
            f"Composio account {toolkit}/{access} ({account_id}) is DISABLED — "
            "re-enable it in the Composio dashboard; consuming automations fail with HTTP 410",
            details,
        )
    if status != COMPOSIO_HEALTHY_STATUS:
        return ProbeResult(
            name,
            "error",
            f"Composio account {toolkit}/{access} ({account_id}) is in {status or 'UNKNOWN'} state"
            + (f" ({reason})" if reason else "")
            + " — re-authorise the connection in Composio; consuming automations fail with HTTP 410",
            details,
        )
    return ProbeResult(
        name,
        "ok",
        f"Composio account {toolkit}/{access} is {COMPOSIO_HEALTHY_STATUS}",
        details,
    )


def probe_composio_accounts(
    api_key: str,
    *,
    pins: list[tuple[str, str]],
    account_ids: dict[tuple[str, str], str],
    base_url: str,
    opener: Any = None,
    timeout: float = HTTP_TIMEOUT_SECONDS,
) -> list[ProbeResult]:
    """Probe every declared Composio connected account for liveness.

    Auth alone is not the failure mode worth catching here. A Composio
    project API key keeps working while an individual OAuth *connection*
    expires underneath it, and every consuming automation then fails with
    ``HTTP 410 ... is in EXPIRED state`` — which is exactly how the weekly
    Notion digest died unnoticed between 2026-07-13 and 2026-08-03 while
    this very check reported green, because it probed no Composio surface
    at all.

    ``pins`` comes from the repo's auth policy, so a declared-but-unset
    account pin surfaces as an error rather than as silence.
    """
    if not pins:
        return [
            ProbeResult(
                "composio_accounts",
                "error",
                "Composio auth policy declares no connected accounts — this probe would "
                "report green while verifying nothing",
            )
        ]
    if not api_key or not api_key.strip():
        return [
            ProbeResult(
                "composio_accounts",
                "error",
                f"Composio API key is empty or missing — {len(pins)} declared connected-account "
                "pins are UNVERIFIED (an expired connection would stay invisible)",
                {"declared_pins": len(pins)},
            )
        ]

    _opener = opener or urllib.request.build_opener()
    results: list[ProbeResult] = []
    for toolkit, access in pins:
        name = f"composio_account_{toolkit}_{access}"
        account_id = (account_ids.get((toolkit, access)) or "").strip()
        if not account_id:
            results.append(
                ProbeResult(
                    name,
                    "error",
                    f"auth policy declares {toolkit}/{access} but "
                    f"COMPOSIO_{toolkit.upper()}_{access.upper()}_ACCOUNT_ID is unset — "
                    "that connection is unprobed and unusable",
                    {"toolkit": toolkit, "access": access},
                )
            )
            continue
        url = f"{base_url.rstrip('/')}/api/v3/connected_accounts/{urllib.parse.quote(account_id, safe='')}"
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "skipp-algo-credential-health-check/1",
                "x-api-key": api_key.strip(),
            },
        )
        try:
            with _open_with_transient_retry(_opener, req, timeout=timeout) as resp:
                status = resp.getcode()
                body = resp.read()
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                results.append(
                    ProbeResult(
                        name,
                        "error",
                        f"Composio does not know account {account_id} pinned for {toolkit}/{access} "
                        "(HTTP 404) — the pin is stale or points at another project",
                        {"account_id": account_id, "toolkit": toolkit, "access": access},
                    )
                )
            else:
                results.append(_map_vendor_http_error(name, f"Composio ({toolkit}/{access})", exc))
            continue
        except (urllib.error.URLError, TimeoutError) as exc:
            results.append(
                ProbeResult(
                    name,
                    "warn",
                    f"could not reach Composio for {toolkit}/{access}: {exc} — probe inconclusive",
                    {"account_id": account_id},
                )
            )
            continue

        if status != 200:
            results.append(
                ProbeResult(
                    name,
                    "warn",
                    f"Composio returned HTTP {status} for {toolkit}/{access} — probe inconclusive",
                    {"status": status, "account_id": account_id},
                )
            )
            continue
        try:
            payload = json.loads(body)
        except (json.JSONDecodeError, UnicodeDecodeError):
            payload = None
        results.append(
            _composio_account_result(
                name=name,
                toolkit=toolkit,
                access=access,
                account_id=account_id,
                payload=payload,
            )
        )
    return results


def _build_report(results: list[ProbeResult]) -> dict[str, Any]:
    severities = [r.severity for r in results]
    if "error" in severities:
        overall = "error"
    elif "warn" in severities:
        overall = "warn"
    else:
        overall = "ok"
    return {
        "schema_version": "1",
        "generated_at": datetime.now(UTC).isoformat(),
        "overall_severity": overall,
        "probes": [asdict(r) for r in results],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else "")
    parser.add_argument(
        "--tv-storage-state-secret-env",
        default="TV_STORAGE_STATE",
        help=(
            "Env var name holding TV storage_state as raw JSON or gzip+base64 JSON "
            "(default: TV_STORAGE_STATE)"
        ),
    )
    parser.add_argument(
        "--tv-max-age-hours",
        type=float,
        default=72.0,
        help="TTL the consuming workflow enforces (default: 72.0 — keep in sync with smc-library-refresh.yml)",
    )
    parser.add_argument(
        "--gh-pat-env",
        default="GH_PAT",
        help="Env var name holding the GitHub PAT to probe (default: GH_PAT)",
    )
    parser.add_argument(
        "--skip-tv",
        action="store_true",
        help="Skip the TV storage_state probe (useful for testing the workflow with no TV secret yet)",
    )
    parser.add_argument(
        "--skip-gh-pat",
        action="store_true",
        help="Skip the GitHub PAT probe (offline mode)",
    )
    parser.add_argument(
        "--databento-key-env",
        default="DATABENTO_API_KEY",
        help="Env var name holding the Databento API key (default: DATABENTO_API_KEY)",
    )
    parser.add_argument(
        "--skip-databento",
        action="store_true",
        help="Skip the Databento API-key probe",
    )
    parser.add_argument(
        "--fmp-key-env",
        default="FMP_API_KEY",
        help="Env var name holding the Financial-Modeling-Prep API key (default: FMP_API_KEY)",
    )
    parser.add_argument(
        "--skip-fmp",
        action="store_true",
        help="Skip the FMP API-key probe",
    )
    parser.add_argument(
        "--newsapi-key-env",
        default="NEWSAPI_KEY",
        help="Env var name holding the NewsAPI key (default: NEWSAPI_KEY)",
    )
    parser.add_argument(
        "--skip-newsapi",
        action="store_true",
        help="Skip the NewsAPI key probe",
    )
    parser.add_argument(
        "--benzinga-key-env",
        default="BENZINGA_API_KEY",
        help="Env var name holding the Benzinga key (default: BENZINGA_API_KEY)",
    )
    parser.add_argument(
        "--skip-benzinga",
        action="store_true",
        help="Skip the Benzinga News API key probe",
    )
    parser.add_argument(
        "--finnhub-key-env",
        default="FINNHUB_API_KEY",
        help="Env var name holding the Finnhub key (default: FINNHUB_API_KEY)",
    )
    parser.add_argument(
        "--skip-finnhub",
        action="store_true",
        help="Skip the Finnhub API-key probe",
    )
    parser.add_argument(
        "--skip-composio",
        action="store_true",
        help="Skip the Composio connected-account probes",
    )
    parser.add_argument(
        "--composio-auth-policy",
        default=str(COMPOSIO_AUTH_POLICY_PATH),
        help=(
            "Path to the auth policy declaring which connected accounts must exist "
            f"(default: {COMPOSIO_AUTH_POLICY_PATH.name})"
        ),
    )
    parser.add_argument(
        "--output",
        help="Write JSON report to this path (in addition to stdout)",
    )
    args = parser.parse_args(argv)

    results: list[ProbeResult] = []

    if not args.skip_tv:
        tv_secret = os.environ.get(args.tv_storage_state_secret_env, "")
        if not tv_secret.strip():
            results.append(
                ProbeResult(
                    "tv_storage_state_age",
                    "error",
                    f"env {args.tv_storage_state_secret_env} is empty — cannot probe TV cookie age",
                )
            )
        else:
            results.append(probe_tv_storage_state(tv_secret, args.tv_max_age_hours))

    if not args.skip_gh_pat:
        token = os.environ.get(args.gh_pat_env, "")
        results.append(probe_github_pat(token))

    if not args.skip_databento:
        databento_key = os.environ.get(args.databento_key_env, "")
        results.append(probe_databento(databento_key))
        results.append(probe_databento_delivery(databento_key))

    if not args.skip_fmp:
        results.append(probe_fmp(os.environ.get(args.fmp_key_env, "")))

    if not args.skip_newsapi:
        results.append(probe_newsapi(os.environ.get(args.newsapi_key_env, "")))

    if not args.skip_benzinga:
        results.append(probe_benzinga(os.environ.get(args.benzinga_key_env, "")))

    if not args.skip_finnhub:
        finnhub_key = os.environ.get(args.finnhub_key_env, "").strip()
        # Optional provider: only probe when the key is configured. An unset
        # FINNHUB_API_KEY leaves it unprobed (no gauge, no cron failure) and the
        # probe self-activates once the secret is set — unlike the core probes
        # above whose keys must always be present.
        if finnhub_key:
            results.append(probe_finnhub(finnhub_key))

    if not args.skip_composio:
        # Resolve key / base-url / account pins through composio_ops so the probe
        # reads exactly what the consuming automations read. A second, private
        # copy of that resolution is how a probe drifts into checking a surface
        # production no longer uses.
        try:  # `python scripts/foo.py` puts scripts/ on sys.path[0]
            import composio_ops
        except ImportError:  # imported as scripts.credential_health_check (pytest pythonpath=".")
            from scripts import composio_ops

        try:
            pins = _composio_declared_pins(Path(args.composio_auth_policy))
        except (OSError, json.JSONDecodeError) as exc:
            results.append(
                ProbeResult(
                    "composio_accounts",
                    "error",
                    f"could not read Composio auth policy {args.composio_auth_policy}: {exc} — "
                    "connected accounts are UNVERIFIED",
                )
            )
        else:
            results.extend(
                probe_composio_accounts(
                    composio_ops._api_key(),
                    pins=pins,
                    account_ids={
                        (toolkit, access): composio_ops._account_for_toolkit(toolkit, access) or ""
                        for toolkit, access in pins
                    },
                    base_url=composio_ops._base_url(),
                )
            )

    if not results:
        # All probes disabled. That is a configuration error.
        report = _build_report([])
        report["overall_severity"] = "error"
        report["probes"] = [
            {
                "name": "configuration",
                "severity": "error",
                "message": "all probes were skipped — credential health check produced no signal",
                "details": {},
            }
        ]
        print(json.dumps(report, indent=2))
        return 1

    report = _build_report(results)
    rendered = json.dumps(report, indent=2)
    print(rendered)
    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        # ATOMIC-WRITE-EXEMPT: monitoring probe output to operator-supplied path; not a production dataset
        Path(args.output).write_text(rendered + "\n", encoding="utf-8")

    return 0 if report["overall_severity"] == "ok" else 2


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
