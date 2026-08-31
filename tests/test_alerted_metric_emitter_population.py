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

DASHBOARD PANELS — added 2026-08-20, closing the hole this file used to label
UNGESICHERT. The first attempt (are all 240 panel metrics in the fixture-fed
render?) was the wrong question: 33 were missing, and every one of them turned
out to be a family the fixture does not feed, not a dead panel. Enriching the
fixture until all of them render would have made the check a fixture-
completeness test. The question a panel actually poses is weaker and answerable
statically: **can any code path in the exporters spell this name?** That is
derived from their AST, and a metric name reaches Prometheus by five spellings,
each of which cost one failing run of the mutation proof below to discover:

1. a literal — ``"live_overlay_feed_ready"``;
2. an f-string — ``f"live_overlay_hotspot_symbol_{sym}_requests_total"``;
3. a dotted counter key sanitised at render time — ``"live_overlay.smc_live_requests.total"``;
4. a stem passed to a helper that appends the leaf — ``_emit_age("live_overlay_evidence_ledger_age", …)``;
5. a suffix from a literal tuple a loop walks, joined to its namespace.

Measured 2026-08-20: 233 panel metric names + 11 ``__name__`` family regexes
against 224 literal names and 415 templates — **0 unproducible**. What this
does NOT catch: one leaf vanishing inside a family whose template still
exists, because the template spells the leaf's siblings too. Family-level
death is caught; leaf-level death inside a live family is not, and that limit
is why the alert check above stays render-based.

