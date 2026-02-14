"""
Regression tests for Cooldown Hardening (Patch A + Option B + Enterprise Hardening).

Ensures:
1. cooldownTriggers input exists in both files with default "ExitsOnly".
2. Phase 1 stamps (Exit/Cover) are unconditional.
3. Phase 2 stamps (Buy/Short) are strictly guarded by `if cooldownTriggers == "AllSignals"`.
"""
import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
INDICATOR_PATH = ROOT / "SkippALGO.pine"
STRATEGY_PATH = ROOT / "SkippALGO_Strategy.pine"

class TestCooldownHardening(unittest.TestCase):
    
    @classmethod
    def setUpClass(cls):
        cls.indicator_text = INDICATOR_PATH.read_text(encoding="utf-8")
        cls.strategy_text = STRATEGY_PATH.read_text(encoding="utf-8")

    def _assert_contains(self, text, pattern, msg):
        match = re.search(pattern, text, re.MULTILINE | re.DOTALL)
        self.assertTrue(match, msg)

    def test_input_defaults(self):
        """Verify cooldownTriggers input exists and defaults to ExitsOnly."""
        pattern = r'cooldownTriggers\s*=\s*input\.string\("ExitsOnly",\s*"Cooldown triggers",\s*options=\["ExitsOnly",\s*"AllSignals"\]\)'
        
        self._assert_contains(self.indicator_text, pattern, "Indicator: cooldownTriggers input missing or incorrect default")
        self._assert_contains(self.strategy_text, pattern, "Strategy: cooldownTriggers input missing or incorrect default")

    def test_phase1_unconditional_stamps(self):
        """Verify Phase 1 (Exit/Cover) updates cooldown unconditionally."""
        # Pattern looks for: if exitSignal ... lastSignalTime := time (without guard)
        # We check specific snippets to ensure no `if cooldownTriggers` block wraps it.
        
        # This is slightly tricky with regex due to indentation, so we check existence of the assignment line
        # inside the block. A robust way is to ensure the line `lastSignalTime := time` appears 
        # indented but NOT inside a nested `if cooldownTriggers` block in Phase 1.
        
        # Simplified Check: Just ensure the lines exist and are NOT preceded by the guard in the immediate vicinity.
        # But since we know the exact code structure, we can verify the specific lines for Exit/Cover.
        
        exit_pattern = r'if\s+exitSignal\s+and\s+pos\s*==\s*1.*?(?<!if cooldownTriggers == "AllSignals")\s+lastSignalTime\s*:=\s*time'
        cover_pattern = r'else\s+if\s+coverSignal\s+and\s+pos\s*==\s*-1.*?(?<!if cooldownTriggers == "AllSignals")\s+lastSignalTime\s*:=\s*time'
        
        # Note: The lookbehind assertion (?<!) might be tricky across lines in Python re.
        # Instead, let's verify that the guard string is NOT present in the Phase 1 block.
        
        for name, text in [("Indicator", self.indicator_text), ("Strategy", self.strategy_text)]:
            # Extract Phase 1 block (Exit part)
            phase1_match = re.search(r'// --- Phase 1: Process exits ---(.*?)// --- Phase 2:', text, re.DOTALL)
            self.assertTrue(phase1_match, f"{name}: Could not find Phase 1 block")
            phase1_code = phase1_match.group(1)
            
            # Verify stamps exist
            self.assertIn('lastSignalTime := time', phase1_code, f"{name}: Phase 1 missing timestamp update")
            
            # Verify guard is NOT present in Phase 1
            self.assertNotIn('if cooldownTriggers == "AllSignals"', phase1_code, f"{name}: Phase 1 Exit/Cover incorrectly guarded")

    def test_phase2_guarded_stamps(self):
        """Verify Phase 2 (Entries) updates are correctly guarded."""
        
        # We need to check both BUY and SHORT blocks.
        
        for name, text in [("Indicator", self.indicator_text), ("Strategy", self.strategy_text)]:
            # Extract Phase 2 block
            phase2_match = re.search(r'// --- Phase 2: Process entries.*?(buyEvent\s*=|alertFreq\s*=)', text, re.DOTALL)
            self.assertTrue(phase2_match, f"{name}: Could not find Phase 2 block")
            phase2_code = phase2_match.group(0)
            
            # Split into Buy and Short sections roughly
            buy_section = re.search(r'if buySignal.*?(else if shortSignal|$)', phase2_code, re.DOTALL).group(0)
            short_section = re.search(r'else if shortSignal.*', phase2_code, re.DOTALL).group(0)
            
            # Helper to check guard is present
            guard_pattern = r'if\s+cooldownTriggers\s*==\s*"AllSignals"\s*\n\s*lastSignalBar\s*:=\s*bar_index\s*\n\s*lastSignalTime\s*:=\s*time'
            
            # Assert guard exists in BUY branch
            self.assertTrue(re.search(guard_pattern, buy_section, re.MULTILINE), f"{name}: BUY entry missing 'AllSignals' guard")
            
            # Assert guard exists in SHORT branch
            self.assertTrue(re.search(guard_pattern, short_section, re.MULTILINE), f"{name}: SHORT entry missing 'AllSignals' guard")

    def test_no_legacy_comments(self):
        """Ensure legacy commented-out assignments are removed to prevent confusion."""
        legacy_pattern = r'//\s*lastSignalTime\s*:=\s*time'
        
        for name, text in [("Indicator", self.indicator_text), ("Strategy", self.strategy_text)]:
            # We must be careful not to match comments explaining the new logic, but specifically
            # the old pattern of commented-out code.
            # The new code has: // Option B: Cooldown update removed so entries don't block...
            # But the actual assignment lines inside should be active (guarded).
            
            # Use a strict check for the exact commented-out assignment line pattern
            # indentation + // + assignment
            match = re.search(r'^\s*//\s*lastSignalBar\s*:=\s*bar_index', text, re.MULTILINE)
            self.assertFalse(match, f"{name}: Found legacy commented-out logic (lastSignalBar). Cleanup required.")

            match = re.search(r'^\s*//\s*lastSignalTime\s*:=\s*time', text, re.MULTILINE)
            self.assertFalse(match, f"{name}: Found legacy commented-out logic (lastSignalTime). Cleanup required.")

if __name__ == '__main__':
    unittest.main()
