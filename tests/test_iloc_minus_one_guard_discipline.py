"""Pin: production OHLC derivation paths must consult
:func:`smc_core.bar_close_guard.guard_closed_bars` before snapshotting
the most recent bar (H-7, system review 2026-04-24).

Why
---
Multiple SMC derivers read ``df.iloc[-1]`` as "the current bar" but
the upstream provider has no notion of a closed-vs-partial flag. A
new derivation file that lifts the same pattern without consulting
the guard would silently regress the audit fix.

This is a **forward-looking** pin: existing call-sites are documented
in :data:`_KNOWN_HOTSPOTS` with a short justification (the code-paths
predate the guard and are wrapped via caller-provided ``as_of`` in
their entry points). New ``iloc[-1]`` sites in any file under
``smc_core/`` or ``scripts/`` must either:

1. Be in the same module/function as a call to ``guard_closed_bars``;
2. Carry a ``# BAR-CLOSE-EXEMPT: <reason>`` marker on the same line
   or one of the 4 surrounding lines; OR
3. Be added to :data:`_KNOWN_HOTSPOTS` with a justification.
"""
from __future__ import annotations

import ast
from pathlib import Path
from typing import Final

REPO_ROOT = Path(__file__).resolve().parent.parent

# Files within these subtrees are scanned. Tests/fixtures are skipped.
_SCAN_DIRS: Final[tuple[Path, ...]] = (
    REPO_ROOT / "smc_core",
    REPO_ROOT / "scripts",
)

# Existing iloc[-1] sites at the time of the H-7 baseline. Each entry
# is (relative_path, lineno, brief_justification). The pin allows
# these — new sites must justify themselves via the exempt comment or
# by extending this set.
_KNOWN_HOTSPOTS: Final[frozenset[tuple[str, int]]] = frozenset(
    {
        # smc_core/session_context.py — D/W/M open snapshots from
        # already-resampled HTF buckets; the daily/weekly/monthly
        # frames are produced via pandas resample which drops the
        # partial bucket when the source frame is bar-close clean.
        ("smc_core/session_context.py", 124),
        ("smc_core/session_context.py", 130),
        ("smc_core/session_context.py", 136),
        # smc_core/vol_regime.py — ATR / variance current values; the
        # caller passes a frame post-`guard_closed_bars` in production.
        ("smc_core/vol_regime.py", 135),
        ("smc_core/vol_regime.py", 151),
        # smc_core/htf_context.py — IPDA range needs last + previous
        # HTF candle; partial HTF bar is acceptable (range only widens).
        ("smc_core/htf_context.py", 103),
        # scripts/smc_structure_state.py — last close used for CHoCH/BOS;
        # script-level entry validates frame.
        ("scripts/smc_structure_state.py", 141),
        # scripts/smc_imbalance_lifecycle.py — FVG mitigation tests need
        # the live tip; correctness is preserved because mitigation
        # detection is monotonic w.r.t. partial-bar high/low extension.
        ("scripts/smc_imbalance_lifecycle.py", 132),
        ("scripts/smc_imbalance_lifecycle.py", 133),
        ("scripts/smc_imbalance_lifecycle.py", 134),
        # scripts/market_structure_features.py — EMA snapshot for trend
        # sign; backtest-only path operates on closed historical frames.
        ("scripts/market_structure_features.py", 105),
        ("scripts/market_structure_features.py", 106),
        # scripts/explicit_structure_from_bars.py — explicit inline
        # guard immediately above (`agg = agg.iloc[:-1]` if trailing
        # aggregated bucket exceeds the source frame's max timestamp).
        ("scripts/explicit_structure_from_bars.py", 77),
        # scripts/smc_session_structure.py — previous-day row + opening
        # range break; both consume closed daily frames.
        ("scripts/smc_session_structure.py", 96),
        ("scripts/smc_session_structure.py", 146),
        # scripts/smc_range_regime.py — last close vs lookback range;
        # closed daily frame.
        ("scripts/smc_range_regime.py", 126),
        # scripts/smc_range_profile_regime.py — breakout / value-area /
        # liquidity / centre snapshots, all from closed-bar profile.
        ("scripts/smc_range_profile_regime.py", 137),
        ("scripts/smc_range_profile_regime.py", 226),
        ("scripts/smc_range_profile_regime.py", 256),
        ("scripts/smc_range_profile_regime.py", 278),
        # scripts/databento_preopen_fast.py — premarket "last" close
        # snapshot from already-closed pre-market session window.
        ("scripts/databento_preopen_fast.py", 428),
        # scripts/databento_production_export.py — same premarket "last"
        # snapshot, production export path.
        ("scripts/databento_production_export.py", 2301),
        # scripts/generate_bullish_quality_scanner.py — manifest scalar
        # lookups (source_data_fetched_at / latest window_tag); not bar
        # data.
        ("scripts/generate_bullish_quality_scanner.py", 77),
        ("scripts/generate_bullish_quality_scanner.py", 177),
        # scripts/generate_databento_watchlist.py — manifest scalar
        # lookup (latest manifest string value); not bar data.
        ("scripts/generate_databento_watchlist.py", 143),
        # scripts/smc_microstructure_base_runtime.py — OHLC reduction
        # over a full closed frame (open from first row, close from
        # last row).
        ("scripts/smc_microstructure_base_runtime.py", 817),
    }
)

