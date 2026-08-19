"""Unit tests for the Railway volume-backup half of the Railway bridge.

The point of these gauges is to make a *missing* backup loud. So most of what
is asserted here is the difference between "no backup exists" and "a fresh
backup exists" — the two states a naive age gauge renders identically as 0.
"""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from services.live_overlay_daemon import config, railway_metrics


@pytest.fixture(autouse=True)
def _reset_backup_cache() -> None:
    railway_metrics.reset_volume_backup_cache()
    yield
    railway_metrics.reset_volume_backup_cache()


@pytest.fixture
def _one_instance(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RAILWAY_API_TOKEN", "token")
    monkeypatch.setenv("RAILWAY_VOLUME_BACKUP_INSTANCES", "lab-worker-volume=vi-1")


def _fake_response(body: bytes) -> object:
    class _Response:
        def read(self) -> bytes:
            return body

        def __enter__(self) -> object:
            return self

        def __exit__(self, *args: object) -> None:
            return None

    return _Response()


def _body(*, schedules: list[dict] | None = None, backups: list[dict] | None = None) -> bytes:
    return json.dumps(
        {
            "data": {
                "volumeInstanceBackupScheduleList": schedules if schedules is not None else [],
                "volumeInstanceBackupList": backups if backups is not None else [],
            }
        }
    ).encode()


# --- timestamp parsing -----------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("2026-08-13T10:57:00.302Z", 1_786_618_620.0),
        ("2026-08-13T10:57:00Z", 1_786_618_620.0),
        ("2026-08-13T10:57:00+00:00", 1_786_618_620.0),
    ],
)
def test_parse_iso_utc_accepts_railways_shapes(raw: str, expected: float) -> None:
    assert railway_metrics._parse_iso_utc(raw) == expected


@pytest.mark.parametrize("raw", [None, "", "   ", "gestern", 1_786_618_620, {"createdAt": "x"}])
def test_parse_iso_utc_returns_none_rather_than_a_wrong_epoch(raw: object) -> None:
    """An unparseable timestamp must not collapse into 0.0 — that reads as 1970."""
    assert railway_metrics._parse_iso_utc(raw) is None


# --- summarising one instance ---------------------------------------------


def test_summarise_counts_schedules_and_picks_the_newest_backup() -> None:
    body = json.loads(
        _body(
            schedules=[{"id": "s1", "kind": "DAILY", "retentionSeconds": 518_400}],
            backups=[
                {"id": "b1", "createdAt": "2026-08-11T10:00:00Z"},
                {"id": "b2", "createdAt": "2026-08-13T10:57:00.302Z"},
                {"id": "b3", "createdAt": "2026-08-12T10:00:00Z"},
            ],
        )
    )
    summary = railway_metrics._summarise_volume("lab", "vi-1", body)

    assert summary["schedule_count"] == 1.0
    assert summary["schedule_kinds"] == "DAILY"
    assert summary["retention_seconds"] == 518_400.0
    assert summary["backup_count"] == 3.0
    assert summary["newest_created_at_unix"] == 1_786_618_620.0


def test_summarise_reports_unknown_age_when_no_backup_exists() -> None:
    """A configured schedule that has never fired is the state to catch."""
    body = json.loads(_body(schedules=[{"id": "s1", "kind": "DAILY", "retentionSeconds": 518_400}]))
    summary = railway_metrics._summarise_volume("lab", "vi-1", body)

    assert summary["schedule_count"] == 1.0
    assert summary["backup_count"] == 0.0
    assert summary["newest_created_at_unix"] is None


def test_summarise_counts_an_unparseable_backup_but_leaves_the_age_unknown() -> None:
    body = json.loads(_body(backups=[{"id": "b1", "createdAt": "irgendwann"}]))
    summary = railway_metrics._summarise_volume("lab", "vi-1", body)

    assert summary["backup_count"] == 1.0
    assert summary["newest_created_at_unix"] is None


def test_summarise_reports_no_schedule_at_all() -> None:
    """The state the customer plane was actually in until 2026-08-13."""
    summary = railway_metrics._summarise_volume("lab", "vi-1", json.loads(_body()))

    assert summary["schedule_count"] == 0.0
    assert summary["backup_count"] == 0.0
    assert summary["retention_seconds"] is None


# --- snapshot --------------------------------------------------------------


