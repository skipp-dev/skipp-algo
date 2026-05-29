"""File-level count ratchet for ``set +e`` in workflow ``run:`` scripts.

Background
==========

The 2026-05-28 silent-publish-skip post-mortem (PRs #2415, #2418, #2421,
#2426; tracking issue #2422) identified the ``set +e`` + captured-rc +
no downstream surfacing pattern as the dominant carrier of silent-skip
regressions. The repo currently contains ~420 ``set +e`` occurrences
across rendering/digest/cron workflows where fail-soft is the
intentional, well-understood style ("best-effort step in multi-step
rollup; each step uploads its own artefact even when peers fail").

A per-step surfacing requirement would force a ~400-step retrofit. This
test instead installs the proportionate ratchet:

* **Every workflow file that contains `set +e`** is pinned by file-level
  occurrence count.
* **New workflow files** introducing the pattern fail the test until
  added to ``_ALLOWED`` with a one-line rationale comment.
* **Existing files** whose count grows fail the test — the operator must
  either re-baseline (acknowledging the new silent-skip surface) or
  add ``::error::`` surfacing for the new occurrences.
* **Existing files** whose count drops fail the test too (drift in
  either direction) — but the fix is trivial: update the constant. This
  encourages cleanup PRs to stay honest.

Why file-level, not per-step?
-----------------------------

Per-step would require ~400 entries today and create review fatigue on
every digest workflow edit. File-level pin (cf. budget/ledger tests in
this repo) is the same pattern used for ``# noqa`` budgets, bare
``type: ignore`` budgets, etc. — surfaces the *class-level* risk
("silent-skip surface area is growing") without micromanaging every
historical step.

A future PR may add the per-step variant for **specific high-risk
workflows** (promotion-gate-daily.yml, f2-promotion-gate-daily.yml,
smc-library-refresh.yml). Until then, the corresponding workflow-shape
tests carry that responsibility individually.

Audit lineage: Bundle D from issue #2422.
"""

from __future__ import annotations

import re

import pytest

from tests._workflow_yaml import (
    WORKFLOWS_DIR,
    iter_steps,
    iter_workflow_files,
    load_workflow,
)

# Matches `set +e` at the start of a line in a shell script (any
# indentation). The only form ever used in this repo.
_SET_PLUS_E_RE = re.compile(r"(?m)^\s*set\s+\+e(?:\s|$)")


# Snapshot baseline captured 2026-05-29 during Bundle D from issue #2422.
# Format: ``filename -> total_set_plus_e_count``.
#
# Adding a new key (= a workflow gained the pattern for the first time)
# requires a one-line rationale here AND a `# silent-skip-ok: <why>`
# comment in the workflow alongside the first new occurrence.
#
# Mutating an existing value requires a CHANGELOG / PR-description note
# explaining whether the change is hardening (count down) or a deliberate
# new fail-soft surface (count up).
_ALLOWED: dict[str, int] = {
    # Daily heavy-compute crons with per-section fault tolerance.
    "c13-daily-cron.yml": 7,
    "drift-watchdog.yml": 1,
    # F2 promotion-gate cron: per-output-section fault tolerance plus
    # auto-revert / status-alert blocks that PR #2426 hardened to emit
    # ::error:: on failure. New occurrences in this file should follow
    # the PR #2426 pattern (capture rc, emit annotation, exit 0).
    "f2-promotion-gate-daily.yml": 7,
    "f2-weekly-digest.yml": 1,
    "feature-importance-daily.yml": 1,
    "fvg-quality-recal-shadow-daily.yml": 1,
    "g23-ab-watchdog.yml": 1,
    # Fault-tolerant rendering pipelines (Plan 2.8 digest family).
    # Every step is independent and uploads its own artefact; one
    # rendering failure must not cascade and hide successful peers.
    # The 382-count baseline for the weekly digest reflects ~50 small
    # rendering / metric / summary sub-steps each with its own
    # set +e | exit 0 envelope. Growth here is acceptable as long as the
    # individual step still uploads a marker artefact.
    "plan-2-8-monthly-digest.yml": 4,
    "plan-2-8-weekly-digest.yml": 382,
    # Promotion-gate daily: covered separately by issue #2422 finding A.
    # Count is the post-#2421 baseline.
    "promotion-gate-daily.yml": 2,
    "smc-databento-production-export-sharded.yml": 1,
    "smc-databento-production-export.yml": 1,
    "smc-deeper-integration-gates.yml": 1,
    # Library refresh: includes the F-V8-N1 preflight retry wrapper
    # (PR #2418) plus the breaking/gates capture blocks (PR #2415).
    "smc-library-refresh.yml": 3,
    "smc-live-newsapi-refresh.yml": 1,
    "smc-measurement-benchmark-rolling.yml": 5,
}


