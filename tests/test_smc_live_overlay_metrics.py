"""Unit tests for services.live_overlay_daemon.metrics.

Covers:
- Prometheus text formatting basics
- market-aware health status gauges
- non-finite sanitization in metrics rendering
- non-finite rejection in observability primitives
"""

from __future__ import annotations

import json
import math
import re
import time
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _reset_compute_news_loader_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    """Avoid cross-test bleed from compute._load_news_snapshot() TTL globals."""
    import services.live_overlay_daemon.compute as compute_mod

    monkeypatch.setattr(compute_mod.config, "news_snapshot_url", lambda: "")
    monkeypatch.setattr(compute_mod, "_news_loaded_at", 0.0)
    monkeypatch.setattr(compute_mod, "_news_checked_at", 0.0)
    monkeypatch.setattr(compute_mod, "_news_cache", {})


def test_sanitize_name_rejects_invalid_prometheus_characters() -> None:
    import services.live_overlay_daemon.metrics as metrics_mod

    assert metrics_mod._sanitize_name("  AAPL/US @NASDAQ  ") == "aapl_us_nasdaq"
    assert metrics_mod._sanitize_name("BTC-USD.PERP") == "btc_usd_perp"
    assert metrics_mod._sanitize_name("__$$$__") == "unknown"


def test_sanitize_name_prefixes_leading_digits() -> None:
    """Prometheus metric names must not start with a digit.

    Prefixing with ``_`` preserves semantic digits (timeframe ``5m``,
    monitor id ``803343156``) instead of stripping them and creating
    collisions.
    """
    import services.live_overlay_daemon.metrics as metrics_mod

    assert metrics_mod._sanitize_name("123ABC") == "_123abc"
    assert metrics_mod._sanitize_name("1e9-symbol") == "_1e9_symbol"
    assert metrics_mod._sanitize_name("456") == "_456"
    assert metrics_mod._sanitize_name("00_abc") == "_00_abc"
    assert metrics_mod._sanitize_name("5m") == "_5m"
    assert metrics_mod._sanitize_name("15m") == "_15m"


def test_sanitize_name_collapses_runs_of_separators() -> None:
    import services.live_overlay_daemon.metrics as metrics_mod

    assert metrics_mod._sanitize_name("A..B---C") == "a_b_c"


def _patch_common(
    monkeypatch: pytest.MonkeyPatch,
    *,
    feed_ready: bool,
    market_open: bool,
    bar_count: int,
    overlay_symbols: int,
    overlay_age: float,
    workers: dict[str, bool] | None = None,
    last_bar_age: float | None = 5.0,
) -> None:
    import services.live_overlay_daemon.cache as cache
    import services.live_overlay_daemon.config as config
    import services.live_overlay_daemon.feed as feed
    import services.live_overlay_daemon.metrics as metrics_mod

    monkeypatch.setattr(feed, "is_ready", lambda: feed_ready)
    monkeypatch.setattr(feed, "last_bar_age_secs", lambda: last_bar_age)
    monkeypatch.setattr(
        feed,
        "worker_liveness",
        lambda: (
            workers
            or {
                "live_feed": True,
                "overlay_refresh": True,
                "flow_refresh": True,
            }
        ),
    )
    monkeypatch.setattr(
        feed,
        "metrics_snapshot",
        lambda: {
            "reconnect_attempts": 2,
            "bento_errors": 1,
            "unexpected_errors": 0,
            "circuit_breakers": 0,
            "partial_restarts": 0,
        },
    )
    monkeypatch.setattr(
        feed,
        "backpressure_snapshot",
        lambda: {
            "ingest_queue_depth": 0.0,
            "ingest_queue_depth_max": 3.0,
            "ingest_queue_dropped_total": 1.0,
            "ingest_queue_lag_ms_last": 7.5,
            "ingest_queue_lag_ms_max": 35.0,
        },
    )
    monkeypatch.setattr(
        metrics_mod,
        "_provider_health_snapshot",
        lambda: {
            "news_snapshot_loaded": 1.0,
            "news_snapshot_age_seconds": 42.0,
            "news_providers_total": 3.0,
            "news_providers_ok_total": 1.0,
            "news_providers_degraded_total": 1.0,
            "news_providers_unknown_total": 0.0,
            "news_providers_disabled_total": 1.0,
            "news_providers_consumed_total": 2.0,
            "news_health_ok": 0.0,
            "news_health_degraded": 1.0,
            "news_health_unknown": 0.0,
            "news_provider_ok": {"newsapi_ai": 1.0, "tv": 0.0, "benzinga": 0.0},
            "news_provider_degraded": {"newsapi_ai": 0.0, "tv": 1.0, "benzinga": 0.0},
            "news_provider_state_code": {"newsapi_ai": 2.0, "tv": 1.0, "benzinga": 3.0},
            "news_provider_consumed": {"newsapi_ai": 1.0, "tv": 1.0, "benzinga": 0.0},
            "news_provider_info": [
                {"provider": "newsapi_ai", "state": "ok", "reason": "OK", "consumed": "true"},
                {"provider": "tv", "state": "degraded", "reason": "API key missing", "consumed": "true"},
                {
                    "provider": "benzinga",
                    "state": "disabled",
                    "reason": "Provider disabled (not ingested)",
                    "consumed": "false",
                },
            ],
        },
    )

    monkeypatch.setattr(cache, "overlay_symbol_count", lambda: overlay_symbols)
    monkeypatch.setattr(cache, "bar_symbol_count", lambda: max(overlay_symbols, 1))
    monkeypatch.setattr(cache, "total_bar_count", lambda: bar_count)
    monkeypatch.setattr(cache, "overlay_age_secs", lambda: overlay_age)

    monkeypatch.setattr(config, "max_stale_secs", lambda: 300)
    monkeypatch.setattr(metrics_mod, "is_us_regular_session_open", lambda: market_open)
    monkeypatch.setattr(metrics_mod, "is_europe_regular_session_open", lambda: False)
    monkeypatch.setattr(metrics_mod, "is_asia_regular_session_open", lambda: False)


def test_render_metrics_prometheus_format_and_trailing_newline(monkeypatch: pytest.MonkeyPatch) -> None:
    import services.live_overlay_daemon.metrics as metrics_mod
    import services.live_overlay_daemon.observability as obs

    _patch_common(
        monkeypatch,
        feed_ready=True,
        market_open=True,
        bar_count=10,
        overlay_symbols=5,
        overlay_age=60.0,
    )

    with obs._counter_lock:
        obs._counters.clear()
        obs._counters["live_overlay.health_requests.total"] = 3.0

    body = metrics_mod.render_metrics(startup_ts=100.0)

    assert body.endswith("\n")
    assert "# TYPE live_overlay_health_requests_total counter" in body
    assert "live_overlay_health_requests_total 3.0" in body
    assert "# TYPE live_overlay_uptime_seconds gauge" in body
    assert "# TYPE live_overlay_max_stale_seconds gauge" in body
    assert "live_overlay_max_stale_seconds 300" in body
    assert body.count("# TYPE live_overlay_max_stale_seconds gauge") == 1
    assert body.count("live_overlay_max_stale_seconds 300") == 1
    assert "live_overlay_feed_ingest_queue_depth 0.0" in body
    assert "# TYPE live_overlay_feed_ingest_queue_dropped_total counter" in body
    assert "live_overlay_feed_ingest_queue_dropped_total 1.0" in body
    assert "live_overlay_feed_ingest_queue_lag_ms_max 35.0" in body
    assert "live_overlay_provider_news_snapshot_loaded 1.0" in body
    assert "live_overlay_provider_news_providers_degraded_total 1.0" in body
    assert "live_overlay_provider_news_health_degraded 1.0" in body
    assert "live_overlay_provider_news_newsapi_ai_ok 1.0" in body
    assert "live_overlay_provider_news_tv_degraded 1.0" in body
    assert "live_overlay_provider_news_tv_state_code 1.0" in body
    assert "live_overlay_provider_news_providers_disabled_total 1.0" in body
    assert "live_overlay_provider_news_providers_consumed_total 2.0" in body
    assert "live_overlay_provider_news_benzinga_state_code 3.0" in body
    assert "live_overlay_provider_news_benzinga_consumed 0.0" in body
    assert "live_overlay_provider_news_newsapi_ai_consumed 1.0" in body
    assert (
        'live_overlay_provider_news_info{provider="benzinga",state="disabled",'
        'reason="Provider disabled (not ingested)",consumed="false"} 1' in body
    )
    assert (
        'live_overlay_provider_news_info{provider="tv",state="degraded",'
        'reason="API key missing",consumed="true"} 1' in body
    )
    # Evidence-freshness gauges are always emitted (fail-soft to loaded=0 when
    # no snapshot is present), so the ADR-0023 chain-freshness alerts always
    # have a series to evaluate.
    assert "# TYPE live_overlay_evidence_freshness_loaded gauge" in body
    assert "# TYPE live_overlay_evidence_ledger_age_seconds gauge" in body
    assert "# TYPE live_overlay_evidence_audit_branch_age_seconds gauge" in body
    assert "# TYPE live_overlay_evidence_fills_closed_total gauge" in body
    # submit_failed_total powers lo-evidence-submit-failed (dead brackets), and
    # the submit-code-behind gauges power lo-c13-submitter-stale-checkout.
    assert "# TYPE live_overlay_evidence_fills_submit_failed_total gauge" in body
    assert "# TYPE live_overlay_evidence_c13_submit_code_behind_commits gauge" in body
    assert "# TYPE live_overlay_evidence_c13_submit_code_behind_commits_known gauge" in body
    # Newest-incubation age powers lo-evidence-incubation-fills-stalled: it
    # distinguishes "submitting but nothing fills" from "no trading at all".
    assert "# TYPE live_overlay_evidence_fills_newest_incubation_age_seconds gauge" in body
    assert "live_overlay_evidence_ledger_info{plane=" in body
    # §2/§5 per-family sample-progress gauge (the real distance to §5).
    assert "# TYPE live_overlay_evidence_samples_target gauge" in body
    # WS4a sweep-trap shadow gauges are always emitted (fail-soft to loaded=0),
    # so lo-sweep-trap-shadow-stale always has a series to evaluate.
    assert "# TYPE live_overlay_sweep_trap_shadow_loaded gauge" in body
    assert "# TYPE live_overlay_sweep_trap_shadow_snapshot_stale gauge" in body
    assert "# TYPE live_overlay_sweep_trap_shadow_verdict_code gauge" in body


def test_render_metrics_emits_submit_failed_and_stale_checkout_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The submit-failed count and the submitter behind-commits reading flow from
    the evidence snapshot into their gauges (dead-bracket + deploy-gap)."""
    import services.live_overlay_daemon.metrics as metrics_mod

    snap = {
        "loaded": 1.0,
        "generated_at_unix": 1_783_000_000.0,
        "ledger": {"newest_date": "", "plane": "", "rows": 0, "candidate_pass": 0},
        "audit_branch": {"last_commit_date": ""},
        "samples": {"target": 0, "per_family": {}},
        "fills": {
            "filled_cumulative": 0,
            "closed_cumulative": 0,
            "submit_failed_cumulative": 4,
            "target": 40,
            "newest_incubation_date": "2026-07-08",
        },
        "wsh": {"newest_date": "", "status": ""},
        "submitter": {"submit_code_behind_commits": 7, "known": 1},
        "error": "",
    }
    monkeypatch.setattr(metrics_mod.evidence_freshness_bridge, "snapshot", lambda: snap)

    body = "\n".join(metrics_mod._render_evidence_freshness_metrics())
    assert "live_overlay_evidence_fills_submit_failed_total 4.0" in body
    assert "live_overlay_evidence_c13_submit_code_behind_commits 7.0" in body
    assert "live_overlay_evidence_c13_submit_code_behind_commits_known 1.0" in body


def _sweep_trap_snap(**overrides: object) -> dict:
    snap = {
        "loaded": 1.0,
        "generated_at_unix": 0.0,
        "date": "2026-07-11",
        "n_samples": 55.0,
        "min_samples": 40.0,
        "brier_signal": 0.20,
        "brier_baseline": 0.231,
        "brier_delta": 0.031,
        "lift": 0.12,
        "verdict": "PROMOTABLE",
        "verdict_code": 2.0,
        "error": "",
    }
    snap.update(overrides)
    return snap


def test_render_metrics_emits_sweep_trap_shadow_values(monkeypatch: pytest.MonkeyPatch) -> None:
    """The WS4a shadow snapshot (Brier-delta, lift, sample accrual, verdict) flows
    into its gauges; a fresh snapshot is not stale."""
    import time

    import services.live_overlay_daemon.metrics as metrics_mod

    snap = _sweep_trap_snap(generated_at_unix=time.time() - 60.0)
    monkeypatch.setattr(metrics_mod.sweep_trap_shadow_bridge, "snapshot", lambda: snap)

    body = "\n".join(metrics_mod._render_sweep_trap_shadow_metrics())
    assert "live_overlay_sweep_trap_shadow_loaded 1.0" in body
    assert "live_overlay_sweep_trap_shadow_brier_signal 0.2" in body
    assert "live_overlay_sweep_trap_shadow_brier_baseline 0.231" in body
    assert "live_overlay_sweep_trap_shadow_brier_delta 0.031" in body
    assert "live_overlay_sweep_trap_shadow_lift 0.12" in body
    assert "live_overlay_sweep_trap_shadow_sample_count 55.0" in body
    assert "live_overlay_sweep_trap_shadow_min_samples 40.0" in body
    assert 'live_overlay_sweep_trap_shadow_verdict_code{verdict="PROMOTABLE"} 2.0' in body
    assert 'metric="Valid samples",metric_value="55",assessment="Sample floor met"' in body
    assert 'metric="Brier Baseline",metric_value="0.231000",assessment="not better than signal"' in body
    assert 'metric="Verdict",metric_value="PROMOTABLE",assessment="promotable"' in body
    # idx labels pin the table's display order via the dashboard sortBy transform;
    # they are zero-padded so Grafana's lexicographic sort keeps numeric order.
    assert 'idx="00",metric="Valid samples"' in body
    assert 'idx="05",metric="Verdict"' in body
    assert "live_overlay_sweep_trap_shadow_snapshot_age_known 1.0" in body
    assert "live_overlay_sweep_trap_shadow_snapshot_stale 0.0" in body


def test_render_metrics_evidence_table_marks_empty_corpus_inconclusive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With no evaluated corpus the evidence table must show "—", not assert
    a failed gate on data that was never computed."""
    import services.live_overlay_daemon.metrics as metrics_mod

    snap = _sweep_trap_snap(
        date="",
        n_samples=0.0,
        min_samples=40.0,
        brier_signal=0.0,
        brier_baseline=0.0,
        brier_delta=0.0,
        lift=0.0,
        verdict="INCONCLUSIVE",
        verdict_code=0.0,
    )
    monkeypatch.setattr(metrics_mod.sweep_trap_shadow_bridge, "snapshot", lambda: snap)

    body = "\n".join(metrics_mod._render_sweep_trap_shadow_metrics())
    # Loaded empty corpus: samples honestly fail the floor and verdict explains
    # that no decision can be made; computed-score rows remain neutral.
    assert 'metric="Valid samples",metric_value="0",assessment="Sample floor not met"' in body
    assert 'metric="Brier Baseline",metric_value="—",assessment="—"' in body
    assert 'metric="Brier Delta",metric_value="—",assessment="—"' in body
    assert 'metric="Tercile Lift",metric_value="—",assessment="—"' in body
    assert 'metric="Verdict",metric_value="INCONCLUSIVE",assessment="no decision possible"' in body
    # It must NOT claim a gate verdict when there is no corpus.
    assert "Gate failed" not in body
    assert "not better than signal" not in body


