"""F-012: contract test for the sharded production-export workflow.

Pins the probe-cron schedule, schedule-gated compat steps, probe-log env
var and the dedicated probe-log upload-artifact step. The workflow is a
shared-infra surface (consumed by the F-V8-perf-3.5 probe telemetry
pipeline and the manual export ops); silent edits there are exactly the
kind of regression this test class exists to prevent.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = ROOT / ".github/workflows/smc-databento-production-export-sharded.yml"


def _read() -> str:
    return WORKFLOW_PATH.read_text(encoding="utf-8")


def test_probe_cron_pinned_at_02_utc_weekdays() -> None:
    text = _read()
    assert "schedule:" in text
    assert '- cron: "0 2 * * 1-5"' in text, (
        "probe-cron schedule must be pinned to 02:00 UTC Mon-Fri "
        "(F-V8-perf-3.5 telemetry contract)"
    )


def test_probe_log_env_var_is_per_shard() -> None:
    text = _read()
    assert (
        'DATABENTO_CACHE_PROBE_LOG: "artifacts/ci/cache_probe_shard_${{ matrix.shard_id }}.jsonl"'
        in text
    ), "probe-log path must be sharded by matrix.shard_id"


def test_probe_log_has_dedicated_upload_step_with_hard_error() -> None:
    text = _read()
    # The dedicated step name + its hard-error gate are both required.
    assert "Upload cache-probe log" in text
    assert "if-no-files-found: error" in text, (
        "F-011: probe-log upload must hard-error on missing telemetry"
    )
    # The shard-bundle artifact must NOT also list the probe JSONL
    # (otherwise the warn-on-missing bundle hides the missing-probe case).
    bundle_block_start = text.index("a9b-2b-shard-${{ matrix.shard_id }}-of-${{ matrix.shard_of }}")
    bundle_block_end = text.index("retention-days", bundle_block_start)
    bundle_block = text[bundle_block_start:bundle_block_end]
    assert "cache_probe_shard_" not in bundle_block, (
        "probe-log must live in its own upload step, not bundled with stdout"
    )


def test_input_fallbacks_present() -> None:
    text = _read()
    # F-12 / PR #2288 contract: manual dispatch must still work without
    # explicit inputs (schedule trigger has no inputs at all).
    assert "${{ inputs.lookback_days || '30' }}" in text
    assert "${{ inputs.num_shards || '6' }}" in text


def test_compat_stage_gated_on_non_schedule() -> None:
    text = _read()
    # Compat-stage / upload steps must NOT run on probe-cron (schedule),
    # otherwise every 02:00 UTC run would consume the daily compat-stage
    # budget and overwrite the live-cron output.
    assert "github.event_name != 'schedule'" in text
