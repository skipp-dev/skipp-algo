"""Pin: timeout consistency for ``httpx.Client(...)`` in
``scripts/smc_newsapi_ai.py``.

Companion to
``tests/test_newsapi_ai_client_instantiation_budget.py`` (count + guard
discipline). This pin freezes the *value* of the timeout so that
divergence (e.g. one fetch at 20.0s, another at 30.0s) cannot creep
in unnoticed — divergence usually signals an inconsistent latency
expectation across fetches and should be a code-review conversation,
not a silent edit.
"""

from __future__ import annotations

import re
from pathlib import Path

from scripts.smc_newsapi_ai import HTTPX_REQUEST_TIMEOUT_SECONDS

REPO_ROOT = Path(__file__).resolve().parent.parent
TARGET_FILE = REPO_ROOT / "scripts" / "smc_newsapi_ai.py"

# Frozen baseline: every fallback uses the shared
# ``HTTPX_REQUEST_TIMEOUT_SECONDS`` constant (45.0s as of 2026-04-30).
# The bump from 20.0s to 45.0s landed in P-7 (see
# docs/reviews/2026-04-24-system-review.md) after the live audit showed
# broad-keyword ``getArticles`` round-trips of up to ~24s.
_EXPECTED_TIMEOUT_SECONDS: float = 45.0

# Match either a numeric literal (legacy) or the named constant so the
# pin survives the constant-extraction refactor.
_TIMEOUT_RE = re.compile(
    r"httpx\.Client\s*\(\s*timeout\s*=\s*"
    r"(?P<value>[0-9]+(?:\.[0-9]+)?|HTTPX_REQUEST_TIMEOUT_SECONDS)"
)


def test_target_file_exists() -> None:
    assert TARGET_FILE.is_file(), f"Expected {TARGET_FILE} to exist."


def test_constant_matches_baseline() -> None:
    assert HTTPX_REQUEST_TIMEOUT_SECONDS == _EXPECTED_TIMEOUT_SECONDS, (
        f"HTTPX_REQUEST_TIMEOUT_SECONDS drifted from the pinned baseline: "
        f"observed={HTTPX_REQUEST_TIMEOUT_SECONDS}s, "
        f"expected={_EXPECTED_TIMEOUT_SECONDS}s. Update this pin "
        f"deliberately if the new value is intentional."
    )


def test_all_httpx_client_timeouts_match_baseline() -> None:
    text = TARGET_FILE.read_text(encoding="utf-8")
    matches = list(_TIMEOUT_RE.finditer(text))
    assert matches, (
        f"No httpx.Client(timeout=...) calls found in {TARGET_FILE}. "
        f"Either the file changed shape or the regex is stale — "
        f"investigate together with the budget pin."
    )
    drift: list[str] = []
    for m in matches:
        raw = m.group("value")
        if raw == "HTTPX_REQUEST_TIMEOUT_SECONDS":
            continue
        value = float(raw)
        if value != _EXPECTED_TIMEOUT_SECONDS:
            drift.append(f"timeout={value}s at offset {m.start()}")
    assert not drift, (
        f"httpx.Client timeout drift in {TARGET_FILE.name}: "
        f"expected HTTPX_REQUEST_TIMEOUT_SECONDS ({_EXPECTED_TIMEOUT_SECONDS}s) "
        f"for every call, got:\n"
        + "\n".join(f"  {d}" for d in drift)
        + "\nIf an asymmetric timeout is genuinely required, refactor "
        "to a named constant and update this pin to allow the new "
        "baseline + the documented exception."
    )
