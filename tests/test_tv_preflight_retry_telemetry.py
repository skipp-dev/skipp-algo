"""Structural pin for the TradingView preflight retry wrapper telemetry.

Bundle B (audit follow-up from PR #2415 / #2418, issue #2422 item #3).

The retry wrapper inside ``.github/workflows/smc-library-refresh.yml``
gained per-attempt structured telemetry so that a post-mortem can
distinguish a transient flake ("attempt 1 failed, attempt 2 passed")
from a deterministic regression ("all 3 attempts failed identically =
real DOM drift") without parsing log strings.

This file pins the load-bearing pieces of that contract.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

WORKFLOW = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "smc-library-refresh.yml"


@pytest.fixture(scope="module")
def workflow_text() -> str:
    assert WORKFLOW.exists(), f"missing workflow: {WORKFLOW}"
    return WORKFLOW.read_text(encoding="utf-8")


def _preflight_block(text: str) -> str:
    """Slice out the `Run TradingView readonly preflight` step body."""
    start = text.index("Run TradingView readonly preflight")
    # Next top-level step starts with `      - name: ` after this one.
    rest = text[start:]
    m = re.search(r"\n      - name: ", rest[10:])
    assert m, "could not delimit preflight step"
    return rest[: 10 + m.start()]


def test_retry_log_path_is_pinned(workflow_text: str) -> None:
    block = _preflight_block(workflow_text)
    assert 'retry_log="artifacts/tradingview/preflight_retry_log.jsonl"' in block, (
        "retry log path must stay at the documented location so downstream "
        "tooling and the workflow artifact upload can find it"
    )


def test_retry_log_is_truncated_per_run(workflow_text: str) -> None:
    block = _preflight_block(workflow_text)
    assert ': > "$retry_log"' in block, (
        "retry log must be truncated at the start of each run so a re-run "
        "does not append to stale state"
    )


def test_each_attempt_preserves_preflight_json(workflow_text: str) -> None:
    block = _preflight_block(workflow_text)
    assert 'preserved="artifacts/tradingview/tv_preflight_ci.attempt_${attempt}.json"' in block
    assert "cp artifacts/tradingview/tv_preflight_ci.json" in block, (
        "each attempt's preflight JSON must be copied before the next "
        "attempt overwrites it"
    )


def test_jsonl_record_schema_pinned(workflow_text: str) -> None:
    block = _preflight_block(workflow_text)
    # The JSONL record must carry every field a downstream post-mortem
    # needs. The Python one-liner is intentionally inline (no separate
    # script) but its schema is load-bearing.
    for key in (
        "'attempt'",
        "'max_attempts'",
        "'exit_code'",
        "'started_at'",
        "'ended_at'",
        "'duration_seconds'",
        "'output_preserved_as'",
        "'will_retry'",
    ):
        assert key in block, f"retry JSONL record missing required field: {key}"


def test_jsonl_uses_python_for_safe_json_emission(workflow_text: str) -> None:
    block = _preflight_block(workflow_text)
    # Shell `echo` of JSON is fragile (quote escaping). The pin forces
    # the use of python -c so values are JSON-safe.
    assert "python -c " in block and "json.dump" in block, (
        "JSONL line must be emitted via python json.dump, not raw shell echo"
    )
    # And the line must be appended (NOT truncating) to the per-run log.
    assert '>> "$retry_log"' in block


def test_will_retry_flag_logic(workflow_text: str) -> None:
    block = _preflight_block(workflow_text)
    # ``will_retry`` is true only when the attempt failed AND another
    # attempt remains; covers the "last attempt failed" edge case that
    # post-mortem analysis cares about.
    assert 'will_retry="false"' in block
    assert (
        'if [ "$status" -ne 0 ] && [ "$attempt" -lt "$max_attempts" ]; then'
        in block
    )


def test_failure_path_appends_retry_log_to_step_summary(workflow_text: str) -> None:
    block = _preflight_block(workflow_text)
    # On all-attempts-failed, the human reader gets the JSONL inline in
    # the GH step summary so they can immediately see "flake vs drift".
    assert "### TradingView preflight retry log" in block
    assert '>> "$GITHUB_STEP_SUMMARY"' in block


def test_step_still_exits_with_real_status(workflow_text: str) -> None:
    block = _preflight_block(workflow_text)
    # Bundle A lesson: telemetry must not swallow the real exit code.
    assert 'exit "$status"' in block, (
        "preflight step must propagate the real status; telemetry must "
        "never mask the failure"
    )


def test_max_attempts_env_default_unchanged(workflow_text: str) -> None:
    # The retry count itself is part of the contract — bumping it
    # silently would change post-mortem semantics.
    assert 'TV_PREFLIGHT_MAX_ATTEMPTS: "3"' in workflow_text


def test_artifacts_tradingview_is_uploaded(workflow_text: str) -> None:
    # The retry log lives under artifacts/tradingview/, which must
    # continue to be uploaded so post-mortem download works.
    assert "actions/upload-artifact" in workflow_text
    assert "artifacts/tradingview/" in workflow_text
