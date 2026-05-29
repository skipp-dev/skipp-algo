"""Tests for ``scripts/analyze_tv_preflight_retries.py``.

Bundle B follow-up to PR #2431 — exercises every verdict path of the
post-mortem analyzer against synthetic per-attempt fixtures.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.analyze_tv_preflight_retries import analyze, main


def _write_log(
    tmp_path: Path,
    records: list[dict],
) -> Path:
    log = tmp_path / "preflight_retry_log.jsonl"
    log.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")
    return log


def _write_attempt(tmp_path: Path, n: int, payload: dict) -> str:
    name = f"tv_preflight_ci.attempt_{n}.json"
    (tmp_path / name).write_text(json.dumps(payload), encoding="utf-8")
    # Mirrors what the workflow writes into the log.
    return f"artifacts/tradingview/{name}"


# -- success ----------------------------------------------------------------


def test_verdict_success_when_first_attempt_passes(tmp_path: Path) -> None:
    preserved = _write_attempt(tmp_path, 1, {"overall_preflight_ok": True})
    log = _write_log(
        tmp_path,
        [
            {
                "attempt": 1,
                "max_attempts": 3,
                "exit_code": 0,
                "started_at": "2026-05-29T10:00:00Z",
                "ended_at": "2026-05-29T10:01:00Z",
                "duration_seconds": 60,
                "output_preserved_as": preserved,
                "will_retry": False,
            }
        ],
    )
    r = analyze(log, base_dir=tmp_path)
    assert r.verdict == "success"
    assert r.attempts == 1 and r.succeeded_attempts == 1
    assert r.failed_attempts == 0
    assert "no action" in r.recommendation


# -- flake_recovered --------------------------------------------------------


def test_verdict_flake_recovered_when_last_attempt_passes(tmp_path: Path) -> None:
    p1 = _write_attempt(tmp_path, 1, {"ui_green": False, "binding_green": False})
    p2 = _write_attempt(tmp_path, 2, {"ui_green": True, "binding_green": True, "overall_preflight_ok": True})
    log = _write_log(
        tmp_path,
        [
            {"attempt": 1, "max_attempts": 3, "exit_code": 7, "duration_seconds": 60,
             "output_preserved_as": p1, "will_retry": True,
             "started_at": "2026-05-29T10:00:00Z", "ended_at": "2026-05-29T10:01:00Z"},
            {"attempt": 2, "max_attempts": 3, "exit_code": 0, "duration_seconds": 55,
             "output_preserved_as": p2, "will_retry": False,
             "started_at": "2026-05-29T10:02:00Z", "ended_at": "2026-05-29T10:02:55Z"},
        ],
    )
    r = analyze(log, base_dir=tmp_path)
    assert r.verdict == "flake_recovered"
    assert r.failed_attempts == 1 and r.succeeded_attempts == 1
    assert "earned its keep" in r.recommendation


# -- deterministic_failure (the #2425 signature) ----------------------------


def test_verdict_deterministic_failure_when_all_attempts_identical(tmp_path: Path) -> None:
    payload = {
        "ui_green": False,
        "binding_green": False,
        "overall_preflight_ok": False,
        "targets": {"pine_buttons": 1, "pine_texts": 5, "toolbar_host": False},
        # Noise field that MUST be scrubbed before comparing.
        "generatedAt": "varies-between-attempts",
    }
    p1 = _write_attempt(tmp_path, 1, {**payload, "generatedAt": "T1"})
    p2 = _write_attempt(tmp_path, 2, {**payload, "generatedAt": "T2"})
    p3 = _write_attempt(tmp_path, 3, {**payload, "generatedAt": "T3"})
    log = _write_log(
        tmp_path,
        [
            {"attempt": i + 1, "max_attempts": 3, "exit_code": 7,
             "duration_seconds": 60, "output_preserved_as": p,
             "will_retry": i < 2,
             "started_at": "x", "ended_at": "y"}
            for i, p in enumerate([p1, p2, p3])
        ],
    )
    r = analyze(log, base_dir=tmp_path)
    assert r.verdict == "deterministic_failure", r
    assert r.distinct_failure_fingerprints == 1
    assert "DOM-drift" in r.recommendation
    # The per-attempt fingerprint hashes must all match.
    hashes = {a["fingerprint_sha"] for a in r.per_attempt}
    assert len(hashes) == 1


# -- flake_with_progression -------------------------------------------------


def test_verdict_flake_with_progression_when_failures_differ(tmp_path: Path) -> None:
    # Two attempts, both failed, but different shapes (e.g. one ui-fail,
    # one binding-fail). Wrapper hasn't recovered AND it isn't the clean
    # deterministic signature.
    p1 = _write_attempt(tmp_path, 1, {"ui_green": False, "binding_green": True})
    p2 = _write_attempt(tmp_path, 2, {"ui_green": True, "binding_green": False})
    log = _write_log(
        tmp_path,
        [
            {"attempt": 1, "max_attempts": 2, "exit_code": 7, "duration_seconds": 60,
             "output_preserved_as": p1, "will_retry": True,
             "started_at": "x", "ended_at": "y"},
            {"attempt": 2, "max_attempts": 2, "exit_code": 7, "duration_seconds": 60,
             "output_preserved_as": p2, "will_retry": False,
             "started_at": "x", "ended_at": "y"},
        ],
    )
    r = analyze(log, base_dir=tmp_path)
    assert r.verdict == "flake_with_progression"
    assert r.distinct_failure_fingerprints == 2


# -- inconclusive paths -----------------------------------------------------


def test_verdict_inconclusive_when_log_empty(tmp_path: Path) -> None:
    log = tmp_path / "preflight_retry_log.jsonl"
    log.write_text("", encoding="utf-8")
    r = analyze(log, base_dir=tmp_path)
    assert r.verdict == "inconclusive"
    assert "empty" in r.summary


def test_verdict_inconclusive_when_no_payloads_preserved(tmp_path: Path) -> None:
    log = _write_log(
        tmp_path,
        [
            {"attempt": 1, "max_attempts": 1, "exit_code": 7, "duration_seconds": 60,
             "output_preserved_as": None, "will_retry": False,
             "started_at": "x", "ended_at": "y"},
        ],
    )
    r = analyze(log, base_dir=tmp_path)
    assert r.verdict == "inconclusive"
    assert "NO per-attempt" in r.summary
    assert r.per_attempt[0]["payload_present"] is False
    assert r.per_attempt[0]["fingerprint_sha"] is None


def test_corrupt_log_raises(tmp_path: Path) -> None:
    log = tmp_path / "preflight_retry_log.jsonl"
    log.write_text("{not json}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="corrupt retry log"):
        analyze(log, base_dir=tmp_path)


def test_missing_log_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        analyze(tmp_path / "does_not_exist.jsonl", base_dir=tmp_path)


# -- CLI --------------------------------------------------------------------


def test_cli_writes_output_file_and_returns_zero(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    p1 = _write_attempt(tmp_path, 1, {"overall_preflight_ok": True})
    log = _write_log(
        tmp_path,
        [{"attempt": 1, "max_attempts": 1, "exit_code": 0, "duration_seconds": 30,
          "output_preserved_as": p1, "will_retry": False,
          "started_at": "x", "ended_at": "y"}],
    )
    out = tmp_path / "report.json"
    rc = main([str(log), "--base-dir", str(tmp_path), "--output", str(out)])
    assert rc == 0
    assert out.exists()
    parsed = json.loads(out.read_text(encoding="utf-8"))
    assert parsed["verdict"] == "success"


def test_cli_exit_on_deterministic_returns_three(tmp_path: Path) -> None:
    p1 = _write_attempt(tmp_path, 1, {"ui_green": False})
    p2 = _write_attempt(tmp_path, 2, {"ui_green": False})
    log = _write_log(
        tmp_path,
        [
            {"attempt": 1, "max_attempts": 2, "exit_code": 7, "duration_seconds": 60,
             "output_preserved_as": p1, "will_retry": True, "started_at": "x", "ended_at": "y"},
            {"attempt": 2, "max_attempts": 2, "exit_code": 7, "duration_seconds": 60,
             "output_preserved_as": p2, "will_retry": False, "started_at": "x", "ended_at": "y"},
        ],
    )
    rc = main([str(log), "--base-dir", str(tmp_path), "--exit-on-deterministic"])
    assert rc == 3


def test_cli_exit_on_deterministic_returns_zero_when_not_deterministic(tmp_path: Path) -> None:
    p1 = _write_attempt(tmp_path, 1, {"overall_preflight_ok": True})
    log = _write_log(
        tmp_path,
        [{"attempt": 1, "max_attempts": 1, "exit_code": 0, "duration_seconds": 30,
          "output_preserved_as": p1, "will_retry": False, "started_at": "x", "ended_at": "y"}],
    )
    rc = main([str(log), "--base-dir", str(tmp_path), "--exit-on-deterministic"])
    assert rc == 0


# -- scrubbing --------------------------------------------------------------


def test_noise_fields_do_not_break_fingerprint_equality(tmp_path: Path) -> None:
    """Two failing attempts that differ ONLY in noise fields must still
    classify as deterministic_failure."""
    base = {"ui_green": False, "targets": {"a": 1}}
    p1 = _write_attempt(tmp_path, 1, {**base, "generatedAt": "ts1", "duration_ms": 1000, "screenshot": "1.png"})
    p2 = _write_attempt(tmp_path, 2, {**base, "generatedAt": "ts2", "duration_ms": 2000, "screenshot": "2.png"})
    log = _write_log(
        tmp_path,
        [
            {"attempt": 1, "max_attempts": 2, "exit_code": 7, "duration_seconds": 60,
             "output_preserved_as": p1, "will_retry": True, "started_at": "x", "ended_at": "y"},
            {"attempt": 2, "max_attempts": 2, "exit_code": 7, "duration_seconds": 60,
             "output_preserved_as": p2, "will_retry": False, "started_at": "x", "ended_at": "y"},
        ],
    )
    r = analyze(log, base_dir=tmp_path)
    assert r.verdict == "deterministic_failure"
    assert r.distinct_failure_fingerprints == 1
