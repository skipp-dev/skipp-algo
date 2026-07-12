# ADR-0026: Record the executed status of the tier-2 magnitude re-target and the closure of the OHLCV shadow-feature queue (records-only)

| Field    | Value                                                                            |
|----------|----------------------------------------------------------------------------------|
| Status   | Accepted — **records-only**; changes no gate, score, threshold, or test code. It reconciles the ADR index with decisions already *executed* by separate, reviewed PRs, so ADR-0019/0022/0023 stop reading as bare "Proposed" long after their outcomes shipped |
| Date     | 2026-07-12                                                                        |
| Deciders | skipp-dev (autonomous mandate; product owner + principal quant)                  |
| Related  | ADR-0019 (multi-feature family score v2 — OHLCV onramp), ADR-0022 (joint meta-label A/B executed), ADR-0023 (pre-registered tier-2 move-size re-target), ADR-0016 (order-flow aggressor data path — Williams VIX Fix candidate), [ADR-0023 live-rollout handover](../governance/adr0023_live_rollout_handover.md), [feature onramp saturation verdict](../governance/feature_onramp_saturation_verdict.md), [resolution feature-gap analysis](../governance/resolution_feature_gap_analysis.md) |

## Context

ADR-0019, ADR-0022, and ADR-0023 were each authored as `Proposed`/doc-only
pre-registrations. Their downstream decisions have since been *proven and
executed* by separate, reviewed PRs, but the append-only ADR bodies and the
index still present them as open proposals. Per the ADR discipline (`ADRs are
append-only — to revise a decision, add a new ADR that supersedes the old one
and update the table below`), the correct fix is this new ADR plus an index
status update — **not** an in-place rewrite of the earlier ADR bodies.

The concrete executed facts, each verified in-repo:

- **ADR-0023 (tier-2 move-size re-target) — proven and staged-live.** The §2
  acceptance bar was **RESOLVED on real data**; the additive
  `magnitude_resolution_floor` check is implemented
  (`governance/magnitude_resolution_gate.py`, wired through
  `governance/family_verdict.py` / `governance/promotion_gate.py`); Stage-1
  ledger verdicts feed the promotion gate daily; and **Stage 2 is ARMED for
  BOS/SWEEP** via `governance/magnitude_stage_policy.json` (fail-closed). No
  family is sized on the move-size objective yet (Stage 3 not started) and the
  direction-Brier tier-2 gate stays in force. Source of truth:
  [`adr0023_live_rollout_handover.md`](../governance/adr0023_live_rollout_handover.md).

- **ADR-0019 (OHLCV multi-feature onramp) — queue formally closed.** The
  [feature onramp saturation verdict](../governance/feature_onramp_saturation_verdict.md)
  (Queue closure, 2026-06-04) declares the OHLCV-pure candidate queue closed:
  Williams VIX Fix and Kyle's lambda remain in-tree **recorded-only**, Amihud
  illiquidity was cancelled before any code, and VPIN (the last microstructure
  candidate on this axis) stays recorded-only after a `no_lift` real-data run.
  Data-acquisition effort moved to the options-flow data path (ADR-0020).

- **ADR-0016 candidate `williams_vix_fix` — retired.** The ADR-0016 body lists
  it as "awaiting its real-data A/B verdict"; it has since been **retired**
  after `no_lift` across all four families
  ([resolution feature-gap analysis](../governance/resolution_feature_gap_analysis.md),
  which records the retirement, PR #2551). It stays in the tree recorded-only as
  a control.

## Decision

Record — without changing any code — that:

1. **ADR-0023 is executed (staged rollout).** Its pre-registered acceptance bar
   passed on real data; the `magnitude_resolution_floor` gate plumbing and the
   BOS/SWEEP arming policy are live in shadow. ADR-0023 moves from `Proposed`
   to **Accepted / Executed (Stage 1 live, Stage 2 armed)**.

2. **The ADR-0019 OHLCV shadow-feature queue is closed.** ADR-0019's onramp is
   **superseded** by the saturation verdict's formal queue closure; its
   recorded-only features remain as controls.

3. **`williams_vix_fix` is retired** (recorded-only control), superseding the
   ADR-0016 "awaiting A/B verdict" line.

This ADR introduces **no** new hypothesis and **no** new gate behavior; it is a
status-reconciliation record so the index reflects the real decision lifecycle.

## Alternatives considered

- **Edit the ADR-0019/0022/0023/0016 headers in place** to flip their status.
  Rejected — violates the append-only rule; the original pre-registrations must
  stay verbatim for provenance.
- **Leave the index stale and rely on the governance docs.** Rejected — the
  index is the first stop for reviewers; a bare "Proposed" months after rollout
  is exactly the misleading-canonical-status class this record removes.

## Consequences

- **Positive.** The ADR index now matches executed reality; the governance docs
  (`adr0023_live_rollout_handover.md`, `feature_onramp_saturation_verdict.md`,
  `resolution_feature_gap_analysis.md`) remain the operational source of truth
  and are cross-linked from one place.
- **Negative / neutral.** One more ADR to carry. No code, gate, or threshold
  changes; nothing to enforce at runtime.

## Evidence

- `governance/magnitude_resolution_gate.py`, `governance/family_verdict.py`,
  `governance/promotion_gate.py` — `magnitude_resolution_floor` implemented and
  wired.
- `governance/magnitude_stage_policy.json` — BOS/SWEEP armed (fail-closed).
- `docs/governance/adr0023_live_rollout_handover.md` — §2 RESOLVED; Stage-1
  daily feed; Stage-2 armed; Stage-3 not started.
- `docs/governance/feature_onramp_saturation_verdict.md` — OHLCV queue closure
  (2026-06-04).
- `docs/governance/resolution_feature_gap_analysis.md` — `williams_vix_fix`
  retired after `no_lift` ×4.
