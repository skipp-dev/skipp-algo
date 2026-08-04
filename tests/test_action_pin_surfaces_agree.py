"""Every surface that pins a GitHub Action must pin it to the SAME commit.

Measured 2026-08-04, from two independent failures on the same day:

* #4425 (the grouped action bump) moved ``actions/setup-python`` from v6.2.0 to
  v7.0.0 in all 64 workflows. It did NOT move
  ``.github/actions/setup-python-pinned/action.yml`` — the canonical composite
  several jobs run via ``uses: ./.github/actions/setup-python-pinned`` — because
  Dependabot's ``github-actions`` ecosystem scans ``.github/workflows/`` only.
  The PR would have left TWO setup-python versions in one CI, and nothing was
  red.
* ``.github/workflow-templates/`` pins
  ``astral-sh/setup-uv@caf0cab7a618c569241d31dcd442f54681755d39`` — v3.2.4,
  committed 2024-11-23 — while every workflow runs
  ``fac544c07dec837d0ccb6301d7b5580bf5edae39``, v8.2.0, 2026-06-03. Five majors
  and twenty months of drift, in files that get copied verbatim into new
  workflows.

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
    iter_workflow_files,
    iter_workflow_template_files,
)

_USES_RE = re.compile(r"^\s*-?\s*uses:\s*([^\s#'\"]+)")
_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


def _pins() -> list[tuple[Path, int, str, str]]:
    """``(path, lineno, owner/repo, ref)`` for every third-party ``uses:``.

    Local (``./…``) and Docker (``docker://…``) references are not pinnable
    against upstream and are excluded, matching the allowlist guard.
    """
    out: list[tuple[Path, int, str, str]] = []
    for path in iter_action_pin_surfaces():
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            match = _USES_RE.match(line)
            if not match:
                continue
            ref = match.group(1).strip().strip("'\"")
            if ref.startswith(("./", "../", "docker://")) or "@" not in ref:
                continue
            left, _, version = ref.partition("@")
            parts = left.split("/")
            owner_repo = f"{parts[0]}/{parts[1]}" if len(parts) >= 2 else left
            out.append((path, lineno, owner_repo, version))
    return out


def _rel(path: Path) -> str:
    return path.relative_to(REPO_ROOT).as_posix()


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

    assert len(workflows) >= 50, f"workflow corpus collapsed to {len(workflows)} files"
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
    for path, lineno, owner_repo, ref in _pins():
        by_action[owner_repo][ref].append(f"{_rel(path)}:{lineno}")

    # Guard the guard: if the corpora ever stop overlapping, every action is
    # pinned on exactly one surface, the comparison below is empty, and this
    # test reports green having compared nothing.
    shared = {action: refs for action, refs in by_action.items() if len(refs) >= 1}
    assert shared, "no action is pinned anywhere — nothing was compared"

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
