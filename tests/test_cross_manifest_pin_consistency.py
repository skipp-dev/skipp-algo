"""Cross-manifest pin drift is a DECISION, not an accident.

2026-08-18 (Doppelgaenger-Sweep A1): packages pinned in BOTH the root
``requirements.txt`` and a service manifest had silently diverged — certifi
across three services, pandas across two, pyarrow in one — and
``services/opra_live_daemon/requirements.txt`` was bound by no test at all.
Dependabot treats every directory as its own ecosystem (grouped PRs per dir),
so one side moves without the other ever being looked at; the pin-contract
tests bind hand-picked pairs only.

This guard derives the shared-package population and demands: equal versions,
OR an exact, dated entry in :data:`ACCEPTED_DRIFT`. Any NEW divergence (and
any change to an accepted pair, including bumps of the already-drifted side)
fails on the PR that introduces it and forces the decision.

Runs on the required path: registered in the fast-gates file list
(``smc-fast-pr-gates.yml``) + ``tests/_fast_inventory.py`` — the diff-driven
selection would never pair a service-requirements PR with this file (the
#4333 hole).
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

# The live_overlay_daemon service file is deliberately NOT part of this
# population: it is not the deploy path (the root Dockerfile installs
# requirements.lock; measured at the live container 2026-08-05) and carries
# its own guard, tests/test_live_overlay_daemon_deploy_artifact_contract.py.
# Comparing against a decorative manifest would dilute this guard with noise.
EXCLUDED_SERVICES = frozenset({"live_overlay_daemon"})

# Accepted, dated divergences: (service, package) -> (root_version, service_version).
# Every entry is a standing order, not a shrug: the service side deployed
# these versions via Dependabot while the root side waits for its next
# lock regeneration (root bumps require the full throwaway-venv suite run —
# see skipp-dependabot-pin-contract-drift). Closing an entry = align the two
# manifests and delete the line; this test then goes red on the stale entry
# via the exactness check below.
ACCEPTED_DRIFT: dict[tuple[str, str], tuple[str, str]] = {
    ("a0_fast_detector", "certifi"): ("2026.4.22", "2026.7.22"),  # 2026-08-18
    ("a0_fast_detector", "pandas"): ("3.0.3", "3.0.5"),  # 2026-08-18
    ("a0_fast_detector", "pyarrow"): ("24.0.0", "25.0.1"),  # 2026-08-18 (#4778)
    ("opra_live_daemon", "certifi"): ("2026.4.22", "2026.7.22"),  # 2026-08-18
    ("opra_live_daemon", "pandas"): ("3.0.3", "3.0.5"),  # 2026-08-18
    ("signals_producer", "certifi"): ("2026.4.22", "2026.7.22"),  # 2026-08-18
    ("signals_producer", "feedparser"): ("6.0.11", "6.0.14"),  # 2026-08-18
}

_PIN_RE = re.compile(r"^([A-Za-z0-9_.\[\]-]+)==([A-Za-z0-9.]+)")


def _pins(path: Path) -> dict[str, str]:
    pins: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        match = _PIN_RE.match(line)
        if match:
            name = match.group(1).lower().split("[")[0].replace("_", "-")
            pins[name] = match.group(2)
    return pins


def _service_manifests() -> dict[str, Path]:
    return {
        path.parent.name: path
        for path in sorted(REPO.glob("services/*/requirements.txt"))
        if path.parent.name not in EXCLUDED_SERVICES
    }


def test_shared_pins_agree_or_carry_a_dated_decision() -> None:
    root = _pins(REPO / "requirements.txt")
    assert len(root) >= 20, "root requirements parsed to almost nothing — vacuous scan"

    services_with_overlap = 0
    problems: list[str] = []
    seen_pairs: set[tuple[str, str]] = set()
    for service, manifest in _service_manifests().items():
        service_pins = _pins(manifest)
        shared = sorted(set(service_pins) & set(root))
        if shared:
            services_with_overlap += 1
        for package in shared:
            pair = (root[package], service_pins[package])
            if pair[0] == pair[1]:
                continue
            seen_pairs.add((service, package))
            accepted = ACCEPTED_DRIFT.get((service, package))
            if accepted != pair:
                problems.append(
                    f"{service}/{package}: root=={pair[0]} vs service=={pair[1]}"
                    f" (accepted: {accepted})"
                )
    assert services_with_overlap >= 3, (
        f"only {services_with_overlap} services share packages with root — "
        "the derivation went vacuous."
    )
    assert not problems, (
        "cross-manifest pin drift without a dated decision: "
        f"{problems}. Either align both manifests or record the divergence in "
        "ACCEPTED_DRIFT with a date — never let the two truths drift silently."
    )

    stale = sorted(set(ACCEPTED_DRIFT) - seen_pairs)
    assert not stale, (
        f"ACCEPTED_DRIFT carries entries that no longer diverge: {stale}. "
        "Delete them so the list stays an honest inventory of open decisions."
    )


def test_every_service_manifest_is_in_scope() -> None:
    """opra_live_daemon had NO binding test at all — keep the population honest."""
    names = set(_service_manifests())
    assert "opra_live_daemon" in names
    assert "a0_fast_detector" in names
    assert "signals_producer" in names