def test_snapshot_is_disabled_without_configured_instances(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RAILWAY_API_TOKEN", "token")
    monkeypatch.setenv("RAILWAY_VOLUME_BACKUP_INSTANCES", "")

    snapshot = railway_metrics.volume_backup_snapshot()

    assert snapshot["enabled"] is False
    assert snapshot["configured"] is False
    assert snapshot["volumes"] == []


def test_snapshot_is_disabled_without_a_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RAILWAY_API_TOKEN", "")
    monkeypatch.setenv("RAILWAY_VOLUME_BACKUP_INSTANCES", "lab=vi-1")

    assert railway_metrics.volume_backup_snapshot()["enabled"] is False


@pytest.mark.usefixtures("_one_instance")
def test_snapshot_fetches_and_parses() -> None:
    body = _body(
        schedules=[{"id": "s1", "kind": "DAILY", "retentionSeconds": 518_400}],
        backups=[{"id": "b1", "createdAt": "2026-08-13T10:57:00.302Z"}],
    )
    with patch("urllib.request.urlopen", return_value=_fake_response(body)):
        snapshot = railway_metrics.volume_backup_snapshot()

    assert snapshot["ok"] is True
    assert snapshot["error"] is None
    assert [volume["name"] for volume in snapshot["volumes"]] == ["lab-worker-volume"]
    assert snapshot["volumes"][0]["schedule_count"] == 1.0


@pytest.mark.usefixtures("_one_instance")
def test_snapshot_queries_every_configured_instance(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RAILWAY_VOLUME_BACKUP_INSTANCES", "a=vi-1,b=vi-2")
    body = _body(backups=[{"id": "b1", "createdAt": "2026-08-13T10:57:00Z"}])
    with patch("urllib.request.urlopen", return_value=_fake_response(body)) as opened:
        snapshot = railway_metrics.volume_backup_snapshot()

    assert opened.call_count == 2
    assert [volume["name"] for volume in snapshot["volumes"]] == ["a", "b"]


@pytest.mark.usefixtures("_one_instance")
def test_snapshot_keeps_last_good_volumes_but_admits_the_failed_attempt() -> None:
    good = _body(backups=[{"id": "b1", "createdAt": "2026-08-13T10:57:00Z"}])
    with patch("urllib.request.urlopen", return_value=_fake_response(good)):
        railway_metrics.volume_backup_snapshot()

    railway_metrics._BACKUP_CACHE_EXPIRES_AT = 0.0
    with patch("urllib.request.urlopen", side_effect=TimeoutError("zu langsam")):
        failed = railway_metrics.volume_backup_snapshot()

    assert failed["ok"] is False
    assert failed["error"] == "timeout"
    # The data survives so the dashboard still shows the last known state...
    assert failed["volumes"][0]["backup_count"] == 1.0
    # ...but the freshness of that data is not claimed to be current.
    assert failed["last_success_fetched_at_unix"] > 0


@pytest.mark.usefixtures("_one_instance")
def test_snapshot_treats_graphql_errors_as_a_failed_scrape() -> None:
    body = json.dumps({"errors": [{"message": "Not Authorized"}]}).encode()
    with patch("urllib.request.urlopen", return_value=_fake_response(body)):
        snapshot = railway_metrics.volume_backup_snapshot()

    assert snapshot["ok"] is False
    assert snapshot["volumes"] == []


# --- rendering -------------------------------------------------------------


def _render(snapshot: dict, *, now: float = 1_786_618_620.0 + 3600.0) -> str:
    from services.live_overlay_daemon import metrics

    with (
        patch.object(metrics.railway_metrics, "volume_backup_snapshot", return_value=snapshot),
        patch.object(metrics.time, "time", return_value=now),
    ):
        return metrics.render_metrics(startup_ts=1_000_000.0)


def _snapshot(volumes: list[dict], **overrides: object) -> dict:
    base = {
        "enabled": True,
        "configured": True,
        "ok": True,
        "fetched_at_unix": 1_786_618_620.0,
        "last_success_fetched_at_unix": 1_786_618_620.0,
        "scrape_duration_seconds": 0.42,
        "error": None,
        "volumes": volumes,
    }
    base.update(overrides)
    return base


def test_render_emits_the_bridge_contract_and_the_volume_gauges() -> None:
    text = _render(
        _snapshot(
            [
                {
                    "name": "lab-worker-volume",
                    "instance_id": "vi-1",
                    "schedule_count": 1.0,
                    "schedule_kinds": "DAILY",
                    "retention_seconds": 518_400.0,
                    "backup_count": 2.0,
                    "newest_created_at_unix": 1_786_618_620.0,
                }
            ]
        )
    )

    assert 'live_overlay_bridge_enabled{bridge="railway_volume_backups"} 1' in text
    assert 'live_overlay_bridge_configured{bridge="railway_volume_backups"} 1' in text
    assert 'live_overlay_bridge_scrape_success{bridge="railway_volume_backups"} 1' in text
    assert 'live_overlay_railway_volume_backup_schedule_count{volume="lab-worker-volume"} 1' in text
    assert 'live_overlay_railway_volume_backup_count{volume="lab-worker-volume"} 2' in text
    assert 'live_overlay_railway_volume_backup_age_known{volume="lab-worker-volume"} 1.0' in text
    assert 'live_overlay_railway_volume_backup_age_seconds{volume="lab-worker-volume"} 3600.0' in text
    assert 'live_overlay_railway_volume_backup_retention_seconds{volume="lab-worker-volume"} 518400' in text


def test_render_publishes_the_staleness_threshold_it_was_configured_with() -> None:
    """Grafana compares against this gauge, so the two cannot drift apart."""
    text = _render(_snapshot([{"name": "v", "instance_id": "vi-1", "schedule_count": 1.0,
                              "backup_count": 1.0, "newest_created_at_unix": 1_786_618_620.0}]))

    expected = config.railway_volume_backup_max_age_secs()
    assert f"live_overlay_railway_volume_backup_max_age_seconds {expected}" in text


def test_render_marks_a_never_backed_up_volume_as_unknown_not_as_zero_seconds_old() -> None:
    text = _render(
        _snapshot(
            [
                {
                    "name": "lab-worker-volume",
                    "instance_id": "vi-1",
                    "schedule_count": 1.0,
                    "backup_count": 0.0,
                    "newest_created_at_unix": None,
                }
            ]
        )
    )

    assert 'live_overlay_railway_volume_backup_age_known{volume="lab-worker-volume"} 0.0' in text
    assert 'live_overlay_railway_volume_backup_count{volume="lab-worker-volume"} 0' in text
    # The age gauge is still emitted (Grafana needs the series) but is only
    # meaningful together with age_known — which is 0 here.
    assert 'live_overlay_railway_volume_backup_age_seconds{volume="lab-worker-volume"} 0.0' in text


def test_render_omits_retention_when_no_schedule_reports_one() -> None:
    text = _render(
        _snapshot([{"name": "v", "instance_id": "vi-1", "schedule_count": 0.0,
                    "retention_seconds": None, "backup_count": 0.0, "newest_created_at_unix": None}])
    )

    assert 'live_overlay_railway_volume_backup_schedule_count{volume="v"} 0' in text
    assert "live_overlay_railway_volume_backup_retention_seconds{" not in text


def test_render_when_disabled_emits_the_contract_but_no_volume_series() -> None:
    text = _render(
        _snapshot([], enabled=False, configured=False, ok=False,
                  fetched_at_unix=0.0, last_success_fetched_at_unix=0.0,
                  scrape_duration_seconds=None)
    )

    assert 'live_overlay_bridge_enabled{bridge="railway_volume_backups"} 0' in text
    assert 'live_overlay_bridge_configured{bridge="railway_volume_backups"} 0' in text
    assert "live_overlay_railway_volume_backup_age_known{" not in text
    assert "live_overlay_railway_volume_backup_max_age_seconds" not in text


def test_render_surfaces_a_failed_scrape_while_still_showing_the_last_known_volumes() -> None:
    text = _render(
        _snapshot(
            [{"name": "v", "instance_id": "vi-1", "schedule_count": 1.0,
              "backup_count": 1.0, "newest_created_at_unix": 1_786_618_620.0}],
            ok=False,
            error="timeout",
        )
    )

    assert 'live_overlay_bridge_scrape_success{bridge="railway_volume_backups"} 0' in text
    assert 'live_overlay_bridge_error_info{bridge="railway_volume_backups",error="timeout"} 1' in text
    assert 'live_overlay_railway_volume_backup_count{volume="v"} 1' in text


# --- configuration ---------------------------------------------------------


def test_instances_parse_into_label_to_id(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "RAILWAY_VOLUME_BACKUP_INSTANCES", " lab-worker-volume=vi-1 , other = vi-2 ,,broken"
    )

    assert config.railway_volume_backup_instances() == {"lab-worker-volume": "vi-1", "other": "vi-2"}


def test_max_age_default_covers_a_daily_schedule_with_slack(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("RAILWAY_VOLUME_BACKUP_MAX_AGE_SECS", raising=False)

    assert config.railway_volume_backup_max_age_secs() == 129_600


def test_docs_do_not_copy_the_deployed_instance_list() -> None:
    """Die Doku darf die konfigurierte Volume-Liste NICHT replizieren.

    Bis 2026-08-19 nannte OPS.md genau eine Instanz-ID als "Production:".
    Am selben Tag wurden fuenf weitere Volumes aufgenommen — die Zeile war
    ab dem Moment falsch, ohne dass irgendetwas es gemerkt haette. Genau die
    Klasse, die der Doppelgaenger-Sweep jagt: eine zweite Kopie einer Wahrheit,
    die niemand gleich haelt.

    Wahrheitsquelle ist die deployte Variable; sichtbar ist sie ueber
    live_overlay_railway_volume_backup_schedule_count (eine Serie pro Volume).
    """
    import re
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "services" / "live_overlay_daemon"
    uuid = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b")

    offenders: list[str] = []
    for doc in ("OPS.md", "README.md"):
        for lineno, line in enumerate(
            (root / doc).read_text(encoding="utf-8").splitlines(), start=1
        ):
            if "RAILWAY_VOLUME_BACKUP_INSTANCES" in line and uuid.search(line):
                offenders.append(f"{doc}:{lineno}")

    assert not offenders, (
        "Die Doku traegt eine Volume-Instanz-ID neben "
        f"RAILWAY_VOLUME_BACKUP_INSTANCES ({offenders}) — das ist eine zweite "
        "Kopie der deployten Liste, die beim naechsten Volume still falsch "
        "wird. Auf die Metrik verweisen statt die Liste abzuschreiben."
    )
