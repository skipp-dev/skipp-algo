"""Tests for the daemon-side evidence_freshness_bridge (URL/local, fail-soft)."""
from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest

from services.live_overlay_daemon import evidence_freshness_bridge as bridge

# --------------------------------------------------------------------------- #
# GitHub Contents-API handling (post-review finding 1: base64 envelope)
# --------------------------------------------------------------------------- #


def test_is_github_contents_api_url():
    assert bridge._is_github_contents_api_url(
        "https://api.github.com/repos/o/r/contents/a/b.json?ref=bot/x"
    )
    assert not bridge._is_github_contents_api_url(
        "https://raw.githubusercontent.com/o/r/bot/x/a/b.json"
    )
    assert not bridge._is_github_contents_api_url("https://example.com/x.json")


def test_contents_api_url_requests_raw_accept(monkeypatch):
    """The Contents-API URL must send Accept: vnd.github.raw+json so GitHub
    returns the file, not the base64 envelope (the silent-green bug)."""
    captured = {}

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b'{"generated_at_unix": 1.0}'

    def _fake_urlopen(request, timeout=10.0):
        captured["accept"] = request.headers.get("Accept")
        return _Resp()

    monkeypatch.setattr(bridge.urllib.request, "urlopen", _fake_urlopen)
    bridge._fetch_url("https://api.github.com/repos/o/r/contents/x.json?ref=b", "tok")
    assert captured["accept"] == "application/vnd.github.raw+json"


def test_decode_github_envelope():
    inner = {"generated_at_unix": 5.0, "samples": {"target": 40}}
    env = {
        "name": "evidence_freshness.json",
        "encoding": "base64",
        "content": base64.b64encode(json.dumps(inner).encode()).decode(),
    }
    assert bridge._decode_github_envelope(env) == inner
    # A raw snapshot (no envelope) is passed through as not-an-envelope.
    assert bridge._decode_github_envelope({"generated_at_unix": 5.0}) is None


def test_load_raw_decodes_base64_envelope(monkeypatch, tmp_path):
    """Belt-and-suspenders: even if a proxy returns the base64 envelope, the
    bridge must decode it instead of coercing an empty (silent-green) snapshot."""
    inner = {
        "generated_at_unix": 9.0,
        "samples": {"target": 40, "per_family": {"BOS": {"usable": 7, "classification": "operational"}}},
    }
    env = json.dumps({"encoding": "base64", "content": base64.b64encode(json.dumps(inner).encode()).decode()})
    monkeypatch.setenv("EVIDENCE_FRESHNESS_SNAPSHOT_URL", "https://api.github.com/repos/o/r/contents/x.json?ref=b")
    monkeypatch.setattr(bridge, "_fetch_url", lambda *a, **k: env)
    snap = bridge.snapshot()
    assert snap["loaded"] == 1.0
    assert snap["generated_at_unix"] == 9.0
    assert snap["samples"]["per_family"]["BOS"]["usable"] == 7.0


@pytest.fixture(autouse=True)
def _reset_cache_and_env(monkeypatch):
    # Never hit a real URL; isolate the module cache between tests.
    monkeypatch.setenv("EVIDENCE_FRESHNESS_SNAPSHOT_URL", "")
    bridge._cached = None
    bridge._cached_at_monotonic = 0.0
    yield
    bridge._cached = None
    bridge._cached_at_monotonic = 0.0


def _write(tmp_path: Path, payload: dict) -> Path:
    p = tmp_path / "evidence.json"
    p.write_text(json.dumps(payload), encoding="utf-8")
    return p


def test_missing_snapshot_is_fail_soft(monkeypatch, tmp_path):
    monkeypatch.setenv("EVIDENCE_FRESHNESS_SNAPSHOT_PATH", str(tmp_path / "nope.json"))
    snap = bridge.snapshot()
    assert snap["loaded"] == 0.0
    assert snap["error"] == "missing_snapshot"
    # Shape is still complete so metric rendering never KeyErrors.
    assert snap["ledger"]["newest_date"] == ""
    assert snap["fills"]["closed_cumulative"] == 0


def test_unreadable_snapshot_is_fail_soft(monkeypatch, tmp_path):
    p = tmp_path / "evidence.json"
    p.write_text("{ not json", encoding="utf-8")
    monkeypatch.setenv("EVIDENCE_FRESHNESS_SNAPSHOT_PATH", str(p))
    snap = bridge.snapshot()
    assert snap["loaded"] == 0.0
    assert snap["error"] == "unreadable_snapshot"


