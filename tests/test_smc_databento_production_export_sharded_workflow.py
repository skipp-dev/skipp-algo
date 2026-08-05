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


def test_first_daily_tick_seeds_full_window_for_long_horizon_benchmarks() -> None:
    text = _read()
    assert 'github.event.schedule != \'0 8 * * 1-5\'' in text
    assert '08:00 UTC – cache-backed full-window benchmark seed' in text


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


def test_incremental_from_manifest_input_is_opt_in_default_false() -> None:
    # Step-2b cadence activation (Option b): the watermark-narrowing toggle
    # is opt-in and defaults to false, so every schedule run keeps doing a
    # full-lookback rescan until an operator explicitly flips it on after
    # reviewing the dry-run preview.
    text = _read()
    assert "incremental_from_manifest:" in text
    block_start = text.index("incremental_from_manifest:")
    block = text[block_start : block_start + 500]
    assert "type: boolean" in block, "incremental_from_manifest must be typed boolean"
    assert "default: false" in block, "incremental_from_manifest must default to false (opt-in)"


def test_incremental_toggle_uses_boolean_safe_truthy_form() -> None:
    # Same GHA-quirk guard as enable_cache_probe: a boolean-typed input is
    # exposed as a real boolean, so it must use the bare truthy form and
    # never a string compare against 'true' (which is always false and would
    # silently keep the producer on the full-lookback path).
    text = _read()
    assert (
        "inputs.incremental_from_manifest" in text
        and "&& 'true'" in text
    ), "incremental toggle must use the boolean-safe truthy form"
    assert "inputs.incremental_from_manifest == 'true'" not in text, (
        "GHA-quirk: boolean-typed workflow inputs are NOT compared with the "
        "string 'true'. Use the bare truthy form instead."
    )


def test_compute_step_reads_manifest_asof_for_dry_run() -> None:
    # The plan job must read the baked manifest's asof_date and always emit a
    # side-effect-free incremental dry-run preview into the job summary, so
    # the narrowed window can be reviewed before the toggle is switched on
    # (CI dry-run before scharfschalten).
    text = _read()
    assert 'MANIFEST="pine/generated/smc_micro_profiles_generated.json"' in text
    assert "jq -r '.asof_date // empty'" in text
    assert "incremental dry-run preview" in text
    assert '>> "$GITHUB_STEP_SUMMARY"' in text


def test_incremental_only_feeds_matrix_when_toggle_on() -> None:
    # The production matrix-producing plan_shards call only receives
    # --last-baked-date when BOTH the opt-in toggle is on AND a watermark
    # exists; otherwise it stays the byte-for-byte full-lookback invocation.
    text = _read()
    assert 'if [ -n "${INCREMENTAL}" ] && [ -n "${ASOF}" ]; then' in text
    compute_start = text.index("- name: Compute shard plan")
    compute_block = text[compute_start : text.index("- name: Upload shard plan", compute_start)]
    assert "--last-baked-date" in compute_block
    # Both the dry-run preview call and at least one matrix-producing call
    # (incremental + full-lookback fall-through) keep plan_shards referenced
    # multiple times.
    assert compute_block.count("scripts/databento_plan_shards.py") >= 2


def test_databento_volatility_cache_is_warmed_across_runs() -> None:
    # Phase-C re-validation (#2334): without an actions/cache step for the
    # parquet cache directory every shard starts cold and the probe hit-rate
    # cannot reach the 86.8% sim-target. The primary key MUST rotate per
    # window-end AND per run_id so each run always uploads a fresh cache
    # entry containing newly delta-fetched parquets. The restore-keys
    # fallback MUST be OS-partitioned and shard-scoped so a new day inherits
    # the prior day's cache for delta-fetch.
    text = _read()
    assert "- name: Restore databento volatility cache" in text
    step_start = text.index("- name: Restore databento volatility cache")
    step_block = text[step_start : step_start + 1000]
    assert "uses: actions/cache@" in step_block
    assert "path: artifacts/databento_volatility_cache" in step_block
    assert (
        "key: dbnv-cache-${{ runner.os }}-shard-${{ matrix.shard_id }}-of-${{ matrix.shard_of }}-${{ matrix.end_date }}-${{ github.run_id }}"
        in step_block
    )
    assert "restore-keys:" in step_block
    # Most-specific fallback: same OS, same shard, same end_date (any run_id).
    assert (
        "dbnv-cache-${{ runner.os }}-shard-${{ matrix.shard_id }}-of-${{ matrix.shard_of }}-${{ matrix.end_date }}-"
        in step_block
    )
    # Broader fallback: same OS, same shard (any end_date / any run_id) so
    # a new window-end inherits the prior day's parquets.
    assert (
        "dbnv-cache-${{ runner.os }}-shard-${{ matrix.shard_id }}-of-${{ matrix.shard_of }}-"
        in step_block
    )


