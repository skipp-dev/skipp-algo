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
``smc-library-refresh`` alone runs ~216 minutes, nine times per trading day (09:00-23:00 UTC crons).
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


@pytest.mark.parametrize("name", sorted(MUTATING | EXEMPT))
def test_the_group_actually_queues_instead_of_dropping(name: str) -> None:
    """``cancel-in-progress: false`` was never the thing that made runs wait.

    It governs only the RUNNING run. Under the default ``queue: single`` a
    concurrency group holds exactly one PENDING run, and the next entrant
    cancels that pending run and takes its place -- so with eleven producers on
    one group, ticks 3..N were being dropped, not delayed. Observed 2026-08-05
    and 2026-08-06 as ``cancelled`` refresh and tv-save runs that never started.

    ``queue: max`` (GitHub Actions, 2026-05-07) raises the cap to 100 pending
    runs. It is mutually exclusive with ``cancel-in-progress: true``, which the
    assertion above already forbids for every mutating workflow.
    """
    concurrency = load_workflow(_tradingview_workflows()[name])["concurrency"]
    assert concurrency.get("queue") == "max", (
        f"{name} runs on the default `queue: single`: one pending run per group, "
        "cancelled by the next entrant. Set `queue: max` so overlapping "
        "dispatches queue instead of displacing each other."
    )


@pytest.mark.parametrize("name", sorted(MUTATING))
def test_the_group_does_not_claim_to_serialise_the_operator(name: str) -> None:
    """The comment used to say "one browser session at a time". False.

    The group serialises CI against CI and nothing else. The operator's own
    browser is a second, unserialised writer on the same account, TradingView
    autosaves from it (operator-confirmed 2026-08-01, autosave active), and a
    chart tab on this account was open all day on 2026-08-01 while runs mutated
    layouts -- nothing in CI knew or could have known. Same defect class as the
    Pine-editor "no close affordance" comment fixed the same day: a guarantee
    stated wider than what is implemented stops being questioned.
    """
    text = _tradingview_workflows()[name].read_text(encoding="utf-8")

    assert "one TradingView account, one browser session at a time" not in text, (
        f"{name} restates the over-claim this test exists to keep dead"
    )
    assert "second, unserialised writer" in text, (
        f"{name} shares the session group but no longer discloses the "
        "operator's browser as an unserialised second writer"
    )
    assert "autosave" in text, (
        f"{name} must name autosave -- it is what turns an open operator tab "
        "from a reader into a writer"
    )
