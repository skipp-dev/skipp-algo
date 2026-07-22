"""Guard: every monitoring metric the exporter emits has a consumer.

The 2026-06/07 blind-spot had a precise shape: the daemon *exported*
per-workflow health gauges (``live_overlay_github_workflow_latest_success`` /
``phase_code`` / ``latest_age_seconds``) but **zero alert rules referenced
them**, so ``adr0023-magnitude-shadow-daily`` could go red for weeks while
Grafana stayed green. This test makes that class of gap fail CI:

* Part A — the per-workflow status signals MUST each be used by >= 1 alert rule.
* Part B — the evidence-chain freshness signals MUST each be used by >= 1 alert.
* Part C — no ``live_overlay_evidence_*`` / per-workflow metric may be emitted
  without at least one consumer (alert rule OR dashboard panel), so a future
  metric added with no watcher fails here instead of silently going invisible.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
import yaml

_REPO_ROOT = Path(__file__).resolve().parents[1]
_METRICS_PY = _REPO_ROOT / "services" / "live_overlay_daemon" / "metrics.py"
_GRAFANA = _REPO_ROOT / "services" / "live_overlay_daemon" / "infra" / "grafana"
_ALERT_RULES = _GRAFANA / "alert-rules.yaml"
_DASHBOARD = _GRAFANA / "dashboard.json"
# All dashboards are consumers: a metric charted only on a companion board
# still counts as watched, so scan every committed operations dashboard.
_DASHBOARDS = (
    _DASHBOARD,
    _GRAFANA / "dashboard-signals-experiments.json",
    _GRAFANA / "dashboard-pre-a0.json",
)

# Per-workflow status signals that had zero alert coverage (the exact gap).
_WORKFLOW_SIGNAL_METRICS = (
    "live_overlay_github_workflow_latest_success",
    "live_overlay_github_workflow_phase_code",
    "live_overlay_github_workflow_latest_age_seconds",
)

# Evidence-chain freshness signals that MUST alert (the silent-freeze detectors).
_EVIDENCE_SIGNAL_METRICS = (
    "live_overlay_evidence_freshness_loaded",
    "live_overlay_evidence_freshness_snapshot_age_seconds",
    "live_overlay_evidence_ledger_age_seconds",
    "live_overlay_evidence_audit_branch_age_seconds",
    "live_overlay_evidence_wsh_age_seconds",
)

# Credential / API-key health signals that MUST alert. These gauges were charted
# but had ZERO alert coverage while the probe's only alarm (a GitHub issue) was
# inert (repo Issues disabled) — an expired key surfaced nowhere. The per-probe
# ``_valid`` names are built by f-string in metrics.py, so _METRIC_RE cannot
# auto-discover them (it stops at ``{``); they are pinned explicitly like Part A/B.
_CREDENTIAL_SIGNAL_METRICS = (
    "live_overlay_credential_health_fmp_api_key_valid",
    "live_overlay_credential_health_databento_api_key_valid",
    "live_overlay_credential_health_databento_delivery_valid",
    "live_overlay_credential_health_benzinga_key_valid",
    "live_overlay_credential_health_finnhub_api_key_valid",
    "live_overlay_credential_health_github_pat_validity_valid",
    "live_overlay_credential_health_tv_storage_state_age_valid",
    "live_overlay_credential_health_snapshot_age_seconds",
    # The staleness gauge alone is not enough: it is only meaningful while
    # age_known == 1, so the age_known gauge needs its own watcher too (see
    # test_credential_health_age_unknown_has_alert_coverage).
    "live_overlay_credential_health_snapshot_age_known",
)

# Provider-usage FEED-HEALTH signals that MUST alert. The daemon exported
# ``live_overlay_provider_usage_loaded`` and ``...snapshot_age_seconds`` but
# nothing consumed them, so a missing/frozen ingest snapshot silently starved
# the FMP-quota + provider-429 alerts (all computed off that same snapshot)
# while they stayed on ``noDataState: OK``. Pin the feed-health gauges here so a
# dropped stale/missing rule fails CI instead of reopening the blind spot.
_PROVIDER_USAGE_SIGNAL_METRICS = (
    "live_overlay_provider_usage_loaded",
    "live_overlay_provider_usage_snapshot_age_seconds",
)

# Pine-library version-drift signals that MUST alert (#3599/#3603). The daemon
# exports the snapshot loaded/age gauges, the top-level drift rollup, and the
# facade-probe health; if any loses its alert rule a stale import pin (the
# ~4-month micro_profiles /1-vs-/152 blind spot) goes unwatched again. `_METRIC_RE`
# only auto-discovers evidence/workflow families, so pin these explicitly.
_PINE_LIBRARY_SIGNAL_METRICS = (
    "live_overlay_pine_library_snapshot_loaded",
    "live_overlay_pine_library_snapshot_age_seconds",
    "live_overlay_pine_library_any_drift",
    "live_overlay_pine_library_facade_ok",
)

# VIX enrichment signals that MUST have a watcher. Before 2026-07-21 the daemon
# polled ^VIX from FMP fail-soft (keep-last) but exported nothing: an FMP outage
# froze the payload's vix_level with NO operator signal (truth-audit finding F-2).
# The freshness pair must alert (lo-vix-unavailable) and the level must be
# charted; `_METRIC_RE` also auto-discovers the family for the orphan scan.
_VIX_SIGNAL_METRICS = (
    "live_overlay_vix_age_seconds",
    "live_overlay_vix_age_known",
)

_METRIC_RE = re.compile(r"live_overlay_(?:evidence|github_workflow|vix)_[a-z0-9_]+")


def _alert_expr_text() -> str:
    doc = yaml.safe_load(_ALERT_RULES.read_text(encoding="utf-8"))
    exprs: list[str] = []
    for group in doc.get("groups", []):
        for rule in group.get("rules", []):
            for node in rule.get("data", []):
                expr = (node.get("model") or {}).get("expr")
                if isinstance(expr, str):
                    exprs.append(expr)
    return "\n".join(exprs)


def _dashboard_expr_text() -> str:
    exprs: list[str] = []
    for dashboard in _DASHBOARDS:
        if not dashboard.exists():
            continue
        doc = json.loads(dashboard.read_text(encoding="utf-8"))
        for panel in doc.get("panels", []):
            for target in panel.get("targets", []) or []:
                expr = target.get("expr")
                if isinstance(expr, str):
                    exprs.append(expr)
    return "\n".join(exprs)


def _emitted_metrics() -> set[str]:
    """Metric names the exporter emits, discovered from metrics.py source.

    f-string fragments (a name interrupted by ``{...}``) end up with a trailing
    underscore after the regex stops at ``{`` — those are dropped; only fully
    literal metric names are asserted (which is all the evidence + per-workflow
    status metrics this guard cares about).
    """
    source = _METRICS_PY.read_text(encoding="utf-8")
    return {m for m in _METRIC_RE.findall(source) if not m.endswith("_")}


def test_per_workflow_signals_have_alert_coverage() -> None:
    """The exact 2026-06/07 gap: per-workflow health metrics must alert."""
    alerts = _alert_expr_text()
    missing = [m for m in _WORKFLOW_SIGNAL_METRICS if m not in alerts]
    assert not missing, (
        "per-workflow status metrics exist but NO alert rule references them "
        f"(the silent-red-cron gap): {missing}"
    )


def test_evidence_signals_have_alert_coverage() -> None:
    alerts = _alert_expr_text()
    missing = [m for m in _EVIDENCE_SIGNAL_METRICS if m not in alerts]
    assert not missing, f"evidence freshness signals lack alert coverage: {missing}"


def test_credential_signals_have_alert_coverage() -> None:
    """Every API-key health gauge + the snapshot-staleness gauge must alert.

    Prevents the credential-alerting gap from silently reopening: a new probe or
    a dropped alert rule that leaves a key gauge unwatched fails CI here.
    """
    alerts = _alert_expr_text()
    missing = [m for m in _CREDENTIAL_SIGNAL_METRICS if m not in alerts]
    assert not missing, f"credential/API-key health signals lack alert coverage: {missing}"


def test_provider_usage_feed_health_signals_have_alert_coverage() -> None:
    """Provider-usage feed-health gauges must alert, so a missing/frozen ingest
    snapshot cannot silently starve the FMP-quota + provider-429 alerts.
    """
    alerts = _alert_expr_text()
    missing = [m for m in _PROVIDER_USAGE_SIGNAL_METRICS if m not in alerts]
    assert not missing, f"provider-usage feed-health signals lack alert coverage: {missing}"


def test_pine_library_signals_have_alert_coverage() -> None:
    """Every Pine-library version-drift health gauge must alert, so a stale
    import pin or a frozen/blind facade probe cannot silently reopen the
    #3599/#3603 blind spot."""
    alerts = _alert_expr_text()
    missing = [m for m in _PINE_LIBRARY_SIGNAL_METRICS if m not in alerts]
    assert not missing, f"pine-library version-drift signals lack alert coverage: {missing}"


def test_vix_signals_have_alert_coverage() -> None:
    """The VIX freshness pair must alert and the level must be charted.

    The FMP ^VIX poll is fail-soft keep-last by design, so without a watcher an
    FMP outage is invisible while clients consume a frozen vix_level. The
    lo-vix-unavailable rule owns the freshness axis (sentinel form, so
    never-fetched fires too); the dashboard panel owns the level.
    """
    alerts = _alert_expr_text()
    missing = [m for m in _VIX_SIGNAL_METRICS if m not in alerts]
    assert not missing, f"VIX freshness signals lack alert coverage: {missing}"
    assert "live_overlay_vix_level" in _dashboard_expr_text(), (
        "live_overlay_vix_level is emitted but charted nowhere — the VIX panel "
        "vanished and the level is invisible again (truth-audit F-2)"
    )


def test_no_emitted_monitoring_metric_is_unconsumed() -> None:
    """Every emitted evidence/workflow metric must be alerted OR charted."""
    consumers = _alert_expr_text() + "\n" + _dashboard_expr_text()
    emitted = _emitted_metrics()
    # Sanity: discovery actually found the families (guards against a rename
    # silently emptying the set and making this test vacuously pass).
    assert any(m.startswith("live_overlay_evidence_") for m in emitted), emitted
    orphans = sorted(m for m in emitted if m not in consumers)
    assert not orphans, (
        "these monitoring metrics are emitted but referenced by no alert rule "
        f"and no dashboard panel — they are invisible: {orphans}"
    )


def test_sweep_trap_shadow_no_data_state_has_alert_coverage() -> None:
    """The gt-0-inert hole: a missing/unreadable snapshot (and the committed
    no-data seed) yields age_known=0 AND stale=0, so the gt-0 stale rule stays
    green with zero data. The dedicated age-unknown rule must exist, target the
    age_known gauge and use the `== bool 0` form (a bare `== 0` returns 0 and a
    gt-0 threshold reads 0>0=false — inert)."""
    rules = yaml.safe_load(_ALERT_RULES.read_text(encoding="utf-8"))
    exprs: dict[str, str] = {}
    for group in rules.get("groups", []):
        for rule in group.get("rules", []):
            for query in rule.get("data", []):
                expr = str((query.get("model") or {}).get("expr", ""))
                if expr:
                    exprs[str(rule.get("uid", ""))] = exprs.get(str(rule.get("uid", "")), "") + expr
    assert "lo-sweep-trap-shadow-age-unknown" in exprs
    expr = exprs["lo-sweep-trap-shadow-age-unknown"]
    assert "live_overlay_sweep_trap_shadow_snapshot_age_known" in expr
    assert "== bool 0" in expr


# Every evidence-chain age axis and the age_known gauge that says whether the
# age means anything. `_coerce` (evidence_freshness_bridge) hard-codes
# loaded=1.0 and tolerates missing keys, so a snapshot that PARSES but carries
# no date yields age_known=0 AND age_seconds=0 -- every `age > threshold` rule
# reads 0>N=false and lo-evidence-snapshot-unloadable reads loaded<1=false.
# Both stay green with zero data. That shape is not hypothetical: the GitHub
# Contents-API envelope produced exactly it ("EMPTY snapshot with loaded=1,
# keeping the stale alert silently green" -- _fetch_url, post-review finding
# 1). The cause was fixed; these rules close the DETECTION gap.
_EVIDENCE_AGE_UNKNOWN_RULES = (
    ("lo-evidence-snapshot-age-unknown", "live_overlay_evidence_freshness_snapshot_age_known"),
    ("lo-evidence-ledger-age-unknown", "live_overlay_evidence_ledger_age_known"),
    ("lo-evidence-audit-branch-age-unknown", "live_overlay_evidence_audit_branch_age_known"),
    ("lo-evidence-wsh-age-unknown", "live_overlay_evidence_wsh_age_known"),
)


def _rule_exprs() -> dict[str, str]:
    rules = yaml.safe_load(_ALERT_RULES.read_text(encoding="utf-8"))
    exprs: dict[str, str] = {}
    for group in rules.get("groups", []):
        for rule in group.get("rules", []):
            uid = str(rule.get("uid", ""))
            for query in rule.get("data", []):
                expr = str((query.get("model") or {}).get("expr", ""))
                if expr:
                    exprs[uid] = exprs.get(uid, "") + expr
    return exprs


def test_evidence_age_unknown_states_have_alert_coverage() -> None:
    """Each evidence age axis needs an age-unknown rule the stale rule cannot be.

    Stale is only computable once an age is KNOWN, so `age > threshold` can
    never fire on age_known=0 (it reads 0>N=false). Each axis therefore needs a
    dedicated rule on its age_known gauge, gated on `loaded` so an unloadable
    snapshot pages once (lo-evidence-snapshot-unloadable) rather than twice.
    """
    exprs = _rule_exprs()
    for uid, known_metric in _EVIDENCE_AGE_UNKNOWN_RULES:
        assert uid in exprs, f"{uid} is missing — the age-unknown state is unwatched"
        expr = exprs[uid]
        assert known_metric in expr, f"{uid} must target {known_metric}, got: {expr}"
        # `== bool 0` is mandatory: a bare `== 0` returns the value 0 and the
        # gt-0 threshold reads 0>0=false — inert (the gt-0-inert class).
        assert "== bool 0" in expr, f"{uid} must use `== bool 0` (bare `== 0` is inert): {expr}"
        assert "live_overlay_evidence_freshness_loaded" in expr, (
            f"{uid} must gate on the loaded gauge so an unloadable snapshot does not "
            f"double-page with lo-evidence-snapshot-unloadable: {expr}"
        )


def test_evidence_ledger_age_unknown_does_not_double_page_with_empty() -> None:
    """lo-evidence-ledger-empty already owns rows==0, so the ledger age-unknown
    rule must gate on rows>0 and cover only the state neither -stale (needs a
    KNOWN age) nor -empty (needs rows==0) can see."""
    expr = _rule_exprs()["lo-evidence-ledger-age-unknown"]
    assert "live_overlay_evidence_ledger_rows" in expr, expr
    assert "> bool 0" in expr, expr


def test_credential_health_age_unknown_has_alert_coverage() -> None:
    """The same gt-0-inert hole, one chain over — the follow-up #3659 deferred.

    A credential-health snapshot that LOADS but carries no parseable
    ``generated_at`` reports age_known=0 AND age_seconds=0, so neither existing
    rule can see it:

    - ``lo-credential-monitor-stale`` reads ``(0 * 0) > 129600`` = false. Note
      the ``* age_known`` factor (#3666) does NOT close this: it stops an
      unknown age from reading as fresh-and-stale, but 0 was already below the
      threshold, so the undated state stays silent either way.
    - ``lo-credential-snapshot-missing`` reads ``loaded == 0`` = false.

    Both green, zero data — the stale-green blind spot the monitor exists to
    prevent. The complement rule must exist, gate on ``_loaded`` so it cannot
    double-page with the missing-snapshot rule, and use the ``== bool 0`` form
    (a bare ``== 0`` returns 0 and a gt-0 threshold reads 0>0=false — inert).
    """
    exprs = _rule_exprs()
    assert "lo-credential-monitor-age-unknown" in exprs, (
        "the credential-health age-unknown rule is gone — a loaded-but-undated "
        "snapshot is invisible again (the stale rule cannot cover it)"
    )
    expr = exprs["lo-credential-monitor-age-unknown"]
    assert "live_overlay_credential_health_snapshot_age_known" in expr, expr
    assert "live_overlay_credential_health_loaded" in expr, (
        "must gate on the loaded gauge so a missing snapshot does not double-page "
        f"with lo-credential-snapshot-missing: {expr}"
    )
    assert "== bool 0" in expr, f"bare `== 0` is inert (0>0=false): {expr}"


def test_dashboard_age_panels_gate_on_age_known() -> None:
    """An age panel must not render an UNKNOWN age as a misleading `0`.

    `metrics.py` emits age_seconds=0.0 when the age is unknown and publishes the
    truth in a companion age_known gauge. A panel that plots age_seconds alone
    shows `0` — "perfectly fresh" — for "no data at all", and its `noValue`
    never fires because the series exists. "Magnitude Ledger Age (days)" is a
    stat with a red-at-3-days threshold, so unknown rendered as a GREEN 0.
    Gating on age_known empties the series instead, so noValue shows N/A.
    """
    panels_by_title = {}
    for dashboard in _DASHBOARDS:
        if not dashboard.exists():
            continue
        doc = json.loads(dashboard.read_text(encoding="utf-8"))
        for panel in doc.get("panels", []):
            panels_by_title[str(panel.get("title", ""))] = panel

    expected = {
        "Magnitude Ledger Age (days)": {
            "live_overlay_evidence_ledger_age_seconds": "live_overlay_evidence_ledger_age_known",
        },
        "Evidence Chain Age (days)": {
            "live_overlay_evidence_ledger_age_seconds": "live_overlay_evidence_ledger_age_known",
            "live_overlay_evidence_audit_branch_age_seconds": (
                "live_overlay_evidence_audit_branch_age_known"
            ),
            "live_overlay_evidence_wsh_age_seconds": "live_overlay_evidence_wsh_age_known",
            "live_overlay_evidence_freshness_snapshot_age_seconds": (
                "live_overlay_evidence_freshness_snapshot_age_known"
            ),
        },
        "News Snapshot Age": {
            "live_overlay_provider_news_snapshot_age_seconds": (
                "live_overlay_provider_news_snapshot_age_known"
            ),
        },
    }

    for title, axes in expected.items():
        panel = panels_by_title.get(title)
        assert panel is not None, f"panel {title!r} vanished — update this guard"
        exprs = [
            str(t.get("expr", ""))
            for t in (panel.get("targets") or [])
            if isinstance(t.get("expr"), str)
        ]
        for age_metric, known_metric in axes.items():
            using = [e for e in exprs if age_metric in e]
            assert using, f"{title!r} no longer plots {age_metric} — update this guard"
            for expr in using:
                assert known_metric in expr, (
                    f"{title!r} plots {age_metric} without gating on {known_metric}: an "
                    f"unknown age renders as a misleading 0. Got: {expr}"
                )
        no_value = (panel.get("fieldConfig") or {}).get("defaults", {}).get("noValue")
        assert no_value, (
            f"{title!r} gates on age_known (so an unknown age yields an EMPTY series) but "
            "sets no noValue text — the panel would render blank instead of N/A"
        )


def test_news_snapshot_stale_alert_gates_on_age_known() -> None:
    """The news snapshot stale rule must not read age_seconds=0 as fresh.

    A loaded snapshot without a timestamp exports age_known=0 and
    age_seconds=0. Without an age_known gate the stale rule's
    `age_seconds > 10800` reads false (0 > threshold) and the dashboard shows
    a perfectly fresh 0 while the producer heartbeat is actually unknown.
    """
    expr = _rule_exprs()["lo-news-snapshot-stale"]
    assert "live_overlay_provider_news_snapshot_age_known" in expr, (
        "lo-news-snapshot-stale must gate on age_known so an unknown timestamp "
        f"does not masquerade as fresh. Got: {expr}"
    )


_AGE_UNKNOWN_RULES = (
    # (rule_uid, loaded_metric, age_known_metric)
    (
        "lo-news-snapshot-age-unknown",
        "live_overlay_provider_news_snapshot_loaded",
        "live_overlay_provider_news_snapshot_age_known",
    ),
    (
        "lo-pine-library-snapshot-age-unknown",
        "live_overlay_pine_library_snapshot_loaded",
        "live_overlay_pine_library_snapshot_age_known",
    ),
    (
        "lo-provider-usage-snapshot-age-unknown",
        "live_overlay_provider_usage_loaded",
        "live_overlay_provider_usage_snapshot_age_known",
    ),
    (
        "lo-trading-signals-snapshot-age-unknown",
        "live_overlay_trading_signals_loaded",
        "live_overlay_trading_signals_snapshot_age_known",
    ),
    (
        "lo-experiment-snapshot-age-unknown",
        "live_overlay_experiment_loaded",
        "live_overlay_experiment_snapshot_age_known",
    ),
    (
        "lo-tradingview-credential-age-unknown",
        "live_overlay_tradingview_credential_loaded",
        "live_overlay_tradingview_credential_age_known",
    ),
)


@pytest.mark.parametrize("uid,loaded_metric,age_known_metric", _AGE_UNKNOWN_RULES)
def test_age_unknown_alert_coverage(
    uid: str, loaded_metric: str, age_known_metric: str
) -> None:
    """A loaded-but-undated snapshot needs its own alert.

    The unloadable rule owns loaded==0; the stale rule needs a known age. The
    loaded-but-undated state (age_known=0, age_seconds=0) is invisible to both
    unless a dedicated rule targets the age_known gauge with the `== bool 0`
    form (bare `== 0` is inert behind a gt-0 threshold).
    """
    exprs = _rule_exprs()
    assert uid in exprs, f"missing rule for loaded-but-undated snapshot: {uid}"
    expr = exprs[uid]
    assert age_known_metric in expr, (
        f"{uid} must target {age_known_metric}, got: {expr}"
    )
    assert loaded_metric in expr, (
        f"{uid} must gate on {loaded_metric} to avoid double-paging with the "
        f"unloadable rule, got: {expr}"
    )
    assert "== bool 0" in expr, (
        f"{uid} must use `== bool 0` (bare `== 0` is inert): {expr}"
    )


# warning < high < critical. Only the ORDER matters here, not the numbers.
_SEVERITY_RANK = {"warning": 1, "high": 2, "critical": 3}


def _rules_by_uid() -> dict[str, dict]:
    doc = yaml.safe_load(_ALERT_RULES.read_text(encoding="utf-8"))
    return {
        str(rule.get("uid", "")): rule
        for group in doc.get("groups", [])
        for rule in group.get("rules", [])
    }


def test_age_unknown_severity_never_below_its_stale_rule() -> None:
    """An `-age-unknown` rule must never page quieter than its `-stale` sibling.

    The two rules split one axis: `-stale` owns "the age is known and too old",
    `-age-unknown` owns "there is no age at all". The second is not the milder
    half. While age_known=0 the stale rule *cannot fire for that chain at all*
    (its `age_seconds * age_known` product is 0), so the whole freshness axis is
    gone rather than merely aged — strictly worse than a known-old snapshot, and
    it stays that way until a human fixes the producer. Ranking it below its
    stale sibling would route the worse state to the quieter channel.

    Discovered from the YAML rather than a hand list: a new `-age-unknown` rule
    is covered the moment it is added, and this cannot silently empty (a rename
    that broke discovery would trip the vacuity floor below).

    NOTE: deliberately says nothing about `for`. That is a per-rule tuning knob
    with no safety invariant behind it, and at least one rule documents a
    deliberate divergence (lo-sweep-trap-shadow-age-unknown holds 2h to ride out
    restarts while its stale sibling uses 30m). Freezing `for` here would
    override that reasoning, not protect it.
    """
    rules = _rules_by_uid()
    age_unknown = sorted(u for u in rules if u.endswith("-age-unknown"))
    assert len(age_unknown) >= 8, (
        "age-unknown rule discovery collapsed — a rename or restructure broke "
        f"the `-age-unknown` suffix convention, leaving this guard asserting on "
        f"almost nothing. Found: {age_unknown}"
    )

    checked = 0
    for uid in age_unknown:
        stale_uid = uid[: -len("-age-unknown")] + "-stale"
        stale = rules.get(stale_uid)
        if stale is None:
            # No stale sibling on this chain -> no floor to enforce.
            continue
        checked += 1
        got = str((rules[uid].get("labels") or {}).get("severity", ""))
        want = str((stale.get("labels") or {}).get("severity", ""))
        assert got in _SEVERITY_RANK, f"{uid} has unknown severity {got!r}"
        assert want in _SEVERITY_RANK, f"{stale_uid} has unknown severity {want!r}"
        assert _SEVERITY_RANK[got] >= _SEVERITY_RANK[want], (
            f"{uid} is severity={got} but its stale sibling {stale_uid} is "
            f"severity={want}. The undated state is worse, not milder: while "
            f"age_known=0 the stale rule cannot fire at all, so this rule is the "
            f"only thing watching that chain's freshness. Raise it to at least "
            f"{want}."
        )

    assert checked >= 8, (
        "the age-unknown -> stale pairing collapsed — the `-stale` sibling "
        f"convention broke, so the floor was enforced on only {checked} rule(s)"
    )


# Mirrors scripts/grafana_alert_rules_upsert.MAX_UID_LENGTH. Asserted here too
# because this file is on the required fast-gates path while the upsert tests
# are not — an over-long uid must be unmergeable, not merely un-deployable.
_MAX_UID_LENGTH = 40


def test_no_alert_rule_uid_exceeds_grafana_limit() -> None:
    """An over-long uid does not just drop its own rule — it strands the rest.

    Grafana 400s a uid over 40 chars, and the upsert applies group-by-group, so
    the abort leaves every LATER group at its previous content: a partial apply,
    silently. #3510 landed `lo-provider-usage-snapshot-series-missing` (41
    chars) on 2026-07-13; for two days every publish run failed on it, so
    #3665's credential-health group and two of #3671's three age-unknown rules
    never reached Grafana — while both PRs merged green and the repo looked
    correct. That is the silent non-alarm this file exists to prevent, one
    layer down: the rule was authored, reviewed, merged, and never armed.
    """
    groups = yaml.safe_load(_ALERT_RULES.read_text(encoding="utf-8"))["groups"]
    offenders = [
        (rule["uid"], len(rule["uid"]), group["name"])
        for group in groups
        for rule in group["rules"]
        if len(rule.get("uid", "")) > _MAX_UID_LENGTH
    ]
    assert not offenders, (
        f"alert rule uid(s) exceed Grafana's {_MAX_UID_LENGTH}-char limit — the "
        "upsert will HTTP 400 and leave every later group unapplied:\n"
        + "\n".join(f"  {n:>3} chars: {u}  [group: {g}]" for u, n, g in offenders)
    )


# Mirrors scripts/grafana_alert_rules_upsert.UID_CHARSET_RE, and duplicated for
# the same reason as _MAX_UID_LENGTH above: this file is required, the upsert
# tests are not, so the contract must be unmergeable here rather than merely
# un-deployable there. Both copies are deliberately independent — a test that
# asserted the two constants merely AGREE would stay green if both drifted to
# something wrong together, which is the failure it would exist to catch.
_UID_CHARSET_RE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")


def test_alert_rule_uids_stay_in_the_portable_charset() -> None:
    """A look-alike character is invisible to every other uid check.

    The length guard above cannot see this one: swap the ASCII hyphen in
    `lo-credential-monitor-stale` for a typographic en-dash (U+2013) and the uid
    is the SAME 27 characters, renders almost identically in a review diff, and
    is a distinct string — so the uniqueness check reads it as an unrelated rule
    rather than a duplicate. It sails through to Grafana, which then either 400s
    a rule that looks correct, or accepts it as a SEPARATE rule and leaves the
    hyphenated original orphaned, firing forever, while CI and the publish run
    both stay green.

    Not hypothetical in this repo: the alert YAML is authored by agents and
    pasted between rendered Markdown, Slack and Outlook, all of which autocorrect
    hyphens into dashes.

    This is a REPO-LOCAL contract, not a claim about Grafana's charset rules
    (which the observed HTTP 400 surface does not document). It is deliberately
    narrower than whatever Grafana accepts: it freezes the lived `lo-…` naming
    convention and keeps len() an unambiguous stand-in for Grafana's "symbols"
    count, which only coincides for ASCII.
    """
    groups = yaml.safe_load(_ALERT_RULES.read_text(encoding="utf-8"))["groups"]
    rules = [(r, g["name"]) for g in groups for r in g["rules"]]
    assert len(rules) >= 90, (
        f"uid discovery collapsed — only {len(rules)} rule(s) found, so this "
        "guard would be asserting on almost nothing"
    )
    offenders = [
        (rule["uid"], group, [c for c in rule["uid"] if not re.fullmatch(r"[a-z0-9-]", c)])
        for rule, group in rules
        if not _UID_CHARSET_RE.fullmatch(str(rule.get("uid", "")))
    ]
    assert not offenders, (
        "alert rule uid(s) leave the portable [a-z0-9] + '-' subset. A look-alike "
        "character passes the length and uniqueness checks and reaches Grafana:\n"
        + "\n".join(f"  {u!r}  [group: {g}]  offending: {o}" for u, g, o in offenders)
    )
