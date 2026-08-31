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
        # 2026-08-31: die Zusicherung ist STAERKER geworden. Frueher las die
        # Praesenz von derselben Lauf-Seite ab und war damit selbst
        # seitenabhaengig -- ein `nightly`, das heute frueh lief, aber aus dem
        # 9-Stunden-Fenster gerutscht war, meldete faelschlich 0. Jetzt ist die
        # Sonde unabhaengig: `nightly` fehlt hier auf der Seite UND hat laut
        # Sonde keinen Lauf, und nur DESHALB ist die 0 richtig.
        snapshot = _fetch_with_runs(monkeypatch, [_run("ci")], presence={"nightly": None})
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
    monkeypatch: pytest.MonkeyPatch,
    runs: list[dict[str, object]],
    presence: dict[str, float | None] | None = None,
) -> dict[str, object]:
    """Lauf-Seite UND Praesenz-Sonde stellen — seit 2026-08-31 zwei Quellen.

    Die Praesenz kommt nicht mehr aus der Lauf-Seite (die deckte gemessen neun
    Stunden ab, ein Daily fehlte darauf zwei Drittel des Tages), sondern aus
    einer eigenen Abfrage je Workflow. Ohne ``presence`` wird sie aus den
    deklarierten Namen und der Lauf-Seite ABGELEITET, damit die alten Faelle
    unveraendert lesbar bleiben: wer auf der Seite steht, hat ein Alter.
    """
    monkeypatch.setattr(
        github_workflow_bridge,
        "_github_request_json",
        lambda *a, **k: {"workflow_runs": runs},
    )
    if presence is None:
        auf_seite = {str(r.get("name") or "") for r in runs}
        presence = {
            name: (60.0 if name in auf_seite else None)
            for name in config.github_workflow_expected()
        }
    monkeypatch.setattr(github_workflow_bridge, "presence_snapshot", lambda: dict(presence))
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


