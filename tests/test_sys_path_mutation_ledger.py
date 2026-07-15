"""Defense-pin: ``sys.path.insert(...)`` / ``sys.path.append(...)`` site ledger.

Mutating ``sys.path`` at module import time is a load-order foot-gun:

* Order-dependent imports become silently fragile (the same ``import foo``
  resolves to a different ``foo.py`` depending on which script booted the
  process).
* New sites can mask packaging bugs — e.g. a missing ``pyproject.toml``
  console-script entry point or a forgotten ``__init__.py``.
* When a script is later promoted to a CLI / module / library, the
  ``sys.path`` dance is exactly the line that has to come out, but it
  tends to stick around because nobody notices it.

This module freezes the inventory by ``(file, count)``. Adding a new
site requires bumping ``_FROZEN_SITES`` in the same PR; removing a site
(great!) trips the same check so we don't accidentally regress later.

Defense-only — no production code changes.
"""

from __future__ import annotations

import ast
from collections import Counter
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

_DIR_EXCLUDE = frozenset(
    {
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
    }
)

# Per-file count of ``sys.path.insert(...)`` and ``sys.path.append(...)`` calls
# in first-party production / script / streamlit / tooling code.
#
# Convention on this repo: every site is a one-shot
# ``sys.path.insert(0, REPO_ROOT)`` performed before relative-from-root
# imports in standalone-runnable scripts. The one script with count == 2
# (``smc_zone_priority_calibration.py``) does it inside two different
# ``__main__``-style entry blocks.
_FROZEN_SITES: dict[str, int] = {
    "open_prep/realtime_signals.py": 1,
    "open_prep/streamlit_monitor.py": 1,
    "scripts/analyze_smc_contextual_calibration_history.py": 1,
    "scripts/build_phase_a_inputs.py": 1,
    "scripts/check_environment.py": 1,
    # Rebaselined 2026-05-03 (after PR #2035): bumped 1 → 2 because the
    # cross-process import-order fix added a module-level
    # ``sys.path.insert`` (the ``_bootstrap_sys_mod`` helper) on top of the
    # pre-existing in-function insert so ``from scripts.…`` imports resolve
    # before being referenced.
    "scripts/check_pine_legacy_drift.py": 2,
    # Rebaselined 2026-05-03 (after PR #2035): see check_pine_legacy_drift.py.
    "scripts/collect_smc_gate_evidence.py": 2,
    # Step-2b incremental window: lazy _load_narrow_scan_window() inserts
    # REPO_ROOT so scripts.databento_incremental_window imports both as a
    # script and via importlib (commit b04e7d83).
    "scripts/databento_plan_shards.py": 1,
    "scripts/databento_preopen_fast.py": 1,
    "scripts/databento_production_export.py": 1,
    # A9b.3 reduce-step needs sys.path bootstrap to import scripts.smc_atomic_write
    # for atomic JSON writes when invoked as `python scripts/X.py` from CI.
    "scripts/databento_production_merge_shards.py": 1,
    "scripts/databento_smoke_test.py": 1,
    # Rebaselined 2026-05-03 (after PR #2035): see check_pine_legacy_drift.py.
    "scripts/e2e_smoke_ci.py": 2,
    # Rebaselined 2026-05-03 (after PR #2035): see check_pine_legacy_drift.py.
    "scripts/emit_fvg_context_pine.py": 2,
    # 2026-07-04 (plan B1): repo-root bootstrap so the Open-Prep Pine panel
    # generator works under both `python -m scripts.X` and `python scripts/X.py`.
    "scripts/generate_openprep_pine_panel.py": 1,
    "scripts/execute_ibkr_watchlist.py": 1,
    "scripts/export_open_prep_lists.py": 1,
    "scripts/export_open_prep_reports.py": 1,
    "scripts/export_smc_live_news_snapshot.py": 1,
    "scripts/fvg_asia_real_sample.py": 1,
    "scripts/fvg_label_audit.py": 1,
    # Rebaselined 2026-05-03 (after PR #2035): see check_pine_legacy_drift.py.
    "scripts/fvg_quality_quartile_gate.py": 2,
    # Rebaselined 2026-05-03 (after PR #2035): see check_pine_legacy_drift.py.
    "scripts/fvg_quality_recalibration.py": 2,
    # Rebaselined 2026-05-03 (after PR #2035): see check_pine_legacy_drift.py.
    "scripts/g23_ab_watchdog.py": 2,
    "scripts/generate_performance_report.py": 1,
    "scripts/generate_showcase_summary.py": 1,
    "scripts/generate_smc_micro_base_from_databento.py": 1,
    # 2026-07-11: repo-root bootstrap so the Grafana notification-routing upsert
    # can `from scripts.grafana_alert_rules_upsert import _api_key, _request`
    # (reuse one auth path) under both `python -m scripts.X` and
    # `python scripts/X.py` (the deploy workflow uses the latter).
    "scripts/grafana_notification_routing_upsert.py": 1,
    "scripts/investigate_universe_delta.py": 1,
    # measure_databento_ops_run.py has a second textual occurrence inside a
    # triple-quoted subprocess runner string — AST sees only the real call.
    "scripts/measure_databento_ops_run.py": 1,
    "scripts/probe_newsapi_feed_cursor.py": 1,
    # Fast overlay refresh: inserts REPO_ROOT so scripts.* imports resolve
    # when invoked as `python scripts/refresh_overlay_enrichment.py`.
    "scripts/refresh_overlay_enrichment.py": 1,
    "scripts/run_smc_ci_health_checks.py": 1,
    "scripts/run_smc_e2e_smoke_test.py": 1,
    "scripts/run_smc_measurement_benchmark.py": 1,
    # Rebaselined 2026-05-03 (after PR #2035): see check_pine_legacy_drift.py.
    "scripts/run_smc_pre_release_artifact_refresh.py": 2,
    # Rebaselined 2026-05-03 (after PR #2035): see check_pine_legacy_drift.py.
    "scripts/run_smc_release_gates.py": 2,
    "scripts/smc_performance_report.py": 1,
    "scripts/smc_version_governance.py": 1,
    # Rebaselined 2026-05-02: bumped 2 → 3 because Bug-Hunt 2026-05-01 F-01
    # added a module-level ``sys.path.insert`` (line 42) so REPO_ROOT is on
    # sys.path *before* deferred imports inside ``main()``. The two existing
    # in-function inserts (lines 632, 739) are kept for direct script-run
    # paths.
    "scripts/smc_zone_priority_calibration.py": 3,
    "smc_tv_bridge/smc_api.py": 1,
    "streamlit_databento_volatility_screener.py": 1,
    "streamlit_smc_micro_base_generator.py": 1,
    "streamlit_terminal.py": 1,
}
_FROZEN_TOTAL = sum(_FROZEN_SITES.values())


