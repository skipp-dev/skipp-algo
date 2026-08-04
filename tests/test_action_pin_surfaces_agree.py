"""Every surface that pins a GitHub Action must pin it to the SAME commit.

Measured 2026-08-04, from two independent failures on the same day:

* In #4425 (the grouped action bump) DEPENDABOT'S OWN COMMIT (753b7a33e) moved
  ``actions/setup-python`` from v6.2.0 to v7.0.0 in the 18 workflows that
  reference it, and did NOT move
  ``.github/actions/setup-python-pinned/action.yml`` — the canonical composite
  several jobs run via ``uses: ./.github/actions/setup-python-pinned`` — because
  its ``github-actions`` ecosystem scans ``.github/workflows/`` only. That would
  have left TWO setup-python versions in one CI, and nothing was red.

  Stated precisely 2026-08-05, after a review caught the earlier wording here
  claiming the MERGED #4425 left the split in place: it does not. A companion
  commit in the same PR repaired the composite and both templates by hand. The
  blind spot being pinned is Dependabot's, not the merged result's — which is
  exactly why it needs a guard rather than a one-off fix.
* ``.github/workflow-templates/`` pinned
  ``astral-sh/setup-uv@caf0cab7a618c569241d31dcd442f54681755d39`` — v3.2.4,
  committed 2024-11-23 — while the workflows ran v8.2.0 (2026-06-03), and then
  v9.0.0 (2026-07-21) once #4425 landed. Five majors and twenty months of drift,
  in files copied verbatim into new workflows.

  Note for whoever bumps actions next: templates are neither ``.github/workflows``
  nor an ``action.yml``, so no Dependabot directory entry can reach them. They
  stay a manual companion edit on every actions bump — and this guard is what
  turns "forgot" into a red check instead of silent rot.

Why the existing guards could not see either. ``test_gha_action_allowlist.py``
asks the right questions — is it SHA-pinned, is the owner trusted, is the SHA on
the approved set — but only of ``iter_workflow_files()``, which is
``.github/workflows/*.y{a,}ml`` and nothing else.
``test_workflow_python_version_pinned.py`` does read the composite, and pins
``python-version: "3.12"`` inside it, but selects the step with
``startswith("actions/setup-python@")`` — a filter that accepts a 40-hex SHA, a
mutable tag, and a SHA that does not exist upstream, all the same.

So this guard asks a question none of them do: not "is this pin well-formed"
but "do the surfaces AGREE". That is the question a partial bump fails.
"""

from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path

from tests._workflow_yaml import (
    REPO_ROOT,
    iter_action_pin_surfaces,
    iter_composite_action_files,
    iter_uses,
    iter_workflow_files,
    iter_workflow_template_files,
)

_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


def _pins() -> list[tuple[Path, int, str, str]]:
    """``(path, lineno, owner/repo, ref)`` for every third-party ``uses:``.

    Local (``./…``) and Docker (``docker://…``) references are not pinnable
    against upstream and are excluded, matching the allowlist guard.
    """
    out: list[tuple[Path, int, str, str]] = []
    for path, lineno, ref in iter_uses(iter_action_pin_surfaces()):
        if ref.startswith(("./", "../", "docker://")) or "@" not in ref:
            continue
        left, _, version = ref.partition("@")
        parts = left.split("/")
        owner_repo = f"{parts[0]}/{parts[1]}" if len(parts) >= 2 else left
        out.append((path, lineno, owner_repo, version))
    return out


def _rel(path: Path) -> str:
    return path.relative_to(REPO_ROOT).as_posix()


def _surface_of(path: Path) -> str:
    """Which of the three corpora a file belongs to.

    Membership is asked of the corpus functions rather than pattern-matched on
    the path, so a directory move relocates this with them instead of silently
    bucketing every file as "other".
    """
    if path in set(iter_workflow_files()):
        return "workflows"
    if path in set(iter_composite_action_files()):
        return "composite-actions"
    if path in set(iter_workflow_template_files()):
        return "workflow-templates"
    raise AssertionError(f"{_rel(path)} is on no known pin surface")


