"""Audit pin: ``nonlocal`` keyword frozen-inventory budget.

``nonlocal`` indicates closure-mutated state — almost always a hidden
state-machine in disguise.  We freeze the current 5 known sites and
trip on (a) any new site, (b) silent name additions to an existing
``nonlocal`` declaration.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from tests._guard_corpus import parse_module

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


def _iter_prod_files() -> list[Path]:
    out: list[Path] = []
    for path in _REPO_ROOT.rglob("*.py"):
        if any(part in _DIR_EXCLUDE for part in path.relative_to(_REPO_ROOT).parts):
            continue
        out.append(path)
    return sorted(out)


def _all_nonlocal_sites() -> list[tuple[str, int, tuple[str, ...]]]:
    sites: list[tuple[str, int, tuple[str, ...]]] = []
    for path in _iter_prod_files():
        tree = parse_module(path)
        if tree is None:  # pragma: no cover
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Nonlocal):
                rel = path.relative_to(_REPO_ROOT).as_posix()
                sites.append((rel, node.lineno, tuple(sorted(node.names))))
    return sorted(sites)


# Frozen ``nonlocal`` sites at the time this pin landed (5 total).
# Categories:
# * ``databento_volatility_screener._fast_progress_*`` — single-callback
#   progress-bar smoothing closure inside a one-shot Streamlit run.
# * ``smc_core/ensemble_quality.py`` — weighted-aggregate accumulator
#   within an ensemble scoring helper closure.
_FROZEN_SITES: frozenset[tuple[str, int, tuple[str, ...]]] = frozenset(
    {
        # Phase-5.2 Quickfix B (PR #2058): Item 1 inserted +7 lines around Z 2531
        # in databento_volatility_screener.py, shifting the four ``_fast_progress_*``
        # nonlocal sites from 4682-4685 to 4689-4692. No semantic change.
        # A8.1 (PR #2078): all four sites shifted +36 by
        # _rss_current_mib + _fmt_rss_pair helpers + 13 step9a markers.
        # A8.1.5 (this PR): Series-Build refactor in _build_close_{trade,outcome}_aggregates
        # added +22 net lines around L2876+, shifting the four sites by +22.
        # PR #2113 (Copilot follow-up to PR #2112 L5): explanatory comments
        # added at the two ``utc=True`` trade_date sites in
        # _build_close_{trade,outcome}_aggregates inserted +7 lines, drifting
        # the four ``_fast_progress_*`` sites from 4917-4920 to 4924-4927.
        # F-V8-cutover (this PR): _read_cached_frame skew-fix port from
        # PR #2277 added ~16 lines in databento_utils.py — unrelated to this
        # file, but inventory diff caught the volatility_screener sites
        # drifting further by +16 to 4940-4943 from upstream main reshuffles.
        # PR #2309 / follow-up: strict-json + open-prep mainline changes
        # shifted the same four closure-progress sites by +65 lines. The
        # nonlocal names and owning closure are unchanged.
        # #2334 (PR #2338): cache-pollution filter blocks in 3 collectors shifted these
        # sites by +26 lines (5005-5008 -> 5031-5034). #2334 (PR #2338): the
        # main-merge into the cache-redesign branch + the _cached_frame_coverage
        # helper inserts shifted them again to 5162-5165. Coverage-bug fix added
        # a 3-line comment in load_daily_bars -> 5165-5168.
        # 2026-05-23 PR #2338 follow-up: partial-cache block shifted these
        # four nonlocal sites by another +33 (5165-5168 -> 5198-5201).
        # PR #2339: +170 (5198→5368) by universe-version metadata helpers,
        # drift detector, and per-collector captured/current symbol wiring
        # in the cache-coverage funnels above the fast-progress callback,
        # plus drift-detector helpers + urlopen-ledger alignment shifting
        # the four ``_fast_progress_*`` sites further down the file. No
        # semantic change to the progress closure itself.
        # 2026-06-10 (#2670 W9): timestamp_substitutions disclosure shifted
        # the four sites +27 (5368-5371 -> 5395-5398).
        ("databento_volatility_screener.py", 5398, ("_fast_progress_pct",)),
        ("databento_volatility_screener.py", 5399, ("_fast_progress_step",)),
        ("databento_volatility_screener.py", 5400, ("_fast_progress_total",)),
        ("databento_volatility_screener.py", 5401, ("_fast_eta_smooth_seconds",)),
        ("smc_core/ensemble_quality.py", 188, ("active_weight", "weighted_total")),
        # 2026-06-25: worker-thread target for interruptible AsyncNewsstackPoller
        # poll loop uses nonlocal to ferry result/error back to the caller.
        # 2026-06-28 (semantic monitoring): shifted +20 lines by readiness metrics.
        ("open_prep/realtime_signals.py", 582, ("error", "result")),
    }
)


def test_no_new_nonlocal_sites() -> None:
    current = set(_all_nonlocal_sites())
    new = current - _FROZEN_SITES
    assert not new, (
        "New ``nonlocal`` sites — closure-mutated state is a code-smell, "
        "prefer an explicit class or @dataclass:\n  - "
        + "\n  - ".join(f"{f}:{ln} names={names}" for f, ln, names in sorted(new))
    )


@pytest.mark.parametrize("site", sorted(_FROZEN_SITES))
def test_frozen_nonlocal_site_still_present(
    site: tuple[str, int, tuple[str, ...]],
) -> None:
    rel, lineno, names = site
    path = _REPO_ROOT / rel
    assert path.is_file(), f"{rel} no longer exists — refresh _FROZEN_SITES"
    tree = parse_module(path)
    if tree is None:
        pytest.fail(f"{rel} no longer parses")
    found = [
        (n.lineno, tuple(sorted(n.names)))
        for n in ast.walk(tree)
        if isinstance(n, ast.Nonlocal)
    ]
    assert (lineno, names) in found, (
        f"Frozen ``nonlocal`` site drifted: {rel}:{lineno} names={names}. "
        f"Current sites in file: {sorted(found)}"
    )


def test_inventory_parity() -> None:
    current = set(_all_nonlocal_sites())
    missing = _FROZEN_SITES - current
    extra = current - _FROZEN_SITES
    assert not missing and not extra, (
        f"_FROZEN_SITES out of sync. missing={sorted(missing)} extra={sorted(extra)}"
    )


def test_prod_file_inventory_sane() -> None:
    files = _iter_prod_files()
    assert len(files) >= 50, (
        f"Production *.py scan only found {len(files)} files — "
        f"_DIR_EXCLUDE may be over-broad or sparse-checkout incomplete."
    )