class TestPresenceProbeIsIndependentOfTheRunsPage:
    """2026-08-31: die Praesenz haengt nicht mehr an der geteilten Lauf-Seite.

    Gemessen an dem Tag: eine Seite von ``/actions/runs?per_page=100`` deckte
    NEUN Stunden ab (22:46Z-07:51Z, 31 Workflows); am 2026-08-20 waren es fuenf.
    Ein taeglicher Workflow fehlt darauf zwei Drittel des Tages. Die Regel
    darueber laeuft mit ``for: 6h`` -- bei gesetzter Erwartungsliste haette sie
    JEDEN TAG fuer JEDEN Daily gefeuert. Die Stille waere gegen taeglichen
    Fehlalarm getauscht worden.
    """

    def test_a_workflow_off_the_page_is_still_present_when_the_probe_saw_it(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Der Fall, an dem die alte Fassung taeglich falsch gelegen haette."""
        monkeypatch.setenv("GITHUB_WORKFLOW_MONITOR_EXPECTED", "nightly")
        snapshot = _fetch_with_runs(
            monkeypatch, [_run("ci")], presence={"nightly": 4 * 3600.0}
        )
        assert snapshot["expected_present"] == {"nightly": 1}, (
            "nightly lief vor 4 h, steht aber nicht auf der Seite — die alte "
            "Ableitung haette hier 0 gemeldet und die Regel ausgeloest"
        )

    def test_a_probe_failure_keeps_the_last_state_instead_of_claiming_absence(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Ein API-Schluckauf darf keinen Alarm erzeugen.

        Eine leere Antwort waere von "alle Workflows verschwunden" nicht zu
        unterscheiden. Der letzte bekannte Stand ist hier die richtige
        Degradation -- fail-safe, nicht fail-loud, weil die Ursache im
        Transport liegt und nicht im beobachteten System.
        """
        monkeypatch.setenv("GITHUB_WORKFLOW_MONITOR_EXPECTED", "nightly")
        monkeypatch.setattr(github_workflow_bridge, "_presence_cache", {"nightly": 120.0})
        monkeypatch.setattr(github_workflow_bridge, "_presence_at_monotonic", 0.0)
        monkeypatch.setattr(config, "github_workflow_token", lambda: "t")
        monkeypatch.setattr(config, "github_workflow_presence_ttl_secs", lambda: 0)

        def _kaputt(token: str) -> dict[str, float | None]:
            raise OSError("connection reset")

        monkeypatch.setattr(github_workflow_bridge, "_presence_ages", _kaputt)
        assert github_workflow_bridge.presence_snapshot() == {"nightly": 120.0}


class TestPresenceAgesBuildsTheRightRequests:
    """Die Abfrageform wird gepinnt, nicht angenommen (Sweep-Richtung I).

    ``_presence_ages`` ist der einzige Teil, der wirklich neue URLs baut. Ein
    Tippfehler im Pfad, ein vergessener Branch-Filter oder ein Griff auf die
    falsche Antwortebene faellt sonst erst in Produktion auf -- und zwar als
    ``None`` fuer jeden Workflow, also als Alarm ueber einen gesunden Zustand.
    """

    def _stub(
        self, monkeypatch: pytest.MonkeyPatch, gerufen: list[str], runs_by_id: dict[int, list]
    ) -> None:
        def _fake(url: str, token: str, timeout: int) -> dict[str, object]:
            gerufen.append(url)
            if "/actions/workflows?" in url:
                return {"workflows": [{"id": 11, "name": "ci"}, {"id": 22, "name": "nightly"}]}
            wid = int(url.split("/actions/workflows/")[1].split("/")[0])
            return {"workflow_runs": runs_by_id.get(wid, [])}

        monkeypatch.setattr(github_workflow_bridge, "_github_request_json", _fake)
        monkeypatch.setattr(github_workflow_bridge, "_workflow_ids_cache", None)
        monkeypatch.setattr(github_workflow_bridge, "_workflow_ids_at_monotonic", 0.0)

    def test_one_dedicated_request_per_declared_workflow(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("GITHUB_WORKFLOW_MONITOR_EXPECTED", "ci,nightly")
        monkeypatch.setenv("GITHUB_WORKFLOW_MONITOR_BRANCH", "main")
        gerufen: list[str] = []
        self._stub(monkeypatch, gerufen, {11: [_run("ci")], 22: []})

        alter = github_workflow_bridge._presence_ages("t")

        assert set(alter) == {"ci", "nightly"}
        assert alter["ci"] is not None, "ci hat einen Lauf -> Alter"
        assert alter["nightly"] is None, "nightly hat keinen Lauf -> Befund, nicht fehlendes Datum"
        runs_urls = [u for u in gerufen if "/runs?" in u]
        assert len(runs_urls) == 2, f"eine Abfrage je Workflow erwartet, war: {runs_urls}"
        for url in runs_urls:
            assert "per_page=1" in url, url
            assert "branch=main" in url, f"ohne Branch-Filter zaehlen Feature-Branch-Laeufe mit: {url}"

    def test_a_declared_name_without_a_workflow_is_a_finding(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Ein Tippfehler in der Liste darf nicht still als 'vorhanden' durchgehen."""
        monkeypatch.setenv("GITHUB_WORKFLOW_MONITOR_EXPECTED", "gibtsnicht")
        gerufen: list[str] = []
        self._stub(monkeypatch, gerufen, {})

        assert github_workflow_bridge._presence_ages("t") == {"gibtsnicht": None}
        assert not [u for u in gerufen if "/runs?" in u], (
            "fuer einen unbekannten Namen darf keine Lauf-Abfrage rausgehen"
        )

    def test_no_declaration_costs_no_api_calls(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Leere Liste = die Sonde ist AUS und darf kein Budget verbrauchen."""
        monkeypatch.delenv("GITHUB_WORKFLOW_MONITOR_EXPECTED", raising=False)
        gerufen: list[str] = []
        self._stub(monkeypatch, gerufen, {})
        assert github_workflow_bridge._presence_ages("t") == {}
        assert gerufen == []
