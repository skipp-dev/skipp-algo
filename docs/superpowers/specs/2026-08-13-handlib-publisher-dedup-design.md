# Hand-authored library publishers — de-duplication and version derivation

**Date:** 2026-08-13

**Origin:** Review of PR #4680
(`fix(pine): re-pin the four engine consumers to the published v3`).
That PR had to bump a hardcoded `--version` default in
`scripts/tv_publish_engine_library.ts` from `2` to `3` alongside the consumer
pins, because the publisher refuses to run when the two disagree. The bump was
correct and necessary, but it exposed a standing obligation: every future
content change to a hand-authored library requires a manual edit to its
publisher's frozen version constant, or the publisher fails.

**Operator decisions recorded 2026-08-13, before implementation:**

1. **Scope** — fix all ten hand-authored publishers, not only the engine one.
2. **Truth source** — the repo's consumer pin is the expectation *before* a
   publish; the facade-reported version is the truth *after* it.
3. **Approach** — extract a shared module and keep ten thin wrappers, rather
   than editing ten near-copies in place or collapsing them into one CLI.

## Problem

### The treadmill

`scripts/tv_publish_<lib>_library.ts` each carry a frozen pair of defaults:

```ts
importPath: getFlag("--import-path", "preuss_steffen/smc_engine_private/3"),
version:    Number(getFlag("--version", "3")),
```

Three mechanisms then bind that constant to reality:

- **Before the publish**, the publisher asserts that the consumer source
  contains the exact import line built from `--import-path`. A mismatch throws
  `Core import mismatch` (engine publisher, `verifyEnginePublishContract`).
- **After the publish**, the publisher requires script identity plus a verified
  version, otherwise it throws
  `Published TradingView <lib> library could not be verified exactly`.
  This check is **weaker than it looks**: when the pine-facade
  lookup answers, `exactVersionVerified` is set to `true` unconditionally
  (`tv_publish_draw_library.ts:339-343`), so a published version that differs
  from the declared `--version` already passes today. That override was added
  deliberately in the #3603/#3606 follow-up, because UI-text evidence settles on
  the hardcoded expectation and made libraries past `/1` exit `rc=1`. The
  equality only still bites when the facade returns `null`.

  **Correction, recorded 2026-08-14 during the final whole-branch review:**
  `draw_library.ts` is representative of only eight of the ten. Measured over
  the whole population at `8a8a9b87a` (`git show 8a8a9b87a:scripts/tv_publish_*_library.ts`
  for each of the ten, grepping `exactVersionVerified`): eight publishers set
  `exactVersionVerified = true;` unconditionally as described above, but
  `tv_publish_engine_library.ts` and `tv_publish_context_engine_library.ts`
  instead set `exactVersionVerified = facadeVersion === details.version;` —
  strict equality, not an unconditional override. For those two, a published
  version that differs from the declared `--version` did **not** already
  pass today. See the second correction under Component 3 below.
- **The orchestrator** `scripts/tv_publish_hand_authored_libraries.ts` invokes
  each publisher with only `--out` and `--no-allow-create` — no `--version`,
  no `--import-path`. The defaults are therefore live in the automated path,
  not merely a convenience for manual runs.

The failure therefore lands on the **pre-publish** check, one run later than one
might expect. TradingView no-ops an unchanged publish, so nothing moves while a
library's content is stable. When the content does change, TradingView
increments the version, the facade override lets that run succeed, and
`repinAllConsumers` rewrites every consumer pin to the new version. On the
**next** run the publisher's frozen `--import-path` no longer matches the
repinned consumer, and `verifyPublishContract` throws `Core import mismatch`
*before writing anything* — until a human edits the constant. Because the
orchestrator publishes in topological dependency order and breaks on the first
failure (`tv_publish_hand_authored_libraries.ts:263-266`, `return 1` at 283),
one stale constant stops the run before the downstream libraries are reached.

### The duplication underneath it

The version constant appears ten times because the whole publisher appears ten
times. Measured on `origin/main` at `8a8a9b87a`:

