"""Live probe for FMP 13F-HR endpoint discovery (G3 follow-up).

Provider-audit (2026-05-12) flagged that ``newsstack_fmp/ingest_fmp_filings.py``
defines ``FMP_13F_LATEST_PATH = "/sec-filings-13f"`` with a comment "path NOT
verified live" — the 2026-05-09 audit probed 7 candidate paths, all 404.
Subsequent research (2026-05-12) surfaced additional candidates from third-party
FMP wrappers that this script probes empirically so the audit comment can be
refreshed with ground truth.

Usage::

    FMP_API_KEY=... python -m scripts.probe_fmp_13f_endpoints

The script issues HTTP HEAD/GET requests to each candidate path with a small
parameter set, prints status codes + payload heads, and exits non-zero if no
working bulk 13F path is found. The output is intended to be pasted into the
audit comment update PR.

This is a READ-ONLY probe. It does not write artifacts, send notifications, or
mutate any state. It also does not retry: a 200 is a 200 and a 4xx is a 4xx —
this is exactly what we want for endpoint discovery.
"""

from __future__ import annotations

import json
import os
import re
import sys
from urllib.parse import urlencode
from urllib.request import Request, urlopen

# Candidate paths to probe. The first three were already in the 2026-05-09
# audit notes; the second three were surfaced from third-party FMP SDK docs on
# 2026-05-12 (PowerShell FinancialModelingPrep module, fmpcloudr R package,
# Smithery FMP skill reference) and have NOT been verified empirically.
CANDIDATES: tuple[tuple[str, dict[str, str]], ...] = (
    # Already-probed (expected 404 — kept for completeness so the output table
    # in the audit comment can show a full history)
    ("/stable/sec-filings-13f", {"page": "0", "limit": "5"}),
    ("/stable/sec-filings-13F-HR", {"page": "0", "limit": "5"}),
    ("/stable/sec-filings-form-13f", {"page": "0", "limit": "5"}),
    # New candidates surfaced 2026-05-12 — these are the priority probes
    ("/stable/institutional-ownership/dates", {}),
    ("/stable/institutional-ownership/latest", {}),
    ("/stable/form-thirteen-latest", {"page": "0", "limit": "5"}),
    # Legacy /api/v3 paths still documented by FMP
    ("/api/v3/cik_list", {}),
    ("/api/v3/form-thirteen-date/0001067983", {}),
)

BASE_STABLE = "https://financialmodelingprep.com"

# Match `apikey=<value>` in a URL query string. Tolerates URL-encoded characters
# in the key value (which `url.replace(api_key, "***")` does NOT). Anchored to
# `apikey=` so we never redact unrelated path segments.
_APIKEY_RE = re.compile(r"(apikey=)[^&\s]+", re.IGNORECASE)


def _redact_apikey(url: str) -> str:
    return _APIKEY_RE.sub(r"\1***", url)


def _build_url(path: str, params: dict[str, str], api_key: str) -> str:
    query = dict(params)
    query["apikey"] = api_key
    return f"{BASE_STABLE}{path}?{urlencode(query)}"


def _probe(path: str, params: dict[str, str], api_key: str) -> dict[str, object]:
    url = _build_url(path, params, api_key)
    sanitized = _redact_apikey(url)
    try:
        request = Request(url, headers={"User-Agent": "skipp-algo-13f-probe/1.0"})
        with urlopen(request, timeout=15.0) as response:
            status = response.status
            body = response.read(2048).decode("utf-8", errors="replace")
    except Exception as exc:
        code = getattr(exc, "code", None)
        body = ""
        if hasattr(exc, "fp") and exc.fp is not None:  # type: ignore[attr-defined]
            try:
                body = exc.fp.read(2048).decode("utf-8", errors="replace")  # type: ignore[attr-defined]
            except Exception:
                body = ""
        return {  # SECLEAK: dict carries type(exc).__name__ only; no exc.args/.message exposed
            "path": path,
            "url": sanitized,
            "status": code or "ERROR",
            "ok": False,
            "body_head": body[:200],
            "exception": type(exc).__name__,
        }
    return {
        "path": path,
        "url": sanitized,
        "status": status,
        "ok": 200 <= int(status) < 300,
        "body_head": body[:200],
    }


def main() -> int:
    api_key = os.environ.get("FMP_API_KEY") or ""
    if not api_key.strip():
        print("ERROR: FMP_API_KEY environment variable is required.", file=sys.stderr)
        return 2

    results: list[dict[str, object]] = []
    any_ok = False
    for path, params in CANDIDATES:
        result = _probe(path, params, api_key)
        results.append(result)
        if result["ok"]:
            any_ok = True
        print(
            f"{result['status']!s:>5}  {result['path']:<60}  "
            f"{str(result.get('body_head', ''))[:120]}",
        )

    print()
    print("Summary (JSON):")
    print(json.dumps(results, indent=2, default=str))
    return 0 if any_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
