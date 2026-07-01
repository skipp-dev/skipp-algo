"""Defense ledger: HTTP POST egress sites (``.post(...)`` + ``Request(method="POST")``).

Outbound HTTP POST is the canonical *write* edge of the system —
where the application sends user / market data over the network to
external services (webhooks, OpenAI, Discord). Pinning every call
site by ``(path, line)`` means a new outbound POST must be a
deliberate, reviewed change instead of a copy-paste, which gives
us a single grep-able list of all data-egress edges for review.

Why this matters:

* Every entry here is a candidate for a leak — keys, prompts,
  payloads, customer secrets — going to a URL that may or may not
  be in the allow-list.
* It catches accidentally re-using an outbound client for a new
  destination without explicit review (Discord webhook URL,
  OpenAI chat completions, FMP webhook export, terminal
  notifications).
* It also catches *transport switches* (e.g. ``requests`` instead
  of ``httpx`` / a new SDK that calls ``.post(...)``) which would
  otherwise bypass the existing ``http_client_discipline`` ledger
  for ``timeout=`` invariants.

This test pins **two** detection shapes that together cover every
POST-egress pattern present in the tree today:

1. ``<expr>.post(...)`` — attribute-name match, transport-agnostic
   (covers ``requests.post``, ``httpx.AsyncClient().post``,
   ``session.post``, OpenAI client ``.post`` shims, etc.).
2. ``urllib.request.Request(..., method="POST")`` — the low-level
   POST shape that has no ``.post(...)`` attribute call and would
   otherwise silently bypass shape (1).

Sites where ``post`` is something other than an HTTP method (e.g.
test fixtures, dataframe ``.post(...)`` — neither exists in this
tree) would intentionally surface and require an allow-list review.

Defense-only — no production changes.
"""

from __future__ import annotations

import ast
from pathlib import Path

from tests._guard_corpus import parse_module

ROOT = Path(__file__).resolve().parents[1]

_DIR_EXCLUDE = {
    ".git",
    ".github",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "venv",
    "node_modules",
    "artifacts",
    "docs",
    "tests",
    "SMC++",
    "scripts",
}


def _iter_py_files() -> list[Path]:
    out: list[Path] = []
    for path in ROOT.rglob("*.py"):
        rel = path.relative_to(ROOT)
        rel_posix = rel.as_posix()
        if (
            any(part in _DIR_EXCLUDE or part.startswith(".") for part in rel.parts)
            and rel_posix != "scripts/publish_overlay_dashboard.py"
        ):
            continue
        out.append(path)
    return out


def _post_call_sites() -> set[tuple[str, int]]:
    """Return ``{(relpath, lineno)}`` for every ``<expr>.post(...)`` call."""

    sites: set[tuple[str, int]] = set()
    for path in _iter_py_files():
        tree = parse_module(path)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not isinstance(func, ast.Attribute):
                continue
            if func.attr != "post":
                continue
            sites.add((path.relative_to(ROOT).as_posix(), node.lineno))
    return sites


def _request_method_post_sites() -> set[tuple[str, int]]:
    """Return ``{(relpath, lineno)}`` for ``Request(..., method="POST")`` calls.

    Catches the low-level ``urllib.request.Request`` POST shape that
    bypasses the ``.post(...)`` attribute-call detector. Match is on
    ``func.attr == 'Request'`` *or* ``func.id == 'Request'`` plus a
    keyword ``method="POST"`` (case-insensitive constant).
    """

    sites: set[tuple[str, int]] = set()
    for path in _iter_py_files():
        tree = parse_module(path)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = None
            if isinstance(func, ast.Attribute):
                name = func.attr
            elif isinstance(func, ast.Name):
                name = func.id
            if name != "Request":
                continue
            for kw in node.keywords:
                if kw.arg != "method":
                    continue
                v = kw.value
                if isinstance(v, ast.Constant) and isinstance(v.value, str) and v.value.upper() == "POST":
                    sites.add((path.relative_to(ROOT).as_posix(), node.lineno))
                    break
    return sites


# Locked outbound HTTP POST surface — every entry is a reviewed,
# legitimate egress edge to a known external service.
HTTP_POST_LEDGER: set[tuple[str, int]] = {
    # Notification webhook fan-out (Discord/Slack-style).
    ("terminal_notifications.py", 279),
    # FMP/news export webhook (raw body, no redirects, HMAC-SHA256 signed,
    # SSRF-guarded via _is_safe_webhook_url). Line shifted 912 → 916
    # (deep-audit fallback-buffer lock refresh).
    ("terminal_export.py", 916),
    # OpenAI chat completions — FMP insights enrichment.
    # Line shifted 402 → 409 (main merge for PR-J3 cache-key scoping).
    ("terminal_fmp_insights.py", 409),
    # Webhook fan-out from the live Streamlit terminal alert path
    # (httpx, follow_redirects=False, timeout=5s, dedup + budget cap).
    # Line shifted 2257 → 2274 (system review 2026-04-30).
    ("streamlit_terminal.py", 2306),
    # OpenAI chat completions — terminal AI insights enrichment.
    # Line shifted 276 → 283 (main merge for PR-J3 cache-key scoping).
    ("terminal_ai_insights.py", 283),
    # Databento BentoHttpAPI._post TLS-override patch (F1 dedup, 2026-06-14):
    # both calls are internal Databento SDK POST paths using trust_env=False
    # + certifi CA bundle. Auth via HTTPBasicAuth(api_key, "").
    ("databento_client.py", 293),
    ("databento_client.py", 316),
}