| Publisher | Lines | Current pinned version |
| --- | ---: | ---: |
| `tv_publish_bus_library.ts` | 418 | 3 |
| `tv_publish_context_engine_library.ts` | 547 | 3 |
| `tv_publish_context_resolvers_library.ts` | 419 | 3 |
| `tv_publish_core_types_library.ts` | 419 | 5 |
| `tv_publish_draw_library.ts` | 421 | 3 |
| `tv_publish_engine_library.ts` | 425 | 3 |
| `tv_publish_lifecycle_library.ts` | 419 | 3 |
| `tv_publish_observability_library.ts` | 419 | 4 |
| `tv_publish_profile_engine_library.ts` | 419 | 3 |
| `tv_publish_utils_library.ts` | 419 | 4 |

Pairwise differences between the plain copies are small and entirely
non-behavioral — `bus` vs `draw` differ in 45 lines, `bus` vs `utils` in 49, and
every differing line is a constant or a name: source path, script name, import
path, alias, description text, report filename stem, report type name, exported
CLI function name, and the noun inside error messages.

Nine of the ten therefore carry roughly 396 identical lines each; about 3,500
lines are redundant copies of one program.

### The one that is not a copy

`tv_publish_context_engine_library.ts` differs from `bus` in 185 lines and is
the exception that shapes this design. It already implements the expectation
model chosen above:

- `consumerPins(repoRoot, scriptName)` scans **every** `.pine` under the repo
  for `import <owner>/<scriptName>/(\d+)` and collects the pinned versions.
- Zero pins is a legal bootstrap state, so a newly introduced private library
  version can be published before anything imports it.
- Any pin that does exist must name the version being published; otherwise the
  run aborts with `Consumer pin mismatch`.
- Its in-file comment records why a core-only check is wrong here: the real
  consumer is `SMC_Context_Bus.pine`, not `SMC_Long_Dip_Suite.pine`, so a
  Suite-only assertion would stay blind precisely when the library is wired.

That reasoning is not specific to the context engine. It is the correct check
for all ten, and it is the check this design promotes to the shared module.

### Two version models, not one

**Discovered 2026-08-13 while preparing the implementation plan.** The context
engine also carries a second contract the other nine do not
(`tv_publish_context_engine_library.ts:218-230`): it takes an
`--expected-current-version` and refuses to run unless
`expectedCurrentVersion === version - 1`, with the message
`Context engine publish must advance exactly one version`.

The two models therefore differ in what `--version` *means*:

| | `--version` means | Consumer pins at publish time |
| --- | --- | --- |
| The nine | the version that is published and that consumers pin | equal to `--version` |
| `context_engine` | the **target** version this run creates | equal to `--version`, i.e. already repinned ahead |

**Assumption, stated rather than resolved:** the shared module carries the
advance contract as an optional descriptor field, enabled only for
`smc_context_engine_private`, so every library keeps the behavior it has today.
Unifying the two models is explicitly out of scope — it would change when a
publish is allowed to run, which is a separate operator decision from
de-duplication. If the operator later wants one model, that is its own spec.

**Correction, recorded 2026-08-14 during the final whole-branch review:** the
assumption above ("every library keeps the behavior it has today") did not
survive implementation for `context_engine`. Pre-refactor,
`tv_publish_context_engine_library.ts` had frozen `--version` /
`--expected-current-version` defaults (`"3"` / `"2"`), so the
advance-exactly-one check ran unconditionally on every invocation, including the
orchestrator's own call path (`tv_publish_hand_authored_libraries.ts` never
passes either flag) — it just always passed trivially against that frozen
pair. Shipped: the advance contract (`tv_publish_hand_lib.ts:436-454`) is
`"enforced"` only when `--version` was passed explicitly; when the version is
instead derived from consumer pins — which is unconditionally the case on the
orchestrator's path post-refactor — it resolves to
`"skipped_derived_version"` and the check does not run at all. So
`context_engine` does not keep the behavior it had today: the advance
contract is live on manual runs that pass `--version` explicitly, and inert
on the automated orchestrator path, where before it always evaluated
(vacuously, against a frozen pair). See
`tests/test_pine_handlib_publisher_inventory.py::test_shared_module_preflights_before_any_editor_mutation`
for the equivalent, and separate, distinction on the page-auth-probe /
preflight pair within a single `requiresExplicitVersionAdvance` publish.

