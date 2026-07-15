"""Fast-gates inventory — single source of truth for the ADR-0012 partition.

The repository runs two pytest CI lanes:

- ``fast-gates`` (smc-fast-pr-gates.yml) — required status check, ~6 min,
  curated set of pin/ledger/integration tests.
- ``validate``  (ci.yml) — full suite, ~40 min.

ADR-0012 Option B partitions them via a pytest ``slow`` marker so the
two lanes become *disjoint*. To avoid scattering ``pytestmark =
pytest.mark.slow`` lines across ~1000 files, the partition is driven
from this single inventory: the root ``conftest.py`` auto-marks every
test file **not** in :data:`FAST_TEST_FILES` (or :data:`FAST_TEST_GLOBS`)
as ``slow`` at collection time.

The inventory MUST stay in lock-step with the file list inside
``.github/workflows/smc-fast-pr-gates.yml``;
``tests/test_pytest_marker_bucket_discipline.py`` is the guard.

Phase 1 (this commit): auto-mark only — no CI selection changes. Lets
local developers run ``pytest -m "not slow"`` to get the fast set.
Phase 2 (follow-up): replace the explicit file list in
smc-fast-pr-gates.yml with ``pytest -m "not slow"``; add ``-m slow`` to
validate. See ADR-0012.
"""

from __future__ import annotations