def test_valid_snapshot_is_normalized(monkeypatch, tmp_path):
    p = _write(
        tmp_path,
        {
            "generated_at_unix": 1_783_000_000.0,
            "ledger": {"newest_date": "2026-06-11", "plane": "15m", "rows": 4, "candidate_pass": 2},
            "audit_branch": {"last_commit_date": "2026-07-06"},
            "fills": {"filled_cumulative": 3, "closed_cumulative": 1,
                      "submit_failed_cumulative": 2, "target": 20,
                      "newest_incubation_date": "2026-07-06"},
            "wsh": {"newest_date": "2026-06-23", "status": "degraded:no-events"},
            "submitter": {"submit_code_behind_commits": 5, "known": 1},
            "portfolio_shadow": {
                "status": "observing",
                "min_shadow_sessions_for_review": 20,
                "risk_relevant_sessions_observed": 4,
                "risk_relevant_decision_count": 6,
                "verdict_counts": {"allow": 3, "resize": 2, "reject": 1},
                "latest_snapshot_age_seconds": 7.5,
                "latest_snapshot_max_age_seconds": 120.0,
                "newest_risk_relevant_session": "2026-08-08",
                "submission_attempt_count": 6,
                "submission_attempts_without_prior_evaluation": 0,
                "incomplete_decisions": 0,
                "reconciliation_sessions": 4,
                "risk_relevant_sessions_missing_reconciliation": 0,
                "reconciliation_failures": 0,
                "latest_reconciliation_at": "2026-08-08T21:05:00+00:00",
                "latest_reconciliation_max_abs_quantity_delta": 0.25,
                "latest_reconciliation_reconciled": True,
                "evidence_complete": False,
            },
        },
    )
    monkeypatch.setenv("EVIDENCE_FRESHNESS_SNAPSHOT_PATH", str(p))
    snap = bridge.snapshot()
    assert snap["loaded"] == 1.0
    assert snap["ledger"]["plane"] == "15m"
    assert snap["ledger"]["candidate_pass"] == 2.0
    assert snap["audit_branch"]["last_commit_date"] == "2026-07-06"
    assert snap["fills"]["closed_cumulative"] == 1.0
    assert snap["fills"]["submit_failed_cumulative"] == 2.0
    assert snap["submitter"] == {"submit_code_behind_commits": 5.0, "known": 1.0}
    assert snap["portfolio_shadow"]["known"] == 1.0
    assert snap["portfolio_shadow"]["risk_relevant_sessions_observed"] == 4.0
    assert snap["portfolio_shadow"]["newest_risk_relevant_session"] == "2026-08-08"
    assert snap["portfolio_shadow"]["verdict_counts"] == {
        "allow": 3.0,
        "resize": 2.0,
        "reject": 1.0,
    }
    assert snap["portfolio_shadow"]["latest_snapshot_age_known"] == 1.0
    assert snap["portfolio_shadow"]["latest_snapshot_age_seconds"] == 7.5
    assert snap["portfolio_shadow"]["latest_snapshot_max_age_known"] == 1.0
    assert snap["portfolio_shadow"]["latest_reconciliation_known"] == 1.0
    assert (
        snap["portfolio_shadow"]["latest_reconciliation_max_abs_quantity_delta"]
        == 0.25
    )
    assert snap["portfolio_shadow"]["latest_reconciliation_reconciled"] == 1.0


def test_submitter_section_defaults_when_absent(monkeypatch, tmp_path):
    """A snapshot with no submitter section (old producer) normalizes to
    known=0 so the stale-checkout alert stays silent, not falsely green."""
    p = _write(tmp_path, {"generated_at_unix": 1_783_000_000.0})
    monkeypatch.setenv("EVIDENCE_FRESHNESS_SNAPSHOT_PATH", str(p))
    snap = bridge.snapshot()
    assert snap["submitter"] == {"submit_code_behind_commits": 0.0, "known": 0.0}
    assert snap["fills"]["submit_failed_cumulative"] == 0.0
    assert snap["portfolio_shadow"]["known"] == 0.0


def test_samples_section_is_normalized(monkeypatch, tmp_path):
    p = _write(
        tmp_path,
        {
            "generated_at_unix": 1_783_000_000.0,
            "samples": {
                "target": 40,
                "per_family": {
                    "BOS": {"usable": 16, "classification": "operational"},
                    "SWEEP": {"usable": 9, "classification": "proof_of_concept_15m"},
                },
            },
        },
    )
    monkeypatch.setenv("EVIDENCE_FRESHNESS_SNAPSHOT_PATH", str(p))
    snap = bridge.snapshot()
    assert snap["samples"]["target"] == 40.0
    assert snap["samples"]["per_family"]["BOS"] == {"usable": 16.0, "classification": "operational"}
    assert snap["samples"]["per_family"]["SWEEP"]["classification"] == "proof_of_concept_15m"


