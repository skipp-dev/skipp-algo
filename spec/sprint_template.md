# Sprint Template — `<C-id>` `<short title>`

> Copy this file to `spec/sprints/<C-id>_<slug>.md` at sprint start.
> Replace every `<…>` placeholder. Delete sections you genuinely don't need
> (and explain why in the rationale block); do not delete a section because
> it's inconvenient.

## 0. Meta

- **Sprint id**: `<C-id, e.g. C2>`
- **Title**: `<one line>`
- **Owner**: `<solo>`
- **Working days budget**: `<N Werktage>`
- **Hard stop date (calendar)**: `<YYYY-MM-DD>`
- **Depends on**: `<previous sprint id(s) that MUST be merged first>`
- **Blocks**: `<sprint id(s) that cannot start without this>`

## 1. Outcome (one paragraph)

`<What does the world look like when this sprint is done? Concrete,
verifiable. NOT "design doc for X" but "X.py exists, gated by N tests,
wired into pipeline Y, evidence at Z.">`

## 2. Day 1 — Inventur (verbindlich)

> **Pflichtschritt.** Vor jeder neuen Datei: `python scripts/sprint_inventory.py <topic>`.
> Output in `spec/sprints/<C-id>_inventory.md` ablegen.
>
> Aus Erfahrung: 30–50 % eines C-Sprints ist Erweiterung bestehender
> Module, nicht Greenfield. Diese Inventur spart die Hälfte des Build-Blocks.

- Topic-Keywords für `sprint_inventory.py`: `<keyword1, keyword2, …>`
- Existing modules to extend: `<list>`
- Existing tests to extend: `<list>`
- Truly new files (justify each): `<list>`

## 3. Tasks T1–T7

> Use exactly these 7 task slots. Combine or leave empty if needed,
> but keep the numbering — it makes mid-sprint diff-against-plan trivial.

| # | Task | Werktage | Stop-Kriterium | Evidenz-Marker |
|---|------|----------|----------------|----------------|
| T1 | `<inventory + scaffold>` | 0.5 | `<…>` | `<file/path or test name>` |
| T2 | `<core build, part 1>` | `<…>` | `<…>` | `<…>` |
| T3 | `<core build, part 2>` | `<…>` | `<…>` | `<…>` |
| T4 | `<integration / wiring>` | `<…>` | `<…>` | `<…>` |
| T5 | `<tests + ledger pins>` | `<…>` | `<…>` | `<…>` |
| T6 | `<docs + CHANGELOG>` | `<…>` | `<…>` | `<…>` |
| T7 | `<release/merge>` | `<…>` | `<…>` | PR # / merged-at |

## 4. Stop-Kriterien (sprint-level)

> **2-Iterations-Limit.** Wenn nach 2 Anläufen ein Stop-Kriterium NICHT
> erfüllt ist: Sprint stoppen, in `docs/reviews/<C-id>_stop.md` dokumentieren,
> nicht endlos weiteroptimieren.

- [ ] All T1–T7 tasks have an evidence marker that an outsider can verify.
- [ ] No `pytest` failures on `-n auto --dist=loadfile`.
- [ ] Coverage ratchet honored (see `/memories/repo/coverage-ratchet-protocol.md`).
- [ ] `<sprint-specific gate, e.g. "C2 walk-forward report exists at docs/walk_forward/<C-id>.md">`
- [ ] `<sprint-specific gate>`

## 5. Definition of Done

- [ ] PR opened, auto-merge enabled (`gh pr merge --auto --squash`).
- [ ] CHANGELOG `[Unreleased]` entry under appropriate heading.
- [ ] Sprint summary written into `/memories/repo/<sprint-id>-shipped.md`.
- [ ] `spec/sprints/<C-id>_inventory.md` retained as historical record
      (do not delete after sprint).
- [ ] Stop-criterion-hits documented even if sprint passed (preserve why
      a path was abandoned).

## 6. Out of scope (explicit)

> Listing what is NOT in this sprint. Reduces mid-sprint scope drift.

- `<…>`

## 7. Mid-sprint re-prioritization rule

A sprint plan is verbindlich, sobald merged. Re-prioritization mid-sprint
is allowed ONLY when a Stop-Kriterium hits. In that case: stop, document,
move to the next planned sprint or to a documented pivot. Do NOT silently
extend.
