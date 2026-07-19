"""Invariant / robustness coverage for ``github_workflow_bridge``.

Complements the example-based ``test_github_workflow_bridge.py`` with the
coverage holes an audit (2026-07-12) surfaced on current main:

* ``_phase_code`` has no direct unit test although it feeds the
  ``live_overlay_github_workflow_phase_code`` gauge — assert its output stays a
  bounded int in ``[0, 11]`` for arbitrary inputs (a regression that returned an
  out-of-range code would silently corrupt the gauge).
* ``_iso_age_seconds`` / ``_duration_seconds`` must never raise and never emit a
  non-finite / negative value for arbitrary / malformed timestamps.
* ``config.github_workflow_repo`` / ``github_workflow_ids`` parsing (malformed /
  dedup / empty) was untested.
* ``snapshot()``'s ``_cache_lock`` had zero concurrency coverage.

These assertions encode the *current* semantics deliberately (e.g. a completed
``cancelled`` run is a distinct phase code, NOT a failure — matching
``_FAILURE_CONCLUSIONS``), so they do not re-introduce pre-fix behaviour.
"""
from __future__ import annotations

import threading

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

import services.live_overlay_daemon.config as config
import services.live_overlay_daemon.github_workflow_bridge as bridge


@pytest.fixture(autouse=True)
def _reset_bridge_cache():
    """Isolate the module-level snapshot cache between tests."""
    bridge._cached_snapshot = None
    bridge._cached_at_monotonic = 0.0
    yield
    bridge._cached_snapshot = None
    bridge._cached_at_monotonic = 0.0


# ---------------------------------------------------------------------------
# _phase_code — bounded int, feeds a gauge (untested on main)
# ---------------------------------------------------------------------------

_STATUSES = ["queued", "in_progress", "completed", "waiting", "", "QUEUED", "unknown"]
_CONCLUSIONS = [
    None, "success", "failure", "cancelled", "skipped", "neutral", "timed_out",
    "action_required", "startup_failure", "stale", "SUCCESS", "weird", "",
]


@given(status=st.sampled_from(_STATUSES), conclusion=st.sampled_from(_CONCLUSIONS))
@settings(max_examples=200, deadline=None)
def test_phase_code_is_a_bounded_int(status: str, conclusion: str | None) -> None:
    code = bridge._phase_code(status, conclusion)
    assert isinstance(code, int)
    assert 0 <= code <= 11


@given(status=st.text(), conclusion=st.one_of(st.none(), st.text()))
@settings(max_examples=200, deadline=None)
def test_phase_code_never_crashes_on_arbitrary_text(
    status: str, conclusion: str | None
) -> None:
    code = bridge._phase_code(status, conclusion)
    assert isinstance(code, int) and 0 <= code <= 11


def test_phase_code_known_mapping_and_casing():
    assert bridge._phase_code("queued", None) == 1
    assert bridge._phase_code("in_progress", None) == 2
    assert bridge._phase_code("waiting", None) == 0  # any non-terminal status
    assert bridge._phase_code("completed", "success") == 3
    # A completed *cancelled* run is its own phase (5), NOT a failure (4):
    # matches _FAILURE_CONCLUSIONS, which excludes cancelled/skipped/neutral.
    assert bridge._phase_code("completed", "cancelled") == 5
    assert bridge._phase_code("completed", "stale") == 11
    assert bridge._phase_code("completed", "SUCCESS") == 3  # case-insensitive
    assert bridge._phase_code("completed", "made-up") == 0  # unknown conclusion
    assert bridge._phase_code("completed", None) == 0


# ---------------------------------------------------------------------------
# _iso_age_seconds / _duration_seconds — None or finite, never negative, never raise
# ---------------------------------------------------------------------------

@given(ts=st.one_of(st.none(), st.text(), st.sampled_from([
    "", "not-a-date", "2026-07-12T00:00:00Z", "2026-07-12T00:00:00+00:00",
    "2026-07-12 00:00:00", "0001-01-01T00:00:00Z", "9999-12-31T23:59:59Z",
])))
@settings(max_examples=200, deadline=None)
def test_iso_age_seconds_is_none_or_finite_nonnegative(ts: str | None) -> None:
    age = bridge._iso_age_seconds(ts)
    assert age is None or (isinstance(age, float) and age == age and age >= 0.0)


@given(
    start=st.one_of(st.none(), st.text()),
    end=st.one_of(st.none(), st.text()),
)
@settings(max_examples=200, deadline=None)
def test_duration_seconds_is_none_or_finite_nonnegative(
    start: str | None, end: str | None
) -> None:
    duration = bridge._duration_seconds(start, end)
    assert duration is None or (
        isinstance(duration, float) and duration == duration and duration >= 0.0
    )


def test_duration_seconds_clamps_reversed_interval_to_zero():
    # end before start -> max(0.0, ...) floors at 0, never negative.
    d = bridge._duration_seconds("2026-07-12T02:00:00Z", "2026-07-12T01:00:00Z")
    assert d == 0.0


# ---------------------------------------------------------------------------
# config parsing — github_workflow_repo / github_workflow_ids (untested on main)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "raw",
    ["", "no-slash", "/only-repo", "owner/", "a/b/c", "  /  ", "bad owner/repo",
     "owner/bad repo", "owner//repo"],
)
def test_github_workflow_repo_malformed_falls_back(monkeypatch, raw: str) -> None:
    monkeypatch.setenv("GITHUB_WORKFLOW_MONITOR_REPO", raw)
    owner, repo = config.github_workflow_repo()
    assert (owner, repo) == ("skipp-dev", "skipp-algo")