def test_missing_samples_section_defaults_empty(monkeypatch, tmp_path):
    p = _write(tmp_path, {"generated_at_unix": 1_783_000_000.0})
    monkeypatch.setenv("EVIDENCE_FRESHNESS_SNAPSHOT_PATH", str(p))
    snap = bridge.snapshot()
    assert snap["samples"] == {"target": 0.0, "per_family": {}}


def test_partial_snapshot_tolerated(monkeypatch, tmp_path):
    """A snapshot missing whole sections must not raise — missing sections
    normalize to their empty defaults."""
    p = _write(tmp_path, {"generated_at_unix": 1_783_000_000.0, "ledger": {"newest_date": "2026-07-06"}})
    monkeypatch.setenv("EVIDENCE_FRESHNESS_SNAPSHOT_PATH", str(p))
    snap = bridge.snapshot()
    assert snap["loaded"] == 1.0
    assert snap["ledger"]["newest_date"] == "2026-07-06"
    assert snap["audit_branch"]["last_commit_date"] == ""
    assert snap["fills"]["target"] == 0.0


def test_non_dict_snapshot_is_fail_soft(monkeypatch, tmp_path):
    p = tmp_path / "evidence.json"
    p.write_text("[1, 2, 3]", encoding="utf-8")
    monkeypatch.setenv("EVIDENCE_FRESHNESS_SNAPSHOT_PATH", str(p))
    snap = bridge.snapshot()
    assert snap["loaded"] == 0.0
    assert snap["error"] == "malformed_snapshot"




def test_failed_load_preserves_last_good_snapshot(monkeypatch, tmp_path):
    """A transient load failure must not evict a previously-good snapshot.

    Without this guard a missing/unreadable snapshot immediately flips the
    dashboard to loaded=0, masking a broken producer with a false "no data"
    reading even though the last-known good evidence is still useful.
    """
    good = _write(tmp_path, {"generated_at_unix": 1_783_000_000.0, "ledger": {"newest_date": "2026-07-06"}})
    monkeypatch.setenv("EVIDENCE_FRESHNESS_SNAPSHOT_PATH", str(good))
    first = bridge.snapshot()
    assert first["loaded"] == 1.0
    assert first["generated_at_unix"] == 1_783_000_000.0

    # Simulate the snapshot becoming unreadable and the TTL expiring.
    bad = tmp_path / "evidence.json"
    bad.write_text("{ not json", encoding="utf-8")
    monkeypatch.setenv("EVIDENCE_FRESHNESS_SNAPSHOT_PATH", str(bad))
    bridge._cached_at_monotonic = 0.0

    second = bridge.snapshot()
    assert second["loaded"] == 1.0
    assert second["generated_at_unix"] == 1_783_000_000.0
    assert second["ledger"]["newest_date"] == "2026-07-06"


def test_failed_load_without_prior_cache_returns_error_payload(monkeypatch, tmp_path):
    """When no good snapshot was ever loaded, a failure must still be fail-soft."""
    bad = tmp_path / "evidence.json"
    bad.write_text("{ not json", encoding="utf-8")
    monkeypatch.setenv("EVIDENCE_FRESHNESS_SNAPSHOT_PATH", str(bad))
    snap = bridge.snapshot()
    assert snap["loaded"] == 0.0
    assert snap["error"] == "unreadable_snapshot"
# --------------------------------------------------------------------------- #
# age_seconds_from_date
# --------------------------------------------------------------------------- #


def test_age_seconds_from_date_monotonic():
    now = 1_783_000_000.0
    # 2026-06-11 midnight UTC is well before `now`; age must be positive.
    age = bridge.age_seconds_from_date("2026-06-11", now=now)
    assert age is not None and age > 0


def test_age_seconds_from_date_unparseable_is_none():
    assert bridge.age_seconds_from_date("", now=1_783_000_000.0) is None
    assert bridge.age_seconds_from_date("not-a-date", now=1_783_000_000.0) is None


def test_age_seconds_is_unknown_for_future_date():
    assert bridge.age_seconds_from_date("2099-01-01", now=1_783_000_000.0) is None
