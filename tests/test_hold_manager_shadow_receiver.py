"""Contract and security tests for the Hold Manager shadow receiver."""

from __future__ import annotations

import datetime as dt
import json
import secrets
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from services.live_overlay_daemon.hold_manager_shadow_receiver import (
    _CHANNELS,
    _session_breakdown,
    build_router,
)

ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = (
    ROOT
    / "artifacts"
    / "governance"
    / "smc_hold_manager_shadow_contract.json"
)
TEMPLATES_PATH = (
    ROOT
    / "artifacts"
    / "governance"
    / "smc_hold_manager_shadow_alert_templates.json"
)
TOKEN = "shadow-receiver-test-token-" + "x" * 32
SOURCE_SHA256 = (
    "1761e96aaf5e62412329bb7be10383c36fce4e471b98467f86e1ce63ba360813"
)


@pytest.fixture()
def client(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> TestClient:
    monkeypatch.setenv("HOLD_MANAGER_SHADOW_WEBHOOK_TOKEN", TOKEN)
    monkeypatch.setenv("HOLD_MANAGER_SHADOW_ACCEPTING", "1")
    monkeypatch.setenv(
        "HOLD_MANAGER_SHADOW_LEDGER_PATH",
        str(tmp_path / "shadow.sqlite3"),
    )
    monkeypatch.setenv(
        "HOLD_MANAGER_SHADOW_CONTRACT_PATH",
        str(CONTRACT_PATH),
    )
    app = FastAPI()
    app.include_router(build_router(secrets.compare_digest))
    return TestClient(app)


def _payload(
    *,
    channel: str = "HM_ENTRY",
    bar_time: dt.datetime | None = None,
) -> dict[str, object]:
    return {
        "authToken": TOKEN,
        "schemaVersion": 1,
        "requirementId": "R2-SHADOW-CUTOVER",
        "channel": channel,
        "mode": "hold_manager",
        "sourceSha256": SOURCE_SHA256,
        "scriptName": "SMC Hold Manager R2.4 Validation",
        "layout": "SMC Hold R2.4 Validation",
        "producer": "SMC Long-Dip Suite",
        "busSchema": 7001,
        "symbol": "NASDAQ:BKNG",
        "timeframe": "5",
        "barTime": (
            bar_time or dt.datetime.now(dt.UTC)
        ).isoformat(),
        "price": "187.08",
    }


def _post_url() -> str:
    return "/tradingview/hold-manager-shadow"


def _state_url() -> str:
    return "/tradingview/hold-manager-shadow/state"


def _state_headers(token: str = TOKEN) -> dict[str, str]:
    return {"X-Hold-Manager-Shadow-Token": token}


def test_production_app_mounts_both_receiver_routes() -> None:
    from services.live_overlay_daemon import main

    paths = {route.path for route in main.app.routes}

    assert "/tradingview/hold-manager-shadow" in paths
    assert "/tradingview/hold-manager-shadow/state" in paths


def test_receiver_defaults_fail_closed_when_not_accepting(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HOLD_MANAGER_SHADOW_ACCEPTING", "0")

    response = client.post(_post_url(), json=_payload())

    assert response.status_code == 503
    assert "not accepting" in response.json()["detail"]


def test_receiver_rejects_unconfigured_or_weak_token(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HOLD_MANAGER_SHADOW_WEBHOOK_TOKEN", "short")

    payload = _payload()
    payload["authToken"] = "x" * 32
    response = client.post(_post_url(), json=payload)

    assert response.status_code == 503


def test_receiver_hides_route_on_wrong_token(client: TestClient) -> None:
    payload = _payload()
    payload["authToken"] = "z" * 64
    response = client.post(_post_url(), json=payload)

    assert response.status_code == 404


def test_receiver_requires_persistent_ledger_configuration(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("HOLD_MANAGER_SHADOW_LEDGER_PATH")

    response = client.post(_post_url(), json=_payload())

    assert response.status_code == 503
    assert "ledger" in response.json()["detail"].lower()


def test_accepts_once_and_counts_duplicate_delivery(
    client: TestClient,
    tmp_path: Path,
) -> None:
    payload = _payload()

    first = client.post(_post_url(), json=payload)
    duplicate = client.post(_post_url(), json=payload)
    state = client.get(_state_url(), headers=_state_headers())

    assert first.status_code == 200
    assert first.json()["status"] == "accepted"
    assert duplicate.status_code == 200
    assert duplicate.json()["status"] == "duplicate"
    assert duplicate.json()["eventId"] == first.json()["eventId"]
    assert state.status_code == 200
    snapshot = state.json()
    assert snapshot["accepting"] is True
    assert snapshot["uniqueEvents"] == 1
    assert snapshot["deliveryAttempts"] == 2
    assert snapshot["duplicateDeliveries"] == 1
    assert snapshot["uniqueByChannel"]["HM_ENTRY"] == 1
    assert snapshot["attemptsByChannel"]["HM_ENTRY"] == 2
    assert snapshot["duplicatesByChannel"]["HM_ENTRY"] == 1
    assert "ledger" not in json.dumps(snapshot).lower()
    assert TOKEN not in json.dumps(snapshot)
    assert TOKEN.encode() not in (tmp_path / "shadow.sqlite3").read_bytes()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("requirementId", "OTHER"),
        ("channel", "UNKNOWN"),
        ("mode", "exit_signal"),
        ("sourceSha256", "0" * 64),
        ("scriptName", "Wrong script"),
        ("layout", "Wrong layout"),
        ("producer", "Wrong producer"),
        ("busSchema", 7002),
    ],
)
def test_contract_mismatches_are_rejected(
    client: TestClient,
    field: str,
    value: object,
) -> None:
    payload = _payload()
    payload[field] = value

    response = client.post(_post_url(), json=payload)

    assert response.status_code == 409
    assert field in response.json()["detail"]["fields"]


def test_payload_is_strict_and_json_only(client: TestClient) -> None:
    payload = _payload()
    payload["unexpected"] = True

    extra = client.post(_post_url(), json=payload)
    wrong_type = client.post(
        _post_url(),
        content="not-json",
        headers={"content-type": "text/plain"},
    )
    deceptive_type = client.post(
        _post_url(),
        content=json.dumps(_payload()),
        headers={"content-type": "application/json-malformed"},
    )
    oversized = client.post(
        _post_url(),
        content=b"{" + b"x" * 8_300 + b"}",
        headers={"content-type": "application/json"},
    )

    assert extra.status_code == 400
    assert wrong_type.status_code == 415
    assert deceptive_type.status_code == 415
    assert oversized.status_code == 413


def test_rejects_stale_and_future_events(client: TestClient) -> None:
    now = dt.datetime.now(dt.UTC)

    stale = client.post(
        _post_url(),
        json=_payload(bar_time=now - dt.timedelta(seconds=901)),
    )
    future = client.post(
        _post_url(),
        json=_payload(bar_time=now + dt.timedelta(seconds=121)),
    )

    assert stale.status_code == 409
    assert "older" in stale.json()["detail"]
    assert future.status_code == 409
    assert "newer" in future.json()["detail"]


def test_all_six_templates_match_the_receiver_contract(
    client: TestClient,
) -> None:
    artifact = json.loads(TEMPLATES_PATH.read_text(encoding="utf-8"))
    contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    alerts = artifact["alerts"]

    assert artifact["receiver"]["activationRequired"] == (
        "HOLD_MANAGER_SHADOW_ACCEPTING=1"
    )
    assert tuple(row["condition"] for row in alerts) == _CHANNELS
    assert len(alerts) == len(_CHANNELS)
    assert artifact["source"]["sha256"] == contract["source"]["sha256"]
    assert artifact["source"]["hashMode"] == contract["source"]["hashMode"]
    assert artifact["source"]["frozenMicroProfileLibraryPin"] == (
        contract["source"]["frozenMicroProfileLibraryPin"]
    )

    observed_hashes: set[str] = set()
    for row in alerts:
        rendered = (
            row["message"]
            .replace("<HOLD_MANAGER_SHADOW_WEBHOOK_TOKEN>", TOKEN)
            .replace("{{exchange}}:{{ticker}}", "NASDAQ:BKNG")
            .replace("{{interval}}", "5")
            .replace(
                "{{time}}",
                dt.datetime.now(dt.UTC).isoformat(),
            )
            .replace("{{close}}", "187.08")
        )
        payload = json.loads(rendered)
        observed_hashes.add(payload["sourceSha256"])
        response = client.post(_post_url(), json=payload)
        assert response.status_code == 200
        assert response.json()["status"] == "accepted"

    assert observed_hashes == {SOURCE_SHA256}
    state = client.get(_state_url(), headers=_state_headers()).json()
    assert state["uniqueEvents"] == 6
    assert state["duplicateDeliveries"] == 0
    assert state["uniqueByChannel"] == dict.fromkeys(_CHANNELS, 1)


def test_state_exposes_per_session_delivery_breakdown(
    client: TestClient,
) -> None:
    """The observation chain's delivered-alert half: /state must break the
    ledger down per US-market session date so the reconciliation script can
    fill sessions[*].deliveredServerAlerts from receiver truth instead of a
    manual claim."""
    bar_time = dt.datetime.now(dt.UTC)
    entry = client.post(_post_url(), json=_payload(bar_time=bar_time))
    duplicate = client.post(_post_url(), json=_payload(bar_time=bar_time))
    assert entry.status_code == 200
    assert duplicate.json()["status"] == "duplicate"

    state = client.get(_state_url(), headers=_state_headers()).json()

    assert state["marketTimezone"] == "America/New_York"
    expected_date = (
        bar_time.astimezone(ZoneInfo("America/New_York")).date().isoformat()
    )
    assert state["sessions"] == [
        {
            "sessionDate": expected_date,
            "uniqueByChannel": {**dict.fromkeys(_CHANNELS, 0), "HM_ENTRY": 1},
            "duplicatesByChannel": {
                **dict.fromkeys(_CHANNELS, 0),
                "HM_ENTRY": 1,
            },
        }
    ]


def test_session_breakdown_groups_by_market_timezone_date() -> None:
    """A late-RTH bar after UTC midnight still belongs to the prior New York
    session date; a next-morning bar starts a new session entry."""
    rows = [
        # 2026-07-28 19:55 ET == 2026-07-28 23:55 UTC (same UTC date).
        {"channel": "HM_ENTRY", "bar_time": "2026-07-28T23:55:00Z", "delivery_count": 1},
        # 2026-07-28 20:05 ET == 2026-07-29 00:05 UTC — crosses UTC midnight
        # but is STILL the 2026-07-28 New York session.
        {"channel": "HM_EXIT_ANY", "bar_time": "2026-07-29T00:05:00Z", "delivery_count": 2},
        # 2026-07-29 09:35 ET — the next session.
        {"channel": "HM_ENTRY", "bar_time": "2026-07-29T13:35:00Z", "delivery_count": 1},
    ]

    sessions = _session_breakdown(rows, "America/New_York")

    assert [row["sessionDate"] for row in sessions] == [
        "2026-07-28",
        "2026-07-29",
    ]
    assert sessions[0]["uniqueByChannel"]["HM_ENTRY"] == 1
    assert sessions[0]["uniqueByChannel"]["HM_EXIT_ANY"] == 1
    assert sessions[0]["duplicatesByChannel"]["HM_EXIT_ANY"] == 1
    assert sessions[1]["uniqueByChannel"] == {
        **dict.fromkeys(_CHANNELS, 0),
        "HM_ENTRY": 1,
    }
