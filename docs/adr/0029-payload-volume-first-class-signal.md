# ADR-0029: Payload volume is a first-class signal; publish gates compare field pairs

- **Status:** Proposed
- **Date:** 2026-07-22
- **Related:** ADR-0025 (Grafana publish surface), ADR-0027 (structure artifacts are runtime outputs)

## Context

Five consecutive versions of `smc_micro_profiles_generated` were published to
TradingView with an empty payload. The defect was found by looking at a chart.
No gate blocked it, no test failed, no alert fired.

The state is still reproducible on `origin/main` (`1c7d659a8`). The generated
manifest says:

```text
universe_size      = 6929
list_counts        = {clean_reclaim: 0, stop_hunt_prone: 0, midday_dead: 0,
                      rth_only: 0, weak_premarket: 0, weak_afterhours: 0, fast_decay: 0}
productivity_gate  = {publish_ready: true, blocking_reasons: []}
```

and the shipped library says:

```pine
export const int    UNIVERSE_SIZE    = 6929
export const string UNIVERSE_TICKERS = ""
```

Four independent blind spots produced that green result. Each was verified at
the implementation:

1. **The gate validates a number, not the list the consumers read.**
   `blocking_reasons` (`scripts/generate_smc_micro_profiles.py:1467-1473`) knows
   exactly three reasons — `fixture_input`, `default_event_risk`,
   `placeholder_symbols`. `list_counts` is *written* into the same manifest
   (line 1495) and never read back. The two quantities also have different
   origins: `universe_size` is `df["symbol"].nunique()` from the base scan
   (`scripts/smc_micro_generator.py:92`), while `UNIVERSE_TICKERS` is rendered
   from `enrichment.meta.scanned_symbols`
   (`scripts/generate_smc_micro_profiles.py:749-753`). When the enrichment
   sidecar drops out, the number survives and the list disappears.

2. **`static_control_plane` mode narrows the gate further.** In that mode —
   the mode the incident ran in, since the #3896 revert —
   `default_event_risk` is suppressed, leaving `fixture_input` as effectively
   the only reachable blocking reason.

3. **The publish contract verifier never leaves the filesystem.**
   `scripts/verify_smc_micro_publish_contract.py` checks path consistency, the
   import alias block, the deprecated-field policy and the `publish_ready`
   flag. It reads the manifest's claim about the library; it never checks the
   library against that claim.

4. **The live preflight discards `not_run` before combining.**
   `combineVerificationStatuses` (`automation/tradingview/lib/tv_validation_model.ts:439`)
   filters `not_run` out of the set, so `[true, not_run, not_run]` combines to
   `true` and `overall_preflight_ok` is `true`. Only an all-`not_run` set
   degrades. The existing test at `tv_validation_model.test.ts:309` pins this.

Underneath all four sits the reason the gap was *structural* rather than
merely missed: **nothing in the repo measures payload volume.** The library
monitoring added after the #3599/#3603 incident chain
(`live_overlay_pine_library_data_age_seconds`) reads `ASOF_DATE` from the
repo-owned source (`scripts/build_pine_library_version_snapshot.ts:22`). A
fresh date on an empty payload reads green. Every existing signal is metadata
*about* the payload; none is the payload.

## Decision

### 1. Payload volume becomes an explicit measured quantity

Two numbers, derived from the generated `.pine` — the artifact the consumers
actually read:

| Quantity | Source | Value on `1c7d659a8` |
| --- | --- | --- |
| `universe_tickers_count` | `UNIVERSE_TICKERS` | 0 |
| `list_total` | sum of the seven `*_TICKERS` membership lists | 0 |

They are defined once and consumed at three layers: the generator's
productivity gate, the publish contract verifier, and the Pine-library version
snapshot that feeds Prometheus.

### 2. Hard blockers are contradictions between field pairs, never bare emptiness

```text
empty_universe_tickers:  UNIVERSE_SIZE > 0          ∧  universe_tickers_count == 0
empty_membership_lists:  universe_tickers_count > 0  ∧  list_total == 0
```

Both say the same thing: *material was present and nothing arrived*. Neither
asks whether "empty" is legitimate, because a contradiction cannot be
legitimate — 6929 scanned symbols of which none reach the payload is not a
valid state under any configuration.

A payload that is empty *consistently* — no universe size, no tickers, no
lists — triggers neither reason, by design. Nothing contradicts anything
there, so the gate has no evidence of a defect. That shape is the
relative-collapse warning rule's job, not the gate's.