### The guard that freezes the current shape

`tests/test_pine_handlib_publisher_inventory.py` asserts the present structure
directly, so it will fail on any fix and must move with it:

| Test | What it asserts today |
| --- | --- |
| `test_context_engine_publisher_defaults_are_coherent` | `--library`, `--script-name`, `--import-path` and `--version` defaults exist **as literals in the publisher file** and agree with each other |
| `test_core_types_publisher_defaults_match_current_consumer_pin` | the `core_types` `--version` default is literally `"5"` and the consumer pins `/5` |
| `test_context_engine_publisher_checks_pins_across_every_consumer` | `function consumerPins(` occurs **inside `tv_publish_context_engine_library.ts`**, along with `path.join(repoRoot, "SMC++")` and `Consumer pin mismatch`, and that `if (!coreText.includes(expectedImportLine))` does **not** occur |
| `test_engine_publisher_requires_exact_facade_version` | `publishedVersion = facadeVersion;` occurs in the engine publisher |

The second of these hardcodes the version `5`, which means the treadmill is
enforced by a test as well as by the code. Migrating this guard is the highest
risk item in this design and is treated as its own component.

## Scope

- A shared publisher module for the ten hand-authored `SMC++/` libraries.
- Version and import path derived from the repo's consumer pins instead of
  frozen constants.
- Post-publish verification that accepts a version bump as success.
- Migration of `tests/test_pine_handlib_publisher_inventory.py` and the one
  existing TypeScript publisher test, with a mutation proof per assertion.

### Non-goals

- **No collapse into a single CLI.** The ten script paths stay, because
  `package.json` scripts and the orchestrator's `publisher:` entries address
  them by path, and operators run them by hand.
- **No change to the generated-library publishers.**
  `tv_publish_micro_library.ts` and `tv_publish_overlay_library.ts` publish
  `pine/generated/` content on a different lifecycle and are out of scope,
  even though they import the same `tv_shared.ts` helpers.
- **No change to repin behavior.** `repinAllConsumers` in the orchestrator
  already rewrites consumer pins to the real published version; this design
  relies on it and does not alter it.
- **No TV→repo sync.** The repo remains the single source of truth per
  `CLAUDE.md`; nothing here reads library *content* back from TradingView.
- **No change to the dependency ordering** encoded in `HAND_LIBS`.

## Component 1 — the shared module

New file `automation/tradingview/lib/tv_publish_hand_lib.ts`, exporting:

```ts
export type HandLibDescriptor = {
  scriptName:  string;  // "smc_draw"
  source:      string;  // "SMC++/smc_draw.pine"
  alias:       string;  // "d"
  noun:        string;  // "Draw" — interpolated into error messages
  reportStem:  string;  // "publish-draw-library"
  description: string;
  /**
   * Opt-in to the advance-exactly-one contract that only
   * smc_context_engine_private has today: require --expected-current-version
   * and refuse unless it equals version - 1. Absent or false for the nine.
   */
  requiresExplicitVersionAdvance?: boolean;
};

export async function runHandLibPublish(
  descriptor: HandLibDescriptor,
  argv: string[],
): Promise<number>;
```

It absorbs the argument parsing, contract verification, publish, facade
verification, retry, and report writing that the ten copies share. Each of the
ten scripts becomes a wrapper holding only its descriptor and its exported CLI
function:

```ts
#!/usr/bin/env -S node --enable-source-maps
import { runHandLibPublish, type HandLibDescriptor }
  from "../automation/tradingview/lib/tv_publish_hand_lib.js";

export const DRAW_LIBRARY: HandLibDescriptor = {
  scriptName:  "smc_draw",
  source:      "SMC++/smc_draw.pine",
  alias:       "d",
  noun:        "Draw",
  reportStem:  "publish-draw-library",
  description: "Private drawing and visualization helpers consumed by SMC Core.",
};

export async function runPublishDrawLibraryCli(): Promise<number> {
  return runHandLibPublish(DRAW_LIBRARY, process.argv);
}
```