When it fails, exactly one of two things happened, and the message says so:
either a rule now fires on a metric nothing emits (the real defect — the alert
is decoration), or a new bridge/family arrived whose snapshot shape this
fixture does not feed yet (then extend ``_apply_fixture`` in the same PR, which
is the cheap half of keeping the answer honest).
"""

from __future__ import annotations

import ast
import json
import re
from collections.abc import Iterable
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
_GRAFANA = _REPO_ROOT / "services" / "live_overlay_daemon" / "infra" / "grafana"
_EXPORTERS = (
    _REPO_ROOT / "services" / "live_overlay_daemon" / "metrics.py",
    _REPO_ROOT / "open_prep" / "realtime_signals.py",
)

# A dashboard may select a family instead of a name: {__name__=~"…_state_code"}.
_QUOTED_RE = re.compile(r'"([^"]*)"')
_OWN_PREFIX_RE = re.compile(r"^(live_overlay_|signals_producer_)")
# Counter keys carry dots and only become metric names via _sanitize_name.
_OWN_DOTTED_RE = re.compile(r"\b(live_overlay\.[a-z0-9_.]+|signals_producer\.[a-z0-9_.]+)\b")
# Stands in for a runtime-substituted part of a composed metric name.
_WITNESS_TOKEN = "xwitnessx"
# One variable can hold many names; the cross product stays bounded so a
# pathological template cannot turn this guard into a hang.
_MAX_BINDINGS = 32
_MAX_SPELLINGS = 256

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
                {"name": "SMC Decision Board", "ok": 1, "bindings": 64, "mismatches": 0}
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
    from open_prep.cisco_probe import CiscoKeyProber

    return SimpleNamespace(
        _watchlist=[{"symbol": "AAPL", "avg_volume": 10_000}],
        # Not started: metrics_lines renders without the thread, proving the
        # sp-cisco-probe-stale series comes from the real exporter path.
        _cisco_prober=CiscoKeyProber(interval_s=3600.0, probe_fn=lambda: (True, "")),
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


def _exporter_sources() -> list[str]:
    return [path.read_text(encoding="utf-8") for path in _EXPORTERS]


def _emittable(sources: Iterable[str]) -> tuple[frozenset[str], tuple[re.Pattern[str], ...], tuple[str, ...]]:
    """Every metric name the exporters CAN write, derived from their AST.

    Three products, because a name reaches Prometheus by two routes:

    * literals — ``"live_overlay_feed_ready"`` written out in full;
    * composed — ``f"live_overlay_hotspot_symbol_{symbol}_requests_total"``,
      where the full name exists only at runtime. Each placeholder becomes
      ``[a-z0-9_]+``, so the template turns into a matcher.
    * witnesses — one concrete sample name per composed template, so a panel's
      own ``__name__=~`` regex has something to match against.

    This is a STATIC population: it proves a name is writable, not that the
    write is reachable. That is deliberately weaker than the fixture render
    used for alerts above, and it is the right strength here — a dashboard
    panel naming a metric no exporter can even spell is dead on arrival,
    while a panel whose family simply has no data today is merely empty.
    """
    literals: set[str] = set()
    witnesses: list[str] = []
    for source in sources:
        tree = ast.parse(source)
        bindings = _name_templates(tree)
        stack: list[ast.AST] = [tree]
        while stack:
            node = stack.pop()
            if isinstance(node, ast.JoinedStr):
                # Do NOT descend: the literal chunks of a template are name
                # FRAGMENTS ("live_overlay_hotspot_symbol_"), and harvesting
                # them as names would let a truncated prefix cover a panel.
                witnesses.extend(_template_of(node, bindings))
                continue
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                literals.update(_OWN_METRIC_RE.findall(node.value))
                # Third route: dotted counter keys ("live_overlay.smc_live_requests.total")
                # that only become metric names through _sanitize_name at render
                # time. Seven traffic counters and the compute-cycle errors exist
                # ONLY in this spelling — a name-shaped grep never sees them.
                literals.update(
                    key.replace(".", "_") for key in _OWN_DOTTED_RE.findall(node.value)
                )
            stack.extend(ast.iter_child_nodes(node))
    composed = tuple(re.compile("^" + w.replace(_WITNESS_TOKEN, "[a-z0-9_]+") + "$") for w in set(witnesses))
    return frozenset(literals), composed, tuple(sorted(set(witnesses)) + sorted(literals))


def _name_templates(tree: ast.Module) -> dict[str, list[str]]:
    """Names that reach a template through a variable, resolved one hop.

    Two hops matter in practice, and both were found by this guard's own
    failures on 2026-08-20:

    * assignment — ``prefix = f"live_overlay_uptimerobot_monitor_{id}"``, with
      the leaf spelled ``f"{prefix}_status_code"``;
    * argument — ``_emit_age("live_overlay_evidence_ledger_age", …)`` where the
      helper appends ``_known``/``_seconds``. The stem lives at the call site,
      the suffix inside the helper, and NEITHER is the metric name.

    Without this hop eight live gauges look unproducible and would need an
    exception list — the very thing the fix ladder forbids.
    """
    bindings: dict[str, list[str]] = {}

    def remember(name: str, value: str) -> None:
        if value not in bindings.setdefault(name, []):
            bindings[name].append(value)

    # Loop variable ← the literal tuple it walks. Thirteen news-health gauges
    # exist only as suffixes in such a tuple ("news_health_degraded"), joined
    # to their namespace one line later.
    for node in ast.walk(tree):
        if not isinstance(node, ast.For) or not isinstance(node.target, ast.Name):
            continue
        if not isinstance(node.iter, ast.Tuple | ast.List | ast.Set):
            continue
        for element in node.iter.elts:
            legal = isinstance(element, ast.Constant) and isinstance(element.value, str)
            if legal and re.fullmatch(r"[a-z0-9_.]+", element.value):
                remember(node.target.id, element.value)

    # Parameter ← literal arguments, matched by position across call sites.
    functions = {
        node.name: node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)
    }
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)):
            continue
        target_fn = functions.get(node.func.id)
        if target_fn is None:
            continue
        params = [arg.arg for arg in target_fn.args.args]
        for index, argument in enumerate(node.args[: len(params)]):
            literal = isinstance(argument, ast.Constant) and isinstance(argument.value, str)
            if literal and _OWN_PREFIX_RE.match(argument.value):
                remember(params[index], argument.value)

    # Assignments LAST, and twice: an intermediate ("prom_name = f"…{key}"")
    # can only resolve once the loop and parameter bindings above exist.
    # Resolved too early it degrades to live_overlay_provider_<any>, which
    # then covers every leaf of that family and makes the guard toothless.
    for _pass in range(2):
        for node in ast.walk(tree):
            if not isinstance(node, ast.Assign) or len(node.targets) != 1:
                continue
            target = node.targets[0]
            if not isinstance(target, ast.Name):
                continue
            if isinstance(node.value, ast.JoinedStr):
                for spelled in _template_of(node.value, bindings)[:_MAX_BINDINGS]:
                    remember(target.id, spelled)
            # ``_prefix = "signals_producer"`` — the namespace without its
            # trailing underscore is a legitimate half-name.
            elif (
                isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, str)
                and re.match(r"^(live_overlay|signals_producer)", node.value.value)
            ):
                remember(target.id, node.value.value)
    return bindings


def _template_of(node: ast.JoinedStr, bindings: dict[str, str]) -> list[str]:
    """An f-string → every concrete witness name it can spell (often none).

    A name does not sit at a fixed place in the template. It leads an emit
    line (``f"{name}{{labels}} {value}"``), but it sits in the middle of a
    ``f"# TYPE {_prefix}_fmp_endpoint_requests_total counter"`` header — so
    every name-legal run is a candidate, not just the first. A run ending in
    the placeholder is a name with labels glued on, so its stem counts too.

    Two rejections keep the result from turning vacuous — which is what the
    mutation proof caught: a run must start in one of our namespaces, and it
    must contribute at least three literal characters beyond that namespace.
    ``f"{value:,}"`` contributes none and would otherwise be read as
    ``live_overlay_<anything>``.
    """
    alternatives: list[list[str]] = []
    saw_placeholder = False
    for value in node.values:
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            alternatives.append([value.value])
            continue
        saw_placeholder = True
        inner = value.value if isinstance(value, ast.FormattedValue) else None
        # ``f"live_overlay_provider_{_sanitize_name(key)}"`` — the exporter's
        # own naming function is part of the spelling, so follow it.
        if (
            isinstance(inner, ast.Call)
            and isinstance(inner.func, ast.Name)
            and inner.func.id == "_sanitize_name"
            and len(inner.args) == 1
            and isinstance(inner.args[0], ast.Name)
        ):
            sanitised = [v.replace(".", "_").replace("-", "_") for v in bindings.get(inner.args[0].id, [])]
            alternatives.append(sanitised[:_MAX_BINDINGS] if sanitised else [_WITNESS_TOKEN])
            continue
        bound = bindings.get(inner.id) if isinstance(inner, ast.Name) else None
        alternatives.append(list(bound)[:_MAX_BINDINGS] if bound else [_WITNESS_TOKEN])
    if not saw_placeholder:
        return []

    spellings = [""]
    for options in alternatives:
        spellings = [prefix + option for prefix in spellings for option in options][:_MAX_SPELLINGS]

    found: list[str] = []
    for spelling in spellings:
        for run in re.findall(r"[a-z0-9_]+", spelling):
            if not _OWN_PREFIX_RE.match(run):
                continue
            beyond = _OWN_PREFIX_RE.sub("", run).replace(_WITNESS_TOKEN, " ")
            if len(re.sub(r"[^a-z0-9]", "", beyond)) < 3:
                continue
            found.append(run)
            if run.endswith(_WITNESS_TOKEN):
                found.append(run[: -len(_WITNESS_TOKEN)].rstrip("_"))
    return found


def _panel_references() -> tuple[frozenset[str], tuple[str, ...]]:
    """What the dashboards point at: plain metric names, and ``__name__`` regexes.

    The two are separated on purpose. A ``{__name__=~"live_overlay_hotspot_symbol_.*"}``
    filter is not a metric name — reading it as one yields the truncated
    prefix ``live_overlay_hotspot_symbol_`` and three phantom gaps (measured
    2026-08-20). It is a *requirement over the family*, checked as such below.
    """
    names: set[str] = set()
    patterns: set[str] = set()
    for path in sorted(_GRAFANA.glob("dashboard*.json")):
        document = json.loads(path.read_text(encoding="utf-8"))

        def walk(node: Any) -> None:
            if isinstance(node, dict):
                expr = node.get("expr")
                if isinstance(expr, str) and expr.strip():
                    # Every QUOTED run is an argument, never a metric selector:
                    # __name__ filters, label_replace's regex, label values. A
                    # metric name a panel actually reads stands bare. Reading
                    # the quoted ones as names yields truncated prefixes such
                    # as live_overlay_hotspot_symbol_ (measured 2026-08-20).
                    for quoted in _QUOTED_RE.findall(expr):
                        if _OWN_METRIC_RE.search(quoted) and re.search(r"[.*+?()\[|]", quoted):
                            patterns.add(quoted)
                    names.update(_OWN_METRIC_RE.findall(_QUOTED_RE.sub(" ", expr)))
                for value in node.values():
                    walk(value)
            elif isinstance(node, list):
                for value in node:
                    walk(value)

        walk(document)
    return frozenset(names), tuple(sorted(patterns))


def _not_producible(names: Iterable[str], sources: Iterable[str]) -> list[str]:
    literals, composed, _ = _emittable(sources)
    return sorted(n for n in names if n not in literals and not any(rx.match(n) for rx in composed))


def test_every_dashboard_panel_metric_is_producible() -> None:
    """No panel may point at a metric name no exporter can spell.

    2026-08-20: 240 panel metrics across three dashboards, 0 unproducible.
    Under the alert fixture 33 of them render no series — every one of those
    turned out to be a family the fixture does not feed, not a dead panel.
    That distinction is why this check reads the exporters' source instead of
    the rendered body: enriching the fixture until all 240 render would make
    the guard a fixture-completeness test, not a panel test.
    """
    names, _ = _panel_references()
    assert len(names) >= 200, f"only {len(names)} panel metrics parsed — dashboard extraction broke"

    dead = _not_producible(names, _exporter_sources())
    assert not dead, (
        "dashboard panel(s) point at metric(s) no exporter can emit:\n  - "
        + "\n  - ".join(dead)
        + "\n\nEither the metric was renamed/removed and the panel still names the old "
        "one (fix the panel), or the exporter lost its write. A blind panel shows an "
        "empty graph, which reads as 'nothing is happening' rather than 'nobody is looking'."
    )


def test_every_panel_name_regex_matches_a_producible_family() -> None:
    """``{__name__=~"…"}`` panels must select a family that actually exists."""
    _, patterns = _panel_references()
    assert patterns, "no __name__ regex panels found — extraction broke (three existed on 2026-08-20)"

    _, _, witnesses = _emittable(_exporter_sources())
    # (?:…) around the pattern: a panel may select an alternation, and
    # "^a|b$" anchors only the first branch.
    orphaned = [p for p in patterns if not any(re.compile(f"^(?:{p})$").match(w) for w in witnesses)]
    assert not orphaned, (
        f"panel name-regex(es) match no metric this repo can emit: {orphaned} — "
        "the family was renamed or never existed"
    )


def test_a_dead_panel_is_actually_caught() -> None:
    """Mutation proof, in both directions.

    Without it the two checks above pass on any codebase: a matcher built from
    ~500 templates matches nearly anything, and an empty pattern list asserts
    nothing.
    """
    sources = _exporter_sources()
    invented = "live_overlay_a_metric_no_exporter_writes"
    assert _not_producible([invented], sources) == [invented], (
        "an invented metric name was considered producible — the matcher is too loose"
    )

    # One victim per derivation route that a panel depends on. Each is spelled
    # a different way in the exporter, and each hop below was added only after
    # this proof showed the route was load-bearing.
    for victim, spelling, route in (
        ("live_overlay_railway_service_cpu_cores", "live_overlay_railway_service_cpu_cores", "literal"),
        ("live_overlay_smc_live_requests_total", "live_overlay.smc_live_requests.total", "dotted counter key"),
        ("live_overlay_evidence_ledger_age_seconds", '"live_overlay_evidence_ledger_age"', "call-site stem"),
        # NOT news_health_degraded: the sibling template
        # f"live_overlay_provider_news_{provider}_degraded" happens to spell it
        # too, so removing its own route proves nothing. A generous matcher is
        # the price of following composed names — this check catches a whole
        # family going away, not one leaf inside a family that still exists.
        (
            "live_overlay_provider_news_snapshot_age_known",
            '"news_snapshot_age_known"',
            "loop over a literal tuple",
        ),
    ):
        assert not _not_producible([victim], sources), f"{victim} is expected to be producible today"
        without = [source.replace(spelling, "removed_by_this_test") for source in sources]
        assert _not_producible([victim], without) == [victim], (
            f"removing the {route} spelling of {victim} from the analysed source left it "
            "covered — that derivation route is not actually being read"
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
