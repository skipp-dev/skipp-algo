# TradingView second-writer coverage — design

**Date:** 2026-08-02
**Operator decision this supersedes:** 2026-08-01 rejected Dispatch-Ack (A),
post-run notification (B) and TV session probe (D), building only the
post-mutation re-verify (C, #4318). On 2026-08-02 the operator lifted that
rejection for the work below: both halves are in scope, and D returns as a
time-boxed feasibility spike whose negative result is an acceptable outcome.

## Problem

The operator's browser is the normal production writer on the TradingView
account; automation is the guest. TradingView autosaves from that browser. The
repository states the gap plainly in `.github/workflows/tv-save-consumer-source.yml`:

> No mechanism detects or excludes that session; mutating runs coordinate with
> the operator by convention, not by code.

Measured coverage as of 2026-08-02:

| Direction | Covered by | Latency |
|---|---|---|
| Autosave writes back stale state *after* a mutating CI run | `tv-post-mutation-verify.yml` (#4318) | ~15 min |
| Operator writes with **no** CI run that day | `tv-save-consumer-source` cron `17 5 * * *` | up to ~24 h |
| CI starts mutating **while** an operator tab is open | nothing | undetected |
| Operator opens a tab **during** a mutating run | `tv-post-mutation-verify.yml` | ~15 min |

`concurrency: tradingview-session` serialises seven CI workflows against each
other. It does not serialise the account. Nothing anywhere in
`automation/tradingview/` reads a layout modification timestamp.

No damage from this gap has been measured. The one incident with real cost —
run 30700389375, 67 minutes of broken layout — was a CI failure, not an
autosave. This design therefore buys detection and one cheap exclusion, not a
rewrite.

## Scope

Four components, in dependency order. Each is independently useful; none
depends on the spike.

1. **Evening verify** — halve the no-CI-run detection latency.
2. **A1, out-of-band drift fingerprint** — prove, before mutating, whether
   someone wrote since the last CI run.
3. **A2, operator window** — let the operator exclude CI by code, with expiry.
4. **A3 spike** — decide whether a session probe is feasible at all.

### Non-goals

* Preventing an autosave that lands *during* a mutating run. `#4318` remains
  the only cover for that direction, and this design does not improve it.
* Serialising the TradingView account itself. A2 excludes CI when the operator
  declares a window; it cannot detect an undeclared one.
* Any change to what a mutating run writes. Detection reports; it does not
  narrow the write set.

## Component 1 — evening verify

Add a second schedule entry to `.github/workflows/tv-save-consumer-source.yml`:

```yaml
schedule:
  - cron: "17 5 * * *"
  - cron: "17 21 * * *"
```

Read-only is structural, not conventional: the rollout step derives
`TV_VERIFY_ONLY` from `github.event_name == 'schedule' && 'true'` and
`TV_CONSUMER_MAPPING_JSON` from the same condition, so a schedule entry cannot
mutate regardless of which cron fired it. 21:17Z is after the US close and so
honours the file's `# live-window: off-hours-only` declaration.

Worst-case latency for operator drift on a day with no other run falls from
~24 h to ~12 h. Cost: one additional read-only run per day (~3–9 min).

**Blocking detail:** `tests/test_workflow_tv_save_consumer_source_contract.py`
pins the schedule by exact equality —
`assert on_block["schedule"] == [{"cron": "17 5 * * *"}]` — inside a test named
`test_schedule_is_daily_and_invokes_explicit_verify_only_mode`. Both the
assertion and the name must change in the same commit, or the change lands red.

## Component 2 — A1, out-of-band drift fingerprint

### Baseline source

Every run already publishes its observation to a stable branch: the "Publish
latest binding snapshot" step force-pushes
`artifacts/monitoring/latest/tradingview_consumer_bindings.json` to
`bot/live-tradingview-bindings`. That file is the baseline; no new persistence
is needed.

### Mechanism

A mutating run reads the bindings of every `verifyTarget` **before** its first
mutation and compares them against the baseline. Before the first mutation, any
difference is by construction not this run's doing — that is the proof nobody
currently produces.

The comparison key is, per verify target, the map
`label -> selections[].actual` (the actual bound parent study IDs). Source
hashes stay out of it: `sources.drifted` already covers them on every run.

### Verdict states

| State | Condition | Report |
|---|---|---|
| `clean` | every target's actual selections equal the baseline's | `ok` unaffected |
| `drifted` | any target differs | `ok=false`, red closing step |
| `unknown` | baseline missing, unparsable, or **incomplete** | `ok=false`, red closing step |

`unknown` on an incomplete baseline is load-bearing. The publish step runs under
`if: always()`, so a run that died before its verification pass publishes a
snapshot with fewer checked consumers than expected — comparing a full
observation against that would report drift that never happened. A baseline
whose `bindings` array does not cover every current verify target is `unknown`,
never `drifted`.

### Policy on a finding: report, do not withhold

A detected drift makes the run red; it does not stop the save. This repeats the
operator's 2026-08-01 reasoning for `savedWithoutAttestation` verbatim:
withholding freezes the consumers on an old pinned library while the producer
moves on, trading a bookkeeping divergence for a live one.

### Plumbing

The comparison runs inside the browser session, so it belongs in
`scripts/tv_batch_consumer_rollout.ts`. The baseline reaches it as a file: a
workflow step ahead of the rollout fetches it with `gh api` (the checkout uses
`persist-credentials: false`, so `git fetch` is not available) and writes it to
`artifacts/monitoring/previous/tradingview_consumer_bindings.json`. A missing
file is not an error at fetch time — it is the `unknown` verdict, decided by the
script.

The report gains one field, `outOfBandDrift`, carrying the verdict, the reason,
and the differing targets.

**Cost:** one extra binding-verification pass per mutating run, ~170 s against a
run that today takes 170–540 s.

## Component 3 — A2, operator window

Repository variable `TV_OPERATOR_ACTIVE` holds an ISO-8601 timestamp with an
explicit offset: the instant until which the operator claims the account.

```bash
gh variable set TV_OPERATOR_ACTIVE --body "2026-08-02T22:00:00Z"
```

A new `scripts/check_tv_operator_window.py` runs as the first step after
checkout — before the Node and Playwright installs, so a refusal costs seconds
rather than minutes.

**Which workflows are gated: `tv-save-consumer-source` only.** Seven workflows
share the `tradingview-session` group, but only this one writes the operator's
traded layout and its bindings, which is the surface the finding is about. The
library publishers (`smc-library-refresh`,
`pine-library-publish-handlibs`, `smc-overlay-library-publish`,
`openprep-pine-panel-publish`) write script sources, not layouts — and the one
of them that does reach a layout, `smc-library-refresh`, reaches it by chaining
into `tv-save-consumer-source`, where the gate already stands. Extending the
gate to the remaining workflows is a separate decision with its own evidence,
deliberately not smuggled into this one.

| Value | Behaviour |
|---|---|
| unset or empty | exit 0, no output |
| timestamp in the past | exit 0, notice naming the expiry |
| timestamp in the future | exit 1, error naming the expiry and the remaining minutes |
| unparsable, or lacking an explicit UTC offset | exit 1, error naming the exact command to clear it |

The expiry is the whole point: a forgotten window blocks nothing past its own
timestamp. Unparsable fails closed because the value only ever changes by
deliberate operator action — but the error text carries
`gh variable delete TV_OPERATOR_ACTIVE` so the escape is one command.

Read-only runs are never gated. They write nothing, and gating them would let an
open window suppress exactly the verification that Component 1 adds. The step's
condition is:

```yaml
if: ${{ github.event_name != 'schedule' && github.event.inputs.verify_only != 'true' }}
```

which classifies the three trigger paths the same way the rollout step's
`TV_VERIFY_ONLY` expression does: schedule is read-only, a dispatch with
`verify_only=true` is read-only, and everything else — including the
`workflow_run` refresh chain — mutates.

Precedent for repository variables in this repo: `vars.SMC_GH_HOSTED_RUNNER`.

## Component 4 — A3, session-probe spike

Time-boxed investigation of whether an authenticated TradingView session can
observe other active sessions on the same account, and whether CI's own session
would be distinguishable from the operator's.

The deliverable is a written finding under `docs/`, explicitly including a
negative one. No probe code lands unless the finding shows the surface exists
and is stable. This is the component whose feasibility is unverified; it is
sequenced last so that a negative result costs nothing already built.

## Testing

Every component is testable without a TradingView account.

* **Component 1** — the amended contract test asserts both cron entries and
  re-asserts that the schedule path forces `--verify-only`.
* **Component 2** — unit tests over the comparison function with fixture
  snapshots: identical, differing, missing, and incomplete baselines. The
  incomplete-baseline case pins `unknown` rather than `drifted`.
* **Component 3** — unit tests over the window script for all four value
  classes, driven by an injected clock rather than wall time. A workflow
  contract test pins the step's position ahead of the Node setup and its
  read-only exemption.
* **Component 4** — none; the deliverable is prose.

Workflow edits in this repo are only partially covered by the fast-gates
selection, so every task that touches a `.github/workflows/` file runs
`pytest tests/ -k workflow` in full before commit.

## Risks

* **A2 blocks the library-refresh chain.** If a refresh chain fires inside an
  open window, the consumers stay on the old library until the window expires
  and someone re-dispatches. Accepted: the window is operator-declared and
  short by construction.
* **A1 false positives.** Any legitimate out-of-band change — the operator
  deliberately fixing a binding by hand — reports as drift. That is the
  intended reading: the run says "someone else wrote", not "something broke".
* **Evening cron cost.** One more run per day against an Actions budget that
  has been exhausted before. ~3–9 min/day.