# Explicit fast test files — mirror of the file list inside
# ``smc-fast-pr-gates.yml`` (steps "Run pin / ledger drift guard",
# "Run fast SMC integration tests", "Run terminal coverage subset").
FAST_TEST_FILES: frozenset[str] = frozenset({
    # Pin / ledger drift guard
    "test_assert_and_open_encoding_pin.py",
    "test_assert_in_production_budget.py",
    "test_bare_type_ignore_ledger.py",
    "test_broad_except_silent_budget.py",
    "test_builtin_open_encoding_ledger.py",
    "test_dynamic_getattr_ledger.py",
    "test_dynamic_import_and_todo_tripwires.py",
    "test_field_preference_chain_ledger.py",
    "test_global_statement_budget.py",
    "test_hashlib_weak_hash_ledger.py",
    "test_http_client_discipline.py",
    "test_http_post_egress_ledger.py",
    "test_lint_debt_no_regression.py",
    "test_loopback_and_baseimage_pin.py",
    "test_monitoring_metric_alert_coverage.py",
    "test_mutable_defaults_and_loads_pins.py",
    "test_nonlocal_budget.py",
    "test_noqa_budget.py",
    "test_noqa_suppression_ledger.py",
    "test_os_environ_mutation_ledger.py",
    "test_os_unlink_remove_ledger.py",
    "test_path_text_io_encoding_ledger.py",
    "test_pine_alertcondition_and_declaration_pin.py",
    "test_pine_context_library_contract.py",
    "test_pine_engine_fill_boundary.py",
    "test_pine_handlib_publisher_inventory.py",
    "test_pine_library_import_permissions.py",
    "test_pine_request_security_htf_pin.py",
    "test_pine_var_budget_pin.py",
    "test_prod_print_ledger.py",
    "test_pytest_skip_budget.py",
    "test_random_tempfile_ledger_pin.py",
    "test_realtime_signals_sister_ledger_guardrail.py",
    "test_silent_error_swallow_pin.py",
    "test_silent_security_and_boundary_bundle.py",
    "test_socket_bind_loopback_pin.py",
    "test_subprocess_shell_injection_pin.py",
    "test_subprocess_spawn_sites_ledger.py",
    "test_sys_exit_ledger_pin.py",
    "test_sys_path_mutation_ledger.py",
    "test_time_sleep_budget.py",
    "test_type_ignore_budget.py",
    "test_urllib_urlopen_ledger.py",
    "test_warnings_simplefilter_ledger.py",
    "test_weak_hash_pin.py",
    "test_while_true_termination_ledger.py",
    "test_workflow_upload_artifact_uniform_version.py",
    "test_workflow_issue_labels_exist.py",
    "test_workflow_no_fake_push_success.py",
    # Workflow structural-invariant guards (added to fast-gates via #2445)
    "test_workflow_concurrency_cron_no_cancel.py",
    "test_workflow_continue_on_error_inventory.py",
    "test_workflow_freshness_monitor_workflow.py",
    "test_workflow_invoked_scripts_importable.py",
    "test_workflow_orphan_inventory.py",
    "test_workflow_permissions_present.py",
    "test_workflow_auth_pattern.py",
    "test_atexit_register_zero_surface.py",
    "test_atomic_write_call_sites.py",
    "test_dynamic_setattr_hasattr_zero_surface.py",
    "test_hmac_auth_zero_surface.py",
    "test_dangerous_io_zero_surface_pin.py",
    "test_fcntl_flock_zero_surface.py",
    "test_globals_call_zero_surface.py",
    "test_lru_cache_maxsize_discipline.py",
    "test_asyncio_event_loop_zero_surface.py",
    "test_division_site_baseline.py",
    "test_pine_request_security_per_file_budget.py",
    "test_requirements_discipline_pin.py",
    # Zero-surface security guards. On the required path because fast-gates is
    # the only merge-gating test job: these forbid a construct outright, so an
    # ungated one lets a NEW violation merge green and only fails afterwards in
    # `validate` (agent.py's asyncio.run reached main exactly that way, #3499).
    # #3672/#3680 derive the required set from a ledger's structure — line pins
    # or per-file counts — which these have neither of, so they were invisible
    # to it. Cost measured A/B on one machine, each run alone: the drift-guard
    # suite goes 104.98s -> 112.08s (2160 -> 2189 tests), i.e. ~7s. Cheap
    # because they share the cached AST corpus: parsing ~1030 first-party
    # modules is already paid for by the guards ahead of them, so each of these
    # only re-walks the trees. (Run standalone on a cold cache the same set
    # costs ~62s — nearly all of it that first parse.)
    "test_dangerous_builtins_zero_surface.py",
    "test_datetime_tz_safety_zero_surface.py",
    "test_dynamic_exec_and_pickle_zero_surface.py",
    "test_exec_mktemp_shelltrue_zero_surface.py",
    "test_library_discipline_zero_surface.py",
    "test_os_system_input_assert_zero_surface.py",
    "test_pickle_read_and_eval_zero_surface.py",
    "test_pickle_write_and_abs_pathjoin_zero_surface.py",
    "test_tls_jwt_verification_zero_surface.py",
    "test_yaml_xml_zero_surface.py",
    # Semantic security guards. #3672/#3680/#3685 put the *inventory* guards on
    # the required path — the ones that freeze a call site's line, its per-file
    # count, or the absence of a construct. These are the other half: they check
    # the *property* a call site must have. Each protects a surface no gated
    # guard reads, verified per surface rather than by name:
    #   httpx timeout        — the gated http_client_discipline pins urlopen's
    #                          timeout only, and this repo is httpx-exclusive.
    #   subprocess check=/timeout=, threading daemon=, mkdir exist_ok=,
    #   tempfile delete=    — the gated ledgers pin these call sites but never
    #                          read the kwarg (same shape as #3678's os.kill).
    #   weak-hash usedforsecurity= — the gated weak_hash_pin freezes the budget;
    #                          swapping a call in place keeps the count.
    #   to_datetime utc=     — no gated reader.
    #   six_zero bundle      — secret-shaped files tracked in git, star-imports,
    #                          Pine study()/version, workflow YAML parse.
    #
    # Cost: not measurable above this machine's noise. Three runs, each alone:
    # base 127.0s and 108.25s on IDENTICAL input (a 19s spread), this branch
    # 106.8s with 41 more tests. So the added cost is bounded by that spread,
    # not quantified by it — quoting a point estimate here would be inventing
    # precision the measurement does not have. It is cheap for a structural
    # reason: these share the cached AST corpus, so the ~1030-module parse is
    # already paid for by the guards ahead of them and only the walk is new.
    "test_httpx_timeout_invariant.py",
    "test_mkdir_makedirs_exist_ok_invariant.py",
    "test_six_zero_tripwires_bundle.py",
    "test_subprocess_run_check_invariant.py",
    "test_subprocess_timeout_discipline.py",
    "test_tempfile_namedtemp_delete_kwarg_invariant.py",
    "test_threading_thread_daemon_invariant.py",
    "test_to_datetime_utc_discipline.py",
    "test_weak_hash_usedforsecurity_pin.py",
    "test_module_test_coverage_pin.py",
    "test_workflow_python_unbuffered.py",
    "test_workflow_pythonpath_for_direct_invoke.py",
    "test_workflow_runner_pinned.py",
    "test_workflow_set_plus_e_inventory.py",
    "test_smc_library_refresh_workflow.py",
    "test_schema_version_manifest_alignment.py",
    "test_edge_hypotheses_frozen.py",
    "test_point_in_time_integrity.py",
    "test_family_walkforward_config.py",
    "test_build_family_metrics.py",
    "test_family_returns.py",
    "test_family_event_adapter.py",
    "test_family_verdict.py",
    "test_verdict_panel.py",
    "test_run_edge_pipeline.py",
    "test_fast_gates_silent_skip_coverage.py",
    # Bus-v3 / context-library contract guards. On the required path because
    # fast-gates is the only merge-gating test job: #3657 landed the
    # smc_profile_engine allowlist exception together with the test enforcing it,
    # and CI ran neither. Source-parsing only, <2s total.
    "test_smc_bus_v2_freeze.py",
    "test_smc_context_golden.py",
    # Fast SMC integration suite
    "test_smc_action_degradation.py",
    "test_manifest_preference.py",
    "test_stale_batch_guard.py",
    "test_smc_trust_state.py",
    # Terminal coverage subset
    "test_streamlit_terminal_import.py",
    "test_streamlit_terminal_config.py",
    "test_streamlit_terminal_runtime.py",
    "test_streamlit_terminal_alerts.py",
    "test_terminal_notifications.py",
    "test_terminal_export_dispatch.py",
    "test_streamlit_terminal_feed_state.py",
    "test_streamlit_terminal_pure_functions.py",
    # Discipline test itself — kept in the FAST inventory so the
    # conftest auto-marker never marks it `slow`, and executed on the
    # required `fast-gates` path (drift-guard step) so the fast/slow
    # partition is validated before merge, not only post-merge in
    # `validate`.
    "test_pytest_marker_bucket_discipline.py",
})

# Glob patterns covered by the fast lane. fast-gates expands
# ``tests/test_smc_integration_*.py`` directly in the workflow step;
# mirror that pattern here so new files in the SMC integration suite
# do not get auto-marked slow.
FAST_TEST_GLOBS: frozenset[str] = frozenset({
    "test_smc_integration_*.py",
})


def is_fast(basename: str) -> bool:
    """Return True iff ``basename`` belongs to the fast-gates lane.

    Membership is determined by exact match against :data:`FAST_TEST_FILES`
    or by glob match against :data:`FAST_TEST_GLOBS`.
    """
    from fnmatch import fnmatch

    if basename in FAST_TEST_FILES:
        return True
    return any(fnmatch(basename, pat) for pat in FAST_TEST_GLOBS)
