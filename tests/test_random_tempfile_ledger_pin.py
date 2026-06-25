"""Pin: ``random.*`` + ``tempfile.*`` usage ledgers.

Two layers of defense — each scoped to its bug class:

1. **`random.*` 1-site frozen ledger.** The `random` module is NOT
   cryptographically secure (uses Mersenne Twister, predictable from
   seed). For security-relevant randomness `secrets` must be used.
   Today: 1 legitimate non-security site in `open_prep/error_taxonomy.py:111`
   for retry-jitter. Pin enforces that any new `random.*` call requires
   a ledger entry — at which point reviewer must verify it's NOT used
   for tokens/IDs/passwords.

2. **`tempfile.*` per-method allowlist + 20-site frozen ledger.** All
   20 current uses are `tempfile.mkstemp()` (atomic-write pattern).
   Pin bans `mktemp` (race condition, CWE-377) and `NamedTemporaryFile`
   with `delete=False` shenanigans by enforcing that only `mkstemp` is
   used. Frozen ledger surfaces silent additions for review.

Defense-only, no production changes.

OWASP A02 (Cryptographic Failures, for `random` misuse) +
CWE-377 (Insecure Temporary File, for `tempfile` discipline).
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from tests._guard_corpus import parse_module

_REPO_ROOT = Path(__file__).resolve().parents[1]
_DIR_EXCLUDE = frozenset({
    ".git", ".github", ".mypy_cache", ".pytest_cache", ".ruff_cache",
    ".venv", "venv", "node_modules", "artifacts", "docs", "scripts",
    "tests", "SMC++",
})

# ---- Layer 1: random.* ledger -------------------------------------------------

_RANDOM_LEDGER: frozenset[tuple[str, int]] = frozenset({
    ("open_prep/error_taxonomy.py", 111),  # retry-jitter; non-security
    ("newsstack_fmp/_bz_http.py", 35),  # retry-jitter; non-security
    # ADR-0023 magnitude-resolution gate: seeded RNG for the bootstrap-CI /
    # permutation-null estimators (deterministic, reproducible); non-security.
    ("governance/magnitude_resolution_gate.py", 204),
    # ADR-0023 §5 E[PnL]-after-cost gate: seeded RNG for the bootstrap-CI of
    # the sized/equal-weight PnL estimators (deterministic); non-security.
    ("governance/epnl_after_cost.py", 194),
    # ADR-0023 §5 execution-cost calibration: seeded RNG for the bootstrap-CI
    # of the empirical round-turn cost (deterministic); non-security.
    # 2026-06-11 (#2697 review findings): 322→329 after the fee-only-leg
    # comment block above the call site, then 329→332 after the
    # non-finite cost-input guard landed three lines above it.
    ("governance/execution_costs.py", 332),
})

# ---- Layer 2: tempfile.* ledger ----------------------------------------------

_ALLOWED_TEMPFILE_METHODS: frozenset[str] = frozenset({"mkstemp"})

_TEMPFILE_LEDGER: frozenset[tuple[str, int, str]] = frozenset({
    ("databento_reference.py", 106, "mkstemp"),
    ("databento_utils.py", 144, "mkstemp"),
    # F-002 (PR #2295): cache-probe helpers added near the top of
    # ``databento_volatility_screener.py`` shifted the only ``mkstemp`` site
    # (``_make_atomic_temp_path``). F-V8-perf-3.5 PR-A re-routed
    # ``dump_cache_probe_log`` via ``_write_text_atomic`` and dropped its
    # redundant ``mkdir``/``open`` body; PR #2339 (universe-version
    # metadata) added the drift detector / version-bump persistence
    # block above the helper which shifted the site further: 489 → 597.
    # 2026-06-10 (#2670 W9): timestamp_substitutions disclosure shifted +5
    # (597 -> 602).
    ("databento_volatility_screener.py", 604, "mkstemp"),
    ("governance/alpha_ledger.py", 70, "mkstemp"),
    ("newsstack_fmp/open_prep_export.py", 25, "mkstemp"),
    ("newsstack_fmp/shared_fetch.py", 258, "mkstemp"),
    ("open_prep/alerts.py", 68, "mkstemp"),
    ("open_prep/candidate_weights.py", 146, "mkstemp"),
    ("open_prep/diff.py", 57, "mkstemp"),
    # 2026-06-13 (audit-e2/aw7-reader-observability, PR #2759): _load_previous_latest
    #   DEBUG log insertion shifted mkstemp from 249 → 250.
    ("open_prep/feature_importance_report.py", 250, "mkstemp"),
    # 2026-06-11 (backfill defer-unpublished): 88→107, 531→581.
    # 2026-06-17 (F1 lint fix): remove unused import sys → 116→115.
    ("open_prep/outcome_backfill.py", 115, "mkstemp"),
    # 2026-06-11 (eval-findings B1/B2): direction+TB code shifted 581→660.
    # 2026-06-11 (c10b FI component persistence): era-gate block 660→682.
    # 2026-06-11 (Copilot sweep #2677): deferred-summary accounting 682→694.
    # 2026-06-12 (pytest write-guard merge): guard import/call + sweep
    # combined — measured 703; outcomes.py guard shift → 152.
    # 2026-06-12 (Copilot #2729): main() exit-semantics docstring +6 → 709.
    # 2026-06-17 (F1 lint fix): remove unused import sys → 709→708.
    ("open_prep/outcome_backfill.py", 708, "mkstemp"),
    ("open_prep/outcomes.py", 152, "mkstemp"),
    # 2026-06-11 (trend-state features): 419→437, snapshot keys +
    # FEATURE_KEYS/PASS_THROUGH block added above.
    # 2026-06-11 (eval-findings B5/B1): gap-playbook report + direction
    # helpers + snapshot fields shifted 437→525; vix9d D5 → 531.
    # 2026-06-11 (c10b FI component persistence): _component_fields helper
    # + component flattening shifted 531→555.
    # 2026-06-12 (backlog-resilience): non-list warning in
    # _load_outcomes_range +6 → 575.
    ("open_prep/outcomes.py", 575, "mkstemp"),
    ("open_prep/realtime_signals.py", 117, "mkstemp"),
    # 2026-06-25: AsyncNewsstackPoller telemetry additions shifted
    # 2768 -> 2849 and 2815 -> 2896.
    ("open_prep/realtime_signals.py", 2849, "mkstemp"),
    ("open_prep/realtime_signals.py", 2896, "mkstemp"),
    ("open_prep/watchlist.py", 63, "mkstemp"),
    ("smc_core/benchmark.py", 30, "mkstemp"),
    ("smc_core/ensemble_quality.py", 49, "mkstemp"),
    ("smc_core/event_ledger.py", 133, "mkstemp"),
    ("smc_core/inference/null_cache.py", 96, "mkstemp"),
    ("smc_core/scoring.py", 1211, "mkstemp"),
    ("smc_integration/batch.py", 26, "mkstemp"),
    ("smc_integration/provider_health.py", 60, "mkstemp"),
    ("smc_integration/structure_batch.py", 30, "mkstemp"),
    ("streamlit_terminal.py", 2255, "mkstemp"),
    ("terminal_export.py", 177, "mkstemp"),
    ("terminal_export.py", 229, "mkstemp"),
    ("terminal_export.py", 606, "mkstemp"),
    ("terminal_export.py", 750, "mkstemp"),
})


def _iter_prod_py() -> list[Path]:
    out: list[Path] = []
    for p in sorted(_REPO_ROOT.rglob("*.py")):
        rel_parts = p.relative_to(_REPO_ROOT).parts
        if any(part in _DIR_EXCLUDE for part in rel_parts):
            continue
        out.append(p)
    return out


def _scan() -> tuple[set[tuple[str, int]], set[tuple[str, int, str]]]:
    """Return (random_sites, tempfile_sites) found in production code."""
    random_sites: set[tuple[str, int]] = set()
    tempfile_sites: set[tuple[str, int, str]] = set()
    for p in _iter_prod_py():
        rel = str(p.relative_to(_REPO_ROOT)).replace("\\", "/")
        tree = parse_module(p)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            f = node.func
            if not isinstance(f, ast.Attribute):
                continue
            if isinstance(f.value, ast.Name):
                if f.value.id == "random":
                    random_sites.add((rel, node.lineno))
                elif f.value.id == "tempfile":
                    tempfile_sites.add((rel, node.lineno, f.attr))
    return random_sites, tempfile_sites


# ---- Layer 1 tests -----------------------------------------------------------

def test_random_no_new_sites() -> None:
    """No new `random.*` call site without ledger entry.

    `random` is not cryptographically secure. Use `secrets` for any
    security-sensitive randomness (tokens, IDs, salt, passwords).
    """
    random_sites, _ = _scan()
    new_sites = random_sites - _RANDOM_LEDGER
    assert new_sites == set(), (
        f"New random.* call site(s) without ledger entry: {sorted(new_sites)}. "
        f"If non-security, add to _RANDOM_LEDGER. If security-sensitive, "
        f"switch to `secrets` module."
    )


def test_random_no_stale_ledger() -> None:
    """Every entry in `_RANDOM_LEDGER` still exists in code."""
    random_sites, _ = _scan()
    stale = _RANDOM_LEDGER - random_sites
    assert stale == set(), (
        f"Stale entries in _RANDOM_LEDGER (no longer in code): {sorted(stale)}. "
        f"Remove them."
    )


# ---- Layer 2 tests -----------------------------------------------------------

def test_tempfile_only_allowed_methods() -> None:
    """Only `tempfile.mkstemp` allowed.

    Bans:
    - `tempfile.mktemp` — race condition (CWE-377)
    - `tempfile.NamedTemporaryFile(delete=False, …)` — leaks files on crash
    - `tempfile.gettempdir()` etc — caller should use `tempfile.mkstemp`
      and rename, not write to a guessed path.
    """
    _, tempfile_sites = _scan()
    forbidden = [
        (rel, lineno, attr)
        for rel, lineno, attr in tempfile_sites
        if attr not in _ALLOWED_TEMPFILE_METHODS
    ]
    assert forbidden == [], (
        f"Forbidden tempfile.* methods used: {sorted(forbidden)}. "
        f"Use `tempfile.mkstemp` + rename for atomic-write."
    )


def test_tempfile_no_new_sites() -> None:
    """No new `tempfile.*` call site without ledger entry."""
    _, tempfile_sites = _scan()
    new_sites = tempfile_sites - _TEMPFILE_LEDGER
    assert new_sites == set(), (
        f"New tempfile.* call site(s) without ledger entry: {sorted(new_sites)}. "
        f"Add to _TEMPFILE_LEDGER."
    )


def test_tempfile_no_stale_ledger() -> None:
    """Every entry in `_TEMPFILE_LEDGER` still exists in code."""
    _, tempfile_sites = _scan()
    stale = _TEMPFILE_LEDGER - tempfile_sites
    assert stale == set(), (
        f"Stale entries in _TEMPFILE_LEDGER (no longer in code): {sorted(stale)}. "
        f"Remove them."
    )


@pytest.mark.parametrize(
    ("rel", "lineno", "attr"),
    sorted(_TEMPFILE_LEDGER),
    ids=lambda v: str(v),
)
def test_tempfile_ledger_files_exist(rel: str, lineno: int, attr: str) -> None:
    """Every ledgered file still exists (catches deletes/renames)."""
    p = _REPO_ROOT / rel
    assert p.is_file(), f"Ledger references missing file: {rel}"
