# TradingView second-writer coverage — design

**Date:** 2026-08-02
**Operator decision this supersedes:** 2026-08-01 rejected Dispatch-Ack (A),
post-run notification (B) and TV session probe (D), building only the
post-mutation re-verify (C, #4318). On 2026-08-02 the operator lifted that
rejection for both halves of the coverage gap below.

**Amendment, 2026-08-02 (same day, before implementation):** the session probe
(D) is struck again, this time deliberately. It was scoped here as a
feasibility spike, but the spike cannot be delegated: TradingView auth is only
reachable through a Chrome profile copy plus CDP export on the operator's own
machine, and running a probe session against the account is itself an instance
of the second-writer risk this design exists to reduce. The 2026-08-01
rejection of D therefore stands — now as a recorded choice rather than an
unexamined one. A1 and A2 cover the exclusion half without it.

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

Three components are built, in dependency order; each is independently useful.
The fourth is recorded here as a decision not to build it.

1. **Evening verify** — halve the no-CI-run detection latency.
2. **A1, out-of-band drift fingerprint** — prove, before mutating, whether
   someone wrote since the last CI run.
3. **A2, operator window** — let the operator exclude CI by code, with expiry.
4. ~~**A3 spike** — decide whether a session probe is feasible at all.~~
   Struck 2026-08-02; see Component 4.

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
~24 h to **16 h**, not the 12 h an earlier draft of this document claimed: crons
at 05:17Z and 21:17Z split the day into a 16 h gap and an 8 h one, so the worst
case is the longer of the two — a 33 % reduction, not a halving. Cost: one
additional read-only run per day (~3–9 min).

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
`label -> selections[].actual`. Source hashes stay out of it: `sources.drifted`
already covers them on every run.

**What that key actually is, corrected 2026-08-03 after review.** This document
first called it "the actual bound parent study IDs". It is not. `readSelectedSource`
returns the rendered text of the settings dialog's `button[role=combobox]` — a
label, not an id. `tv_batch_consumer_rollout.ts` states the consequence in its own
comment: *"A matching dropdown label does not prove a live parent: TradingView
keeps the text while the stored input.source parent study id is dead."*

So the detector's reach is narrower than the sentence above implied. It sees a
binding repointed to a *differently named* source, and it sees one that
disappeared. It does NOT see the case where the operator re-applies the Suite and
every consumer's binding goes dead while the dropdown text stays identical — that
reads as `clean`. That case is the one `unknownParentRuntimeError` exists for, and
it remains the signal to watch; this design does not replace it.

Comparing real parent study ids would be strictly better and is not done here,
because nothing in the automation reads them today. Recorded as a known bound,
not as a gap someone forgot.

### Verdict states

| State | Condition | Report on a mutating run | Report on a read-only run |
|---|---|---|---|
| `clean` | every target's actual selections equal the baseline's | `ok` unaffected | `ok` unaffected |
| `drifted` | any target differs | `ok=false`, red closing step | recorded only |
| `unknown` | baseline missing, unparsable, **incomplete**, or **ambiguous** | `ok=false`, red closing step | recorded only |

`unknown` on an incomplete baseline is load-bearing. The publish step runs after
any run whose rollout step executed, so a run that died mid-verification
publishes a snapshot with fewer checked consumers than expected — comparing a
full observation against that would report drift that never happened. A baseline
whose `bindings` array does not cover every current verify target is `unknown`,
never `drifted`. Review added a fourth trigger for `unknown`: an *ambiguous*
reading — a duplicated `scriptName` or `label` on either side, or an empty list
of verify targets. Duplicates previously collapsed through a `Map` and produced a
false `clean` over a real drift; an empty target list previously returned `clean`
while comparing nothing.

**Read-only runs compare too, and never gate on the result** (decided
2026-08-03, after review). They cannot be the second writer, so gating them on
the verdict would only produce red runs with nothing to attribute. But they were
also *publishing* their observation as the next baseline while never comparing —
so the 05:17Z cron absorbed an operator's overnight write hours before the
mutating chain (normally ~09-13Z) ever looked at it, and the comparison then
reported `clean` over it. A read-only run therefore now compares its own
verification reading against the baseline and records the verdict, without
touching `report.ok`. That is what makes the evening cron of Component 1 worth
having: it now *sees* the drift it used to bury.

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

**Which workflows are gated: `tv-save-consumer-source` and
`smc-r4-context-readback`.** An earlier draft of this document said "the first
one only", on the reasoning that no other workflow writes a layout. That was
wrong, and the whole-branch review caught it: `smc-r4-context-readback` invokes
the *same* rollout script in mutating mode, with its own config and its own
output path. Left ungated it would have failed on every mutating run — and
worse, its `Run TradingView preflight` step, the separate-process proof that the
layout save persisted, had no condition and would have been skipped by exactly
the failure it exists to survive. That is the shape of run 30700389375.

So R4 is gated too, and it gets **its own baseline**: the published snapshot
covers the consumer-rollout targets, not the R4 context surface, so sharing one
would have meant a permanent `unknown`. R4 publishes and fetches
`artifacts/monitoring/latest/tradingview_r4_context_bindings.json` on the same
`bot/live-tradingview-bindings` branch. Its first run finds no baseline, reports
`unknown` and goes red — an honest bootstrap, matching the ADR-0031 precedent
for a gate that starts red rather than pretending.

Two producers now write to that one branch, which is a shape this repository has
been bitten by before (two producers owning one output left a gate permanently
blind). Both publish steps therefore seed the branch tip before staging, so
neither deletes the other's file. That was verified by round-tripping both
publish blocks against a throwaway repo, not by reading them.

The library publishers (`smc-library-refresh`, `pine-library-publish-handlibs`,
`smc-overlay-library-publish`, `openprep-pine-panel-publish`) write script
sources, not layouts — and the one that does reach a layout,
`smc-library-refresh`, reaches it by chaining into `tv-save-consumer-source`,
where the gate stands. `smc-release-gates` drives `tv_preflight.ts` in readonly
mode. Extending the gate to those is a separate decision with its own evidence.

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

## Component 4 — A3, session probe: NOT BUILT

Struck on 2026-08-02 before implementation. The idea was to ask TradingView
which sessions are active on the account and refuse to mutate when one of them
is not CI's own.

Two reasons it does not happen here. The investigation needs an authenticated
session that only exists on the operator's machine — TradingView auth is
reachable solely through a Chrome profile copy plus CDP export, so no CI job and
no delegated agent can run it. And the probe would open a browser session
against the account purely to ask who else is on it, which is the very
second-writer pressure this design reduces.

What that leaves uncovered is stated plainly: an operator session that is never
declared through `TV_OPERATOR_ACTIVE` remains invisible to CI. A1 still catches
what such a session *wrote*, on the next mutating run or the next scheduled
verify. Nothing catches it while it is merely open.

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
* **Component 4** — not built; nothing to test.

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
* **A1 reports drift after every BUS-contract change, and this one is
  predictable.** The observed label set is derived from the repo's current
  `.pine` sources, while the baseline carries the labels of the previous commit.
  A removed or renamed BUS binding label therefore compares as `was → null` and
  the first mutating run after that PR goes red, naming targets and attributing
  them to a second writer that does not exist. It self-clears on the next run.
  The refresh chain that moved 60 → 62 channels (#4263) is exactly the kind of
  change that triggers it. Written down here so the first red after a contract
  change is diagnosable rather than alarming — a detector whose own docstring
  warns that false drift "trains the operator to ignore the signal" should not
  keep its most predictable false positive undocumented.
* **Evening cron cost.** One more run per day against an Actions budget that
  has been exhausted before. ~3–9 min/day.
