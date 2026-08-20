"""Every alerted metric must have a producer — proven by rendering, not grep.

2026-08-20 (Geburtsfehler-Sweep, 2. Flug): the sweep asked "does every metric
an alert rule fires on actually get emitted?" and could not answer it. Two
attempts failed for instructive reasons, both of them the sweep's own
"instrument before measurement" rule:

* A literal grep over the exporters answers nothing — metric names are
  composed (``f"{_prefix}_watchlist_symbols"``, ``f"live_overlay_feed_{name}"``),
  so the full name never appears in the source. It reported 47 phantom gaps.
* Rendering the exporter cold answers nothing either — every bridge-fed family
  (github workflows, credential probes, railway volumes, uptimerobot, pine
  library) is empty without data, and the daemon's own upstream fetches get
  HTTP 403 rate-limited on a laptop. It reported 22 phantom gaps.

The only honest instrument is a FIXTURE-FED render: give every bridge a
representative snapshot, render both exporters, and compare the emitted series
names against the metric names the deployed alert rules select. Measured that
way on 2026-08-20: 152 alerted metrics, 313 rendered series, **0 without a
producer**. This test freezes that answer so it stays true.

SCOPE — alert rules only, deliberately. Dashboard panels reference 242 own
metrics, 144 of them alerted by nothing; under this fixture 35 of those still
render no series, but several of those 35 are regex artifacts (a panel's
``live_overlay_bridge_.*`` label filter parses as a metric name) and the
experiment families need a richer fixture than a paging guard justifies. A
panel pointing at nothing is a cosmetic defect; a RULE pointing at nothing is a
silent alert. Extending to panels is open and UNGESICHERT — nothing fires when
a panel goes blind.

When it fails, exactly one of two things happened, and the message says so:
either a rule now fires on a metric nothing emits (the real defect — the alert
is decoration), or a new bridge/family arrived whose snapshot shape this
fixture does not feed yet (then extend ``_apply_fixture`` in the same PR, which
is the cheap half of keeping the answer honest).
"""

from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import yaml

import open_prep.realtime_signals as rs
import services.live_overlay_daemon.metrics as daemon_metrics
from services.live_overlay_daemon import (
    compute,
    config,
    evidence_freshness_bridge,
    github_workflow_bridge,
    pine_library_version_bridge,
    provider_usage_bridge,
    railway_metrics,
    reaction_zone_shadow_bridge,
    sweep_trap_shadow_bridge,
    tradingview_binding_bridge,
    uptimerobot_bridge,
)

_REPO_ROOT = Path(__file__).resolve().parents[1]
_ALERT_RULES = (
    _REPO_ROOT / "services" / "live_overlay_daemon" / "infra" / "grafana" / "alert-rules.yaml"
)
_CREDENTIAL_PRODUCER = _REPO_ROOT / "scripts" / "credential_health_check.py"

# Namespaces this repo produces itself. Third-party series (prometheus_*,
# node_*, grafanacloud_*) are emitted by the scrapers, not by us.
_OWN_METRIC_RE = re.compile(r"\b(live_overlay_[a-z0-9_]+|signals_producer_[a-z0-9_]+)\b")

_FIXTURE_EPOCH = 1_700_000_000.0

# Alerted metrics that deliberately have no series in this fixture. Empty by
# design: an entry here is an admission that an alert cannot fire, so it needs
# a written reason and a decision, not a quiet exemption.
_ALERTED_WITHOUT_PRODUCER_BY_DESIGN: frozenset[str] = frozenset()


def _producer_probe_names() -> list[str]:
    """Credential probe names DERIVED from the producer, not remembered.

    ``ProbeResult(name=...)`` appears both as a keyword argument and as a local
    assignment; both spellings count. A regex that saw only the keyword form
    missed three probes on 2026-08-19 and produced three phantom findings.
    """
    source = _CREDENTIAL_PRODUCER.read_text(encoding="utf-8")
    return sorted(set(re.findall(r'name\s*=\s*"([a-z0-9_]+)"', source)))


