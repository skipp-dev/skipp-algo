"""Required-check coverage pin (Audit 2026-05-29).

Today's audit uncovered that PR #2415 merged at 16:44 with only
``fast-gates`` as the required status-check, while ``validate`` (which
runs ``test_workflow_issue_labels_exist.py`` and would have caught the
unknown ``release-pending`` / ``breaking-change`` labels introduced by
the same PR) only finished failing at 17:08 — **after** the merge. The
guard was already in the tree, it just wasn't on the required-check
boundary so main-governance let the PR through.

This test pins the inverse contract: the static workflow-shape lints
that catch the silent-skip class of regressions MUST be invoked inside
the ``smc-fast-pr-gates`` workflow's tripwire pytest call, because that
is the only check ``main-governance`` requires before merge.

Listed tests:
  * ``test_workflow_issue_labels_exist.py``  — catches ``--label X``
    where ``X`` is not in the repo's label snapshot (root cause of the
    PR #2419 auto-PR-create failure).
  * ``test_workflow_no_fake_push_success.py`` — catches workflows that
    paper over a rejected push with ``git push ... || echo`` (the GH013
    silent-success anti-pattern).
  * ``test_smc_library_refresh_workflow.py`` — pins the F-V8-N1 surfacing
    contract (::error annotation, release-pending auto-PR, override
    gate, retry wrapper) so a future refactor cannot silently revert
    back to the silent-skip behaviour that caused the 5-week
    publish-stall.
  * ``test_schema_version_manifest_alignment.py`` — catches the
    SCHEMA_VERSION-constant-vs-generated-manifest drift that produced
    the surprise MAJOR-bump in run 26598144143.

If any of these are removed from the fast-gates tripwire step (or moved
into the slower ``validate`` job that runs post-merge), the silent-skip
class of regressions re-opens.

----

Roster completeness pin (Principal-engineer audit 2026-05-31)
-------------------------------------------------------------
The four tests above were only a *subset* of the required-path tripwire
roster. The "Run pin / ledger drift guard" step invokes ~55 ledger /
budget / structural-invariant tripwires, but only those four were
frozen against silent removal. A refactor could drop, e.g.,
``test_hashlib_weak_hash_ledger.py`` or
``test_subprocess_shell_injection_pin.py`` from the required path and
no guard would notice — re-opening the exact "guard fell off the
required-check boundary" finding that motivated PR #2421.

:func:`test_full_tripwire_roster_pinned_in_fast_gates` closes that gap
by freezing the **complete** roster. Because this test file is itself
listed in the drift-guard step, the completeness check runs on the
required path: dropping any tripwire fails fast-gates immediately, not
post-merge in ``validate``. Intentionally retiring a tripwire requires a
conscious edit to :data:`FULL_REQUIRED_PATH_TRIPWIRES` (audit trail).

Self-pin bootstrap limit (acknowledged)
---------------------------------------
This guard cannot fully pin *its own* presence on the required path:
if a change drops ``test_fast_gates_silent_skip_coverage.py`` from the
drift-guard step, that same change also stops fast-gates from running
this assertion, so the removal cannot fail the required check in the
same PR. This is the inherent "who watches the watcher" bootstrap
problem. It is mitigated, not eliminated:

* The file is itself a member of :data:`FULL_REQUIRED_PATH_TRIPWIRES`,
  so its removal from the step is still caught whenever this test runs —
  including the full ``validate`` suite (post-merge) — converting a
  silent drop into a loud, attributable failure rather than a no-op.
* Full *pre-merge* closure would require a SECOND required status check
  that re-runs this assertion independently. The repository deliberately
  keeps ``fast-gates`` as the single required check (ADR-0011), so that
  trade-off is intentional: the residual exposure is one post-merge
  ``validate`` cycle, not an undetectable gap.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FAST_GATES_WORKFLOW = ROOT / ".github" / "workflows" / "smc-fast-pr-gates.yml"

REQUIRED_PINNED_TESTS: tuple[str, ...] = (
    "tests/test_workflow_issue_labels_exist.py",
    "tests/test_workflow_no_fake_push_success.py",
    "tests/test_smc_library_refresh_workflow.py",
    "tests/test_schema_version_manifest_alignment.py",
)

# Complete roster of tripwire tests invoked by the "Run pin / ledger
# drift guard" step in smc-fast-pr-gates.yml. This is an *independent*
# source of truth: it deliberately duplicates the YAML so that removing
# a test from the workflow (without also editing this tuple) is caught.
# Snapshot refreshed 2026-07-26; additions require a matching workflow edit so
# the tuple and the merge-critical invocation remain a two-way audit trail.
FULL_REQUIRED_PATH_TRIPWIRES: tuple[str, ...] = (
    "tests/test_assert_and_open_encoding_pin.py",
    "tests/test_assert_in_production_budget.py",
    "tests/test_asyncio_event_loop_zero_surface.py",
    "tests/test_atexit_register_zero_surface.py",
    "tests/test_atomic_write_call_sites.py",
    "tests/test_bare_type_ignore_ledger.py",
    "tests/test_bundle_loader_frame_discipline.py",
    "tests/test_broad_except_silent_budget.py",
    "tests/test_build_family_metrics.py",
    "tests/test_builtin_open_encoding_ledger.py",
    # 2026-08-01: guards that the R1-attested-source gate stays wired into
    # fast-gates. Without it the gate could be dropped from the workflow and,
    # like the R1 contract test itself, nothing would notice until after a
    # merge — which is the hole #4272 and #4284 went through.
    "tests/test_check_r1_attested_sources.py",
    "tests/test_dangerous_builtins_zero_surface.py",
    "tests/test_dangerous_io_zero_surface_pin.py",
    "tests/test_datetime_tz_safety_zero_surface.py",
    "tests/test_division_site_baseline.py",
    "tests/test_dynamic_exec_and_pickle_zero_surface.py",
    "tests/test_dynamic_getattr_ledger.py",
    "tests/test_dynamic_import_and_todo_tripwires.py",
    "tests/test_dynamic_setattr_hasattr_zero_surface.py",
    "tests/test_edge_hypotheses_frozen.py",
    "tests/test_exec_mktemp_shelltrue_zero_surface.py",
    "tests/test_family_event_adapter.py",
    "tests/test_family_returns.py",
    "tests/test_family_verdict.py",
    "tests/test_family_walkforward_config.py",
    "tests/test_fast_gates_silent_skip_coverage.py",
    "tests/test_fcntl_flock_zero_surface.py",
    "tests/test_field_preference_chain_ledger.py",
    "tests/test_gha_action_allowlist.py",
    "tests/test_global_statement_budget.py",
    "tests/test_globals_call_zero_surface.py",
    "tests/test_grafana_alert_rules_upsert.py",
    "tests/test_grafana_dashboard_pullback.py",
    "tests/test_guard_corpus_tracked_files.py",
    "tests/test_hashlib_weak_hash_ledger.py",
    "tests/test_hmac_auth_zero_surface.py",
    "tests/test_http_client_discipline.py",
    "tests/test_http_post_egress_ledger.py",
    "tests/test_httpx_timeout_invariant.py",
    "tests/test_iloc_minus_one_guard_discipline.py",
    "tests/test_library_discipline_zero_surface.py",
    "tests/test_lint_debt_no_regression.py",
    "tests/test_live_overlay_alert_rules_publish_workflow.py",
    "tests/test_live_overlay_dashboard_contract.py",
    "tests/test_live_overlay_dashboard_publish_workflow.py",
    "tests/test_library_field_audit.py",
    "tests/test_loopback_and_baseimage_pin.py",
    "tests/test_lru_cache_maxsize_discipline.py",
    "tests/test_mkdir_makedirs_exist_ok_invariant.py",
    "tests/test_module_test_coverage_pin.py",
    "tests/test_degraded_status_alert_coverage.py",
    "tests/test_github_workflow_expected_presence.py",
    "tests/test_monitoring_metric_alert_coverage.py",
    "tests/test_mutable_defaults_and_loads_pins.py",
    "tests/test_nonlocal_budget.py",
    "tests/test_noqa_budget.py",
    "tests/test_noqa_suppression_ledger.py",
    "tests/test_os_environ_mutation_ledger.py",
    "tests/test_os_system_input_assert_zero_surface.py",
    "tests/test_os_unlink_remove_ledger.py",
    "tests/test_outcome_horizons.py",
    "tests/test_path_text_io_encoding_ledger.py",
    "tests/test_pickle_read_and_eval_zero_surface.py",
    "tests/test_pickle_write_and_abs_pathjoin_zero_surface.py",
    "tests/test_pine_alert_bar_close_gate.py",
    "tests/test_pine_alertcondition_and_declaration_pin.py",
    "tests/test_pine_decision_logic_deep_review_regressions.py",
    "tests/test_pine_context_library_contract.py",
    "tests/test_pine_engine_fill_boundary.py",
    "tests/test_pine_handlib_publisher_inventory.py",
    "tests/test_pine_library_import_permissions.py",
    "tests/test_pine_surface_registry.py",
    "tests/test_pine_request_security_htf_pin.py",
    "tests/test_pine_request_security_per_file_budget.py",
    "tests/test_pine_var_budget_pin.py",
    "tests/test_point_in_time_integrity.py",
    "tests/test_pre_a0_alert_rules.py",
    "tests/test_pre_a0_grafana_dashboard.py",
    "tests/test_prod_print_ledger.py",
    "tests/test_publish_overlay_dashboard.py",
    "tests/test_pytest_marker_bucket_discipline.py",
    "tests/test_pytest_skip_budget.py",
    "tests/test_random_tempfile_ledger_pin.py",
    "tests/test_realtime_signals_sister_ledger_guardrail.py",
    "tests/test_requirements_discipline_pin.py",
    "tests/test_run_edge_pipeline.py",
    "tests/test_schema_version_manifest_alignment.py",
    "tests/test_signals_dashboard_contract.py",
    "tests/test_silent_error_swallow_pin.py",
    "tests/test_silent_security_and_boundary_bundle.py",
    "tests/test_six_zero_tripwires_bundle.py",
    "tests/test_smc_bus_v2_freeze.py",
    "tests/test_smc_context_golden.py",
    "tests/test_smc_htf_context_r5_spike.py",
    "tests/test_smc_fast_pr_gates_workflow.py",
    "tests/test_smc_library_refresh_workflow.py",
    "tests/test_smc_live_overlay_metrics.py",
    "tests/test_smc_product_cut_manifest.py",
    "tests/test_socket_bind_loopback_pin.py",
    "tests/test_subprocess_run_check_invariant.py",
    "tests/test_subprocess_shell_injection_pin.py",
    "tests/test_subprocess_spawn_sites_ledger.py",
    "tests/test_subprocess_timeout_discipline.py",
    "tests/test_sys_exit_ledger_pin.py",
    "tests/test_sys_path_mutation_ledger.py",
    "tests/test_tempfile_namedtemp_delete_kwarg_invariant.py",
    "tests/test_threading_thread_daemon_invariant.py",
    "tests/test_time_sleep_budget.py",
    "tests/test_tls_jwt_verification_zero_surface.py",
    "tests/test_to_datetime_utc_discipline.py",
    "tests/test_type_ignore_budget.py",
    "tests/test_update_overlay_dashboard.py",
    "tests/test_urllib_urlopen_ledger.py",
    "tests/test_verdict_panel.py",
    "tests/test_warnings_simplefilter_ledger.py",
    "tests/test_weak_hash_pin.py",
    "tests/test_weak_hash_usedforsecurity_pin.py",
    "tests/test_while_true_termination_ledger.py",
    "tests/test_workflow_auth_pattern.py",
    "tests/test_workflow_concurrency_cron_no_cancel.py",
    "tests/test_workflow_continue_on_error_inventory.py",
    "tests/test_workflow_continue_on_error_semantics.py",
    "tests/test_workflow_freshness_monitor_workflow.py",
    "tests/test_workflow_invoked_scripts_importable.py",
    "tests/test_workflow_issue_labels_exist.py",
    "tests/test_workflow_no_fake_push_success.py",
    "tests/test_workflow_orphan_inventory.py",
    "tests/test_workflow_permissions_present.py",
    # 2026-08-01: tv-save-consumer-source pushes repository sources onto the
    # live account on schedule, on dispatch, and chained after a library
    # refresh -- none of them a pull request. #4286 guards the diff; this guards
    # the dispatch, by holding back sources the registered R1 evidence no
    # longer attests. A guard on that path may not first run post-merge.
    "tests/test_tv_attested_source_holdback.py",
    # 2026-08-01: the live-window posture vocabulary is closed, but the guard
    # ran only in heavy CI on main push. #4281 invented the near-synonym
    # "manual-dispatch-only", merged green, and turned main red -- a posture
    # guard that cannot block the pull request that breaks it is a report, not
    # a gate. The marker decides whether a workflow may touch a live account,
    # so it belongs on the required path.
    "tests/test_workflow_live_window_posture.py",
    # 2026-08-01: a workflow that uses $SMC_PYTHON_BIN without setting it
    # exits 127 on its first heredoc step. workflow_dispatch-only workflows
    # are never exercised by CI, so the break is invisible until someone
    # needs the workflow (smc-r4-context-readback, run 30683157375).
    "tests/test_workflow_python_bin_resolved.py",
    # 2026-08-01: contract for smc-r4-context-readback, which can drive a live
    # TradingView account at mutating execution mode. Dispatch-only, a readonly
    # default and the shared session concurrency group are the properties that
    # keep it safe, so the guard has to gate rather than merely exist.
    "tests/test_smc_r4_context_readback_workflow.py",
    # 2026-08-01: pins the shared TradingView session group. The partition it
    # guards is the whole point — an unguarded one drifts back to per-workflow
    # groups exactly the way the original "single shared external target"
    # comment did, stating a guarantee nothing enforced.
    "tests/test_tradingview_session_concurrency.py",
    "tests/test_workflow_python_unbuffered.py",
    "tests/test_workflow_pythonpath_for_direct_invoke.py",
    "tests/test_workflow_runner_pinned.py",
    "tests/test_workflow_set_plus_e_inventory.py",
    "tests/test_workflow_tv_save_consumer_source_contract.py",
    "tests/test_workflow_upload_artifact_uniform_version.py",
    "tests/test_yaml_xml_zero_surface.py",
)


def _strip_comments(text: str) -> str:
    """Drop YAML / shell comment content from each line.

    A ``#`` at line start or preceded by whitespace begins a comment in
    both YAML and POSIX shell. Removing that tail prevents a test name
    that only appears in a comment — or in a commented-out pytest line —
    from counting as a live reference in the drift-guard step.
    """
    cleaned: list[str] = []
    for line in text.splitlines():
        stripped = re.sub(r"(^|\s)#.*$", "", line)
        cleaned.append(stripped)
    return "\n".join(cleaned)


def _drift_guard_step_text() -> str:
    """Return only the 'Run pin / ledger drift guard' step body.

    Scoping to the step (rather than the whole YAML) prevents a false
    pass where a test name appears only in a comment elsewhere in the
    workflow instead of in the required tripwire pytest invocation.
    Comment content is stripped so a test commented out *inside* the
    step is not mistaken for a live reference.
    """
    text = FAST_GATES_WORKFLOW.read_text(encoding="utf-8")
    start = text.index("Run pin / ledger drift guard")
    end = text.index("Run fast SMC integration tests", start)
    return _strip_comments(text[start:end])


def test_silent_skip_class_tests_are_pinned_in_fast_gates() -> None:
    workflow_text = FAST_GATES_WORKFLOW.read_text(encoding="utf-8")

    missing = [t for t in REQUIRED_PINNED_TESTS if t not in workflow_text]
    assert not missing, (
        "smc-fast-pr-gates.yml dropped tests from the silent-skip tripwire pin. "
        "Branch-protection only requires fast-gates, so any test that leaves this "
        "workflow loses its ability to block merge.\n\n"
        f"Missing pins: {missing}\n\n"
        "Re-add them to the 'Run pin / ledger drift guard' step's pytest invocation "
        "or document explicitly why coverage moves elsewhere AND update "
        "this guard."
    )


def test_full_tripwire_roster_pinned_in_fast_gates() -> None:
    """Every required-path tripwire must stay in the drift-guard step.

    Branch protection requires only ``fast-gates``; a tripwire dropped
    from this step can no longer block merge. Freezing the full roster
    means a silent removal fails the required check immediately.
    """
    step = _drift_guard_step_text()
    referenced = set(re.findall(r"tests/test_[A-Za-z0-9_]+\.py", step))

    missing = sorted(t for t in FULL_REQUIRED_PATH_TRIPWIRES if t not in referenced)
    assert not missing, (
        "smc-fast-pr-gates.yml 'Run pin / ledger drift guard' step dropped "
        "required-path tripwire(s). Branch protection only requires fast-gates, "
        "so each missing test can no longer block merge — re-opening the "
        "'guard fell off the required path' regression class (PR #2421).\n\n"
        f"Missing from the step: {missing}\n\n"
        "Re-add them to the step's pytest invocation, or — if a tripwire is "
        "being intentionally retired — remove it from "
        "FULL_REQUIRED_PATH_TRIPWIRES in this file in the same PR (audit trail)."
    )

    extra = sorted(t for t in referenced if t not in FULL_REQUIRED_PATH_TRIPWIRES)
    assert not extra, (
        "smc-fast-pr-gates.yml 'Run pin / ledger drift guard' step references "
        "tripwire(s) absent from FULL_REQUIRED_PATH_TRIPWIRES. Without this "
        "reverse check the roster is not a complete source of truth: a newly "
        "added required-path tripwire could later be silently removed and no "
        "guard would notice.\n\n"
        f"Referenced but unregistered: {extra}\n\n"
        "Add them to FULL_REQUIRED_PATH_TRIPWIRES in this file (same PR) so the "
        "complete roster stays frozen in both directions."
    )


# ---------------------------------------------------------------------------
# Derived-roster guard (2026-07-15)
# ---------------------------------------------------------------------------
# The roster checks above freeze the step against FULL_REQUIRED_PATH_TRIPWIRES
# in both directions, but both sides are hand-maintained — so shrinking BOTH
# together is, by design, the "intentional retirement" escape hatch. #3670
# exercised it by accident: a rebase artefact in a PR about a sweep threshold
# silently dropped four security ledgers (os.kill, fcntl.flock, globals(),
# @lru_cache) from the step, the roster AND the fast inventory. Every guard
# above stayed green because the removal was *consistent*, and the PR merged on
# auto-merge ~30 min after #3669 put them there. Nothing noticed.
#
# This guard removes the hand-maintained list from the loop: it derives what
# MUST be gated from the source itself — a test that freezes (file, lineno)
# tuples is a line-pinned ledger, and a line-pinned ledger that is not on the
# required path drifts red on main unnoticed (proven three times over for the
# hmac ledger: 2026-07-09, -07-13, -07-15). Retiring one now takes an explicit,
# reviewable entry below rather than a silent deletion.


# Ledgers deliberately kept OFF the required path. Empty by design: an entry
# here is a conscious, reviewable decision with a justification, not a
# side effect of a rebase.
_LEDGERS_INTENTIONALLY_UNGATED: frozenset[str] = frozenset()


def _freezes_line_pins(path: Path) -> bool:
    """True when the module freezes ``(file, lineno, ...)`` tuples at module level.

    That shape is the structural signature of a line-pinned ledger: it pins a
    call site by exact line, so ANY edit above that site shifts it and turns the
    test red. Naming is not a usable signal here (>300 test files match
    ledger/pin/budget-ish names, almost all unrelated).
    """
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError):  # pragma: no cover - unparseable/unreadable
        return False
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        if not isinstance(node.value, (ast.Set, ast.Tuple, ast.List)):
            continue
        for elt in getattr(node.value, "elts", []):
            if not isinstance(elt, ast.Tuple) or len(elt.elts) < 2:
                continue
            path_node, lineno_node = elt.elts[0], elt.elts[1]
            if (
                isinstance(path_node, ast.Constant)
                and isinstance(path_node.value, str)
                and isinstance(lineno_node, ast.Constant)
                and isinstance(lineno_node.value, int)
                and not isinstance(lineno_node.value, bool)
                and lineno_node.value > 0
            ):
                return True
    return False


def _is_path_like(value: str) -> bool:
    return value.endswith((".py", ".pine", ".txt", ".toml", ".yml", ".yaml")) or "/" in value


def _freezes_per_file_counts(path: Path) -> bool:
    """True when the module freezes a ``{"some/file.py": <int>}`` map.

    The second ledger shape (2026-07-15). A count ledger does not carry line
    numbers, so ``_freezes_line_pins`` cannot see it — but it drifts by the same
    mechanism whenever a suppression, print, division or dependency line is
    added, and being ungated it merges green just the same.

    Requiring EVERY key to be path-like is what makes this precise: fixtures
    also map strings to ints (regime names, field counts, sample payloads), and
    a looser shape reported ~50% false positives. On the current tree this
    signature finds 16 modules and no fixtures.
    """
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError):  # pragma: no cover - unparseable/unreadable
        return False
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        if not isinstance(node.value, ast.Dict) or not node.value.keys:
            continue
        pairs = [
            (key, val)
            for key, val in zip(node.value.keys, node.value.values)
            if isinstance(key, ast.Constant)
            and isinstance(key.value, str)
            and isinstance(val, ast.Constant)
            and isinstance(val.value, int)
            and not isinstance(val.value, bool)
        ]
        if pairs and all(_is_path_like(key.value) for key, _ in pairs):
            return True
    return False


def _pinned_ledgers() -> set[str]:
    """Every line-pinned, count-pinned or registry-backed ledger, from source."""
    found: set[str] = set()
    for path in sorted((ROOT / "tests").glob("test_*.py")):
        if _freezes_line_pins(path) or _freezes_per_file_counts(path):
            found.add(f"tests/{path.name}")
            continue
        # pin_registry-backed ledgers keep their pins in pin_registry.toml
        # instead of in the test body, so the AST shapes above cannot see them.
        if "pin_registry" in path.read_text(encoding="utf-8", errors="replace"):
            found.add(f"tests/{path.name}")
    return found


def test_every_pinned_ledger_is_on_the_required_path() -> None:
    """A pinned ledger that is not gated drifts red on main unnoticed.

    Derived, not hand-maintained: the required set comes from the source, so a
    PR cannot retire a ledger by deleting it from the step and the roster
    together (the hole #3670 fell through). The ledger still exists in tests/,
    so it must still be gated — or be listed above with a reason.

    Covers both ledger shapes: line-pinned ``(file, lineno)`` tuples and
    count-pinned ``{"file": n}`` maps. The two differ in how OFTEN they drift —
    a line pin shifts on any edit above the site, a count only moves when a
    suppression is actually added — but not in what an ungated one costs: the
    addition the pin exists to force a review of merges green either way.
    """
    ledgers = _pinned_ledgers()
    # Sanity: discovery actually found ledgers, so a rename/refactor cannot make
    # this test vacuously pass with an empty set.
    assert len(ledgers) >= 15, (
        f"ledger discovery found only {len(ledgers)} — the AST signature or the "
        "tests/ layout changed and this guard is no longer measuring anything"
    )

    step = _drift_guard_step_text()
    referenced = set(re.findall(r"tests/test_[A-Za-z0-9_]+\.py", step))
    ungated = sorted(ledgers - referenced - _LEDGERS_INTENTIONALLY_UNGATED)
    assert not ungated, (
        "pinned ledger(s) are not on the required path. fast-gates is the "
        "only merge-gating job, so these pins cannot block a merge: a drifted "
        "pin — or a NEW allow-listed call site they exist to force a review of — "
        "merges green and accumulates red on main unnoticed (the hmac ledger did "
        "this three times: 2026-07-09, -07-13, -07-15).\n\n"
        f"Ungated: {ungated}\n\n"
        "Add each to the 'Run pin / ledger drift guard' step in "
        "smc-fast-pr-gates.yml (plus FULL_REQUIRED_PATH_TRIPWIRES here and "
        "FAST_TEST_FILES in tests/_fast_inventory.py — the meta-guards will name "
        "them), or add it to _LEDGERS_INTENTIONALLY_UNGATED with a justification."
    )


# ---------------------------------------------------------------------------
# Derived zero-surface guard (2026-07-15)
# ---------------------------------------------------------------------------
# The guard above derives its required set from a ledger's *structure*: line
# pins (#3672) or per-file counts (#3680). Both signatures need an allow-list to
# exist. That is exactly what the other half of the security surface does not
# have — a zero-surface guard asserts a construct does not appear at all, so
# there is nothing to freeze and nothing for those signatures to match.
#
# Their failure mode is the inverse, and quieter. Nothing drifts, so nothing
# goes red — instead a NEW violation merges green and only fails afterwards in
# the non-required `validate` job. 10 were off the required path when this
# landed (pickle read/eval, pickle write, exec/mktemp/shell=True, os.system,
# dangerous builtins, dynamic exec+pickle, TLS/JWT verification, yaml/xml,
# datetime-tz, library-discipline), and one was ALREADY red on main:
# agent.py's asyncio.run merged green in #3499 because the rule forbidding it
# has never run on the required path. The failure mode had already arrived.
#
# Naming is a usable signal *here*, where #3672 rejected it for ledgers, and the
# difference is the hit rate: `*_zero_surface*` matches 17 files and every one
# is a security guard, whereas ledger/pin/budget-ish names match 300+ files that
# are mostly unrelated.

# Zero-surface guards deliberately kept OFF the required path. Empty by design:
# an entry here is a conscious, reviewable decision with a justification, not a
# side effect of a rebase.
_ZERO_SURFACE_INTENTIONALLY_UNGATED: frozenset[str] = frozenset()


def _zero_surface_guards() -> set[str]:
    """Every zero-surface security guard, discovered from the tests/ layout."""
    return {
        f"tests/{path.name}"
        for path in sorted((ROOT / "tests").glob("test_*zero_surface*.py"))
    }


def test_every_zero_surface_guard_is_on_the_required_path() -> None:
    """An ungated zero-surface guard lets a new violation merge green.

    Same contract as the pinned-ledger guard above, for the surface its
    structural signatures cannot see. Derived from the tests/ layout, so a new
    zero-surface guard is required-by-default and cannot be born ungated —
    which is how all of them came to be ungated in the first place.
    """
    guards = _zero_surface_guards()
    # Sanity: discovery actually found guards, so a rename or a layout change
    # cannot make this test vacuously pass on an empty set.
    assert len(guards) >= 15, (
        f"zero-surface discovery found only {len(guards)} — the naming "
        "convention or the tests/ layout changed and this guard is no longer "
        "measuring anything"
    )

    step = _drift_guard_step_text()
    referenced = set(re.findall(r"tests/test_[A-Za-z0-9_]+\.py", step))
    ungated = sorted(guards - referenced - _ZERO_SURFACE_INTENTIONALLY_UNGATED)
    assert not ungated, (
        "zero-surface guard(s) are not on the required path. fast-gates is the "
        "only merge-gating job, so these cannot block a merge: a NEW pickle "
        "load, eval, shell=True, os.system or unverified-TLS call site merges "
        "green and is only caught afterwards by `validate`, if anyone reads it. "
        "agent.py's asyncio.run reached main exactly this way (#3499).\n\n"
        f"Ungated: {ungated}\n\n"
        "Add each to the 'Run pin / ledger drift guard' step in "
        "smc-fast-pr-gates.yml (plus FULL_REQUIRED_PATH_TRIPWIRES here and "
        "FAST_TEST_FILES in tests/_fast_inventory.py — the meta-guards will name "
        "them), or add it to _ZERO_SURFACE_INTENTIONALLY_UNGATED with a "
        "justification."
    )


# ---------------------------------------------------------------------------
# Derived repo-wide-guard rule (2026-07-15)
# ---------------------------------------------------------------------------
# The three rules above each key off what a guard *freezes*: line pins (#3672),
# per-file counts (#3680), or a `*_zero_surface*` filename (#3685). A guard that
# instead checks a *property* of a call site — "this httpx client passes a
# timeout", "this NamedTemporaryFile passes delete=" — freezes nothing and is
# named nothing in particular, so all three miss it.
#
# `tests/_guard_corpus` is the signal that survives that: importing the shared
# repo-wide AST corpus is what a first-party source guard *does*, structurally,
# whatever it then asserts and whatever it is called. 27 of its 60 importers
# were off the required path when this landed.
#
# Exceptions below are per-surface, not per-name: each is a guard whose surface a
# gated guard already reads. They were checked one at a time, not inferred from
# similar filenames.
_GUARD_CORPUS_INTENTIONALLY_UNGATED: frozenset[str] = frozenset(
    {
        # shell=True / os.system / os.popen / eval / exec / pickle. Every leg is
        # already read on the required path: shell=True by
        # test_subprocess_shell_injection_pin (test_no_shell_true_anywhere), and
        # os.system + os.popen + eval + exec + pickle by the zero-surface set
        # #3685 gated. These four bundles predate that set and restate it.
        "tests/test_dangerous_call_tripwires.py",
        "tests/test_dynamic_exec_and_shell_tripwires.py",
        "tests/test_serialization_and_shell_tripwires.py",
        "tests/test_shell_true_tripwire.py",
        # assert-in-prod and encoding-less open(). The gated
        # test_assert_and_open_encoding_pin freezes a PER-FILE count for both, so
        # a new violation moves a count and fails there. These two assert the
        # rule directly — same surface, already covered.
        "tests/test_no_prod_assert_pin.py",
        "tests/test_open_encoding_discipline.py",
        # Not a production surface: a pytest-xdist parametrize determinism pin.
        # It guards the test harness.
        "tests/test_pytest_xdist_parametrize_determinism.py",
        # test_guard_corpus_tracked_files was exempted here on the same grounds
        # ("the corpus's own tracked-file self-check", #3690). That was true of
        # the file as it stood. It no longer is: the file now also pins
        # iter_production_py_files' floor — the thing that stops a collapsed
        # corpus from being certified as scanned. Leaving it exempt would put the
        # floor's own proof on no lane, so it is gated instead.
    }
)


def _guard_corpus_users() -> set[str]:
    """Every test importing the shared repo-wide AST corpus."""
    return {
        f"tests/{path.name}"
        for path in sorted((ROOT / "tests").glob("test_*.py"))
        if "_guard_corpus" in path.read_text(encoding="utf-8", errors="replace")
    }


def test_every_guard_corpus_user_is_on_the_required_path() -> None:
    """A repo-wide source guard that is not gated cannot block the merge it exists for.

    Keys off the import, not the name or the frozen shape, so it also covers the
    guards that check a *property* rather than freezing a location — the half the
    three rules above cannot see.
    """
    users = _guard_corpus_users()
    # Sanity: discovery actually found guards, so a corpus rename cannot make
    # this test vacuously pass on an empty set.
    assert len(users) >= 40, (
        f"guard-corpus discovery found only {len(users)} importers — the corpus "
        "module moved or the tests/ layout changed, and this guard is no longer "
        "measuring anything"
    )

    step = _drift_guard_step_text()
    referenced = set(re.findall(r"tests/test_[A-Za-z0-9_]+\.py", step))
    ungated = sorted(users - referenced - _GUARD_CORPUS_INTENTIONALLY_UNGATED)
    assert not ungated, (
        "repo-wide source guard(s) are not on the required path. fast-gates is "
        "the only merge-gating job, so these cannot block a merge: the property "
        "they check — a timeout passed, a kwarg set, a secret-shaped file kept "
        "out of git — is enforced only afterwards by `validate`, if anyone reads "
        "it.\n\n"
        f"Ungated: {ungated}\n\n"
        "Add each to the 'Run pin / ledger drift guard' step in "
        "smc-fast-pr-gates.yml (plus FULL_REQUIRED_PATH_TRIPWIRES here and "
        "FAST_TEST_FILES in tests/_fast_inventory.py — the meta-guards will name "
        "them), or add it to _GUARD_CORPUS_INTENTIONALLY_UNGATED naming the gated "
        "guard that already reads its surface."
    )


# ---------------------------------------------------------------------------
# Sibling corpora (2026-07-15)
# ---------------------------------------------------------------------------
# The rule above keys off `tests/_guard_corpus` — the shared PYTHON AST corpus.
# Two sibling corpora carry repo-wide guards it cannot see, because their
# surface is not Python source:
#
#   tests/_workflow_yaml  — the .github/workflows corpus
#   tests/_pine_text      — the Pine source corpus
#
# Same argument as _guard_corpus, same failure if ungated: nothing drifts, so
# nothing turns red; a NEW violation just merges green. That is how
# test_gha_action_allowlist — the SHA-pinning defence against GitHub Action
# tag-mutation — sat off the required path indefinitely. It is on it now, and it
# was refactored onto the shared corpus so this rule DERIVES it instead of
# trusting a hand-maintained entry (its private file-walk returned the identical
# 62 files; verified before the swap).
#
# Membership is decided by a real IMPORT, parsed from the AST — not by the
# substring test the _guard_corpus rule uses. On this tree the substring form
# over-reports these corpora badly (8 hits vs 3 real importers for
# _workflow_yaml, 3 vs 2 for _pine_text): a docstring cross-reference or a
# comment naming the helper is not a use of it, and gating on a mention would
# drag single-workflow contract pins and a shard planner's unit tests onto the
# required path.

_SIBLING_CORPORA: tuple[str, ...] = ("_workflow_yaml", "_pine_text")

# Empty by design: an entry is a reviewed decision with a justification naming
# the gated guard that already reads the surface, not a rebase artefact.
_SIBLING_CORPUS_INTENTIONALLY_UNGATED: frozenset[str] = frozenset()


def _imports_module(path: Path, module: str) -> bool:
    """True only when ``module`` is genuinely imported by ``path``."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, SyntaxError):  # pragma: no cover - unparseable/unreadable
        return False
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and module in node.module:
            return True
        if isinstance(node, ast.Import) and any(
            module in alias.name for alias in node.names
        ):
            return True
    return False


def _sibling_corpus_users() -> set[str]:
    """Every test that genuinely imports a workflow-YAML or Pine corpus."""
    return {
        f"tests/{path.name}"
        for path in sorted((ROOT / "tests").glob("test_*.py"))
        if any(_imports_module(path, corpus) for corpus in _SIBLING_CORPORA)
    }


def test_every_sibling_corpus_user_is_on_the_required_path() -> None:
    """Workflow-YAML and Pine guards must gate too, not just Python-source ones.

    Their surface is YAML and Pine, so neither the frozen-shape rules nor the
    _guard_corpus import can see them — and an ungated one fails the same quiet
    way: a new violation merges green and surfaces post-merge in `validate`, if
    anyone reads it.
    """
    users = _sibling_corpus_users()
    # Sanity: these corpora are small, but a rename must not empty the set and
    # make this rule pass on nothing.
    assert len(users) >= 4, (
        f"sibling-corpus discovery found only {len(users)} importers — a corpus "
        "module moved or the tests/ layout changed, and this rule is no longer "
        "measuring anything"
    )

    step = _drift_guard_step_text()
    referenced = set(re.findall(r"tests/test_[A-Za-z0-9_]+\.py", step))
    ungated = sorted(users - referenced - _SIBLING_CORPUS_INTENTIONALLY_UNGATED)
    assert not ungated, (
        "workflow-YAML / Pine guard(s) are not on the required path. fast-gates "
        "is the only merge-gating job, so the rule they enforce — an action "
        "SHA-pinned against tag mutation, an alertcondition gated to bar close — "
        "cannot block the merge that breaks it.\n\n"
        f"Ungated: {ungated}\n\n"
        "Add each to the 'Run pin / ledger drift guard' step in "
        "smc-fast-pr-gates.yml (plus FULL_REQUIRED_PATH_TRIPWIRES and "
        "FAST_TEST_FILES — the meta-guards will name them), or add it to "
        "_SIBLING_CORPUS_INTENTIONALLY_UNGATED with a justification."
    )


# ---------------------------------------------------------------------------
# Derived monitoring-artifact rule (2026-07-23)
# ---------------------------------------------------------------------------
# The rules above key off what a guard freezes (line pins, per-file counts), what
# it is named (`*_zero_surface*`), or which corpus it imports. A test that asserts
# the *deployed observability contract* — that a Grafana panel queries a metric
# the exposition actually emits, that an alert rule targets a series that exists —
# matches none of those: it freezes nothing, is named nothing in particular, and
# imports no corpus. It just reads `dashboard*.json` / `alert-rules*.yaml`.
#
# Reading a shipped monitoring artifact is the structural signal that survives.
#
# This gap is not hypothetical and not new. The drift-guard step already carries
# a comment explaining that test_monitoring_metric_alert_coverage.py "until #3665
# ran in no PR lane at all ... It only ran post-merge on main push." That was one
# instance; 13 more had the same shape when this landed. PR #3919 is what surfaced
# it: it pointed a Railway panel at `live_overlay_railway_service_memory_gb`, a
# metric the exposition does not emit under that name, and every PR check went
# green because the only test that checks it ran on no PR lane.
_MONITORING_ARTIFACT_SIGNAL = re.compile(r"dashboard[-\w]*\.json|alert-rules[-\w]*\.yaml")

# Per-surface exceptions, each justified. Empty: every monitoring-artifact guard
# found at introduction was cheap enough to gate (373 tests, ~28 s serial).
_MONITORING_ARTIFACT_INTENTIONALLY_UNGATED: frozenset[str] = frozenset()


def _monitoring_artifact_guards() -> set[str]:
    """Every test that reads a shipped Grafana dashboard or alert-rules file."""
    return {
        f"tests/{path.name}"
        for path in sorted((ROOT / "tests").glob("test_*.py"))
        if _MONITORING_ARTIFACT_SIGNAL.search(
            path.read_text(encoding="utf-8", errors="replace")
        )
    }


def test_every_monitoring_artifact_guard_is_on_the_required_path() -> None:
    """An ungated dashboard/alert guard lets broken observability merge green.

    Monitoring breakage is uniquely quiet: nothing crashes, no user sees an
    error, and the only symptom is a panel that plots nothing or an alert that
    can never fire — discovered during the next incident, which is exactly when
    the dashboard is needed. Post-merge `validate` catches it in principle, but
    only if someone reads a run that no longer blocks anything.
    """
    guards = _monitoring_artifact_guards()
    # Sanity: discovery must not silently collapse to an empty set if the
    # artifacts are renamed or moved.
    assert len(guards) >= 10, (
        f"monitoring-artifact discovery found only {len(guards)} guards — the "
        "dashboard/alert-rules naming or the tests/ layout changed, and this "
        "rule is no longer measuring anything"
    )

    step = _drift_guard_step_text()
    referenced = set(re.findall(r"tests/test_[A-Za-z0-9_]+\.py", step))
    ungated = sorted(guards - referenced - _MONITORING_ARTIFACT_INTENTIONALLY_UNGATED)
    assert not ungated, (
        "monitoring-artifact guard(s) are not on the required path. fast-gates "
        "is the only merge-gating job, so a PR that points a panel at a metric "
        "nothing emits, or drops the series an alert rule fires on, merges "
        "green — and the dashboard is only found broken when it is next "
        "needed.\n\n"
        f"Ungated: {ungated}\n\n"
        "Add each to the 'Run pin / ledger drift guard' step in "
        "smc-fast-pr-gates.yml (plus FULL_REQUIRED_PATH_TRIPWIRES and "
        "FAST_TEST_FILES — the meta-guards will name them), or add it to "
        "_MONITORING_ARTIFACT_INTENTIONALLY_UNGATED with a justification."
    )


# --------------------------------------------------------------------------- #
# TypeScript lane (TradingView automation)
#
# The meta-guards above cover the PYTHON merge gate (fast-gates). They are
# blind to the TypeScript lane, which is a separate workflow
# (tv-onboarding-packages.yml) with no auto-discovery: it runs a hand-picked
# `npx tsx --test <file>` list. A TS pin can therefore exist and run NOWHERE —
# exactly what happened to tv_preflight_add_to_chart_floor.test.ts (#3967): it
# pinned the 90s add-to-chart floor but was in no run step and excluded by the
# workflow's own paths filter, so a follow-up removing the floor would have
# merged green and re-opened the 45s-timeout release-gate failure.
#
# This freezes the current TS state: every *.test.ts must be either RUN by the
# workflow or on the exempt set below. A new TS test then forces a conscious
# choice (wire it, or exempt it with a reason) instead of silently running
# nowhere. The exempt set is exactly the tests whose import graph reaches
# `playwright` (via lib/tv_shared.ts) — verified by running each: the 13 exempt
# fail fast with ERR_MODULE_NOT_FOUND 'playwright' locally and need a pinned
# browser (the local `tv:test` lane, which hangs without it), so demanding they
# run in this packaging workflow would break it. The hermetic source-scan /
# pure-logic pins (no playwright import) all gate: 13 run, 13 exempt.
TV_ONBOARDING_WORKFLOW = ROOT / ".github" / "workflows" / "tv-onboarding-packages.yml"
_TV_TEST_DIR = ROOT / "automation" / "tradingview" / "tests"

#: TS tests that legitimately do not run in tv-onboarding-packages.yml — the
#: 13 that import `playwright` transitively and need a pinned browser. Adding a
#: member is a deliberate edit (audit trail), the same contract as the
#: *_INTENTIONALLY_UNGATED sets above. Reducing it means a browserless test was
#: wired into CI (the 10 hermetic pins were, 2026-07-24).
_TS_TESTS_INTENTIONALLY_UNGATED: frozenset[str] = frozenset(
    {
        "tv_auth_probe_precedence.test.ts",
        "tv_binding_repair.test.ts",
        "tv_launch_options.test.ts",
        "tv_pine_editor_close.test.ts",
        # tv_preflight_add_to_chart_floor.test.ts is NOT here — it is wired into
        # the run step (#3970) and gates.
        "tv_preflight_identity_assertion.test.ts",
        "tv_producer_refresh_layouts.test.ts",
        "tv_publish_draw_library.test.ts",
        "tv_publish_micro_library.test.ts",
        "tv_publish_openprep_panel.test.ts",
        "tv_publish_overlay_library.test.ts",
        "tv_read_editor_content.test.ts",
        "tv_save_consumer_source.test.ts",
        "tv_shared.test.ts",
    }
)


def _tv_workflow_text() -> str:
    return TV_ONBOARDING_WORKFLOW.read_text(encoding="utf-8")


def _tv_run_step_tests() -> set[str]:
    """Basenames of *.test.ts invoked by an `npx tsx --test` line."""
    text = _tv_workflow_text()
    tests: set[str] = set()
    for line in text.splitlines():
        if "tsx --test" not in line:
            continue
        tests.update(re.findall(r"([A-Za-z0-9_./-]+\.test\.ts)", line))
    return {Path(t).name for t in tests}


def _tv_paths_filter_tests() -> set[str]:
    """Basenames of *.test.ts listed under any `paths:` filter."""
    return {Path(t).name for t in re.findall(r"([A-Za-z0-9_./-]+\.test\.ts)", _tv_workflow_text())} - _tv_run_step_tests() | {
        Path(t).name
        for t in re.findall(r'-\s*"([^"]+\.test\.ts)"', _tv_workflow_text())
    }


def _all_ts_tests() -> set[str]:
    return {p.name for p in _TV_TEST_DIR.glob("*.test.ts")}


def test_every_ts_test_is_gated_or_exempt() -> None:
    """A new TypeScript test must run in CI or be a conscious exemption.

    The Python meta-guards do not see the TS lane. tv-onboarding-packages.yml
    has no test discovery — it runs an explicit `npx tsx --test` list — so a TS
    pin added without touching that list runs nowhere and gates nothing
    (tv_preflight_add_to_chart_floor.test.ts, #3967). Freezing the set makes
    every new *.test.ts a deliberate wire-or-exempt decision.
    """
    all_ts = _all_ts_tests()
    assert len(all_ts) >= 20, (
        f"TS test discovery found only {len(all_ts)} files — the tests/ layout "
        "moved and this rule is no longer measuring anything"
    )
    gated = _tv_run_step_tests()
    ungated = sorted(all_ts - gated - _TS_TESTS_INTENTIONALLY_UNGATED)
    assert not ungated, (
        "TypeScript test(s) run in no workflow. tv-onboarding-packages.yml is "
        "the only TS runner and has no discovery, so these gate nothing and a "
        "PR breaking them merges green.\n\n"
        f"Ungated: {ungated}\n\n"
        "Add each to an `npx tsx --test` step AND the push+pull_request "
        "`paths:` filters in tv-onboarding-packages.yml (plus the source it "
        "scans, so a change there triggers the run), or add it to "
        "_TS_TESTS_INTENTIONALLY_UNGATED with a reason."
    )


def test_exempt_ts_tests_still_exist() -> None:
    """A stale exemption silently shrinks the guarded set — flag renamed/removed."""
    missing = sorted(_TS_TESTS_INTENTIONALLY_UNGATED - _all_ts_tests())
    assert not missing, (
        "_TS_TESTS_INTENTIONALLY_UNGATED names TS test(s) that no longer exist "
        f"(renamed/removed): {missing}. Drop them so the exemption set stays a "
        "true mirror of the tests/ dir."
    )


def test_gated_ts_tests_trigger_their_own_workflow() -> None:
    """A TS test that runs but is not in `paths:` does not trigger on its change.

    tv_preflight_add_to_chart_floor needed BOTH a run step and a paths entry
    (#3970): without the paths entry, editing the test — or the source it
    guards — would not start the workflow, so the pin could not fire on its own
    regression. Every run test must therefore also be in the paths filter.
    """
    gated = _tv_run_step_tests()
    in_paths = _tv_paths_filter_tests()
    missing = sorted(gated - in_paths)
    assert not missing, (
        "TS test(s) run in tv-onboarding-packages.yml but are absent from its "
        f"`paths:` filter: {missing}. A change to the test then does not trigger "
        "the workflow. Add each to both the push and pull_request `paths:` lists."
    )
