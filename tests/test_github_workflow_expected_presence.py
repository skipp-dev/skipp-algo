"""Declared-workflow presence: a flow that stops running must stay ALERTABLE.

Every other github-workflow series is keyed off rows discovered in the fetched
runs page, so a workflow that stops running loses its series entirely. Because
every rule in alert-rules.yaml carries ``noDataState: OK``, a vanished series is
indistinguishable from a healthy one -- ``lo-workflow-run-stale`` is structurally
unable to fire in the very scenario its runbook names ("the cron may be disabled
or never firing"). These tests pin the presence gauge that survives that
disappearance, and the alert leg that reads it.
"""

from __future__ import annotations

import pytest

from services.live_overlay_daemon import config, github_workflow_bridge, metrics


class TestExpectedPresenceConfig:
    def test_expected_defaults_to_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("GITHUB_WORKFLOW_MONITOR_EXPECTED", raising=False)
        assert config.github_workflow_expected() == []

    def test_expected_parses_dedupes_and_strips(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GITHUB_WORKFLOW_MONITOR_EXPECTED", " ci , nightly ,ci,, nightly ")
        assert config.github_workflow_expected() == ["ci", "nightly"]

    def test_per_page_cannot_exceed_github_ceiling(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The docstring used to promise "raise via env"; the clamp forbids it."""
        monkeypatch.setenv("GITHUB_WORKFLOW_MONITOR_PER_PAGE", "500")
        assert config.github_workflow_per_page() == 100


class TestBridgePresenceMap:
    def test_absent_workflow_reports_zero_not_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A declared flow with no run on the page is 0 -- present and alertable."""
        monkeypatch.setenv("GITHUB_WORKFLOW_MONITOR_EXPECTED", "ci,nightly")
        snapshot = _fetch_with_runs(monkeypatch, [_run("ci")])
        assert snapshot["expected_present"] == {"ci": 1, "nightly": 0}

    def test_undeclared_workflows_are_not_reported(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GITHUB_WORKFLOW_MONITOR_EXPECTED", "ci")
        snapshot = _fetch_with_runs(monkeypatch, [_run("ci"), _run("some-other-flow")])
        assert snapshot["expected_present"] == {"ci": 1}

    def test_no_declaration_emits_no_presence_claims(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("GITHUB_WORKFLOW_MONITOR_EXPECTED", raising=False)
        snapshot = _fetch_with_runs(monkeypatch, [_run("ci")])
        assert snapshot["expected_present"] == {}


class TestPresenceMetric:
    def test_missing_workflow_renders_zero_series(self, monkeypatch: pytest.MonkeyPatch) -> None:
        body = _render(monkeypatch, {"expected_present": {"ci": 1, "nightly": 0}})
        assert 'live_overlay_github_workflow_expected_present{workflow="ci"} 1' in body
        assert 'live_overlay_github_workflow_expected_present{workflow="nightly"} 0' in body

    def test_series_is_labelled_by_name_only(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """workflow_id/event are unknown for a flow with no runs; inventing them
        would churn labels the moment it returns."""
        body = _render(monkeypatch, {"expected_present": {"nightly": 0}})
        line = _presence_lines(body)[0]
        assert "workflow_id=" not in line and "event=" not in line

    def test_unknown_presence_emits_nothing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Disabled/failed bridge => no fetch => no fabricated "missing" claim."""
        assert _presence_lines(_render(monkeypatch, {"expected_present": {}})) == []
        assert _presence_lines(_render(monkeypatch, {})) == []

    def test_survives_a_workflow_vanishing_from_the_runs_page(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The regression this whole file exists for.

        When a declared flow stops running, every OTHER series it had disappears
        (age/verdict/phase are built from discovered rows). Under
        ``noDataState: OK`` a disappeared series is silent, so the presence gauge
        must be the one that remains -- reading 0, not going absent.
        """
        monkeypatch.setenv("GITHUB_WORKFLOW_MONITOR_EXPECTED", "nightly")
        snapshot = _fetch_with_runs(monkeypatch, [_run("ci")])
        body = _render(monkeypatch, snapshot)

        assert 'live_overlay_github_workflow_expected_present{workflow="nightly"} 0' in body
        # ...while the age series it used to have is indeed gone, which is
        # precisely why lo-workflow-run-stale alone cannot catch this.
        assert "nightly" not in "\n".join(
            line
            for line in body.splitlines()
            if line.startswith("live_overlay_github_workflow_latest_age_seconds")
        )


def _run(name: str) -> dict[str, object]:
    return {
        "name": name,
        "workflow_id": f"id-{name}",
        "event": "schedule",
        "status": "completed",
        "conclusion": "success",
        "created_at": "2026-07-23T00:00:00Z",
        "run_started_at": "2026-07-23T00:00:00Z",
        "updated_at": "2026-07-23T00:01:00Z",
    }


def _fetch_with_runs(
    monkeypatch: pytest.MonkeyPatch, runs: list[dict[str, object]]
) -> dict[str, object]:
    monkeypatch.setattr(
        github_workflow_bridge,
        "_github_request_json",
        lambda *a, **k: {"workflow_runs": runs},
    )
    return github_workflow_bridge._fetch_snapshot("token")


def _render(monkeypatch: pytest.MonkeyPatch, workflow_snapshot: dict[str, object]) -> str:
    """Run the REAL exporter over a given github-workflow bridge snapshot.

    Deliberately not a local re-implementation of the emission block: that would
    keep passing if the exporter stopped emitting the gauge altogether, which is
    the failure this file is here to catch.
    """
    monkeypatch.setattr(github_workflow_bridge, "snapshot", lambda: workflow_snapshot)
    return metrics.render_metrics(100.0, 1_700_000_000.0)


def _presence_lines(body: str) -> list[str]:
    return [
        line
        for line in body.splitlines()
        if line.startswith("live_overlay_github_workflow_expected_present")
    ]
