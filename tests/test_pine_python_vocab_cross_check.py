"""Cross-language pin: every Python Hero/Trust/Action vocab token must be
rendered or compared against by at least one of the corresponding Pine
surfaces.

This complements ``tests/test_central_vocab_fingerprint_gate.py``: the
fingerprint pin freezes the Python-side vocabularies, while this pin
ensures the Pine layer does not silently fall behind when those
vocabularies are extended.

Failure means one of two things:
1. Python added a new vocab token but no Pine surface renders/compares
   against it (drift toward a silently-stale dashboard), OR
2. Python removed/renamed a token that Pine still references (drift
   toward dead Pine branches).

Either way the cross-check forces a deliberate Pine update.

Scope is intentionally limited to vocab→target-file pairs the Pine
dashboards are known to render; each pair lives in ``_TARGETS`` below.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


def _pine_text(*relpaths: str) -> str:
    """Concatenate the contents of the given Pine files (newline-separated)."""
    chunks: list[str] = []
    for rp in relpaths:
        p = REPO_ROOT / rp
        if not p.exists():
            pytest.fail(
                f"vocab cross-check target file is missing: {rp} "
                f"(expected at {p}). Either restore the file or update the "
                f"_TARGETS table in {Path(__file__).name}."
            )
        chunks.append(p.read_text(encoding="utf-8"))
    return "\n".join(chunks)


def _quoted_present(token: str, text: str) -> bool:
    """Return True iff ``"token"`` appears as a quoted literal in text."""
    pattern = r'"' + re.escape(token) + r'"'
    return re.search(pattern, text) is not None


# Python-side source of truth — kept in lockstep with
# scripts/smc_hero_state.py and smc_integration/trust_state.py. If you
# change a vocab on the Python side, the fingerprint gate
# (test_central_vocab_fingerprint_gate.py) will fail first; this pin then
# forces the Pine surface to follow.
_HERO_TRUST_TOKENS = ("healthy", "warmup", "degraded", "stale", "unavailable")
_HERO_ACTION_TOKENS = ("ACTIVE", "WATCH", "AVOID", "BLOCKED")
_HERO_SETUP_QUALITY_TOKENS = ("high", "good", "ok", "low")
_HERO_MARKET_MODE_TOKENS = ("BULLISH", "BEARISH", "NEUTRAL", "RISK_OFF")
_HERO_BIAS_TOKENS = ("LONG", "SHORT", "FLAT")
_TRUST_STATE_TOKENS = ("healthy", "degraded", "stale", "unavailable", "watch_only")

# (vocab_name, tokens, pine_files_that_must_collectively_cover_them)
# A token is considered "covered" if it appears as a quoted literal in
# the concatenation of the listed Pine files. The dashboards are the
# canonical render surface; one of them rendering each token is enough.
_TARGETS: tuple[tuple[str, tuple[str, ...], tuple[str, ...]], ...] = (
    (
        "HERO_TRUST_VOCAB",
        _HERO_TRUST_TOKENS,
        ("SMC_Dashboard.pine", "SMC_Mobile_Dashboard.pine"),
    ),
    (
        "HERO_ACTION_VOCAB",
        _HERO_ACTION_TOKENS,
        ("SMC_Dashboard.pine", "SMC_Mobile_Dashboard.pine"),
    ),
    (
        "HERO_SETUP_QUALITY_VOCAB",
        _HERO_SETUP_QUALITY_TOKENS,
        ("SMC_Dashboard.pine",),
    ),
    (
        "HERO_MARKET_MODE_VOCAB",
        _HERO_MARKET_MODE_TOKENS,
        ("SMC_Dashboard.pine", "SMC_Mobile_Dashboard.pine", "SMC_Core_Engine.pine"),
    ),
    (
        "HERO_BIAS_VOCAB",
        _HERO_BIAS_TOKENS,
        ("SMC_Dashboard.pine", "SMC_Mobile_Dashboard.pine"),
    ),
    (
        "TRUST_STATE_VALUES",
        _TRUST_STATE_TOKENS,
        ("SMC_Dashboard.pine", "SMC_Mobile_Dashboard.pine"),
    ),
)


@pytest.mark.parametrize("vocab_name,tokens,pine_files", _TARGETS)
def test_python_vocab_token_is_referenced_by_pine_surface(
    vocab_name: str, tokens: tuple[str, ...], pine_files: tuple[str, ...]
) -> None:
    text = _pine_text(*pine_files)
    missing = [t for t in tokens if not _quoted_present(t, text)]
    assert not missing, (
        f"Pine ↔ Python vocab drift detected for {vocab_name}: "
        f"the following Python tokens are NOT rendered/compared in any of "
        f"{list(pine_files)}: {missing}. "
        f"Either add a quoted-literal branch for each missing token in the "
        f"Pine surface(s), or — if the token was removed from Python — "
        f"remove it from the Python vocab and from the _TARGETS table in "
        f"{Path(__file__).name}."
    )
