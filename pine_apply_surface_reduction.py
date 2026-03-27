#!/usr/bin/env python3
"""Apply input surface-area reduction to Pine scripts.

SMC++.pine  → add display = display.none to expert inputs (keeps ~25 core visible)
SkippALGO.pine → group all ungrouped inputs into logical sections
SkippALGO_Strategy.pine → same grouping for parity

Run:  python pine_apply_surface_reduction.py [--dry-run]
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

# ── SMC++ display.none reduction ──────────────────────────────────────
# These vars KEEP status-line visibility (core controls); all others get display.none
SMC_CORE_VARS = {
    # Execution Mode
    "signal_mode", "long_user_preset",
    # LTF
    "enable_ltf_sampling", "ltf_timeframe",
    # HTF Trend
    "show_mtf_trend", "mtf_trend_tf1", "mtf_trend_tf2", "mtf_trend_tf3",
    # Dashboard / Alerts
    "show_dashboard", "enable_dynamic_alerts",
    # Performance
    "performance_mode",
    # Risk
    "show_risk_levels", "target1_r", "target2_r",
    # Session toggles
    "use_vwap_filter", "use_trade_session_gate",
    # Micro / Market regime toggles
    "use_microstructure_profiles", "use_index_gate",
    # Long Dip main toggles
    "show_reclaim_markers", "show_long_confirmation_markers",
    # Module toggles
    "use_accel_module", "use_sd_confluence", "use_volatility_regime",
    "use_stretch_context", "use_ddvi_context",
    # Structure / OB / FVG toggles
    "show_Structure", "show_ob", "show_fvg", "show_htf_fvg", "show_eq",
    # Context quality toggle
    "use_context_quality_score",
}


def apply_smc_display_none(path: Path, dry_run: bool) -> int:
    """Add display = display.none to non-core SMC++ inputs."""
    from pine_input_surface import parse_inputs, _DISPLAY_RE

    text = path.read_text()
    lines = text.splitlines(keepends=True)
    inputs = parse_inputs([l.rstrip("\n") for l in lines])
    changes = 0

    for inp in inputs:
        if not inp.group:
            continue  # shouldn't happen for SMC++ but be safe
        if inp.has_display_none:
            continue  # already has it
        if inp.varname in SMC_CORE_VARS:
            continue  # keep visible
        # Check if it already has display.status_line — replace with display.none
        line_idx = inp.lineno - 1
        original = lines[line_idx]

        if _DISPLAY_RE.search(original):
            # Already has a display setting (e.g., display.status_line) — replace it
            modified = _DISPLAY_RE.sub("display = display.none", original)
        else:
            # No display setting — add display.none before closing paren
            stripped = original.rstrip("\n")
            idx = stripped.rfind(")")
            if idx == -1:
                continue
            modified = stripped[:idx] + ", display = display.none" + stripped[idx:] + "\n"

        if modified != original:
            lines[line_idx] = modified
            changes += 1
            if dry_run:
                print(f"  SMC++ L{inp.lineno}: {inp.varname} → display.none")

    if not dry_run and changes:
        path.write_text("".join(lines))
    return changes


# ── SkippALGO grouping ───────────────────────────────────────────────
# Classification map: varname → (group_name, display_none?)
# Only ungrouped vars are listed; already-grouped vars are left alone.

SKIPPALGO_GROUPS = {
    # ── Core ──
    "config":                   ("Core", False),
    "engine":                   ("Core", False),
    "allowNeuralReversals":     ("Core", False),
    "enableShorts":             ("Core", False),
    "enableForecast":           ("Core", False),

    # ── Entry Gates ──
    "useForecastGateEntry":     ("Entry Gates", False),
    "entryFcTF":                ("Entry Gates", False),
    "minEdgePP":                ("Entry Gates", True),
    "requireRelOk":             ("Entry Gates", True),
    "requirePathTargetEntry":   ("Entry Gates", True),
    "useChopAbstain":           ("Entry Gates", False),
    "flatAbstainThr":           ("Entry Gates", True),
    "requireSET":               ("Entry Gates", True),

    # ── Risk Management ──
    "useAtrRisk":               ("Risk Management", False),
    "stopATR":                  ("Risk Management", False),
    "tpATR":                    ("Risk Management", False),
    "useInfiniteTP":            ("Risk Management", False),
    "trailATR":                 ("Risk Management", False),
    "trailAfterR":              ("Risk Management", False),
    "dynSlPreset30m":           ("Risk Management", False),
    "tpPreset30m":              ("Risk Management", False),
    "useDynamicSlProfile":      ("Risk Management", True),
    "dynamicSlWidenUntilR":     ("Risk Management", True),
    "dynamicSlMaxWidenATR":     ("Risk Management", True),
    "dynamicSlTightenStartR":   ("Risk Management", True),
    "dynamicSlTightenATRPerR":  ("Risk Management", True),
    "dynamicSlMaxTightenATR":   ("Risk Management", True),
    "dynamicSlRequireTrend":    ("Risk Management", True),
    "dynamicSlRequireConf":     ("Risk Management", True),
    "dynamicSlMinConf":         ("Risk Management", True),
    "useDynamicTpExpansion":    ("Risk Management", True),
    "dynamicTpKickInR":         ("Risk Management", True),
    "dynamicTpAddATRPerR":      ("Risk Management", True),
    "dynamicTpMaxAddATR":       ("Risk Management", True),
    "dynamicTpRequireTrend":    ("Risk Management", True),
    "dynamicTpRequireConf":     ("Risk Management", True),
    "dynamicTpMinConf":         ("Risk Management", True),
    "useRiskDecay":             ("Risk Management", True),
    "decayStopATR":             ("Risk Management", True),
    "decayTpATR":               ("Risk Management", True),
    "decayBars":                ("Risk Management", True),

    # ── Pullback Detection ──
    "pbLookback":               ("Pullback Detection", True),
    "pbMinATR":                 ("Pullback Detection", True),
    "pbMaxATR":                 ("Pullback Detection", True),
    "useVolConfirm":            ("Pullback Detection", False),
    "volLen":                   ("Pullback Detection", True),
    "volMult":                  ("Pullback Detection", True),

    # ── Structure / Breakout ──
    "swingL":                   ("Structure / Breakout", False),
    "swingR":                   ("Structure / Breakout", False),
    "swingMaxAgeBars":          ("Structure / Breakout", True),
    "breakoutSource":           ("Structure / Breakout", False),
    "structureLogic":           ("Structure / Breakout", False),
    "chochScalpPreset":         ("Structure / Breakout", False),
    "chochScalpSaferPreset":    ("Structure / Breakout", False),
    "useStructureTags":         ("Structure / Breakout", False),
    "chochSignalMode":          ("Structure / Breakout", False),
    "showChochPing":            ("Structure / Breakout", True),
    "chochMinProb":             ("Structure / Breakout", True),
    "chochReqVol":              ("Structure / Breakout", True),

    # ── Cooldown ──
    "cooldownBars":             ("Cooldown", False),
    "cooldownMode":             ("Cooldown", True),
    "cooldownMinutes":          ("Cooldown", True),
    "cooldownTriggers":         ("Cooldown", True),
    "allowSameBarBuyAfterCover":("Cooldown", True),
    "allowSameBarShortAfterExit":("Cooldown", True),

    # ── MTF Confirmation ──
    "useMtfConfirm":            ("MTF Confirmation", False),
    "mtfSet":                   ("MTF Confirmation", False),
    "tfShort1":                 ("MTF Confirmation", True),
    "tfShort2":                 ("MTF Confirmation", True),
    "tfShort3":                 ("MTF Confirmation", True),
    "tfMedium1":                ("MTF Confirmation", True),
    "tfMedium2":                ("MTF Confirmation", True),
    "tfMedium3":                ("MTF Confirmation", True),
    "tfLong1":                  ("MTF Confirmation", True),
    "tfLong2":                  ("MTF Confirmation", True),
    "tfLong3":                  ("MTF Confirmation", True),

    # ── Forecast Horizons ──
    "tfF1":                     ("Forecast Horizons", True),
    "tfF2":                     ("Forecast Horizons", True),
    "tfF3":                     ("Forecast Horizons", True),
    "tfF4":                     ("Forecast Horizons", True),
    "tfF5":                     ("Forecast Horizons", True),
    "tfF6":                     ("Forecast Horizons", True),
    "tfF7":                     ("Forecast Horizons", True),

    # ── Trust & Guardrails ──
    "trustWAccuracy":           ("Trust & Guardrails", True),
    "trustWRegime":             ("Trust & Guardrails", True),
    "trustWGuardrail":          ("Trust & Guardrails", True),
    "trustWData":               ("Trust & Guardrails", True),
    "trustWMacro":              ("Trust & Guardrails", True),
    "penaltyGuardrail":         ("Trust & Guardrails", True),
    "penaltyRegimeHigh":        ("Trust & Guardrails", True),
    "penaltyRegimeMed":         ("Trust & Guardrails", True),
    "volRankMed":               ("Trust & Guardrails", True),
    "volRankHigh":              ("Trust & Guardrails", True),
    "gapShockPct":              ("Trust & Guardrails", True),
    "rangeShockPct":            ("Trust & Guardrails", True),

    # ── Macro & Drawdown ──
    "macroPctLen":              ("Macro & Drawdown", True),
    "macroPctLenIntraday":      ("Macro & Drawdown", True),
    "macroGateMode":            ("Macro & Drawdown", False),
    "macroLongPctThreshold":    ("Macro & Drawdown", True),
    "macroShortPctThreshold":   ("Macro & Drawdown", True),
    "ddLookback":               ("Macro & Drawdown", True),
    "ddMild":                   ("Macro & Drawdown", True),
    "ddSevere":                 ("Macro & Drawdown", True),
    "ddTrustPenalty":           ("Macro & Drawdown", True),
    "ddHardGate":               ("Macro & Drawdown", True),

    # ── Core Indicators ──
    "emaFastLen":               ("Core Indicators", False),
    "emaSlowLen":               ("Core Indicators", False),
    "atrLen":                   ("Core Indicators", True),
    "volRankLen":               ("Core Indicators", True),

    # ── RSI / Momentum ──
    "useAdaptiveRsi":           ("RSI / Momentum", True),
    "rsiLenFastTF":             ("RSI / Momentum", True),
    "rsiLenMidTF":              ("RSI / Momentum", True),
    "rsiLenSlowTF":             ("RSI / Momentum", True),
    "rsiLongOn":                ("RSI / Momentum", True),
    "rsiLongOff":               ("RSI / Momentum", True),
    "rsiShortOn":               ("RSI / Momentum", True),
    "rsiShortOff":              ("RSI / Momentum", True),
    "rsiStateLen":              ("RSI / Momentum", True),

    # ── CRSI ──
    "useCrsiFactor":            ("CRSI", True),
    "crsiRsiLen":               ("CRSI", True),
    "crsiStreakRsiLen":          ("CRSI", True),
    "crsiRankLen":              ("CRSI", True),
    "crsiLongGoodLo":           ("CRSI", True),
    "crsiLongGoodHi":           ("CRSI", True),
    "crsiLongGoodMult":         ("CRSI", True),
    "crsiLongOver":             ("CRSI", True),
    "crsiLongOverMult":         ("CRSI", True),
    "crsiLongPanic":            ("CRSI", True),
    "crsiLongPanicMult":        ("CRSI", True),
    "crsiShortGoodLo":          ("CRSI", True),
    "crsiShortGoodHi":          ("CRSI", True),
    "crsiShortGoodMult":        ("CRSI", True),
    "crsiShortExhaust":         ("CRSI", True),
    "crsiShortExhaustMult":     ("CRSI", True),
    "crsiShortOver":            ("CRSI", True),
    "crsiShortOverMult":        ("CRSI", True),

    # ── Zones ──
    "showZones":                ("Zones & Visuals", False),
    "zoneAnchor":               ("Zones & Visuals", False),
    "zoneMode":                 ("Zones & Visuals", True),
    "zoneNeutralMult":          ("Zones & Visuals", True),
    "zoneAggressiveMult1":      ("Zones & Visuals", True),
    "zoneAggressiveMult2":      ("Zones & Visuals", True),

    # ── Labels & Display ──
    "showLongLabels":           ("Labels & Display", False),
    "showShortLabels":          ("Labels & Display", False),
    "showPreEntryLabels":       ("Labels & Display", False),
    "preWarnDistATR":           ("Labels & Display", True),
    "preSetPulseOnly":          ("Labels & Display", True),
    "setPulseOnly":             ("Labels & Display", True),
    "labelPriceMode":           ("Labels & Display", True),
    "alertOnBarCloseOnly":      ("Labels & Display", False),

    # ── Strict Mode ──
    "strictMtfMargin":          ("Strict Mode", True),
    "strictChochConfirmBars":   ("Strict Mode", True),
    "useAdaptiveStrictMargin":  ("Strict Mode", True),
    "strictAdaptiveRange":      ("Strict Mode", True),
    "strictAdaptiveLen":        ("Strict Mode", True),

    # ── Session & Timing ──
    "useRthCloseFilter":        ("Session & Timing", False),
    "rthCloseHour":             ("Session & Timing", True),
    "rthCloseMinute":           ("Session & Timing", True),
    "avoidCloseMins":           ("Session & Timing", True),
    "useRevOpenWindow":         ("Session & Timing", False),
    "rthOpenHour":              ("Session & Timing", True),
    "rthOpenMinute":            ("Session & Timing", True),
    "revOpenWindowLongMins":    ("Session & Timing", True),
    "revOpenWindowShortMins":   ("Session & Timing", True),
    "revOpenWindowMode":        ("Session & Timing", True),
    "revOpenWindowEngine":      ("Session & Timing", True),

    # ── Forecast Calibration ──
    "allowForecastOnNonFixed":  ("Forecast Calibration", True),
    "fcDisplay":                ("Forecast Calibration", True),

    # ── Liquidity Concepts ──
    "useLiqSweep":              ("Liquidity Concepts", False),
    "liqSweepLookback":         ("Liquidity Concepts", True),

    # Not in target profile groups (already grouped) — skip
    # Target profiles (already grouped) — leave alone

    # ── Global Trade Policies ──
    "noHitPolicy":              ("Trade Policies", True),
    "pathTiePolicy":            ("Trade Policies", True),
    "atrTargetLen":             ("Trade Policies", True),
    "exitGraceBars":            ("Trade Policies", True),

    # ── Automation ──
    # Already grouped

    # ── Forecast Filtering ──
    "useRelFilter":             ("Forecast Filtering", True),
    "maxBrier":                 ("Forecast Filtering", True),
    "relFilterTF":              ("Forecast Filtering", True),
    "evidenceGate":             ("Forecast Filtering", True),
    "evidenceMinTotal":         ("Forecast Filtering", True),
    "abstainGate":              ("Forecast Filtering", True),
    "abstainMinEdge":           ("Forecast Filtering", True),
    "abstainOverrideConf":      ("Forecast Filtering", True),
    "tradeMinBinSamples":       ("Forecast Filtering", True),
    "tradeMinTotalSamples":     ("Forecast Filtering", True),
    "rescueVolMult":            ("Forecast Filtering", True),
    "rescueImpulseATR":         ("Forecast Filtering", True),
    "revMinProb":               ("Forecast Filtering", True),
    "revRecencyBars":           ("Forecast Filtering", True),

    # ── Calibration Dimensions ──
    "predBinsN":                ("Calibration Dimensions", True),
    "predBins1":                ("Calibration Dimensions", True),
    "useQuantileBins":          ("Calibration Dimensions", True),
    "quantileWindow":           ("Calibration Dimensions", True),
    "quantileUpdate":           ("Calibration Dimensions", True),
    "quantileMinSamples":       ("Calibration Dimensions", True),
    "calibrateInBackground":    ("Calibration Dimensions", True),
    "alphaN":                   ("Calibration Dimensions", True),
    "alpha1":                   ("Calibration Dimensions", True),
    "kShrink":                  ("Calibration Dimensions", True),
    "calMinSamples":            ("Calibration Dimensions", True),
    "predUpThr":                ("Calibration Dimensions", True),
    "predDnThr":                ("Calibration Dimensions", True),

    # ── ECE Recalibration ──
    "eceRecalBoost":            ("Calibration Dimensions", True),

    # ── Exit Rules ──
    "chochGraceBars":           ("Exit Rules", True),
    "useStrictEmaExit":         ("Exit Rules", True),
}


def _build_group_var_header(groups_used: set[str]) -> str:
    """Build the group variable declarations block."""
    # Ordered by appearance priority
    ordered = [
        "Core", "Entry Gates", "Risk Management", "Structure / Breakout",
        "Pullback Detection", "Cooldown", "MTF Confirmation", "Forecast Horizons",
        "Core Indicators", "RSI / Momentum", "CRSI", "Liquidity Concepts",
        "Zones & Visuals", "Labels & Display", "Session & Timing", "Strict Mode",
        "Macro & Drawdown", "Trust & Guardrails",
        "Forecast Calibration", "Forecast Filtering", "Calibration Dimensions",
        "Trade Policies", "Exit Rules",
    ]
    lines = ["// ── Input Groups ─────────────────────────────────────────\n"]
    for g in ordered:
        if g in groups_used:
            slug = re.sub(r"[^a-zA-Z0-9]+", "_", g).strip("_").lower()
            lines.append(f'var string g_{slug} = "{g}"\n')
    lines.append("\n")
    return "".join(lines)


def apply_skippalgo_grouping(path: Path, dry_run: bool) -> int:
    """Group ungrouped inputs in SkippALGO.pine."""
    from pine_input_surface import parse_inputs, _GROUP_RE, _DISPLAY_RE

    text = path.read_text()
    lines = text.splitlines(keepends=True)
    inputs = parse_inputs([l.rstrip("\n") for l in lines])

    changes = 0
    groups_used: set[str] = set()

    for inp in inputs:
        if inp.group:
            continue  # already grouped
        assignment = SKIPPALGO_GROUPS.get(inp.varname)
        if not assignment:
            continue

        group_name, add_dnone = assignment
        groups_used.add(group_name)
        slug = re.sub(r"[^a-zA-Z0-9]+", "_", group_name).strip("_").lower()
        gvar = f"g_{slug}"

        line_idx = inp.lineno - 1
        original = lines[line_idx]
        modified = original.rstrip("\n")

        # Add group
        idx = modified.rfind(")")
        if idx == -1:
            continue
        modified = modified[:idx] + f", group = {gvar}" + modified[idx:]

        # Add display.none if expert
        if add_dnone and not _DISPLAY_RE.search(modified):
            idx = modified.rfind(")")
            modified = modified[:idx] + ", display = display.none" + modified[idx:]

        modified += "\n"
        if modified != original:
            lines[line_idx] = modified
            changes += 1
            if dry_run:
                print(f"  L{inp.lineno}: {inp.varname} → group={group_name}" +
                      (" + display.none" if add_dnone else ""))

    # Insert group variable declarations
    if groups_used and changes > 0:
        header = _build_group_var_header(groups_used)
        # Find insertion point: first ungrouped input that we modified
        first_ungrouped = min(
            inp.lineno for inp in inputs
            if not inp.group and inp.varname in SKIPPALGO_GROUPS
        )
        # Check if there are existing group var declarations nearby
        insert_at = first_ungrouped - 1
        # Check lines above for comments/empty lines marking a section
        while insert_at > 0 and lines[insert_at - 1].strip() == "":
            insert_at -= 1

        # Check existing group var declarations already in the file
        existing_gvars = set()
        for line in lines:
            m = re.match(r'(?:var\s+string\s+)?(\w+)\s*=\s*"([^"]+)"', line.strip())
            if m and m.group(1).startswith("g_"):
                existing_gvars.add(m.group(2))
            m2 = re.match(r'(\w+)\s*=\s*"([^"]+)"', line.strip())
            if m2 and m2.group(1).startswith("grp_"):
                existing_gvars.add(m2.group(2))

        # Only declare group vars not already declared
        new_groups = groups_used - existing_gvars
        if new_groups:
            header_lines = _build_group_var_header(new_groups)
            for i, hl in enumerate(header_lines.splitlines(keepends=True)):
                lines.insert(insert_at + i, hl)

    if not dry_run and changes:
        path.write_text("".join(lines))
    return changes


# ── SkippALGO second pass: hide previously-grouped expert inputs ─────
# Groups whose inputs should ALL get display.none on status line
SKIPPALGO_EXPERT_GROUPS = {
    "grp_sigfilt", "grp_tri", "grp_score", "⚡", "grp_ens",
    "grp_vwt", "grp_fast", "grp_mid", "grp_slow", "grp_phase1",
    "Calibration", "grp_smc", "grp_exit", "grp_auto", "🔧",
    # Strategy-specific expert groups
    "Engine", "grp_cal", "grp_export", "Policy", "Signals", "Maintenance",
}

# Ungrouped evaluation inputs → group + display.none
SKIPPALGO_EVAL_VARS = {
    "resetWhich", "resetNow", "showEvalSection", "evalInBackground",
    "evalMode", "evalRollScore", "evalRollShort", "evalRollLong",
    "evalBuckets", "evalMinEvents", "driftWarnPP", "useEceGate",
    "eceMax", "useDriftGate", "driftMaxPP", "useEvalPenalty",
    "eceWarn", "evalPenalty", "useEceRecal",
    # Strategy-specific ungrouped
    "minDirProb", "useEngulfExit", "engulfExitMode", "engulfTightenMult",
    "showTable", "useAlertCalls", "useSessionFilter", "sessionWin",
}


def apply_skippalgo_expert_display_none(path: Path, dry_run: bool) -> int:
    """Add display.none to previously-grouped expert inputs in SkippALGO."""
    from pine_input_surface import parse_inputs, _DISPLAY_RE, _GROUP_RE

    text = path.read_text()
    lines = text.splitlines(keepends=True)
    inputs = parse_inputs([l.rstrip("\n") for l in lines])
    changes = 0

    # Check if g_forecast_eval group var exists; if not, we'll add it
    has_eval_gvar = any("g_forecast_eval" in l for l in lines)

    for inp in inputs:
        line_idx = inp.lineno - 1
        original = lines[line_idx]
        modified = original

        # Handle ungrouped evaluation vars
        if not inp.group and inp.varname in SKIPPALGO_EVAL_VARS:
            stripped = modified.rstrip("\n")
            idx = stripped.rfind(")")
            if idx == -1:
                continue
            stripped = stripped[:idx] + ", group = g_forecast_eval" + stripped[idx:]
            if not _DISPLAY_RE.search(stripped):
                idx = stripped.rfind(")")
                stripped = stripped[:idx] + ", display = display.none" + stripped[idx:]
            modified = stripped + "\n"

        # Handle previously-grouped expert inputs without display.none
        elif inp.group in SKIPPALGO_EXPERT_GROUPS and not inp.has_display_none:
            stripped = modified.rstrip("\n")
            if not _DISPLAY_RE.search(stripped):
                idx = stripped.rfind(")")
                if idx == -1:
                    continue
                stripped = stripped[:idx] + ", display = display.none" + stripped[idx:]
                modified = stripped + "\n"

        if modified != original:
            lines[line_idx] = modified
            changes += 1
            if dry_run:
                grp = inp.group or "Forecast Evaluation"
                print(f"  L{inp.lineno}: {inp.varname} [{grp}] → display.none")

    # Add g_forecast_eval group var if we used it and it doesn't exist
    if not has_eval_gvar and any(inp.varname in SKIPPALGO_EVAL_VARS and not inp.group for inp in inputs):
        # Find existing group var block and append
        last_gvar_line = 0
        for i, line in enumerate(lines):
            if re.match(r'^var\s+string\s+g_', line):
                last_gvar_line = i
        if last_gvar_line > 0:
            lines.insert(last_gvar_line + 1, 'var string g_forecast_eval = "Forecast Evaluation"\n')

    if not dry_run and changes:
        path.write_text("".join(lines))
    return changes


def main():
    dry_run = "--dry-run" in sys.argv
    base = Path(__file__).parent

    # 1. SMC++.pine — add display.none to expert inputs
    smc_path = base / "SMC++.pine"
    if smc_path.exists():
        n = apply_smc_display_none(smc_path, dry_run)
        print(f"{'[DRY RUN] ' if dry_run else ''}SMC++.pine: {n} inputs → display.none")
    else:
        print(f"SMC++.pine not found at {smc_path}")

    # 2. SkippALGO.pine — group ungrouped inputs + expert display.none
    for name in ["SkippALGO.pine", "SkippALGO_Strategy.pine"]:
        path = base / name
        if path.exists():
            n = apply_skippalgo_grouping(path, dry_run)
            print(f"{'[DRY RUN] ' if dry_run else ''}{name}: {n} inputs grouped")
            n2 = apply_skippalgo_expert_display_none(path, dry_run)
            print(f"{'[DRY RUN] ' if dry_run else ''}{name}: {n2} expert inputs → display.none")
        else:
            print(f"{name} not found")


if __name__ == "__main__":
    main()
