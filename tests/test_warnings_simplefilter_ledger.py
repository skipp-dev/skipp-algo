"""Ledger pin for ``warnings.simplefilter("always")`` call sites.

Complements ``test_silent_security_and_boundary_bundle.py`` Layer 4
(which bans ``warnings.simplefilter("ignore")`` / ``filterwarnings("ignore")``)
by pinning the *positive* counterpart: every production
``warnings.simplefilter(...)`` call currently passes the literal
``"always"`` action, which is the loud / safe behavior — it surfaces
each warning so the surrounding ``warnings.catch_warnings()`` block can
inspect / log them.

Pinning these locations means:

* introducing a new caller becomes a deliberate, reviewed change;
* if a contributor ever flips one to ``"ignore"`` the ledger fails and
  forces an update — at which point the silent-warnings bundle (Layer 4)
  also fails, double-locking the regression;
* drift detection: any line-shift in these files surfaces here so the
  responsible PR explicitly acknowledges the change (the same drift
  protection used by other ledger pins like
  ``test_hashlib_weak_hash_ledger.py`` and ``test_nonlocal_budget.py``).
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


def _warnings_simplefilter_sites() -> set[tuple[str, int, str]]:
    """Return ``{(relpath, lineno, action)}`` for every
    ``warnings.simplefilter(<literal>)`` call. The action is the literal
    string passed as the first positional argument; non-literal actions
    are reported as ``"<dynamic>"`` so they cannot silently slip past
    the ledger.
    """

    sites: set[tuple[str, int, str]] = set()
    for path in _iter_py_files():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not isinstance(func, ast.Attribute) or func.attr != "simplefilter":
                continue
            value = func.value
            if not isinstance(value, ast.Name) or value.id != "warnings":
                continue
            action = "<dynamic>"
            if node.args:
                first = node.args[0]
                if isinstance(first, ast.Constant) and isinstance(first.value, str):
                    action = first.value
            sites.add((str(path.relative_to(ROOT)), node.lineno, action))
    return sites


# Every entry uses the literal ``"always"`` action — the loud / safe
# behavior that surfaces warnings to the surrounding
# ``warnings.catch_warnings()`` block. New entries must also be
# ``"always"`` (or the parallel silent-warnings bundle will also fail).
WARNINGS_SIMPLEFILTER_LEDGER: set[tuple[str, int, str]] = {
    # #2334 (PR #2338): cache-pollution filter blocks in 3 collectors shifted the
    # 5 screener warning sites again; action remains the loud / safe
    # ``"always"``. Coverage-bug fix added a 3-line comment in load_daily_bars
    # which shifted 4 of the 5 sites by +3.
    # 2026-05-23 PR #2338 follow-up: partial-cache block landed in three
    # post-742 collectors, shifting 2452->2463 (+11), 2931->2953 (+22) and
    # 3075->3108 (+33); 742 and 1832 are above the inserts and unchanged.
    # 2026-05-25 PR #2355 (drift-detector / universe-version-metadata branch):
    # additional helpers landed across the screener, shifting all five sites
    # downward by +115/+124/+134/+143/+152 — action remains ``"always"``.
    ("databento_volatility_screener.py", 857, "always"),
    ("databento_volatility_screener.py", 1956, "always"),
    ("databento_volatility_screener.py", 2597, "always"),
    ("databento_volatility_screener.py", 3096, "always"),
    ("databento_volatility_screener.py", 3260, "always"),
    ("databento_universe.py", 162, "always"),
}


def test_warnings_simplefilter_ledger_exact() -> None:
    sites = _warnings_simplefilter_sites()

    unexpected = sites - WARNINGS_SIMPLEFILTER_LEDGER
    assert not unexpected, (
        "New / drifted warnings.simplefilter(...) call site detected. "
        "Add or update the entry in WARNINGS_SIMPLEFILTER_LEDGER, keeping "
        'the action set to ``"always"`` — passing ``"ignore"`` is banned '
        "by tests/test_silent_security_and_boundary_bundle.py (Layer 4) "
        "and silently swallows warnings the catch block expects to see.\n"
        f"unexpected = {sorted(unexpected)}"
    )

    missing = WARNINGS_SIMPLEFILTER_LEDGER - sites
    assert not missing, (
        "WARNINGS_SIMPLEFILTER_LEDGER entries no longer present in code. "
        "If a call site was deliberately removed, drop the matching "
        "(path, line, action) tuple from the ledger.\n"
        f"missing = {sorted(missing)}"
    )


def test_warnings_simplefilter_no_ignore_or_default() -> None:
    """Defense in depth — the ledger already pins exact actions, but
    this test makes the intent obvious in the failure message: the only
    action allowed in production ``simplefilter`` calls is ``"always"``.
    """

    bad: list[str] = []
    for relpath, lineno, action in _warnings_simplefilter_sites():
        if action != "always":
            bad.append(f"{relpath}:{lineno}: warnings.simplefilter({action!r})")
    assert not bad, (
        'warnings.simplefilter(...) must use the "always" action in '
        "production — anything else (especially \"ignore\" / \"default\") "
        "either swallows warnings or interacts badly with the surrounding "
        "warnings.catch_warnings() block:\n  - " + "\n  - ".join(bad)
    )
