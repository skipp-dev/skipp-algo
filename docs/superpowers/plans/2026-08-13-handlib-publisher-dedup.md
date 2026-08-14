# Hand-lib publisher de-duplication — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace ten near-copied TradingView publishers with one shared module plus ten descriptor wrappers, and derive each library's expected version from the repo's consumer pins instead of a frozen constant.

**Architecture:** Pure, Playwright-free logic (pin scanning, version derivation, post-publish acceptance) lands in `automation/tradingview/lib/tv_publish_hand_lib.ts` first and is unit-tested on its own. The Playwright publish body is extracted from `scripts/tv_publish_draw_library.ts` afterwards and parameterized by a `HandLibDescriptor`. Publishers convert one at a time, `draw` first as the pilot because it is the only one with a dedicated TypeScript test.

**Tech Stack:** TypeScript run through `tsx`, Node's built-in `node:test` runner with `node:assert/strict`, Playwright via the existing `automation/tradingview/lib/tv_shared.ts` helpers, pytest for the Python inventory guard.

**Spec:** `docs/superpowers/specs/2026-08-13-handlib-publisher-dedup-design.md`

## Global Constraints

- The repo is the single source of truth for all Pine libraries; publishing is **repo → TradingView only**. Never read library content back from TradingView (`CLAUDE.md`).
- No unverified assumptions. Every checkable claim in a commit message, PR body or comment must be resolved to TRUE or FALSE with evidence before it is written (`CLAUDE.md`).
- The ten script paths under `scripts/tv_publish_*_library.ts` must keep working as CLI entry points — `package.json` and `scripts/tv_publish_hand_authored_libraries.ts` address them by path.
- Structural/string-matching guards must ship with a recorded mutation proof: violate the property, observe red; restore, observe green. A rewritten guard without a recorded red run is not accepted.
- Python runs through the main repo venv at `/Users/spreuss/Documents/skipp-algo/.venv/bin/python`. Always set `PYTEST_ADDOPTS="-n 4"` — `-n auto` OOMs on 16 GB.
- Every push runs the pre-push gate (ruff + the 8 line-pinned ledger tests). Push only via a backgrounded command; a foreground timeout orphans the hook.
- No live TradingView publish is part of this plan. Acceptance on the live path is an operator run.

## File Structure

| File | Responsibility |
| --- | --- |
| `automation/tradingview/lib/tv_publish_hand_lib.ts` (create) | `HandLibDescriptor`, pin scanning, version derivation, post-publish acceptance, and the shared `runHandLibPublish` body |
| `automation/tradingview/tests/tv_publish_hand_lib.test.ts` (create) | unit tests for the pure functions above |
| `scripts/tv_publish_<lib>_library.ts` × 10 (rewrite) | descriptor + exported CLI function only |
| `automation/tradingview/tests/tv_publish_draw_library.test.ts` (modify) | re-pointed at the shared module |
| `tests/test_pine_handlib_publisher_inventory.py` (modify) | guard migrated to the new structure |

---

### Task 1: Pin scanning and version derivation

**Files:**
- Create: `automation/tradingview/lib/tv_publish_hand_lib.ts`
- Test: `automation/tradingview/tests/tv_publish_hand_lib.test.ts`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `type ConsumerPin = { file: string; version: number }`, `consumerPineFiles(repoRoot: string): string[]`, `consumerPins(repoRoot: string, scriptName: string): ConsumerPin[]`, and `deriveExpectedVersion(repoRoot: string, scriptName: string): { version: number | null; pins: ConsumerPin[] }`. `deriveExpectedVersion` returns `version: null` for the zero-pin bootstrap case and throws on disagreement.

- [ ] **Step 1: Write the failing tests**

Create `automation/tradingview/tests/tv_publish_hand_lib.test.ts`:

