"""A9b.2b-v2 — YAML smoke tests for the reduce job.

Guards the structural wiring of the sharded workflow's ``reduce`` job
which downloads every per-shard producer artifact, runs
``scripts/databento_production_merge_shards.py`` with
``--expected-shard-count`` + ``--allow-partial``, and uploads the merged
manifest. Anything below that the GitHub Actions YAML engine cannot
catch in a static parse round (e.g. wrong artifact pattern, missing
``always()`` guard on the if-condition, wrong actions/ versions) gets
caught here in <2s pytest instead of after a 120-min producer dispatch.
"""

from __future__ import annotations

from pathlib import Path

import pytest

_SHARDED_WORKFLOW_BASENAME = "smc-databento-production-export-sharded"
_REPO_ROOT = Path(__file__).resolve().parents[1]


def _yaml_doc() -> dict:
    yaml = pytest.importorskip("yaml")
    path = (
        _REPO_ROOT
        / ".github"
        / "workflows"
        / f"{_SHARDED_WORKFLOW_BASENAME}.yml"
    )
    assert path.exists(), f"Expected sharded workflow at {path}"
    return yaml.safe_load(path.read_text())


def _reduce_job() -> dict:
    doc = _yaml_doc()
    jobs = doc["jobs"]
    assert "reduce" in jobs, "A9b.2b-v2: reduce job missing from sharded workflow"
    return jobs["reduce"]


def _reduce_steps() -> list[dict]:
    return _reduce_job()["steps"]


# ---------------------------------------------------------------------------
# Job-level structure
# ---------------------------------------------------------------------------

def test_reduce_needs_plan_and_producer() -> None:
    job = _reduce_job()
    needs = job["needs"]
    if isinstance(needs, str):
        needs = [needs]
    assert set(needs) == {"plan", "producer"}, (
        f"reduce job must depend on both plan and producer; got {needs!r}"
    )


def test_reduce_if_condition_is_partial_safe() -> None:
    # Must use always() so reduce still runs when some producer shards
    # fail (partial-report principle), but must also gate on plan success
    # so we don't run reduce when there is provably nothing to merge.
    job = _reduce_job()
    expr = str(job.get("if", ""))
    assert "always()" in expr, (
        f"reduce.if must include always(); got {expr!r}. Without it, a single "
        f"producer-shard failure would skip reduce and we'd lose the partial "
        f"merged manifest."
    )
    assert "needs.plan.result == 'success'" in expr, (
        f"reduce.if must guard on plan success; got {expr!r}. Without it, "
        f"reduce would run even when the planner failed (no shards to merge)."
    )
    assert "needs.plan.outputs.shard_count != '0'" in expr, (
        f"reduce.if must guard against zero-shard plans; got {expr!r}. The "
        f"producer job is skipped when shard_count == '0', and without this "
        f"guard reduce would run on an empty matrix and fail at download."
    )


def test_reduce_uses_pinned_runner_var() -> None:
    job = _reduce_job()
    runs_on = str(job.get("runs-on", ""))
    assert "vars.SMC_GH_HOSTED_RUNNER" in runs_on, (
        f"reduce.runs-on must consult vars.SMC_GH_HOSTED_RUNNER per repo "
        f"runner-pinning discipline; got {runs_on!r}"
    )


def test_reduce_timeout_is_short() -> None:
    # Reduce is small (downloads a few MB of manifests + JSON merge).
    # Anything > 30min suggests artifact-download flakiness was masked.
    job = _reduce_job()
    tmo = job.get("timeout-minutes")
    assert isinstance(tmo, int) and 1 <= tmo <= 30, (
        f"reduce.timeout-minutes must be an int in [1, 30]; got {tmo!r}"
    )


# ---------------------------------------------------------------------------
# Step-level structure
# ---------------------------------------------------------------------------

def test_reduce_downloads_all_shard_artifacts_separately() -> None:
    steps = _reduce_steps()
    matches = [
        s for s in steps if str(s.get("uses", "")).startswith("actions/download-artifact@")
    ]
    assert matches, "reduce job must include actions/download-artifact"
    # Pin to v7 per repo discipline (matches upload-artifact@v7).
    # Accept the SHA-pinned equivalent produced by the ci/pin-action-shas PR.
    _DOWNLOAD_V7_SHA = "37930b1c2abaa49bbe596cd826c3c89aef350131"
    for s in matches:
        assert s["uses"] in {
            "actions/download-artifact@v7",
            f"actions/download-artifact@{_DOWNLOAD_V7_SHA}",
        }, (
            f"reduce must pin actions/download-artifact@v7; got {s['uses']!r}"
        )
    with_block = matches[0].get("with", {})
    assert with_block.get("pattern") == "a9b-2b-shard-*-of-*", (
        f"download pattern must be 'a9b-2b-shard-*-of-*'; got "
        f"{with_block.get('pattern')!r}"
    )
    # merge-multiple: false is critical — true would collide manifest
    # basenames across shards and silently overwrite.
    assert with_block.get("merge-multiple") is False, (
        "reduce download-artifact must set merge-multiple: false to keep "
        "each shard's manifest in its own subdirectory"
    )


