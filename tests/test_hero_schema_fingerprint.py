"""HERO schema fingerprint pin (ADR-0007).

Locks a SHA-256 digest over:

* The 7 HERO field names (in canonical order).
* The contents of all 6 HERO controlled vocabularies.
* The string literal of ``library_field_version`` from the generator.

Any change to vocabulary membership, field count, field name/order, or
``library_field_version`` will break this pin and force a deliberate
update. The failure message contains the auto-update recipe.

This pin is the **single tripwire** that catches drift introduced by
PRs that touch only one half of the contract (e.g. add a vocab member
without bumping ``library_field_version``).
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
_GENERATOR_PATH = REPO_ROOT / "scripts" / "generate_smc_micro_profiles.py"

# Canonical 7-field order — see ADR-0007.
HERO_FIELD_ORDER: tuple[str, ...] = (
    "HERO_MARKET_MODE",
    "HERO_BIAS",
    "HERO_TRUST",
    "HERO_SETUP_QUALITY",
    "HERO_WHY_NOW",
    "HERO_RISK",
    "HERO_ACTION",
)

# Pinned library_field_version literal from generate_smc_micro_profiles.py.
EXPECTED_LIBRARY_FIELD_VERSION = "v7.0a"

# Pinned digest. Update via:
#   python -c "from tests.test_hero_schema_fingerprint import compute_fingerprint; \
#              print(compute_fingerprint())"
EXPECTED_FINGERPRINT = "4cefc5ca621c6f9a8d62783e0709ffe4695493fcc89a60e418de3839f804f939"


def compute_fingerprint() -> str:
    """Recompute the canonical fingerprint."""
    from scripts.smc_hero_state import (
        HERO_ACTION_VOCAB,
        HERO_BIAS_VOCAB,
        HERO_MARKET_MODE_VOCAB,
        HERO_RISK_VOCAB,
        HERO_SETUP_QUALITY_VOCAB,
        HERO_TRUST_VOCAB,
    )

    parts: list[str] = []
    parts.append("FIELDS=" + ",".join(HERO_FIELD_ORDER))
    for name, vocab in (
        ("MARKET_MODE", HERO_MARKET_MODE_VOCAB),
        ("BIAS", HERO_BIAS_VOCAB),
        ("TRUST", HERO_TRUST_VOCAB),
        ("SETUP_QUALITY", HERO_SETUP_QUALITY_VOCAB),
        ("RISK", HERO_RISK_VOCAB),
        ("ACTION", HERO_ACTION_VOCAB),
    ):
        # Encode the empty-string sentinel explicitly so it does not
        # vanish when joined.
        members = "|".join(repr(m) for m in sorted(vocab))
        parts.append(f"{name}={members}")
    parts.append(f"LFV={EXPECTED_LIBRARY_FIELD_VERSION}")

    digest_input = "\n".join(parts).encode("utf-8")
    return hashlib.sha256(digest_input).hexdigest()


def _extract_library_field_version() -> str:
    """Read the literal ``library_field_version`` from the generator."""
    source = _GENERATOR_PATH.read_text(encoding="utf-8")
    match = re.search(r'"library_field_version"\s*:\s*"([^"]+)"', source)
    assert match is not None, (
        "Cannot find library_field_version literal in "
        f"{_GENERATOR_PATH}. The generator no longer emits it?"
    )
    return match.group(1)


def test_library_field_version_is_pinned() -> None:
    """Catch drift in ``scripts/generate_smc_micro_profiles.py``'s LFV literal."""
    actual = _extract_library_field_version()
    assert actual == EXPECTED_LIBRARY_FIELD_VERSION, (
        f"library_field_version drifted: actual={actual!r} "
        f"expected={EXPECTED_LIBRARY_FIELD_VERSION!r}. If intentional, "
        "update EXPECTED_LIBRARY_FIELD_VERSION in this test, the "
        "generator, AND the schema fingerprint pin below."
    )


def test_hero_schema_fingerprint_matches_pin() -> None:
    """Lock the canonical hash over fields + vocabs + LFV."""
    actual = compute_fingerprint()
    assert actual == EXPECTED_FINGERPRINT, (
        "HERO schema fingerprint drift detected.\n"
        f"  actual:   {actual}\n"
        f"  expected: {EXPECTED_FINGERPRINT}\n"
        "If the change is intentional (vocab member added/removed, "
        "field reordered, library_field_version bumped), update "
        "EXPECTED_FINGERPRINT in tests/test_hero_schema_fingerprint.py "
        "AND ensure ADR-0007 + Pine consumers + library_field_version "
        "are co-updated. Recipe:\n"
        "  python -c 'from tests.test_hero_schema_fingerprint import "
        "compute_fingerprint; print(compute_fingerprint())'"
    )


def test_hero_field_order_matches_module_docstring() -> None:
    """The 7-field order in this test matches the module docstring."""
    from scripts.smc_hero_state import __doc__ as hs_doc

    assert hs_doc is not None
    for field in HERO_FIELD_ORDER:
        assert field in hs_doc, (
            f"Field {field!r} from HERO_FIELD_ORDER not mentioned in "
            "scripts/smc_hero_state.py module docstring. Sync the "
            "docstring or the field list."
        )
