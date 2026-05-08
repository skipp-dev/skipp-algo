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