```ts
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";

import { consumerPins, deriveExpectedVersion } from "../lib/tv_publish_hand_lib.js";

function scratchRepo(files: Record<string, string>): string {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "handlib-"));
  fs.mkdirSync(path.join(root, "SMC++"), { recursive: true });
  for (const [rel, body] of Object.entries(files)) {
    fs.writeFileSync(path.join(root, rel), body, "utf-8");
  }
  return root;
}

test("a library is not its own consumer", () => {
  const root = scratchRepo({
    "SMC++/smc_draw.pine": 'library("smc_draw")\nimport preuss_steffen/smc_draw/3 as d\n',
  });
  assert.deepEqual(consumerPins(root, "smc_draw"), []);
});

test("pins are collected from the repo root and SMC++", () => {
  const root = scratchRepo({
    "SMC_Long_Dip_Suite.pine": "import preuss_steffen/smc_draw/3 as d\n",
    "SMC++/smc_context_engine_private.pine": "import preuss_steffen/smc_draw/3 as d\n",
  });
  assert.equal(consumerPins(root, "smc_draw").length, 2);
});

test("zero pins is a legal bootstrap, not an error", () => {
  const root = scratchRepo({ "SMC_Long_Dip_Suite.pine": "// nothing pins draw\n" });
  const resolved = deriveExpectedVersion(root, "smc_draw");
  assert.equal(resolved.version, null);
  assert.deepEqual(resolved.pins, []);
});

test("unanimous pins become the expectation", () => {
  const root = scratchRepo({
    "SMC_Long_Dip_Suite.pine": "import preuss_steffen/smc_draw/4 as d\n",
    "SMC_Breakout_Overlay.pine": "import preuss_steffen/smc_draw/4 as d\n",
  });
  assert.equal(deriveExpectedVersion(root, "smc_draw").version, 4);
});

test("disagreeing pins abort and name every file and version", () => {
  const root = scratchRepo({
    "SMC_Long_Dip_Suite.pine": "import preuss_steffen/smc_draw/4 as d\n",
    "SMC_Breakout_Overlay.pine": "import preuss_steffen/smc_draw/3 as d\n",
  });
  assert.throws(
    () => deriveExpectedVersion(root, "smc_draw"),
    (e: Error) =>
      /Consumer pins disagree/.test(e.message)
      && /SMC_Long_Dip_Suite\.pine pins \/4/.test(e.message)
      && /SMC_Breakout_Overlay\.pine pins \/3/.test(e.message),
  );
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `npx tsx --test automation/tradingview/tests/tv_publish_hand_lib.test.ts`
Expected: FAIL — cannot resolve `../lib/tv_publish_hand_lib.js`.

- [ ] **Step 3: Write the minimal implementation**

Create `automation/tradingview/lib/tv_publish_hand_lib.ts`:

```ts
import fs from "node:fs";
import path from "node:path";

export type ConsumerPin = { file: string; version: number };

/** Every repo .pine that may import a hand-authored library. */
export function consumerPineFiles(repoRoot: string): string[] {
  const out: string[] = [];
  for (const dir of [repoRoot, path.join(repoRoot, "SMC++")]) {
    let entries: fs.Dirent[];
    try {
      entries = fs.readdirSync(dir, { withFileTypes: true });
    } catch {
      continue;
    }
    for (const e of entries) {
      if (e.isFile() && e.name.endsWith(".pine")) {
        out.push(path.join(dir, e.name));
      }
    }
  }
  return out;
}

/** Every consumer pin of `scriptName`, with the version each one names. */
export function consumerPins(repoRoot: string, scriptName: string): ConsumerPin[] {
  const re = new RegExp(`import\\s+[A-Za-z0-9_]+\\/${scriptName}\\/(\\d+)`, "g");
  const pins: ConsumerPin[] = [];
  for (const file of consumerPineFiles(repoRoot)) {
    // The library declares itself; it is not its own consumer.
    if (path.basename(file) === `${scriptName}.pine`) {
      continue;
    }
    const text = fs.readFileSync(file, "utf-8");
    for (const m of text.matchAll(re)) {
      pins.push({ file, version: Number(m[1]) });
    }
  }
  return pins;
}

/**
 * The version the repo declares for `scriptName`.
 *
 * Zero pins is a legal bootstrap (a newly introduced private library version
 * that nothing imports yet) and yields `null`. Disagreement is a repo
 * inconsistency and aborts before any TradingView write, because publishing
 * against a guess would pick a winner silently.
 */
