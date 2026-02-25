"""Smoke test for all new modules and wiring."""
from open_prep.signal_decay import adaptive_half_life, adaptive_freshness_decay, signal_strength_decay
from open_prep.realtime_signals import RealtimeEngine, RealtimeSignal
from open_prep.scorer import filter_candidate, rank_candidates_v2
from open_prep.technical_analysis import detect_breakout, detect_consolidation, detect_symbol_regime
from open_prep.regime import classify_symbol_regime, apply_symbol_regime_adjustments

# Test signal_decay
assert adaptive_half_life(0.5) == 1200.0, "Low ATR should give max HL"
assert adaptive_half_life(5.0) == 180.0, "High ATR should give min HL"
hl2 = adaptive_half_life(2.5)
assert 180.0 < hl2 < 1200.0, f"Mid ATR should be between: {hl2}"
assert adaptive_freshness_decay(0) == 1.0, "Zero elapsed should be 1.0"
assert adaptive_freshness_decay(None) == 0.5, "None should be 0.5 (neutral)"
s = signal_strength_decay(0.8, 300, atr_pct=3.0)
assert 0 < s < 0.8, f"Decayed strength should be less: {s}"

# Test instrument class fallback
assert adaptive_half_life(None, "penny") == 240.0
assert adaptive_half_life(None, "large_cap") == 900.0

# Test RealtimeSignal dataclass
sig = RealtimeSignal(
    symbol="TEST", level="A0", direction="LONG", pattern="test",
    price=100.0, prev_close=95.0, change_pct=5.26, volume_ratio=4.0,
    score=0.85, confidence_tier="HIGH_CONVICTION", atr_pct=2.5,
    freshness=1.0, fired_at="2024-01-01T00:00:00Z", fired_epoch=1704067200.0,
)
d = sig.to_dict()
assert d["symbol"] == "TEST"
assert d["level"] == "A0"

# Test detect_consolidation
cons = detect_consolidation(bb_width_pct=5.0, adx=15.0)
assert cons["is_consolidating"] is True
assert cons["score"] > 0

cons2 = detect_consolidation(bb_width_pct=15.0, adx=30.0)
assert cons2["is_consolidating"] is False

# Test detect_symbol_regime
assert detect_symbol_regime(30.0, 6.0) == "TRENDING"
assert detect_symbol_regime(15.0, 1.5) == "RANGING"
assert detect_symbol_regime(22.0, 3.0) == "NEUTRAL"

# Load signals from disk (should return a valid structure)
data = RealtimeEngine.load_signals_from_disk()
assert isinstance(data.get("signal_count"), int), "signal_count must be int"

print("All smoke tests passed")
