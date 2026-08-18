"""The Composio separation audit must stay ARMED in its only caller.

2026-08-18 (Verdrahtungs-Sweep B-2): ``composio-canary.yml`` ran
``composio_config_audit.py`` with only the READ side of every identity —
each of the nine checks is ``if read and write``, so the audit could only
ever report green (empirically proven: identical read IDs across all
toolkits still exited 0). A gate that can only pass is worse than no gate.

This pin keeps the caller's env block in lockstep with what the audit
reads: both API keys and, per toolkit, BOTH account-ID sides. The
WRITE_AUTH_CONFIG side stays deliberately unset (no such repo variables
exist anywhere); if that changes, extend the audit env here in the same PR.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.composio_config_audit import TOOLKITS

WORKFLOW = (
    Path(__file__).resolve().parents[1]
    / ".github"
    / "workflows"
    / "composio-canary.yml"
)


def _env_block() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


@pytest.mark.parametrize("key", ["COMPOSIO_PROD_API_KEY", "COMPOSIO_DEV_API_KEY"])
def test_both_api_keys_reach_the_audit(key: str) -> None:
    assert f"{key}:" in _env_block(), key


@pytest.mark.parametrize("toolkit", sorted(TOOLKITS))
@pytest.mark.parametrize("side", ["READ", "WRITE"])
def test_both_account_sides_reach_the_audit(toolkit: str, side: str) -> None:
    key = f"COMPOSIO_{toolkit}_{side}_ACCOUNT_ID:"
    assert key in _env_block(), key
