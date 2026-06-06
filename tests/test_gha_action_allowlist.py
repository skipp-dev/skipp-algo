"""Defense-pin: GitHub Actions action-reference allowlist.

Every ``uses: <owner>/<repo>@<ref>`` in ``.github/workflows/*.y*ml`` MUST
be either:

1. SHA-pinned (40-char hex), OR
2. on the frozen trusted-publisher allowlist below.

Local actions (``./...``) and Docker actions (``docker://...``) are
exempt.

Rationale: prevents drive-by supply-chain attacks via tag-mutation on
unvetted third-party actions. The allowlist is intentionally tiny —
adding a new third-party action requires updating this ledger.

Defense-only — no production changes.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

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

_USES_RE = re.compile(r"^\s*-?\s*uses:\s*([^\s#'\"]+)")
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
            # workflows now pin v6 (Node-24). See the v5→v6 sweep commit.
            "a309ff8b426b58ec0e2a45f0f869d46889d02405",  # v6 (Node-24)
        }
    ),
}


def _iter_workflow_files() -> list[Path]:
    if not WORKFLOWS_DIR.is_dir():
        return []
    return sorted(
        p for p in WORKFLOWS_DIR.iterdir()
        if p.is_file() and p.suffix in (".yml", ".yaml")
    )


def _iter_uses() -> list[tuple[Path, int, str]]:
    out: list[tuple[Path, int, str]] = []
    for wf in _iter_workflow_files():
        for ln, line in enumerate(wf.read_text(encoding="utf-8").splitlines(), 1):
            m = _USES_RE.match(line)
            if not m:
                continue
            ref = m.group(1).strip()
            # strip surrounding quotes if any survived
            ref = ref.strip("'\"")
            out.append((wf, ln, ref))
    return out


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