No external module imports any `runPublish*Cli` symbol today (verified by grep
across `automation/`, `scripts/` and `tests/`), so the wrapper shape is free.
Script paths, npm script names, and the orchestrator's `publisher:` values are
unchanged, which is what keeps the blast radius of a ~4,300-line refactor
confined to the files being refactored.

## Component 2 — version derivation

`consumerPins` moves from the context-engine publisher into the shared module
and becomes the sole source of the expected version. Resolution order:

1. An explicit `--version` / `--import-path` on the command line wins, so an
   operator can still force a value during a bootstrap or a recovery.
2. Otherwise the module scans every `.pine` in the repo for
   `import <owner>/<scriptName>/(\d+)`, excluding the library's own source.
3. **Zero pins** — legal bootstrap, but only in combination with rule 1: an
   explicit `--version` is required.
4. **All pins agree** — that version is the expectation.
5. **Pins disagree** — abort before any write, naming every file and version
   found. This is a repo inconsistency, and publishing against a guess would
   pick a winner silently.

The pre-publish identity assertion keeps its current strength: the library
source must carry the matching `library(...)` header, and every existing
consumer pin must name the version about to be published. What disappears is
only the frozen literal that made that expectation stale by default.

**Correction, recorded 2026-08-14 during the final whole-branch review:** item
3 above originally read "legal bootstrap. The publish proceeds and the
published version is whatever the facade reports." That does not match the
shipped code. `resolveDefaultVersion` (`tv_publish_hand_lib.ts:293-301`)
**throws** when zero consumer pins are found and `--version` was not passed,
naming the library and requiring an explicit `--version`; it does not fall
through to letting the facade decide. The reason is ordering, not oversight:
the pre-publish contract check needs a concrete target version *before*
touching TradingView, and the facade can only answer *after* the write — so
there is nothing for "whatever the facade reports" to mean at the point this
resolution runs. An operator publishing a library nothing imports yet must
therefore pass `--version` explicitly (rule 1); only then does the zero-pins
case resolve at all, and it resolves to the explicit value, not a facade
guess.

## Component 3 — post-publish verification

**Correction, recorded 2026-08-13 while reading the implementation:** an earlier
draft of this spec claimed the run fails unless
`publishedVersion === details.version`, and that this equality is what a content
bump violates. That is wrong. The facade override at
`tv_publish_draw_library.ts:339-343` already sets `exactVersionVerified = true`
whenever the facade answers, so a bumped version passes today. This component is
therefore much smaller than first scoped, and what remains of it is mostly a
*tightening*.

**Second correction, recorded 2026-08-14 during the final whole-branch
review:** the correction above is itself incomplete — it is true for eight of
the ten, not all ten. Measured over the whole population at `8a8a9b87a`
(`git show 8a8a9b87a:scripts/tv_publish_*_library.ts` for each of the ten,
grepping `exactVersionVerified`): eight publishers set
`exactVersionVerified = true;` unconditionally as the correction above
describes, but `tv_publish_engine_library.ts` and
`tv_publish_context_engine_library.ts` set
`exactVersionVerified = facadeVersion === details.version;` instead — strict
equality. For those two, a bumped version did **not** already pass today; item
2 below (acceptance of a version above the expectation) is a **relaxation**
for engine and context_engine, not a tightening. Items 1 and 3 are unaffected
by this distinction — the silent-facade fallback and the below-expectation
rejection are new behavior for all ten either way.

Three things change:

1. **The silent-facade fallback stops trusting a constant.** In the
   `idempotent_no_change` branches (lines 245-246, 289-290, 323-324) the
   publisher sets `publishedVersion = details.version` — the hardcoded
   expectation — when nothing changed and the facade said nothing. With
   Component 2 that value is the derived consumer pin, so the fallback becomes
   correct by construction instead of correct by maintenance.

