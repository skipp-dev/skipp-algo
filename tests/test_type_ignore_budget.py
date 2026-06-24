"""Audit pin: ``type: ignore`` per-file count budget.

A ``# type: ignore`` is a deliberate type-checker suppression; collectively
they are a reservoir of latent silent type-bugs.  Line numbers are too
churn-prone for a per-site frozen ledger (these comments cluster densely
in pandas/streamlit-bridge files), so we use a **per-file count budget**:

* ``_FROZEN_FILE_COUNTS`` records the exact ``# type: ignore`` count per
  file at the time this pin landed (19 files, 81 total suppressions).
* ``test_no_type_ignore_count_increases`` fails on (a) any file whose
  count exceeds its frozen budget, (b) any new file that introduces a
  ``# type: ignore``.
* ``test_no_stale_file_in_ledger`` fails on any ledger entry whose file
  no longer exists or no longer contains any ``# type: ignore``.
* Decreases are *encouraged* but flagged via a soft test that prints
  the new lower count so the ledger can be tightened deliberately.

Categories observed:
* pandas / streamlit / databento bridge wrappers (``# type: ignore[attr-defined]``,
  ``[import-untyped]`` for optional deps).
* ``terminal_poller`` Finnhub schema-shimming.
* ``newsstack_fmp/scoring`` enum-narrowing.
"""

from __future__ import annotations

import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent

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
        "scripts",
        "tests",
        "SMC++",
    }
)

_TYPE_IGNORE_RE = re.compile(r"type:\s*ignore")


def _iter_prod_files() -> list[Path]:
    out: list[Path] = []
    for path in _REPO_ROOT.rglob("*.py"):
        if any(part in _DIR_EXCLUDE for part in path.relative_to(_REPO_ROOT).parts):
            continue
        out.append(path)
    return sorted(out)


def _count_in_file(path: Path) -> int:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):  # pragma: no cover - defensive
        return 0
    return sum(1 for line in text.splitlines() if _TYPE_IGNORE_RE.search(line))


def _all_counts() -> dict[str, int]:
    out: dict[str, int] = {}
    for path in _iter_prod_files():
        n = _count_in_file(path)
        if n:
            out[path.relative_to(_REPO_ROOT).as_posix()] = n
    return out


# Frozen ``# type: ignore`` count per file at the time this pin landed.
# Reductions are welcome; keep this ledger aligned with the current scan.
# Reductions are welcome — when a file's count drops, lower its entry
# (or remove it entirely if the count reaches 0).
_FROZEN_FILE_COUNTS: dict[str, int] = {
    "databento_volatility_screener.py": 1,  # A8-Telemetry-Mini: optional ``import resource`` shim for non-POSIX (CI is POSIX-only).
    "governance/family_cross_lead_lag_hy_v3.py": 2,  # HY estimator: control-flow guarantees ``prev_p``/``curve`` are non-None at the ``math.log``/``float`` call sites, but mypy cannot narrow across the ``continue`` guards (``[arg-type]``).
    "governance/run_manifest.py": 1,
    "ml/calibration/probability_calibrator.py": 1,
    "ml/training/lgbm_family_trainer.py": 2,
    "ml/training/xgb_family_trainer.py": 1,  # PR #2241: 2 bare ignores replaced by 1 specific `[import-not-found]` on `import xgboost`.
    "ml/walkforward.py": 1,
    "newsstack_fmp/_bz_http.py": 2,
    "newsstack_fmp/ingest_benzinga.py": 2,  # websockets + feedparser (both import-untyped).
    "newsstack_fmp/normalize.py": 1,
    "newsstack_fmp/scoring.py": 5,
    "newsstack_fmp/store_sqlite.py": 3,
    "open_prep/alerts.py": 1,
    "open_prep/diff.py": 1,
    "open_prep/streamlit_monitor.py": 24,  # rebaselined 2026-05-30 PR #2451 (was 25; -1 for benzinga dead-code removal)
    "rl/agents/ppo_slicer.py": 4,
    "rl/agents/sac_sizer.py": 2,
    "rl/simulator/execution_env.py": 5,
    "rl/simulator/sb3_execution_env.py": 5,
    "smc_adapters/regime_bridge.py": 2,
    "smc_core/layering.py": 1,
    "smc_core/resilient.py": 2,
    "streamlit_terminal.py": 7,
    "terminal_ai_insights.py": 1,  # PR #2128: tuple-return (bool, T) miss-cache helper signature confuses generic narrowing.
    "terminal_bitcoin.py": 18,
    "terminal_export.py": 1,
    "terminal_finnhub.py": 4,
    "terminal_fmp_insights.py": 1,  # PR #2128: tuple-return (bool, T) miss-cache helper signature confuses generic narrowing.
    "terminal_forecast.py": 2,
    "terminal_poller.py": 12,  # rebaselined 2026-05-30 PR #2451 (was 13; -1 for dead-code removal)
    "terminal_spike_scanner.py": 1,
    "terminal_tabs/tab_live_incubation.py": 1,
    "terminal_technicals.py": 2,
    "terminal_tradingview_news.py": 1,  # PR #2128: tuple-return (bool, T) miss-cache helper signature confuses generic narrowing.
}


def test_no_type_ignore_count_increases() -> None:
    """Tripwire: no file may exceed its frozen ``# type: ignore`` budget,
    and no new file may introduce one without ledger update."""
    current = _all_counts()
    over_budget: list[str] = []
    new_files: list[str] = []
    for rel, count in sorted(current.items()):
        budget = _FROZEN_FILE_COUNTS.get(rel)
        if budget is None:
            new_files.append(f"{rel}: {count} suppressions (no ledger entry)")
            continue
        if count > budget:
            over_budget.append(
                f"{rel}: {count} > budget {budget} (added {count - budget})"
            )
    msgs: list[str] = []
    if over_budget:
        msgs.append("Files exceeding their ``# type: ignore`` budget:")
        msgs.extend(f"  - {m}" for m in over_budget)
    if new_files:
        msgs.append(
            "New files introducing ``# type: ignore`` — fix the type instead, "
            "or add the file to _FROZEN_FILE_COUNTS with a documented reason:"
        )
        msgs.extend(f"  - {m}" for m in new_files)
    assert not msgs, "\n".join(msgs)


def test_no_stale_file_in_ledger() -> None:
    """Stale guard: every ledger file must still exist and still carry suppressions."""
    current = _all_counts()
    stale: list[str] = []
    for rel in sorted(_FROZEN_FILE_COUNTS):
        path = _REPO_ROOT / rel
        if not path.is_file():
            stale.append(f"{rel} (file no longer exists)")
            continue
        if rel not in current:
            stale.append(
                f"{rel} (no remaining ``# type: ignore`` — remove from ledger)"
            )
    assert not stale, (
        "Stale entries in _FROZEN_FILE_COUNTS — refresh:\n  - "
        + "\n  - ".join(stale)
    )


def test_total_budget_matches_inventory() -> None:
    """Sanity: total ledger budget must equal current scanned total."""
    current_total = sum(_all_counts().values())
    ledger_total = sum(_FROZEN_FILE_COUNTS.values())
    assert current_total == ledger_total, (
        f"# type: ignore total drift: ledger={ledger_total}, scan={current_total}. "
        f"Either reduce a budget (decreases welcome) or add a new file."
    )


def test_prod_file_inventory_sane() -> None:
    files = _iter_prod_files()
    assert len(files) >= 50, (
        f"Production *.py scan only found {len(files)} files — "
        f"_DIR_EXCLUDE may be over-broad or sparse-checkout incomplete."
    )
