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
  plus per-vendor metadata probes (Databento, FMP, NewsAPI) that burn at
  most ~1 quota call/day each. Databento additionally gets a DELIVERY
  probe (``metadata.get_dataset_range``, free): billing failures (HTTP
  402 / suspended account) keep the auth probe green while data silently
  stops flowing — post-mortem 2026-06-12, unpaid invoice unnoticed 12 days.
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
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any

# Warn at 80% of TTL, fail (error) at 100%.
WARN_FRACTION = 0.80


@dataclass
class ProbeResult:
    name: str
    severity: str  # "ok" | "warn" | "error"
    message: str
    details: dict[str, Any] = field(default_factory=dict)


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
                "storage_state is not valid JSON and gzip+base64 decode failed"
            ) from decode_exc


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
            f"TV storage_state cookie is EXPIRED ({age_hours:.1f}h ≥ {max_age_hours}h TTL) — next publish will fail at preflight",
            details,
        )
    if age_hours >= max_age_hours * WARN_FRACTION:
        return ProbeResult(
            name,
            "warn",
            f"TV storage_state cookie is approaching expiry ({age_hours:.1f}h ≥ {max_age_hours * WARN_FRACTION:.1f}h, TTL={max_age_hours}h) — schedule manual refresh",
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
        with _opener.open(req, timeout=10) as resp:  # nosec B310 - URL is literal
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
    timeout: float = 10.0,
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
        with _opener.open(req, timeout=timeout) as resp:  # nosec B310 - URL is literal per call site
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
    )


# Dataset the pipeline actually consumes (open_prep/outcome_backfill.py).
DATABENTO_DELIVERY_DATASET = "DBEQ.BASIC"
# DBEQ.BASIC is a daily dataset; weekend + market holiday can stack to
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
    timeout: float = 10.0,
) -> ProbeResult:
    """Probe Databento DELIVERY health, not just auth.

    Post-mortem 2026-06-12: an unpaid Databento invoice went unnoticed for
    12 days. ``list_publishers`` keeps returning HTTP 200 with broken
    billing, so the key probe alone cannot catch a suspended account.
    This probe calls ``metadata.get_dataset_range`` (free metadata call)
    for the dataset the pipeline consumes and alarms when the dataset's
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
        with _opener.open(req, timeout=timeout) as resp:  # nosec B310 - URL is literal
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
        from pathlib import Path

        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        # ATOMIC-WRITE-EXEMPT: monitoring probe output to operator-supplied path; not a production dataset
        Path(args.output).write_text(rendered + "\n", encoding="utf-8")

    return 0 if report["overall_severity"] == "ok" else 2


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