2. **Acceptance of a bump becomes explicit and tested.** Today it is an emergent
   property of an unconditional `= true` inside a branch, covered by no test.
   The shared module states the rule directly: a facade-verified version is
   authoritative and may exceed the expectation.

3. **A version *below* the expectation becomes a failure.** Today the facade
   override accepts it, because it sets `exactVersionVerified = true` without
   looking at the direction. A published version lower than every consumer pin
   means the wrong script was addressed, and that should not pass. This is new
   protection, not a relaxation.

`not_verified` — no facade answer and no UI evidence — still fails, as today.

The net effect on the operator-visible contract is that a publish which moves
`3 → 4` succeeds and reports `4` (as it already does), and the orchestrator's
`repinAllConsumers(lib, 4)` converges the repo — the behavior it was written
for.

## Component 4 — guard migration

Each assertion in `tests/test_pine_handlib_publisher_inventory.py` is rewritten
to protect the same property at its new location. The intent is preserved; only
the address changes.

| Today | After |
| --- | --- |
| `--version` literal exists in the publisher file | no wrapper may supply a *default* version literal — the flag itself stays supported in the shared module, but a hardcoded fallback in a wrapper is the regression being guarded against |
| `core_types` default is `"5"` and consumers pin `/5` | derived expectation for `smc_core_types` equals the version its consumers actually pin, whatever that is |
| `function consumerPins(` inside the context-engine publisher | `consumerPins` exported from the shared module, and every one of the ten resolves through it |
| `publishedVersion = facadeVersion;` in the engine publisher | the shared module assigns the facade version, and no wrapper overrides it |

Two new assertions are added, because the refactor creates two new ways to be
wrong:

- every `HAND_LIBS` entry's `publisher` file resolves to a wrapper that exports
  a descriptor whose `scriptName` matches the entry's `name`;
- no wrapper contains publish logic — the wrappers are descriptor plus CLI
  export only.

## Testing

Structural assertions of this kind pass vacuously when their subject moves, so
each rewritten assertion ships with a **mutation proof**: violate the property
in a scratch copy, run the test, record that it fails; restore, record that it
passes. A rewritten guard without a recorded red run is not accepted.

Beyond the guard:

- `automation/tradingview/tests/tv_publish_draw_library.test.ts` is the only
  dedicated TypeScript test among the ten and is re-pointed at the shared
  module; the behavior it covers now covers all ten by construction.
- New unit tests for `consumerPins` resolution: zero pins, unanimous pins,
  disagreeing pins, and the library's own source excluded from the scan.
- New unit tests for post-publish acceptance: equal version, bumped version,
  lower version, and `not_verified`.
- The full TypeScript lane and the Python ledger set run before the push, per
  the repo's pre-push gate.

A live TradingView publish is **not** part of the automated test plan. The
session is a shared, rate-limited resource and the publish path writes to the
production account. Acceptance on the live path is an operator-run of
`tv_publish_hand_authored_libraries.ts --dry-run`, followed by one real run at
the operator's discretion.

## Risks

**A refactor of a live write path cannot be proven by unit tests alone.** The
publishers write to the production TradingView account. The mitigation is that
the descriptor-and-wrapper split leaves every entry point addressable exactly as
before, so a bad outcome is recoverable by reverting one commit rather than by
reconstructing ten files.

**The `--dry-run` path in the orchestrator is the only cheap end-to-end
rehearsal**, and it does not exercise the publisher's post-publish branch at
all. Coverage of that branch stays unit-level.

**Deriving the expectation from the repo makes a mis-pinned repo authoritative.**
If every consumer is pinned wrong in the same direction, the publisher will now
proceed where it previously refused. This is the accepted cost of the operator's
chosen truth source and is consistent with `CLAUDE.md` — but it means the
consumer-pin guards in CI remain load-bearing and must not be weakened as part
of this work.

**`context_engine` loses its bespoke implementation.** Its 185 differing lines
contain the reasoning this design generalizes; the comment explaining why a
core-only check is wrong must survive into the shared module rather than being
dropped as refactor noise.
