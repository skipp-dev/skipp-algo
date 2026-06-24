"""Defense ledger for ``os.unlink(...)`` / ``os.remove(...)`` call sites.

File deletion is destructive and irreversible. The repository currently
has 23 production call sites across the open-prep pipeline, the
terminal export module, and a couple of newsstack helpers. Locking
those locations with a ledger means:

* drift detection — any line shift in these files surfaces here so the
  responsible PR explicitly acknowledges the change (the same drift
  protection used by ``test_hashlib_weak_hash_ledger.py`` and
  ``test_nonlocal_budget.py``);
* growth gate — adding a new ``os.remove`` / ``os.unlink`` caller in
  production becomes a deliberate, reviewed action with the
  justification recorded in the ledger entry;
* surface awareness — the ledger doubles as a quick map of every place
  the codebase deletes a file, useful for audits.

Note: ``shutil.rmtree(...)`` is already pinned by
``tests/test_dangerous_io_zero_surface_pin.py`` (allow-listed only
inside ``scripts/``). This ledger is the single-file complement.
"""

from __future__ import annotations

import ast
from pathlib import Path

from tests._guard_corpus import parse_module

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


def _os_delete_sites() -> set[tuple[str, int, str]]:
    """Return ``{(relpath, lineno, attr)}`` for every ``os.unlink(...)``
    or ``os.remove(...)`` call. ``attr`` is the literal method name so
    the ledger pins the chosen API, not just the line.
    """

    sites: set[tuple[str, int, str]] = set()
    for path in _iter_py_files():
        tree = parse_module(path)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not isinstance(func, ast.Attribute):
                continue
            if func.attr not in ("unlink", "remove"):
                continue
            value = func.value
            if not isinstance(value, ast.Name) or value.id != "os":
                continue
            sites.add((path.relative_to(ROOT).as_posix(), node.lineno, func.attr))
    return sites