# Locked low-level POST surface — `urllib.request.Request(..., method="POST")`
# sites that bypass the .post(...) attribute-call detector above.
URLLIB_REQUEST_POST_LEDGER: set[tuple[str, int]] = {
    # Generic POST webhook helper (Slack/Discord-shape).
    ("terminal_notifications.py", 251),
    # Pushover messages API.
    ("terminal_notifications.py", 316),
    # Open-prep alerts dispatcher (Slack/webhook).
    # 2026-07-01: alert candidate/throttle hardening + payload/url guards
    # shifted 439 -> 476.
    # 2026-07-02: SSRF path/query hardening inserted helper logic;
    # POST Request line shifted 476 -> 512.
    # 2026-07-02: generic-payload finite-normalization shifted POST 512 -> 514.
    ("open_prep/alerts.py", 514),
    # 2026-06-21: UptimeRobot bridge polls monitor API with low-level
    # urllib.request.Request(..., method="POST") + timeout discipline.
    ("services/live_overlay_daemon/uptimerobot_bridge.py", 84),
    # 2026-06-24: Railway GraphQL API for container metrics polling.
    ("services/live_overlay_daemon/railway_metrics.py", 74),
    # 2026-06-22: the Grafana dashboard publisher previously pinned here as a
    # literal Request(method="POST"). ADR-0025 consolidated its GET/POST/PUT
    # egress into a single method-agnostic urllib.request.Request in
    # _request_json (no literal method="POST"), so it is no longer detectable
    # by this literal-POST shape. Its single urlopen transport edge stays
    # pinned via the urllib_urlopen ledger (pin_registry.toml) +
    # http_client_discipline at scripts/publish_overlay_dashboard.py:287.
}


def test_http_post_inventory_sane() -> None:
    files = _iter_py_files()
    assert len(files) >= 50, (
        f"first-party python file count collapsed to {len(files)} — "
        "the AST scan is likely seeing an empty tree, which would let "
        "new outbound POST callers slip in unnoticed."
    )


def test_urllib_request_method_post_ledger_pin() -> None:
    sites = _request_method_post_sites()

    unexpected = sites - URLLIB_REQUEST_POST_LEDGER
    assert not unexpected, (
        "New ``Request(..., method=\"POST\")`` call site detected. "
        "This low-level POST shape bypasses the ``.post(...)`` ledger "
        "above and is the second canonical egress path. If this is a "
        "legitimate new outbound POST, append the (path, line) tuple "
        "to URLLIB_REQUEST_POST_LEDGER and document the destination + "
        "auth posture in the commit message.\n"
        f"unexpected = {sorted(unexpected)}"
    )

    missing = URLLIB_REQUEST_POST_LEDGER - sites
    assert not missing, (
        "URLLIB_REQUEST_POST_LEDGER entries no longer present at the "
        "recorded (path, line). Update the ledger to match the current "
        "call sites and verify the underlying egress destination is "
        "unchanged.\n"
        f"missing = {sorted(missing)}"
    )


def test_http_post_egress_ledger_pin() -> None:
    sites = _post_call_sites()

    unexpected = sites - HTTP_POST_LEDGER
    assert not unexpected, (
        "New ``.post(...)`` call site detected. Outbound HTTP POST is "
        "the canonical write-edge of the system — every new caller is "
        "a candidate data-egress leak (API keys, prompts, payloads). "
        "If this is a legitimate new outbound POST, append the "
        "(path, line) tuple to HTTP_POST_LEDGER and document the "
        "destination + auth posture in the commit message. If this is "
        "NOT an HTTP POST (e.g. an unrelated ``.post`` method on a "
        "different object), rename the method or refactor to avoid "
        "ambiguity with the egress ledger.\n"
        f"unexpected = {sorted(unexpected)}"
    )

    missing = HTTP_POST_LEDGER - sites
    assert not missing, (
        "HTTP_POST_LEDGER entries no longer present at the recorded "
        "(path, line). The line numbers below have shifted upstream — "
        "update the ledger to match the current call sites and verify "
        "the underlying egress destination is unchanged.\n"
        f"missing = {sorted(missing)}"
    )
