#!/usr/bin/env python3
"""
Bulk-slim a SkippALGO-family Pine Script by delegating shared function bodies
to the 5 skipp_* libraries.

Usage:
    python scripts/pine_slim.py <file.pine> [--dry-run]

Steps:
 1. Inject import statements after `indicator(…)` or `strategy(…)` line.
 2. For each known pure-function mapping, replace the multi-line body
    with a one-line delegate.
 3. Report line savings.

Safety:
 - Functions that depend on global inputs are skipped.
 - The script only touches the function *body* (everything between
   `f_name(…) =>` and the next blank line or next definition).
 - Dry-run mode shows what would change without writing.
"""

import argparse
import re
import sys
from pathlib import Path

# ──────────────────────────────────────────────────────────────────────
# Library import block to inject
# ──────────────────────────────────────────────────────────────────────
IMPORT_BLOCK = """\
import preuss_steffen/skipp_math/1       as m
import preuss_steffen/skipp_scoring/1    as sc
import preuss_steffen/skipp_indicators/1 as ind
import preuss_steffen/skipp_calibration/1 as cal
import preuss_steffen/skipp_labels/1     as lbl
"""

# ──────────────────────────────────────────────────────────────────────
# One-line delegate mappings:  local name → delegate expression template
# The template uses {ARGS} as a placeholder for the original arg list.
# ──────────────────────────────────────────────────────────────────────
# fmt: off
DELEGATES: dict[str, str] = {
    # ----- skipp_math -----
    "f_clamp01":           "m.clamp01({ARGS})",
    "f_clamp":             "m.clamp({ARGS})",
    "f_epsClamp":          "m.eps_clamp({ARGS})",
    "f_logit":             "m.logit({ARGS})",
    "f_sigmoid":           "m.sigmoid({ARGS})",
    "f_platt_prob":        "m.platt_prob({ARGS})",
    "f_safe_log":          "m.safe_log({ARGS})",
    "f_pct_rank":          "m.pct_rank({ARGS})",
    "f_ci95_halfwidth":    "m.ci95_halfwidth({ARGS})",
    "f_brier":             "m.brier({ARGS})",
    "f_logloss":           "m.logloss({ARGS})",
    "f_safe_remove_float": "m.safe_remove_float({ARGS})",
    "f_safe_remove_int":   "m.safe_remove_int({ARGS})",
    "f_safe_remove_bool":  "m.safe_remove_bool({ARGS})",
    "f_safe_get_float":    "m.safe_get_float({ARGS})",
    "f_safe_get_int":      "m.safe_get_int({ARGS})",
    "f_safe_get_bool":     "m.safe_get_bool({ARGS})",
    "f_min_sec":           "m.min_sec({ARGS})",
    "f_soft":              "m.soft({ARGS})",
    "f_fail_open":         "m.fail_open({ARGS})",
    "f_score_add":         "m.score_add({ARGS})",
    "f_penalty":           "m.penalty({ARGS})",
    # ----- skipp_scoring -----
    "f_trend_strength":    "sc.trend_strength({ARGS})",
    "f_trend_regime":      "sc.trend_regime({ARGS})",
    "f_pullback_score":    "sc.pullback_score({ARGS})",
    "f_ensemble4":         "sc.ensemble4({ARGS})",
    "f_roc_score":         "sc.roc_score({ARGS})",
    "f_vol_score":         "sc.vol_score({ARGS})",
    "f_bias_from_score":   "sc.bias_from_score({ARGS})",
    "f_is_bull_bias":      "sc.is_bull_bias({ARGS})",
    "f_bin":               "sc.bin({ARGS})",
    "f_fill_cuts":         "sc.fill_cuts({ARGS})",
    "f_regime_bin":        "sc.regime_bin({ARGS})",
    "f_bucket":            "sc.bucket({ARGS})",
    # ----- skipp_indicators -----
    "f_zl_src":            "ind.zl_src({ARGS})",
    "f_zl_src_pct":        "ind.zl_src_pct({ARGS})",
    "f_zl_trend_core":     "ind.zl_trend_core({ARGS})",
    "f_log_regression_single": "ind.log_regression_single({ARGS})",
    "f_calc_reg_slope_osc":    "ind.calc_reg_slope_osc({ARGS})",
    # ----- skipp_calibration -----
    "f_update_accum_stats":"cal.update_accum_stats({ARGS})",
    "f_reset_sum1":        "cal.reset_sum1({ARGS})",
    "f_prob3":             "cal.prob3({ARGS})",
    "f_softmax3":          "cal.softmax3({ARGS})",
    "f_brier3":            "cal.brier3({ARGS})",
    "f_logloss3":          "cal.logloss3({ARGS})",
    "f_decay_counts":      "cal.decay_counts({ARGS})",
    "f_cal_update3":       "cal.cal_update3({ARGS})",
    "f_cal_roll_update":   "cal.cal_roll_update({ARGS})",
    # ----- skipp_labels -----
    "f_safe_label_text":   "lbl.safe_label_text({ARGS})",
}
# fmt: on

