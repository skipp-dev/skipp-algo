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
        "wUsi", "wLiquidity", "wMomentum", "wTrendContext", "wChopPenalty"
    ]
    
    for inp in inputs:
        assert inp in strategy_content, f"Strategy missing input: {inp}"
        assert inp in indicator_content, f"Indicator missing input: {inp}"

if __name__ == "__main__":
    # Manually run tests if executed primarily
    try:
        test_score_engine_integration_order()
        test_score_inputs_parity()
        print("✅ Score Engine Parity Tests Passed")
    except AssertionError as e:
        print(f"❌ Test Failed: {e}")
    except Exception as e:
        print(f"❌ Error: {e}")
