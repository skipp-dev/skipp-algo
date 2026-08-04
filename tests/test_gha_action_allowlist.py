"""Defense-pin: GitHub Actions action-reference allowlist.

Every ``uses: <owner>/<repo>@<ref>`` on ANY of this repo's three action-pin
surfaces — ``.github/workflows/``, ``.github/actions/``,
``.github/workflow-templates/`` — MUST be either:

1. SHA-pinned (40-char hex), OR
2. on the frozen trusted-publisher allowlist below.

Local actions (``./...``) and Docker actions (``docker://...``) are
exempt.

Rationale: prevents drive-by supply-chain attacks via tag-mutation on
unvetted third-party actions. The allowlist is intentionally tiny —
adding a new third-party action requires updating this ledger.

Note what rule 1 does and does not say, because it looks like a hole and is
not one: a 40-hex SHA from an ARBITRARY owner passes, allowlist or no. That is
deliberate — a SHA cannot be repointed, so tag-mutation, the threat this file
names, does not apply to it. Measured 2026-08-04 for the avoidance of doubt:
``uses: evilcorp/totally-fake@deadbeef…`` passes identically in a workflow and
in a composite action, so it is a repo-wide policy choice and not a gap in any
one surface. Requiring the allowlist for SHA pins too would be a real policy
change and belongs in its own PR, not in a widening.

Defense-only — no production changes.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from tests._workflow_yaml import iter_action_pin_surfaces, iter_uses

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS_DIR = ROOT / ".github" / "workflows"

# Frozen trusted-publisher allowlist. Every entry is "<owner>/<repo>"
# (without sub-path). Sub-paths like ``actions/cache/restore`` collapse
# to their owner/repo prefix ``actions/cache``.
_ALLOWLIST_OWNER_REPOS: frozenset[str] = frozenset(
    {
        "actions/attest-build-provenance",
        "actions/cache",
        "actions/checkout",
        "actions/download-artifact",
        "actions/github-script",
        "actions/setup-node",
        "actions/setup-python",
        "actions/upload-artifact",
        "astral-sh/setup-uv",
        "dawidd6/action-download-artifact",
    }
)

_SHA_RE = re.compile(r"^[0-9a-f]{40}$")

# Approved-SHA drift guard (zero-network).
#
# The format-only SHA check above cannot tell a *resolvable* pin from a
# typo'd / hallucinated / upstream-rebased 40-hex string. On 2026-06-03 a
# third, divergent `actions/setup-python` pin
# (e348410e00f449f3bb50f72fda1d4f7600fc1b04, labelled "v6.0.0") was
# introduced next to the two established pins. It is a 40-char hex, so the
# allowlist passed at PR time — but the SHA does not exist upstream
# (HTTP 422), so every run that reached it failed with
# "Unable to resolve action ... unable to find version". credential-health
# and workflow-freshness-monitor both broke (run 26880387376 et al.).
#
# This guard freezes the *exact* set of SHAs each runtime-installing action
# may pin to. Any new pin must be added here deliberately — which forces a
# human (or this agent) to verify the SHA resolves before it can land,
# catching the divergence at PR time WITHOUT a network call. To add a
# legitimately bumped pin: confirm `gh api repos/<owner>/<repo>/commits/<sha>`
# resolves, then add it below.
_APPROVED_ACTION_SHAS: dict[str, frozenset[str]] = {
    "actions/setup-python": frozenset(
        {
            # v5 (a26af69be…, Node-20) retired 2026-06-06: Node-20 actions are
            # deprecated (force-disabled 2026-06-16, removed 2026-09-16). All
            # workflows pinned v6 (Node-24) from then until 2026-08-04.
            #
            # v6 (a309ff8b4…, v6.2.0) → v7.0.0 on 2026-08-04 with #4425.
            # Verified as this ledger's own docstring requires, BEFORE the pin
            # was written here: `gh api repos/actions/setup-python/commits/
            # 5fda3b95a4…` resolves, and `git/refs/tags` puts BOTH `v7` and
            # `v7.0.0` on exactly that commit. `action.yml` at the new SHA still
            # declares `using: node24`, so the Node-24 property this set was
            # rebuilt for in June survives the bump. The only input v7 drops is
            # `pip-install`, which no workflow in this repo passes (measured
            # across all 68).
            "5fda3b95a4ea91299a34e894583c3862153e4b97",  # v7 (Node-24)
        }
    ),
}


def _iter_workflow_files() -> list[Path]:
    """Every file in this repo that pins an action, from the shared helper.

    Was a private duplicate of ``_workflow_yaml.iter_workflow_files`` (verified
    2026-07-15: both return the identical 62 files). Using the shared corpus is
    what makes this guard DERIVABLE — the required-path rule keys off the
    IMPORT of ``tests._workflow_yaml``, so a PR can no longer drop this
    supply-chain pin off the merge gate by editing three hand-maintained lists
    in step (the #3670 shape). Widening which function is imported does not
    weaken that: the rule parses the module import, not the symbol.

    Widened 2026-08-04 from workflows to all three pin surfaces. Everything
    below — SHA-pinning, the trusted-owner allowlist, the approved-SHA ledger —
    applied to ``.github/workflows/`` alone, so an untrusted owner or a
    40-hex-but-unresolvable SHA in ``.github/actions/`` or
    ``.github/workflow-templates/`` was checked by nothing. Measured: adding
    ``uses: evilcorp/totally-fake@deadbeef…`` to the composite action left all
    18 assertions across both guard files green.
    """
    return iter_action_pin_surfaces()


def _iter_uses() -> list[tuple[Path, int, str]]:
    return iter_uses(_iter_workflow_files())


def _owner_repo(ref_left: str) -> str:
    """Reduce ``actions/cache/restore`` -> ``actions/cache``."""
    parts = ref_left.split("/")
    if len(parts) < 2:
        return ref_left
    return f"{parts[0]}/{parts[1]}"


def test_every_uses_is_sha_pinned_or_allowlisted() -> None:
    violations: list[str] = []
    for wf, ln, ref in _iter_uses():
        # Local action
        if ref.startswith("./") or ref.startswith("../"):
            continue
        # Docker action
        if ref.startswith("docker://"):
            continue
        if "@" not in ref:
            violations.append(f"{wf.name}:{ln}: missing @ref in '{ref}'")
            continue
        left, _, version = ref.partition("@")
        # SHA pin always allowed
        if _SHA_RE.match(version):
            continue
        owner_repo = _owner_repo(left)
        if owner_repo not in _ALLOWLIST_OWNER_REPOS:
            violations.append(
                f"{wf.name}:{ln}: '{ref}' is not SHA-pinned and "
                f"'{owner_repo}' is not on the trusted allowlist. "
                f"Either pin to a 40-char SHA or add to "
                f"_ALLOWLIST_OWNER_REPOS in this test."
            )
    assert not violations, (
        "Untrusted GitHub Actions detected:\n  " + "\n  ".join(violations)
    )


def test_no_stale_allowlist_entries() -> None:
    """Every allowlist entry must still be referenced by at least one
    workflow. Removes drift when an action is dropped."""
    used_owner_repos: set[str] = set()
    for _, _, ref in _iter_uses():
        if ref.startswith("./") or ref.startswith("../") or ref.startswith("docker://"):
            continue
        if "@" not in ref:
            continue
        left, _, _ = ref.partition("@")
        used_owner_repos.add(_owner_repo(left))
    stale = sorted(_ALLOWLIST_OWNER_REPOS - used_owner_repos)
    assert not stale, (
        "Stale entries in _ALLOWLIST_OWNER_REPOS — no workflow references them: "
        + ", ".join(stale)
    )


@pytest.mark.parametrize("owner_repo", sorted(_ALLOWLIST_OWNER_REPOS))
def test_allowlist_entry_shape(owner_repo: str) -> None:
    parts = owner_repo.split("/")
    assert len(parts) == 2 and all(parts), (
        f"Allowlist entry '{owner_repo}' must be exactly '<owner>/<repo>' "
        f"(no sub-path, no @ref)."
    )


def test_workflow_inventory_sane() -> None:
    """Sanity: at least one workflow with at least one uses-line so a
    silent removal of all workflows can't trivially pass the suite."""
    uses = _iter_uses()
    assert len(uses) >= 10, (
        f"Expected >=10 uses-lines across .github/workflows, got {len(uses)}. "
        f"Workflow files may have been removed."
    )


def test_runtime_action_pins_on_approved_sha_set() -> None:
    """Every pin of a guarded runtime-installing action must reference one of
    the deliberately frozen SHAs in ``_APPROVED_ACTION_SHAS``.

    This catches a 40-hex-but-unresolvable pin (typo / hallucinated /
    upstream-rebased SHA) at PR time without any network call. See the
    module-level note on the 2026-06-03 dead-``setup-python`` incident.
    """
    violations: list[str] = []
    for wf, ln, ref in _iter_uses():
        if ref.startswith("./") or ref.startswith("../") or ref.startswith("docker://"):
            continue
        if "@" not in ref:
            continue
        left, _, version = ref.partition("@")
        owner_repo = _owner_repo(left)
        approved = _APPROVED_ACTION_SHAS.get(owner_repo)
        if approved is None:
            continue
        if not _SHA_RE.match(version):
            violations.append(
                f"{wf.name}:{ln}: '{ref}' — guarded action '{owner_repo}' must "
                f"be SHA-pinned (got non-SHA ref '{version}')."
            )
            continue
        if version not in approved:
            violations.append(
                f"{wf.name}:{ln}: '{ref}' pins '{owner_repo}' to an "
                f"unapproved SHA. Approved SHAs: "
                f"{', '.join(sorted(approved))}. If this is a legitimate "
                f"bump, verify it resolves upstream "
                f"(`gh api repos/{owner_repo}/commits/{version}`) and add it "
                f"to _APPROVED_ACTION_SHAS in this test."
            )
    assert not violations, (
        "Unapproved runtime-action SHA pins (possible dead/typo'd pin):\n  "
        + "\n  ".join(violations)
    )


def test_approved_sha_set_has_no_stale_entries() -> None:
    """Every SHA in ``_APPROVED_ACTION_SHAS`` must still be pinned by at least
    one workflow, so the frozen set cannot silently accumulate dead SHAs."""
    used: dict[str, set[str]] = {}
    for _, _, ref in _iter_uses():
        if "@" not in ref:
            continue
        left, _, version = ref.partition("@")
        used.setdefault(_owner_repo(left), set()).add(version)
    stale: list[str] = []
    for owner_repo, approved in _APPROVED_ACTION_SHAS.items():
        used_shas = used.get(owner_repo, set())
        for sha in sorted(approved - used_shas):
            stale.append(f"{owner_repo}@{sha}")
    assert not stale, (
        "Stale entries in _APPROVED_ACTION_SHAS — no workflow pins them: "
        + ", ".join(stale)
    )