def test_render_metrics_evidence_table_marks_unavailable_snapshot_unknown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A missing snapshot is unknown, not an evaluated zero-sample corpus."""
    import services.live_overlay_daemon.metrics as metrics_mod

    snap = _sweep_trap_snap(
        loaded=0.0,
        date="",
        n_samples=0.0,
        min_samples=0.0,
        verdict="",
        verdict_code=0.0,
    )
    monkeypatch.setattr(metrics_mod.sweep_trap_shadow_bridge, "snapshot", lambda: snap)

    body = "\n".join(metrics_mod._render_sweep_trap_shadow_metrics())
    assert 'metric="Valid samples",metric_value="—",assessment="—"' in body
    assert 'metric="Verdict",metric_value="—",assessment="—"' in body


@pytest.mark.parametrize("n_samples", [float("nan"), float("inf"), float("-inf")])
def test_render_metrics_evidence_table_sanitizes_non_finite_sample_count(
    monkeypatch: pytest.MonkeyPatch,
    n_samples: float,
) -> None:
    """A corrupt sample count must not take down the whole metrics render."""
    import services.live_overlay_daemon.metrics as metrics_mod

    snap = _sweep_trap_snap(n_samples=n_samples, verdict="INCONCLUSIVE", verdict_code=0.0)
    monkeypatch.setattr(metrics_mod.sweep_trap_shadow_bridge, "snapshot", lambda: snap)

    body = "\n".join(metrics_mod._render_sweep_trap_shadow_metrics())
    assert "live_overlay_sweep_trap_shadow_sample_count nan" in body
    assert 'metric="Valid samples",metric_value="—",assessment="—"' in body
    assert 'metric="Verdict",metric_value="INCONCLUSIVE",assessment="no decision possible"' in body


def test_render_metrics_evidence_table_shows_brier_but_dashes_lift_below_tercile_floor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With data but fewer than 6 samples the Brier rows carry real values while
    the tercile-lift row stays "—" (mirrors the evaluator's own n>=6 floor)."""
    import services.live_overlay_daemon.metrics as metrics_mod

    snap = _sweep_trap_snap(
        date="2026-07-16",
        n_samples=4.0,
        min_samples=40.0,
        brier_signal=0.18,
        brier_baseline=0.20,
        brier_delta=0.02,
        lift=0.0,  # evaluator returns None below 6 samples; the bridge coerces to 0.0
        verdict="INCONCLUSIVE",
        verdict_code=0.0,
    )
    monkeypatch.setattr(metrics_mod.sweep_trap_shadow_bridge, "snapshot", lambda: snap)

    body = "\n".join(metrics_mod._render_sweep_trap_shadow_metrics())
    # Data present: Brier rows show real numbers and real assessments.
    assert 'metric="Valid samples",metric_value="4",assessment="Sample floor not met"' in body
    assert 'metric="Brier Signal",metric_value="0.180000"' in body
    assert 'metric="Brier Baseline",metric_value="0.200000",assessment="not better than signal"' in body
    assert 'metric="Brier Delta",metric_value="+0.020000",assessment="Gate passed"' in body
    assert 'metric="Verdict",metric_value="INCONCLUSIVE",assessment="no decision possible"' in body
    # Too few samples for terciles: the lift row must NOT fabricate +0.000000/nicht positiv.
    assert 'metric="Tercile Lift",metric_value="—",assessment="—"' in body
    assert "not positive" not in body


