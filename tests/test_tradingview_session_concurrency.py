"""Every layout-mutating TradingView workflow shares one concurrency group.

TradingView is a single external account. Until 2026-08-01 each workflow that
drove it carried a private concurrency group, so nothing stopped two browser
sessions from running against the same account, the same layouts and the same
saved scripts at once. Two of those blocks even said "TradingView is a single
shared external target" while keeping a private group — the guarantee was
written down and never implemented, and the collision was avoided by the
operator noticing rather than by CI.

Three workflows stay out of the shared group ON PURPOSE, and that is pinned
here too so the exemption cannot quietly grow: they maintain or probe the
credential the others depend on and must not queue behind a publish.
``smc-library-refresh`` alone runs ~216 minutes, three times per trading day.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests._workflow_yaml import iter_workflow_files, load_workflow

SHARED_GROUP = "tradingview-session"

# Workflows that open a TradingView browser session AND may mutate layouts,
# saved scripts or published sources.
MUTATING: frozenset[str] = frozenset(
    {
        "smc-library-refresh.yml",
        "smc-overlay-library-publish.yml",
        "openprep-pine-panel-publish.yml",
        "pine-library-publish-handlibs.yml",
        "tv-save-consumer-source.yml",
        "smc-release-gates.yml",
        "smc-r4-context-readback.yml",
    }
)

# Short credential maintenance / probes. Parking these behind a ~216 min
# publish is how a 72 h cookie TTL becomes an outage and how a stale-cookie
# probe stops being timely.
EXEMPT: frozenset[str] = frozenset(
    {
        "tradingview-storage-refresh.yml",
        "credential-health-check.yml",
        "pine-library-version-monitor.yml",
    }
)


def _tradingview_workflows() -> dict[str, Path]:
    """Workflow files that open a TradingView session, by basename."""
    out: dict[str, Path] = {}
    for path in iter_workflow_files():
        if "TV_STORAGE_STATE" in path.read_text(encoding="utf-8"):
            out[path.name] = path
    return out


def test_the_inventory_still_matches_the_repository() -> None:
    """A new TradingView workflow must be classified, not silently ignored."""
    found = set(_tradingview_workflows())
    # Floor: a rename or a changed detection heuristic must not empty this set
    # and make every assertion below pass on nothing.
    assert len(found) >= 10, f"only {len(found)} TradingView workflows detected"
    unclassified = sorted(found - MUTATING - EXEMPT)
    assert not unclassified, (
        "New TradingView workflow(s) are in neither list: "
        f"{unclassified}. Add them to MUTATING (they share the session) or to "
        "EXEMPT with the reason, in the same PR."
    )
    missing = sorted((MUTATING | EXEMPT) - found)
    assert not missing, f"listed workflows no longer open a TradingView session: {missing}"


@pytest.mark.parametrize("name", sorted(MUTATING))
def test_mutating_workflows_share_one_session_group(name: str) -> None:
    workflow = load_workflow(_tradingview_workflows()[name])
    concurrency = workflow.get("concurrency")
    assert isinstance(concurrency, dict), f"{name} declares no concurrency block"
    assert concurrency["group"] == SHARED_GROUP, (
        f"{name} drives the shared TradingView account but serialises only "
        f"against itself (group={concurrency['group']!r})"
    )
    assert concurrency["cancel-in-progress"] is False, (
        f"{name} saves layouts or publishes scripts — a queued run must wait, "
        "never pre-empt a run that is mid-save"
    )


@pytest.mark.parametrize("name", sorted(EXEMPT))
def test_exempt_workflows_stay_out_of_the_shared_group(name: str) -> None:
    workflow = load_workflow(_tradingview_workflows()[name])
    concurrency = workflow.get("concurrency")
    assert isinstance(concurrency, dict), f"{name} declares no concurrency block"
    assert concurrency["group"] != SHARED_GROUP, (
        f"{name} maintains or probes the credential every other TradingView "
        "workflow depends on; queueing it behind a publish is the failure this "
        "exemption exists to prevent"
    )