def test_reduce_invokes_merge_shards_script_with_required_flags() -> None:
    steps = _reduce_steps()
    run_text = "\n".join(str(s.get("run", "")) for s in steps if "run" in s)
    assert "scripts/databento_production_merge_shards.py" in run_text, (
        "reduce job must invoke scripts/databento_production_merge_shards.py"
    )
    for flag in ("--shard-dir", "--output", "--expected-shard-count", "--allow-partial"):
        assert flag in run_text, (
            f"reduce job must pass {flag} to the merge script; not found in run-blocks"
        )


def test_reduce_passes_plan_shard_count_to_expected() -> None:
    steps = _reduce_steps()
    # The shard-count must come from the plan job's output, not be
    # hard-coded; otherwise a planner-config change silently breaks the
    # partial-run detection.
    blob = "\n".join(
        str(s.get("env", "")) + "\n" + str(s.get("run", "")) for s in steps
    )
    assert "needs.plan.outputs.shard_count" in blob, (
        "reduce must derive --expected-shard-count from "
        "needs.plan.outputs.shard_count, not hard-code it"
    )


def test_reduce_uploads_merged_manifest_artifact() -> None:
    steps = _reduce_steps()
    uploads = [
        s for s in steps if str(s.get("uses", "")).startswith("actions/upload-artifact@")
    ]
    assert uploads, "reduce job must upload the merged manifest as an artifact"
    # The reduce job may now have multiple upload-artifact steps (canonical
    # merged manifest + an optional compat-export bundle gated on
    # partial_run=false). This test guards only the canonical merged-manifest
    # upload, which must remain `if: always()` so partial runs are still
    # captured for triage. Other uploads (e.g. the compat-export bundle) are
    # intentionally gated and are validated by their own dedicated tests
    # (see tests/test_workflow_a9b5_sharded_compat.py).
    canonical = [
        u for u in uploads
        if str(u.get("with", {}).get("name", "")).startswith("a9b-2b-merged-manifest")
    ]
    assert canonical, (
        "reduce must upload an artifact named 'a9b-2b-merged-manifest' "
        f"(got upload names: {[str(u.get('with', {}).get('name')) for u in uploads]!r})"
    )
    # Accept both the floating tag and its SHA-pinned equivalent.
    _UPLOAD_V7_SHA = "043fb46d1a93c77aae656e7c1c64a875d1fc6a0a"
    for s in canonical:
        assert s["uses"] in {
            "actions/upload-artifact@v7",
            f"actions/upload-artifact@{_UPLOAD_V7_SHA}",
        }, (
            f"reduce upload-artifact must be pinned @v7; got {s['uses']!r}"
        )
        assert str(s.get("if", "")).strip() == "always()", (
            f"reduce merged-manifest upload-artifact must run with if: always() "
            f"so partial merged manifests are still captured for triage; got "
            f"{s.get('if')!r}"
        )
    names = {u["with"]["name"] for u in canonical}
    assert "a9b-2b-merged-manifest" in names, (
        f"reduce must upload artifact named 'a9b-2b-merged-manifest'; "
        f"got {names!r}"
    )


def test_reduce_checkout_pinned_v6() -> None:
    steps = _reduce_steps()
    checkouts = [s for s in steps if str(s.get("uses", "")).startswith("actions/checkout@")]
    assert checkouts, "reduce must check out the repo to access scripts/"
    # Accept either the mutable tag or the SHA-pinned equivalent (repo enforces SHA pinning).
    _CHECKOUT_V6_REFS = {
        "actions/checkout@v6",
        "actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd",  # SHA pin for v6
    }
    for s in checkouts:
        assert s["uses"] in _CHECKOUT_V6_REFS, (
            f"reduce checkout must be pinned @v6 (or its SHA equivalent); got {s['uses']!r}"
        )


def test_reduce_uses_python_pinned_action() -> None:
    steps = _reduce_steps()
    py_setup = [
        s for s in steps if str(s.get("uses", "")).endswith("/setup-python-pinned")
    ]
    assert py_setup, (
        "reduce must use ./.github/actions/setup-python-pinned per repo "
        "Python version discipline"
    )


def test_reduce_installs_python_dependencies_before_merging_payloads() -> None:
    """The reducer imports pandas/pyarrow when concatenating parquet payloads."""
    steps = _reduce_steps()
    names = [str(step.get("name", "")) for step in steps]
    install_uv_idx = names.index("Install uv")
    install_deps_idx = names.index("Install Python dependencies")
    reduce_idx = names.index("Reduce per-shard manifests into one canonical manifest")

    assert install_uv_idx < install_deps_idx < reduce_idx
    install_run = steps[install_deps_idx].get("run", "")
    assert "uv pip install --system -r requirements.txt" in install_run, (
        "reduce must install requirements.txt before invoking the merge script; "
        "otherwise pandas/pyarrow imports fail after all shard artifacts download"
    )


