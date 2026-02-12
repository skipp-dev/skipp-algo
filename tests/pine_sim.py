"""
Pine Script Behavioral Simulator for SkippALGO.

Transpiles the core control-flow logic from SkippALGO.pine into Python
so that we can run scenario-based behavioral tests without TradingView.

Scope:
  - Entry guard (allowEntry / allowRescue / allowRevBypass)
  - Signal engine (revBuyGlobal, engine-specific gateBuy, conflict resolution)
  - State machine (pos transitions, barsSinceEntry, exitGraceBars)
  - Exit logic (structHit, canStructExit, canChochExit, risk exits)

Out of scope (tested separately via regex):
  - Forecast calibration, Platt scaling, Brier scoring
  - Label rendering, table rendering
  - Alert dispatch
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Bar:
    """OHLCV bar data fed into the simulator."""
    open: float = 100.0
    high: float = 101.0
    low: float = 99.0
    close: float = 100.5
    volume: float = 1000.0


@dataclass
class SimConfig:
    """Input settings mirroring Pine Script inputs."""
    # Engine
    engine: str = "Hybrid"
    enable_shorts: bool = True
    allow_neural_reversals: bool = True
    use_liq_sweep: bool = False  # simplified: default off

    # Cooldown
    cooldown_bars: int = 5
    abstain_override_conf: float = 0.85

    # Exit
    exit_grace_bars: int = 5
    exit_conf_choch: float = 0.0  # no ChoCH filter by default
    exit_conf_tp: float = 1.0  # never hold winner by default (requires conf >= 1.0)

    # Risk
    use_atr_risk: bool = False  # simplified: off
    stop_atr: float = 2.0
    tp_atr: float = 3.0
    use_infinite_tp: bool = False

    # Forecast gates (simplified)
    reliability_ok: bool = True
    evidence_ok: bool = True
    eval_ok: bool = True
    abstain_gate: bool = False
    use_3way: bool = False

    # Session / close filter
    in_session: bool = True
    block_near_close: bool = False

    # Macro / drawdown
    macro_gate_long: bool = True
    macro_gate_short: bool = True
    dd_ok: bool = True

    # MTF
    mtf_ok_long: bool = True
    mtf_ok_short: bool = True

    # Confidence
    confidence: float = 0.70
    min_trust: float = 0.50

    # Volume
    vol_ok: bool = True

    # Enhancement gates (simplified: all pass)
    enh_long_ok: bool = True
    enh_short_ok: bool = True

    # Forecast gate
    fc_gate_long_safe: bool = True
    fc_gate_short_safe: bool = True

    # SET / pullback / hybrid triggers (simplified)
    set_ok_long: bool = True
    set_ok_short: bool = True
    pullback_long_ok: bool = True
    pullback_short_ok: bool = True
    hybrid_long_trigger: bool = False
    hybrid_short_trigger: bool = False

    # Breakout triggers
    breakout_long: bool = False
    breakout_short: bool = False
    trend_up: bool = True
    trend_dn: bool = False

    # Trend+Pullback triggers
    trend_flip_up: bool = False
    trend_flip_down: bool = False
    reclaim_up: bool = False
    reclaim_down: bool = False

    # Loose triggers
    cross_close_ema_f_up: bool = False
    cross_close_ema_f_down: bool = False

    # ChoCH filter
    choch_min_prob: float = 0.50
    choch_req_vol: bool = False

    # Prob values (forecast model output, simplified)
    p_u: float = 0.60  # prob up
    p_d: float = 0.30  # prob down

    # Strict alert mode simulation
    use_strict_alert_mode: bool = False
    in_rev_open_window: bool = False
    strict_mtf_long_ok: bool = True
    strict_mtf_short_ok: bool = True
    strict_choch_long_ok: bool = True
    strict_choch_short_ok: bool = True


@dataclass
class SimState:
    """Mutable state of the simulator (persists across bars)."""
    pos: int = 0  # 0=flat, 1=long, -1=short
    last_signal_bar: Optional[int] = None
    entry_price: Optional[float] = None
    entry_atr: Optional[float] = None
    stop_px: Optional[float] = None
    tp_px: Optional[float] = None
    trail_px: Optional[float] = None
    bars_since_entry: int = 0
    bar_index: int = 0
    struct_state: int = 0  # 0=neutral, 1=bullish, -1=bearish
    last_exit_reason: str = ""
    prev_buy_event: bool = False
    prev_short_event: bool = False


@dataclass
class BarSignals:
    """Per-bar signal inputs (what happened on this bar)."""
    is_choch_long: bool = False
    is_choch_short: bool = False
    is_bos_long: bool = False
    is_bos_short: bool = False
    break_long: bool = False  # bearish EMA break (exit trigger for longs)
    break_short: bool = False  # bullish EMA break (exit trigger for shorts)
    is_impulse: bool = False
    # Risk exit overrides
    risk_hit: bool = False
    risk_msg: str = ""
    stale_exit: bool = False


@dataclass
class BarResult:
    """Output of processing one bar."""
    buy_signal: bool = False
    short_signal: bool = False
    exit_signal: bool = False
    cover_signal: bool = False
    did_buy: bool = False
    did_short: bool = False
    did_exit: bool = False
    did_cover: bool = False
    pos_before: int = 0
    pos_after: int = 0
    # Diagnostics
    allow_entry: bool = False
    allow_rescue: bool = False
    allow_rev_bypass: bool = False
    entry_block_reached: bool = False
    rev_buy_global: bool = False
    rev_short_global: bool = False
    raw_buy_signal: bool = False
    raw_short_signal: bool = False
    exit_reason: str = ""
    strict_alerts_enabled: bool = False
    buy_event_strict: bool = False
    short_event_strict: bool = False
    alert_buy_cond: bool = False
    alert_short_cond: bool = False
    alert_exit_cond: bool = False
    alert_cover_cond: bool = False


class SkippAlgoSim:
    """
    Behavioral simulator for SkippALGO's core control flow.

    Mirrors the Pine Script logic in Python for testing:
      - Entry guard (allowEntry / allowRescue / allowRevBypass)
      - Signal engine per engine type
      - State machine (pos transitions)
      - Exit logic (struct exits, grace periods)
    """

    def __init__(self, config: Optional[SimConfig] = None):
        self.cfg = config or SimConfig()
        self.state = SimState()

    def reset(self):
        """Reset state to initial conditions."""
        self.state = SimState()

    def _cooldown_ok(self) -> bool:
        if self.state.last_signal_bar is None:
            return True
        return (self.state.bar_index - self.state.last_signal_bar) > self.cfg.cooldown_bars

    def _conf_ok(self) -> bool:
        return self.cfg.confidence >= self.cfg.min_trust

    def _gate_long_now(self) -> bool:
        return (self._conf_ok()
                and self.cfg.mtf_ok_long
                and self.cfg.macro_gate_long
                and self.cfg.dd_ok)

    def _gate_short_now(self) -> bool:
        return (self._conf_ok()
                and self.cfg.mtf_ok_short
                and self.cfg.macro_gate_short
                and self.cfg.dd_ok)

    def process_bar(self, bar: Bar, signals: BarSignals) -> BarResult:
        """Process a single confirmed bar. Returns the result."""
        result = BarResult()
        result.pos_before = self.state.pos
        cfg = self.cfg
        st = self.state

        # -- Update bar counting --
        prev_pos = st.pos
        # (bars_since_entry updated AFTER state transitions, see below)

        # -- Compute allowEntry --
        cooldown_ok_safe = self._cooldown_ok()
        allow_entry = (
            cooldown_ok_safe
            and not cfg.block_near_close
            and cfg.reliability_ok
            and cfg.evidence_ok
            and cfg.eval_ok
            and (not cfg.abstain_gate or True)  # simplified: decisionFinal always true
            and cfg.in_session
        )
        result.allow_entry = allow_entry

        # -- Compute allowRescue --
        allow_rescue_long = (signals.is_impulse and bar.close > bar.open
                             and cooldown_ok_safe)
        allow_rescue_short = (signals.is_impulse and bar.close < bar.open
                              and cooldown_ok_safe)
        allow_rescue = allow_rescue_long or allow_rescue_short
        result.allow_rescue = allow_rescue

        # -- Compute allowRevBypass --
        allow_rev_bypass = (cfg.allow_neural_reversals
                            and cooldown_ok_safe
                            and (signals.is_choch_long or signals.is_choch_short))
        result.allow_rev_bypass = allow_rev_bypass

        # -- Signal flags --
        buy_signal = False
        short_signal = False
        exit_signal = False
        cover_signal = False

        # -- Entry evaluation block --
        if st.pos == 0 and (allow_entry or allow_rescue or allow_rev_bypass):
            result.entry_block_reached = True

            # SMC filter (simplified: useLiqSweep defaults off)
            smc_ok_l = True
            smc_ok_s = True

            # Reversal logic (global)
            prob_ok_global = cfg.p_u >= 0.50
            prob_ok_global_s = cfg.p_d >= 0.50

            rev_buy_global = (cfg.allow_neural_reversals
                              and cfg.macro_gate_long
                              and cfg.dd_ok
                              and signals.is_choch_long
                              and prob_ok_global
                              and cfg.vol_ok
                              and smc_ok_l)

            rev_short_global = (cfg.allow_neural_reversals
                                and cfg.macro_gate_short
                                and cfg.dd_ok
                                and signals.is_choch_short
                                and prob_ok_global_s
                                and cfg.vol_ok
                                and smc_ok_s)

            result.rev_buy_global = rev_buy_global
            result.rev_short_global = rev_short_global

            gate_long = self._gate_long_now()
            gate_short = self._gate_short_now()

            if cfg.engine == "Hybrid":
                gate_buy = (gate_long and cfg.fc_gate_long_safe and cfg.vol_ok
                            and cfg.set_ok_long and cfg.pullback_long_ok
                            and cfg.enh_long_ok and cfg.hybrid_long_trigger)

                # ChoCH filter
                is_choch_entry = gate_buy and (st.struct_state == -1 or signals.is_choch_long)
                choch_filter_ok = (not is_choch_entry) or (
                    (cfg.p_u >= cfg.choch_min_prob) and (not cfg.choch_req_vol or cfg.vol_ok))

                buy_signal = (gate_buy and choch_filter_ok)

                gate_short_sig = (cfg.enable_shorts and gate_short and cfg.fc_gate_short_safe
                                  and cfg.vol_ok and cfg.set_ok_short and cfg.pullback_short_ok
                                  and cfg.enh_short_ok and cfg.hybrid_short_trigger)
                is_choch_short_entry = gate_short_sig and (st.struct_state == 1 or signals.is_choch_short)
                choch_short_filter_ok = (not is_choch_short_entry) or (
                    (cfg.p_d >= cfg.choch_min_prob) and (not cfg.choch_req_vol or cfg.vol_ok))

                short_signal = (gate_short_sig and choch_short_filter_ok)

            elif cfg.engine == "Breakout":
                base_buy = (gate_long and cfg.fc_gate_long_safe and cfg.vol_ok
                            and cfg.trend_up and cfg.enh_long_ok and cfg.breakout_long)
                is_choch_entry = base_buy and (st.struct_state == -1 or signals.is_choch_long)
                choch_filter_ok = (not is_choch_entry) or (
                    (cfg.p_u >= cfg.choch_min_prob) and (not cfg.choch_req_vol or cfg.vol_ok))
                buy_signal = (base_buy and choch_filter_ok)

                base_short = (cfg.enable_shorts and gate_short and cfg.fc_gate_short_safe
                              and cfg.vol_ok and cfg.trend_dn and cfg.enh_short_ok
                              and cfg.breakout_short)
                is_choch_short_entry = base_short and (st.struct_state == 1 or signals.is_choch_short)
                choch_short_filter_ok = (not is_choch_short_entry) or (
                    (cfg.p_d >= cfg.choch_min_prob) and (not cfg.choch_req_vol or cfg.vol_ok))
                short_signal = (base_short and choch_short_filter_ok)

            elif cfg.engine == "Trend+Pullback":
                buy_signal = (gate_long and cfg.enh_long_ok
                              and (cfg.trend_flip_up or cfg.reclaim_up))
                short_signal = (cfg.enable_shorts and gate_short and cfg.enh_short_ok
                                and (cfg.trend_flip_down or cfg.reclaim_down))

            else:  # Loose
                buy_signal = (gate_long and cfg.cross_close_ema_f_up and cfg.enh_long_ok)
                short_signal = (cfg.enable_shorts and gate_short
                                and cfg.cross_close_ema_f_down and cfg.enh_short_ok)

            # Unified Neural Reversal injection (all engines, including Loose)
            buy_signal = buy_signal or rev_buy_global
            short_signal = short_signal or rev_short_global

            # Conflict resolution
            result.raw_buy_signal = buy_signal
            result.raw_short_signal = short_signal
            if buy_signal and short_signal:
                buy_signal = False
                short_signal = False

        # -- Exit evaluation --
        can_struct_exit = st.bars_since_entry >= cfg.exit_grace_bars
        can_choch_exit = st.bars_since_entry >= min(2, cfg.exit_grace_bars)

        if st.pos == 1:
            # Long exit
            r_hit = signals.risk_hit
            r_msg = signals.risk_msg

            # TP filtering
            if r_hit and r_msg == "TP" and cfg.confidence >= cfg.exit_conf_tp:
                r_hit = False

            struct_hit = ((signals.break_long and can_struct_exit)
                          or (signals.is_choch_short and can_choch_exit))

            # ChoCH filtering
            if struct_hit and cfg.p_d < cfg.exit_conf_choch:
                struct_hit = False

            exit_signal = r_hit or struct_hit or signals.stale_exit
            if exit_signal:
                reason = r_msg if r_hit else ("Stalemate" if signals.stale_exit else "ChoCH")
                result.exit_reason = reason

        elif st.pos == -1:
            # Short cover
            r_hit = signals.risk_hit
            r_msg = signals.risk_msg

            if r_hit and r_msg == "TP" and cfg.confidence >= cfg.exit_conf_tp:
                r_hit = False

            struct_hit = ((signals.break_short and can_struct_exit)
                          or (signals.is_choch_long and can_choch_exit))

            cover_signal = r_hit or struct_hit or signals.stale_exit
            if cover_signal:
                reason = r_msg if r_hit else ("Stalemate" if signals.stale_exit else "ChoCH")
                result.exit_reason = reason

        result.buy_signal = buy_signal
        result.short_signal = short_signal
        result.exit_signal = exit_signal
        result.cover_signal = cover_signal

        # -- State transitions (barstate.isconfirmed) --
        # Priority: EXIT > COVER > BUY > SHORT (matches Pine if/else-if chain)
        if exit_signal and st.pos == 1:
            result.did_exit = True
            st.last_exit_reason = result.exit_reason
            st.pos = 0
            st.entry_price = None
            st.stop_px = None
            st.tp_px = None
            st.trail_px = None
            st.last_signal_bar = st.bar_index
        elif cover_signal and st.pos == -1:
            result.did_cover = True
            st.last_exit_reason = result.exit_reason
            st.pos = 0
            st.entry_price = None
            st.stop_px = None
            st.tp_px = None
            st.trail_px = None
            st.last_signal_bar = st.bar_index
        elif buy_signal and st.pos == 0:
            result.did_buy = True
            st.pos = 1
            st.entry_price = bar.close
            st.entry_atr = 1.0  # simplified
            st.last_signal_bar = st.bar_index
        elif short_signal and st.pos == 0:
            result.did_short = True
            st.pos = -1
            st.entry_price = bar.close
            st.entry_atr = 1.0
            st.last_signal_bar = st.bar_index

        result.pos_after = st.pos

        # -- Strict alert-mode conditions (event-layer simulation) --
        strict_alerts_enabled = cfg.use_strict_alert_mode and (not cfg.in_rev_open_window)
        buy_event_strict = (st.prev_buy_event
                    and cfg.strict_mtf_long_ok
                    and cfg.strict_choch_long_ok)
        short_event_strict = (st.prev_short_event
                      and cfg.strict_mtf_short_ok
                      and cfg.strict_choch_short_ok)

        result.strict_alerts_enabled = strict_alerts_enabled
        result.buy_event_strict = buy_event_strict
        result.short_event_strict = short_event_strict
        result.alert_buy_cond = buy_event_strict if strict_alerts_enabled else result.did_buy
        result.alert_short_cond = short_event_strict if strict_alerts_enabled else result.did_short
        result.alert_exit_cond = result.did_exit
        result.alert_cover_cond = result.did_cover

        # Prepare previous-event memory for next bar strict-delay checks
        st.prev_buy_event = result.did_buy
        st.prev_short_event = result.did_short

        # -- Update bar counting (AFTER state transitions, for NEXT bar) --
        # On entry bar: pos changed from 0 to ±1, so next bar barsSinceEntry = 1
        if st.pos != prev_pos and st.pos != 0:
            st.bars_since_entry = 0
        elif st.pos != 0:
            st.bars_since_entry += 1
        else:
            st.bars_since_entry = 0

        # -- Advance bar index --
        st.bar_index += 1

        return result

    def run_scenario(self, bars: list[Bar], signals_per_bar: list[BarSignals]) -> list[BarResult]:
        """Run a multi-bar scenario. Returns list of results."""
        assert len(bars) == len(signals_per_bar), "bars and signals must have same length"
        results = []
        for bar, sigs in zip(bars, signals_per_bar):
            results.append(self.process_bar(bar, sigs))
        return results
