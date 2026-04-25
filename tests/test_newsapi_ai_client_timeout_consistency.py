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

REPO_ROOT = Path(__file__).resolve().parent.parent
TARGET_FILE = REPO_ROOT / "scripts" / "smc_newsapi_ai.py"

# Frozen baseline: every fallback uses timeout=20.0.
_EXPECTED_TIMEOUT_SECONDS: float = 20.0

_TIMEOUT_RE = re.compile(
    r"httpx\.Client\s*\(\s*timeout\s*=\s*(?P<value>[0-9]+(?:\.[0-9]+)?)"
)


def test_target_file_exists() -> None:
    assert TARGET_FILE.is_file(), f"Expected {TARGET_FILE} to exist."


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
        value = float(m.group("value"))
        if value != _EXPECTED_TIMEOUT_SECONDS:
            drift.append(f"timeout={value}s at offset {m.start()}")
    assert not drift, (
        f"httpx.Client timeout drift in {TARGET_FILE.name}: "
        f"expected {_EXPECTED_TIMEOUT_SECONDS}s for every call, got:\n"
        + "\n".join(f"  {d}" for d in drift)
        + "\nIf an asymmetric timeout is genuinely required, refactor "
        "to a named constant and update this pin to allow the new "
        "baseline + the documented exception."
    )