def test_github_workflow_repo_valid_is_parsed_and_trimmed(monkeypatch) -> None:
    monkeypatch.setenv("GITHUB_WORKFLOW_MONITOR_REPO", "  skipp-dev / skipp-algo ")
    assert config.github_workflow_repo() == ("skipp-dev", "skipp-algo")


def test_snapshot_urls_default_to_monitored_repo_rolling_branches(monkeypatch) -> None:
    monkeypatch.setenv("GITHUB_WORKFLOW_MONITOR_REPO", "skipp-dev/skipp-algo")
    monkeypatch.delenv("EVIDENCE_FRESHNESS_SNAPSHOT_URL", raising=False)
    monkeypatch.delenv("TRADINGVIEW_BINDINGS_SNAPSHOT_URL", raising=False)

    assert config.evidence_freshness_snapshot_url() == (
        "https://api.github.com/repos/skipp-dev/skipp-algo/contents/"
        "artifacts/monitoring/latest/evidence_freshness.json"
        "?ref=bot/live-evidence-freshness"
    )
    assert config.tradingview_bindings_snapshot_url().endswith(
        "artifacts/monitoring/latest/tradingview_consumer_bindings.json"
        "?ref=bot/live-tradingview-bindings"
    )


def test_snapshot_token_reuses_monitor_token_only_for_own_contents_api(monkeypatch) -> None:
    monkeypatch.setenv("GITHUB_WORKFLOW_MONITOR_REPO", "skipp-dev/skipp-algo")
    monkeypatch.setenv("GITHUB_WORKFLOW_MONITOR_TOKEN", "monitor-token")
    monkeypatch.delenv("EVIDENCE_FRESHNESS_SNAPSHOT_URL_TOKEN", raising=False)

    monkeypatch.setenv(
        "EVIDENCE_FRESHNESS_SNAPSHOT_URL",
        "https://api.github.com/repos/skipp-dev/skipp-algo/contents/x.json?ref=bot/live-x",
    )
    assert config.evidence_freshness_snapshot_url_token() == "monitor-token"

    monkeypatch.setenv("EVIDENCE_FRESHNESS_SNAPSHOT_URL", "https://example.test/x.json")
    assert config.evidence_freshness_snapshot_url_token() == ""


def test_snapshot_specific_token_wins_for_custom_url(monkeypatch) -> None:
    monkeypatch.setenv("EVIDENCE_FRESHNESS_SNAPSHOT_URL", "https://example.test/x.json")
    monkeypatch.setenv("EVIDENCE_FRESHNESS_SNAPSHOT_URL_TOKEN", "source-token")
    monkeypatch.setenv("GITHUB_WORKFLOW_MONITOR_TOKEN", "monitor-token")
    assert config.evidence_freshness_snapshot_url_token() == "source-token"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("", []),
        ("   ", []),
        ("ci.yml", ["ci.yml"]),
        ("a, b , c", ["a", "b", "c"]),          # split + strip
        ("a,,b, ,c", ["a", "b", "c"]),          # empties dropped
        ("a,b,a,b,c", ["a", "b", "c"]),         # dedup, order-preserving
    ],
)
def test_github_workflow_ids_parsing(monkeypatch, raw: str, expected: list[str]) -> None:
    monkeypatch.setenv("GITHUB_WORKFLOW_MONITOR_IDS", raw)
    assert config.github_workflow_ids() == expected


# ---------------------------------------------------------------------------
# snapshot() — _cache_lock concurrency (zero coverage on main)
# ---------------------------------------------------------------------------

def test_snapshot_is_thread_safe_and_lock_serializes_fetch(monkeypatch) -> None:
    fetch_calls = {"n": 0}

    def _fake_fetch(_token: str) -> dict:
        fetch_calls["n"] += 1
        return {"enabled": 1, "configured": 1, "ok": 1, "fetched_at_unix": 1.0,
                "counts": {"seen": 1, "success": 1, "failed": 0,
                           "in_progress": 0, "queued": 0}, "workflows": []}

    monkeypatch.setattr(config, "github_workflow_token", lambda: "tok")
    monkeypatch.setattr(config, "github_workflow_poll_ttl_secs", lambda: 3600)
    monkeypatch.setattr(bridge, "_fetch_snapshot", _fake_fetch)

    results: list[dict] = []
    errors: list[BaseException] = []
    lock = threading.Lock()

    def _worker() -> None:
        try:
            snap = bridge.snapshot()
            with lock:
                results.append(snap)
        except BaseException as exc:  # record any thread failure, incl. AssertionError
            with lock:
                errors.append(exc)

    threads = [threading.Thread(target=_worker) for _ in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"snapshot() raised under concurrency: {errors!r}"
    assert len(results) == 20
    # The lock serialises: exactly one thread fetches, the rest hit the fresh
    # cache — a single fetch across 20 concurrent callers.
    assert fetch_calls["n"] == 1
    assert all(r.get("ok") == 1 and r.get("counts", {}).get("seen") == 1 for r in results)


def test_snapshot_without_token_is_disabled_and_never_fetches(monkeypatch) -> None:
    monkeypatch.setattr(config, "github_workflow_token", lambda: "")

    def _boom(_token: str) -> dict:  # pragma: no cover - must never be called
        raise AssertionError("_fetch_snapshot must not run without a token")

    monkeypatch.setattr(bridge, "_fetch_snapshot", _boom)
    snap = bridge.snapshot()
    assert snap["enabled"] == 0 and snap["configured"] == 0 and snap["error"] is None
