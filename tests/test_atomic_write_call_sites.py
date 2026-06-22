"""Inventory pin for raw file-write call sites.

Background
==========

Audit `docs/audits/smc-system-review-2026-04-24.md` (I-1) flagged a noisy
1003-vs-92 ratio for raw write candidates. After AST-based filtering the
real surface is ~15 raw writes outside ``scripts/smc_atomic_write.py``.

This test pins the explicit allowlist of files that may bypass
``atomic_write_parquet`` / ``atomic_write_csv``. Each entry has a brief
rationale.

Scope (Deep-Review 2026-04-27 follow-up)
----------------------------------------

Original scope was ``scripts/`` only. The deep review observed that
the pin was therefore blind to raw writes added under ``open_prep/``,
``ml/``, ``rl/``, and ``governance/`` — directories that have grown
production-impacting write sites since I-1 landed. The scan now
covers all five top-level directories; allowlist keys are the
repo-relative POSIX paths so the same filename in different
directories never collides.

Rules of thumb for the allowlist
================================

* JSON / text snapshot writes via ``os.fdopen(fd, ...)`` already use the
  ``mkstemp + fdopen + os.replace`` atomic pattern (see e.g.
  ``plan_2_8_history_backfill.py``); they do NOT need to migrate to
  ``smc_atomic_write``, which is parquet/csv specific.
* Showcase / log / one-shot CSV writes that are not consumed downstream
  by the SMC pipeline are tolerated.
* A NEW raw write to a parquet/csv that participates in a downstream
  manifest MUST be migrated to ``atomic_write_*`` before merge.

Failure semantics
=================

Adding a new raw write site forces an explicit decision: migrate to
``smc_atomic_write`` or update ``_ALLOWED_RAW_WRITE_FILES`` with a
rationale.
"""
from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
# Deep-Review 2026-04-27: scan additional top-level directories so the
# atomic-write pin can no longer be silently bypassed by writing under
# open_prep/ ml/ rl/ governance/.
# Audit E-1 2026-06-13 (AW-1): scope-expansion round 2 — smc_core/,
# smc_integration/, newsstack_fmp/ and the repo-root *.py modules
# (databento_*, terminal_export, streamlit_terminal, pine_*) were still
# unguarded; a new non-atomic writer there regressed silently.
_SCAN_DIRS: tuple[Path, ...] = tuple(
    REPO_ROOT / name
    for name in (
        "scripts", "open_prep", "ml", "rl", "governance",
        "smc_core", "smc_integration", "newsstack_fmp",
    )
)

# Guard: every declared scan directory must exist. A missing dir silently
# shrinks coverage (renames/deletions go undetected) — fail loudly instead.
for _scan_dir in _SCAN_DIRS:
    if not _scan_dir.is_dir():
        raise RuntimeError(
            f"_SCAN_DIRS entry {_scan_dir} does not exist — update _SCAN_DIRS "
            f"to reflect the current repository layout."
        )

