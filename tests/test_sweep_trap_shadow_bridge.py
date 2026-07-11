"""Tests for the daemon-side sweep_trap_shadow_bridge (URL/local, fail-soft)."""
from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest

from services.live_overlay_daemon import sweep_trap_shadow_bridge as bridge


@pytest.fixture(autouse=True)
def _reset_cache_and_env(monkeypatch):
    # Never hit a real URL; isolate the module cache between tests.
    monkeypatch.setenv("SWEEP_TRAP_SHADOW_SNAPSHOT_URL", "")
    bridge._reset_cache_for_tests()
    yield
    bridge._reset_cache_for_tests()


def _write(tmp_path: Path, payload: dict) -> Path:
    p = tmp_path / "sweep_trap_shadow.json"
    p.write_text(json.dumps(payload), encoding="utf-8")
    return p


# --------------------------------------------------------------------------- #
# GitHub Contents-API handling (base64 envelope)
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
            return b'{"generated_at": 1.0}'

    def _fake_urlopen(request, timeout=10.0):
        captured["accept"] = request.headers.get("Accept")
        return _Resp()

    monkeypatch.setattr(bridge.urllib.request, "urlopen", _fake_urlopen)
    bridge._fetch_url("https://api.github.com/repos/o/r/contents/x.json?ref=b", "tok")
    assert captured["accept"] == "application/vnd.github.raw+json"


def test_decode_github_envelope():
    inner = {"generated_at": 5.0, "verdict": "SHADOW", "verdict_code": 1}
    env = {
        "name": "sweep_trap_shadow.json",
        "encoding": "base64",
        "content": base64.b64encode(json.dumps(inner).encode()).decode(),
    }
    assert bridge._decode_github_envelope(env) == inner
    # A raw snapshot (no envelope) is passed through as not-an-envelope.
    assert bridge._decode_github_envelope({"generated_at": 5.0}) is None


def test_load_raw_decodes_base64_envelope(monkeypatch):
    """Belt-and-suspenders: even if a proxy returns the base64 envelope, the
    bridge must decode it instead of coercing an empty (silent-green) snapshot."""
    inner = {"generated_at": 9.0, "n_samples": 42, "verdict": "PROMOTABLE", "verdict_code": 2}
    env = json.dumps(
        {"encoding": "base64", "content": base64.b64encode(json.dumps(inner).encode()).decode()}
    )
    monkeypatch.setenv(
        "SWEEP_TRAP_SHADOW_SNAPSHOT_URL", "https://api.github.com/repos/o/r/contents/x.json?ref=b"
    )
    monkeypatch.setattr(bridge, "_fetch_url", lambda *a, **k: env)
    snap = bridge.snapshot()
    assert snap["loaded"] == 1.0
    assert snap["generated_at_unix"] == 9.0
    assert snap["n_samples"] == 42.0
    assert snap["verdict_code"] == 2.0


# --------------------------------------------------------------------------- #
# Fail-soft loading
# --------------------------------------------------------------------------- #


def test_missing_snapshot_is_fail_soft(monkeypatch, tmp_path):
    monkeypatch.setenv("SWEEP_TRAP_SHADOW_SNAPSHOT_PATH", str(tmp_path / "nope.json"))
    snap = bridge.snapshot()
    assert snap["loaded"] == 0.0
    assert snap["error"] == "missing_snapshot"
    # Shape is still complete so metric rendering never KeyErrors.
    assert snap["verdict"] == ""
    assert snap["verdict_code"] == 0.0
    assert snap["generated_at_unix"] == 0.0


def test_unreadable_snapshot_is_fail_soft(monkeypatch, tmp_path):
    p = tmp_path / "sweep_trap_shadow.json"
    p.write_text("{ not json", encoding="utf-8")
    monkeypatch.setenv("SWEEP_TRAP_SHADOW_SNAPSHOT_PATH", str(p))
    snap = bridge.snapshot()
    assert snap["loaded"] == 0.0
    assert snap["error"] == "unreadable_snapshot"


def test_non_dict_snapshot_is_fail_soft(monkeypatch, tmp_path):
    p = tmp_path / "sweep_trap_shadow.json"
    p.write_text("[1, 2, 3]", encoding="utf-8")
    monkeypatch.setenv("SWEEP_TRAP_SHADOW_SNAPSHOT_PATH", str(p))
    snap = bridge.snapshot()
    assert snap["loaded"] == 0.0
    assert snap["error"] == "malformed_snapshot"