def test_evidence_table_dashboard_sorts_and_renames_only_emitted_labels(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The dashboard's sortBy field and every renamed evidence column must be a
    label the metric actually emits. Emitter and consumer are otherwise pinned by
    two separate tests, so a one-sided rename would leave both green while the
    table silently stops sorting or loses a column — this couples the two sides."""
    import services.live_overlay_daemon.metrics as metrics_mod

    snap = _sweep_trap_snap()
    monkeypatch.setattr(metrics_mod.sweep_trap_shadow_bridge, "snapshot", lambda: snap)
    body = "\n".join(metrics_mod._render_sweep_trap_shadow_metrics())

    emitted_labels: set[str] = set()
    for line in body.splitlines():
        if line.startswith("live_overlay_sweep_trap_shadow_evidence_info{"):
            label_block = line.split("{", 1)[1].rsplit("}", 1)[0]
            emitted_labels.update(re.findall(r'(\w+)="', label_block))
    assert emitted_labels, "evidence_info metric emitted no labelled series"

    dashboard = json.loads(
        (
            Path(__file__).resolve().parents[1]
            / "services"
            / "live_overlay_daemon"
            / "infra"
            / "grafana"
            / "dashboard-signals-experiments.json"
        ).read_text(encoding="utf-8")
    )
    panel = next(
        p for p in dashboard["panels"] if p.get("title") == "Latest Sweep-Trap Evidence"
    )
    sort_by = next(t for t in panel["transformations"] if t["id"] == "sortBy")
    organize = next(t for t in panel["transformations"] if t["id"] == "organize")

    sort_field = sort_by["options"]["sort"][0]["field"]
    assert sort_field in emitted_labels, (
        f"dashboard sorts the evidence table by {sort_field!r} but the metric never emits it"
    )
    for column in organize["options"]["renameByName"]:
        assert column in emitted_labels, (
            f"dashboard renames {column!r} but the metric never emits it as a label"
        )


def test_sweep_trap_shadow_stale_gauge_fires_past_max_age(monkeypatch: pytest.MonkeyPatch) -> None:
    """The precomputed stale gauge flips to 1 once the snapshot is older than the
    96h max-age budget — the alertable 0/1 that dodges the gt-0-inert trap."""
    import time

    import services.live_overlay_daemon.metrics as metrics_mod

    snap = _sweep_trap_snap(generated_at_unix=time.time() - 200 * 3600, verdict="SHADOW", verdict_code=1.0)
    monkeypatch.setattr(metrics_mod.sweep_trap_shadow_bridge, "snapshot", lambda: snap)

    body = "\n".join(metrics_mod._render_sweep_trap_shadow_metrics())
    assert "live_overlay_sweep_trap_shadow_snapshot_stale 1.0" in body


def test_sweep_trap_shadow_no_data_seed_is_not_stale(monkeypatch: pytest.MonkeyPatch) -> None:
    """generated_at 0 (the committed no-data seed) → age unknown → stale stays 0,
    so the alert does not false-fire before the first real run publishes."""
    import services.live_overlay_daemon.metrics as metrics_mod

    snap = _sweep_trap_snap(generated_at_unix=0.0, verdict="INCONCLUSIVE", verdict_code=0.0, n_samples=0.0)
    monkeypatch.setattr(metrics_mod.sweep_trap_shadow_bridge, "snapshot", lambda: snap)

    body = "\n".join(metrics_mod._render_sweep_trap_shadow_metrics())
    assert "live_overlay_sweep_trap_shadow_snapshot_age_known 0.0" in body
    assert "live_overlay_sweep_trap_shadow_snapshot_stale 0.0" in body


def test_render_metrics_health_status_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    import services.live_overlay_daemon.metrics as metrics_mod

    _patch_common(
        monkeypatch,
        feed_ready=True,
        market_open=True,
        bar_count=10,
        overlay_symbols=3,
        overlay_age=30.0,
    )

    body = metrics_mod.render_metrics(startup_ts=100.0)
    assert "live_overlay_overlay_fresh 1" in body
    assert "live_overlay_health_status_code 3" in body
    assert 'live_overlay_health_status_info{status="ok"} 1' in body
    assert "live_overlay_market_us_open 1" in body
    assert "live_overlay_market_europe_open 0" in body
    assert "live_overlay_market_asia_open 0" in body


def test_render_metrics_region_open_gauges(monkeypatch: pytest.MonkeyPatch) -> None:
    import services.live_overlay_daemon.metrics as metrics_mod

    _patch_common(
        monkeypatch,
        feed_ready=True,
        market_open=False,
        bar_count=10,
        overlay_symbols=3,
        overlay_age=30.0,
    )
    monkeypatch.setattr(metrics_mod, "is_europe_regular_session_open", lambda: True)
    monkeypatch.setattr(metrics_mod, "is_asia_regular_session_open", lambda: False)

    body = metrics_mod.render_metrics(startup_ts=100.0)

    assert "live_overlay_market_us_open 0" in body
    assert "live_overlay_market_europe_open 1" in body
    assert "live_overlay_market_asia_open 0" in body


def test_render_metrics_health_status_idle_market_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    import services.live_overlay_daemon.metrics as metrics_mod

    _patch_common(
        monkeypatch,
        feed_ready=False,
        market_open=False,
        bar_count=0,
        overlay_symbols=0,
        overlay_age=float("inf"),
    )

    body = metrics_mod.render_metrics(startup_ts=100.0)
    assert "live_overlay_health_status_code 2" in body
    assert 'live_overlay_health_status_info{status="idle_market_closed"} 1' in body


def test_render_metrics_health_status_starting(monkeypatch: pytest.MonkeyPatch) -> None:
    import services.live_overlay_daemon.metrics as metrics_mod

    _patch_common(
        monkeypatch,
        feed_ready=False,
        market_open=True,
        bar_count=0,
        overlay_symbols=0,
        overlay_age=float("inf"),
    )

    # Fresh boot (uptime < warmup): a non-ok state during the open session is
    # still "starting", not "degraded".
    # Pin monotonic: on a fresh CI runner time.monotonic() is only minutes
    # old, so "now - X" can go NEGATIVE and render_metrics' `startup_ts > 0`
    # guard silently zeroes the uptime (the F-3 degraded test failed on every
    # main full-CI run this way while passing on long-booted dev machines).
    now = 1_000_000.0
    monkeypatch.setattr(metrics_mod.time, "monotonic", lambda: now)
    body = metrics_mod.render_metrics(startup_ts=now - 30.0)
    assert "live_overlay_health_status_code 1" in body
    assert 'live_overlay_health_status_info{status="starting"} 1' in body


def test_render_metrics_health_status_degraded_past_warmup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A market-open failure that outlives warmup must not read as boot noise.

    Before the degraded state, a multi-hour feed outage rendered the same
    status_code 1 / "starting" as a 30-second-old boot (truth-audit
    2026-07-22 F-3), so dashboards reported outages as perpetual startups.
    """
    import services.live_overlay_daemon.metrics as metrics_mod

    _patch_common(
        monkeypatch,
        feed_ready=False,
        market_open=True,
        bar_count=0,
        overlay_symbols=0,
        overlay_age=float("inf"),
    )

    now = 1_000_000.0  # pinned: epoch-independent uptime (see warmup test above)
    monkeypatch.setattr(metrics_mod.time, "monotonic", lambda: now)
    body = metrics_mod.render_metrics(startup_ts=now - 3600.0)
    assert "live_overlay_health_status_code 4" in body
    assert 'live_overlay_health_status_info{status="degraded"} 1' in body


def test_render_metrics_market_closed_failure_stays_starting_not_degraded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Outside the US session a long-lived non-idle failure keeps "starting".

    "degraded" is deliberately market-open-gated: overnight the feed is
    expected to be quiet (bars age out, feed_healthy drops with bar_count > 0),
    and the 24/7 age alerts own genuine overnight compute hangs.
    """
    import services.live_overlay_daemon.metrics as metrics_mod

    _patch_common(
        monkeypatch,
        feed_ready=False,
        market_open=False,
        bar_count=10,
        overlay_symbols=0,
        overlay_age=float("inf"),
    )

    now = 1_000_000.0  # pinned: epoch-independent uptime (see warmup test above)
    monkeypatch.setattr(metrics_mod.time, "monotonic", lambda: now)
    body = metrics_mod.render_metrics(startup_ts=now - 3600.0)
    assert "live_overlay_health_status_code 1" in body
    assert 'live_overlay_health_status_info{status="starting"} 1' in body


def test_render_metrics_sanitizes_non_finite_counters(monkeypatch: pytest.MonkeyPatch) -> None:
    import services.live_overlay_daemon.metrics as metrics_mod
    import services.live_overlay_daemon.observability as obs

    _patch_common(
        monkeypatch,
        feed_ready=True,
        market_open=True,
        bar_count=10,
        overlay_symbols=5,
        overlay_age=60.0,
    )

    with obs._counter_lock:
        obs._counters.clear()
        obs._counters["live_overlay.bad_inf"] = float("inf")
        obs._counters["live_overlay.bad_nan"] = float("nan")

    body = metrics_mod.render_metrics(startup_ts=100.0)

    assert "live_overlay_bad_inf nan" in body
    assert "live_overlay_bad_nan nan" in body


def test_render_metrics_emits_latency_quantile_gauges(monkeypatch: pytest.MonkeyPatch) -> None:
    import services.live_overlay_daemon.metrics as metrics_mod
    import services.live_overlay_daemon.observability as obs

    _patch_common(
        monkeypatch,
        feed_ready=True,
        market_open=True,
        bar_count=10,
        overlay_symbols=5,
        overlay_age=60.0,
    )

    with obs._counter_lock:
        obs._counters.clear()
        obs._counters["live_overlay.smc_live_latency.count"] = 100.0
        obs._counters["live_overlay.smc_live_latency.bucket_le_100"] = 90.0
        obs._counters["live_overlay.smc_live_latency.bucket_le_250"] = 98.0
        obs._counters["live_overlay.smc_live_latency.bucket_le_500"] = 100.0
        obs._counters["live_overlay.smc_live_latency.bucket_le_inf"] = 100.0

    body = metrics_mod.render_metrics(startup_ts=100.0)

    # The derived p95/p99 gauges are gone: consumers read the buckets via
    # histogram_quantile(), and two dashboard/alert contract tests forbid the
    # gauges outright, so emitting them served nothing.
    assert "live_overlay_smc_live_latency_p95_ms" not in body
    assert "live_overlay_smc_live_latency_p99_ms" not in body
    assert "# TYPE live_overlay_smc_live_latency_ms histogram" in body
    assert 'live_overlay_smc_live_latency_ms_bucket{le="10"} 0.0' in body
    assert 'live_overlay_smc_live_latency_ms_bucket{le="25"} 0.0' in body
    assert 'live_overlay_smc_live_latency_ms_bucket{le="50"} 0.0' in body
    assert 'live_overlay_smc_live_latency_ms_bucket{le="100"} 90.0' in body
    assert 'live_overlay_smc_live_latency_ms_bucket{le="250"} 98.0' in body
    assert 'live_overlay_smc_live_latency_ms_bucket{le="500"} 100.0' in body
    assert 'live_overlay_smc_live_latency_ms_bucket{le="1000"} 100.0' in body
    assert 'live_overlay_smc_live_latency_ms_bucket{le="2500"} 100.0' in body
    assert 'live_overlay_smc_live_latency_ms_bucket{le="5000"} 100.0' in body
    assert 'live_overlay_smc_live_latency_ms_bucket{le="+Inf"} 100.0' in body
    assert "live_overlay_smc_live_latency_ms_sum 0.0" in body
    assert "live_overlay_smc_live_latency_ms_count 100.0" in body
    # Classic histogram structure: bucket series, _sum, _count, and +Inf bucket.
    assert "live_overlay_smc_live_latency_ms_bucket{" in body
    assert "live_overlay_smc_live_latency_ms_sum " in body
    assert "live_overlay_smc_live_latency_ms_count " in body
    # Buckets must be sorted numerically, not lexicographically.
    p10 = body.find('live_overlay_smc_live_latency_ms_bucket{le="10"}')
    p100 = body.find('live_overlay_smc_live_latency_ms_bucket{le="100"}')
    p1000 = body.find('live_overlay_smc_live_latency_ms_bucket{le="1000"}')
    assert 0 < p10 < p100 < p1000, "histogram buckets not sorted numerically"


def test_render_metrics_never_reemits_legacy_latency_quantile_gauges(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The p95/p99 gauges stay deleted — reviving them re-opens the orphan.

    They existed only "until dashboard/alert consumers are fully migrated to
    histogram_quantile()". That migration is done and enforced by
    test_dashboard_latency_panel_uses_only_histogram_quantile and
    test_latency_alert_uses_histogram_quantile_bucket, which forbid the gauges
    in every panel and rule. Re-emitting them would therefore produce a series
    nothing is allowed to consume, so this pins their absence in the one place
    that could bring them back.

    Exercised with the +Inf-only counter state that used to be their trickiest
    case (it once risked a misleadingly-perfect 0.000 ms reading).
    """
    import services.live_overlay_daemon.metrics as metrics_mod
    import services.live_overlay_daemon.observability as obs

    _patch_common(monkeypatch, feed_ready=True, market_open=True, bar_count=10, overlay_symbols=5, overlay_age=60.0)
    with obs._counter_lock:
        obs._counters.clear()
        obs._counters["live_overlay.smc_live_latency.count"] = 100.0
        obs._counters["live_overlay.smc_live_latency.bucket_le_inf"] = 100.0

    body = metrics_mod.render_metrics(startup_ts=100.0)

    assert "live_overlay_smc_live_latency_p95_ms" not in body
    assert "live_overlay_smc_live_latency_p99_ms" not in body
    # The histogram itself must still be there — this deletion removed the
    # derived duplicates, not the latency signal.
    assert "# TYPE live_overlay_smc_live_latency_ms histogram" in body
    assert 'live_overlay_smc_live_latency_ms_bucket{le="+Inf"} 100.0' in body
    assert "live_overlay_smc_live_latency_ms_count 100.0" in body


def test_render_metrics_emits_age_known_gauges(monkeypatch: pytest.MonkeyPatch) -> None:
    import services.live_overlay_daemon.metrics as metrics_mod

    _patch_common(
        monkeypatch,
        feed_ready=True,
        market_open=True,
        bar_count=10,
        overlay_symbols=5,
        overlay_age=60.0,
    )

    body = metrics_mod.render_metrics(startup_ts=100.0)
    assert "live_overlay_overlay_age_known 1.0" in body
    assert "live_overlay_overlay_age_seconds 60.0" in body
    assert "live_overlay_last_bar_age_known 1.0" in body
    assert "live_overlay_last_bar_age_seconds 5.0" in body


def test_render_metrics_age_known_zero_when_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    import services.live_overlay_daemon.metrics as metrics_mod

    _patch_common(
        monkeypatch,
        feed_ready=True,
        market_open=True,
        bar_count=0,
        overlay_symbols=0,
        overlay_age=float("inf"),
        last_bar_age=None,
    )

    body = metrics_mod.render_metrics(startup_ts=100.0)
    assert "live_overlay_overlay_age_known 0.0" in body
    # 0.0 and NOT nan is the contract `lo-overlay-stale` depends on: it selects with
    # `(age * known) + ((1 - known) * 3601)`, so a NaN age would make `nan * 0 = nan`
    # swallow the 3601 unknown-sentinel and silence a severity-high rule.
    assert "live_overlay_overlay_age_seconds 0.0" in body
    assert "live_overlay_last_bar_age_known 0.0" in body
    assert "live_overlay_last_bar_age_seconds 0.0" in body


def test_render_metrics_known_age_still_renders_finite_value(monkeypatch: pytest.MonkeyPatch) -> None:
    import services.live_overlay_daemon.metrics as metrics_mod

    _patch_common(
        monkeypatch,
        feed_ready=True,
        market_open=True,
        bar_count=10,
        overlay_symbols=5,
        overlay_age=60.0,
        last_bar_age=12.5,
    )

    body = metrics_mod.render_metrics(startup_ts=100.0)
    assert "live_overlay_overlay_age_known 1.0" in body
    assert "live_overlay_overlay_age_seconds 60.0" in body
    assert "live_overlay_last_bar_age_known 1.0" in body
    assert "live_overlay_last_bar_age_seconds 12.5" in body


def test_render_metrics_emits_vix_gauges_when_fetched(monkeypatch: pytest.MonkeyPatch) -> None:
    import services.live_overlay_daemon.cache as cache
    import services.live_overlay_daemon.metrics as metrics_mod

    _patch_common(
        monkeypatch,
        feed_ready=True,
        market_open=True,
        bar_count=10,
        overlay_symbols=5,
        overlay_age=60.0,
    )
    monkeypatch.setattr(cache, "get_vix", lambda: 22.354)
    monkeypatch.setattr(cache, "vix_age_secs", lambda: 120.0)

    body = metrics_mod.render_metrics(startup_ts=100.0)
    assert "live_overlay_vix_level 22.35" in body
    assert "live_overlay_vix_age_known 1.0" in body
    assert "live_overlay_vix_age_seconds 120.0" in body


def test_render_metrics_vix_never_fetched_is_distinguishable_from_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import services.live_overlay_daemon.cache as cache
    import services.live_overlay_daemon.metrics as metrics_mod

    _patch_common(
        monkeypatch,
        feed_ready=True,
        market_open=True,
        bar_count=10,
        overlay_symbols=5,
        overlay_age=60.0,
    )
    monkeypatch.setattr(cache, "get_vix", lambda: None)
    monkeypatch.setattr(cache, "vix_age_secs", lambda: float("inf"))

    body = metrics_mod.render_metrics(startup_ts=100.0)
    assert "live_overlay_vix_age_known 0.0" in body
    # 0.0 and NOT nan: `lo-vix-unavailable` selects with
    # `(age * known) + ((1 - known) * 5401)`, so a NaN age would swallow the
    # unknown-sentinel exactly like the lo-overlay-stale case above.
    assert "live_overlay_vix_age_seconds 0.0" in body
    assert "live_overlay_vix_level 0.0" in body


def test_render_metrics_emits_hotspot_gauges(monkeypatch: pytest.MonkeyPatch) -> None:
    import services.live_overlay_daemon.metrics as metrics_mod

    _patch_common(
        monkeypatch,
        feed_ready=True,
        market_open=True,
        bar_count=10,
        overlay_symbols=5,
        overlay_age=60.0,
    )
    monkeypatch.setattr(
        metrics_mod.request_hotspots,
        "snapshot",
        lambda top_n=5: {
            "symbol_count": 3,
            "tf_count": 2,
            "top_symbols": [("NVDA", 12), ("AAPL", 7)],
            "top_tfs": [("5m", 15), ("1H", 4)],
        },
    )

    body = metrics_mod.render_metrics(startup_ts=100.0)

    assert "live_overlay_hotspot_symbols_tracked 3.0" in body
    assert "live_overlay_hotspot_timeframes_tracked 2.0" in body
    assert "live_overlay_hotspot_symbol_nvda_requests_total 12.0" in body
    assert "live_overlay_hotspot_symbol_aapl_requests_total 7.0" in body
    assert "live_overlay_hotspot_tf__5m_requests_total 15.0" in body
    assert "live_overlay_hotspot_tf__1h_requests_total 4.0" in body


def test_observability_rejects_non_finite_values() -> None:
    import services.live_overlay_daemon.observability as obs

    with pytest.raises(ValueError):
        obs.metric_counter("live_overlay.test_counter", float("inf"))
    with pytest.raises(ValueError):
        obs.metric_gauge("live_overlay.test_gauge", float("nan"))
    with pytest.raises(ValueError):
        obs.metric_timing_ms("live_overlay.test_timing", float("-inf"))


def test_observability_counter_accepts_finite_values() -> None:
    import services.live_overlay_daemon.observability as obs

    with obs._counter_lock:
        obs._counters.pop("live_overlay.test_counter_ok", None)

    total = obs.metric_counter("live_overlay.test_counter_ok", 1.5)
    assert math.isfinite(total)
    assert total == 1.5


def test_observability_histogram_ms_emits_bucket_count_and_sum() -> None:
    import services.live_overlay_daemon.observability as obs

    with obs._counter_lock:
        obs._counters.pop("live_overlay.test_latency.count", None)
        obs._counters.pop("live_overlay.test_latency.sum_ms", None)
        obs._counters.pop("live_overlay.test_latency.bucket_le_10", None)
        obs._counters.pop("live_overlay.test_latency.bucket_le_50", None)
        obs._counters.pop("live_overlay.test_latency.bucket_le_inf", None)

    obs.metric_histogram_ms("live_overlay.test_latency", 42.0, buckets_ms=(10.0, 50.0))

    with obs._counter_lock:
        assert obs._counters["live_overlay.test_latency.count"] == 1.0
        assert obs._counters["live_overlay.test_latency.sum_ms"] == 42.0
        assert "live_overlay.test_latency.bucket_le_10" not in obs._counters
        assert obs._counters["live_overlay.test_latency.bucket_le_50"] == 1.0
        assert obs._counters["live_overlay.test_latency.bucket_le_inf"] == 1.0


def test_observability_histogram_respects_explicit_empty_buckets() -> None:
    import services.live_overlay_daemon.observability as obs

    with obs._counter_lock:
        for key in list(obs._counters):
            if key.startswith("live_overlay.test_latency_empty"):
                obs._counters.pop(key, None)

    obs.metric_histogram_ms("live_overlay.test_latency_empty", 42.0, buckets_ms=())

    with obs._counter_lock:
        assert obs._counters["live_overlay.test_latency_empty.count"] == 1.0
        assert obs._counters["live_overlay.test_latency_empty.sum_ms"] == 42.0
        assert obs._counters["live_overlay.test_latency_empty.bucket_le_inf"] == 1.0
        assert "live_overlay.test_latency_empty.bucket_le_10" not in obs._counters
        assert "live_overlay.test_latency_empty.bucket_le_50" not in obs._counters


def test_observability_histogram_bucket_suffix_avoids_scientific_notation() -> None:
    import services.live_overlay_daemon.observability as obs

    with obs._counter_lock:
        obs._counters.pop("live_overlay.test_latency_scientific.bucket_le_1000000", None)
        obs._counters.pop("live_overlay.test_latency_scientific.bucket_le_inf", None)

    obs.metric_histogram_ms(
        "live_overlay.test_latency_scientific",
        1000.0,
        buckets_ms=(1_000_000.0,),
    )

    with obs._counter_lock:
        assert obs._counters["live_overlay.test_latency_scientific.bucket_le_1000000"] == 1.0
        assert obs._counters["live_overlay.test_latency_scientific.bucket_le_inf"] == 1.0


def test_render_metrics_includes_uptimerobot_bridge_snapshot(monkeypatch: pytest.MonkeyPatch) -> None:
    import services.live_overlay_daemon.metrics as metrics_mod

    _patch_common(
        monkeypatch,
        feed_ready=True,
        market_open=True,
        bar_count=10,
        overlay_symbols=5,
        overlay_age=60.0,
    )
    monkeypatch.setattr(
        metrics_mod.uptimerobot_bridge,
        "snapshot",
        lambda: {
            "enabled": 1,
            "configured": 1,
            "ok": 1,
            "fetched_at_unix": 1_700_000_000.0,
            "last_success_fetched_at_unix": 1_700_000_000.0,
            "scrape_duration_seconds": 0.123,
            "counts": {"total": 4, "up": 4, "down": 0, "paused": 0, "unknown": 0},
            "avg_response_time_ms": 101.5,
            "monitors": [
                {
                    "id": "803343156",
                    "up": 1,
                    "status_code": 2,
                    "response_time_ms": 98.0,
                }
            ],
        },
    )
    monkeypatch.setattr(
        metrics_mod.config,
        "uptimerobot_monitor_ids",
        lambda: [
            "803309701",
            "803341452",
            "803343155",
            "803343156",
            "803362511",
            "803555263",
            "803555264",
        ],
    )

    body = metrics_mod.render_metrics(startup_ts=100.0)

    assert 'live_overlay_bridge_enabled{bridge="uptimerobot"} 1' in body
    assert 'live_overlay_bridge_configured{bridge="uptimerobot"} 1' in body
    assert 'live_overlay_bridge_scrape_success{bridge="uptimerobot"} 1' in body
    assert 'live_overlay_bridge_last_scrape_duration_seconds{bridge="uptimerobot"} 0.123' in body
    assert "live_overlay_uptimerobot_bridge_enabled" not in body
    assert "live_overlay_uptimerobot_scrape_success" not in body
    assert "live_overlay_uptimerobot_monitors_total 4.0" in body
    assert "live_overlay_uptimerobot_monitors_expected 7.0" in body
    assert "live_overlay_uptimerobot_monitors_up_total 4.0" in body
    assert "live_overlay_uptimerobot_monitors_response_time_ms_avg 101.5" in body
    assert "live_overlay_uptimerobot_monitor__803343156_up 1.0" in body
    assert "live_overlay_uptimerobot_monitor__803343156_status_code 2.0" in body
    assert "live_overlay_uptimerobot_monitor__803343156_response_time_ms 98.0" in body


def test_render_metrics_handles_uptimerobot_bridge_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    import services.live_overlay_daemon.metrics as metrics_mod

    _patch_common(
        monkeypatch,
        feed_ready=True,
        market_open=True,
        bar_count=10,
        overlay_symbols=5,
        overlay_age=60.0,
    )
    monkeypatch.setattr(
        metrics_mod.uptimerobot_bridge,
        "snapshot",
        lambda: {
            "enabled": 0,
            "configured": 0,
            "ok": 0,
            "fetched_at_unix": 0.0,
            "scrape_duration_seconds": None,
            "counts": {"total": 0, "up": 0, "down": 0, "paused": 0, "unknown": 0},
            "avg_response_time_ms": None,
            "monitors": [],
        },
    )
    monkeypatch.setattr(metrics_mod.config, "uptimerobot_monitor_ids", lambda: [])

    body = metrics_mod.render_metrics(startup_ts=100.0)

    assert 'live_overlay_bridge_enabled{bridge="uptimerobot"} 0' in body
    assert 'live_overlay_bridge_configured{bridge="uptimerobot"} 0' in body
    assert 'live_overlay_bridge_scrape_success{bridge="uptimerobot"} 0' in body
    assert "live_overlay_uptimerobot_bridge_enabled" not in body
    assert "live_overlay_uptimerobot_scrape_success" not in body
    assert "live_overlay_uptimerobot_monitors_total 0.0" in body
    assert "live_overlay_uptimerobot_monitors_expected" not in body


def test_render_metrics_includes_github_workflow_bridge_snapshot(monkeypatch: pytest.MonkeyPatch) -> None:
    import services.live_overlay_daemon.metrics as metrics_mod

    _patch_common(
        monkeypatch,
        feed_ready=True,
        market_open=True,
        bar_count=10,
        overlay_symbols=5,
        overlay_age=60.0,
    )
    monkeypatch.setattr(
        metrics_mod.github_workflow_bridge,
        "snapshot",
        lambda: {
            "enabled": 1,
            "configured": 1,
            "ok": 1,
            "fetched_at_unix": 1_700_000_100.0,
            "last_success_fetched_at_unix": 1_700_000_100.0,
            "scrape_duration_seconds": 0.456,
            "counts": {
                "seen": 4,
                "success": 2,
                "failed": 1,
                "in_progress": 1,
                "queued": 0,
            },
            "latest_run_age_seconds": 45.5,
            "latest_run_duration_seconds": 120.0,
            "workflows": [
                {
                    "id": "129428056",
                    "name": "CI",
                    "event": "schedule",
                    "phase_code": 3,
                    "latest_success": 1,
                    "latest_age_seconds": 45.5,
                    "latest_duration_seconds": 120.0,
                }
            ],
        },
    )

    body = metrics_mod.render_metrics(startup_ts=100.0)

    assert 'live_overlay_bridge_enabled{bridge="github_workflow"} 1' in body
    assert 'live_overlay_bridge_configured{bridge="github_workflow"} 1' in body
    assert 'live_overlay_bridge_scrape_success{bridge="github_workflow"} 1' in body
    assert 'live_overlay_bridge_last_scrape_duration_seconds{bridge="github_workflow"} 0.456' in body
    assert "live_overlay_github_workflow_bridge_enabled" not in body
    assert "live_overlay_github_workflow_scrape_success" not in body
    assert "# TYPE live_overlay_github_workflow_runs_seen_total gauge" in body
    assert "live_overlay_github_workflow_runs_seen_total 4.0" in body
    assert "live_overlay_github_workflow_runs_success_total 2.0" in body
    assert "live_overlay_github_workflow_runs_failed_total 1.0" in body
    assert "live_overlay_github_workflow_latest_run_age_seconds 45.5" in body
    assert "live_overlay_github_workflow_latest_run_duration_seconds 120.0" in body
    # Per-workflow series are labelled (id + name + event) so Grafana can name
    # each flow and group a shared status timeline / detail table.
    workflow_labels = 'workflow_id="129428056",workflow="CI",event="schedule"'
    assert f"live_overlay_github_workflow_phase_code{{{workflow_labels}}} 3.0" in body
    assert f"live_overlay_github_workflow_latest_success{{{workflow_labels}}} 1.0" in body
    assert f"live_overlay_github_workflow_latest_age_seconds{{{workflow_labels}}} 45.5" in body
    assert f"live_overlay_github_workflow_latest_duration_seconds{{{workflow_labels}}} 120.0" in body


def test_render_metrics_handles_github_workflow_bridge_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    import services.live_overlay_daemon.metrics as metrics_mod

    _patch_common(
        monkeypatch,
        feed_ready=True,
        market_open=True,
        bar_count=10,
        overlay_symbols=5,
        overlay_age=60.0,
    )
    monkeypatch.setattr(
        metrics_mod.github_workflow_bridge,
        "snapshot",
        lambda: {
            "enabled": 0,
            "configured": 0,
            "ok": 0,
            "fetched_at_unix": 0.0,
            "scrape_duration_seconds": None,
            "counts": {
                "seen": 0,
                "success": 0,
                "failed": 0,
                "in_progress": 0,
                "queued": 0,
            },
            "latest_run_age_seconds": None,
            "latest_run_duration_seconds": None,
            "workflows": [],
        },
    )

    body = metrics_mod.render_metrics(startup_ts=100.0)

    assert 'live_overlay_bridge_enabled{bridge="github_workflow"} 0' in body
    assert 'live_overlay_bridge_configured{bridge="github_workflow"} 0' in body
    assert 'live_overlay_bridge_scrape_success{bridge="github_workflow"} 0' in body
    assert "live_overlay_github_workflow_bridge_enabled" not in body
    assert "live_overlay_github_workflow_scrape_success" not in body
    assert "live_overlay_github_workflow_runs_seen_total 0.0" in body


def test_render_metrics_escapes_uptimerobot_error_code_labels(monkeypatch: pytest.MonkeyPatch) -> None:
    import services.live_overlay_daemon.metrics as metrics_mod

    _patch_common(
        monkeypatch,
        feed_ready=True,
        market_open=True,
        bar_count=10,
        overlay_symbols=5,
        overlay_age=60.0,
    )
    monkeypatch.setattr(
        metrics_mod.uptimerobot_bridge,
        "snapshot",
        lambda: {
            "enabled": 1,
            "ok": 0,
            "fetched_at_unix": 1_700_000_100.0,
            "error_code": 'timeout\\\\"quoted',
            "counts": {"total": 0, "up": 0, "down": 0, "paused": 0, "unknown": 0},
            "avg_response_time_ms": None,
            "monitors": [],
        },
    )

    body = metrics_mod.render_metrics(startup_ts=100.0)

    assert 'live_overlay_bridge_error_info{bridge="uptimerobot",error="timeout\\\\\\\\\\"quoted"} 1' in body
    assert "live_overlay_uptimerobot_scrape_error_info" not in body


def test_render_metrics_escapes_github_workflow_error_code_labels(monkeypatch: pytest.MonkeyPatch) -> None:
    import services.live_overlay_daemon.metrics as metrics_mod

    _patch_common(
        monkeypatch,
        feed_ready=True,
        market_open=True,
        bar_count=10,
        overlay_symbols=5,
        overlay_age=60.0,
    )
    monkeypatch.setattr(
        metrics_mod.github_workflow_bridge,
        "snapshot",
        lambda: {
            "enabled": 1,
            "ok": 0,
            "fetched_at_unix": 1_700_000_100.0,
            "error_code": 'http\\\\"401',
            "counts": {"seen": 0, "success": 0, "failed": 0, "in_progress": 0, "queued": 0},
            "latest_run_age_seconds": None,
            "latest_run_duration_seconds": None,
            "workflows": [],
        },
    )

    body = metrics_mod.render_metrics(startup_ts=100.0)

    assert 'live_overlay_bridge_error_info{bridge="github_workflow",error="http\\\\\\\\\\"401"} 1' in body
    assert "live_overlay_github_workflow_scrape_error_info" not in body


def test_render_metrics_bridge_error_info_absent_when_healthy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Healthy scrapes must not emit legacy scrape_error_info series."""
    import services.live_overlay_daemon.metrics as metrics_mod

    _patch_common(
        monkeypatch,
        feed_ready=True,
        market_open=True,
        bar_count=10,
        overlay_symbols=5,
        overlay_age=60.0,
    )
    monkeypatch.setattr(
        metrics_mod.uptimerobot_bridge,
        "snapshot",
        lambda: {
            "enabled": 1,
            "ok": 1,
            "fetched_at_unix": 1_700_000_100.0,
            "error_code": "",
            "counts": {"total": 0, "up": 0, "down": 0, "paused": 0, "unknown": 0},
            "avg_response_time_ms": None,
            "monitors": [],
        },
    )
    monkeypatch.setattr(
        metrics_mod.github_workflow_bridge,
        "snapshot",
        lambda: {
            "enabled": 1,
            "ok": 1,
            "fetched_at_unix": 1_700_000_100.0,
            "error_code": "",
            "counts": {"seen": 0, "success": 0, "failed": 0, "in_progress": 0, "queued": 0},
            "latest_run_age_seconds": None,
            "latest_run_duration_seconds": None,
            "workflows": [],
        },
    )

    body = metrics_mod.render_metrics(startup_ts=100.0)

    assert 'live_overlay_bridge_error_info{bridge="uptimerobot",error="none"} 0' in body
    assert 'live_overlay_bridge_error_info{bridge="github_workflow",error="none"} 0' in body
    assert "live_overlay_uptimerobot_scrape_error_info" not in body
    assert "live_overlay_github_workflow_scrape_error_info" not in body


def test_disabled_bridges_are_not_reported_as_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A missing credential disables the uptimerobot / github_workflow bridge
    (enabled=0) but is NOT an error: error_code stays None so bridge_error_info
    is 0 — consistent with railway_metrics._disabled_snapshot. Previously the
    disabled path emitted error="missing_api_key"/"missing_token", a permanent
    error_info=1 that read as a fault on an intentionally-off optional bridge
    (the missing-credential state is already conveyed by configured=0)."""
    import services.live_overlay_daemon.github_workflow_bridge as gw
    import services.live_overlay_daemon.uptimerobot_bridge as ub

    monkeypatch.setattr(ub.config, "uptimerobot_api_key", lambda: "")
    monkeypatch.setattr(gw.config, "github_workflow_token", lambda: "")

    for snap in (ub.snapshot(), gw.snapshot()):
        assert snap["enabled"] == 0
        assert snap["configured"] == 0
        assert snap["error"] is None
        assert snap["error_code"] is None


def test_render_metrics_bridge_error_info_clears_after_recovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A recovery scrape must no longer contain the previous error series."""
    import services.live_overlay_daemon.metrics as metrics_mod

    _patch_common(
        monkeypatch,
        feed_ready=True,
        market_open=True,
        bar_count=10,
        overlay_symbols=5,
        overlay_age=60.0,
    )
    monkeypatch.setattr(
        metrics_mod.uptimerobot_bridge,
        "snapshot",
        lambda: {
            "enabled": 1,
            "ok": 0,
            "fetched_at_unix": 1_700_000_100.0,
            "error_code": "timeout",
            "counts": {"total": 0, "up": 0, "down": 0, "paused": 0, "unknown": 0},
            "avg_response_time_ms": None,
            "monitors": [],
        },
    )
    monkeypatch.setattr(
        metrics_mod.github_workflow_bridge,
        "snapshot",
        lambda: {
            "enabled": 1,
            "ok": 0,
            "fetched_at_unix": 1_700_000_100.0,
            "error_code": "http401",
            "counts": {"seen": 0, "success": 0, "failed": 0, "in_progress": 0, "queued": 0},
            "latest_run_age_seconds": None,
            "latest_run_duration_seconds": None,
            "workflows": [],
        },
    )

    body = metrics_mod.render_metrics(startup_ts=100.0)
    assert 'live_overlay_bridge_error_info{bridge="uptimerobot",error="timeout"} 1' in body
    assert 'live_overlay_bridge_error_info{bridge="github_workflow",error="http401"} 1' in body
    assert "live_overlay_uptimerobot_scrape_error_info" not in body
    assert "live_overlay_github_workflow_scrape_error_info" not in body

    monkeypatch.setattr(
        metrics_mod.uptimerobot_bridge,
        "snapshot",
        lambda: {
            "enabled": 1,
            "ok": 1,
            "fetched_at_unix": 1_700_000_100.0,
            "error_code": "",
            "counts": {"total": 0, "up": 0, "down": 0, "paused": 0, "unknown": 0},
            "avg_response_time_ms": None,
            "monitors": [],
        },
    )
    monkeypatch.setattr(
        metrics_mod.github_workflow_bridge,
        "snapshot",
        lambda: {
            "enabled": 1,
            "ok": 1,
            "fetched_at_unix": 1_700_000_100.0,
            "error_code": "",
            "counts": {"seen": 0, "success": 0, "failed": 0, "in_progress": 0, "queued": 0},
            "latest_run_age_seconds": None,
            "latest_run_duration_seconds": None,
            "workflows": [],
        },
    )
    body = metrics_mod.render_metrics(startup_ts=100.0)
    assert 'live_overlay_bridge_error_info{bridge="uptimerobot",error="none"} 0' in body
    assert 'live_overlay_bridge_error_info{bridge="github_workflow",error="none"} 0' in body
    assert 'live_overlay_bridge_error_info{bridge="uptimerobot",error="timeout"}' not in body
    assert 'live_overlay_bridge_error_info{bridge="github_workflow",error="http401"}' not in body
    assert "live_overlay_uptimerobot_scrape_error_info" not in body
    assert "live_overlay_github_workflow_scrape_error_info" not in body


def test_render_metrics_includes_trading_signals_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import time as _time

    import services.live_overlay_daemon.metrics as metrics_mod

    _patch_common(
        monkeypatch,
        feed_ready=True,
        market_open=True,
        bar_count=10,
        overlay_symbols=5,
        overlay_age=60.0,
    )
    snapshot = {
        "updated_at": "2026-06-23T14:30:00+00:00",
        "updated_epoch": _time.time() - 30.0,
        "poll_interval": 5,
        "poll_duration": 0.4,
        "watched_symbols": ["AAPL", "TSLA", "NVDA"],
        "signal_count": 3,
        "a0_count": 1,
        "a1_count": 1,
        "a2_count": 1,
        "disabled_reason": None,
        "signals": [
            {
                "symbol": "AAPL",
                "level": "A1",
                "direction": "LONG",
                "confidence_tier": "HIGH",
                "score": 7.5,
                "freshness": 0.9,
                "technical_score": 0.82,
                "change_pct": 1.23,
                "technical_signal": "STRONG_BUY",
                "macd_signal": "BUY",
                "symbol_regime": "TREND_UP",
                "news_category": "earnings",
            },
            {
                "symbol": "TSLA",
                "level": "A0",
                "direction": "SHORT",
                "confidence_tier": "MEDIUM",
                "score": 4.0,
                "freshness": 0.5,
                "technical_score": 0.31,
                "change_pct": -2.0,
                "technical_signal": "SELL",
                "macd_signal": "SELL",
                "symbol_regime": "TREND_DOWN",
                "news_category": "none",
            },
            {
                "symbol": "NVDA",
                "level": "A2",
                "direction": "LONG",
                "confidence_tier": "LOW",
                "score": 2.5,
                "freshness": 0.95,
                "technical_score": 0.20,
                "change_pct": 0.8,
                "technical_signal": "HOLD",
                "macd_signal": "NEUTRAL",
                "symbol_regime": "RANGE",
                "news_category": "none",
            },
        ],
    }
    monkeypatch.setattr(metrics_mod.compute, "_load_signals_snapshot", lambda: snapshot)

    body = metrics_mod.render_metrics(startup_ts=100.0)

    assert "live_overlay_trading_signals_loaded 1.0" in body
    # Canonical suffix-less gauges (point-in-time counts).
    assert "live_overlay_trading_signals_active 3.0" in body
    assert "live_overlay_trading_signals_a0 1.0" in body
    assert "live_overlay_trading_signals_a1 1.0" in body
    # A2 early-warning tier is a first-class gauge (added 2026-07-08).
    assert "live_overlay_trading_signals_a2 1.0" in body
    assert "live_overlay_trading_signals_watched 3.0" in body
    # The deprecated *_total aliases were dropped 2026-07-22 (transition over:
    # all committed dashboards use the suffix-less names, and the orphan scan
    # covers the trading_signals family). Pin the removal — a revert would
    # reintroduce five emitted-but-unconsumed series.
    assert "live_overlay_trading_signals_active_total" not in body
    assert "live_overlay_trading_signals_a0_total" not in body
    assert "live_overlay_trading_signals_a1_total" not in body
    assert "live_overlay_trading_signals_a2_total" not in body
    assert "live_overlay_trading_signals_watched_total" not in body
    # A2 signals also surface as labelled per-signal series (level="A2").
    assert 'live_overlay_trading_signal_score{symbol="NVDA",level="A2"' in body
    assert "live_overlay_trading_signals_snapshot_age_known 1.0" in body
    # Per-signal series are labelled so Grafana can name/group each firing symbol.
    aapl = 'symbol="AAPL",level="A1",direction="LONG",tier="HIGH"'
    assert f"live_overlay_trading_signal_score{{{aapl}}} 7.5" in body
    assert f"live_overlay_trading_signal_freshness{{{aapl}}} 0.9" in body
    assert f"live_overlay_trading_signal_technical_score{{{aapl}}} 0.82" in body
    assert f"live_overlay_trading_signal_change_pct{{{aapl}}} 1.23" in body
    expected_info = (
        "live_overlay_trading_signal_info{" + aapl + ',technical_signal="STRONG_BUY",macd_signal="BUY",'
        'symbol_regime="TREND_UP",news_category="earnings"} 1'
    )
    assert expected_info in body
    # Highest score sorts first in the capped list.
    assert body.index('live_overlay_trading_signal_score{symbol="AAPL"') < body.index(
        'live_overlay_trading_signal_score{symbol="TSLA"'
    )


def test_future_trading_signals_snapshot_is_unknown_and_stale(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A future producer clock must not look like a fresh signal snapshot."""
    import time as _time

    import services.live_overlay_daemon.metrics as metrics_mod

    _patch_common(
        monkeypatch,
        feed_ready=True,
        market_open=True,
        bar_count=10,
        overlay_symbols=5,
        overlay_age=60.0,
    )
    monkeypatch.setattr(
        metrics_mod.compute,
        "_load_signals_snapshot",
        lambda: {"updated_epoch": _time.time() + 60.0, "signals": []},
    )

    body = metrics_mod.render_metrics(startup_ts=100.0)

    assert "live_overlay_trading_signals_snapshot_age_known 0.0" in body
    assert "live_overlay_trading_signals_snapshot_stale 1.0" in body


def test_stale_trading_signals_snapshot_exports_no_active_signals(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Dashboards must not present an expired snapshot as an active signal."""
    import time as _time

    import services.live_overlay_daemon.metrics as metrics_mod

    _patch_common(
        monkeypatch,
        feed_ready=True,
        market_open=True,
        bar_count=10,
        overlay_symbols=5,
        overlay_age=60.0,
    )
    monkeypatch.setattr(
        metrics_mod.compute,
        "_load_signals_snapshot",
        lambda: {
            "updated_epoch": _time.time() - (metrics_mod.config.signals_max_age_secs() + 1),
            "watched_symbols": ["AAPL"],
            "signal_count": 1,
            "a0_count": 1,
            "signals": [{"symbol": "AAPL", "level": "A0", "score": 9.0}],
        },
    )

    body = metrics_mod.render_metrics(startup_ts=100.0)

    assert "live_overlay_trading_signals_snapshot_stale 1.0" in body
    assert "live_overlay_trading_signals_active 0.0" in body
    assert "live_overlay_trading_signals_a0 0.0" in body
    assert "live_overlay_trading_signal_score{" not in body


def test_render_metrics_includes_tradingview_credential(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import services.live_overlay_daemon.metrics as metrics_mod

    _patch_common(
        monkeypatch,
        feed_ready=True,
        market_open=True,
        bar_count=10,
        overlay_symbols=5,
        overlay_age=60.0,
    )
    report = {
        "schema_version": "1",
        "overall_severity": "warn",
        "probes": [
            {
                "name": "tv_storage_state_age",
                "severity": "warn",
                "message": "ageing",
                "details": {
                    "validated_at": "2026-06-20T00:00:00+00:00",
                    "age_hours": 60.0,
                    "max_age_hours": 72,
                },
            }
        ],
    }
    monkeypatch.setattr(metrics_mod.compute, "_load_tradingview_credential_snapshot", lambda: report)

    body = metrics_mod.render_metrics(startup_ts=100.0)

    assert "live_overlay_tradingview_credential_loaded 1.0" in body
    # severity "warn" is not "error" -> still considered valid.
    assert "live_overlay_tradingview_credential_valid 1.0" in body
    assert "live_overlay_tradingview_credential_age_known 1.0" in body
    assert "live_overlay_tradingview_credential_age_hours 60.000" in body


def test_render_metrics_tradingview_credential_error_is_invalid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import services.live_overlay_daemon.metrics as metrics_mod

    _patch_common(
        monkeypatch,
        feed_ready=True,
        market_open=True,
        bar_count=10,
        overlay_symbols=5,
        overlay_age=60.0,
    )
    report = {
        "probes": [
            {
                "name": "tv_storage_state_age",
                "severity": "error",
                "details": {"validated_at": "2026-06-15T00:00:00+00:00", "age_hours": 120.0},
            }
        ],
    }
    monkeypatch.setattr(metrics_mod.compute, "_load_tradingview_credential_snapshot", lambda: report)

    body = metrics_mod.render_metrics(startup_ts=100.0)

    assert "live_overlay_tradingview_credential_loaded 1.0" in body
    assert "live_overlay_tradingview_credential_valid 0.0" in body
    assert "live_overlay_tradingview_credential_age_hours 120.000" in body


def test_render_metrics_handles_tradingview_credential_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import services.live_overlay_daemon.metrics as metrics_mod

    _patch_common(
        monkeypatch,
        feed_ready=True,
        market_open=True,
        bar_count=10,
        overlay_symbols=5,
        overlay_age=60.0,
    )
    monkeypatch.setattr(metrics_mod.compute, "_load_tradingview_credential_snapshot", lambda: {})

    body = metrics_mod.render_metrics(startup_ts=100.0)

    assert "live_overlay_tradingview_credential_loaded 0.0" in body
    assert "live_overlay_tradingview_credential_valid 0.0" in body
    assert "live_overlay_tradingview_credential_age_known 0.0" in body
    assert "live_overlay_tradingview_credential_age_hours 0.000" in body


def test_render_metrics_includes_full_credential_health_report(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import services.live_overlay_daemon.metrics as metrics_mod

    _patch_common(
        monkeypatch,
        feed_ready=True,
        market_open=True,
        bar_count=10,
        overlay_symbols=5,
        overlay_age=60.0,
    )
    report = {
        "schema_version": "1",
        "overall_severity": "warn",
        "probes": [
            {
                "name": "tv_storage_state_age",
                "severity": "warn",
                "message": "ageing",
                "details": {
                    "validated_at": "2026-06-20T00:00:00+00:00",
                    "age_hours": 60.0,
                    "max_age_hours": 72,
                },
            },
            {
                "name": "github_pat_validity",
                "severity": "ok",
                "message": "PAT valid",
                "details": {"days_left": 45},
            },
            {
                "name": "databento_delivery",
                "severity": "error",
                "message": "stale delivery",
                "details": {"staleness_days": 3.5},
            },
            {
                "name": "fmp_api_key",
                "severity": "ok",
                "message": "OK",
                "details": {},
            },
        ],
    }
    monkeypatch.setattr(metrics_mod.compute, "_load_credential_health_snapshot", lambda: report)

    body = metrics_mod.render_metrics(startup_ts=100.0)

    assert "live_overlay_credential_health_loaded 1.0" in body
    assert "live_overlay_credential_health_overall_valid 1.0" in body
    assert 'severity="warn"' in body
    assert "live_overlay_credential_health_tv_storage_state_age_severity_code 1.0" in body
    assert "live_overlay_credential_health_tv_storage_state_age_valid 1.0" in body
    assert "live_overlay_credential_health_tv_storage_state_age_age_hours 60.0" in body
    assert "live_overlay_credential_health_tv_storage_state_age_validated_at_seconds" in body
    assert "live_overlay_credential_health_github_pat_validity_severity_code 2.0" in body
    assert "live_overlay_credential_health_github_pat_validity_valid 1.0" in body
    assert "live_overlay_credential_health_github_pat_validity_days_left 45.0" in body
    assert "live_overlay_credential_health_databento_delivery_severity_code 0.0" in body
    assert "live_overlay_credential_health_databento_delivery_valid 0.0" in body
    assert "live_overlay_credential_health_databento_delivery_staleness_days 3.5" in body
    assert 'live_overlay_credential_health_fmp_api_key_info{severity="ok",message="OK"} 1' in body


def test_render_metrics_credential_health_missing_report_is_zeroed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import services.live_overlay_daemon.metrics as metrics_mod

    _patch_common(
        monkeypatch,
        feed_ready=True,
        market_open=True,
        bar_count=10,
        overlay_symbols=5,
        overlay_age=60.0,
    )
    monkeypatch.setattr(metrics_mod.compute, "_load_credential_health_snapshot", lambda: {})

    body = metrics_mod.render_metrics(startup_ts=100.0)

    assert "live_overlay_credential_health_loaded 0.0" in body
    assert "live_overlay_credential_health_overall_valid 0.0" in body
    assert "live_overlay_credential_health_tv_storage_state_age_severity_code" not in body


def test_render_metrics_handles_trading_signals_snapshot_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import services.live_overlay_daemon.metrics as metrics_mod

    _patch_common(
        monkeypatch,
        feed_ready=True,
        market_open=True,
        bar_count=10,
        overlay_symbols=5,
        overlay_age=60.0,
    )
    monkeypatch.setattr(metrics_mod.compute, "_load_signals_snapshot", lambda: {})

    body = metrics_mod.render_metrics(startup_ts=100.0)

    assert "live_overlay_trading_signals_loaded 0.0" in body
    assert "live_overlay_trading_signals_active 0.0" in body
    assert "live_overlay_trading_signals_snapshot_age_known 0.0" in body
    # No per-signal series when the snapshot is empty.
    assert "live_overlay_trading_signal_score{" not in body


def test_alert_rules_split_news_snapshot_unavailable_and_stale() -> None:
    """Unavailable snapshot (loaded==0) and stale snapshot (age>10800) must be separate alerts."""
    import yaml

    repo_root = Path(__file__).resolve().parents[1]
    rules_path = repo_root / "services" / "live_overlay_daemon" / "infra" / "grafana" / "alert-rules.yaml"
    rules_doc = yaml.safe_load(rules_path.read_text(encoding="utf-8"))
    warning_group = next(g for g in rules_doc["groups"] if g.get("name") == "live-overlay-warning")
    uids = {r.get("uid") for r in warning_group["rules"]}
    assert "lo-news-snapshot-unavailable" in uids
    assert "lo-news-snapshot-stale" in uids

    unavailable = next(r for r in warning_group["rules"] if r.get("uid") == "lo-news-snapshot-unavailable")
    assert unavailable["labels"]["severity"] == "high"
    assert "snapshot_loaded" in unavailable["data"][0]["model"]["expr"]
    assert "== bool 0" in unavailable["data"][0]["model"]["expr"]

    stale = next(r for r in warning_group["rules"] if r.get("uid") == "lo-news-snapshot-stale")
    assert "snapshot_age_seconds" in stale["data"][0]["model"]["expr"]
    assert "> bool 10800" in stale["data"][0]["model"]["expr"]
    # Unknown age (age_seconds=0) must not read as fresh. The stale rule must
    # gate on the known-flag; the unavailable rule covers loaded==0.
    assert "snapshot_age_known" in stale["data"][0]["model"]["expr"]


def test_alert_rules_cover_absence_of_every_core_readiness_gauge() -> None:
    """All three readiness inputs need an absent() guard, not just overlay_fresh.

    lo-scrape-missing only catches a whole-daemon outage. A *selective* export
    bug in one gauge was alert-blind, and each consumer fails silently rather
    than loudly when its input disappears:

    * ``feed_healthy`` — lo-feed-down-market-open computes
      ``market_us_open * ((1 - feed_healthy) + bar-age-term)``. Vector
      arithmetic inner-joins, so an empty ``(1 - feed_healthy)`` empties the
      entire sum: the bar-age term is lost as well and the feed-down alert
      goes silent exactly when the feed is what's in question.
    * ``workers_healthy`` — lo-workers-degraded evaluates ``< 1`` against an
      empty vector, which never crosses the threshold.
    """
    import yaml

    repo_root = Path(__file__).resolve().parents[1]
    rules_path = repo_root / "services" / "live_overlay_daemon" / "infra" / "grafana" / "alert-rules.yaml"
    rules_doc = yaml.safe_load(rules_path.read_text(encoding="utf-8"))
    all_rules = [rule for group in rules_doc["groups"] for rule in group["rules"]]
    guarded = " ".join(
        expr for expr in (rule["data"][0]["model"].get("expr", "") for rule in all_rules) if "absent(" in expr
    )
    for gauge in (
        "live_overlay_overlay_fresh",
        "live_overlay_feed_healthy",
        "live_overlay_workers_healthy",
    ):
        assert f"absent({gauge}" in guarded, (
            f"{gauge} has no absent() alert; if only that series stops being exported, "
            "its consuming rule evaluates an empty vector and never fires"
        )

    # The consumers this protects must still be the ones described above, so a
    # rename or rewrite re-opens the review rather than silently voiding it.
    by_uid = {rule.get("uid"): rule for rule in all_rules}
    assert "live_overlay_feed_healthy" in by_uid["lo-feed-down-market-open"]["data"][0]["model"]["expr"]
    assert "live_overlay_workers_healthy" in by_uid["lo-workers-degraded"]["data"][0]["model"]["expr"]


def test_alert_rules_cover_trading_signals_snapshot_unavailable() -> None:
    """A signals snapshot that never loads (loaded==0) must page on its own.

    Both sibling rules read 0 in that state — the stale rule consumes the
    exporter's ``_snapshot_stale`` verdict (which stays 0 while age_known==0)
    and the age-unknown rule is multiplied by ``_loaded`` — so without this rule
    a fresh deploy or a misconfigured SIGNALS_* URL leaves the A0/A1/A2 overlays
    blank with every signals alert green.
    """
    import yaml

    repo_root = Path(__file__).resolve().parents[1]
    rules_path = repo_root / "services" / "live_overlay_daemon" / "infra" / "grafana" / "alert-rules.yaml"
    rules_doc = yaml.safe_load(rules_path.read_text(encoding="utf-8"))
    warning_group = next(g for g in rules_doc["groups"] if g.get("name") == "live-overlay-warning")
    rules_by_uid = {r.get("uid"): r for r in warning_group["rules"]}
    assert "lo-trading-signals-snapshot-unavailable" in rules_by_uid, (
        "neither lo-trading-signals-snapshot-stale nor -age-unknown can fire while "
        "live_overlay_trading_signals_loaded == 0; a dedicated unavailable rule is required"
    )
    rule = rules_by_uid["lo-trading-signals-snapshot-unavailable"]
    expr = rule["data"][0]["model"]["expr"]
    assert "live_overlay_trading_signals_loaded" in expr
    assert "< bool 1" in expr
    assert rule["labels"]["severity"] == "high"
    # The sibling rules must keep their loaded-gating; this rule is what covers
    # the gap they leave, so it must not itself be gated on loaded.
    age_unknown_expr = rules_by_uid["lo-trading-signals-snapshot-age-unknown"]["data"][0]["model"]["expr"]
    assert "live_overlay_trading_signals_loaded" in age_unknown_expr


def test_uptimerobot_monitor_count_series_marked_keep_last_good() -> None:
    """Monitor-count gauges serve last-good data during a bridge outage.

    ``uptimerobot_bridge._snapshot`` keeps the previous counts/monitors when a
    scrape fails (only the status keys are overridden), so a legend reading
    plain "up"/"down" implies a live poll that is not happening. The legends and
    the panel description must say so; ``bridge_scrape_success``/``error_info``
    remain the truthful liveness signals.
    """
    import json

    repo_root = Path(__file__).resolve().parents[1]
    dash_path = repo_root / "services" / "live_overlay_daemon" / "infra" / "grafana" / "dashboard.json"
    dashboard = json.loads(dash_path.read_text(encoding="utf-8"))

    def _walk(obj: object):
        if isinstance(obj, dict):
            yield obj
            for value in obj.values():
                yield from _walk(value)
        elif isinstance(obj, list):
            for item in obj:
                yield from _walk(item)

    legends = [
        (node["expr"], node["legendFormat"])
        for node in _walk(dashboard)
        if isinstance(node.get("expr"), str)
        and "legendFormat" in node
        and "live_overlay_uptimerobot_monitors_" in node["expr"]
    ]
    assert legends, "expected uptimerobot monitor-count series in the dashboard"
    for expr, legend in legends:
        assert "last-good" in legend, (
            f"uptimerobot monitor series {expr!r} has legend {legend!r}, which implies live data "
            "although the bridge serves the last successful counts during an outage"
        )

    panel = next(
        node
        for node in _walk(dashboard)
        if node.get("title") == "UptimeRobot Monitors" and isinstance(node.get("description"), str)
    )
    assert "KEEP-LAST-GOOD" in panel["description"]


def test_age_unknown_gated_stale_alert_rules_require_known_age() -> None:
    """Every stale alert that reads an _age_seconds gauge must gate on the matching _known flag.

    The daemon exports age_seconds=0 when the underlying timestamp is missing,
    malformed, or unparseable. Without an explicit ``_known == 1`` gate the
    stale rule sees zero and stays silent, masking a broken producer.
    """
    import yaml

    repo_root = Path(__file__).resolve().parents[1]
    rules_path = repo_root / "services" / "live_overlay_daemon" / "infra" / "grafana" / "alert-rules.yaml"
    rules_doc = yaml.safe_load(rules_path.read_text(encoding="utf-8"))

    stale_rules = [
        ("live-overlay-warning", "lo-news-snapshot-stale", "snapshot_age_known"),
        ("evidence-and-workflow-freshness", "lo-evidence-snapshot-stale", "snapshot_age_known"),
        ("evidence-and-workflow-freshness", "lo-pine-library-snapshot-stale", "snapshot_age_known"),
        ("evidence-and-workflow-freshness", "lo-pine-library-data-stale", "data_age_known"),
        ("evidence-and-workflow-freshness", "lo-tv-binding-snapshot-stale", "snapshot_age_known"),
        ("evidence-and-workflow-freshness", "lo-evidence-ledger-stale", "ledger_age_known"),
        ("evidence-and-workflow-freshness", "lo-evidence-audit-branch-stale", "audit_branch_age_known"),
        ("evidence-and-workflow-freshness", "lo-evidence-wsh-stale", "wsh_age_known"),
        ("evidence-and-workflow-freshness", "lo-provider-usage-snapshot-stale", "snapshot_age_known"),
        ("credential-health", "lo-credential-monitor-stale", "snapshot_age_known"),
    ]

    for group_name, uid, known_metric in stale_rules:
        group = next(g for g in rules_doc["groups"] if g.get("name") == group_name)
        rule = next(r for r in group["rules"] if r.get("uid") == uid)
        expr = rule["data"][0]["model"]["expr"]
        assert known_metric in expr, f"{uid} must reference {known_metric} to avoid masking unknown age as zero"
        # Ensure the expression multiplies/gates by the known flag rather than
        # merely mentioning it in a comment or label selector.
        assert f"{known_metric}" in expr.replace(" ", ""), f"{uid} expression does not use {known_metric}"


def test_dashboard_service_status_panel_maps_starting_state() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    dashboard_path = repo_root / "services" / "live_overlay_daemon" / "infra" / "grafana" / "dashboard.json"
    dashboard = json.loads(dashboard_path.read_text(encoding="utf-8"))
    panel = next(p for p in dashboard["panels"] if p.get("title") == "Service Status")
    assert panel["targets"][0]["expr"] == 'max(live_overlay_health_status_code{job=~"$job"}) or on() vector(0)'
    options = panel["fieldConfig"]["defaults"]["mappings"][0]["options"]
    assert options.get("1", {}).get("text") == "STARTING"
    assert options.get("2", {}).get("text") == "IDLE (MARKET CLOSED)"
    assert options.get("3", {}).get("text") == "OK"


def test_stat_panel_targets_are_aggregated() -> None:
    """Every target on the binding `stat` panel must collapse to one value.

    A `stat` panel renders one tile per returned series. An unaggregated instant
    vector therefore turns a single reading into a row of tiles that grows with
    the series count — the panel silently reshapes itself as the label set
    changes. #3919 added six targets without the `max()` every pre-existing
    target carries; this is a property rather than another exact-string pin so
    the next addition cannot reintroduce it.
    """
    repo_root = Path(__file__).resolve().parents[1]
    dashboard_path = repo_root / "services" / "live_overlay_daemon" / "infra" / "grafana" / "dashboard.json"
    dashboard = json.loads(dashboard_path.read_text(encoding="utf-8"))
    panel = next(p for p in dashboard["panels"] if p.get("title") == "TradingView Binding Status")
    assert panel.get("type") == "stat", "this contract only holds for stat panels"

    unaggregated = [
        target["expr"]
        for target in panel["targets"]
        if not target["expr"].lstrip().startswith(("max(", "min(", "sum(", "avg(", "count("))
    ]
    assert not unaggregated, (
        "stat-panel targets must be wrapped in an aggregation so they collapse to "
        f"a single series; unaggregated: {unaggregated}"
    )


def test_dashboard_has_tradingview_binding_status_panel() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    dashboard_path = repo_root / "services" / "live_overlay_daemon" / "infra" / "grafana" / "dashboard.json"
    dashboard = json.loads(dashboard_path.read_text(encoding="utf-8"))
    panel = next(p for p in dashboard["panels"] if p.get("title") == "TradingView Binding Status")
    # The pin drifted: the panel gained the per-consumer and saved-source
    # targets without this set following, so it had been failing on main.
    # Re-pinned to the full panel, including the binding-coverage trio that
    # makes "0 of 7 consumers verified" readable next to the drift verdict.
    expressions = {target["expr"] for target in panel["targets"]}
    assert expressions == {
        'max(live_overlay_tv_binding_snapshot_loaded{job="live_overlay"})',
        'max(live_overlay_tv_binding_snapshot_age_seconds{job="live_overlay"}) / 3600',
        'max(live_overlay_tv_bindings_checked{job="live_overlay"})',
        'max(live_overlay_tv_binding_drift{job="live_overlay"})',
        'max(live_overlay_tv_binding_mismatches{job="live_overlay"})',
        'max(live_overlay_tv_binding_check_known{job="live_overlay"})',
        'max(live_overlay_tv_binding_consumers_expected{job="live_overlay"})',
        'max(live_overlay_tv_binding_consumers_checked{job="live_overlay"})',
        'max(live_overlay_tv_consumer_source_check_known{job="live_overlay"})',
        'max(live_overlay_tv_consumer_sources_checked{job="live_overlay"})',
        'max(live_overlay_tv_consumer_source_drift{job="live_overlay"})',
        'max(live_overlay_tv_binding_failed_consumers{job="live_overlay"})',
        'max(live_overlay_tv_consumer_binding_mismatches{job="live_overlay"})',
        'max(live_overlay_tv_consumer_sources_expected{job="live_overlay"})',
        'max(live_overlay_tv_consumer_sources_drifted{job="live_overlay"})',
        'max(live_overlay_tv_consumer_source_matches{job="live_overlay"})',
        'max(live_overlay_tv_consumer_source_failures{job="live_overlay"})',
    }


def test_dashboard_has_pine_library_data_freshness_panel() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    dashboard_path = repo_root / "services" / "live_overlay_daemon" / "infra" / "grafana" / "dashboard.json"
    dashboard = json.loads(dashboard_path.read_text(encoding="utf-8"))
    panel = next(p for p in dashboard["panels"] if p.get("title") == "Pine library data freshness")
    expressions = {target["expr"] for target in panel["targets"]}
    assert expressions == {
        'max(live_overlay_pine_library_data_age_seconds{job="live_overlay",library="smc_micro_profiles_generated"}) / 86400',
        'max(live_overlay_pine_library_data_age_known{job="live_overlay",library="smc_micro_profiles_generated"})',
    }


def test_pine_library_data_stale_alert_uses_five_day_threshold() -> None:
    # 432000s = 5 days, resized 2026-07-22 to the T-1 + morning-refresh
    # cadence (2 days false-fired nightly; weekend peak is ~4d13h) — full
    # rationale in the rule comment and in
    # test_micro_profile_stale_threshold_absorbs_weekday_cadence.
    import yaml

    repo_root = Path(__file__).resolve().parents[1]
    rules_path = repo_root / "services" / "live_overlay_daemon" / "infra" / "grafana" / "alert-rules.yaml"
    rules_doc = yaml.safe_load(rules_path.read_text(encoding="utf-8"))
    group = next(g for g in rules_doc["groups"] if g.get("name") == "evidence-and-workflow-freshness")
    rule = next(r for r in group["rules"] if r.get("uid") == "lo-pine-library-data-stale")
    expr = rule["data"][0]["model"]["expr"]
    assert "live_overlay_pine_library_data_age_known" in expr
    assert "live_overlay_pine_library_data_age_seconds" in expr
    assert "> bool 432000" in expr
    assert rule["labels"]["severity"] == "critical"


def test_pine_library_empty_probe_alert_detects_loaded_but_empty_snapshot() -> None:
    import yaml

    repo_root = Path(__file__).resolve().parents[1]
    rules_path = repo_root / "services" / "live_overlay_daemon" / "infra" / "grafana" / "alert-rules.yaml"
    rules_doc = yaml.safe_load(rules_path.read_text(encoding="utf-8"))
    group = next(g for g in rules_doc["groups"] if g.get("name") == "evidence-and-workflow-freshness")
    rule = next(r for r in group["rules"] if r.get("uid") == "lo-pine-library-no-probes")
    expr = rule["data"][0]["model"]["expr"]
    assert "live_overlay_pine_library_snapshot_loaded" in expr
    assert "live_overlay_pine_libraries_probed" in expr
    assert "== bool 0" in expr
    assert rule["labels"]["severity"] == "critical"


def test_tradingview_saved_source_alerts_fail_closed_on_unknown_or_drift() -> None:
    import yaml

    repo_root = Path(__file__).resolve().parents[1]
    rules_path = repo_root / "services" / "live_overlay_daemon" / "infra" / "grafana" / "alert-rules.yaml"
    rules_doc = yaml.safe_load(rules_path.read_text(encoding="utf-8"))
    group = next(g for g in rules_doc["groups"] if g.get("name") == "evidence-and-workflow-freshness")
    by_uid = {rule["uid"]: rule for rule in group["rules"]}
    missing = by_uid["lo-tv-consumer-source-check-missing"]
    drift = by_uid["lo-tv-consumer-source-drift"]
    assert "source_check_known" in missing["data"][0]["model"]["expr"]
    assert "== bool 0" in missing["data"][0]["model"]["expr"]
    assert "source_check_known" in drift["data"][0]["model"]["expr"]
    assert "source_drift" in drift["data"][0]["model"]["expr"]
    assert missing["labels"]["severity"] == "critical"
    assert drift["labels"]["severity"] == "critical"


def test_tradingview_binding_snapshot_stale_alert_uses_24_hour_threshold() -> None:
    import yaml

    repo_root = Path(__file__).resolve().parents[1]
    rules_path = repo_root / "services" / "live_overlay_daemon" / "infra" / "grafana" / "alert-rules.yaml"
    rules_doc = yaml.safe_load(rules_path.read_text(encoding="utf-8"))
    group = next(g for g in rules_doc["groups"] if g.get("name") == "evidence-and-workflow-freshness")
    rule = next(r for r in group["rules"] if r.get("uid") == "lo-tv-binding-snapshot-stale")
    expr = rule["data"][0]["model"]["expr"]
    assert "live_overlay_tv_binding_snapshot_loaded" in expr
    assert "live_overlay_tv_binding_snapshot_age_known" in expr
    assert "live_overlay_tv_binding_snapshot_age_seconds" in expr
    assert "> bool 86400" in expr
    assert rule["labels"]["severity"] == "warning"


def test_dashboard_overall_health_distinguishes_starting_from_idle() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    dashboard_path = repo_root / "services" / "live_overlay_daemon" / "infra" / "grafana" / "dashboard.json"
    dashboard = json.loads(dashboard_path.read_text(encoding="utf-8"))
    panel = next(p for p in dashboard["panels"] if p.get("title") == "Overall Health")
    assert panel["targets"][0]["expr"] == 'max(live_overlay_health_status_code{job=~"$job"}) or on() vector(0)'
    options = panel["fieldConfig"]["defaults"]["mappings"][0]["options"]
    assert options.get("1", {}).get("text") == "STARTING"
    assert options.get("2", {}).get("text") == "IDLE (MARKET CLOSED)"
    assert options.get("3", {}).get("text") == "HEALTHY"


def test_dashboard_worker_liveness_uses_human_labels() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    dashboard_path = repo_root / "services" / "live_overlay_daemon" / "infra" / "grafana" / "dashboard.json"
    dashboard = json.loads(dashboard_path.read_text(encoding="utf-8"))
    panel = next(p for p in dashboard["panels"] if p.get("title") == "Worker Liveness")
    options = panel["fieldConfig"]["defaults"]["mappings"][0]["options"]
    assert options.get("0", {}).get("text") == "DEAD"
    assert options.get("1", {}).get("text") == "ALIVE"
    assert "min" not in panel["fieldConfig"]["defaults"]
    assert "max" not in panel["fieldConfig"]["defaults"]


def test_dashboard_has_uptimerobot_state_timeline() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    dashboard_path = repo_root / "services" / "live_overlay_daemon" / "infra" / "grafana" / "dashboard.json"
    dashboard = json.loads(dashboard_path.read_text(encoding="utf-8"))
    panel = next(p for p in dashboard["panels"] if p.get("title") == "UptimeRobot Monitor States")
    assert panel["type"] == "state-timeline"
    assert any("live_overlay_uptimerobot_monitor_.*_status_code" in t["expr"] for t in panel["targets"])
    target = panel["targets"][0]
    assert 'job=~"$job"' in target["expr"]
    assert 'job="$job"' not in target["expr"]
    assert target["datasource"] == {"type": "prometheus", "uid": "grafanacloud-prom"}
    options = panel["fieldConfig"]["defaults"]["mappings"][0]["options"]
    assert options.get("0", {}).get("text") == "PAUSED"
    assert options.get("8", {}).get("text") == "DOWN"


def test_dashboard_github_workflow_runs_panel_uses_snapshot_counts() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    dashboard_path = repo_root / "services" / "live_overlay_daemon" / "infra" / "grafana" / "dashboard.json"
    dashboard = json.loads(dashboard_path.read_text(encoding="utf-8"))
    panel = next(p for p in dashboard["panels"] if p.get("title") == "GitHub Workflow Runs")
    expected_exprs = {
        "seen": 'live_overlay_github_workflow_runs_seen_total{job=~"$job"}',
        "success": 'live_overlay_github_workflow_runs_success_total{job=~"$job"}',
        "failed": 'live_overlay_github_workflow_runs_failed_total{job=~"$job"}',
        "in_progress": 'live_overlay_github_workflow_runs_in_progress_total{job=~"$job"}',
        "queued": 'live_overlay_github_workflow_runs_queued_total{job=~"$job"}',
    }
    actual_exprs = {t["legendFormat"]: t["expr"] for t in panel["targets"]}
    assert actual_exprs == expected_exprs
    assert panel["fieldConfig"]["defaults"]["unit"] == "none"
    assert panel["fieldConfig"]["defaults"]["custom"]["axisLabel"] == "runs (snapshot)"


def test_dashboard_has_trading_signals_panels() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    dashboard_path = (
        repo_root / "services" / "live_overlay_daemon" / "infra" / "grafana" / "dashboard-signals-experiments.json"
    )
    dashboard = json.loads(dashboard_path.read_text(encoding="utf-8"))
    by_title = {p.get("title"): p for p in dashboard["panels"]}

    active = by_title["Active Trading Signals"]
    assert active["type"] == "stat"
    assert any(t["expr"].startswith("live_overlay_trading_signals_active{") for t in active["targets"])

    # A2 early-warning tier is first-class on the dashboard (added 2026-07-08):
    # its own stat tile + a coloured mapping in the detail table's Level column.
    a2_tile = by_title["A2 Early-Warning"]
    assert a2_tile["type"] == "stat"
    assert any(t["expr"].startswith("live_overlay_trading_signals_a2{") for t in a2_tile["targets"])
    level_ov = next(
        ov for ov in by_title["Top Trading Signals — Latest Detail"]["fieldConfig"]["overrides"]
        if ov["matcher"].get("options") == "Level"
    )
    mappings = next(p for p in level_ov["properties"] if p["id"] == "mappings")["value"][0]["options"]
    assert {"A0", "A1", "A2"} <= set(mappings)

    age = by_title["Signals Snapshot Age"]
    assert age["fieldConfig"]["defaults"]["unit"] == "s"
    assert any("live_overlay_trading_signals_snapshot_age_seconds" in t["expr"] for t in age["targets"])
    assert any("live_overlay_trading_signals_snapshot_age_known" in t["expr"] for t in age["targets"])

    table = by_title["Top Trading Signals — Latest Detail"]
    assert table["type"] == "table"
    exprs = {t["expr"] for t in table["targets"]}
    assert any("live_overlay_trading_signal_score{" in e for e in exprs)
    assert any("live_overlay_trading_signal_technical_score{" in e for e in exprs)
    assert any("live_overlay_trading_signal_change_pct{" in e for e in exprs)
    assert any("live_overlay_trading_signal_freshness{" in e for e in exprs)
    # The numeric series share the same label set so the merge collapses them
    # onto one row per signal; instant queries are required for an at-a-glance
    # snapshot table.
    assert all(t.get("instant") for t in table["targets"])
    assert any(tr["id"] == "merge" for tr in table["transformations"])

    ts_panel = by_title["Signal Score — Active Symbols"]
    assert ts_panel["type"] == "timeseries"
    assert ts_panel["targets"][0]["legendFormat"] == "{{symbol}} {{level}} {{direction}}"


def test_signals_experiments_dashboard_is_packed_from_top() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    dashboard_path = (
        repo_root / "services" / "live_overlay_daemon" / "infra" / "grafana" / "dashboard-signals-experiments.json"
    )
    dashboard = json.loads(dashboard_path.read_text(encoding="utf-8"))
    y_values = [p["gridPos"]["y"] for p in dashboard["panels"]]
    assert min(y_values) == 0


def test_provider_health_snapshot_classifies_state_reason_and_consumed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Disabled providers are excluded from health; degraded reasons are mapped."""
    import services.live_overlay_daemon.compute as compute_mod
    import services.live_overlay_daemon.metrics as metrics_mod

    snapshot = {
        "fetched_at_unix": 0,
        "providers": {
            "newsapi_ai": {"ok": True, "error": None, "raw_count": 12, "new_item_count": 3},
            "benzinga": {"ok": False, "error": "disabled"},
            "fmp_press": {"ok": False, "error": "missing_api_key"},
            "fmp_articles": {"ok": False, "error": "fetch_failed: 403 forbidden no subscription"},
            "tv": {"ok": None},
        },
    }
    snap_path = tmp_path / "smc_live_news_snapshot.json"
    snap_path.write_text(json.dumps(snapshot), encoding="utf-8")
    monkeypatch.setattr(metrics_mod.config, "news_snapshot_path", lambda: snap_path)
    # Deterministic read: provider-health uses the shared compute loader which
    # is TTL-cached process-wide. Reset it so this test does not inherit a
    # prior snapshot from another case (testmon/shard order dependent).
    monkeypatch.setattr(compute_mod.config, "news_snapshot_url", lambda: "")
    monkeypatch.setattr(compute_mod, "_news_loaded_at", 0.0)
    monkeypatch.setattr(compute_mod, "_news_checked_at", 0.0)
    monkeypatch.setattr(compute_mod, "_news_cache", {})

    health = metrics_mod._provider_health_snapshot()

    assert health["news_providers_total"] == 5.0
    assert health["news_providers_ok_total"] == 1.0
    assert health["news_providers_degraded_total"] == 2.0
    assert health["news_providers_unknown_total"] == 1.0
    assert health["news_providers_disabled_total"] == 1.0
    # disabled provider is not consumed; everything else is.
    assert health["news_providers_consumed_total"] == 4.0
    # benzinga disabled must NOT drag health into degraded by itself,
    # but the missing-key / unknown providers still mark it degraded.
    assert health["news_health_degraded"] == 1.0
    assert health["news_health_ok"] == 0.0

    info = {row["provider"]: row for row in health["news_provider_info"]}
    assert info["benzinga"]["state"] == "disabled"
    assert info["benzinga"]["consumed"] == "false"
    assert info["benzinga"]["reason"] == "Provider disabled (not ingested)"
    assert info["fmp_press"]["state"] == "degraded"
    assert info["fmp_press"]["reason"] == "API key missing"
    assert info["fmp_articles"]["reason"] == "No active subscription"
    assert info["tv"]["state"] == "unknown"
    assert info["newsapi_ai"]["state"] == "ok"
    assert info["newsapi_ai"]["reason"] == "OK"

    assert health["news_provider_state_code"]["benzinga"] == 3.0
    assert health["news_provider_consumed"]["benzinga"] == 0.0
    assert health["news_provider_consumed"]["newsapi_ai"] == 1.0


@pytest.mark.parametrize("last_ingest_success_at", [float("inf"), float("-inf"), float("nan")])
def test_provider_health_ignores_non_finite_ingest_marker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, last_ingest_success_at: float
) -> None:
    import services.live_overlay_daemon.compute as compute_mod
    import services.live_overlay_daemon.metrics as metrics_mod

    snapshot = {
        "fetched_at_unix": 0,
        "last_ingest_success_at": last_ingest_success_at,
        "providers": {"newsapi_ai": {"ok": True, "error": None}},
    }
    snap_path = tmp_path / "smc_live_news_snapshot.json"
    snap_path.write_text(json.dumps(snapshot), encoding="utf-8")
    monkeypatch.setattr(metrics_mod.config, "news_snapshot_path", lambda: snap_path)
    monkeypatch.setattr(compute_mod.config, "news_snapshot_url", lambda: "")
    monkeypatch.setattr(compute_mod, "_news_loaded_at", 0.0)
    monkeypatch.setattr(compute_mod, "_news_checked_at", 0.0)
    monkeypatch.setattr(compute_mod, "_news_cache", {})

    health = metrics_mod._provider_health_snapshot()

    assert health["news_last_ingest_age_known"] == 0.0
    assert health["news_last_ingest_age_seconds"] == 0.0


def test_provider_health_snapshot_all_disabled_except_consumed_ok(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When only one provider is consumed and it is OK, health must be OK."""
    import services.live_overlay_daemon.compute as compute_mod
    import services.live_overlay_daemon.metrics as metrics_mod

    snapshot = {
        "fetched_at_unix": 0,
        "providers": {
            "newsapi_ai": {"ok": True, "error": None},
            "benzinga": {"ok": False, "error": "disabled"},
            "fmp_stock": {"ok": False, "error": "disabled"},
            "tv": {"ok": False, "error": "disabled"},
        },
    }
    snap_path = tmp_path / "smc_live_news_snapshot.json"
    snap_path.write_text(json.dumps(snapshot), encoding="utf-8")
    monkeypatch.setattr(metrics_mod.config, "news_snapshot_path", lambda: snap_path)
    # Metrics derive from the shared (TTL-cached) compute loader; reset its
    # cache so the patched snapshot path is read fresh and no URL is used.
    monkeypatch.setattr(compute_mod.config, "news_snapshot_url", lambda: "")
    monkeypatch.setattr(compute_mod, "_news_loaded_at", 0.0)
    monkeypatch.setattr(compute_mod, "_news_checked_at", 0.0)
    monkeypatch.setattr(compute_mod, "_news_cache", {})

    health = metrics_mod._provider_health_snapshot()

    assert health["news_providers_consumed_total"] == 1.0
    assert health["news_providers_disabled_total"] == 3.0
    assert health["news_health_ok"] == 1.0
    assert health["news_health_degraded"] == 0.0
    assert health["news_health_unknown"] == 0.0


def test_render_metrics_includes_daily_experiment_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import services.live_overlay_daemon.metrics as metrics_mod

    _patch_common(
        monkeypatch,
        feed_ready=True,
        market_open=True,
        bar_count=10,
        overlay_symbols=5,
        overlay_age=60.0,
    )
    rollup = {
        "schema_version": 1,
        "scoring_root": "/x/artifacts/ci/measurement_benchmark_rolling/2026-06-21",
        "files_scanned": 1234,
        "per_tf": {
            "5m": {
                "n_events": 200,
                "hit_rate": 0.61,
                "symbols": ["AAPL"],
                "families": {
                    "FVG": {"n_events": 80, "hit_rate": 0.7},
                    "SWEEP": {"n_events": 40, "hit_rate": 0.55},
                },
            },
            "4H": {
                "n_events": 50,
                "hit_rate": 0.48,
                "families": {"BOS": {"n_events": 30, "hit_rate": 0.5}},
            },
        },
        "phase_e2_verdict": {
            "fvg_ttf_5m_vs_baseline": {
                "status": "measured",
                "delta_hr": 0.08,
                "delta_hr_p_value": 0.012,
                "underpowered": False,
                "n_a": 80,
                "n_b": 90,
            },
            "bos_stability_4h_vs_baseline": {
                "status": "insufficient_data",
                "n_a": 5,
                "n_b": 7,
            },
        },
    }
    history = [
        {
            "captured_at": "2026-06-20T13:00:00Z",
            "per_tf": {
                "5m": {
                    "n_events": 180,
                    "hit_rate": 0.58,
                    "families": {"FVG": {"n_events": 70, "hit_rate": 0.66}},
                }
            },
        },
        {
            "captured_at": "2026-06-21T13:00:00Z",
            "per_tf": {
                "5m": {
                    "n_events": 200,
                    "hit_rate": 0.61,
                    "families": {"FVG": {"n_events": 80, "hit_rate": 0.7}},
                }
            },
        },
    ]
    monkeypatch.setattr(metrics_mod.compute, "_load_experiment_snapshot", lambda: rollup)
    monkeypatch.setattr(metrics_mod.compute, "_load_experiment_history", lambda: history)

    body = metrics_mod.render_metrics(startup_ts=100.0)

    assert "live_overlay_experiment_loaded 1.0" in body
    assert "live_overlay_experiment_files_scanned 1234.0" in body
    # The dated scoring_root yields a known run age.
    assert "live_overlay_experiment_snapshot_age_known 1.0" in body
    # Per-timeframe aggregates.
    assert 'live_overlay_experiment_tf_hit_rate{timeframe="5m"} 0.61' in body
    assert 'live_overlay_experiment_tf_n_events{timeframe="4H"} 50.0' in body
    # Per-family detail.
    assert 'live_overlay_experiment_family_hit_rate{timeframe="5m",family="FVG"} 0.7' in body
    assert 'live_overlay_experiment_family_n_events{timeframe="5m",family="SWEEP"} 40.0' in body
    # Phase E2 verdicts mapped to numeric codes; p-value only when measured.
    assert 'live_overlay_experiment_verdict_status_code{hypothesis="fvg_5m",status="measured"} 4.0' in body
    assert 'live_overlay_experiment_verdict_status_code{hypothesis="bos_4h",status="insufficient_data"} 1.0' in body
    assert 'live_overlay_experiment_verdict_p_value{hypothesis="fvg_5m",status="measured"} 0.012' in body
    # p-value is omitted for the insufficient-data verdict (no false 0).
    assert 'live_overlay_experiment_verdict_p_value{hypothesis="bos_4h"' not in body
    # Per-day backfilled history series, one per (run_date, timeframe, family).
    assert 'live_overlay_experiment_day_family_hit_rate{run_date="2026-06-20",timeframe="5m",family="FVG"} 0.66' in body
    assert 'live_overlay_experiment_day_family_hit_rate{run_date="2026-06-21",timeframe="5m",family="FVG"} 0.7' in body


def test_experiment_date_accepts_current_results_prefixed_scoring_root() -> None:
    import services.live_overlay_daemon.metrics as metrics_mod

    assert metrics_mod._experiment_date_from_root(
        "/workspace/evaluation/plan_2_8/results_2026-07-19"
    ) == "2026-07-19"
    assert metrics_mod._experiment_date_from_root(
        "/workspace/evaluation/plan_2_8/results_not-a-date"
    ) == ""


def test_render_metrics_handles_daily_experiment_snapshot_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import services.live_overlay_daemon.metrics as metrics_mod

    _patch_common(
        monkeypatch,
        feed_ready=True,
        market_open=True,
        bar_count=10,
        overlay_symbols=5,
        overlay_age=60.0,
    )
    monkeypatch.setattr(metrics_mod.compute, "_load_experiment_snapshot", lambda: {})
    monkeypatch.setattr(metrics_mod.compute, "_load_experiment_history", lambda: [])

    body = metrics_mod.render_metrics(startup_ts=100.0)

    assert "live_overlay_experiment_loaded 0.0" in body
    assert "live_overlay_experiment_snapshot_age_known 0.0" in body
    assert "live_overlay_experiment_files_scanned 0.0" in body
    # No per-family or per-day series when nothing is available.
    assert "live_overlay_experiment_family_hit_rate{" not in body
    assert "live_overlay_experiment_day_family_hit_rate{" not in body


def test_dashboard_has_daily_experiment_panels() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    dashboard_path = (
        repo_root / "services" / "live_overlay_daemon" / "infra" / "grafana" / "dashboard-signals-experiments.json"
    )
    dashboard = json.loads(dashboard_path.read_text(encoding="utf-8"))
    by_title = {p.get("title"): p for p in dashboard["panels"]}

    age = by_title["Daily Experiment — Snapshot Age"]
    assert age["fieldConfig"]["defaults"]["unit"] == "s"
    assert any("live_overlay_experiment_snapshot_age_seconds" in t["expr"] for t in age["targets"])
    assert any("live_overlay_experiment_snapshot_age_known" in t["expr"] for t in age["targets"])

    fvg = by_title["FVG 5m Verdict (Phase E2)"]
    assert any(
        'hypothesis="fvg_5m"' in t["expr"] and "live_overlay_experiment_verdict_status_code" in t["expr"]
        for t in fvg["targets"]
    )
    fvg_map = fvg["fieldConfig"]["defaults"]["mappings"][0]["options"]
    assert fvg_map["4"]["text"] == "measured"

    detail = by_title["Daily Experiment — Latest Per-Family Detail"]
    assert detail["type"] == "table"
    exprs = {t["expr"] for t in detail["targets"]}
    assert any("live_overlay_experiment_family_hit_rate{" in e for e in exprs)
    assert any("live_overlay_experiment_family_n_events{" in e for e in exprs)
    assert all(t.get("instant") for t in detail["targets"])
    assert any(tr["id"] == "merge" for tr in detail["transformations"])

    ts_panel = by_title["Family Hit-Rate Over Time (accumulates daily)"]
    assert ts_panel["type"] == "timeseries"
    assert ts_panel["targets"][0]["legendFormat"] == "{{timeframe}} · {{family}}"

    history = by_title["Per-Day Family Hit-Rate — History (backfilled)"]
    assert history["type"] == "table"
    hist_exprs = {t["expr"] for t in history["targets"]}
    assert any("live_overlay_experiment_day_family_hit_rate{" in e for e in hist_exprs)
    assert any(tr["id"] == "merge" for tr in history["transformations"])


def test_dashboard_railway_panels_query_emitted_metrics() -> None:
    from pathlib import Path

    repo_root = Path(__file__).resolve().parents[1]
    dashboard_path = repo_root / "services" / "live_overlay_daemon" / "infra" / "grafana" / "dashboard.json"
    dashboard = json.loads(dashboard_path.read_text(encoding="utf-8"))

    emitted = {
        "live_overlay_railway_service_cpu_cores",
        "live_overlay_railway_service_memory_used_ratio",
        "live_overlay_railway_service_disk_gb",
        "live_overlay_railway_service_network_rx_gb",
        "live_overlay_railway_service_network_tx_gb",
        "live_overlay_railway_service_memory_limit_gb",
        # Wired to the Memory Limit panel by #3919; emitted in metrics.py
        # with service labels, so this literal has to name it explicitly.
        "live_overlay_railway_service_memory_gb",
    }
    expected_titles = {
        "Railway CPU Cores",
        "Railway Memory Used Ratio",
        "Railway Disk Usage (GB)",
        "Railway Network RX (GB)",
        "Railway Network TX (GB)",
        "Railway Memory Limit (GB)",
    }
    by_title = {p["title"]: p for p in dashboard["panels"]}
    missing_titles = expected_titles - by_title.keys()
    assert not missing_titles, f"Missing Railway panels: {missing_titles}"

    queried = set()
    for title in expected_titles:
        panel = by_title[title]
        for target in panel.get("targets", []):
            expr = target.get("expr", "")
            metric = expr.split("{")[0].split("(")[-1]
            queried.add(metric)

    missing_metrics = emitted - queried
    assert not missing_metrics, f"Railway panels do not query emitted metrics: {missing_metrics}"

    bad = queried - emitted
    assert not bad, f"Railway panels query non-existent metrics: {bad}"


def test_inert_restart_counters_are_no_longer_emitted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """live_overlay_daemon_restarts_total and restart_cause_*_total lived in
    process memory, so every restart reset them to 1. Prometheus saw 1,1,1,...
    -- no decrease, so no counter reset was detected, so increase()/rate() were
    structurally 0. Measured in production 2026-07-23: the series read 1 while
    changes(live_overlay_process_start_time_seconds[24h]) read 51.

    Both facts are served truthfully elsewhere (restart count via
    changes(process_start_time_seconds), cause via the labeled start-time gauge
    pinned in the next test), so these two are removed rather than documented
    around for a third time.
    """
    import services.live_overlay_daemon.main as main_mod
    import services.live_overlay_daemon.metrics as metrics_mod

    source = Path(main_mod.__file__).read_text(encoding="utf-8")
    assert '"live_overlay.daemon.restarts_total"' not in source
    assert "live_overlay.daemon.restart_cause." not in source

    _patch_common(
        monkeypatch,
        feed_ready=True,
        market_open=True,
        bar_count=10,
        overlay_symbols=5,
        overlay_age=60.0,
    )
    body = metrics_mod.render_metrics(startup_ts=100.0)
    assert "live_overlay_daemon_restarts_total" not in body
    assert "live_overlay_daemon_restart_cause_" not in body
    # The working replacement must still be there — removing the inert pair
    # must not take the cause attribution with it.
    assert "live_overlay_daemon_start_time_seconds{" in body


def test_render_metrics_emits_restart_cause_as_labeled_start_time_gauge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Restart-cause attribution is a start-time-VALUED gauge LABELED by cause.

    ``changes(live_overlay_daemon_start_time_seconds[window])`` grouped by cause
    counts real restarts per cause; the old per-cause ``*_total`` counters were
    reset to 1 each process, so ``increase()`` over them was always 0.
    """
    import services.live_overlay_daemon.metrics as metrics_mod

    _patch_common(
        monkeypatch,
        feed_ready=True,
        market_open=True,
        bar_count=10,
        overlay_symbols=5,
        overlay_age=60.0,
    )
    monkeypatch.setattr(metrics_mod.config, "restart_cause", lambda: "deploy")

    body = metrics_mod.render_metrics(startup_ts=100.0, startup_epoch=1700000000.0)
    assert "# TYPE live_overlay_daemon_start_time_seconds gauge" in body
    assert (
        'live_overlay_daemon_start_time_seconds{cause="deploy"} 1700000000.000' in body
    )


def test_dashboard_all_panels_have_datasource() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    expected = {"type": "prometheus", "uid": "grafanacloud-prom"}
    for dashboard_name in ("dashboard.json", "dashboard-signals-experiments.json"):
        dashboard_path = repo_root / "services" / "live_overlay_daemon" / "infra" / "grafana" / dashboard_name
        dashboard = json.loads(dashboard_path.read_text(encoding="utf-8"))
        for panel in dashboard["panels"]:
            if panel.get("type") == "row":
                continue
            assert panel.get("datasource") == expected, panel.get("title")
            for target in panel.get("targets", []):
                assert target.get("datasource") == expected, panel.get("title")


def test_dashboard_all_panels_have_stable_id() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    dashboard_path = repo_root / "services" / "live_overlay_daemon" / "infra" / "grafana" / "dashboard.json"
    dashboard = json.loads(dashboard_path.read_text(encoding="utf-8"))
    ids = []
    panels = list(dashboard["panels"])
    for panel in dashboard["panels"]:
        panels.extend(panel.get("panels") or [])
    for panel in panels:
        assert "id" in panel, panel.get("title")
        assert isinstance(panel["id"], int), panel.get("title")
        ids.append(panel["id"])
    assert len(ids) == len(set(ids)), "duplicate panel ids"


def test_render_metrics_always_emits_traffic_counters(monkeypatch: pytest.MonkeyPatch) -> None:
    """Traffic counters must be present even before the first request.

    Grafana panels "Success Rate (%)" and "Market-open Request Health" use
    rate() over live_overlay_smc_live_requests_total / _success_total.  When
    the daemon starts and no request has arrived yet, these counters do not
    exist in the in-process counter dict, so Prometheus returns "No data".
    The renderer must seed them as 0.0 so the series are always scraped.
    """
    import services.live_overlay_daemon.metrics as metrics_mod
    import services.live_overlay_daemon.observability as obs

    _patch_common(
        monkeypatch,
        feed_ready=True,
        market_open=True,
        bar_count=10,
        overlay_symbols=5,
        overlay_age=60.0,
    )

    with obs._counter_lock:
        obs._counters.clear()

    body = metrics_mod.render_metrics(startup_ts=100.0)

    assert "live_overlay_smc_live_requests_total 0.0" in body
    assert "live_overlay_smc_live_success_total 0.0" in body
    assert "live_overlay_smc_live_errors_total 0.0" in body
    assert "live_overlay_smc_live_auth_denied 0.0" in body
    assert "live_overlay_smc_live_bad_tf_total 0.0" in body
    assert "live_overlay_smc_live_cache_miss_total 0.0" in body
    assert "live_overlay_smc_live_stale_served_total 0.0" in body


def test_dashboard_job_variable_allows_multi_and_all() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    dashboard_path = repo_root / "services" / "live_overlay_daemon" / "infra" / "grafana" / "dashboard.json"
    dashboard = json.loads(dashboard_path.read_text(encoding="utf-8"))
    job_var = next(v for v in dashboard["templating"]["list"] if v["name"] == "job")
    assert job_var["multi"] is True
    assert job_var["includeAll"] is True


def test_render_metrics_emits_latency_histogram_before_first_observation(monkeypatch: pytest.MonkeyPatch) -> None:
    """Classic histogram series must exist before the first observation.

    histogram_quantile() over _bucket needs a complete, stable bucket set on
    every scrape. Without observations the exporter must still emit _bucket,
    _sum and _count lines with value 0.
    """
    import services.live_overlay_daemon.metrics as metrics_mod
    import services.live_overlay_daemon.observability as obs

    _patch_common(
        monkeypatch,
        feed_ready=True,
        market_open=True,
        bar_count=10,
        overlay_symbols=5,
        overlay_age=60.0,
    )

    with obs._counter_lock:
        obs._counters.clear()

    body = metrics_mod.render_metrics(startup_ts=100.0)

    assert "# TYPE live_overlay_smc_live_latency_ms histogram" in body
    assert 'live_overlay_smc_live_latency_ms_bucket{le="+Inf"} 0.0' in body
    assert "live_overlay_smc_live_latency_ms_sum 0.0" in body
    assert "live_overlay_smc_live_latency_ms_count 0.0" in body
    assert body.count("live_overlay_smc_live_latency_ms_bucket{") >= 2


def test_render_metrics_exports_generic_bridge_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """All bridges must emit the generic contract series."""
    import services.live_overlay_daemon.metrics as metrics_mod

    _patch_common(
        monkeypatch,
        feed_ready=True,
        market_open=True,
        bar_count=10,
        overlay_symbols=5,
        overlay_age=60.0,
    )
    monkeypatch.setattr(
        metrics_mod.uptimerobot_bridge,
        "snapshot",
        lambda: {
            "enabled": 1,
            "configured": 1,
            "ok": 1,
            "fetched_at_unix": 1_700_000_000.0,
            "last_success_fetched_at_unix": 1_700_000_000.0,
            "scrape_duration_seconds": 0.111,
            "error_code": "",
            "counts": {"total": 0, "up": 0, "down": 0, "paused": 0, "unknown": 0},
            "avg_response_time_ms": None,
            "monitors": [],
        },
    )
    monkeypatch.setattr(
        metrics_mod.github_workflow_bridge,
        "snapshot",
        lambda: {
            "enabled": 1,
            "configured": 1,
            "ok": 0,
            "fetched_at_unix": 0.0,
            "scrape_duration_seconds": 0.222,
            "error_code": "http401",
            "counts": {"seen": 0, "success": 0, "failed": 0, "in_progress": 0, "queued": 0},
            "latest_run_age_seconds": None,
            "latest_run_duration_seconds": None,
            "workflows": [],
        },
    )
    monkeypatch.setattr(
        metrics_mod.railway_metrics,
        "snapshot",
        lambda: {
            "enabled": True,
            "configured": False,
            "ok": False,
            "fetched_at_unix": 0.0,
            "scrape_duration_seconds": 0.333,
            "error": "missing_configuration",
            "services": [],
        },
    )

    body = metrics_mod.render_metrics(startup_ts=100.0)

    assert 'live_overlay_bridge_enabled{bridge="uptimerobot"} 1' in body
    assert 'live_overlay_bridge_configured{bridge="uptimerobot"} 1' in body
    assert 'live_overlay_bridge_scrape_success{bridge="uptimerobot"} 1' in body
    assert 'live_overlay_bridge_last_scrape_duration_seconds{bridge="uptimerobot"} 0.111' in body
    assert 'live_overlay_bridge_error_info{bridge="uptimerobot",error="none"} 0' in body

    assert 'live_overlay_bridge_enabled{bridge="github_workflow"} 1' in body
    assert 'live_overlay_bridge_configured{bridge="github_workflow"} 1' in body
    assert 'live_overlay_bridge_scrape_success{bridge="github_workflow"} 0' in body
    assert 'live_overlay_bridge_last_scrape_duration_seconds{bridge="github_workflow"} 0.222' in body
    assert 'live_overlay_bridge_error_info{bridge="github_workflow",error="http401"} 1' in body

    assert 'live_overlay_bridge_enabled{bridge="railway_metrics"} 1' in body
    assert 'live_overlay_bridge_configured{bridge="railway_metrics"} 0' in body
    assert 'live_overlay_bridge_scrape_success{bridge="railway_metrics"} 0' in body
    assert 'live_overlay_bridge_last_scrape_duration_seconds{bridge="railway_metrics"} 0.333' in body
    assert 'live_overlay_bridge_error_info{bridge="railway_metrics",error="missing_configuration"} 1' in body


def test_render_metrics_includes_expected_market_traffic_gauge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Gauge reflects LIVE_OVERLAY_EXPECT_MARKET_TRAFFIC env var."""
    import services.live_overlay_daemon.metrics as metrics_mod

    _patch_common(
        monkeypatch,
        feed_ready=True,
        market_open=True,
        bar_count=10,
        overlay_symbols=5,
        overlay_age=60.0,
    )
    monkeypatch.setenv("LIVE_OVERLAY_EXPECT_MARKET_TRAFFIC", "1")

    body = metrics_mod.render_metrics(startup_ts=100.0)

    assert "# TYPE live_overlay_expected_market_traffic gauge" in body
    assert "live_overlay_expected_market_traffic 1" in body


def test_render_metrics_expected_market_traffic_defaults_to_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import services.live_overlay_daemon.metrics as metrics_mod

    _patch_common(
        monkeypatch,
        feed_ready=True,
        market_open=True,
        bar_count=10,
        overlay_symbols=5,
        overlay_age=60.0,
    )
    monkeypatch.delenv("LIVE_OVERLAY_EXPECT_MARKET_TRAFFIC", raising=False)

    body = metrics_mod.render_metrics(startup_ts=100.0)

    assert "live_overlay_expected_market_traffic 0" in body


def test_render_metrics_bridge_last_success_age_preserved_on_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """After a failed poll the bridge last_success_age must not reset to now."""
    import services.live_overlay_daemon.metrics as metrics_mod

    _patch_common(
        monkeypatch,
        feed_ready=True,
        market_open=True,
        bar_count=10,
        overlay_symbols=5,
        overlay_age=60.0,
    )
    past = time.time() - 600.0
    monkeypatch.setattr(
        metrics_mod.uptimerobot_bridge,
        "snapshot",
        lambda: {
            "enabled": 1,
            "ok": 0,
            "fetched_at_unix": time.time(),
            "last_success_fetched_at_unix": past,
            "error_code": "timeout",
            "counts": {"total": 0, "up": 0, "down": 0, "paused": 0, "unknown": 0},
            "avg_response_time_ms": None,
            "monitors": [],
        },
    )
    monkeypatch.setattr(
        metrics_mod.github_workflow_bridge,
        "snapshot",
        lambda: {
            "enabled": 1,
            "ok": 0,
            "fetched_at_unix": time.time(),
            "last_success_fetched_at_unix": past,
            "error_code": "http_error",
            "counts": {"seen": 0, "success": 0, "failed": 0, "in_progress": 0, "queued": 0},
            "latest_run_age_seconds": None,
            "latest_run_duration_seconds": None,
            "workflows": [],
        },
    )

    body = metrics_mod.render_metrics(startup_ts=100.0)

    ur_age_match = re.search(
        r'live_overlay_bridge_last_success_age_seconds\{bridge="uptimerobot"\} ([0-9.eE+-]+)',
        body,
    )
    assert ur_age_match is not None
    ur_age = float(ur_age_match.group(1))
    assert ur_age >= 590.0, f"uptimerobot last_success_age too small: {ur_age}"

    gh_age_match = re.search(
        r'live_overlay_bridge_last_success_age_seconds\{bridge="github_workflow"\} ([0-9.eE+-]+)',
        body,
    )
    assert gh_age_match is not None
    gh_age = float(gh_age_match.group(1))
    assert gh_age >= 590.0, f"github_workflow last_success_age too small: {gh_age}"


def test_render_metrics_never_succeeded_bridge_age_falls_back_to_uptime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A bridge failing since boot (last_success == 0) must report the time
    since daemon start — NOT a near-zero age fabricated from the failed
    attempt's ``fetched_at``. The old ``or fetched_at_unix`` fallback kept
    the >180s/>900s staleness alerts permanently blind in exactly the
    failing-from-boot case they exist for."""
    import services.live_overlay_daemon.metrics as metrics_mod

    _patch_common(
        monkeypatch,
        feed_ready=True,
        market_open=True,
        bar_count=10,
        overlay_symbols=5,
        overlay_age=60.0,
    )
    monkeypatch.setattr(
        metrics_mod.uptimerobot_bridge,
        "snapshot",
        lambda: {
            "enabled": 1,
            "ok": 0,
            "fetched_at_unix": time.time(),  # failed ATTEMPT is fresh
            "last_success_fetched_at_unix": 0.0,  # never succeeded
            "error_code": "timeout",
            "counts": {"total": 0, "up": 0, "down": 0, "paused": 0, "unknown": 0},
            "avg_response_time_ms": None,
            "monitors": [],
        },
    )
    monkeypatch.setattr(
        metrics_mod.github_workflow_bridge,
        "snapshot",
        lambda: {
            "enabled": 1,
            "ok": 0,
            "fetched_at_unix": time.time(),
            "last_success_fetched_at_unix": 0.0,
            "error_code": "http_error",
            "counts": {"seen": 0, "success": 0, "failed": 0, "in_progress": 0, "queued": 0},
            "latest_run_age_seconds": None,
            "latest_run_duration_seconds": None,
            "workflows": [],
        },
    )

    startup_epoch = time.time() - 1200.0  # daemon has been up 20 minutes
    body = metrics_mod.render_metrics(startup_ts=100.0, startup_epoch=startup_epoch)

    for bridge in ("uptimerobot", "github_workflow"):
        match = re.search(
            rf'live_overlay_bridge_last_success_age_seconds\{{bridge="{bridge}"\}} ([0-9.eE+-]+)',
            body,
        )
        assert match is not None, f"{bridge}: age series missing for never-succeeded bridge"
        age = float(match.group(1))
        assert age >= 1190.0, (
            f"{bridge}: never-succeeded age must be >= uptime (~1200s), got {age} — "
            "a small value means the failed attempt's fetched_at leaked back in"
        )


def test_render_metrics_disabled_bridge_still_omits_last_success_age(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The uptime fallback must NOT apply to a disabled bridge — its age
    series stays omitted so a deliberately disabled bridge cannot trip the
    staleness alerts."""
    import services.live_overlay_daemon.metrics as metrics_mod

    _patch_common(
        monkeypatch,
        feed_ready=True,
        market_open=True,
        bar_count=10,
        overlay_symbols=5,
        overlay_age=60.0,
    )
    monkeypatch.setattr(
        metrics_mod.uptimerobot_bridge,
        "snapshot",
        lambda: {
            "enabled": 0,
            "ok": 0,
            "fetched_at_unix": 0.0,
            "last_success_fetched_at_unix": 0.0,
            "error_code": "",
            "counts": {"total": 0, "up": 0, "down": 0, "paused": 0, "unknown": 0},
            "avg_response_time_ms": None,
            "monitors": [],
        },
    )

    body = metrics_mod.render_metrics(
        startup_ts=100.0, startup_epoch=time.time() - 1200.0
    )
    assert 'live_overlay_bridge_last_success_age_seconds{bridge="uptimerobot"}' not in body


def test_render_metrics_experiment_stale_gauge_wired_to_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """OVERLAY_EXPERIMENT_MAX_AGE_SECS is finally wired: the exporter emits a
    0/1 stale verdict against config.experiment_max_age_secs() (mirroring the
    trading-signals pattern). Unknown age must read not-stale."""
    import services.live_overlay_daemon.metrics as metrics_mod

    _patch_common(
        monkeypatch,
        feed_ready=True,
        market_open=True,
        bar_count=10,
        overlay_symbols=5,
        overlay_age=60.0,
    )
    # Dated scoring_root far in the past -> age known and >> any max age.
    rollup = {
        "schema_version": 1,
        "scoring_root": "/x/artifacts/ci/measurement_benchmark_rolling/2026-06-21",
        "files_scanned": 1,
        "per_tf": {},
        "phase_e2_verdict": {},
    }
    monkeypatch.setattr(metrics_mod.compute, "_load_experiment_snapshot", lambda: rollup)
    monkeypatch.setattr(metrics_mod.compute, "_load_experiment_history", lambda: [])

    body = metrics_mod.render_metrics(startup_ts=100.0)
    assert "live_overlay_experiment_snapshot_max_age_seconds" in body
    assert "live_overlay_experiment_snapshot_stale 1.0" in body

    # Missing snapshot -> age unknown -> must NOT read stale.
    monkeypatch.setattr(metrics_mod.compute, "_load_experiment_snapshot", lambda: {})
    body = metrics_mod.render_metrics(startup_ts=100.0)
    assert "live_overlay_experiment_snapshot_age_known 0.0" in body
    assert "live_overlay_experiment_snapshot_stale 0.0" in body


def test_escape_label_value_neutralises_format_breakers() -> None:
    import services.live_overlay_daemon.metrics as metrics_mod

    esc = metrics_mod._escape_label_value
    assert esc('svc"x') == 'svc\\"x'          # quote escaped
    assert esc("a\\b") == "a\\\\b"            # backslash escaped
    assert esc("a\nb") == "a b"               # newline neutralised
    assert esc("a\rb") == "a b"               # carriage return neutralised (F4)


def test_render_metrics_escapes_railway_service_id(monkeypatch: pytest.MonkeyPatch) -> None:
    import services.live_overlay_daemon.metrics as metrics_mod
    import services.live_overlay_daemon.railway_metrics as railway_metrics

    _patch_common(monkeypatch, feed_ready=True, market_open=True, bar_count=10, overlay_symbols=5, overlay_age=60.0)
    monkeypatch.setattr(
        railway_metrics,
        "snapshot",
        lambda: {
            "enabled": True,
            "configured": True,
            "ok": True,
            "services": [{"service": "web", "service_id": 'svc"x', "cpu_cores": 0.5}],
        },
    )

    body = metrics_mod.render_metrics(startup_ts=100.0)

    # A raw quote in service_id would break the exposition format; it must be escaped.
    assert 'service_id="svc\\"x"' in body
    assert 'service_id="svc"x"' not in body


def test_render_metrics_tolerates_non_numeric_signal_counts(monkeypatch: pytest.MonkeyPatch) -> None:
    """A corrupt SIGNALS snapshot with non-numeric/non-finite string counts must
    NOT 500 the /metrics scrape (bare int("abc") raised ValueError synchronously
    in render_metrics). Counts fall back to 0 and the scrape stays valid."""
    import services.live_overlay_daemon.metrics as metrics_mod

    _patch_common(
        monkeypatch,
        feed_ready=True,
        market_open=True,
        bar_count=10,
        overlay_symbols=5,
        overlay_age=60.0,
    )
    snapshot = {
        "updated_epoch": time.time() - 30.0,
        "watched_symbols": ["AAPL"],
        "signal_count": "abc",
        "a0_count": True,  # JSON bool must NOT count as 1
        "a1_count": None,
        "a2_count": float("nan"),
        "signals": [],
    }
    monkeypatch.setattr(metrics_mod.compute, "_load_signals_snapshot", lambda: snapshot)

    body = metrics_mod.render_metrics(startup_ts=100.0)  # must not raise
    assert "live_overlay_trading_signals_active 0.0" in body
    assert "live_overlay_trading_signals_a0 0.0" in body
    assert "live_overlay_trading_signals_a1 0.0" in body
    assert "live_overlay_trading_signals_a2 0.0" in body
    # The snapshot still loaded and the (valid) watched list still parsed.
    assert "live_overlay_trading_signals_loaded 1.0" in body
    assert "live_overlay_trading_signals_watched 1.0" in body


def test_coerce_count_coerces_all_edge_inputs() -> None:
    import services.live_overlay_daemon.metrics as metrics_mod

    c = metrics_mod._coerce_count
    # Valid counts pass through.
    assert c(3) == 3
    assert c("5") == 5
    assert c(5.9) == 5  # truncates
    # bool is an int subclass — must NOT count as 1 (float(True) == 1.0).
    assert c(True) == 0
    assert c(False) == 0
    # Non-numeric / None / non-finite / negative all floor to 0.
    assert c("abc") == 0
    assert c(None) == 0
    assert c(float("nan")) == 0
    assert c(float("inf")) == 0
    assert c(-4) == 0


def test_render_metrics_bridge_scrape_success_reflects_last_attempt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A retained keep-last-good snapshot with a failed last attempt must
    render scrape_success=0 and the truthful error label — not the frozen
    ok=1/error=none of the last success (audit: lo-bridge-scrape-failed was
    unreachable while the runbook pointed at the lying error_info)."""
    import services.live_overlay_daemon.metrics as metrics_mod

    _patch_common(
        monkeypatch,
        feed_ready=True,
        market_open=True,
        bar_count=10,
        overlay_symbols=5,
        overlay_age=60.0,
    )
    monkeypatch.setattr(
        metrics_mod.uptimerobot_bridge,
        "snapshot",
        lambda: {
            "enabled": 1,
            "configured": 1,
            "ok": 1,  # retained last-good payload
            "fetched_at_unix": 1_700_000_000.0,
            "last_success_fetched_at_unix": 1_700_000_000.0,
            "scrape_duration_seconds": 0.123,
            "counts": {"total": 4, "up": 4, "down": 0, "paused": 0, "unknown": 0},
            "avg_response_time_ms": 101.5,
            "monitors": [],
            "last_attempt_ok": 0,
            "last_attempt_error_code": "timeout",
        },
    )

    body = metrics_mod.render_metrics(100.0, 1_700_000_000.0)

    assert 'live_overlay_bridge_scrape_success{bridge="uptimerobot"} 0' in body
    assert 'live_overlay_bridge_error_info{bridge="uptimerobot",error="timeout"} 1' in body
    # last-good data stays served (retention is the point of the cache)
    assert "live_overlay_uptimerobot_monitors_up_total 4" in body


def test_render_metrics_hotspot_name_collisions_are_aggregated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Symbols that sanitize to the same metric name (BRK.A / BRK-A) must
    render as ONE series: duplicate TYPE headers + samples make Prometheus
    reject the entire exposition — a whole-scrape blackout from one request
    pair (runtime-verified in the data-path audit)."""
    import services.live_overlay_daemon.metrics as metrics_mod

    _patch_common(
        monkeypatch,
        feed_ready=True,
        market_open=True,
        bar_count=10,
        overlay_symbols=5,
        overlay_age=60.0,
    )
    monkeypatch.setattr(
        metrics_mod.request_hotspots,
        "snapshot",
        lambda top_n=5: {
            "symbol_count": 2,
            "tf_count": 2,
            "top_symbols": [("BRK.A", 3.0), ("BRK-A", 2.0)],
            "top_tfs": [("5m", 4.0), ("5M", 1.0)],
        },
    )

    body = metrics_mod.render_metrics(100.0, 1_700_000_000.0)

    assert body.count("# TYPE live_overlay_hotspot_symbol_brk_a_requests_total counter") == 1
    assert "live_overlay_hotspot_symbol_brk_a_requests_total 5.0" in body
    assert body.count("# TYPE live_overlay_hotspot_tf__5m_requests_total counter") == 1
    assert "live_overlay_hotspot_tf__5m_requests_total 5.0" in body