def _bridge_health_fields() -> dict[str, Any]:
    """Keys every bridge snapshot carries for the shared bridge-health block."""
    return {
        "known": 1,
        "loaded": 1,
        "enabled": True,
        "configured": True,
        "error": "",
        "generated_at_unix": _FIXTURE_EPOCH,
        "scrape_duration_seconds": 1.0,
        "last_success_fetched_at_unix": _FIXTURE_EPOCH,
    }


def _apply_fixture(monkeypatch: pytest.MonkeyPatch) -> None:
    """Feed every seam the exporter reads. No network, no local state."""
    monkeypatch.setattr(
        compute,
        "_load_credential_health_snapshot",
        lambda *a, **k: {
            "generated_at": "2026-08-20T00:00:00+00:00",
            "overall": {"valid": True, "severity": "ok"},
            "probes": [
                {
                    "name": name,
                    "valid": True,
                    "severity": "ok",
                    "message": "fixture",
                    "code": 2,
                    "details": {"age_hours": 1.0, "days_left": 30, "staleness_days": 0},
                }
                for name in _producer_probe_names()
            ],
        },
        raising=False,
    )
    monkeypatch.setattr(
        compute,
        "_load_signals_snapshot",
        lambda *a, **k: {
            "generated_at": "2026-08-20T00:00:00+00:00",
            "signals": [{"symbol": "AAPL", "timeframe": "5m", "level": 3, "score": 0.7}],
        },
        raising=False,
    )
    monkeypatch.setattr(
        compute,
        "_load_news_snapshot",
        lambda *a, **k: {
            "generated_at": "2026-08-20T00:00:00+00:00",
            "providers": [
                {"name": "fmp", "ok": True, "degraded": False, "state_code": 2, "consumed": 1}
            ],
            "articles": [{"symbol": "AAPL"}],
            "last_ingest_at": "2026-08-20T00:00:00+00:00",
        },
        raising=False,
    )
    monkeypatch.setattr(
        compute,
        "_load_experiment_snapshot",
        lambda *a, **k: {
            "generated_at": "2026-08-20T00:00:00+00:00",
            "experiments": [
                {"hypothesis": "H1", "status": "running", "timeframe": "5m", "family": "BOS"}
            ],
        },
        raising=False,
    )
    monkeypatch.setattr(compute, "_load_experiment_history", lambda *a, **k: [], raising=False)
    monkeypatch.setattr(
        compute,
        "_load_tradingview_credential_snapshot",
        lambda *a, **k: {
            "generated_at": "2026-08-20T00:00:00+00:00",
            "age_hours": 1.0,
            "valid": True,
        },
        raising=False,
    )

    monkeypatch.setattr(config, "uptimerobot_monitor_ids", lambda *a, **k: ["1"], raising=False)

    monkeypatch.setattr(
        github_workflow_bridge,
        "snapshot",
        lambda *a, **k: {
            **_bridge_health_fields(),
            "workflows": [
                {
                    "workflow": "smc-fast-pr-gates",
                    "name": "smc-fast-pr-gates",
                    "phase": "green",
                    "phase_code": 2,
                    "latest_success": 1,
                    "latest_age_seconds": 120.0,
                    "latest_duration_seconds": 60.0,
                    "conclusion": "success",
                    "status": "completed",
                }
            ],
            # A MAPPING workflow -> present, not a scalar.
            "expected_present": {"smc-fast-pr-gates": 1},
        },
        raising=False,
    )
    monkeypatch.setattr(
        uptimerobot_bridge,
        "snapshot",
        lambda *a, **k: {
            **_bridge_health_fields(),
            "monitors": [
                {
                    "id": "1",
                    "friendly_name": "daemon",
                    "status": 2,
                    "response_time_ms": 120.0,
                    "url": "https://example.invalid",
                }
            ],
            "monitors_total": 1,
            "monitors_down": 0,
            "monitors_up": 1,
            "monitors_paused": 0,
            "response_time_ms_avg": 120.0,
        },
        raising=False,
    )
    monkeypatch.setattr(
        railway_metrics,
        "snapshot",
        lambda *a, **k: {
            **_bridge_health_fields(),
            "services": [
                {
                    "service": "live_overlay_daemon",
                    "service_id": "svc",
                    "memory_gb": 0.5,
                    "memory_limit_gb": 8.0,
                    "memory_used_bytes": 5.0e8,
                    "memory_limit_bytes": 8.0e9,
                    "cpu_used_ratio": 0.1,
                    "disk_used_bytes": 1.0,
                }
            ],
        },
        raising=False,
    )
    monkeypatch.setattr(
        railway_metrics,
        "volume_backup_snapshot",
        lambda *a, **k: {
            **_bridge_health_fields(),
            "volumes": [
                {
                    "name": "vol",
                    "id": "v1",
                    "service": "live_overlay_daemon",
                    "backup_count": 6,
                    "schedule_count": 1,
                    "newest_backup_age_seconds": 3600.0,
                    "max_backup_age_seconds": 3600.0,
                    "retention_seconds": 604800.0,
                }
            ],
            "backup_count": 6,
            "schedule_count": 1,
            "age_seconds": 3600.0,
            "age_known": 1,
            "max_age_seconds": 3600.0,
            "retention_seconds": 604800.0,
        },
        raising=False,
    )
    monkeypatch.setattr(
        evidence_freshness_bridge,
        "snapshot",
        lambda *a, **k: {
            **_bridge_health_fields(),
            "ledger_age_seconds": 100.0,
            "ledger_age_known": 1,
            "audit_branch_age_seconds": 100.0,
            "audit_branch_age_known": 1,
            "wsh_age_seconds": 100.0,
            "wsh_age_known": 1,
            "snapshot_age_seconds": 100.0,
            "fills": {"newest_incubation_age_seconds": 100.0, "newest_incubation_age_known": 1},
            "submitter": {"submit_code_behind_commits": 0, "known": 1},
            "portfolio": {
                "latest_reconciliation_known": 1,
                "verdicts": {"allow": 1, "resize": 0, "reject": 0},
            },
        },
        raising=False,
    )
    monkeypatch.setattr(
        pine_library_version_bridge,
        "snapshot",
        lambda *a, **k: {
            **_bridge_health_fields(),
            "data_age_seconds": 100.0,
            "data_age_known": 1,
            "libraries": [
                {
                    "name": "smc_engine_private",
                    "version": 277,
                    "payload_known": 1.0,
                    "payload_universe_symbols": 10.0,
                    "payload_list_symbols": 10.0,
                    "data_age_seconds": 100.0,
                    "data_age_known": 1.0,
                }
            ],
        },
        raising=False,
    )
    monkeypatch.setattr(
        provider_usage_bridge,
        "snapshot",
        lambda *a, **k: {
            **_bridge_health_fields(),
            "providers": [
                {
                    "provider": "fmp",
                    "usage_bytes": 1.0,
                    "bandwidth_limit_bytes": 100.0,
                    "rate_limit_hits": 0,
                }
            ],
        },
        raising=False,
    )
    monkeypatch.setattr(
        tradingview_binding_bridge,
        "snapshot",
        lambda *a, **k: {
            **_bridge_health_fields(),
            "bindings_checked": 13,
            "mismatches": 0,
            "consumers": [
                {"name": "SMC Long-Dip Dashboard", "ok": 1, "bindings": 64, "mismatches": 0}
            ],
            "binding_expected_consumers": 10,
            "binding_checked_consumers": 10,
            "failed_consumers": 0,
            "source_failed_consumers": 0,
            "age_seconds": 100.0,
        },
        raising=False,
    )
    monkeypatch.setattr(
        sweep_trap_shadow_bridge,
        "snapshot",
        lambda *a, **k: {**_bridge_health_fields(), "rows": 1, "age_seconds": 100.0},
        raising=False,
    )
    monkeypatch.setattr(
        reaction_zone_shadow_bridge,
        "snapshot",
        lambda *a, **k: {**_bridge_health_fields(), "rows": 1, "age_seconds": 100.0},
        raising=False,
    )


