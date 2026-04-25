"""Inventory pin for raw file-write call sites under ``scripts/``.

Background
==========

Audit `docs/audits/smc-system-review-2026-04-24.md` (I-1) flagged a noisy
1003-vs-92 ratio for raw write candidates. After AST-based filtering the
real surface is ~15 raw writes outside ``scripts/smc_atomic_write.py``.

This test pins the explicit allowlist of files that may bypass
``atomic_write_parquet`` / ``atomic_write_csv``. Each entry has a brief
rationale.

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

# Files allowed to call open(...,"w"/"wb"/"x"/"a") OR ``Path.open("w"...)``
# without going through smc_atomic_write. Each entry's value is a brief
# rationale string (not asserted, but read by future maintainers).
_ALLOWED_RAW_WRITE_FILES: dict[str, str] = {
    "generate_showcase_summary.py": "showcase artifacts (advisory, not pipeline-consumed)",
    "plan_2_8_history_backfill.py": "fdopen + os.replace atomic pattern (json snapshots)",
    "plan_2_8_snooze_admin.py": "fdopen + os.replace atomic pattern (json snapshots)",
    "plan_2_8_alert_history.py": "fdopen + os.replace atomic pattern (json snapshots)",
    "plan_2_8_status_ledger_prune.py": "fdopen + os.replace atomic pattern (json snapshots)",
    "plan_2_8_history_export.py": "history CSV export (one-shot, not pipeline-consumed)",
    "run_ibkr_open_execution.py": "execution log CSV (one-shot, not pipeline-consumed)",
    "analyze_smc_contextual_calibration_history.py": "analysis CSV (one-shot)",
    "start_open_prep_suite.py": "process bootstrap log files",
    "export_open_prep_lists.py": "fdopen + os.replace atomic pattern (CSV exports)",
    "run_smc_measurement_benchmark.py": "benchmark CSV (one-shot, not pipeline-consumed)",
    "plan_2_8_history_archive.py": "JSONL history append (mode='a', not pipeline-consumed)",
    "plan_2_8_status_ledger.py": "JSONL status ledger append (mode='a', not pipeline-consumed)",
    "render_ci_gate_summary.py": "GitHub Actions $GITHUB_STEP_SUMMARY append (mode='a')",
    # smc_atomic_write itself implements the primitive — exempt by definition.
    "smc_atomic_write.py": "implements the atomic write primitive",
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


def _files_with_raw_writes() -> dict[str, list[int]]:
    out: dict[str, list[int]] = {}
    for py in sorted(SCRIPTS_DIR.glob("*.py")):
        try:
            source = py.read_text(encoding="utf-8")
        except OSError:
            continue
        try:
            hits = _scan_raw_writes(source)
        except SyntaxError:
            continue
        if hits:
            out[py.name] = hits
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
    """Pin: every raw-write file in scripts/ must appear in the allowlist."""
    observed = _files_with_raw_writes()
    extras = sorted(set(observed) - set(_ALLOWED_RAW_WRITE_FILES))
    assert not extras, (
        "NEW script(s) introduced raw open(...,'w'/'wb'/'x') call sites:\n"
        + "\n".join(f"  scripts/{name}: lines {observed[name]}" for name in extras)
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
    stale = [s for s in stale if s != "smc_atomic_write.py"]
    assert not stale, (
        f"Allowlist contains files that no longer perform raw writes: {stale}. "
        "Remove them from _ALLOWED_RAW_WRITE_FILES."
    )
