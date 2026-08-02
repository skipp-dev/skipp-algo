# TradingView Layout Inventory

Single place answering "what is this layout for, and may I touch it?" — the
operator asked exactly that on 2026-08-02 after the validation phases had
accumulated seven layouts with no written map. Every mapping below was
verified against repo references on that date (`git grep` over chart URLs and
layout names); the referencing files are listed so the next audit can re-check
instead of trusting this table.

Two-surface drift warning: this file describes account state that lives on
TradingView, not in git. When a layout is added, renamed, retired, or gains a
pipeline role, update this file in the same PR that changes the referencing
config — the July registry lesson ("single source of truth" that contradicted
the module it described) applies here verbatim.

## Inventory (verified 2026-08-02)

| Layout | Chart URL | Role | Touch policy |
|---|---|---|---|
| ⭐ SMC Suite (BKNG, 5m) | `vWgAWyfC` | **PRODUCTION.** The operator's traded chart: `SMC Long-Dip Suite` producer plus the seven consumers (Decision Board, Strategy, Alerts, Setup Check, Breakout Overlay, Confluence Hub, Mobile). `primaryChartUrl` of `automation/tradingview/config/consumer-rollout.json`. | Never delete. Mutations only via the rollout workflows or deliberate operator action. |
| SMC Simple Management R1 (BKNG, 5m) | `hKHTmKhu` | R1 live-rollout evidence (2026-07-29 rollout, 2026-08-01 re-attestation, rollback drill, operator observation) — **and an active verify target**: `SMC Event Overlay` of the production rollout lives here. | Active. Not an archive candidate despite the "R1" name. |
| SMC Context R4 Shadow (AAPL, 5m) | `Jb2Vp6xs` | R4 shadow surface: `SMC Context Bus` → `SMC Context Overlay`, 62/62 bound and layout-saved on 2026-08-02 (run 30733442671). Target of `.github/workflows/smc-r4-context-readback.yml`. | Keep while the R4 shadow is observed. |
| SMC HTF Context R5 Validation (AAPL, 5m) | `FT4bpvrU` | R5/HTF evidence surface (session rebuild, live no-repaint, session-MSS — artifacts of 2026-07-31). R5 is `complete`, HTF `deployed`; the layout is reused whenever the phase needs fresh dated evidence. | Keep as re-validation surface. |
| SMC Hold R2.4 Validation (BKNG, 1D) | `twh98JLB` | R2.4 evidence and the reference surface of the **active** Hold-Manager shadow (since 2026-07-28). | Keep until the shadow observation window closes. |
| SMC Context Engine R3 Validation (AAPL, 5m) | — | R3 replay evidence of 2026-07-29. Referenced only by committed artifacts, fixtures and docs — no active config or workflow. | Archive candidate. Prefer renaming (`zz-Archiv …`) over deleting: the R1 re-attestation showed phase layouts get reused for later dated evidence. |
| SMC Exit Signal R1 Validation (AAPL, 5m) | — | Exit-signal validation evidence of 2026-07-29. Same status as R3: evidence only, no active config. | Archive candidate, same guidance. |

## Which layout is user-facing?

Exactly one: **⭐ SMC Suite**. It is the layout a customer chart mirrors —
`docs/tradingview-onboarding/PREPARE_CHART.md` describes that setup, and the
onboarding package binds the seven consumers against the suite on the
customer's own chart. Every other layout is an internal validation, evidence,
or shadow surface no customer ever sees.

## Foreign indicators on evidence layouts

"How to consolidate multiple alerts into one" (multiple instances on
`Jb2Vp6xs` as of 2026-08-02) is a public TradingView community script with
**zero references anywhere in this repo** — no script, config, or workflow
knows it. Nothing in the pipeline needs it; it can be removed at any time
(Object Tree → right-click → Remove), followed by a layout save. The R4
bindings live in the Bus/Overlay instances and are unaffected.

General rule: an indicator that appears on a pipeline layout but has no repo
reference is operator exploration residue. Removing it is safe; leaving it
costs nothing but confusion. When in doubt, `git grep` the script name first
— that check is what produced the verdict above.

## Chart URLs that are NOT layouts

`chart/AAA`, `chart/BBB`, `chart/abc` appear in tests as fixture URLs only.
