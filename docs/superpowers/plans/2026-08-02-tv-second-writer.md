# TradingView second-writer coverage — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Detect out-of-band writes to the managed TradingView layouts, let the operator exclude CI by code, and halve the detection latency on days with no CI run.

**Architecture:** Three independent mechanisms. A Python gate refuses mutating runs inside an operator-declared window. A pure TypeScript comparison function decides, before the first mutation, whether the live bindings still match the last CI observation published to `bot/live-tradingview-bindings`. A second read-only cron shortens the no-run detection gap. Nothing here changes what a mutating run writes.

**Tech Stack:** GitHub Actions workflows (YAML), Python 3.12 (stdlib only), TypeScript run through `tsx`, `node:test` for TS unit tests, pytest for Python tests.

**Spec:** `docs/superpowers/specs/2026-08-02-tv-second-writer-design.md`

## Global Constraints

- **Python interpreter:** `/Users/spreuss/Documents/skipp-algo/.venv/bin/python` (3.12). This worktree has no `.venv` of its own; the main checkout's is the one to use, and it runs this worktree's tests correctly from this working directory (verified 2026-08-02). The system `python3` is 3.9 and raises spurious `datetime.UTC` ImportErrors -- that is a reason to invoke the right interpreter, NOT a reason to avoid the spelling. Write `datetime.UTC`: ruff's UP017 is enforced here and rewrites `timezone.utc` to it, and the five existing files that need a UTC constant all use `datetime.UTC`.
- **Workflow edits:** the pre-push guard only runs the fast-gates selection, so it is blind to workflow contract tests. Any task touching `.github/workflows/` runs `pytest tests/ -k workflow` in full before committing.
- **New TypeScript test files** must be registered in THREE places in `.github/workflows/tv-onboarding-packages.yml`: the `paths:` filter near line 30, the `paths:` filter near line 77, and the space-separated file list in the `npx tsx --test …` run step near line 192. A file missing from the run step never executes and the gate is vacuous.
- **Ledger guard:** run with `PYTEST_ADDOPTS="-n 4"`. The default `-n auto` gets SIGKILLed (rc=137) on a 16 GB Mac.
- **Push:** always via `Bash` with `run_in_background: true`. A foreground timeout orphans the pre-push hook and flakes the import-probe tests.
- **Branch:** all work lands on one branch off `origin/main` in a sibling worktree; do not commit to `main` directly.
- **Commit messages:** conventional commits, scope `tv` for TradingView surfaces.

---

## File Structure

**Create:**
- `scripts/check_tv_operator_window.py` — decides whether an operator window is open. Pure function plus a thin CLI; no repo or network access.
- `tests/test_check_tv_operator_window.py` — unit tests for the four value classes, injected clock.
- `automation/tradingview/lib/tv_out_of_band_drift.ts` — pure comparison of observed bindings against a baseline snapshot. No Playwright import.
- `automation/tradingview/tests/tv_out_of_band_drift.test.ts` — unit tests for clean / drifted / missing / incomplete baselines.

**Modify:**
- `.github/workflows/tv-save-consumer-source.yml` — operator-window gate, evening cron, baseline fetch step.
- `.github/workflows/tv-onboarding-packages.yml` — register the new TS test in three places.
- `tests/test_workflow_tv_save_consumer_source_contract.py` — amend the schedule pin, add gate and baseline pins.
- `scripts/tv_batch_consumer_rollout.ts` — pre-mutation observation, `outOfBandDrift` report field, `ok` gating.

---

## Task 1: Operator-window decision script

**Files:**
- Create: `scripts/check_tv_operator_window.py`
- Test: `tests/test_check_tv_operator_window.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `evaluate(raw: str | None, now: datetime) -> tuple[int, str]` returning `(exit_code, message)`; module entrypoint `python -m scripts.check_tv_operator_window` exiting 0 or 1. Task 2 calls the module.

- [ ] **Step 1: Write the failing test**

Create `tests/test_check_tv_operator_window.py`:

```python
"""The operator window is a claim on the TradingView account, with an expiry.

The expiry is the design: a forgotten window blocks nothing past its own
timestamp, which is what makes a hard refusal safe to build at all. An
unreadable value fails closed because the variable only ever changes by
deliberate operator action -- but the message carries the one command that
clears it, so a typo costs seconds.
"""

from __future__ import annotations

from datetime import UTC, datetime

from scripts.check_tv_operator_window import evaluate

_NOW = datetime(2026, 8, 2, 20, 0, tzinfo=UTC)


def test_unset_variable_lets_the_run_through() -> None:
    for raw in (None, "", "   "):
        assert evaluate(raw, _NOW)[0] == 0


def test_expired_window_lets_the_run_through_and_says_so() -> None:
    code, message = evaluate("2026-08-02T19:00:00Z", _NOW)
    assert code == 0
    assert "expired" in message


def test_open_window_blocks_and_names_the_expiry_and_the_remaining_time() -> None:
    code, message = evaluate("2026-08-02T22:00:00Z", _NOW)
    assert code == 1
    assert "2026-08-02T22:00:00+00:00" in message
    assert "120 min" in message


