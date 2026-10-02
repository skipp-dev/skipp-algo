# offset_grid_frozen/ — a few hours on bars shifted by one minute

What `promotion-gate-daily` wrote on 2026-10-02 between the change of the
return rule (#5624) and the correction of the intraday bar grid: the 15m
window verdicts of that day and both trade ledgers (1D: 168 rows, 15m: 2 132).

**Rule:** `next_open_then_horizon_close` — the current one.

**Bar grid:** `offset_one_minute`. Until the correction the resampler read the
start-stamped 1m bars as end-stamped: the minute stamped 13:30 went into the
bar ENDING at 13:30. Every intraday bar was shifted by one minute against the
exchange clock, and the opening minute of the regular session sat in the last
pre-market bar. Measured on 15m: the same detection rules on exchange-aligned
bars reproduce 58–84 % of these events on the same bar. Decision: ADR-0031,
Nachtrag 2026-10-02 III.

**Why the 1D ledger is here too.** Daily bars are taken over unchanged; the
1D trades are not affected by the grid. But a ledger row names its bar grid
since the correction, the producer refuses a ledger that holds rows without
it, and ledger lines are never rewritten. The 1D ledger therefore restarts;
its trades are recorded again from the same events.

**What it is not.** Not part of the record that runs next door. None of these
rows counted towards a cumulative verdict: every one is anchored before the
evidence start (2026-10-05). Nothing appends here and no workflow reads here.