# Files allowed to call open(...,"w"/"wb"/"x"/"a") OR ``Path.open("w"...)``
# without going through smc_atomic_write. Each entry's value is a brief
# rationale string (not asserted, but read by future maintainers).
#
# Keys are repo-relative POSIX paths (Deep-Review 2026-04-27).
_ALLOWED_RAW_WRITE_FILES: dict[str, str] = {
    "scripts/bake_overlay_library.py": "mkstemp + fdopen + os.replace atomic pattern (overlay .pine + manifest snapshots)",
    "scripts/plan_2_8_history_backfill.py": "fdopen + os.replace atomic pattern (json snapshots)",
    "scripts/plan_2_8_snooze_admin.py": "fdopen + os.replace atomic pattern (json snapshots)",
    "scripts/plan_2_8_alert_history.py": "fdopen + os.replace atomic pattern (json snapshots)",
    "scripts/plan_2_8_status_ledger_prune.py": "fdopen + os.replace atomic pattern (json snapshots)",
    "scripts/plan_2_8_history_export.py": "history CSV export (one-shot, not pipeline-consumed)",
    "scripts/run_ibkr_open_execution.py": "execution log CSV (one-shot, not pipeline-consumed)",
    "scripts/analyze_smc_contextual_calibration_history.py": "analysis CSV (one-shot)",
    "scripts/start_open_prep_suite.py": "process bootstrap log files",
    "scripts/export_open_prep_lists.py": "fdopen + os.replace atomic pattern (CSV exports)",
    "scripts/run_smc_measurement_benchmark.py": "benchmark CSV (one-shot, not pipeline-consumed)",
    "scripts/plan_2_8_history_archive.py": "JSONL history append (mode='a', not pipeline-consumed)",
    "scripts/plan_2_8_status_ledger.py": "JSONL status ledger append (mode='a', not pipeline-consumed)",
    "scripts/f2_flip_status.py": "JSONL flip-status journal append (mode='a', append-only audit ledger; issue #45)",
    "scripts/render_ci_gate_summary.py": "GitHub Actions $GITHUB_STEP_SUMMARY append (mode='a')",
    "scripts/resolve_workflow_runner.py": "GitHub Actions $GITHUB_OUTPUT append for runner-selection outputs (mode='a')",
    "scripts/restore_databento_export_bundle.py": "GitHub Actions $GITHUB_OUTPUT append in Databento artifact-restore helper (mode='a')",
    "scripts/backfill_live_outcomes.py": "fdopen + os.replace atomic pattern (audit JSON snapshots)",
    "scripts/build_families_telemetry.py": "fdopen + os.replace atomic pattern (C13 families telemetry JSON)",
    "scripts/collect_opening_imbalances.py": "mkstemp + os.replace atomic pattern (C13 imbalance JSONL/JSON snapshots)",
    "scripts/ib_client_id.py": "cooperative client-id registry JSON + flock file (C13 IBKR rotating client-id helper)",
    "scripts/wsh_earnings_calendar.py": "mkstemp + os.replace atomic pattern (C13 WSH earnings JSONL/JSON snapshots)",
    "scripts/build_backtest_reference.py": "fdopen + os.replace atomic pattern (drift reference + drift-input JSON)",
    "scripts/build_track_record_gate.py": "fdopen + os.replace atomic pattern (track_record_gate cache JSON)",
    "scripts/compute_live_drift.py": "fdopen + os.replace atomic pattern (drift verdict JSON)",
    "scripts/reformat_overlay_dashboard.py": "fdopen + os.replace atomic pattern (Grafana dashboard reformat)",
    "scripts/update_overlay_dashboard.py": "fdopen + os.replace atomic pattern (Grafana dashboard update)",
    "scripts/run_drift_watchdog.py": "fdopen + os.replace atomic pattern (drift_report JSON)",
    "scripts/run_smc_live_incubation.py": "audit JSONL append (mode='a', append-only ledger)",
    "scripts/build_backtest_slippage_samples.py": "mkstemp + fdopen + os.replace atomic pattern (slippage samples JSON)",
    "scripts/smoke_smc_to_ibkr_adapter.py": "mkstemp + fdopen + os.replace atomic pattern (smoke audit JSONL append)",
    # C10c research/analysis one-shot: aggregates per-bar predictions
    # to docs/research/co_firing/per_bar_predictions.jsonl for the
    # joint-outcome-modeling sprint. Not pipeline-consumed; carries the
    # ATOMIC-WRITE-EXEMPT marker inline. Added 2026-05-14 alongside the
    # C13/T4 cron wiring so push-mode validate stops shipping red.
    "scripts/runner_selection_metrics.py": "runner-selection JSONL append (mode='a', append-only metrics ledger; PR #2779)",
    "scripts/c10c_aggregate_per_bar.py": "c10c research/analysis one-shot (ATOMIC-WRITE-EXEMPT, local jsonl write)",
    # W3 (R4b audit, 2026-06-17): best-effort failure trend tracker.
    # History is an append-only JSONL (mode='a', fsync-durable).
    # Snapshot uses the mkstemp+fdopen+fsync+os.replace atomic pattern.
    "scripts/best_effort_failure_trend.py": "JSONL history append (mode='a', fsync-durable) + mkstemp+fdopen+fsync+os.replace atomic snapshot (PR #2840)",
    # smc_atomic_write itself implements the primitive — exempt by definition.
    "scripts/smc_atomic_write.py": "implements the atomic write primitive",
    # --- open_prep/ surface (Deep-Review 2026-04-27 scope expansion) ---
    # Existing surface inventoried at scope-expansion time. New raw
    # writes here MUST still pass code review; this allowlist only
    # documents the pre-existing baseline so the gate flips on.
    "open_prep/alerts.py": "alert ledger JSONL append (mode='a')",
    "open_prep/candidate_weights.py": "candidate-weights snapshot (one-shot, not pipeline-consumed)",
    "open_prep/diff.py": "diff text output (one-shot tool)",
    "open_prep/feature_importance_report.py": "feature-importance report text (one-shot tool)",
    "open_prep/outcome_backfill.py": "outcome backfill audit + state JSON",
    "open_prep/outcomes.py": "outcomes ledger snapshots",
    "open_prep/realtime_signals.py": "realtime-signals state + audit JSONL",
    "open_prep/watchlist.py": "watchlist snapshot",
    # --- rl/ surface ---
    "rl/extensions.py": "rl extension state (research-only, not pipeline-consumed)",
    # --- governance/ surface ---
    "governance/alpha_ledger.py": "alpha-budget ledger JSON (governance audit trail)",
    # --- Audit E-1 2026-06-13 (AW-1) scope-expansion baseline ---
    # smc_core/ + smc_integration/ + newsstack_fmp/: all pre-existing
    # sites verified as mkstemp/fdopen + os.replace atomic patterns.
    "smc_core/benchmark.py": "fdopen + os.replace atomic pattern (benchmark JSON)",
    "smc_core/ensemble_quality.py": "fdopen + os.replace atomic pattern (ensemble-quality JSON)",
    "smc_core/event_ledger.py": "fdopen + os.replace atomic pattern (event ledger JSON)",
    "smc_core/inference/null_cache.py": "mkstemp + fsync + os.replace atomic pattern (null-distribution cache JSON)",
    "smc_core/scoring.py": "fdopen + os.replace atomic pattern (scoring snapshot JSON)",
    "smc_integration/batch.py": "fdopen + os.replace atomic pattern (batch artifact JSON)",
    "smc_integration/provider_health.py": "fdopen + os.replace atomic pattern (provider-health JSON)",
    "smc_integration/structure_batch.py": "fdopen + os.replace atomic pattern (structure batch JSON)",
    "newsstack_fmp/open_prep_export.py": "mkstemp + fsync + os.replace atomic pattern (news candidates JSON export)",
    "scripts/collect_drift_calibration_corpus.py": "JSONL corpus append (mode='a', append-only calibration corpus; issue #2798)",
    # Repo-root modules.
    "streamlit_terminal.py": "_write_json_atomic mkstemp + fsync + os.replace; plus JSONL append (mode='a', audit trail)",
    "terminal_export.py": "JSONL append (mode='a', error/audit trail) + mkstemp + os.replace VisiData exports",
}

