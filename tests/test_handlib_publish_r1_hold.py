"""Pin: the hand-lib repin path honours the R1 hold, fail-closed.

``repinAllConsumers`` rewrites every consumer ``.pine`` — including the
R1-attested companions, whose registered evidence describes their exact
committed content. The refresh path learned this on 2026-08-01/04 (#4284,
#4371: two killed attestations) and gained its hold step; the weekly hand-lib
publish (`pine-library-publish-handlibs.yml`) was a second writer on the same
files with no hold at all. The next ``smc_utils`` bump in a Sunday run would
have de-attested ``SMC_Event_Overlay.pine`` from the other side.

The wiring pinned here, each with the failure it prevents:

* the hold step runs the SAME module the refresh uses
  (``scripts/hold_r1_attested_sources`` — roster derived from the live
  rollout contract, no second list, fails closed on an empty roster), and it
  sits between the publish step and the PR step — after the last write to the
  tree, before anything reads it;
* the changed-set is measured in the hold step, on the post-hold tree — the
  publish step must NOT compute its own: measured pre-hold it counts diffs
  the hold takes back, and a run whose only edit was an attested companion
  would open an empty PR;
* the PR step is conditioned on the hold step's verdict, with no
  ``always()``/``failure()`` escape — a failed hold means the tree cannot be
  trusted, and no repin PR at all beats one that de-attests a companion;
* the PR body names what was held — a repin PR that silently omits two
  consumers reads as a bug, and the omission is the policy working.

The module's own behaviour (restore, roster derivation, empty-roster refusal)
is executed by ``tests/test_hold_r1_attested_sources.py``; this file pins the
composition, which is exactly what the module's tests cannot see.
"""

from __future__ import annotations

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "pine-library-publish-handlibs.yml"


def _steps() -> list[dict]:
    doc = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    return doc["jobs"]["publish"]["steps"]


def _step(steps: list[dict], name_prefix: str) -> dict:
    matches = [s for s in steps if str(s.get("name", "")).startswith(name_prefix)]
    assert matches, f"no step named {name_prefix!r} in {WORKFLOW.name}"
    return matches[0]


def test_hold_step_runs_the_shared_module_between_publish_and_pr() -> None:
    steps = _steps()
    names = [str(s.get("name", "")) for s in steps]
    publish_at = names.index("Ordered publish + repin")
    hold = _step(steps, "Hold R1-attested sources")
    hold_at = names.index(str(hold["name"]))
    pr_at = names.index("Open repin PR")
    assert publish_at < hold_at < pr_at, (
        "the hold must run after the last write to the tree (the publish "
        "step's repins) and before anything reads it (the PR step) — "
        f"got publish={publish_at}, hold={hold_at}, pr={pr_at}"
    )
    assert hold.get("id") == "r1_hold"
    assert "python3 -m scripts.hold_r1_attested_sources" in hold["run"], (
        "the hold must reuse the refresh's module — a reimplementation here "
        "would be a second roster to keep true"
    )
    assert "if" not in hold, (
        "the hold step must run unconditionally: every path that reaches the "
        "PR step must have passed through it"
    )


def test_changed_is_measured_after_the_hold_and_only_there() -> None:
    steps = _steps()
    hold = _step(steps, "Hold R1-attested sources")
    publish = _step(steps, "Ordered publish + repin")
    # The needle is the OUTPUT WRITE, not the substring: the publish step's
    # comments legitimately mention `changed=` when retelling the 2026-08-04
    # empty-$GITHUB_OUTPUT incident.
    write = 'echo "changed='
    assert write in hold["run"], "the post-hold tree decides what the PR carries"
    assert "handlib_release_manifest.json" in hold["run"], (
        "the manifest stays part of the changed-set (a manifest-only first "
        "run must still open its PR — see #4710)"
    )
    assert write not in publish["run"], (
        "two changed= computations are two truths; the publish step's was "
        "measured before the hold and counts diffs the hold takes back"
    )


def test_pr_step_reads_the_hold_verdict_and_cannot_outrun_a_failed_hold() -> None:
    steps = _steps()
    pr = _step(steps, "Open repin PR")
    condition = str(pr.get("if", ""))
    assert "steps.r1_hold.outputs.changed == 'true'" in condition, (
        "the PR step must consume the post-hold changed verdict"
    )
    assert "steps.publish.outputs.changed" not in condition, (
        "the pre-hold verdict is the one that opens empty or de-attesting PRs"
    )
    assert "always()" not in condition and "failure()" not in condition, (
        "a failed hold must block the PR: no repin PR at all beats one that "
        "de-attests a companion"
    )


def test_pr_body_names_the_held_companions() -> None:
    pr = _step(_steps(), "Open repin PR")
    assert "R1_HELD" in str(pr.get("env", {}).get("R1_HELD", "")) or "r1_hold.outputs.held" in str(
        pr.get("env", {}).get("R1_HELD", "")
    ), "the held roster must reach the PR step through env, not expansion into code"
    assert "R1 hold:" in pr["run"], (
        "the PR body must say the companions were held on purpose — a repin "
        "PR silently omitting two consumers reads as a bug"
    )