This form is the decision, not an implementation detail. The failure being
repaired is not "someone forgot an emptiness check" — it is that a field was
validated *in isolation*. A gate that compares field pairs closes the pattern,
not just this instance.

Both reasons apply in every generation mode. There is no mode-dependent
suppression, because the one mode that would have needed it is retired — see
the next section.

### 3. `static_control_plane` is retired from the publish path

**Operator decision, 2026-07-22: there will be no flip back to `--static-only`.**

The intermediate design suppressed the universe reason in
`static_control_plane`, on the grounds that #3896 leaves provider data to the
runtime sidecar in that mode, so an absent `UNIVERSE_TICKERS` is by
construction there. That suppression was the answer to "what if static
publishes again?". With the question withdrawn, the answer does not belong in
the code.

The embedded payload is therefore **permanently load-bearing**: the sidecar
(#3897/#3898) is a live layer on top of the library, not a replacement for it.
That reclassifies this ADR's monitoring from a bridge until sidecar parity
into standing production surveillance.

Two consequences follow, and both simplify things:

*   The contradictions apply unconditionally, and the publish-contract verifier
    no longer reads `generation_mode` to evaluate them. This restores a
    property the mode-awareness had quietly broken: **gate and alert evaluate
    the identical condition on identical data.** The Grafana rule cannot see
    the mode — the snapshot builder reads only the `.pine`, while
    `generation_mode` lives in the manifest beside it — so a mode-dependent
    gate meant the two layers were answering the same question from different
    inputs. That divergence is the very defect this ADR repairs.
*   A new blocking reason, `static_control_plane_retired`, makes a static
    manifest never publish-ready. The workflow contract test pins the automated
    path only (`--enrich-all` present, `--static-only` absent); blocking the
    mode itself refuses a manual or local publish as well. **Absence of use is
    not a substitute for refusal** — the same lesson as the incident. This also
    replaces the former static-mode suppression of `default_event_risk`, which
    existed solely to let static publish.

The mode stays *generable* for local use. Removing the now-dead `--static-only`
plumbing that threads through four production files is a separate concern
(ADR-0013) and is deliberately not bundled here.

### 4. No bootstrap carve-out

An earlier draft proposed exempting bootstrap runs from
`empty_membership_lists`, on the theory that membership state accumulates over
days and a first run could legitimately be empty. The code says otherwise:

```python
if bootstrap_mode and add_candidate:      # generate_smc_micro_profiles.py:521
    is_active = True
    add_streak = hysteresis["add_runs_required"]
```

Bootstrap *skips* the hysteresis and activates every candidate on the first
run. It is the mode in which empty lists are least plausible, so the carve-out
would have disarmed the guard exactly where it is safest and left it armed
where the risk lives. It is not adopted.

A second consideration reinforces this: a state-aware exemption would make the
gate a function of the membership state file. The Grafana-side parser sees only
the `.pine`, so it could never reproduce that condition, and the two layers
would answer the same question from different sources — structurally the same
defect this ADR repairs. Both blockers therefore read only fields present in
the published artifact, so gate and alert evaluate the identical condition on
identical data.

### 5. `not_run` is scored against a required-check set

`combineVerificationStatuses` stays as it is; as a pure combinator it is
correct, and its test keeps testing what it actually promises. Alongside it,
`requiredCheckKeys(target)` derives from `checkInputs` / `addToChart` which of
the ten preflight slots must produce a real result. `computeTargetOverallPreflightOk`
scores a `not_run` **in a required slot** as `not_verified`. Optional slots may
remain `not_run`, so targets that legitimately skip input or chart checks do
not turn red.

### 6. Two gauges and two alert rules

The transport already exists and carries no volume information:

```text
build_pine_library_version_snapshot.ts   (daily 05:30 UTC; already reads ASOF_DATE)
  → bot/live-pine-library-versions       (rolling branch)
  → pine_library_version_bridge.py
  → /metrics
  → Grafana Cloud → alert-rules.yaml
```

New: the builder parses two more values out of the file it already opens, and
the bridge renders `live_overlay_pine_library_payload_symbols{library=…}` and
`live_overlay_pine_library_payload_lists{library=…}`. No new scrape job, no
additional TradingView traffic, no new Playwright surface.

- **critical** — the contradiction: `payload_symbols == 0` while
  `UNIVERSE_SIZE > 0`.
- **warning** — relative collapse against the previous day
  (`payload_symbols < 0.5 × payload_symbols offset 1d`), which catches a
  partial collapse (6929 → 12) without needing a calibrated absolute floor.

Both carry `runbook` annotations, per the convention established in #1750bf5d6.

### 7. The parser must handle the sharded export form

`render_csv_export` (`scripts/generate_smc_micro_profiles.py:656-665`) emits a
single literal only while the payload fits in `max_chars`. `UNIVERSE_TICKERS`
is rendered with `max_chars=3900`, so a healthy 6929-symbol payload (~35k
characters) is split across roughly nine shards and the export line becomes an
expression:

```pine
const  string UNIVERSE_TICKERS_PART_1 = "…"
export string UNIVERSE_TICKERS = UNIVERSE_TICKERS_PART_1 + "," + UNIVERSE_TICKERS_PART_2 + …
```

A parser written in the shape of the existing `ASOF_DATE_RE`
(`= "…"`) finds no literal here and would report 0 — that is, it would report
"empty" precisely when the payload is healthy, and find a real `""` literal
only in the defective case. The alert would be exactly inverted. The parser
must therefore sum the `*_PART_n` shards, and must distinguish "no match" from
"matched empty": on a parse failure it sets `payload_known = 0` rather than a
count of 0, and the rules multiply by `payload_known` so an unparsed artifact
reads neither as empty nor as green. This mirrors the existing `data_age_known`
handling.

## Consequences

**Positive**

- The incident signature blocks at generation time instead of shipping.
- If a publish bypasses the gate, the critical rule fires within a day.
- Gate and alert evaluate one condition on one artifact, so they cannot drift.
- The contradiction form needs no calibration and no exemption list, so it does
  not decay as thresholds age.

**Negative / explicitly not covered**

- A total collapse in which `UNIVERSE_SIZE` also falls to 0 leaves every field
  consistently empty and produces no contradiction. That case belongs to the
  relative-collapse warning rule, which sees 6929 → 0 over time. The two layers
  cover different shapes of the same outage by design.
- Detection latency for the alert layer is up to ~24h (the snapshot cron runs
  05:30 UTC, the publisher 09:00 Mon–Fri). The gate carries the low-latency
  half.
- The measurement is taken from the repo-owned source, so a payload lost
  *during* publishing (repo good, TradingView empty) is still not covered. A
  published-source readback was considered and deferred: `readEditorContent`
  returns the saved revision rather than the published one, so it would be new
  and materially more fragile automation. Version-level drift remains covered by
  the existing facade probe.
- The orphan scan does **not** cover these gauges, contrary to what an earlier
  draft of this ADR assumed. `test_monitoring_metric_alert_coverage._METRIC_RE`
  enumerates `evidence|github_workflow|vix|feed|bridge|provider_news|trading_signals`
  — the `pine_library` family is absent, so a green scan says nothing about
  payload metrics. This is the same failure shape the ADR repairs, one level up:
  a check trusted without reading what it covers. The new gauges are therefore
  wired to an explicit dashboard panel rather than relying on the scan.
  Extending the family list surfaces three pre-existing orphans
  (`pine_consumer_pin_version`, `pine_library_tv_version[_known]`) and belongs
  in its own PR (ADR-0013).

## Enforced by

Gate layer (decisions 1–4, 7):

- `tests/test_smc_payload_volume.py` — parser (literal, sharded, absent),
  contradiction rules, and the productivity-gate wiring. Pins the shipped
  signature (6929 beside an empty payload) as **blocked**, and a static
  manifest as never publish-ready.
- `tests/test_generate_smc_micro_profiles.py::test_manifest_static_control_plane_is_not_publishable`
  — the inverted pin. It previously asserted the opposite; that premise is what
  #3790 acted on.
- `tests/test_verify_smc_micro_publish_contract.py` — the verifier rejects a
  library that contradicts its manifest, and a manifest whose recorded counts
  diverge from the library.

Staged (decisions 5–6):

- `automation/tradingview/tests/tv_validation_model.test.ts` — `[true, not_run,
  not_run]` in required slots must yield `overall_preflight_ok === false`.
- `tests/test_monitoring_metric_alert_coverage.py`,
  `tests/test_grafana_alert_rules_upsert.py` — metric/alert wiring.