def test_reduce_has_swap_allocation_and_heartbeat() -> None:
    # WF-026 (2026-05-24): the reduce job was killed mid-merge by a runner
    # shutdown signal (run 26336694008, frame `full_universe_close_outcome_minute`).
    # Two structural guards prevent silent recurrence:
    # 1. an explicit 6GB swapfile is allocated before the merge so pandas
    #    concat peaks don't reap the runner VM via OOM, and
    # 2. a heartbeat sidecar prints merge RSS + system memory every 15s so
    #    the *next* OOM kill (if any) names the exact frame.
    text = _read()
    assert "- name: Allocate runtime swap (defensive OOM headroom)" in text
    assert "/swapfile.smc" in text
    assert "MERGE_LOG=\"artifacts/merged/_merge.log\"" in text
    assert "HEART_LOG=\"artifacts/merged/_heartbeat.log\"" in text
    assert "merge_rss_kb=" in text


def test_compat_publish_is_independent_job() -> None:
    # WF-026 (2026-05-24): the legacy `smc-databento-production-export-*`
    # compat artifact MUST live in its own job so a runner-shutdown / OOM
    # during the heavy merge can no longer silently drop it. The new
    # `publish-compat` job needs both `plan` and `reduce` (so its
    # `runs-on` evaluates), only runs when reduce fully succeeded, and
    # re-downloads the merged-manifest artifact on a fresh runner.
    import yaml

    text = _read()
    doc = yaml.safe_load(text)
    jobs = doc["jobs"]
    assert "publish-compat" in jobs, "publish-compat job missing"
    pc = jobs["publish-compat"]
    assert pc["needs"] == ["plan", "reduce"]
    assert pc["if"] == "needs.reduce.result == 'success'"
    step_names = [str(s.get("name") or "") for s in pc["steps"]]
    assert "Download merged manifest artifact" in step_names
    assert "Stage compat export bundle (legacy artifact name)" in step_names
    assert "Upload compat export bundle (legacy artifact name)" in step_names
    # The staging script calls `python` to parse the merged manifest's
    # partial_run flag; ubuntu-latest only ships `python3` on PATH, so the
    # pinned setup-python step must be present to expose `python`.
    assert "Set up Python" in step_names, "publish-compat must run setup-python (uses `python` in stage script)"
    setup_step = next(s for s in pc["steps"] if s.get("name") == "Set up Python")
    assert setup_step.get("uses") == "./.github/actions/setup-python-pinned"

    # And the `reduce` job MUST no longer carry the compat upload step,
    # otherwise we'd double-publish (and double-fail on flake).
    reduce_step_names = [str(s.get("name") or "") for s in jobs["reduce"]["steps"]]
    assert "Stage compat export bundle (legacy artifact name)" not in reduce_step_names
    assert "Upload compat export bundle (legacy artifact name)" not in reduce_step_names


# --- the compat gate, executed rather than described -------------------------
#
# `Stage compat export bundle` decides `skip_compat`, which gates the legacy
# artifact upload. Measured 2026-08-04 with a value-preserving arm swap (the
# `true`/`false` token multiset left unchanged, so any substring assertion is
# blind by construction): all 157 tests across the 15 files that name this
# workflow stayed green -- while an incomplete day would have been published to
# legacy consumers that have no partial-run handling, and a complete one would
# have been withheld.

import json
import re
import sys
from pathlib import Path

from tests._workflow_step_shell import Stub, run_step

_COMPAT_STEP = "Stage compat export bundle (legacy artifact name)"
_MANIFEST = "artifacts/merged/databento_volatility_production_merged_manifest.json"