export function deriveExpectedVersion(
  repoRoot: string,
  scriptName: string,
): { version: number | null; pins: ConsumerPin[] } {
  const pins = consumerPins(repoRoot, scriptName);
  const distinct = [...new Set(pins.map((p) => p.version))];
  if (distinct.length > 1) {
    const detail = pins
      .map((p) => `${path.relative(repoRoot, p.file)} pins /${p.version}`)
      .join(", ");
    throw new Error(
      `Consumer pins disagree for ${scriptName}: ${detail}. `
        + `Reconcile the repo before publishing.`,
    );
  }
  return { version: distinct.length === 1 ? distinct[0] : null, pins };
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `npx tsx --test automation/tradingview/tests/tv_publish_hand_lib.test.ts`
Expected: PASS, 5/5.

- [ ] **Step 5: Commit**

```bash
git add automation/tradingview/lib/tv_publish_hand_lib.ts automation/tradingview/tests/tv_publish_hand_lib.test.ts
git commit -m "feat(tv): derive hand-lib expected version from consumer pins"
```

---

### Task 2: Post-publish acceptance rule

**Files:**
- Modify: `automation/tradingview/lib/tv_publish_hand_lib.ts`
- Test: `automation/tradingview/tests/tv_publish_hand_lib.test.ts`

**Interfaces:**
- Consumes: nothing from Task 1 at runtime; same module.
- Produces: `resolveVersionAcceptance(input: { expected: number | null; published: number | null; facadeAnswered: boolean }): { accepted: boolean; reason: string }`.

This encodes the rule the spec's Component 3 states: a facade-verified version is authoritative and may exceed the expectation; a version *below* the expectation is rejected (new protection — today's unconditional override accepts it); no verified version at all still fails.

- [ ] **Step 1: Write the failing tests**

Append to `automation/tradingview/tests/tv_publish_hand_lib.test.ts`:

```ts
import { resolveVersionAcceptance } from "../lib/tv_publish_hand_lib.js";

test("a facade-verified equal version is accepted", () => {
  const r = resolveVersionAcceptance({ expected: 3, published: 3, facadeAnswered: true });
  assert.equal(r.accepted, true);
});

test("a facade-verified bump above the expectation is accepted", () => {
  const r = resolveVersionAcceptance({ expected: 3, published: 4, facadeAnswered: true });
  assert.equal(r.accepted, true);
  assert.match(r.reason, /advanced/);
});

test("a version below the expectation is rejected", () => {
  const r = resolveVersionAcceptance({ expected: 4, published: 3, facadeAnswered: true });
  assert.equal(r.accepted, false);
  assert.match(r.reason, /below/);
});

test("no verified version fails even when the facade answered nothing", () => {
  const r = resolveVersionAcceptance({ expected: 3, published: null, facadeAnswered: false });
  assert.equal(r.accepted, false);
  assert.match(r.reason, /not verified/);
});

test("a bootstrap with no expectation accepts any verified version", () => {
  const r = resolveVersionAcceptance({ expected: null, published: 1, facadeAnswered: true });
  assert.equal(r.accepted, true);
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `npx tsx --test automation/tradingview/tests/tv_publish_hand_lib.test.ts`
Expected: FAIL — `resolveVersionAcceptance` is not exported.

- [ ] **Step 3: Write the minimal implementation**

Append to `automation/tradingview/lib/tv_publish_hand_lib.ts`:

```ts
/**
 * Whether a publish counts as verified.
 *
 * The pre-existing facade override (#3603/#3606) set acceptance to true
 * whenever the facade answered, without looking at the direction of the
 * difference. That kept bumped libraries from exiting rc=1, but it also
 * accepted a version BELOW every consumer pin — which means the wrong script
 * was addressed, not that content changed. This states both halves explicitly.
 */
