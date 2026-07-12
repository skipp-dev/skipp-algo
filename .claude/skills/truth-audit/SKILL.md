---
name: truth-audit
description: Sweep a codebase for places where a name, docstring, comment, or schema promises behavior the code doesn't actually deliver (misnomers, stale docs, dead/unwired-but-valuable code), verify each claim at the implementation, and fix docs net-zero or make a wire-or-remove decision. Use when asked to check that names/docs match behavior, e.g. "wir vertrauen auf names und doku, aber wenn diese irreführend sind kommen wir zu falschen Schlüssen — such nach solchen Mustern".
---

# Truth audit — name/doc vs behavior

We trust names and docs; when they mislead, we reach wrong conclusions. This skill finds
the gaps between what a symbol/comment/schema *promises* and what the code *does*, then
resolves each one. It pairs with **verify-review-findings** (check open PRs first) and
**skipp-pr-flow** (land the fixes).

## Instructions

### Step 1: Harvest claims
Grep for anything that asserts behavior a reader would trust without checking:
- **Names** that promise semantics: `*_score`, `*_count`, `*_share`, `catalyst_*`, `is_*`,
  `*_rank`, `total_*`, `deep_copy`, `atomic_*`, `idempotent`.
- **Docstrings / comments** with claims: "returns X", "sorted by Y", "reverses on read",
  "assumes UTC", "protected on the remote", schedule/threshold/TTL statements, "exposes all
  N fields", "one hour after close".
- **Schema / config descriptions** and metric HELP text.

### Step 2: Verify each claim at the implementation
Read the actual code path — not the name. For each claim decide: does the code do exactly
what the name/doc says? Watch for the high-frequency traps:
- A `*_count` that counts the wrong thing (tickers-with-≥N vs actual impact).
- A signed mean named like a magnitude ("heat" that's really polarity, so a `> 0.8` guard
  fires on the opposite sign).
- A field name carrying a *different* already-computed value (posture score sent as
  `catalyst_score`).
- A parameter that's silently ignored or coupled to an unrelated knob.
- A comment describing a schedule/threshold the code no longer uses.

### Step 3: Classify and resolve
- **Doc/comment wrong, behavior fine** → fix the prose **net-zero** (1-for-1, trailing
  comment) so you don't drift line-pinned ledgers. This is the bulk of a truth-audit.
- **Code wrong (a real bug the name exposed)** → separate behavior fix with a test; run it
  through **verify-review-findings** first (may already be fixed / in an open PR).
- **Dead or unwired but valuable** → explicit **wire-or-remove** decision. Wire it if the
  intent was clear and the cost is small (e.g. a fetched-but-never-merged ratios layer);
  remove it if it's a constant, never-read stub (a dead always-false "signal" field). Never
  leave it in limbo.
- **Name misleading, behavior correct, name is public API** → don't silently rename
  (breaks importers/consumers). Add an honestly-named alias and deprecate the misnomer, or
  document the real semantics; schedule the rename for the next publish/major cycle.

### Step 4: Handle the special surfaces
- **Generated / auto-synced files** (e.g. Pine libraries synced from TradingView, generator
  outputs): fix the **generator** or the upstream source, not the emitted file — a repo edit
  is overwritten on the next sync.
- **Test-meta**: a guard that asserts the *text presence* of a behavior guarantee passes
  even when the guaranteed code is dead. Anchor such assertions on the real behavior /
  block, whitespace-normalised, not on a substring anywhere in the module.
- **Verify before believing a finding is a bug.** Confirm language/runtime semantics
  (example: Pine v6 divides int/int fractionally, so an "int-truncation" misnomer finding is
  a false positive). A wrong finding is worse than none.

### Step 5: Report the residual risk honestly
A grep-and-verify sweep covers the *surface*. State plainly what it can't reach: misnomers
that only domain knowledge would catch (a name that's plausible and subtly wrong), and any
auto-synced source whose truth lives elsewhere. Completeness = "surface audited once";
never claim more.

## Output discipline
- Each finding: `file:line`, the claim quoted, what the code actually does, severity, and the
  chosen resolution (doc-fix / behavior-fix / wire / remove / rename-later).
- Group doc-only net-zero fixes into one PR; keep behavior changes separate.
- Land via **skipp-pr-flow**; keep noise out of large line-pinned files.