def test_all_three_surfaces_are_actually_scanned() -> None:
    """The premise, asserted — a moved directory must not silently empty this.

    Every check below is a loop over a discovered corpus. If a rename made any
    of the three globs return nothing, the whole file would report green while
    guarding one surface fewer than it claims, which is the precise shape it
    exists to catch.
    """
    workflows = iter_workflow_files()
    composites = iter_composite_action_files()
    templates = iter_workflow_template_files()

    assert len(workflows) >= 60, (
        f"workflow corpus collapsed to {len(workflows)} files (68 on 2026-08-04)"
    )
    assert composites, (
        "no composite action found under .github/actions/. Either they moved — "
        "and this guard is now blind to the surface it was written for — or "
        "they are gone and this file should go with them."
    )
    assert templates, (
        "no workflow template found under .github/workflow-templates/. Same "
        "reasoning: a silently empty corpus is indistinguishable from a clean one."
    )
    assert _pins(), "no `uses:` pin discovered on ANY surface — the parser is broken"

    # Files are not pins. A corpus can return documents and still contribute
    # nothing to compare, which reads exactly like a clean surface.
    contributing = {_surface_of(path) for path, _, _, _ in _pins()}
    missing = {"workflows", "composite-actions", "workflow-templates"} - contributing
    assert not missing, (
        "these surfaces were scanned but contributed no third-party `uses:` pin "
        f"at all, so every check below is silent about them: {sorted(missing)}"
    )


def test_every_pin_outside_workflows_is_sha_pinned() -> None:
    """The allowlist guard's rule, applied to the surfaces it cannot reach.

    ``test_gha_action_allowlist.py`` enforces this for ``.github/workflows/``
    only. A composite action or a template pinning a mutable tag is the same
    supply-chain exposure — a tag can be repointed at any commit — on a file the
    existing guard never opens.
    """
    workflow_paths = set(iter_workflow_files())
    violations = [
        f"{_rel(path)}:{lineno}: {owner_repo}@{ref} is not a 40-char SHA"
        for path, lineno, owner_repo, ref in _pins()
        if path not in workflow_paths and not _SHA_RE.match(ref)
    ]
    assert not violations, (
        "action reference(s) outside .github/workflows/ are not SHA-pinned, so "
        "a repointed tag would change what CI runs without any diff here:\n  "
        + "\n  ".join(violations)
    )


def test_an_action_pinned_on_several_surfaces_uses_one_commit() -> None:
    """The one that a partial bump fails.

    A grouped Dependabot update moves the workflows and leaves composites and
    templates behind, because it does not scan them. Nothing else in this repo
    compares the two, so the split merges green and CI quietly runs two
    versions of the same action.
    """
    by_action: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    surfaces_of: dict[str, set[str]] = defaultdict(set)
    for path, lineno, owner_repo, ref in _pins():
        by_action[owner_repo][ref].append(f"{_rel(path)}:{lineno}")
        surfaces_of[owner_repo].add(_surface_of(path))

    # Guard the guard — and the first attempt at this did NOT guard, which is
    # worth recording because it is the very class this file exists for. It read
    #
    #     shared = {a: refs for a, refs in by_action.items() if len(refs) >= 1}
    #     assert shared, "no action is pinned anywhere"
    #
    # `by_action` is a defaultdict filled only by `append`, so every value has
    # at least one ref: the filter was universally true, `shared` WAS
    # `by_action`, and the assertion reduced to `assert _pins()` — already made
    # above. It also counted the wrong thing: `refs` is keyed by COMMIT, so
    # `>= 2` there is the failure condition, not the coverage condition. A
    # review demonstrated it 2026-08-04 by renaming the owners in the composite
    # and both templates until nothing overlapped: the test passed having
    # performed zero comparisons.
    #
    # What has to be non-empty is the set of actions pinned on MORE THAN ONE
    # SURFACE, because those are the only ones this loop can say anything about.
    cross_surface = sorted(a for a, s in surfaces_of.items() if len(s) >= 2)
    assert len(cross_surface) >= 3, (
        "fewer than three actions are pinned on more than one surface, so this "
        "comparison is nearly empty and cannot fail for the reason it exists. "
        "On 2026-08-04 there were four — actions/checkout, actions/setup-python, "
        "actions/upload-artifact, astral-sh/setup-uv. If a surface legitimately "
        f"stopped sharing actions, lower this floor deliberately. Got: {cross_surface}"
    )

    divergent: list[str] = []
    for action, refs in sorted(by_action.items()):
        if len(refs) < 2:
            continue
        detail = "; ".join(
            f"{ref[:10]} at {', '.join(sorted(sites)[:3])}"
            + (f" (+{len(sites) - 3} more)" if len(sites) > 3 else "")
            for ref, sites in sorted(refs.items())
        )
        divergent.append(f"{action}: {len(refs)} different commits -> {detail}")

    assert not divergent, (
        "the same action is pinned to different commits on different surfaces. "
        "Dependabot scans .github/workflows/ only, so a grouped bump moves the "
        "workflows and leaves .github/actions/ and .github/workflow-templates/ "
        "behind — CI then runs two versions of one action, and until this guard "
        "existed nothing said so:\n  " + "\n  ".join(divergent)
    )