def test_reduce_shard_dir_basename_encodes_shard_id() -> None:
    """
    Regression-guard for the shard-id parse bug:

    The reducer parses the shard-id from the basename of each --shard-dir
    via the regex ``shard-<i>(?:-of-<N>)?``. If the workflow passes a path
    whose basename does NOT encode the shard-id (e.g. the inner
    ``smc_microstructure_exports`` subdir, which has the same basename for
    every shard), the parser silently falls back to 1-based enumeration.
    On full-runs this coincidentally yields correct ids, but on partial-runs
    the surviving shard would always be labeled shard-1, producing wrong
    failed_shard_ids.

    This test asserts the workflow's reduce step iterates the OUTER
    shard-artifact dirs (basename pattern ``a9b-2b-shard-*``) and passes
    that dir as ``--shard-dir``.
    """
    steps = _reduce_steps()
    run_text = "\n".join(str(s.get("run", "")) for s in steps if "run" in s)
    # The for-loop must iterate the outer shard-artifact dirs.
    assert "shard-artifacts/a9b-2b-shard-*" in run_text, (
        "reduce step must loop over 'shard-artifacts/a9b-2b-shard-*' "
        "so the basename encodes the shard-id (regex 'shard-<i>')"
    )
    # The --shard-dir argument must be the loop variable, NOT a derived subdir.
    assert 'ARGS+=(--shard-dir "$d")' in run_text, (
        "reduce step must pass the OUTER loop dir '$d' as --shard-dir; "
        "any inner-subdir variant (e.g. '$d/smc_microstructure_exports') "
        "breaks shard-id parsing and corrupts failed_shard_ids on partial runs"
    )


def test_reduce_does_not_pass_smc_microstructure_exports_subdir() -> None:
    """Defensive negation of the previously-shipped bug."""
    steps = _reduce_steps()
    run_text = "\n".join(str(s.get("run", "")) for s in steps if "run" in s)
    assert '--shard-dir "$d/smc_microstructure_exports"' not in run_text, (
        "regression: '--shard-dir \"$d/smc_microstructure_exports\"' "
        "reintroduces the shard-id collision; pass '$d' instead"
    )
    assert '--shard-dir "$sub"' not in run_text, (
        "regression: '--shard-dir \"$sub\"' (where sub=$d/smc_microstructure_exports) "
        "reintroduces the shard-id collision; pass '$d' instead"
    )


def test_run_blocks_do_not_reference_unresolvable_template_expressions() -> None:
    """Regression for GHA template-engine crash on intra-job needs.* refs.

    GitHub Actions evaluates ``${{ ... }}`` expressions inside ``run:`` blocks
    BEFORE the shell sees the script — even inside what looks like a shell
    comment. If a job's run-block references its OWN job's outputs (or any
    expression that resolves to an empty string at evaluation time), the
    template engine crashes with::

        Error reading JToken from JsonReader. Path '', line 0, position 0.

    and the job fails before any step executes. We hit this in run
    25544081086 + 25544170182 because a documentation comment inside the
    ``plan`` job's ``Compute shard plan`` step referenced
    ``${{ fromJson(needs.plan.outputs.matrix) }}`` literally for didactic
    purposes — but ``needs.plan.outputs.matrix`` is empty during the plan
    job itself, so ``fromJson('')`` raised the error.

    Guard: no ``run:`` block may contain the literal substring
    ``${{ fromJson(`` (crashes when reference is empty), or ``${{`` followed
    by a literal ellipsis ``...`` (placeholder leaked into the YAML).
    Documentation must use plain prose without the ``${{`` braces.
    """
    yaml = pytest.importorskip("yaml")
    import re

    path = (
        _REPO_ROOT
        / ".github"
        / "workflows"
        / f"{_SHARDED_WORKFLOW_BASENAME}.yml"
    )
    doc = yaml.safe_load(path.read_text())
    # Match ${{ ... <ellipsis or 'fromJson('> ... }} style misuse.
    bad_patterns = (
        re.compile(r"\$\{\{[^}]*\.\.\."),       # ellipsis placeholder
        re.compile(r"\$\{\{\s*fromJson\("),     # fromJson(...) inside run
    )
    offenders: list[tuple[str, str, str]] = []
    for job_name, job in doc["jobs"].items():
        for step in job.get("steps", []):
            run_text = step.get("run")
            if not isinstance(run_text, str):
                continue
            for pat in bad_patterns:
                m = pat.search(run_text)
                if m:
                    offenders.append(
                        (job_name, str(step.get("name", "<unnamed>")), m.group(0))
                    )
    assert not offenders, (
        f"run: blocks must not contain ${{{{ fromJson(...) }}}} expressions — "
        f"GHA evaluates these even in shell comments and crashes when the "
        f"reference is empty. Offenders: {offenders}. Rephrase the comment to "
        f"plain prose without ${{{{ braces."
    )