# --------------------------------------------------------------------------- #
# Normalization
# --------------------------------------------------------------------------- #


def test_valid_snapshot_is_normalized(monkeypatch, tmp_path):
    p = _write(
        tmp_path,
        {
            "generated_at": 1_783_000_000.0,
            "date": "2026-07-11",
            "n_samples": 55,
            "min_samples": 40,
            "brier_delta": 0.031,
            "lift": 0.12,
            "verdict": "PROMOTABLE",
            "verdict_code": 2,
        },
    )
    monkeypatch.setenv("SWEEP_TRAP_SHADOW_SNAPSHOT_PATH", str(p))
    snap = bridge.snapshot()
    assert snap["loaded"] == 1.0
    assert snap["generated_at_unix"] == 1_783_000_000.0
    assert snap["date"] == "2026-07-11"
    assert snap["n_samples"] == 55.0
    assert snap["min_samples"] == 40.0
    assert snap["brier_delta"] == 0.031
    assert snap["lift"] == 0.12
    assert snap["verdict"] == "PROMOTABLE"
    assert snap["verdict_code"] == 2.0


def test_verdict_code_falls_back_to_name_mapping(monkeypatch, tmp_path):
    """An older producer that omits verdict_code must still map the name."""
    p = _write(tmp_path, {"generated_at": 1.0, "verdict": "SHADOW"})
    monkeypatch.setenv("SWEEP_TRAP_SHADOW_SNAPSHOT_PATH", str(p))
    snap = bridge.snapshot()
    assert snap["verdict"] == "SHADOW"
    assert snap["verdict_code"] == 1.0


def test_no_data_seed_loads_but_reports_zero_age(monkeypatch, tmp_path):
    """The committed no-data seed (generated_at 0) loads without error but keeps
    generated_at_unix 0 so the stale gauge/age render as unknown, not fresh."""
    p = _write(
        tmp_path,
        {
            "generated_at": 0.0,
            "date": "",
            "n_samples": 0,
            "min_samples": 40,
            "brier_delta": 0.0,
            "lift": 0.0,
            "verdict": "INCONCLUSIVE",
            "verdict_code": 0,
        },
    )
    monkeypatch.setenv("SWEEP_TRAP_SHADOW_SNAPSHOT_PATH", str(p))
    snap = bridge.snapshot()
    assert snap["loaded"] == 1.0
    assert snap["generated_at_unix"] == 0.0
    assert snap["verdict"] == "INCONCLUSIVE"
    assert snap["verdict_code"] == 0.0


def test_non_numeric_fields_coerce_to_zero(monkeypatch, tmp_path):
    """Garbage numeric fields must not raise; they coerce to 0.0."""
    p = _write(
        tmp_path,
        {"generated_at": "oops", "n_samples": None, "brier_delta": "x", "verdict": "SHADOW"},
    )
    monkeypatch.setenv("SWEEP_TRAP_SHADOW_SNAPSHOT_PATH", str(p))
    snap = bridge.snapshot()
    assert snap["loaded"] == 1.0
    assert snap["generated_at_unix"] == 0.0
    assert snap["n_samples"] == 0.0
    assert snap["brier_delta"] == 0.0
    # Name mapping still resolves the code even when numerics are junk.
    assert snap["verdict_code"] == 1.0


def test_snapshot_is_ttl_cached(monkeypatch, tmp_path):
    """A second call inside the TTL returns the cached snapshot without re-reading."""
    p = _write(tmp_path, {"generated_at": 1.0, "verdict": "SHADOW", "verdict_code": 1})
    monkeypatch.setenv("SWEEP_TRAP_SHADOW_SNAPSHOT_PATH", str(p))
    first = bridge.snapshot()
    # Mutate the file; without cache the next read would see the new value.
    p.write_text(json.dumps({"generated_at": 2.0, "verdict": "PROMOTABLE", "verdict_code": 2}), encoding="utf-8")
    second = bridge.snapshot()
    assert second["generated_at_unix"] == first["generated_at_unix"] == 1.0
    # After a cache reset the fresh value is picked up.
    bridge._reset_cache_for_tests()
    assert bridge.snapshot()["generated_at_unix"] == 2.0