def _iter_first_party_py_files() -> list[Path]:
    out: list[Path] = []
    for path in ROOT.rglob("*.py"):
        try:
            rel_parts = path.relative_to(ROOT).parts
        except ValueError:
            continue
        if any(part in _DIR_EXCLUDE for part in rel_parts):
            continue
        out.append(path)
    return sorted(out)


def _is_sys_path_mutation(node: ast.Call) -> bool:
    """True if ``node`` is ``sys.path.insert(...)`` or ``sys.path.append(...)``."""
    func = node.func
    if not isinstance(func, ast.Attribute):
        return False
    if func.attr not in {"insert", "append"}:
        return False
    inner = func.value
    if not (isinstance(inner, ast.Attribute) and inner.attr == "path"):
        return False
    return isinstance(inner.value, ast.Name) and inner.value.id == "sys"


def _count_sys_path_mutations(path: Path) -> int:
    try:
        source = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return 0
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError:
        return 0
    return sum(
        1
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and _is_sys_path_mutation(node)
    )


def _observed_counts() -> dict[str, int]:
    counts: Counter[str] = Counter()
    for path in _iter_first_party_py_files():
        n = _count_sys_path_mutations(path)
        if n:
            counts[path.relative_to(ROOT).as_posix()] = n
    return dict(counts)


def test_no_new_sys_path_mutation_files() -> None:
    """No new file may introduce ``sys.path.insert/append`` without a ledger bump."""
    observed = _observed_counts()
    new_files = sorted(set(observed) - set(_FROZEN_SITES))
    assert not new_files, (
        "New file(s) introduce sys.path mutation — silently fragile load order.\n"
        + "\n".join(f"  - {f} (count={observed[f]})" for f in new_files)
        + "\n\nIf the script truly needs sys.path bootstrap, add it to "
        "_FROZEN_SITES with a justifying comment. Otherwise prefer a "
        "console-script entry point in pyproject.toml or `python -m`."
    )


