#!/usr/bin/env python3
"""Controlled Grafana firing/recovery test for TradingView binding alerts.

The production rules and binding snapshot are never modified. Instead, the
script creates short-lived functional clones whose PromQL input is switched
from ``vector(1)`` to ``vector(0)``. A matching Alertmanager silence is installed
before the clones so the test cannot notify normal production contact points.
All temporary state is removed in ``finally``.
"""

from __future__ import annotations

import argparse
import copy
import datetime as dt
import json
import os
import time
import urllib.error
import urllib.request
from typing import Any

DEFAULT_GRAFANA_URL = "https://bronzeporridge977.grafana.net"
SOURCE_UIDS = ("lo-tv-binding-snapshot-unloadable", "lo-tv-binding-drift")
TEST_UIDS = tuple(f"{uid}-e2e" for uid in SOURCE_UIDS)
TEST_GROUP = "controlled-tv-binding-alert-e2e"


class GrafanaClient:
    def __init__(self, base_url: str, token: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token

    def request(self, method: str, path: str, payload: Any | None = None) -> Any:
        body = None if payload is None else json.dumps(payload).encode()
        request = urllib.request.Request(
            self.base_url + path,
            data=body,
            method=method,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read()
            return json.loads(raw) if raw else None


def set_query_expression(rule: dict[str, Any], expression: str) -> dict[str, Any]:
    updated = copy.deepcopy(rule)
    for query in updated.get("data", []):
        if query.get("refId") == "A":
            query.setdefault("model", {})["expr"] = expression
    return updated


def build_test_clone(
    source: dict[str, Any], test_uid: str, test_run: str
) -> dict[str, Any]:
    clone = set_query_expression(source, "vector(1)")
    for key in ("id", "updated", "provenance"):
        clone.pop(key, None)
    clone["uid"] = test_uid
    clone["title"] = f"[E2E] {source['title']}"
    clone["ruleGroup"] = TEST_GROUP
    clone["for"] = "0s"
    clone["labels"] = {
        **clone.get("labels", {}),
        "severity": "info",
        "test_run": test_run,
    }
    clone["annotations"] = {
        "summary": "Temporary controlled functional clone; notifications silenced",
        "runbook": "Deleted automatically after the test",
    }
    return clone


def active_test_uids(client: GrafanaClient, test_run: str) -> list[str]:
    alerts = client.request("GET", "/api/alertmanager/grafana/api/v2/alerts")
    return sorted(
        {
            alert.get("labels", {}).get("__alert_rule_uid__", "")
            for alert in alerts
            if alert.get("labels", {}).get("test_run") == test_run
        }
    )


def wait_for_state(
    client: GrafanaClient,
    test_run: str,
    expected: list[str],
    attempts: int,
    interval_seconds: float,
) -> list[str]:
    observed: list[str] = []
    for _ in range(attempts):
        time.sleep(interval_seconds)
        observed = active_test_uids(client, test_run)
        if observed == expected:
            return observed
    raise RuntimeError(f"expected active test UIDs {expected}, observed {observed}")


def execute_test(client: GrafanaClient, attempts: int, interval_seconds: float) -> dict[str, Any]:
    test_run = "tv-binding-e2e-" + dt.datetime.now(dt.UTC).strftime("%Y%m%d%H%M%S")
    created: list[str] = []
    silence_id = ""
    try:
        for test_uid in TEST_UIDS:
            try:
                client.request("GET", f"/api/v1/provisioning/alert-rules/{test_uid}")
            except urllib.error.HTTPError as exc:
                if exc.code == 404:
                    continue
                raise
            raise RuntimeError(
                f"temporary rule {test_uid} already exists; refusing to overwrite or delete it"
            )

        now = dt.datetime.now(dt.UTC)
        silence = client.request(
            "POST",
            "/api/alertmanager/grafana/api/v2/silences",
            {
                "matchers": [
                    {"name": "test_run", "value": test_run, "isRegex": False, "isEqual": True}
                ],
                "startsAt": (now - dt.timedelta(minutes=1)).isoformat(),
                "endsAt": (now + dt.timedelta(minutes=15)).isoformat(),
                "createdBy": "tv-binding-alert-e2e workflow",
                "comment": "Suppress notifications for controlled TradingView alert clones",
            },
        )
        silence_id = str(silence.get("silenceID", ""))
        if not silence_id:
            raise RuntimeError("Grafana did not return a silence ID; refusing to create test rules")

        for source_uid, test_uid in zip(SOURCE_UIDS, TEST_UIDS, strict=True):
            source = client.request("GET", f"/api/v1/provisioning/alert-rules/{source_uid}")
            clone = build_test_clone(source, test_uid, test_run)
            created.append(test_uid)
            client.request("POST", "/api/v1/provisioning/alert-rules", clone)

        firing = wait_for_state(
            client, test_run, sorted(TEST_UIDS), attempts, interval_seconds
        )
        for test_uid in TEST_UIDS:
            rule = client.request("GET", f"/api/v1/provisioning/alert-rules/{test_uid}")
            client.request(
                "PUT",
                f"/api/v1/provisioning/alert-rules/{test_uid}",
                set_query_expression(rule, "vector(0)"),
            )
        wait_for_state(client, test_run, [], attempts, interval_seconds)
        return {"silenced": True, "fired": firing, "recovered": True}
    finally:
        for uid in created:
            try:
                client.request("DELETE", f"/api/v1/provisioning/alert-rules/{uid}")
            except urllib.error.HTTPError as exc:
                if exc.code != 404:
                    print(f"cleanup warning for {uid}: HTTP {exc.code}")
        if silence_id:
            try:
                client.request(
                    "DELETE", f"/api/alertmanager/grafana/api/v2/silence/{silence_id}"
                )
            except urllib.error.HTTPError as exc:
                if exc.code != 404:
                    print(f"silence cleanup warning: HTTP {exc.code}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true", help="create temporary silenced rules")
    parser.add_argument("--attempts", type=int, default=8)
    parser.add_argument("--interval-seconds", type=float, default=15.0)
    args = parser.parse_args()
    if not args.execute:
        print(
            json.dumps(
                {
                    "dry_run": True,
                    "source_uids": SOURCE_UIDS,
                    "test_uids": TEST_UIDS,
                    "notifications_silenced": True,
                    "production_snapshot_mutated": False,
                },
                indent=2,
            )
        )
        return 0

    token = os.environ.get("GRAFANA_API_KEY", "").strip()
    if not token:
        raise SystemExit("GRAFANA_API_KEY is required with --execute")
    client = GrafanaClient(os.environ.get("GRAFANA_URL", DEFAULT_GRAFANA_URL), token)
    print(json.dumps(execute_test(client, args.attempts, args.interval_seconds), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
