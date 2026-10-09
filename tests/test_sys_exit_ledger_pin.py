"""Pin: ``sys.exit`` / ``exit`` / ``quit`` frozen-site ledger.

Library code must not call `sys.exit()` (or worse, the bare `exit()`
/ `quit()` builtins) — these are CLI/REPL helpers. Library functions
should `raise` an exception so callers can decide how to handle it.

Today: 9 sites, all in legitimate CLI dispatch / `__main__` guards:

| File | Line | Context |
|---|---|---|
| `open_prep/candidate_weights.py` | 241 | `if __name__ == "__main__": sys.exit(main())` |
| `open_prep/feature_importance_report.py` | 359 | same |
| `pine_input_surface.py` | 491, 493 | argparse `args.cmd` dispatch |
| `test_usi_lint.py` | 94, 97 | top-level CLI script |

Any new site requires a ledger entry — review opportunity to confirm
it's a real CLI entry-point, not library code.

Also bans the bare `exit()` / `quit()` builtins (REPL-only,
crash-on-import-without-`site` module). All 0 today.

OWASP A09 (Security Logging & Monitoring Failures) — silent process
termination kills observability.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from tests._guard_corpus import iter_production_py_files, parse_module

_REPO_ROOT = Path(__file__).resolve().parents[1]
_DIR_EXCLUDE = frozenset({
    ".git", ".github", ".mypy_cache", ".pytest_cache", ".ruff_cache",
    ".venv", "venv", "node_modules", "artifacts", "docs", "scripts",
    "tests", "SMC++",
})

# Frozen ledger of legitimate `sys.exit()` sites (CLI entry-points only).
_SYS_EXIT_LEDGER: frozenset[tuple[str, int]] = frozenset({
    # 2026-07-03 (WP-3 holdout rescoring): helper additions shifted CLI
    # guard exit from 244 -> 566.
    ("open_prep/candidate_weights.py", 573),  # 2026-07-10: eps_surprise_pct→recent_eps_surprise_pct reconstruction swap +1 (573->574)
    # 2026-06-13 (audit-e2/aw7-reader-observability, PR #2759): _load_previous_latest
    #   DEBUG log insertion shifted CLI exit from 358 → 359.
    # 2026-07-15 (ops-digest truth): _DIAGNOSTIC_COUNTERS constant + the top-level
    #   counter copy in generate_report shifted the CLI exit 360 → 380 (pure shift;
    #   still the `if __name__ == "__main__": sys.exit(main())` entry point).
    ("open_prep/feature_importance_report.py", 380),
    # 2026-06-12 (backlog-resilience): main() exits non-zero when
    # store_daily_outcomes failed — the daily workflow's primary artifact
    # (outcomes_<date>.json) must not fail silently green.
    # 2026-06-12 (copilot-followup): rename + 3-line comment → 5931.
    # 2026-06-25: feature-flag helper addition shifted 6045 -> 6049.
    # 2026-07-04 (market-microstructure observe-only): import + snapshot
    # block + row-loop fields shifted 6065 -> 6091.
    ("open_prep/run_open_prep.py", 6096),  # 2026-07-19 remove retired TradingView news lane
    # 2026-06-02 (#2497): +68 lines after the `provenance` subcommand block
    # was inserted above the lint dispatch (was 400, 402).
    # 2026-07-15 (provenance v2): active_root_pine_scripts() + its docstring
    #   inserted above build_provenance shifted the pair 468, 470 -> 491, 493.
    ("pine_input_surface.py", 491),
    ("pine_input_surface.py", 493),
    ("test_usi_lint.py", 94),
    ("test_usi_lint.py", 97),
    # 2026-05-12 (#2171 audit-L-1 PR-D R12+R3): consistency-check CLI tools
    # exit non-zero on findings in --strict mode, 0 otherwise.
    ("tools/check_audit_doc_consistency.py", 135),
    # 2026-07-16 (truth audit): intentional env-name exception shifted CLI
    # guard exit from 249 -> 253; the site remains the same __main__ dispatch.
    ("tools/check_defaults_table.py", 253),
})


def _iter_prod_py() -> list[Path]:
    return iter_production_py_files(_DIR_EXCLUDE, root=_REPO_ROOT)


def _scan() -> tuple[set[tuple[str, int]], set[tuple[str, int, str]]]:
    """Return (sys_exit_sites, bare_exit_sites).

    `bare_exit_sites` covers the bare `exit()` / `quit()` builtins.
    """
    sys_exit_sites: set[tuple[str, int]] = set()
    bare_exit_sites: set[tuple[str, int, str]] = set()
    for p in _iter_prod_py():
        tree = parse_module(p)
        if tree is None:
            continue
        rel = p.relative_to(_REPO_ROOT).as_posix()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            f = node.func
            if isinstance(f, ast.Attribute):
                if (
                    f.attr == "exit"
                    and isinstance(f.value, ast.Name)
                    and f.value.id == "sys"
                ):
                    sys_exit_sites.add((rel, node.lineno))
            elif isinstance(f, ast.Name) and f.id in ("exit", "quit"):
                bare_exit_sites.add((rel, node.lineno, f.id))
    return sys_exit_sites, bare_exit_sites


def test_no_bare_exit_or_quit() -> None:
    """Bare ``exit()`` / ``quit()`` builtins zero-tripwire.

    These are added by the `site` module for REPL convenience; in
    embedded interpreters or stripped builds they may be missing,
    crashing on import. Always use `sys.exit` (and only at CLI
    entry-points).
    """
    _, bare_sites = _scan()
    assert bare_sites == set(), (
        f"Bare exit()/quit() in production code: {sorted(bare_sites)}. "
        f"Use `sys.exit(code)` at CLI entry-points; library code "
        f"should raise."
    )


def test_sys_exit_no_new_sites() -> None:
    """Every ``sys.exit`` site must be in the frozen ledger.

    `sys.exit()` is for CLI entry-points only. Library functions
    should `raise` so callers control the failure mode.
    """
    sys_exit_sites, _ = _scan()
    new_sites = sys_exit_sites - _SYS_EXIT_LEDGER
    assert new_sites == set(), (
        f"New sys.exit() site(s) without ledger entry: {sorted(new_sites)}. "
        f"If this is a CLI entry-point, add to _SYS_EXIT_LEDGER. "
        f"If library code, replace with `raise`."
    )


def test_sys_exit_no_stale_ledger() -> None:
    """Every entry in `_SYS_EXIT_LEDGER` still exists in code."""
    sys_exit_sites, _ = _scan()
    stale = _SYS_EXIT_LEDGER - sys_exit_sites
    assert stale == set(), (
        f"Stale entries in _SYS_EXIT_LEDGER: {sorted(stale)}. Remove them."
    )


@pytest.mark.parametrize(
    ("rel", "lineno"),
    sorted(_SYS_EXIT_LEDGER),
    ids=lambda v: str(v),
)
def test_sys_exit_ledger_files_exist(rel: str, lineno: int) -> None:
    """Every ledgered file still exists."""
    p = _REPO_ROOT / rel
    assert p.is_file(), f"Ledger references missing file: {rel}"
