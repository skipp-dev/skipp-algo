"""Defense pin: frozen ledger of ``# noqa`` lint-suppression markers in
first-party non-test code.

Rationale
---------
``# noqa`` (with or without specific code list) silences linter findings.
Each suppression is a deliberate decision that should require justification.
Without a ledger, suppressions accumulate silently and the codebase drifts
toward unmaintained-quality regions.

Sister of #213 (silent-error-swallow ledger), #218 (Path text-IO encoding),
#220 (built-in open encoding). The ledger may only **shrink**: removing
suppressions is welcome; adding new ones requires a deliberate ledger bump
in the same PR.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]

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
}

_NOQA_RE = re.compile(r"#\s*noqa\b", re.IGNORECASE)

# Frozen ledger — exactly today's surface (2026-04-25).
_FROZEN_SITES: dict[str, int] = {
    "newsstack_fmp/ingest_benzinga.py": 1,
    "newsstack_fmp/ingest_benzinga_calendar.py": 1,
    "newsstack_fmp/ingest_benzinga_financial.py": 1,
    "newsstack_fmp/pipeline.py": 1,
    "open_prep/streamlit_monitor.py": 1,
    "scripts/check_pine_legacy_drift.py": 1,
    "scripts/emit_fvg_context_pine.py": 3,
    "scripts/f2_apply_contextual_calibration.py": 1,
    "scripts/fvg_asia_real_sample.py": 3,
    "scripts/fvg_quality_quartile_gate.py": 1,
    "scripts/fvg_quality_recalibration.py": 1,
    "scripts/fx_probe_universe.py": 1,
    "scripts/g23_ab_watchdog.py": 1,
    "scripts/generate_smc_micro_profiles.py": 1,
    "scripts/smc_analyst_enrichment.py": 1,
    "scripts/smc_htf_context.py": 1,
    "scripts/smc_insider_enrichment.py": 1,
    "scripts/smc_institutional_enrichment.py": 1,
    "scripts/smc_microstructure_base_runtime.py": 3,
    "scripts/smc_session_context.py": 1,
    "scripts/tv_recovery.py": 1,
    "scripts/verify_branch_protection.py": 1,
    "smc_core/resilient.py": 1,
    "streamlit_terminal.py": 1,
    "terminal_bitcoin.py": 1,
    "terminal_finnhub.py": 2,
    "terminal_tabs/__init__.py": 17,
}
_FROZEN_TOTAL = sum(_FROZEN_SITES.values())


def _iter_python_files() -> list[Path]:
    out: list[Path] = []
    for path in _ROOT.rglob("*.py"):
        if any(part in _DIR_EXCLUDE for part in path.relative_to(_ROOT).parts):
            continue
        out.append(path)
    return out


def _observed_counts() -> dict[str, int]:
    counts: dict[str, int] = {}
    for path in _iter_python_files():
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        n = sum(1 for line in text.splitlines() if _NOQA_RE.search(line))
        if n:
            counts[path.relative_to(_ROOT).as_posix()] = n
    return counts


def test_noqa_total_does_not_grow() -> None:
    observed = _observed_counts()
    total = sum(observed.values())
    assert total <= _FROZEN_TOTAL, (
        f"Total `# noqa` suppressions grew: frozen={_FROZEN_TOTAL}, "
        f"observed={total}. Justify and update _FROZEN_SITES + _FROZEN_TOTAL "
        "in the same PR, or remove the suppression."
    )


def test_no_new_noqa_files() -> None:
    observed = _observed_counts()
    new_files = sorted(set(observed) - set(_FROZEN_SITES))
    assert not new_files, (
        "New file(s) introduced `# noqa` suppressions. Either fix the "
        f"underlying lint warning or update _FROZEN_SITES. New: {new_files}"
    )


@pytest.mark.parametrize("rel,expected", sorted(_FROZEN_SITES.items()))
def test_per_file_noqa_count_does_not_grow(rel: str, expected: int) -> None:
    observed = _observed_counts()
    actual = observed.get(rel, 0)
    assert actual <= expected, (
        f"{rel}: `# noqa` suppression count grew from {expected} to {actual}. "
        "Either fix the lint warning or bump _FROZEN_SITES in the same PR."
    )
