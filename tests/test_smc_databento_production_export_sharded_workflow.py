"""Contract tests for the canonical sharded Databento producer workflow.

Pins the cache-probe-log telemetry wiring that remains valuable after the
cutover to the live 12:00/16:00 UTC schedule:

* the canonical weekday crons stay fixed at 12:00 + 16:00 UTC,
* manual ``workflow_dispatch`` remains available,
* the probe is opt-in via the ``enable_cache_probe`` dispatch input —
  scheduled runs leave the env empty and skip the probe entirely,
* when enabled, each shard writes its probe JSONL to a shard-specific path,
* the probe JSONL is uploaded via its own dedicated step that stays
  ``always()`` (survives shard OOM/timeout) but is ``if-no-files-found:
  ignore`` so schedule runs which produce no JSONL don't fail the shard,
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


def test_cache_probe_env_var_is_shard_specific_and_opt_in() -> None:
    text = _read()
    expected = (
        "DATABENTO_CACHE_PROBE_LOG: ${{ inputs.enable_cache_probe "
        "&& format('artifacts/ci/cache_probe_shard_{0}.jsonl', matrix.shard_id) || '' }}"
    )
    assert expected in text, (
        "cache-probe path must be partitioned by matrix.shard_id AND gated on "
        "the enable_cache_probe input so schedule runs skip probe IO"
    )
    # GHA-quirk regression-guard (Phase-B Run 1 post-mortem, 2026-05-20):
    # for ``type: boolean`` workflow_dispatch inputs GHA exposes the value
    # as a real boolean in ``${{ inputs.* }}``, NOT the string "true".
    # The string-compare form ``inputs.enable_cache_probe == 'true'`` is
    # therefore always false on dispatches with the toggle on, and silently
    # drops every probe artifact (root cause of Run 26145436063 producing
    # 0 probe files despite ``-f enable_cache_probe=true``).
    assert "inputs.enable_cache_probe == 'true'" not in text, (
        "GHA-quirk: boolean-typed workflow inputs are NOT compared with "
        "the string 'true'. Use the bare truthy form "
        "(``inputs.enable_cache_probe && ... || ''``) instead."
    )


def test_enable_cache_probe_input_is_opt_in_default_false() -> None:
    text = _read()
    # Pin the dispatch surface: the toggle exists, is boolean, defaults to
    # false (= probe off on every schedule run, opt-in for baseline runs).
    assert "enable_cache_probe:" in text
    block_start = text.index("enable_cache_probe:")
    # Window is intentionally tight (next input or section break is well
    # within 400 chars) so we don't accidentally match neighbouring inputs.
    block = text[block_start : block_start + 400]
    assert "type: boolean" in block, "enable_cache_probe must be typed boolean"
    assert "default: false" in block, "enable_cache_probe must default to false (opt-in)"


def test_cache_probe_log_has_dedicated_soft_upload_step() -> None:
    text = _read()
    assert "- name: Upload cache-probe log" in text
    assert "name: cache-probe-shard-${{ matrix.shard_id }}-of-${{ matrix.shard_of }}" in text
    assert "path: artifacts/ci/cache_probe_shard_${{ matrix.shard_id }}.jsonl" in text
    # Locate the probe upload step and assert its `if-no-files-found` is
    # `ignore` (was `error` pre-PR-A; schedule runs intentionally produce
    # no JSONL when the opt-in toggle is off and must not fail the shard).
    step_start = text.index("- name: Upload cache-probe log")
    step_block = text[step_start : step_start + 800]
    assert "if-no-files-found: ignore" in step_block
    assert "if-no-files-found: error" not in step_block
    # The step itself stays unconditional so an OOM/timeout shard with the
    # toggle on still publishes whatever JSONL it managed to flush.
    assert "if: always()" in step_block



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