def _scan_inventory() -> dict[str, int]:
    """Return ``{filename: count}`` for every workflow with `set +e`."""
    observed: dict[str, int] = {}
    for wf in iter_workflow_files():
        data = load_workflow(wf)
        total = 0
        for _, step in iter_steps(data):
            run = step.get("run")
            if isinstance(run, str):
                total += len(_SET_PLUS_E_RE.findall(run))
        if total:
            observed[wf.name] = total
    return observed


def test_workflows_directory_exists() -> None:
    files = iter_workflow_files()
    assert len(files) >= 5, f"unexpectedly few workflow files: {len(files)}"


def test_set_plus_e_inventory_matches_allowed() -> None:
    observed = _scan_inventory()

    extra_files = sorted(set(observed) - set(_ALLOWED))
    missing_files = sorted(set(_ALLOWED) - set(observed))
    drift = {
        name: (observed[name], _ALLOWED[name])
        for name in sorted(set(observed) & set(_ALLOWED))
        if observed[name] != _ALLOWED[name]
    }

    msgs: list[str] = []
    if extra_files:
        details = "\n".join(f"  {f}: {observed[f]}" for f in extra_files)
        msgs.append(
            "NEW workflow(s) introduced `set +e` without an allowlist entry:\n"
            f"{details}\n"
            "Every `set +e` is a silent-skip risk surface (issue #2422 / "
            "post-mortem 2026-05-28).\n"
            "Either add to _ALLOWED with a rationale comment, OR refactor the "
            "step to use `set -e` + explicit rc capture + `::error::`."
        )
    if missing_files:
        msgs.append(
            f"Workflow(s) no longer contain `set +e`: {missing_files}. "
            "Remove the entry from _ALLOWED (good news — silent-skip surface shrank)."
        )
    if drift:
        details = "\n".join(
            f"  {f}: pinned {pinned}, observed {actual} "
            f"({'+' if actual > pinned else ''}{actual - pinned})"
            for f, (actual, pinned) in drift.items()
        )
        msgs.append(
            "`set +e` count drift:\n"
            f"{details}\n"
            "Update _ALLOWED with rationale (count up = new fail-soft surface "
            "— justify; count down = cleanup — celebrate)."
        )

    assert not msgs, "\n\n".join(msgs)


def test_set_plus_e_total_count_pin() -> None:
    """Aggregate tripwire that catches drift across multiple files at once."""
    expected = sum(_ALLOWED.values())
    actual = sum(_scan_inventory().values())
    assert actual == expected, (
        f"`set +e` total drift: pinned {expected}, observed {actual} "
        f"({'+' if actual > expected else ''}{actual - expected}). "
        "See test_set_plus_e_inventory_matches_allowed for per-file detail."
    )


@pytest.mark.parametrize("name,count", sorted(_ALLOWED.items()))
def test_each_allowed_workflow_file_exists(name: str, count: int) -> None:
    assert (WORKFLOWS_DIR / name).is_file(), (
        f"allowlist references missing workflow: {name}"
    )
    assert count >= 1, (
        f"{name}: pinned count must be >= 1 (or remove the entry entirely)"
    )
