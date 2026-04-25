"""Defense ledger: HTTP ``.post(...)`` egress sites.

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

Detection uses an attribute-name match on ``.post(...)`` to be
transport-agnostic. Sites where ``post`` is something other than
an HTTP method (e.g. test fixtures, dataframe ``.post(...)`` —
neither exists in this tree) would intentionally surface and
require an allow-list review.

Defense-only — no production changes.
"""

from __future__ import annotations

import ast
from pathlib import Path

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
        if any(part in _DIR_EXCLUDE or part.startswith(".") for part in rel.parts):
            continue
        out.append(path)
    return out


def _post_call_sites() -> set[tuple[str, int]]:
    """Return ``{(relpath, lineno)}`` for every ``<expr>.post(...)`` call."""

    sites: set[tuple[str, int]] = set()
    for path in _iter_py_files():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not isinstance(func, ast.Attribute):
                continue
            if func.attr != "post":
                continue
            sites.add((str(path.relative_to(ROOT)), node.lineno))
    return sites


# Locked outbound HTTP POST surface — every entry is a reviewed,
# legitimate egress edge to a known external service.
HTTP_POST_LEDGER: set[tuple[str, int]] = {
    # Notification webhook fan-out (Discord/Slack-style).
    ("terminal_notifications.py", 225),
    # FMP/news export webhook (raw body, no redirects).
    ("terminal_export.py", 874),
    # OpenAI chat completions — FMP insights enrichment.
    ("terminal_fmp_insights.py", 372),
    # Webhook fan-out from the live Streamlit terminal alert path.
    ("streamlit_terminal.py", 2275),
    # OpenAI chat completions — terminal AI insights enrichment.
    ("terminal_ai_insights.py", 245),
}


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
