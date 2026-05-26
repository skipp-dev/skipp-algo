"""Central vocabulary fingerprint gate — single source of truth for the
allowed value-spaces of the Hero / Trust / Action surfaces.

Audit follow-up to :file:`docs/reviews/2026-04-24-system-review.md` finding
**I-2** (Klasse #19, "Vocab-Fingerprint Gate"): the repo already has 12
hero/trust pin tests, but each pins its own slice. Drift in one vocab is
caught locally, but there is no single test that snapshots **all**
value-spaces in one place. This file is that snapshot.

How it works:

* Each canonical vocabulary is collected from its module of origin.
* The vocabulary is normalised to a sorted JSON list (deterministic
  serialisation) and hashed via sha256 (truncated to 16 hex chars).
* A baseline ``{vocab_name: (count, fingerprint)}`` map pins the current
  expected state.

Any change to a vocabulary — add, remove, or rename a token — bumps the
fingerprint and forces this test to fail. The reviewer must then
consciously update the baseline (and consider downstream Pine / dashboard
contracts that key off the vocabulary).

Adding a **new** vocabulary requires two edits:

1. Append it to ``_collect_vocabularies()``.
2. Add the new ``(count, fingerprint)`` entry to ``_BASELINE``.

Both edits show up in code review and the diff message tells the reviewer
exactly which fingerprint to use.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable

from scripts.smc_hero_state import (
    DEFAULTS,
    HERO_ACTION_VOCAB,
    HERO_SETUP_QUALITY_VOCAB,
    HERO_TRUST_VOCAB,
)
from smc_integration.trust_state import (
    ACTION_IMPACTS,
    TrustState,
    all_trust_states,
)


def _fingerprint(values: Iterable[str]) -> tuple[int, str]:
    items = sorted(set(values))
    serialised = json.dumps(items, separators=(",", ":"))
    digest = hashlib.sha256(serialised.encode("utf-8")).hexdigest()[:16]
    return (len(items), digest)


def _collect_vocabularies() -> dict[str, tuple[int, str]]:
    """Snapshot every canonical vocabulary in one place."""
    return {
        # Hero state vocabularies (scripts/smc_hero_state.py).
        "HERO_TRUST_VOCAB": _fingerprint(HERO_TRUST_VOCAB),
        "HERO_SETUP_QUALITY_VOCAB": _fingerprint(HERO_SETUP_QUALITY_VOCAB),
        "HERO_ACTION_VOCAB": _fingerprint(HERO_ACTION_VOCAB),
        "HERO_DEFAULTS_KEYS": _fingerprint(DEFAULTS.keys()),
        # Trust state model (smc_integration/trust_state.py).
        "TRUST_STATE_VALUES": _fingerprint(s.value for s in all_trust_states()),
        "ACTION_IMPACTS": _fingerprint(ACTION_IMPACTS),
    }


# Pinned baseline. Bumping any entry requires confirming downstream contracts
# (Pine surface, dashboard renderers, alert payloads) understand the change.
_BASELINE: dict[str, tuple[int, str]] = {
    "HERO_TRUST_VOCAB": (5, "48a4c6ef8fd2ce23"),
    "HERO_SETUP_QUALITY_VOCAB": (5, "e70266fdb4d5ad40"),
    "HERO_ACTION_VOCAB": (4, "33eb5f031c240e98"),
    "HERO_DEFAULTS_KEYS": (7, "5c89a97d90299b42"),
    "TRUST_STATE_VALUES": (5, "d63b52bbd00d2bb7"),
    "ACTION_IMPACTS": (4, "8e1aed0a40b6c344"),
}


def test_no_baseline_vocabulary_was_silently_dropped() -> None:
    current = _collect_vocabularies()
    missing = sorted(set(_BASELINE) - set(current))
    assert not missing, (
        "The following vocabularies are pinned in _BASELINE but no longer "
        "appear in _collect_vocabularies(): "
        + ", ".join(missing)
        + ". Either restore the import / collection, or remove the entry "
        "from _BASELINE explicitly. Audit finding I-2 (Klasse #19)."
    )


def test_no_unpinned_vocabulary_added_silently() -> None:
    current = _collect_vocabularies()
    extra = sorted(set(current) - set(_BASELINE))
    assert not extra, (
        "New vocabularies are exposed by _collect_vocabularies() but missing "
        "from _BASELINE: "
        + ", ".join(extra)
        + ". Add the (count, fingerprint) entry — see _collect_vocabularies "
        "for the canonical fingerprints. Audit finding I-2 (Klasse #19)."
    )


def test_vocabulary_fingerprints_match_baseline() -> None:
    current = _collect_vocabularies()
    drifts: list[str] = []
    for name in sorted(_BASELINE):
        if name not in current:
            continue  # covered by the dropped-baseline test
        if current[name] != _BASELINE[name]:
            exp_n, exp_h = _BASELINE[name]
            got_n, got_h = current[name]
            drifts.append(
                f"  {name}: baseline=(count={exp_n}, fp={exp_h}) "
                f"current=(count={got_n}, fp={got_h})"
            )
    assert not drifts, (
        "Vocabulary drift detected. A token was added, removed, or renamed "
        "in one of the canonical surfaces. Confirm downstream contracts "
        "(Pine surface, dashboards, alert payloads) understand the change, "
        "then bump the matching entry in _BASELINE. Audit finding I-2.\n"
        + "\n".join(drifts)
    )


def test_baseline_is_self_consistent() -> None:
    # Sanity: every baseline entry is reachable. This guards against typos
    # in _BASELINE keys vs. _collect_vocabularies keys.
    current = _collect_vocabularies()
    assert set(current) == set(_BASELINE), (
        "_BASELINE keys must match _collect_vocabularies() keys exactly. "
        f"baseline-only={sorted(set(_BASELINE) - set(current))!r}, "
        f"current-only={sorted(set(current) - set(_BASELINE))!r}"
    )


def test_trust_state_enum_value_set_matches_trust_state_values_baseline() -> None:
    # Cross-check: the TRUST_STATE_VALUES vocabulary baseline must match
    # the enum membership exactly. This prevents a subtle bug where someone
    # adds a new TrustState member but forgets all_trust_states().
    direct = {member.value for member in TrustState}
    via_iter = {s.value for s in all_trust_states()}
    assert direct == via_iter, (
        "TrustState enum members and all_trust_states() iterator disagree: "
        f"enum={sorted(direct)} iter={sorted(via_iter)}. all_trust_states "
        "must enumerate every TrustState member."
    )