def test_unparsable_value_fails_closed_with_the_clearing_command() -> None:
    code, message = evaluate("tomorrow", _NOW)
    assert code == 1
    assert "gh variable delete TV_OPERATOR_ACTIVE" in message


def test_naive_timestamp_is_refused_rather_than_guessed() -> None:
    """Guessing a zone would silently shift the window by hours."""
    code, message = evaluate("2026-08-02T22:00:00", _NOW)
    assert code == 1
    assert "UTC offset" in message
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/Users/spreuss/Documents/skipp-algo/.venv/bin/python -m pytest tests/test_check_tv_operator_window.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'scripts.check_tv_operator_window'`

- [ ] **Step 3: Write the implementation**

Create `scripts/check_tv_operator_window.py`:

```python
#!/usr/bin/env python3
"""Refuse a mutating TradingView run while the operator claims the account.

The operator's browser is the normal production writer on the TradingView
account and automation is the guest; TradingView autosaves from that browser.
Until now the two coordinated by convention -- ``tv-save-consumer-source``
itself says so: "No mechanism detects or excludes that session."

This is that mechanism, in the one direction it can honestly cover: CI starting
while the operator is working. It cannot detect an undeclared session, and it
does not touch the opposite direction (a tab opened mid-run), which stays with
``tv-post-mutation-verify``.

The repository variable holds an EXPIRY, not a boolean, so a forgotten claim
cannot block the pipeline past its own timestamp::

    gh variable set TV_OPERATOR_ACTIVE --body "2026-08-02T22:00:00Z"

Read-only runs are never gated: they write nothing, and gating them would let an
open window suppress exactly the verification that makes the window safe.
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import UTC, datetime

VARIABLE = "TV_OPERATOR_ACTIVE"
CLEAR_COMMAND = f"gh variable delete {VARIABLE}"


def _parse(raw: str) -> datetime:
    text = raw.strip()
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        raise ValueError("timestamp has no UTC offset")
    return parsed


def evaluate(raw: str | None, now: datetime) -> tuple[int, str]:
    """Return ``(exit_code, message)``. Exit code 1 means: do not mutate."""
    if raw is None or not raw.strip():
        return 0, ""
    try:
        until = _parse(raw)
    except ValueError as error:
        return 1, (
            f"{VARIABLE} is set to {raw!r}, which is not an ISO-8601 timestamp "
            f"with a UTC offset ({error}). Refusing to mutate TradingView while "
            f"the operator's claim cannot be read. Clear it with: {CLEAR_COMMAND}"
        )
    if until <= now:
        return 0, f"{VARIABLE} expired at {until.isoformat()} -- proceeding."
    minutes = int((until - now).total_seconds() // 60)
    return 1, (
        f"The operator claims the TradingView account until {until.isoformat()} "
        f"({minutes} min from now). Refusing to mutate: a CI write now would race "
        f"the operator's browser, whose autosave is unserialised. Wait for the "
        f"window to expire, or end it early with: {CLEAR_COMMAND}"
    )


def main() -> int:
    argparse.ArgumentParser(description="Gate mutating TradingView runs on the operator window.").parse_args()
    code, message = evaluate(os.environ.get(VARIABLE), datetime.now(UTC))
    if message:
        print(f"::{'error' if code else 'notice'}::{message}")
    return code


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `/Users/spreuss/Documents/skipp-algo/.venv/bin/python -m pytest tests/test_check_tv_operator_window.py -v`
Expected: PASS, 5 tests

- [ ] **Step 5: Verify the CLI behaves as a module**

Run:
```bash
TV_OPERATOR_ACTIVE="2027-01-01T00:00:00Z" .venv/bin/python -m scripts.check_tv_operator_window; echo "exit=$?"
TV_OPERATOR_ACTIVE="" .venv/bin/python -m scripts.check_tv_operator_window; echo "exit=$?"
```
Expected: first prints an `::error::` line and `exit=1`; second prints nothing and `exit=0`.

- [ ] **Step 6: Lint and commit**

```bash
/Users/spreuss/Documents/skipp-algo/.venv/bin/python -m ruff check scripts/check_tv_operator_window.py tests/test_check_tv_operator_window.py
git add scripts/check_tv_operator_window.py tests/test_check_tv_operator_window.py
git commit -m "feat(tv): decide whether an operator window blocks a mutating run"
```

---

## Task 2: Gate the mutating workflow on the operator window

**Files:**
- Modify: `.github/workflows/tv-save-consumer-source.yml` (insert one step after `Checkout`)
- Modify: `tests/test_workflow_tv_save_consumer_source_contract.py` (append two tests)

**Interfaces:**
- Consumes: `python -m scripts.check_tv_operator_window` from Task 1.
- Produces: a workflow step named exactly `Refuse to mutate inside the operator's TradingView window`. Task 6 places its baseline fetch after this step.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_workflow_tv_save_consumer_source_contract.py`:

```python
_GATE = "Refuse to mutate inside the operator's TradingView window"


def test_operator_window_gate_runs_before_the_expensive_setup() -> None:
    """A refusal must cost seconds, not a Playwright install.

    Placed after Checkout (it needs the script) and before Set up Node, so an
    open window ends the run in about a second instead of after three minutes
    of npm and browser downloads.
    """
    names = [step.get("name", "") for step in _steps()]
    assert _GATE in names, f"missing step: {_GATE}"
    assert names.index("Checkout") < names.index(_GATE) < names.index("Set up Node")


def test_operator_window_gate_exempts_read_only_runs() -> None:
    """An open window must not suppress the verification that makes it safe.

    Read-only runs write nothing, so they are never gated. The condition
    classifies the trigger paths exactly as the rollout step's TV_VERIFY_ONLY
    expression does: schedule is read-only, a dispatch with verify_only=true is
    read-only, and everything else -- including the workflow_run refresh chain,
    which is how 2026-08-01 reached the account -- mutates.
    """
    step = next(s for s in _steps() if s.get("name") == _GATE)
    condition = step["if"]
    assert "github.event_name != 'schedule'" in condition
    assert "github.event.inputs.verify_only != 'true'" in condition
    assert "github.event_name == 'workflow_run'" not in condition
    assert step["env"]["TV_OPERATOR_ACTIVE"] == "${{ vars.TV_OPERATOR_ACTIVE }}"
    assert "scripts.check_tv_operator_window" in step["run"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `/Users/spreuss/Documents/skipp-algo/.venv/bin/python -m pytest tests/test_workflow_tv_save_consumer_source_contract.py -k operator_window -v`
Expected: FAIL — `missing step: Refuse to mutate inside the operator's TradingView window`

- [ ] **Step 3: Insert the step in the workflow**

In `.github/workflows/tv-save-consumer-source.yml`, immediately after the `- name: Checkout` step block (the one with `persist-credentials: false`) and before `- name: Set up Node`, insert:

```yaml
      # The operator's browser is the normal production writer on this account
      # and automation is the guest; the tradingview-session group serialises
      # CI against CI only. This is the one direction that can be excluded
      # honestly: CI starting while the operator is working. The variable holds
      # an EXPIRY, so a forgotten claim cannot block this workflow past its own
      # timestamp -- see scripts/check_tv_operator_window.py.
      #
      # Read-only runs are exempt on purpose: they write nothing, and gating
      # them would let an open window suppress the evening verification.
      - name: Refuse to mutate inside the operator's TradingView window
        if: ${{ github.event_name != 'schedule' && github.event.inputs.verify_only != 'true' }}
        env:
          TV_OPERATOR_ACTIVE: ${{ vars.TV_OPERATOR_ACTIVE }}
        run: python3 -m scripts.check_tv_operator_window
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `/Users/spreuss/Documents/skipp-algo/.venv/bin/python -m pytest tests/test_workflow_tv_save_consumer_source_contract.py -v`
Expected: PASS, all tests in the file

- [ ] **Step 5: Run the full workflow selection**

Run: `/Users/spreuss/Documents/skipp-algo/.venv/bin/python -m pytest tests/ -k workflow -q`
Expected: PASS. `test_workflow_auth_pattern.py` and `test_fast_gates_silent_skip_coverage.py` also read this file; a new step must not trip them.

- [ ] **Step 6: Commit**

```bash
git add .github/workflows/tv-save-consumer-source.yml tests/test_workflow_tv_save_consumer_source_contract.py
git commit -m "feat(tv): refuse mutating saves inside the operator's declared window"
```

---

## Task 3: Evening read-only verification

**Files:**
- Modify: `.github/workflows/tv-save-consumer-source.yml` (schedule block)
- Modify: `tests/test_workflow_tv_save_consumer_source_contract.py` (existing test, renamed)

**Interfaces:**
- Consumes: nothing.
- Produces: nothing consumed by later tasks.

- [ ] **Step 1: Amend the existing pin to the failing state**

In `tests/test_workflow_tv_save_consumer_source_contract.py`, rename `test_schedule_is_daily_and_invokes_explicit_verify_only_mode` to `test_schedule_runs_twice_daily_and_invokes_explicit_verify_only_mode` and replace only its schedule assertion:

```python
    # Two read-only looks per day. The morning cron alone left operator-caused
    # drift undetected for up to 24h on a day with no other run; the evening one
    # halves that. Both sit after the US close, honouring this file's
    # off-hours-only live-window declaration. Read-only is structural, not
    # conventional: TV_VERIFY_ONLY and TV_CONSUMER_MAPPING_JSON both derive from
    # github.event_name == 'schedule', so no cron entry can mutate.
    assert on_block["schedule"] == [{"cron": "17 5 * * *"}, {"cron": "17 21 * * *"}]
```

Leave the rest of the test body unchanged.

- [ ] **Step 2: Run the test to verify it fails**

Run: `/Users/spreuss/Documents/skipp-algo/.venv/bin/python -m pytest tests/test_workflow_tv_save_consumer_source_contract.py -k schedule -v`
Expected: FAIL — `assert [{'cron': '17 5 * * *'}] == [{'cron': '17 5 * * *'}, {'cron': '17 21 * * *'}]`

- [ ] **Step 3: Add the cron entry**

In `.github/workflows/tv-save-consumer-source.yml`, change the `schedule` block to:

```yaml
  schedule:
    - cron: "17 5 * * *"
    # Evening read-only look. Operator-caused drift on a day with no CI run was
    # otherwise invisible until the next morning; this halves the worst case to
    # ~12h. After the US close, so the off-hours posture holds.
    - cron: "17 21 * * *"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `/Users/spreuss/Documents/skipp-algo/.venv/bin/python -m pytest tests/ -k workflow -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add .github/workflows/tv-save-consumer-source.yml tests/test_workflow_tv_save_consumer_source_contract.py
git commit -m "feat(tv): add an evening read-only verification of the managed layouts"
```

---

## Task 4: Out-of-band drift comparison

**Files:**
- Create: `automation/tradingview/lib/tv_out_of_band_drift.ts`
- Create: `automation/tradingview/tests/tv_out_of_band_drift.test.ts`
- Modify: `.github/workflows/tv-onboarding-packages.yml` (three registration points)

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `compareAgainstBaseline({observed, baseline, expectedScriptNames}) => OutOfBandVerdict` where `OutOfBandVerdict = {status: "clean" | "drifted" | "unknown", reason: string, changed: Array<{scriptName, label, baseline, observed}>}`, and the input type `ObservedConsumer = {scriptName: string, selections: Array<{label: string, actual: string | null}>}`. Task 5 imports both.

- [ ] **Step 1: Write the failing test**

Create `automation/tradingview/tests/tv_out_of_band_drift.test.ts`:

```ts
import assert from "node:assert/strict";
import { test } from "node:test";

import { compareAgainstBaseline } from "../lib/tv_out_of_band_drift.js";

const NAMES = ["SMC Decision Board", "SMC Event Overlay"];

function consumer(scriptName: string, actual: string | null) {
  return { scriptName, selections: [{ label: "Bus", actual }] };
}

test("identical readings are clean", () => {
  const observed = [consumer(NAMES[0], "study_1"), consumer(NAMES[1], "study_2")];
  const verdict = compareAgainstBaseline({
    observed,
    baseline: [consumer(NAMES[0], "study_1"), consumer(NAMES[1], "study_2")],
    expectedScriptNames: NAMES,
  });
  assert.equal(verdict.status, "clean");
  assert.deepEqual(verdict.changed, []);
});

test("a changed parent id is drift, and the target is named", () => {
  const verdict = compareAgainstBaseline({
    observed: [consumer(NAMES[0], "study_9"), consumer(NAMES[1], "study_2")],
    baseline: [consumer(NAMES[0], "study_1"), consumer(NAMES[1], "study_2")],
    expectedScriptNames: NAMES,
  });
  assert.equal(verdict.status, "drifted");
  assert.equal(verdict.changed.length, 1);
  assert.equal(verdict.changed[0].scriptName, NAMES[0]);
  assert.equal(verdict.changed[0].baseline, "study_1");
  assert.equal(verdict.changed[0].observed, "study_9");
});

test("a missing baseline is unknown, never clean", () => {
  const verdict = compareAgainstBaseline({
    observed: [consumer(NAMES[0], "study_1"), consumer(NAMES[1], "study_2")],
    baseline: null,
    expectedScriptNames: NAMES,
  });
  assert.equal(verdict.status, "unknown");
  assert.match(verdict.reason, /no published baseline/);
});

test("an INCOMPLETE baseline is unknown, not drift", () => {
  // The publish step runs under always(), so a run that died before verifying
  // publishes a partial observation. Comparing a full reading against that
  // would invent drift that never happened.
  const verdict = compareAgainstBaseline({
    observed: [consumer(NAMES[0], "study_1"), consumer(NAMES[1], "study_2")],
    baseline: [consumer(NAMES[0], "study_1")],
    expectedScriptNames: NAMES,
  });
  assert.equal(verdict.status, "unknown");
  assert.match(verdict.reason, /does not cover/);
});

test("an incomplete OBSERVATION is unknown too", () => {
  const verdict = compareAgainstBaseline({
    observed: [consumer(NAMES[0], "study_1")],
    baseline: [consumer(NAMES[0], "study_1"), consumer(NAMES[1], "study_2")],
    expectedScriptNames: NAMES,
  });
  assert.equal(verdict.status, "unknown");
  assert.match(verdict.reason, /this run did not read/);
});

test("a binding that disappeared counts as drift", () => {
  const verdict = compareAgainstBaseline({
    observed: [{ scriptName: NAMES[0], selections: [] }, consumer(NAMES[1], "study_2")],
    baseline: [consumer(NAMES[0], "study_1"), consumer(NAMES[1], "study_2")],
    expectedScriptNames: NAMES,
  });
  assert.equal(verdict.status, "drifted");
  assert.equal(verdict.changed[0].observed, null);
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `npx tsx --test automation/tradingview/tests/tv_out_of_band_drift.test.ts`
Expected: FAIL — cannot find module `../lib/tv_out_of_band_drift.js`

- [ ] **Step 3: Write the implementation**

Create `automation/tradingview/lib/tv_out_of_band_drift.ts`:

```ts
/**
 * Decide whether someone other than this run wrote to the managed layouts.
 *
 * Read BEFORE the first mutation, any difference from the last CI observation
 * is by construction not this run's doing -- that is the proof the pipeline
 * currently cannot produce. The baseline is the snapshot every run force-pushes
 * to `bot/live-tradingview-bindings`.
 *
 * The comparison key is the actual bound parent study id per label. Source
 * hashes stay out of it: `sources.drifted` already covers them on every run.
 *
 * Three verdicts, and the third is load-bearing. "unknown" means the comparison
 * could not be made -- a missing, unreadable or PARTIAL baseline, or a run that
 * did not read every target. It never rounds to "clean", and it never rounds to
 * "drifted" either: reporting drift that did not happen would train the
 * operator to ignore the signal.
 */

export type ObservedBinding = { label: string; actual: string | null };
export type ObservedConsumer = { scriptName: string; selections: ObservedBinding[] };

export type OutOfBandChange = {
  scriptName: string;
  label: string;
  baseline: string | null;
  observed: string | null;
};

export type OutOfBandVerdict = {
  status: "clean" | "drifted" | "unknown";
  reason: string;
  changed: OutOfBandChange[];
};

function selectionsByLabel(consumer: ObservedConsumer): Map<string, string | null> {
  return new Map(consumer.selections.map((selection) => [selection.label, selection.actual]));
}

function coverage(consumers: ObservedConsumer[], expected: string[]): string[] {
  const present = new Set(consumers.map((consumer) => consumer.scriptName));
  return expected.filter((name) => !present.has(name));
}

export function compareAgainstBaseline(args: {
  observed: ObservedConsumer[];
  baseline: ObservedConsumer[] | null;
  expectedScriptNames: string[];
}): OutOfBandVerdict {
  const { observed, baseline, expectedScriptNames } = args;

  if (baseline === null) {
    return {
      status: "unknown",
      reason: "no published baseline snapshot was available to compare against",
      changed: [],
    };
  }

  const missingFromBaseline = coverage(baseline, expectedScriptNames);
  if (missingFromBaseline.length > 0) {
    return {
      status: "unknown",
      reason: `the baseline does not cover every verify target (missing: ${missingFromBaseline.join(", ")})`,
      changed: [],
    };
  }

  const missingFromObserved = coverage(observed, expectedScriptNames);
  if (missingFromObserved.length > 0) {
    return {
      status: "unknown",
      reason: `this run did not read every verify target (missing: ${missingFromObserved.join(", ")})`,
      changed: [],
    };
  }

  const baselineByName = new Map(baseline.map((consumer) => [consumer.scriptName, selectionsByLabel(consumer)]));
  const observedByName = new Map(observed.map((consumer) => [consumer.scriptName, selectionsByLabel(consumer)]));
  const changed: OutOfBandChange[] = [];

  for (const scriptName of expectedScriptNames) {
    const before = baselineByName.get(scriptName)!;
    const after = observedByName.get(scriptName)!;
    for (const label of new Set([...before.keys(), ...after.keys()])) {
      // A label absent on one side reads as null: a binding that disappeared is
      // as much a foreign write as one that moved.
      const was = before.get(label) ?? null;
      const is = after.get(label) ?? null;
      if (was !== is) changed.push({ scriptName, label, baseline: was, observed: is });
    }
  }

  if (changed.length > 0) {
    return {
      status: "drifted",
      reason: `${changed.length} binding(s) changed since the last CI observation`,
      changed,
    };
  }

  return { status: "clean", reason: "every binding matches the last CI observation", changed: [] };
}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `npx tsx --test automation/tradingview/tests/tv_out_of_band_drift.test.ts`
Expected: PASS, 6 tests

- [ ] **Step 5: Register the test file in all three places**

In `.github/workflows/tv-onboarding-packages.yml`:
1. Add `      - "automation/tradingview/tests/tv_out_of_band_drift.test.ts"` to the `paths:` list near line 30.
2. Add the same line to the `paths:` list near line 77.
3. Append ` automation/tradingview/tests/tv_out_of_band_drift.test.ts` to the end of the `npx tsx --test …` command near line 192.

Verify all three landed:

```bash
grep -c 'tv_out_of_band_drift.test.ts' .github/workflows/tv-onboarding-packages.yml
```
Expected: `3`

- [ ] **Step 6: Run the full TS test list exactly as CI does**

Run the complete `npx tsx --test …` command from the workflow's run step (copy it verbatim, including the newly appended file).
Expected: PASS, no file reported as missing.

- [ ] **Step 7: Commit**

```bash
git add automation/tradingview/lib/tv_out_of_band_drift.ts \
        automation/tradingview/tests/tv_out_of_band_drift.test.ts \
        .github/workflows/tv-onboarding-packages.yml
git commit -m "feat(tv): compare live bindings against the last published CI observation"
```

---

## Task 5: Read the layouts before mutating and report the verdict

**Files:**
- Modify: `scripts/tv_batch_consumer_rollout.ts`
- Create: `automation/tradingview/tests/tv_pre_mutation_observation.test.ts`
- Modify: `.github/workflows/tv-onboarding-packages.yml` (three registration points)

**Interfaces:**
- Consumes: `compareAgainstBaseline`, `ObservedConsumer`, `OutOfBandVerdict` from Task 4.
- Produces: the report field `outOfBandDrift: OutOfBandVerdict` in `tradingview_consumer_bindings.json`, and the CLI flag `--baseline <path>` (default `artifacts/monitoring/previous/tradingview_consumer_bindings.json`). Task 6 writes that file.

This task pins behaviour by regex over the source, the way
`automation/tradingview/tests/tv_preflight_add_to_chart_floor.test.ts` already
does: the pre-mutation pass needs a live browser, so its ordering and its
gating cannot be exercised by a unit test.

- [ ] **Step 1: Write the failing test**

Create `automation/tradingview/tests/tv_pre_mutation_observation.test.ts`:

```ts
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { test } from "node:test";

const SOURCE = fs.readFileSync(
  path.resolve(process.cwd(), "scripts/tv_batch_consumer_rollout.ts"),
  "utf-8",
);

test("the baseline comparison is wired to the shared pure function", () => {
  assert.match(SOURCE, /import \{[\s\S]*?compareAgainstBaseline[\s\S]*?\} from "\.\.\/automation\/tradingview\/lib\/tv_out_of_band_drift\.js"/);
});

test("the pre-mutation read happens only when the run mutates", () => {
  // A read-only run has nothing to prove: it cannot be the writer, and the
  // extra pass would double the cost of the cheapest run in the system.
  assert.match(SOURCE, /if \(executionPlan\.mode !== "verify-only"\) \{[\s\S]*?observeBindingsOnly\(/);
});

test("the pre-mutation read precedes the first write", () => {
  // Anchored on the CALL, not the name: the function definition sits above
  // main(), so indexOf("observeBindingsOnly(") would find the declaration and
  // every ordering assertion below would pass without measuring anything.
  const observe = SOURCE.indexOf("await observeBindingsOnly(");
  const firstSave = SOURCE.indexOf("if (executionPlan.saveSources) {");
  assert.ok(observe > 0, "observeBindingsOnly is never called");
  assert.ok(
    observe < firstSave,
    "the observation must run before the first save, or its finding is no longer attributable to a second writer",
  );
});

test("the observation leaves the save phase on the primary chart with an editor", () => {
  // observeBindingsOnly walks the OTHER layouts, so it ends off the primary
  // chart with the Pine editor closed. It must therefore sit ahead of the
  // gotoChart/ensurePineEditor pair, which then restores exactly the state
  // saveConsumerSource assumes. After that pair, the first save would open on
  // the wrong chart.
  const observe = SOURCE.indexOf("await observeBindingsOnly(");
  const restore = SOURCE.indexOf("await ensurePineEditor(session.page);");
  assert.ok(restore > 0, "the primary-chart editor restore is gone");
  assert.ok(observe < restore, "the pre-mutation observation must precede the editor restore");
});

test("a drifted or unknown verdict makes the run red", () => {
  assert.match(SOURCE, /report\.outOfBandDrift\.status === "clean"/);
});

test("the verdict is reported, not used to withhold the save", () => {
  // Operator decision 2026-08-01, repeated here: withholding freezes the
  // consumers on an old pinned library while the producer moves on.
  assert.doesNotMatch(SOURCE, /outOfBandDrift[\s\S]{0,200}?config\.saveTargets = \[\]/);
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `npx tsx --test automation/tradingview/tests/tv_pre_mutation_observation.test.ts`
Expected: FAIL on the first test — the import does not exist.

- [ ] **Step 3: Add the report field and the import**

In `scripts/tv_batch_consumer_rollout.ts`, add to the import block:

```ts
import {
  compareAgainstBaseline,
  type ObservedConsumer,
  type OutOfBandVerdict,
} from "../automation/tradingview/lib/tv_out_of_band_drift.js";
```

Add to the `RolloutReport` type, immediately after the `mutations: {…}` block:

```ts
  /**
   * Whether anyone wrote to the managed layouts between the last CI run and
   * this one. Measured BEFORE this run's first mutation, so a difference is
   * attributable to a second writer -- normally the operator's browser, whose
   * autosave nothing in CI serialises against.
   */
  outOfBandDrift: OutOfBandVerdict;
```

Add to the report initialiser, immediately after the `mutations: {…}` literal:

```ts
    outOfBandDrift: {
      status: "unknown",
      reason: "the pre-mutation observation has not run yet",
      changed: [],
    },
```

- [ ] **Step 4: Add the observation helper**

In `scripts/tv_batch_consumer_rollout.ts`, add above `async function main()`:

```ts
/**
 * Read the bindings of every verify target without changing anything.
 *
 * verifyConsumerBindings is called with repair=false and forceRebind=false, so
 * this walks the layouts read-only. A target that cannot be read is simply
 * absent from the result, which the comparison turns into "unknown" rather than
 * into a false drift.
 */
async function observeBindingsOnly(
  session: Awaited<ReturnType<typeof newTradingViewSession>>,
  config: RolloutConfig,
): Promise<ObservedConsumer[]> {
  const observed: ObservedConsumer[] = [];
  for (const layout of groupTargetsByLayout(config.verifyTargets, config.primaryChartUrl)) {
    if (!session.page.url().startsWith(layout.chartUrl)) {
      await gotoChart(session.page, layout.chartUrl);
    }
    for (const target of layout.targets) {
      try {
        const result = await verifyConsumerBindings(session, target, false, false);
        observed.push({
          scriptName: result.scriptName,
          selections: result.bindings.map((binding) => ({ label: binding.label, actual: binding.actual })),
        });
      } catch {
        // Left out deliberately: an unread target must not read as unchanged.
      }
    }
  }
  return observed;
}
```

- [ ] **Step 5: Call it before the first write**

In `main()`, insert this immediately **before** the existing
`await gotoChart(session.page, config.primaryChartUrl);` /
`await ensurePineEditor(session.page);` pair — not after it.

The helper walks the other layouts, so it leaves the page off the primary chart
with the Pine editor closed. Placed ahead of that pair, the existing navigation
restores exactly the state the save phase expects; placed after it, the first
`saveConsumerSource` would open on the wrong chart with no editor.

```ts
    // Before anything is written. After the first save, a difference could be
    // this run's own doing and proves nothing about a second writer.
    if (executionPlan.mode !== "verify-only") {
      const baselinePath = path.resolve(
        getFlag("--baseline", "artifacts/monitoring/previous/tradingview_consumer_bindings.json"),
      );
      let baseline: ObservedConsumer[] | null = null;
      try {
        const parsed = JSON.parse(fs.readFileSync(baselinePath, "utf-8"));
        baseline = (parsed?.tradingViewObserved?.bindings ?? null) as ObservedConsumer[] | null;
      } catch {
        baseline = null;
      }
      report.outOfBandDrift = compareAgainstBaseline({
        observed: await observeBindingsOnly(session, config),
        baseline,
        expectedScriptNames: config.verifyTargets.map((target) => target.scriptName),
      });
      if (report.outOfBandDrift.status !== "clean") {
        console.warn(`[rollout] out-of-band drift ${report.outOfBandDrift.status}: ${report.outOfBandDrift.reason}`);
      }
    }
```

- [ ] **Step 6: Gate `ok` on the verdict**

Find the assignment of `report.ok` in the `finally` block and add `report.outOfBandDrift.status === "clean"` as one more conjunct, with this comment above it:

```ts
      // A second writer touched the managed layouts since the last CI run, or
      // the comparison could not be made. The save is NOT withheld -- that
      // would freeze the consumers on an old pinned library while the producer
      // moves on (operator decision 2026-08-01) -- so this field carries the
      // red on its own. Never rely on another clause to catch it: an
      // out-of-band binding change leaves sources.drifted at 0.
```

- [ ] **Step 7: Register the new test file in all three places**

In `.github/workflows/tv-onboarding-packages.yml`, add `automation/tradingview/tests/tv_pre_mutation_observation.test.ts` to both `paths:` lists and to the `npx tsx --test …` run step.

Verify:
```bash
grep -c 'tv_pre_mutation_observation.test.ts' .github/workflows/tv-onboarding-packages.yml
```
Expected: `3`

- [ ] **Step 8: Run the tests**

Run:
```bash
npx tsx --test automation/tradingview/tests/tv_pre_mutation_observation.test.ts automation/tradingview/tests/tv_out_of_band_drift.test.ts
npx tsc --noEmit -p tsconfig.json
/Users/spreuss/Documents/skipp-algo/.venv/bin/python -m pytest tests/ -k workflow -q
```
Expected: TS tests PASS; `tsc` reports no errors; workflow tests PASS.

- [ ] **Step 9: Commit**

```bash
git add scripts/tv_batch_consumer_rollout.ts \
        automation/tradingview/tests/tv_pre_mutation_observation.test.ts \
        .github/workflows/tv-onboarding-packages.yml
git commit -m "feat(tv): measure out-of-band layout drift before the first mutation"
```

---

## Task 6: Fetch the baseline snapshot in CI

**Files:**
- Modify: `.github/workflows/tv-save-consumer-source.yml`
- Modify: `tests/test_workflow_tv_save_consumer_source_contract.py`

**Interfaces:**
- Consumes: the `--baseline` default path from Task 5.
- Produces: `artifacts/monitoring/previous/tradingview_consumer_bindings.json` inside the runner, or no file at all.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_workflow_tv_save_consumer_source_contract.py`:

```python
_BASELINE = "Fetch the published binding baseline"


def test_baseline_fetch_reads_the_published_branch_and_precedes_the_rollout() -> None:
    names = [step.get("name", "") for step in _steps()]
    assert _BASELINE in names, f"missing step: {_BASELINE}"
    rollout = next(
        i for i, s in enumerate(_steps()) if "scripts/tv_batch_consumer_rollout.ts" in s.get("run", "")
    )
    assert names.index(_BASELINE) < rollout

    step = next(s for s in _steps() if s.get("name") == _BASELINE)
    assert "bot/live-tradingview-bindings" in step["run"]
    assert "artifacts/monitoring/previous/tradingview_consumer_bindings.json" in step["run"]


def test_a_missing_baseline_does_not_fail_the_step() -> None:
    """An absent baseline is the "unknown" verdict, decided by the rollout.

    Failing here instead would turn a first-ever run, or a pruned branch, into
    a red step with no measurement behind it.
    """
    step = next(s for s in _steps() if s.get("name") == _BASELINE)
    assert "::warning::" in step["run"]
    assert "exit 1" not in step["run"]
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `/Users/spreuss/Documents/skipp-algo/.venv/bin/python -m pytest tests/test_workflow_tv_save_consumer_source_contract.py -k baseline -v`
Expected: FAIL — `missing step: Fetch the published binding baseline`

- [ ] **Step 3: Add the step**

In `.github/workflows/tv-save-consumer-source.yml`, insert immediately before the `- name: Detect R1-attested sources this save would un-attest` step:

```yaml
      # The comparison baseline is the observation the LAST run published to
      # bot/live-tradingview-bindings. Fetched over the API rather than with
      # git: the checkout above sets persist-credentials: false, so no
      # credential is available to git here.
      #
      # A missing baseline is not an error. It is the "unknown" verdict, and the
      # rollout decides that -- a first run, or a pruned branch, must not fail a
      # step that has measured nothing.
      - name: Fetch the published binding baseline
        if: ${{ github.event_name != 'schedule' && github.event.inputs.verify_only != 'true' }}
        env:
          GH_TOKEN: ${{ github.token }}
          GH_REPO: ${{ github.repository }}
        run: |
          set -euo pipefail
          mkdir -p artifacts/monitoring/previous
          out="artifacts/monitoring/previous/tradingview_consumer_bindings.json"
          path="artifacts/monitoring/latest/tradingview_consumer_bindings.json"
          if gh api "repos/${GH_REPO}/contents/${path}?ref=bot/live-tradingview-bindings" \
               --jq '.content' 2>/dev/null | base64 -d > "${out}"; then
            echo "Baseline fetched: $(wc -c < "${out}") bytes"
          else
            rm -f "${out}"
            echo "::warning::No published binding baseline — out-of-band drift will report as unknown."
          fi
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `/Users/spreuss/Documents/skipp-algo/.venv/bin/python -m pytest tests/ -k workflow -q`
Expected: PASS

- [ ] **Step 5: Prove the fetch command works against the real branch**

Run locally:
```bash
gh api "repos/$(gh repo view --json nameWithOwner --jq .nameWithOwner)/contents/artifacts/monitoring/latest/tradingview_consumer_bindings.json?ref=bot/live-tradingview-bindings" \
  --jq '.content' | base64 -d | jq '{executionMode, observedAt, consumers: (.tradingViewObserved.bindings | length)}'
```
Expected: JSON with a non-zero `consumers` count. If it errors, the branch or path assumption in Task 5 is wrong — stop and re-check before continuing.

- [ ] **Step 6: Commit**

```bash
git add .github/workflows/tv-save-consumer-source.yml tests/test_workflow_tv_save_consumer_source_contract.py
git commit -m "feat(tv): fetch the published binding baseline before a mutating run"
```

---

## Task 7: Session-probe feasibility spike — STRUCK

Removed on 2026-08-02, before implementation, by operator decision.

The spike needed an authenticated TradingView session, and that only exists on
the operator's own machine (Chrome profile copy plus CDP export). Neither a CI
job nor a delegated agent can produce one -- and a probe session opened just to
ask who else is on the account is itself the second-writer pressure this plan
reduces.

The 2026-08-01 rejection of option D therefore stands, now as a recorded choice.
See the spec's Component 4 for what stays uncovered: an operator session that is
never declared through `TV_OPERATOR_ACTIVE` is invisible while it is open. A1
still catches what it wrote, on the next mutating run or scheduled verify.

Nothing in Tasks 1-6 depends on this task.

---

## Final verification

- [ ] **Step 1: Full guard**

Run: `PYTEST_ADDOPTS="-n 4" ./scripts/run_ledger_drift_guard.sh`
Expected: PASS. `-n auto` gets SIGKILLed on a 16 GB Mac; a phantom F is not a real failure.

- [ ] **Step 2: Full workflow selection**

Run: `/Users/spreuss/Documents/skipp-algo/.venv/bin/python -m pytest tests/ -k workflow -q`
Expected: PASS

- [ ] **Step 3: Complete TS test list**

Run the full `npx tsx --test …` command from `.github/workflows/tv-onboarding-packages.yml`, verbatim.
Expected: PASS, including both new files.

- [ ] **Step 4: Confirm nothing leaked into the repo tree**

Run: `git status --short`
Expected: clean. Three tests in this repo write into `governance/` and `artifacts/` via repo-relative defaults; a dirty tree here means one of them ran and left residue.

- [ ] **Step 5: Push and open the PR**

Push via `Bash` with `run_in_background: true`, then open the PR. Do not use `--no-verify`: an import-probe failure in the pre-push hook is load-induced, and the fix is to retry the push.