def _compat(tmp_path: Path, manifest: dict | None, *, extra_stubs: dict | None = None):
    """Run the real step against a merged manifest of our choosing.

    `python` is passed through to the real interpreter rather than stubbed: the
    step's decision IS the manifest read, and faking its answer would move the
    thing under test into the test. `extra_stubs` supplies the clock for the
    one assertion that needs a fixed one.
    """
    if manifest is not None:
        path = tmp_path / _MANIFEST
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(manifest), encoding="utf-8")
        (path.parent / "databento_volatility_production_merged__1m.parquet").write_bytes(b"")
    return run_step(
        "smc-databento-production-export-sharded.yml",
        _COMPAT_STEP,
        tmp_path,
        env={},
        stubs={"python": Stub(passthrough=sys.executable), **(extra_stubs or {})},
        expressions={"needs.plan.outputs.artifact_scope": "smc-databento-production-export"},
    )


def test_a_complete_day_is_published_to_legacy_consumers(tmp_path: Path) -> None:
    """The direction that must not be lost: a whole day reaches the old name."""
    result = _compat(tmp_path, {"partial_run": False})
    assert result.returncode == 0, result.stderr
    assert result.outputs["skip_compat"] == "false", (
        f"a complete export must reach the legacy artifact; got {result.outputs}"
    )


def test_the_export_date_is_the_clock_not_the_manifest(tmp_path: Path) -> None:
    """`EXPORT_DATE=$(date -u +%Y-%m-%d)` — today in UTC, whatever the manifest says.

    2026-08-05: the assertion this replaces wrote `export_date: "2026-08-04"`
    into the manifest and required that value back. It passed on 2026-08-04 --
    because that happened to be the day it ran, not because the manifest was
    ever read. The step ignores that key entirely. The next day it failed with
    `'2026-08-05' == '2026-08-04'`, which is the only reason anyone found out.

    So supply the clock and assert both halves: the value comes from `date`,
    and a manifest key of the same name does not influence it.
    """
    result = _compat(
        tmp_path,
        {"partial_run": False, "export_date": "2026-08-04"},
        # Answers `+%Y-%m-%d` only; anything else is a change in what the step
        # asks the clock for, and must fail here rather than be guessed at.
        extra_stubs={
            "date": Stub(script='''
for a in "$@"; do
  case "$a" in
    +%Y-%m-%d) echo "2019-01-02"; exit 0 ;;
  esac
done
echo "unexpected date invocation: $*" >&2
exit 64
'''),
        },
    )
    assert result.returncode == 0, result.stderr
    assert result.outputs["export_date"] == "2019-01-02", (
        f"the export date must come from the clock, not the manifest; got {result.outputs}"
    )
    # ISO, not YYYYMMDD: the step's own comment says a compact form breaks the
    # consumer's `smc-databento-production-export-<date>-*` prefix match in
    # smc-library-refresh.yml and silently falls back to the previous day.
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", result.outputs["export_date"])
    assert result.called_with("-u", "+%Y-%m-%d"), (
        f"the date must be read in UTC, not the runner's local zone; asked: {result.calls}"
    )


def test_a_partial_day_is_withheld(tmp_path: Path) -> None:
    """The reason the gate exists: legacy consumers cannot see a partial day."""
    result = _compat(tmp_path, {"partial_run": True, "export_date": "2026-08-04"})
    assert result.returncode == 0, result.stderr
    assert result.outputs["skip_compat"] == "true", (
        f"a partial run must not be published under the legacy name; got {result.outputs}"
    )


def test_a_partial_flag_nested_under_manifest_is_honoured_too(tmp_path: Path) -> None:
    """Both shapes the reader accepts, because only one of them is exercised.

    The step reads `d.get('partial_run') or d.get('manifest', {}).get('partial_run')`.
    A test that only ever writes the top-level key would leave the second half
    of that expression unmeasured.
    """
    result = _compat(tmp_path, {"manifest": {"partial_run": True}})
    assert result.outputs["skip_compat"] == "true", (
        f"a nested partial_run must withhold the upload too; got {result.outputs}"
    )


def test_a_missing_manifest_withholds_rather_than_guesses(tmp_path: Path) -> None:
    """No manifest is not evidence of a complete day."""
    result = _compat(tmp_path, None)
    assert result.returncode == 0, "a missing manifest must not fail the job"
    assert result.outputs["skip_compat"] == "true"
    assert result.outputs["export_date"] == ""