def _signals_producer_engine() -> SimpleNamespace:
    return SimpleNamespace(
        _watchlist=[{"symbol": "AAPL", "avg_volume": 10_000}],
        open_prep_snapshot_loaded=1.0,
        open_prep_snapshot_age_seconds=1.0,
        last_poll_success_epoch=_FIXTURE_EPOCH,
        last_poll_duration_seconds=0.1,
        _avg_vol_retry_after={},
        _client=SimpleNamespace(
            get_endpoint_usage_stats=lambda: {
                "/stable/quote": {
                    "calls": 1,
                    "errors": 0,
                    "response_bytes": 1,
                    "empty_responses": 0,
                }
            }
        ),
    )


def _rendered_series() -> set[str]:
    body = daemon_metrics.render_metrics(startup_ts=100.0, startup_epoch=_FIXTURE_EPOCH)
    body += "\n" + rs._collect_process_metrics(_signals_producer_engine())
    return {
        line.split("{")[0].split(" ")[0]
        for line in body.splitlines()
        if line and not line.startswith("#")
    }


def _alerted_metrics() -> set[str]:
    """Own metric names the DEPLOYED rules select, derived from the rule file."""
    document = yaml.safe_load(_ALERT_RULES.read_text(encoding="utf-8"))
    found: set[str] = set()

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            model = node.get("model")
            if isinstance(model, dict) and isinstance(model.get("expr"), str):
                found.update(_OWN_METRIC_RE.findall(model["expr"]))
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(document)
    return found


