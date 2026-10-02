# variant_a_frozen/ — the record under the previous return rule

Everything `promotion-gate-daily` wrote to `docs/calibration/gates/` up to
2026-10-02: the dated 1D files (`returns_series`, `track_record_gate`,
`regime_stratified`, `epnl_after_cost`), the 15m window verdicts and both
trade ledgers with their cumulative verdicts.

**Rule:** Variant A, `touch_then_horizon_close` — entry at the zone midpoint
(OB, FVG) or at the event level (BOS, SWEEP).

**Why it is frozen.** That entry was not a price one could trade at once the
decision existed, and it carried the whole reported return: on 15m, +12.0 bps
per trade as reported against -6.5 bps when bought at the decision bar's
close. Measurement:
`docs/governance/variant_a_entry_price_measurement_2026-10-02.md`. Decision:
ADR-0031, Nachtrag 2026-10-02 II.

**What it is not.** It is not a track record, and it is not the first part of
the one that began on 2026-10-02 next door. Returns under the two rules are
different quantities; adding trade counts, pooling returns or continuing a
streak across the two is wrong. Nothing appends here, no workflow reads here,
and the ledger producer refuses a ledger that holds another rule's rows.

It is kept because the numbers were published and decisions referred to them.