# Files where iloc[-1] is structurally fine (test fixtures, manifest
# emitters, surface generators that operate on summary tables, etc.).
_FILE_LEVEL_EXEMPT: Final[frozenset[str]] = frozenset(
    {
        "smc_core/bar_close_guard.py",  # the guard itself
    }
)

_EXEMPT_MARKER = "BAR-CLOSE-EXEMPT"
_EXEMPT_PROXIMITY = 4


def _is_iloc_minus_one(node: ast.AST) -> bool:
    """Detect ``something.iloc[-1]`` in any AST shape."""
    if not isinstance(node, ast.Subscript):
        return False
    target = node.value
    if not (isinstance(target, ast.Attribute) and target.attr == "iloc"):
        return False
    sl = node.slice
    if isinstance(sl, ast.UnaryOp) and isinstance(sl.op, ast.USub):
        operand = sl.operand
        if isinstance(operand, ast.Constant) and operand.value == 1:
            return True
    return False


def _has_nearby_exempt(lines: list[str], lineno: int) -> bool:
    start = max(1, lineno - _EXEMPT_PROXIMITY)
    end = min(len(lines), lineno + _EXEMPT_PROXIMITY)
    return any(_EXEMPT_MARKER in lines[ln - 1] for ln in range(start, end + 1))


def _module_uses_guard(tree: ast.Module) -> bool:
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id == "guard_closed_bars":
            return True
        if isinstance(node, ast.Attribute) and node.attr == "guard_closed_bars":
            return True
    return False


def test_no_unjustified_iloc_minus_one_in_derivation_files() -> None:
    violations: list[str] = []
    for root in _SCAN_DIRS:
        for path in root.rglob("*.py"):
            rel = path.relative_to(REPO_ROOT).as_posix()
            if rel in _FILE_LEVEL_EXEMPT:
                continue
            text = path.read_text(encoding="utf-8")
            try:
                tree = ast.parse(text, filename=str(path))
            except SyntaxError:
                continue
            module_safe = _module_uses_guard(tree)
            lines = text.splitlines()
            for node in ast.walk(tree):
                if not _is_iloc_minus_one(node):
                    continue
                lineno = node.lineno
                if (rel, lineno) in _KNOWN_HOTSPOTS:
                    continue
                if module_safe:
                    continue
                if _has_nearby_exempt(lines, lineno):
                    continue
                violations.append(f"{rel}:{lineno}")

    assert not violations, (
        "New `iloc[-1]` site without bar-close discipline. Either:\n"
        "  - call smc_core.bar_close_guard.guard_closed_bars(df, interval=..., now=...) "
        "earlier in the same module,\n"
        "  - add a `# BAR-CLOSE-EXEMPT: <reason>` marker within 4 lines, or\n"
        "  - extend _KNOWN_HOTSPOTS in tests/test_iloc_minus_one_guard_discipline.py "
        "with a brief justification.\n"
        "Sites:\n" + "\n".join(f"  - {v}" for v in violations)
    )


def test_known_hotspots_still_resolve() -> None:
    """Sanity: every pinned (path, lineno) still exists and contains an
    iloc[-1] reference. Detects line drift and lets contributors
    update :data:`_KNOWN_HOTSPOTS` deliberately."""
    for rel, lineno in _KNOWN_HOTSPOTS:
        path = REPO_ROOT / rel
        assert path.exists(), f"{rel} no longer exists; update _KNOWN_HOTSPOTS"
        text = path.read_text(encoding="utf-8").splitlines()
        assert 1 <= lineno <= len(text), (
            f"{rel}:{lineno} out of range; update _KNOWN_HOTSPOTS"
        )
        # Allow short drift (±2 lines) before failing — but flag if the
        # pinned line is clearly no longer an iloc[-1] site.
        window = "\n".join(text[max(0, lineno - 3) : lineno + 2])
        assert "iloc[-1]" in window, (
            f"{rel}:{lineno} no longer references `iloc[-1]` "
            "(window: ±2 lines). Update _KNOWN_HOTSPOTS."
        )