def test_no_removed_sys_path_mutation_files() -> None:
    """A site disappearing is great — drop it from the ledger explicitly."""
    observed = _observed_counts()
    missing = sorted(set(_FROZEN_SITES) - set(observed))
    assert not missing, (
        "Frozen sys.path mutation site(s) no longer present — drop from "
        "_FROZEN_SITES in the same PR:\n"
        + "\n".join(f"  - {f}" for f in missing)
    )


@pytest.mark.parametrize("rel,expected", sorted(_FROZEN_SITES.items()))
def test_frozen_count_still_matches(rel: str, expected: int) -> None:
    """Per-file count must match the ledger exactly."""
    path = ROOT / rel
    assert path.is_file(), f"frozen site missing on disk: {rel}"
    actual = _count_sys_path_mutations(path)
    assert actual == expected, (
        f"sys.path mutation count drifted in {rel}: "
        f"expected {expected}, got {actual}. "
        "Update _FROZEN_SITES in the same PR."
    )


def test_total_count_pinned() -> None:
    """Aggregate cross-check against per-file ledger drift."""
    observed = _observed_counts()
    total = sum(observed.values())
    assert total == _FROZEN_TOTAL, (
        f"sys.path mutation total drifted: expected {_FROZEN_TOTAL}, "
        f"got {total}. Per-file = {sorted(observed.items())}"
    )


# ─── position, not just count ─────────────────────────────────────────
#
# The ledger above counts sites and is honest about it ("freezes the inventory
# by (file, count)"). But the harm it names — "the same ``import foo`` resolves
# to a different ``foo.py``" — is decided by *where* in ``sys.path`` the entry
# lands, and ``_is_sys_path_mutation`` treats ``insert`` and ``append`` alike
# and never reads the index. Flipping a site from ``insert(0, REPO_ROOT)`` to
# ``append(REPO_ROOT)`` in place is exactly that harm — the repo copy stops
# winning over an installed one — and it moves no count.
#
# No allow-list: every one of the 55 mutations in this tree is ``insert(0, …)``,
# the bootstrap shape that puts the repo root ahead of site-packages. That
# uniformity is the invariant worth pinning; a deviation is a load-order change
# and belongs in review, not in a count that stays put.


def _sys_path_mutation_kind(node: ast.Call) -> str:
    """Classify a mutation as ``insert@<n>`` / ``append`` / ``insert@?``.

    ``insert@?`` covers a computed index (``sys.path.insert(pos, …)``), which
    cannot be shown to be 0 statically and so must not pass silently.
    """
    attr = node.func.attr  # type: ignore[union-attr]  # guarded by _is_sys_path_mutation
    if attr == "append":
        return "append"
    arg = node.args[0] if node.args else None
    if (
        isinstance(arg, ast.Constant)
        and isinstance(arg.value, int)
        and not isinstance(arg.value, bool)
    ):
        return f"insert@{arg.value}"
    return "insert@?"


def test_every_sys_path_mutation_inserts_at_position_zero() -> None:
    """Every ``sys.path`` mutation must be ``sys.path.insert(0, …)``."""
    offenders: list[str] = []
    for path in _iter_first_party_py_files():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, SyntaxError, UnicodeDecodeError):  # pragma: no cover
            continue
        rel = path.relative_to(ROOT).as_posix()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not _is_sys_path_mutation(node):
                continue
            kind = _sys_path_mutation_kind(node)
            if kind != "insert@0":
                offenders.append(f"  - {rel}:{node.lineno}  {kind}")

    assert not offenders, (
        "sys.path mutated somewhere other than position 0. Every bootstrap in "
        "this tree uses sys.path.insert(0, REPO_ROOT) so the repo copy wins "
        "over an installed one; `append` puts it last and `insert(n>0)` puts it "
        "behind whatever is already there, so `import foo` can silently resolve "
        "to a different foo.py — the exact failure this module exists to "
        "prevent, and one the per-file counts above cannot see. If a different "
        "position is genuinely required, that is a load-order change: raise it "
        "in review rather than widening this test.\n" + "\n".join(offenders)
    )
