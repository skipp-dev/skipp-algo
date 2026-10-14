# A0-Fast rollout and rollback runbook

## Safety invariant

The existing FMP A0 path remains enabled and independent in every A0-Fast
mode. A stream, model, queue, reference, or configuration failure must never
disable it.

## Modes

- `off`: worker has no decision effect.
- `shadow`: collect parity, latency, gap, queue and recovery evidence only.
- `observe`: expose operator-only evidence; existing notification behavior is
  unchanged.
- `active`: requires the frozen evidence gates and the one-time deployment
  approval `RT_A0_FAST_DEPLOYMENT_APPROVED=1`.

Configure with `RT_A0_FAST_MODE` and `RT_A0_FAST_MAX_DATA_AGE_MS`. Invalid
configuration fails to `off`.

## Promotion checklist

1. At least 20 complete representative sessions, including Open Burst and a
   half day. This is the canonical minimum; older 10-session planning text is
   superseded.
2. Parity at least 99.9%, zero duplicate decisions, no unexplained fast-only
   or FMP-only cluster.
3. Reconnect, queue overflow, stale data and restart probes green.
4. FMP path verified independently while A0-Fast is stopped.
5. Monitoring reviewed and rollback rehearsed.
6. Separate explicit deployment approval obtained immediately before change.

## Immediate rollback

Set `RT_A0_FAST_MODE=off`, restart only the A0-Fast worker, and confirm FMP A0
continues. Preserve parity and recovery artifacts for review. Do not clear
state until the incident snapshot is captured.