def test_every_alerted_metric_has_a_producer(monkeypatch: pytest.MonkeyPatch) -> None:
    _apply_fixture(monkeypatch)
    series = _rendered_series()
    alerted = _alerted_metrics()

    # Anti-vacuity floors: a broken extraction or a collapsed render must fail
    # loudly instead of asserting over an empty set.
    assert len(alerted) >= 100, f"only {len(alerted)} alerted metrics parsed — extraction broke"
    assert len(series) >= 200, f"only {len(series)} series rendered — the fixture stopped feeding"

    missing = sorted(alerted - series - _ALERTED_WITHOUT_PRODUCER_BY_DESIGN)
    assert not missing, (
        "alert rules fire on metric(s) that no exporter emits:\n  - "
        + "\n  - ".join(missing)
        + "\n\nEither the rule is decoration (fix the rule or the emitter), or a new "
        "bridge/family arrived whose snapshot shape _apply_fixture does not feed yet "
        "(extend the fixture in the same PR). A grep cannot decide this: metric names "
        "are composed at runtime."
    )


def test_the_fixture_is_what_makes_the_answer_possible(monkeypatch: pytest.MonkeyPatch) -> None:
    """Mutation proof: without a bridge's data its alerted metrics vanish.

    This is why the cold render answered nothing. Emptying one bridge must
    make the population check red — otherwise the assertion above would pass
    on any state and would not be measuring the emitters at all.
    """
    _apply_fixture(monkeypatch)
    monkeypatch.setattr(
        railway_metrics, "volume_backup_snapshot", lambda *a, **k: {**_bridge_health_fields()}
    )
    series = _rendered_series()
    alerted = _alerted_metrics()
    lost = sorted(m for m in alerted - series if "volume_backup" in m)
    assert lost, (
        "emptying the railway volume-backup bridge changed nothing — the render is "
        "no longer fed by that bridge and the population check would pass vacuously"
    )


def test_credential_probe_population_comes_from_the_producer() -> None:
    """The fixture's probe names are derived, so a new probe cannot be missed."""
    names = _producer_probe_names()
    assert len(names) >= 5, f"probe-name derivation collapsed to {names}"
    alerted = _alerted_metrics()
    watched = {
        m[len("live_overlay_credential_health_") : -len("_valid")]
        for m in alerted
        if m.startswith("live_overlay_credential_health_") and m.endswith("_valid")
    }
    unknown = sorted(watched - set(names))
    assert not unknown, (
        f"alert rules watch credential probes the producer never writes: {unknown} — "
        "these alerts can never fire"
    )
