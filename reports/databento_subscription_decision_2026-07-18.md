# Databento subscription decision — preliminary

Decision date target: 2026-07-30 (preliminary), 2026-07-31 (user decision)
Renewal date: 2026-08-01

## US Equities Standard — provisional `keep`

- Base cost: USD 199/month.
- Active engineering roles: `EQUS.MINI` for broad live/intraday parity and
  `EQUS.SUMMARY` for canonical EOD data.
- Technical status: role policy, fail-closed overrides, daily/intraday source
  separation, ARCA normalization and usage telemetry are implemented.
- Remaining evidence: current provider-portal usage, historical parity sample,
  and any additional exchange/distribution fees are still unknown.
- Recommendation: keep provisionally because it supplies the canonical broad
  live source and the newly wired daily source. Re-evaluate with the monthly
  usage snapshot before the decision date.

## OPRA Standard — `insufficient evidence`

- Base cost: USD 199/month.
- Technical status: the former near-live Historical poll is now explicitly
  research/backfill only. A central live Shadow sidecar, processed local
  snapshot, private ledger, telemetry and lazy UI consumer are implemented.
- Product impact: none; the service defaults to `off`, and Shadow emits no
  product alerts.
- Missing evidence: 7–10 complete US sessions, regular-hours uptime,
  reconnect exercise, latency distribution, definition coverage, gap rate,
  outcome labels and incremental lift/ablation confidence intervals.
- Recommendation today: do not convert missing evidence into a positive
  renewal case. Run the approved local Shadow window and use
  `scripts/evaluate_opra_shadow.py`; the final keep/cancel choice remains a
  user decision.

## GLBX.MDP3 and other research datasets — no subscription

Only a separately approved Historical PAYG experiment with a hypothesis, cost
ceiling, walk-forward design and ablation against the equity baseline is
permitted. No live upgrade is justified by the current repository evidence.

## Open commercial question

Data licensing and redistribution terms for any future consumer-facing product
remain an explicit external review item. This report makes no legal or
commercial conclusion.
