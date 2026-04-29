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
})

# ---- Layer 2: tempfile.* ledger ----------------------------------------------

_ALLOWED_TEMPFILE_METHODS: frozenset[str] = frozenset({"mkstemp"})

_TEMPFILE_LEDGER: frozenset[tuple[str, int, str]] = frozenset({
    ("databento_reference.py", 100, "mkstemp"),
    ("databento_utils.py", 126, "mkstemp"),
    ("databento_volatility_screener.py", 300, "mkstemp"),
    ("governance/alpha_ledger.py", 66, "mkstemp"),
    ("newsstack_fmp/open_prep_export.py", 24, "mkstemp"),
    ("open_prep/alerts.py", 67, "mkstemp"),
    ("open_prep/candidate_weights.py", 146, "mkstemp"),
    ("open_prep/diff.py", 57, "mkstemp"),
    ("open_prep/feature_importance_report.py", 247, "mkstemp"),
    ("open_prep/outcome_backfill.py", 87, "mkstemp"),
    ("open_prep/outcome_backfill.py", 513, "mkstemp"),
    ("open_prep/outcomes.py", 121, "mkstemp"),
    ("open_prep/outcomes.py", 396, "mkstemp"),
    ("open_prep/realtime_signals.py", 109, "mkstemp"),
    ("open_prep/realtime_signals.py", 2497, "mkstemp"),
    ("open_prep/realtime_signals.py", 2538, "mkstemp"),
    ("open_prep/watchlist.py", 63, "mkstemp"),
    ("smc_core/inference/null_cache.py", 96, "mkstemp"),
    ("terminal_export.py", 168, "mkstemp"),
    ("terminal_export.py", 222, "mkstemp"),
    ("terminal_export.py", 605, "mkstemp"),
    ("terminal_export.py", 751, "mkstemp"),
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
        try:
            tree = ast.parse(p.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        rel = str(p.relative_to(_REPO_ROOT))
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