# Locked ledger of every production ``os.unlink`` / ``os.remove`` site.
# Adding a new caller? Append the (path, line, attr) tuple in the same
# PR with a justification in the commit message and prefer wrapping the
# call in a ``try / except FileNotFoundError`` (or ``Path.unlink(missing_ok=True)``)
# so a stale handle never crashes the caller.
OS_DELETE_LEDGER: set[tuple[str, int, str]] = {
    ("newsstack_fmp/open_prep_export.py", 35, "unlink"),
    ("newsstack_fmp/store_sqlite.py", 143, "remove"),
    ("open_prep/alerts.py", 79, "unlink"),
    ("open_prep/candidate_weights.py", 154, "unlink"),
    ("open_prep/diff.py", 68, "unlink"),
    # 2026-06-13 (audit-e2/aw7-reader-observability, PR #2759): _load_previous_latest
    #   DEBUG log insertion shifted unlink from 257 → 258.
    ("open_prep/feature_importance_report.py", 258, "unlink"),
    # 2026-06-11 (backfill defer-unpublished): 97→116, 539→589.
    # 2026-06-11 (eval-findings B1/B2): direction+triple-barrier code in
    # compute_pnl_from_bars + backfill loop shifted 589→668.
    # 2026-06-11 (c10b FI component persistence): era-gate block 668→690.
    # 2026-06-11 (Copilot sweep #2677): deferred-summary accounting 690→702.
    # 2026-06-12 (pytest write-guard merge): guard import/call + sweep
    # combined — measured 125/711; outcomes.py guard shift → 161.
    # 2026-06-17 (F1 lint fix): remove unused import sys → 125→124.
    ("open_prep/outcome_backfill.py", 124, "unlink"),
    # 2026-06-12 (Copilot #2729): main() exit-semantics docstring +6 → 717.
    # 2026-06-17 (F1 lint fix): remove unused import sys → 717→716.
    ("open_prep/outcome_backfill.py", 716, "unlink"),
    ("open_prep/outcomes.py", 161, "unlink"),
    # 2026-06-11 (trend-state features): 431→449, snapshot keys +
    # FEATURE_KEYS/PASS_THROUGH block added above.
    # 2026-06-11 (eval-findings B5/B1): gap-playbook report +
    # infer_trade_direction + snapshot fields shifted 449→537.
    # 2026-06-11 (vix9d D5): snapshot field + FEATURE_KEYS entries +7
    # (537→543).
    # 2026-06-11 (c10b FI component persistence): _component_fields helper
    # + component flattening shifted 543→567.
    # 2026-06-12 (backlog-resilience): non-list warning in
    # _load_outcomes_range +6 → 587.
    ("open_prep/outcomes.py", 587, "unlink"),
    ("open_prep/realtime_signals.py", 125, "remove"),
    ("open_prep/realtime_signals.py", 2674, "unlink"),
    ("open_prep/realtime_signals.py", 2713, "unlink"),
    # 2026-06-11 (eval-findings D7): technical_analysis import block +8
    # lines at L55 shifted all run_open_prep sites; enrichment-loop
    # real-ADX/BBW block added +15 more after L5491.
    # 2026-06-11 (vix9d D5): VIX9D fetch (+17) + ratio stamping (+4)
    # shifted 5491→5506, 5765→5784.
    # 2026-06-19 (B9/B10): _add_pdh_pdl_context current-day fields +6 and
    # 2026-06-19 (B10 non-padded date extension): _parse_calendar_date
    # extended; multiple insertion points produced non-uniform shifts.
    ("open_prep/run_open_prep.py", 2308, "unlink"),
    # 2026-06-10 (#2670 W2/W4): regime_source + premarket source-disclosure
    # edits shifted the later unlink sites (+20/+20/+20/+25).
    ("open_prep/run_open_prep.py", 3131, "unlink"),
    ("open_prep/run_open_prep.py", 3483, "unlink"),
    # 2026-06-11 (Copilot sweep #2688): VIX9D fail-closed guard +5;
    # 2026-06-12 (merge #2713 into #2696): net +1 → 5512/5790.
    ("open_prep/run_open_prep.py", 5621, "unlink"),
    # 2026-06-11 (trend-state features): 5731→5742, enrichment-loop
    # stamping + lookback comment added above; eval-findings 5742→5765.
    # 2026-06-12 (backlog-resilience): fail-loud outcome storage +9 → 5799.
    # 2026-06-12 (copilot-followup): rename + 3-line comment → 5802.
    ("open_prep/run_open_prep.py", 5916, "unlink"),
    ("open_prep/scorer.py", 149, "unlink"),
    ("open_prep/watchlist.py", 74, "unlink"),
    ("smc_core/benchmark.py", 39, "unlink"),
    ("smc_core/ensemble_quality.py", 58, "unlink"),
    ("smc_core/event_ledger.py", 153, "unlink"),
    ("smc_core/scoring.py", 1220, "unlink"),
    ("smc_integration/batch.py", 35, "unlink"),
    ("smc_integration/provider_health.py", 69, "unlink"),
    ("smc_integration/structure_batch.py", 39, "unlink"),
    ("streamlit_terminal.py", 2264, "unlink"),
    ("terminal_export.py", 186, "unlink"),
    ("terminal_export.py", 236, "unlink"),
    ("terminal_export.py", 618, "unlink"),
    ("terminal_export.py", 759, "unlink"),
}


def test_os_delete_ledger_exact() -> None:
    sites = _os_delete_sites()

    unexpected = sites - OS_DELETE_LEDGER
    assert not unexpected, (
        "New / drifted os.unlink(...) or os.remove(...) call site detected. "
        "File deletion is destructive — add the (path, line, attr) entry "
        "to OS_DELETE_LEDGER with a justification in the commit message "
        "and prefer wrapping the call to tolerate already-missing files "
        "(``Path.unlink(missing_ok=True)`` or "
        "``except FileNotFoundError``).\n"
        f"unexpected = {sorted(unexpected)}"
    )

    missing = OS_DELETE_LEDGER - sites
    assert not missing, (
        "OS_DELETE_LEDGER entries no longer present in code. If a "
        "deletion call was deliberately removed, drop the matching "
        "tuple from the ledger.\n"
        f"missing = {sorted(missing)}"
    )
