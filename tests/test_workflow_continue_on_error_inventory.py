"""Inventory pin for ``continue-on-error: true`` in GitHub Actions workflows.

Background
==========

Audit `docs/audits/smc-system-review-2026-04-24.md` (M-2) flagged
``continue-on-error: true`` as a silent-degradation surface. The original
report listed only 2 hits (newsapi-refresh + library-refresh) but a fuller
sweep found 12 hits across 6 workflows. This test pins the **exact**
allowed inventory.

Failure semantics
=================

Adding a new ``continue-on-error: true`` line — or removing an existing one
— forces an explicit decision: update the ``_ALLOWED`` map below with a
short rationale comment in the PR description. This prevents silent-fail
patterns from spreading without review.

Note: The test does **not** demand that the workflow file itself carry an
inline comment (YAML noise). The single source of truth is this test.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS_DIR = REPO_ROOT / ".github" / "workflows"

# Match ``continue-on-error: true`` — optionally followed by an inline
# ``# ...`` rationale comment on the same line. The previous strict
# ``stripped == "continue-on-error: true"`` check silently skipped sites
# carrying a trailing comment (Copilot review of PR #1939). Anchored to
# end-of-line so ``continue-on-error: false`` and templated variants
# (``${{ ... }}``) are rejected.
_COE_LINE_RE = re.compile(r"^continue-on-error:\s+true(?:\s+#.*)?$")

# Allowed continue-on-error sites: workflow-relative-path -> set of 1-based line numbers.
# Each entry is intentionally explicit; do NOT collapse with wildcards.
# Adding/removing lines here MUST be paired with a CHANGELOG entry that
# justifies the silent-fail tolerance (typically: best-effort notification
# step, optional gate, or non-blocking observability hop).
_ALLOWED: dict[str, frozenset[int]] = {
    # Best-effort live news refresh: NewsAPI 5xx is tolerated to keep cron green.
    # Rebaselined 2026-05-02: 107 → 111 (+4) after upstream env edit.
    # F-V4-B4 (2026-05-02): 111 → 113 (+2) after actions/upload-artifact@v4 → @v7 fleet bump.
    # F-V4-A2 (2026-05-01, rebased 2026-05-02): 113 → 114 (+1) after PYTHONUNBUFFERED env addition.
    # F-V?-A2 cascade (2026-05-03): 114 → 109 (-5) after PYTHONUNBUFFERED dedup (PR #2033) trimmed duplicate env keys across the workflow.
    "smc-live-newsapi-refresh.yml": frozenset({109}),
    # Library refresh: 6 best-effort hops (gates probe, TV publish, telegram pings).
    # Lines 165 → 166 (alerts dispatch), 376 → 303 sequence shifted by upstream
    # rearrangement (PR #1937 cascade), and a NEW best-effort hop at 303 added
    # by the "Refresh release reference artifacts (best-effort)" step that
    # tolerates a cold producer cache (M-1 marker present, advisory in name).
    # Lines 416/642/785/805 → 418/644/787/807 (+2 each) due to the marker comment
    # and renamed step name above.
    # Rebaselined 2026-05-02 after PR #2028 composite migration (setup-python-pinned)
    # which added 7 lines to the affected jobs:
    # 172→179, 309→316, 424→431, 650→670, 793→813, 813→833.
    # F-V4-B4 (2026-05-02): bumped after upload-artifact@v4 → @v7 fleet migration:
    # 179→197, 316→339, 431→454, 670→693, 813→836, 833→856.
    # F-V4-A4 (2026-05-02): hygiene intent comments shifted 5 sites by +2:
    # 339→341, 454→456, 693→695, 836→838, 856→858 (197 unchanged).
    # F-V4-J3 (2026-05-01, rebased 2026-05-02): workflow_run trigger +
    # job-level `if:` guard added 14 lines: 197→211, 341→355, 456→470,
    # 695→709, 838→852, 858→872.
    # F-V5-D2 (2026-05-02): artifact-handoff bumps to 216, 381, 496, 735, 878, 898.
    # F-V4-A2 (PR #1985, rebased 2026-05-02): PYTHONUNBUFFERED env added
    # 1 more line each → 217, 382, 497, 736, 879, 899.
    # F-V?-A2 cascade (2026-05-03): -5 each after PYTHONUNBUFFERED dedup (PR #2033).
    # Audit unbreaker (2026-05-03): -3 each after removing the dup ref-less
    # `concurrency:` block + lead-in comment that YAML last-wins overrode the
    # per-ref F-V8-C3.1-D guard.
    # F-V8-C4 (2026-05-08): -1 each after cron restructure 4×→2× (consumer
    # cron block lost 4 entries but gained a 6-line rationale comment, net -1).
    "smc-library-refresh.yml": frozenset({208, 373, 488, 727, 870, 890}),
    # Deeper integration gates: 2 advisory-only probes.
    # Rebaselined 2026-05-02 after PR #2028 composite migration: 69→73, 113→117 (+4 each).
    # F-V4-B4 (2026-05-02): 73→74, 117→118 (+1 each) after @v7 fleet bump.
    # F-V4-A4 (2026-05-02): 118 → 120 (+2) after hygiene intent comment.
    # F-V4-A2 (2026-05-01, rebased 2026-05-02): 74→75, 120→121 (+1 each) after PYTHONUNBUFFERED.
    # F-V?-A2 cascade (2026-05-03): -5 each after PYTHONUNBUFFERED dedup (PR #2033).
    "smc-deeper-integration-gates.yml": frozenset({70, 116}),
    # Weekly digest: 3 best-effort delivery hops.
    # Rebaselined 2026-05-02: 447→451, 664→668, 943→947 (+4 each).
    # F-V4-B4 (2026-05-02): 451→458, 668→675, 947→954 (+7 each) after @v7 fleet bump.
    # F-V4-A2 (2026-05-01, rebased 2026-05-02): +1 each after PYTHONUNBUFFERED.
    # F-V?-A2 cascade (2026-05-03): -5 each after PYTHONUNBUFFERED dedup (PR #2033).
    "plan-2-8-weekly-digest.yml": frozenset({456, 673, 952}),
    # Release gates: 1 advisory metric collection hop.
    # Rebaselined 2026-05-02: 173→177 (+4).
    # F-V4-B4 (2026-05-02): 177 → 178 (+1) after @v7 fleet bump.
    # F-V4-A4 (2026-05-02): 178 → 179 (+1) after hygiene intent comment.
    # F-V4-A2 (2026-05-01, rebased 2026-05-02): 179 → 180 (+1) after PYTHONUNBUFFERED.
    # F-V?-A2 cascade (2026-05-03): 180 → 175 (-5) after PYTHONUNBUFFERED dedup (PR #2033).
    "smc-release-gates.yml": frozenset({175}),
    # Drift watchdog: red verdict is intentionally non-fatal so the follow-up
    # step can convert it into a GitHub issue (silent-fail by design — see C9/T4).
    # Line shifted 52 → 54 after adding CONTINUE-ON-ERROR-INTENTIONAL marker comment
    # (PR #333 Copilot review on c13-daily-cron — marker discipline test).
    # Rebaselined 2026-05-02: 54→60 (+6).
    # F-V4-B4 (2026-05-02): 60 → 67 (+7) after @v7 fleet bump.
    # F-V3-12 (PR #1982, 2026-05-02): +2 from new live-window header comment → 67 → 69.
    # F-V4-A2 (2026-05-01, rebased 2026-05-02): 69 → 73 (+4) after PYTHONUNBUFFERED env block addition.
    # F-V?-A2 cascade (2026-05-03): 73 → 69 (-4) after PYTHONUNBUFFERED dedup (PR #2033).
    "drift-watchdog.yml": frozenset({69}),
    # C13 daily-cron: 4 best-effort steps so partial failures still upload
    # artefacts and let the issue-opener step report exactly which step
    # failed; soft-skip rc=78 paths are also gated through these.
    # Lines 109/124/148 → 119/134/158 (+10) after wiring T8.3 imbalance
    # index gate into Step 1's run block (PR #333 follow-up).
    # Rebaselined 2026-05-02 after PR #2028 composite migration:
    # 90→95, 119→124, 134→139, 158→163, 175→180, 202→207 (+5 each).
    # F-V3-15 (PR #1982, 2026-05-02): added Step 1b backfill-progress
    # advisory + 2-line header comment → existing 6 entries shift +2 (Step 1)
    # and +32 (Steps 2–5b after step1b's 30-line block); new Step 1b at 133.
    # F-V4-A2 (2026-05-01, rebased 2026-05-02): +4 each after PYTHONUNBUFFERED env block.
    # F-V?-A2 cascade (2026-05-03): -4 each after PYTHONUNBUFFERED dedup (PR #2033).
    # Audit unbreaker (2026-05-03): +3 to all entries below the new
    # `# CONTINUE-ON-ERROR-INTENTIONAL:` marker re-anchored on Step 1b
    # backfill_progress (line 97 entry is BEFORE the marker, unshifted).
    "c13-daily-cron.yml": frozenset({97, 136, 159, 174, 198, 215, 242}),
    # Producer cache: second save under the date-only canonical key is best-effort
    # because actions/cache rejects re-writes for an existing key (benign 409).
    # Surfaced by PR-D8 (Copilot review of PR #1939) — was previously invisible
    # to the inventory because of the trailing rationale comment on the same line.
    # Rebaselined 2026-05-02 after PR #2028 composite migration: 169→177 (+8).
    # F-V4-B4 (2026-05-02): 177 → 199 (+22) after @v7 fleet bump.
    # F-V5-D2 (2026-05-02): removed entry — PR #2014 dropped the actions/cache
    # producer step entirely (cache→artifact handoff migration). PYTHONUNBUFFERED
    # from PR #1985 still applies to the workflow but no continue-on-error remains.
}


def _scan_workflow(path: Path) -> frozenset[int]:
    """Return the set of 1-based line numbers carrying ``continue-on-error: true``."""
    hits: set[int] = set()
    for idx, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        # Match ``continue-on-error: true`` ignoring leading whitespace AND any
        # trailing inline ``# ...`` comment. PR-D8 hardening (Copilot review of
        # PR #1939): the previous strict ``stripped == "continue-on-error: true"``
        # match silently dropped sites that carried a trailing rationale comment
        # on the same line, e.g.
        #     continue-on-error: true   # second save with identical date key
        # which left the entire workflow out of the inventory ledger.
        # Reject ``continue-on-error: false`` and templated variants by anchoring
        # the regex to ``true`` followed by end-of-line, whitespace, or ``#``.
        stripped = raw.strip()
        if stripped.startswith("#"):
            continue
        if _COE_LINE_RE.match(stripped):
            hits.add(idx)
    return frozenset(hits)


def _all_workflows() -> list[Path]:
    return sorted(WORKFLOWS_DIR.glob("*.yml")) + sorted(WORKFLOWS_DIR.glob("*.yaml"))


def test_workflows_directory_exists() -> None:
    """Sanity: the workflows directory must be present."""
    assert WORKFLOWS_DIR.is_dir(), f"missing workflows dir: {WORKFLOWS_DIR}"
    files = _all_workflows()
    assert len(files) >= 5, f"unexpectedly few workflow files: {len(files)}"


def test_continue_on_error_inventory_matches_allowed() -> None:
    """Pin the exact set of ``continue-on-error: true`` lines per workflow."""
    observed: dict[str, frozenset[int]] = {}
    for wf in _all_workflows():
        hits = _scan_workflow(wf)
        if hits:
            observed[wf.name] = hits

    extra_files = set(observed) - set(_ALLOWED)
    missing_files = set(_ALLOWED) - set(observed)

    assert not extra_files, (
        f"NEW workflow(s) introduced continue-on-error: true: {sorted(extra_files)}. "
        "Update _ALLOWED in this test with rationale, or remove the silent-fail."
    )
    assert not missing_files, (
        f"Workflow(s) no longer carry continue-on-error: {sorted(missing_files)}. "
        "Remove the entry from _ALLOWED."
    )

    diffs: list[str] = []
    for name, allowed_lines in _ALLOWED.items():
        seen = observed[name]
        added = seen - allowed_lines
        removed = allowed_lines - seen
        if added or removed:
            diffs.append(
                f"  {name}: added={sorted(added)} removed={sorted(removed)} "
                f"(seen={sorted(seen)}, allowed={sorted(allowed_lines)})"
            )
    assert not diffs, (
        "continue-on-error inventory drift:\n" + "\n".join(diffs)
        + "\nUpdate _ALLOWED with rationale, or revert the workflow change."
    )


def test_continue_on_error_count_pin() -> None:
    """Belt-and-braces: total count must equal sum of _ALLOWED."""
    expected = sum(len(v) for v in _ALLOWED.values())
    actual = sum(len(_scan_workflow(wf)) for wf in _all_workflows())
    assert actual == expected, (
        f"continue-on-error total drift: expected {expected}, observed {actual}. "
        "See per-file test for details."
    )


@pytest.mark.parametrize("name,lines", sorted(_ALLOWED.items()))
def test_each_allowed_workflow_file_exists(name: str, lines: frozenset[int]) -> None:
    """Per-file sanity that the allowlist references real files."""
    assert (WORKFLOWS_DIR / name).is_file(), f"allowlist references missing workflow: {name}"
    assert lines, f"empty allowlist for {name} — remove the key entirely"