export function resolveVersionAcceptance(input: {
  expected: number | null;
  published: number | null;
  facadeAnswered: boolean;
}): { accepted: boolean; reason: string } {
  const { expected, published } = input;
  if (published === null) {
    return { accepted: false, reason: "published version not verified" };
  }
  if (expected === null) {
    return { accepted: true, reason: `bootstrap: no consumer pin, published /${published}` };
  }
  if (published < expected) {
    return {
      accepted: false,
      reason: `published /${published} is below the expected /${expected}`,
    };
  }
  if (published > expected) {
    return { accepted: true, reason: `publish advanced /${expected} to /${published}` };
  }
  return { accepted: true, reason: `published /${published} matches the consumer pin` };
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `npx tsx --test automation/tradingview/tests/tv_publish_hand_lib.test.ts`
Expected: PASS, 10/10.

- [ ] **Step 5: Commit**

```bash
git add automation/tradingview/lib/tv_publish_hand_lib.ts automation/tradingview/tests/tv_publish_hand_lib.test.ts
git commit -m "feat(tv): state the post-publish acceptance rule explicitly"
```

---

### Task 3: The shared publish body

**Files:**
- Modify: `automation/tradingview/lib/tv_publish_hand_lib.ts`
- Read as the extraction source: `scripts/tv_publish_draw_library.ts:1-421`

**Interfaces:**
- Consumes: `deriveExpectedVersion`, `resolveVersionAcceptance` from Tasks 1-2.
- Produces: `HandLibDescriptor` and `runHandLibPublish(descriptor: HandLibDescriptor, argv: string[]): Promise<number>`.

- [ ] **Step 1: Add the descriptor type**

```ts
export type HandLibDescriptor = {
  scriptName: string;
  source: string;
  alias: string;
  noun: string;
  reportStem: string;
  description: string;
  /**
   * Opt-in to the advance-exactly-one contract that only
   * smc_context_engine_private has today (see
   * tv_publish_context_engine_library.ts:218-230): require
   * --expected-current-version and refuse unless it equals version - 1.
   */
  requiresExplicitVersionAdvance?: boolean;
};
```

- [ ] **Step 2: Move the body across unchanged, then parameterize**

Copy `runPublishDrawLibraryCli` (lines 153-412) and its helpers `parseArgs` (83-118) and `verifyDrawPublishContract` (120-151) into the module as one `runHandLibPublish(descriptor, argv)`. Change **only** these, leaving all Playwright sequencing byte-identical:

- `parseArgs` takes `argv` instead of reading `process.argv`, and its defaults come from the descriptor: `--library` → `descriptor.source`, `--script-name` → `descriptor.scriptName`, `--alias` → `descriptor.alias`, `--description` → `descriptor.description`, `--out` → `automation/tradingview/reports/${descriptor.reportStem}-<ts>.json`.
- `--version` and `--import-path` lose their literal defaults. When absent, `deriveExpectedVersion(repoRoot, descriptor.scriptName)` supplies the version and the import path is built as `preuss_steffen/${descriptor.scriptName}/${version}`.
- The contract check replaces the core-only `coreText.includes(expectedImportLine)` assertion with the pin check from `tv_publish_context_engine_library.ts:206-217`, **carrying its explanatory comment across verbatim** — the spec names losing that reasoning as a risk.
- The final gate at line 345 calls `resolveVersionAcceptance` and throws with its `reason` instead of the inline `exactVersionVerified` boolean.
- Error nouns interpolate `descriptor.noun`.

- [ ] **Step 3: Verify the module compiles and the unit tests still pass**

Run: `npx tsc --noEmit -p tsconfig.json && npx tsx --test automation/tradingview/tests/tv_publish_hand_lib.test.ts`
Expected: no type errors; 10/10 pass.

- [ ] **Step 4: Commit**

```bash
git add automation/tradingview/lib/tv_publish_hand_lib.ts
git commit -m "refactor(tv): extract the shared hand-lib publish body"
```

---

### Task 4: Convert `draw` as the pilot

**Files:**
- Rewrite: `scripts/tv_publish_draw_library.ts`
- Modify: `automation/tradingview/tests/tv_publish_draw_library.test.ts`

**Interfaces:**
- Consumes: `runHandLibPublish`, `HandLibDescriptor`.
- Produces: `DRAW_LIBRARY: HandLibDescriptor` and `runPublishDrawLibraryCli(): Promise<number>` — the same exported name as today, so nothing that greps for it breaks.

`draw` goes first because it is the only one of the ten with a dedicated TypeScript test, so parity is observable before the other nine move.

- [ ] **Step 1: Rewrite the publisher as a wrapper**

```ts
#!/usr/bin/env -S node --enable-source-maps
import path from "node:path";
import { fileURLToPath } from "node:url";

import { runHandLibPublish, type HandLibDescriptor }
  from "../automation/tradingview/lib/tv_publish_hand_lib.js";

export const DRAW_LIBRARY: HandLibDescriptor = {
  scriptName: "smc_draw",
  source: "SMC++/smc_draw.pine",
  alias: "d",
  noun: "Draw",
  reportStem: "publish-draw-library",
  description: "Private drawing and visualization helpers consumed by SMC Core.",
};

export async function runPublishDrawLibraryCli(): Promise<number> {
  return runHandLibPublish(DRAW_LIBRARY, process.argv);
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  runPublishDrawLibraryCli()
    .then((code) => process.exit(code))
    .catch((error: unknown) => {
      console.error(error instanceof Error ? error.stack || error.message : String(error));
      process.exit(1);
    });
}
```

- [ ] **Step 2: Re-point the existing draw test at the shared module**

Read `automation/tradingview/tests/tv_publish_draw_library.test.ts` first and move each assertion to whichever file now owns the property: assertions about publish sequencing move to the shared module's path; assertions about the descriptor stay on the wrapper.

- [ ] **Step 3: Run the full TypeScript lane**

Run: `npm run tv:test`
Expected: PASS. A failure here is real — the pilot is the parity check.

- [ ] **Step 4: Commit**

```bash
git add scripts/tv_publish_draw_library.ts automation/tradingview/tests/tv_publish_draw_library.test.ts
git commit -m "refactor(tv): convert the draw publisher to a descriptor wrapper"
```

---

### Task 5: Convert the eight remaining plain publishers

**Files:**
- Rewrite: `scripts/tv_publish_{bus,context_resolvers,core_types,engine,lifecycle,observability,profile_engine,utils}_library.ts`

**Interfaces:**
- Consumes: `runHandLibPublish`, `HandLibDescriptor`.
- Produces: one `<LIB>_LIBRARY` descriptor and the existing `runPublish<Lib>LibraryCli` export per file.

Each file follows Task 4's wrapper shape exactly. The per-library values, read from the current defaults on `origin/main` — do not re-derive them from memory:

| File | scriptName | alias | noun | reportStem |
| --- | --- | --- | --- | --- |
| `tv_publish_bus_library.ts` | `smc_bus_private` | `bp` | Bus | `publish-bus-library` |
| `tv_publish_context_resolvers_library.ts` | `smc_context_resolvers` | *from file* | Context resolvers | `publish-context-resolvers-library` |
| `tv_publish_core_types_library.ts` | `smc_core_types` | `ct` | Core types | `publish-core-types-library` |
| `tv_publish_engine_library.ts` | `smc_engine_private` | `eng` | Engine | `publish-engine-private-library` |
| `tv_publish_lifecycle_library.ts` | `smc_lifecycle_private` | *from file* | Lifecycle | `publish-lifecycle-library` |
| `tv_publish_observability_library.ts` | `smc_observability_private` | *from file* | Observability | `publish-observability-library` |
| `tv_publish_profile_engine_library.ts` | `smc_profile_engine` | *from file* | Profile engine | `publish-profile-engine-library` |
| `tv_publish_utils_library.ts` | `smc_utils` | *from file* | Utils | `publish-utils-library` |

Cells marked *from file* are not recorded in the spec's measurements; read the current `--alias` and `--out` defaults out of each file before writing its descriptor rather than guessing.

- [ ] **Step 1: Convert one file, run `npm run tv:test`, commit — then repeat**

Convert them one at a time with a test run and a commit each, so a parity break bisects to a single library:

```bash
git add scripts/tv_publish_bus_library.ts
git commit -m "refactor(tv): convert the bus publisher to a descriptor wrapper"
```

- [ ] **Step 2: Verify no version literal survives**

Run:
```bash
grep -nE 'getFlag\("--(version|import-path)"' scripts/tv_publish_*_library.ts
```
Expected: no output from the nine converted wrappers.

---

### Task 6: Convert `context_engine` with its advance contract

**Files:**
- Rewrite: `scripts/tv_publish_context_engine_library.ts`
- Modify: `automation/tradingview/lib/tv_publish_hand_lib.ts`

**Interfaces:**
- Consumes: `runHandLibPublish`.
- Produces: `CONTEXT_ENGINE_LIBRARY` with `requiresExplicitVersionAdvance: true`.

- [ ] **Step 1: Write the failing test for the advance contract**

```ts
test("the advance contract rejects a target that is not current + 1", () => {
  assert.throws(
    () => assertVersionAdvance({ expectedCurrentVersion: 3, version: 5, noun: "Context engine" }),
    /must advance exactly one version/,
  );
});

test("the advance contract accepts current + 1", () => {
  assert.doesNotThrow(
    () => assertVersionAdvance({ expectedCurrentVersion: 3, version: 4, noun: "Context engine" }),
  );
});
```

- [ ] **Step 2: Run to verify failure, then implement `assertVersionAdvance` in the shared module and gate it on `descriptor.requiresExplicitVersionAdvance`**

The thrown message must keep the substring `must advance exactly one version` so any existing operator runbook matching on it still works.

- [ ] **Step 3: Rewrite the publisher as a wrapper with `requiresExplicitVersionAdvance: true`, run `npm run tv:test`, commit**

---

### Task 7: Migrate the inventory guard

**Files:**
- Modify: `tests/test_pine_handlib_publisher_inventory.py`

**Interfaces:**
- Consumes: the wrappers' descriptor shape from Tasks 4-6.
- Produces: no code interface; this is the guard that keeps the new structure honest.

The four assertions listed in the spec's Component 4 point at the old structure and will fail. Each is rewritten to protect the same property at its new address, and each rewrite carries a mutation proof.

- [ ] **Step 1: Replace the two default-literal tests with a no-frozen-version test**

```python
PUBLISHERS = sorted((REPO_ROOT / "scripts").glob("tv_publish_*_library.ts"))
_FROZEN_VERSION_RE = re.compile(r'getFlag\(\s*"--(?:version|import-path)"')


def test_no_wrapper_freezes_a_library_version() -> None:
    """The treadmill this refactor removed must not grow back.

    A hardcoded --version/--import-path default in a wrapper means the next
    content change to that library breaks its publisher until a human edits
    the constant. The flags stay supported in the shared module; only a
    frozen fallback in a wrapper is the regression.
    """
    offenders = [
        p.relative_to(REPO_ROOT).as_posix()
        for p in PUBLISHERS
        if _FROZEN_VERSION_RE.search(p.read_text(encoding="utf-8"))
    ]
    assert not offenders, (
        "these publishers froze a library version again: " + ", ".join(offenders)
    )
```

- [ ] **Step 2: Prove the new test bites**

```bash
python - <<'PY'
from pathlib import Path
p = Path("scripts/tv_publish_draw_library.ts")
p.write_text(p.read_text() + '\nconst frozen = getFlag("--version", "3");\n')
PY
PYTEST_ADDOPTS="-n 4" /Users/spreuss/Documents/skipp-algo/.venv/bin/python -m pytest \
  tests/test_pine_handlib_publisher_inventory.py::test_no_wrapper_freezes_a_library_version -q
```
Expected: **FAIL**, naming `scripts/tv_publish_draw_library.ts`. Then `git checkout scripts/tv_publish_draw_library.ts` and re-run: expected PASS. Record both outcomes in the commit message.

- [ ] **Step 3: Re-point the `consumerPins` location test at the shared module**

```python
SHARED_MODULE = REPO_ROOT / "automation" / "tradingview" / "lib" / "tv_publish_hand_lib.ts"


def test_pin_check_runs_across_every_consumer_from_the_shared_module() -> None:
    text = SHARED_MODULE.read_text(encoding="utf-8")
    assert "export function consumerPins(" in text, (
        "the cross-consumer pin scan is gone from the shared module"
    )
    assert 'path.join(repoRoot, "SMC++")' in text, (
        "the scan no longer covers SMC++/, so a sibling-library pin is invisible"
    )
    assert "Consumer pins disagree" in text, "the disagreement error message is gone"
```

- [ ] **Step 4: Prove it bites** — delete the `SMC++` join from the shared module, run the test, expect FAIL; restore, expect PASS.

- [ ] **Step 5: Replace the facade-assignment test with an acceptance-rule test**

```python
def test_acceptance_rule_rejects_a_version_below_the_expectation() -> None:
    text = SHARED_MODULE.read_text(encoding="utf-8")
    assert "export function resolveVersionAcceptance(" in text
    assert "is below the expected" in text, (
        "the below-expectation rejection is gone; a wrong-script publish would pass"
    )
```

- [ ] **Step 6: Add the two new structural assertions from the spec**

```python
def test_every_hand_lib_publisher_is_a_thin_wrapper() -> None:
    """Wrappers hold a descriptor and a CLI export — never publish logic."""
    fat = [
        p.relative_to(REPO_ROOT).as_posix()
        for p in PUBLISHERS
        if "newTradingViewSession(" in p.read_text(encoding="utf-8")
    ]
    assert not fat, "these publishers still contain publish logic: " + ", ".join(fat)


@pytest.mark.parametrize("name", sorted(_hand_libs()))
def test_descriptor_script_name_matches_the_hand_libs_entry(name: str) -> None:
    entry = _hand_libs()[name]
    publisher = entry["publisher"]
    if publisher is None:
        pytest.skip(f"{name} has no publisher by design")
    text = (REPO_ROOT / publisher).read_text(encoding="utf-8")
    assert f'scriptName: "{name}"' in text, (
        f"{publisher} does not declare scriptName {name!r}"
    )
```

- [ ] **Step 7: Run the whole guard and commit**

```bash
PYTEST_ADDOPTS="-n 4" /Users/spreuss/Documents/skipp-algo/.venv/bin/python -m pytest \
  tests/test_pine_handlib_publisher_inventory.py -q
git add tests/test_pine_handlib_publisher_inventory.py
git commit -m "test(tv): migrate the hand-lib inventory guard to the shared module

Mutation proofs recorded per assertion: each was observed red against a
violated property and green after restore."
```

---

### Task 8: Full gate and PR

**Files:** none changed; this task is verification.

- [ ] **Step 1: Purge stale bytecode**

```bash
find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null
```

- [ ] **Step 2: ruff**

```bash
/Users/spreuss/Documents/skipp-algo/.venv/bin/python -m ruff check --fix . \
  && /Users/spreuss/Documents/skipp-algo/.venv/bin/python -m ruff check .
```
Expected: `All checks passed!`

- [ ] **Step 3: The eight line-pinned ledger tests**

```bash
PYTEST_ADDOPTS="-n 4" /Users/spreuss/Documents/skipp-algo/.venv/bin/python -m pytest \
  tests/test_global_statement_budget.py tests/test_noqa_budget.py \
  tests/test_noqa_suppression_ledger.py tests/test_subprocess_shell_injection_pin.py \
  tests/test_type_ignore_budget.py tests/test_path_text_io_encoding_ledger.py \
  tests/test_atomic_write_call_sites.py tests/test_hmac_auth_zero_surface.py \
  -q --no-header
```
Expected: all pass.

- [ ] **Step 4: The full TypeScript lane and the workflow-touching Python tests**

```bash
npm run tv:test
PYTEST_ADDOPTS="-n 4" /Users/spreuss/Documents/skipp-algo/.venv/bin/python -m pytest tests/ -k "workflow or handlib or pine" -q
```

- [ ] **Step 5: Push in the background and open the PR**

The PR body states which parts were proven by execution and which remain operator-gated: no live TradingView publish ran, so the acceptance of the live path is an operator run of `tv_publish_hand_authored_libraries.ts --dry-run` followed by one real run.

---

## Self-review

**Spec coverage.** Component 1 → Tasks 3-6. Component 2 → Task 1 plus the parameterization in Task 3. Component 3 → Task 2, wired in Task 3 Step 2. Component 4 → Task 7. The spec's two-version-models subsection → Task 6. The spec's testing section → Tasks 1, 2, 7 and Task 8.

**Placeholders.** The only deliberately unfilled cells are the four *from file* aliases in Task 5, which the step explicitly instructs the implementer to read out of the source rather than guess — recording a guessed alias here would be worse than recording its absence.

**Type consistency.** `HandLibDescriptor` is defined once in Task 3 and consumed unchanged in Tasks 4-6. `deriveExpectedVersion` returns `{ version, pins }` in Task 1 and is consumed as such in Task 3. `resolveVersionAcceptance` takes `{ expected, published, facadeAnswered }` in Task 2 and is called with those names in Task 3.
