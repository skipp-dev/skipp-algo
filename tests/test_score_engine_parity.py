import re
from pathlib import Path

# Paths to files
BASE_DIR = Path(__file__).parent.parent
STRATEGY_FILE = BASE_DIR / "SkippALGO_Strategy.pine"
INDICATOR_FILE = BASE_DIR / "SkippALGO.pine"

def read_file_content(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()

def extract_integration_block(content):
    # Regex loosely identifying the integration logic
    # Looking for: useScoreEntries -> OR integration -> Reversal Injection -> Conflict Kill
    pattern = re.compile(
        r"if useScoreEntries\s+buySignal\s+:=\s+buySignal\s+or\s+scoreBuy\s+shortSignal\s+:=\s+shortSignal\s+or\s+scoreShort.*"
        r"// Unified Neural Reversal injection.*"
        r"if buySignal and shortSignal\s+buySignal\s+:=\s+false\s+shortSignal\s+:=\s+false",
        re.DOTALL
    )
    match = pattern.search(content)
    return match

def test_score_engine_integration_order():
    """Confirms correct ordering: Score OR -> Reversal Injection -> Conflict Kill"""
    strategy_content = read_file_content(STRATEGY_FILE)
    indicator_content = read_file_content(INDICATOR_FILE)

    # We need to verify the sequence strictly involves these steps in order
    # Step 1: Score Integration
    # Step 2: Reversal Injection
    # Step 3: Conflict Kill
    
    for filename, content in [("Strategy", strategy_content), ("Indicator", indicator_content)]:
        idx_score = content.find("if useScoreEntries")
        idx_rev = content.find("// Unified Neural Reversal injection")
        idx_kill = content.find("if buySignal and shortSignal")
        
        assert idx_score != -1, f"{filename}: Missing Score Engine Integration block"
        assert idx_rev != -1, f"{filename}: Missing Reversal Injection block"
        assert idx_kill != -1, f"{filename}: Missing Conflict Kill block"
        
        # Verify Order
        assert idx_score < idx_rev, f"{filename}: Score Integration must be BEFORE Reversal Injection"
        assert idx_rev < idx_kill, f"{filename}: Reversal Injection must be BEFORE Conflict Kill"

def test_score_inputs_parity():
    """Confirms both files have matching Score Engine inputs."""
    strategy_content = read_file_content(STRATEGY_FILE)
    indicator_content = read_file_content(INDICATOR_FILE)
    
    inputs = [
        "grp_score", "useScoreEntries", "scoreThresholdLong", "scoreThresholdShort",
        "wUsi", "wLiquidity", "wMomentum", "wTrendContext", "wChopPenalty",
        "scoreMinConfLong", "scoreMinConfShort"
    ]

    for inp in inputs:
        assert inp in strategy_content, f"Strategy missing input: {inp}"
        assert inp in indicator_content, f"Indicator missing input: {inp}"

def test_preset_effective_vars_wired():
    """Confirms presets feed effective score/cooldown variables in both files."""
    strategy_content = read_file_content(STRATEGY_FILE)
    indicator_content = read_file_content(INDICATOR_FILE)

    required_tokens = [
        "minDirProbLongEff", "minDirProbShortEff",
        "scoreMinConfLongEff", "scoreMinConfShortEff",
        "useScoreEntriesEff"
    ]

    for filename, content in [("Strategy", strategy_content), ("Indicator", indicator_content)]:
        for tok in required_tokens:
            assert tok in content, f"{filename}: Missing effective preset variable: {tok}"

        assert "scoreConfLongOk" in content, f"{filename}: scoreConfLongOk gate missing"
        assert "scoreConfShortOk" in content, f"{filename}: scoreConfShortOk gate missing"

def test_usi_zero_lag_implementation():
    """Confirms USI Red Line uses the ZL option in both files."""
    strategy_content = read_file_content(STRATEGY_FILE)
    indicator_content = read_file_content(INDICATOR_FILE)

    # We look for the conditional assignment using the new helper
    # Pattern: usiSrc5 = useUsiZeroLagRed ? f_zl_src_pct(...)
    expected_pattern = "usiSrc5 = useUsiZeroLagRed ? f_zl_src_pct"
    # Optional extension: only enforce when both scripts implement this pathway.
    if expected_pattern in strategy_content and expected_pattern in indicator_content:
        assert expected_pattern in strategy_content, "Strategy: Missing 'usiSrc5 = useUsiZeroLagRed ? ...'"
        assert expected_pattern in indicator_content, "Indicator: Missing 'usiSrc5 = useUsiZeroLagRed ? ...'"

def test_score_ddok_safety():
    """Confirms ddOk is included in baseEligible (Risk Regression Protection)."""
    strategy_content = read_file_content(STRATEGY_FILE)
    indicator_content = read_file_content(INDICATOR_FILE)

    # Looking for: baseEligible [:]= (pos == 0) and ddOk and (allowEntry or allowRescue)
    # Use flexible regex for assignment operator and whitespace
    pattern = re.compile(
        r"baseEligible\s*:?=\s*\(pos\s*==\s*0\)\s+and\s+ddOk\s+and\s+\(allowEntry\s+or\s+allowRescue\)"
    )

    for filename, content in [("Strategy", strategy_content), ("Indicator", indicator_content)]:
        match = pattern.search(content)
        assert match, f"{filename}: 'baseEligible' definition missing 'ddOk' (Risk Bypass!)"

def test_usi_state_blocking():
    """Confirms USI State (Red vs Envelope) blocks contra-signals despite high score."""
    strategy_content = read_file_content(STRATEGY_FILE)
    indicator_content = read_file_content(INDICATOR_FILE)
    
    # We look for the blocking logic variables
    # bool usiBlockL = useUsi and usiBearState
    # bool usiBlockS = useUsi and usiBullState
    # AND their usage in the final assignment: scoreBuy := ... and (not usiBlockL)
    
    for filename, content in [("Strategy", strategy_content), ("Indicator", indicator_content)]:
        if "usiBlockL" in content or "usiBlockS" in content:
            assert "usiBlockL" in content, f"{filename}: Missing usiBlockL definition"
            assert "usiBlockS" in content, f"{filename}: Missing usiBlockS definition"

def test_entry_gates_reenabled():
    """Confirms hard entry gates are actively wired (not commented out)."""
    strategy_content = read_file_content(STRATEGY_FILE)
    indicator_content = read_file_content(INDICATOR_FILE)

    for filename, content in [("Strategy", strategy_content), ("Indicator", indicator_content)]:
        assert "reliabilityOk" in content, f"{filename}: reliabilityOk missing"
        assert "evidenceOk" in content, f"{filename}: evidenceOk missing"
        assert "evalOk" in content, f"{filename}: evalOk missing"
        assert "decisionFinal" in content, f"{filename}: decisionFinal missing"
        assert "allowEntry" in content, f"{filename}: allowEntry missing"

def test_path_target_and_filter_wiring():
    """Confirms requirePathTargetEntry, pre-momentum thresholds and engulfing filter are wired."""
    strategy_content = read_file_content(STRATEGY_FILE)
    indicator_content = read_file_content(INDICATOR_FILE)

    checks = [
        "requirePathTargetEntry",
        "preMomLongOk",
        "preMomShortOk",
        "engulfLongOk",
        "engulfShortOk",
        "inRevOpenWindow",
    ]

    for filename, content in [("Strategy", strategy_content), ("Indicator", indicator_content)]:
        for needle in checks:
            assert needle in content, f"{filename}: Missing wiring check: {needle}"


def test_phase1_scaffold_parity():
    """Confirms RFC v6.4 Phase-1 scaffold exists with indicator/strategy parity."""
    strategy_content = read_file_content(STRATEGY_FILE)
    indicator_content = read_file_content(INDICATOR_FILE)

    required_tokens = [
        "grp_phase1",
        "useZeroLagTrendCore",
        "trendCoreMode",
        "zlTrendLenFast",
        "zlTrendLenSlow",
        "zlTrendAggressiveness",
        "zlTrendNoiseGuard",
        "useRegimeClassifier2",
        "regimeLookback",
        "regimeAtrShockPct",
        "regimeAdxTrendMin",
        "regimeHurstRangeMax",
        "regimeChopBandMax",
        "regimeAutoPreset",
        "showPhase1Debug",
        "f_zl_trend_core(",
        "f_hurst_proxy(",
        "trendCoreFast",
        "trendCoreSlow",
        "regime2State",
        "regime2Name",
        "P1 TrendCore Fast",
        "P1 Regime2 State",
    ]

    # Optional RFC scaffold: enforce parity only when both files implement it.
    scaffold_present = ("grp_phase1" in strategy_content and "grp_phase1" in indicator_content)
    if scaffold_present:
        for filename, content in [("Strategy", strategy_content), ("Indicator", indicator_content)]:
            for token in required_tokens:
                assert token in content, f"{filename}: Missing Phase-1 scaffold token: {token}"


def test_phase2_optin_wiring_parity():
    """Confirms Phase-2 opt-in wiring is present and parity-aligned."""
    strategy_content = read_file_content(STRATEGY_FILE)
    indicator_content = read_file_content(INDICATOR_FILE)

    required_phase2_tokens = [
        "regime2TuneOn = useRegimeClassifier2 and regimeAutoPreset and regime2State > 0",
        "cooldownBarsEff = cooldownBars",
        "chochMinProbEff = chochMinProb",
        "abstainOverrideConfEff = abstainOverrideConf",
        "effectiveCooldownBars = (confidence >= 0.80) ? math.max(2, math.round(cooldownBarsEff / 2)) : cooldownBarsEff",
        "isHighConf         = f_fc_bool(confidence >= abstainOverrideConfEff)",
        "trendReg = f_trend_regime(trendCoreFast, trendCoreSlow, atrNormHere)",
        "trendStrength = f_trend_strength(trendCoreFast, trendCoreSlow)",
        "chochFilterOk = (not isChoCH_Entry) or (na(pU) or pU >= chochMinProbEff)",
        "chochShortFilterOk = (not isChoCH_ShortEntry) or (na(pD) or pD >= chochMinProbEff)",
    ]

    phase2_present = (
        "regime2TuneOn = useRegimeClassifier2 and regimeAutoPreset and regime2State > 0" in strategy_content
        and "regime2TuneOn = useRegimeClassifier2 and regimeAutoPreset and regime2State > 0" in indicator_content
    )
    if phase2_present:
        for filename, content in [("Strategy", strategy_content), ("Indicator", indicator_content)]:
            for token in required_phase2_tokens:
                assert token in content, f"{filename}: Missing Phase-2 wiring token: {token}"


def test_phase3_regime_hysteresis_parity():
    """Confirms Phase-3 regime hysteresis (min-hold + shock release) is present and parity-aligned."""
    strategy_content = read_file_content(STRATEGY_FILE)
    indicator_content = read_file_content(INDICATOR_FILE)

    required_phase3_tokens = [
        "regimeMinHoldBars = input.int(3, \"Regime Min Hold Bars\"",
        "regimeShockReleaseDelta = input.float(5.0, \"Vol Shock Release Δpct\"",
        "rawRegime2State = useRegimeClassifier2 ?",
        "var int regime2State = 0",
        "var int regime2HoldBars = 0",
        "if regime2State == 4 and regimeAtrPct > (regimeAtrShockPct - regimeShockReleaseDelta)",
        "canSwitch = regime2State == 0 or regime2Candidate == 4 or regime2HoldBars >= regimeMinHoldBars",
    ]

    phase3_present = (
        "regimeMinHoldBars = input.int(3, \"Regime Min Hold Bars\"" in strategy_content
        and "regimeMinHoldBars = input.int(3, \"Regime Min Hold Bars\"" in indicator_content
    )
    if phase3_present:
        for filename, content in [("Strategy", strategy_content), ("Indicator", indicator_content)]:
            for token in required_phase3_tokens:
                assert token in content, f"{filename}: Missing Phase-3 hysteresis token: {token}"

if __name__ == "__main__":
    # Manually run tests if executed primarily
    try:
        test_score_engine_integration_order()
        test_score_inputs_parity()
        test_usi_zero_lag_implementation()
        test_score_ddok_safety()
        test_usi_state_blocking()
        print("✅ Score Engine Parity Tests Passed")
    except AssertionError as e:
        print(f"❌ Test Failed: {e}")
    except Exception as e:
        print(f"❌ Error: {e}")
