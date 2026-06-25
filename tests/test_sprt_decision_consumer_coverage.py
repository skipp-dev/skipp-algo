"""Pin: every consumer of an SPRT ``Decision`` literal must reference at
least one vocab member from a known group, preventing silent
fall-through if the vocab is ever extended.

Companion to ``tests/test_sprt_decision_vocab_pin.py`` (membership) and
``tests/test_sprt_decide_ast_return_literal.py`` (producer).
This pin closes the consumer side: scripts that branch on SPRT
decisions must reference enough of the vocab that adding a new
sentinel forces an explicit decision (cover or skip-with-justification).

For each Python file under ``scripts/`` that mentions any SPRT decision
sentinel literal, count distinct sentinels referenced. Files that
reference < 2 distinct sentinels are flagged as suspicious (likely
single-branch consumer that will silently miss new vocab members).

Files explicitly allowlisted (single-purpose handlers) are excluded
with a justification comment in this pin.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"

_VOCAB: tuple[str, ...] = (
    "continue",
    "accept_h0",
    "accept_h1",
    "max_n_reached",
    "inconclusive",
)

# Match each sentinel only when it appears as a quoted string literal
# (avoids false positives from plain English "continue"/"continue."
# words in docstrings — those are unquoted prose).
_PATTERNS: dict[str, re.Pattern[str]] = {
    sentinel: re.compile(rf'["\']{re.escape(sentinel)}["\']')
    for sentinel in _VOCAB
}

# Allowlist: file → reason. Files where single-sentinel reference is
# legitimate (e.g. promotion-only or futility-only narrow handlers).
_SINGLE_BRANCH_ALLOWLIST: dict[str, str] = {
    # f2_simulate_chain.py: synthesises decisions for simulation, not a
    # consumer of real decisions — references continue + accept_h0 by
    # design but doesn't need full coverage semantics.
    "scripts/f2_simulate_chain.py": (
        "decision synthesizer for simulation, not a real-time consumer"
    ),
    # forward_test_tracking.py: own promotion decision module with its
    # own Literal vocab (promote/continue/demote). Only the shared SPRT
    # "continue" literal overlaps; the module is the *producer* of its
    # own decision tuple, not a downstream consumer of SPRT vocab.
    "scripts/forward_test_tracking.py": (
        "emits own promotion-decision vocab; only shares 'continue' literal"
    ),
    # analyze_tv_preflight_retries.py: classifies TradingView preflight
    # retry runs into its own vocab (success / flake_recovered /
    # deterministic_failure / flake_with_progression / inconclusive). The
    # name "inconclusive" overlaps with the SPRT sentinel by coincidence
    # only; this script never imports smc_sprt_stop_rule and never reads
    # SPRT decision payloads.
    "scripts/analyze_tv_preflight_retries.py": (
        "emits own TV-preflight retry-verdict vocab; 'inconclusive' is a "
        "homonym, not the SPRT sentinel"
    ),
    # plan_2_8_evaluate.py: consumes per-family verdict payloads for a
    # narrow dashboard rollup and currently reads only the "inconclusive"
    # sentinel; broader SPRT decision handling is intentionally out of scope.
    "scripts/plan_2_8_evaluate.py": (
        "single-sentinel dashboard rollup consumer"
    ),
}


def _scripts_python_files() -> list[Path]:
    if not SCRIPTS_DIR.is_dir():
        return []
    return sorted(p for p in SCRIPTS_DIR.rglob("*.py") if p.is_file())


def _consumer_files_with_sentinels() -> dict[Path, set[str]]:
    """Return {file: {sentinels referenced}} for files that mention at
    least one SPRT decision literal."""
    out: dict[Path, set[str]] = {}
    for path in _scripts_python_files():
        # Skip the source-of-truth file itself.
        if path.name == "smc_sprt_stop_rule.py":
            continue
        text = path.read_text(encoding="utf-8")
        hits = {s for s, pat in _PATTERNS.items() if pat.search(text)}
        if hits:
            out[path] = hits
    return out


def test_decision_consumers_exist() -> None:
    consumers = _consumer_files_with_sentinels()
    assert consumers, (
        "Expected at least one SPRT decision consumer under scripts/ "
        "but found none. Either the vocab strings have changed or the "
        "regex matching has broken — investigate."
    )


def test_consumer_sentinel_coverage_is_broad_or_allowlisted() -> None:
    """Each consumer must either reference >= 2 distinct sentinels OR
    be on the documented single-branch allowlist."""
    consumers = _consumer_files_with_sentinels()
    violations: list[tuple[str, set[str]]] = []
    for path, sentinels in consumers.items():
        rel = path.relative_to(REPO_ROOT).as_posix()
        if rel in _SINGLE_BRANCH_ALLOWLIST:
            continue
        if len(sentinels) < 2:
            violations.append((rel, sentinels))
    assert not violations, (
        "SPRT decision consumer(s) reference only a single sentinel "
        "(silent fall-through risk if vocab is extended):\n"
        + "\n".join(
            f"  {rel}: only references {sorted(sents)}"
            for rel, sents in violations
        )
        + "\nEither (a) extend the consumer to handle additional "
        "sentinels, or (b) add the file to _SINGLE_BRANCH_ALLOWLIST in "
        "this pin with a justification."
    )


def test_allowlist_entries_are_active_consumers() -> None:
    """Catch allowlist rot: every allowlisted file must (still) exist
    and (still) reference at least one sentinel."""
    consumers = _consumer_files_with_sentinels()
    consumer_rels = {p.relative_to(REPO_ROOT).as_posix() for p in consumers}
    stale = sorted(rel for rel in _SINGLE_BRANCH_ALLOWLIST if rel not in consumer_rels)
    assert not stale, (
        f"Stale entries in _SINGLE_BRANCH_ALLOWLIST (file missing or no "
        f"longer references SPRT sentinels): {stale}. Remove from the "
        f"allowlist."
    )