# Functions that need a global injected into the delegate call.
# Format: local name → (delegate_template, extra_args_appended)
# These are handled separately because the library function takes an extra
# param that the local wrapper supplies from a global.
DELEGATES_WITH_GLOBALS: dict[str, tuple[str, str]] = {
    "f_state_score":        ("sc.state_score({ARGS}, useSmoothTrend)", ""),
    "f_rel_label":          ("cal.rel_label({ARGS}, calMinSamples)", ""),
    "f_roll_add":           ("cal.roll_add({ARGS}, ROLL_RECALC_INTERVAL)", ""),
    "f_cal_roll_update3":   ("cal.cal_roll_update3({ARGS}, evalBuckets)", ""),
    "f_eval_stats_one":     ("cal.eval_stats_one({ARGS}, evalBuckets)", ""),
}

# Regex to match a function definition header line
# Captures: (func_name, arg_list)
FUNC_DEF_RE = re.compile(r'^(f_\w+)\(([^)]*)\)\s*=>\s*$')


def find_func_end(lines: list[str], start: int) -> int:
    """
    Given the line index of a function header (f_xxx(...) =>),
    find the last line of the function body.
    A function ends when we hit:
     - a blank line
     - a non-indented line (not starting with whitespace)
     - another function definition
     - end of file
    The header line itself is at `start`.
    """
    i = start + 1
    while i < len(lines):
        line = lines[i]
        stripped = line.rstrip('\n')
        # Blank line → function ended
        if stripped == '':
            return i - 1
        # Non-whitespace at col 0 → new declaration/code block
        if stripped and not stripped[0].isspace():
            return i - 1
        i += 1
    return len(lines) - 1


def slim_file(path: Path, dry_run: bool = False) -> tuple[int, int]:
    """Apply library delegation to a Pine file. Returns (old_lines, new_lines)."""
    text = path.read_text(encoding='utf-8')
    lines = text.split('\n')
    old_count = len(lines)

    # ── Step 1: Inject imports ──
    # Find the first `indicator(` or `strategy(` line.
    import_idx = None
    for i, line in enumerate(lines):
        if re.match(r'^(indicator|strategy)\(', line):
            import_idx = i + 1
            break
    if import_idx is None:
        print(f"  ⚠ No indicator()/strategy() found — skipping {path.name}")
        return old_count, old_count

    # Check if imports are already present
    if 'skipp_math' not in text:
        import_lines = IMPORT_BLOCK.rstrip('\n').split('\n')
        for j, imp_line in enumerate(import_lines):
            lines.insert(import_idx + j, imp_line)
        print(f"  ✓ Injected {len(import_lines)} import statements at line {import_idx + 1}")
    else:
        print(f"  ⓘ Imports already present — skipping injection")

    # ── Step 2: Replace function bodies ──
    replaced = 0
    skipped = []
    i = 0
    while i < len(lines):
        m_match = FUNC_DEF_RE.match(lines[i].rstrip('\n'))
        if m_match:
            func_name = m_match.group(1)
            args_str = m_match.group(2).strip()

            delegate = None
            if func_name in DELEGATES:
                delegate = DELEGATES[func_name].replace('{ARGS}', args_str)
            elif func_name in DELEGATES_WITH_GLOBALS:
                tmpl, _ = DELEGATES_WITH_GLOBALS[func_name]
                delegate = tmpl.replace('{ARGS}', args_str)

            if delegate is not None:
                body_end = find_func_end(lines, i)
                body_lines = body_end - i  # number of body lines (excluding header)
                if body_lines > 0:
                    # Replace: keep header but make it a one-liner
                    header = f"{func_name}({args_str}) => {delegate}"
                    lines[i] = header
                    del lines[i + 1: body_end + 1]
                    replaced += 1
                elif body_lines == 0:
                    # Already a one-liner — just update the delegate
                    header = f"{func_name}({args_str}) => {delegate}"
                    lines[i] = header
                    replaced += 1
                i += 1
                continue
            else:
                skipped.append(func_name)
        i += 1

    new_count = len(lines)
    saved = old_count - new_count

    if not dry_run:
        path.write_text('\n'.join(lines), encoding='utf-8')
        print(f"  ✓ Replaced {replaced} functions, saved {saved} lines ({old_count} → {new_count})")
    else:
        print(f"  [DRY RUN] Would replace {replaced} functions, save {saved} lines ({old_count} → {new_count})")

    if skipped:
        # Deduplicate
        seen = set()
        unique_skipped = []
        for s in skipped:
            if s not in seen:
                seen.add(s)
                unique_skipped.append(s)
        print(f"  ⓘ Kept inline ({len(unique_skipped)}): {', '.join(unique_skipped[:15])}{'…' if len(unique_skipped) > 15 else ''}")

    return old_count, new_count


def main():
    parser = argparse.ArgumentParser(description='Slim Pine Script files by delegating to libraries')
    parser.add_argument('files', nargs='+', help='Pine files to process')
    parser.add_argument('--dry-run', action='store_true', help='Show what would change without writing')
    args = parser.parse_args()

    total_saved = 0
    for f in args.files:
        p = Path(f)
        if not p.exists():
            print(f"  ✗ File not found: {f}")
            continue
        print(f"\n── {p.name} ──")
        old, new = slim_file(p, dry_run=args.dry_run)
        total_saved += old - new

    print(f"\n═══ Total savings: {total_saved} lines ═══")


if __name__ == '__main__':
    main()
