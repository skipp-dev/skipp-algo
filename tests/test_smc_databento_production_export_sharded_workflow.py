"""Contract tests for the canonical sharded Databento producer workflow.

Pins the cache-probe-log telemetry wiring that remains valuable after the
cutover to the live 12:00/16:00 UTC schedule:

* the canonical weekday crons stay fixed at 12:00 + 16:00 UTC,
* manual ``workflow_dispatch`` remains available,
* each shard writes its probe JSONL to a shard-specific path,
* the probe JSONL is uploaded via its own hard-error artifact step,
* the shard bundle artifact does not silently hide probe-log loss.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = ROOT / ".github/workflows/smc-databento-production-export-sharded.yml"


def _read() -> str:
    return WORKFLOW_PATH.read_text(encoding="utf-8")


def test_canonical_live_crons_are_pinned() -> None:
    text = _read()
    assert "schedule:" in text
    assert '- cron: "0 12 * * 1-5"' in text
    assert '- cron: "0 16 * * 1-5"' in text


def test_manual_dispatch_remains_available() -> None:
    text = _read()
    assert "workflow_dispatch:" in text
    assert "lookback_days:" in text
    assert "num_shards:" in text


def test_cache_probe_env_var_is_shard_specific() -> None:
    text = _read()
    expected = 'DATABENTO_CACHE_PROBE_LOG: "artifacts/ci/cache_probe_shard_${{ matrix.shard_id }}.jsonl"'
    assert expected in text, "cache-probe path must be partitioned by matrix.shard_id"


def test_cache_probe_log_has_dedicated_hard_error_upload_step() -> None:
    text = _read()
    assert "- name: Upload cache-probe log" in text
    assert "name: cache-probe-shard-${{ matrix.shard_id }}-of-${{ matrix.shard_of }}" in text
    assert "path: artifacts/ci/cache_probe_shard_${{ matrix.shard_id }}.jsonl" in text
    assert "if-no-files-found: error" in text



def test_shard_bundle_artifact_does_not_hide_probe_log() -> None:
    text = _read()
    bundle_block_start = text.index("a9b-2b-shard-${{ matrix.shard_id }}-of-${{ matrix.shard_of }}")
    bundle_block_end = text.index("if-no-files-found: warn", bundle_block_start)
    bundle_block = text[bundle_block_start:bundle_block_end]
    assert "cache_probe_shard_" not in bundle_block, (
        "probe JSONL must live in its own upload step, not inside the generic shard bundle"
    )


def test_dispatch_input_fallbacks_still_exist() -> None:
    text = _read()
    assert "${{ inputs.lookback_days || '30' }}" in text
    assert "${{ inputs.num_shards || '6' }}" in text