_WRITE_MODES: frozenset[str] = frozenset({"w", "wb", "wt", "x", "xb", "xt", "a", "ab", "at",
                                          "w+", "wb+", "r+", "rb+"})


def _is_write_mode(node: ast.AST) -> bool:
    """Return True if the AST node is a string literal with a write-ish mode."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        # Normalise: drop "+" trailing since "w+" still writes.
        return node.value in _WRITE_MODES
    return False


def _scan_raw_writes(source: str) -> list[int]:
    """Return 1-based line numbers of raw write call sites in ``source``."""
    tree = ast.parse(source)
    hits: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue

        # Pattern A: open(path, "w"...) — bare or builtins
        if isinstance(node.func, ast.Name) and node.func.id == "open":
            mode_arg: ast.AST | None = node.args[1] if len(node.args) >= 2 else None
            if mode_arg is None:
                # Check for mode= kwarg
                for kw in node.keywords:
                    if kw.arg == "mode":
                        mode_arg = kw.value
                        break
            if mode_arg is not None and _is_write_mode(mode_arg):
                hits.append(node.lineno)
            continue

        # Pattern B: <path>.open("w"...)
        if isinstance(node.func, ast.Attribute) and node.func.attr == "open":
            mode_arg = node.args[0] if node.args else None
            if mode_arg is None:
                for kw in node.keywords:
                    if kw.arg == "mode":
                        mode_arg = kw.value
                        break
            if mode_arg is not None and _is_write_mode(mode_arg):
                hits.append(node.lineno)
            continue

        # Pattern C: os.fdopen(fd, "w"...) — atomic pattern, but still counts
        # as a raw write site. The allowlist's rationale documents these.
        if (isinstance(node.func, ast.Attribute) and node.func.attr == "fdopen"
                and isinstance(node.func.value, ast.Name) and node.func.value.id == "os"):
            mode_arg = node.args[1] if len(node.args) >= 2 else None
            if mode_arg is not None and _is_write_mode(mode_arg):
                hits.append(node.lineno)
            continue

    return sorted(set(hits))


def _iter_scan_files() -> list[Path]:
    """All production .py files in scope: scan dirs (recursive) + repo root."""
    files: list[Path] = []
    for scan_dir in _SCAN_DIRS:
        files.extend(sorted(scan_dir.rglob("*.py")))
    # Audit E-1 2026-06-13 (AW-1): repo-root modules (non-recursive — the
    # subdirectories are covered by _SCAN_DIRS or are out of scope).
    # Exclude conftest.py and test_*.py: test helpers are not production surfaces.
    files.extend(
        p
        for p in sorted(REPO_ROOT.glob("*.py"))
        if not p.name.startswith("test_") and p.name != "conftest.py"
    )
    return files


def _files_with_raw_writes() -> dict[str, list[int]]:
    out: dict[str, list[int]] = {}
    for py in _iter_scan_files():
        try:
            source = py.read_text(encoding="utf-8")
        except OSError:
            continue
        try:
            hits = _scan_raw_writes(source)
        except SyntaxError as exc:
            raise ValueError(
                f"SyntaxError while scanning {py} — fix the syntax error in "
                f"that file: {exc}"
            ) from exc
        if hits:
            rel = py.relative_to(REPO_ROOT).as_posix()
            out[rel] = hits
    return out


def test_scripts_directory_exists() -> None:
    """Sanity: scripts/ must contain a non-trivial number of files."""
    assert SCRIPTS_DIR.is_dir()
    pys = list(SCRIPTS_DIR.glob("*.py"))
    assert len(pys) >= 30, f"unexpectedly few scripts: {len(pys)}"


def test_atomic_write_helper_file_present() -> None:
    """Sanity: the atomic-write primitive must exist."""
    helper = SCRIPTS_DIR / "smc_atomic_write.py"
    assert helper.is_file()
    text = helper.read_text(encoding="utf-8")
    assert "atomic_write_parquet" in text
    assert "atomic_write_csv" in text


def test_no_unsanctioned_raw_writes_in_scripts() -> None:
    """Pin: every raw-write file under the scanned dirs must appear in the allowlist."""
    observed = _files_with_raw_writes()
    extras = sorted(set(observed) - set(_ALLOWED_RAW_WRITE_FILES))
    assert not extras, (
        "NEW file(s) introduced raw open(...,'w'/'wb'/'x') call sites:\n"
        + "\n".join(f"  {name}: lines {observed[name]}" for name in extras)
        + "\nMigrate to scripts.smc_atomic_write or add to _ALLOWED_RAW_WRITE_FILES "
        "with a rationale."
    )


def test_allowlist_is_pruned() -> None:
    """Pin: every entry in the allowlist must still have at least one raw write.

    Prevents the allowlist from accumulating stale entries after refactors.
    """
    observed = _files_with_raw_writes()
    stale = sorted(set(_ALLOWED_RAW_WRITE_FILES) - set(observed))
    # smc_atomic_write.py is exempt: it implements the primitive but its
    # internal os.replace is not flagged by our scanner — keep it in the
    # allowlist as a doc anchor.
    stale = [s for s in stale if s != "scripts/smc_atomic_write.py"]
    assert not stale, (
        f"Allowlist contains files that no longer perform raw writes: {stale}. "
        "Remove them from _ALLOWED_RAW_WRITE_FILES."
    )

