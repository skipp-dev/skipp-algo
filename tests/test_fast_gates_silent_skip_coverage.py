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
# Snapshot taken 2026-06-02 from main after the EV#6/EV#7 edge-pipeline
# merge (65 tests; +10 family/edge tripwires referenced by the drift guard).
FULL_REQUIRED_PATH_TRIPWIRES: tuple[str, ...] = (
    "tests/test_assert_and_open_encoding_pin.py",
    "tests/test_assert_in_production_budget.py",
    "tests/test_atexit_register_zero_surface.py",
    "tests/test_atomic_write_call_sites.py",
    "tests/test_bare_type_ignore_ledger.py",
    "tests/test_broad_except_silent_budget.py",
    "tests/test_build_family_metrics.py",
    "tests/test_builtin_open_encoding_ledger.py",
    "tests/test_dangerous_io_zero_surface_pin.py",
    "tests/test_dynamic_getattr_ledger.py",
    "tests/test_dynamic_import_and_todo_tripwires.py",
    "tests/test_dynamic_setattr_hasattr_zero_surface.py",
    "tests/test_edge_hypotheses_frozen.py",
    "tests/test_family_event_adapter.py",
    "tests/test_family_returns.py",
    "tests/test_family_verdict.py",
    "tests/test_family_walkforward_config.py",
    "tests/test_fast_gates_silent_skip_coverage.py",
    "tests/test_fcntl_flock_zero_surface.py",
    "tests/test_field_preference_chain_ledger.py",
    "tests/test_global_statement_budget.py",
    "tests/test_globals_call_zero_surface.py",
    "tests/test_hashlib_weak_hash_ledger.py",
    # 2026-07-15: the hmac zero-surface ledger (auth/integrity primitive) was
    # never on the required path — not in this roster, not in any workflow (its
    # git history shows no add/remove in either). Its pins drifted red on main
    # three times unnoticed (2026-07-09, -07-13, -07-15) because the drift
    # merged green: fast-gates never ran it. Simply missed when it landed (#3217).
    "tests/test_hmac_auth_zero_surface.py",
    "tests/test_http_client_discipline.py",
    "tests/test_http_post_egress_ledger.py",
    "tests/test_lint_debt_no_regression.py",
    "tests/test_loopback_and_baseimage_pin.py",
    "tests/test_lru_cache_maxsize_discipline.py",
    "tests/test_module_test_coverage_pin.py",
    "tests/test_monitoring_metric_alert_coverage.py",
    "tests/test_mutable_defaults_and_loads_pins.py",
    "tests/test_nonlocal_budget.py",
    "tests/test_noqa_budget.py",
    "tests/test_noqa_suppression_ledger.py",
    "tests/test_os_environ_mutation_ledger.py",
    "tests/test_os_unlink_remove_ledger.py",
    "tests/test_path_text_io_encoding_ledger.py",
    "tests/test_pine_alertcondition_and_declaration_pin.py",
    "tests/test_pine_context_library_contract.py",
    "tests/test_pine_library_import_permissions.py",
    "tests/test_pine_request_security_htf_pin.py",
    "tests/test_pine_var_budget_pin.py",
    "tests/test_point_in_time_integrity.py",
    "tests/test_prod_print_ledger.py",
    "tests/test_pytest_marker_bucket_discipline.py",
    "tests/test_pytest_skip_budget.py",
    "tests/test_random_tempfile_ledger_pin.py",
    "tests/test_realtime_signals_sister_ledger_guardrail.py",
    "tests/test_run_edge_pipeline.py",
    "tests/test_schema_version_manifest_alignment.py",
    "tests/test_silent_error_swallow_pin.py",
    "tests/test_silent_security_and_boundary_bundle.py",
    "tests/test_smc_bus_v2_freeze.py",
    "tests/test_smc_context_golden.py",
    "tests/test_smc_library_refresh_workflow.py",
    "tests/test_socket_bind_loopback_pin.py",
    "tests/test_subprocess_shell_injection_pin.py",
    "tests/test_subprocess_spawn_sites_ledger.py",
    "tests/test_sys_exit_ledger_pin.py",
    "tests/test_sys_path_mutation_ledger.py",
    "tests/test_time_sleep_budget.py",
    "tests/test_type_ignore_budget.py",
    "tests/test_urllib_urlopen_ledger.py",
    "tests/test_verdict_panel.py",
    "tests/test_warnings_simplefilter_ledger.py",
    "tests/test_weak_hash_pin.py",
    "tests/test_while_true_termination_ledger.py",
    "tests/test_workflow_auth_pattern.py",
    "tests/test_workflow_concurrency_cron_no_cancel.py",
    "tests/test_workflow_continue_on_error_inventory.py",
    "tests/test_workflow_freshness_monitor_workflow.py",
    "tests/test_workflow_invoked_scripts_importable.py",
    "tests/test_workflow_issue_labels_exist.py",
    "tests/test_workflow_no_fake_push_success.py",
    "tests/test_workflow_orphan_inventory.py",
    "tests/test_workflow_permissions_present.py",
    "tests/test_workflow_python_unbuffered.py",
    "tests/test_workflow_pythonpath_for_direct_invoke.py",
    "tests/test_workflow_runner_pinned.py",
    "tests/test_workflow_set_plus_e_inventory.py",
    "tests/test_workflow_upload_artifact_uniform_version.py",
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


def _line_pinned_ledgers() -> set[str]:
    """Every line-pinned / registry-backed ledger, discovered from source."""
    found: set[str] = set()
    for path in sorted((ROOT / "tests").glob("test_*.py")):
        if _freezes_line_pins(path):
            found.add(f"tests/{path.name}")
            continue
        # pin_registry-backed ledgers keep their pins in pin_registry.toml
        # instead of in the test body, so the AST shape above cannot see them.
        if "pin_registry" in path.read_text(encoding="utf-8", errors="replace"):
            found.add(f"tests/{path.name}")
    return found


def test_every_line_pinned_ledger_is_on_the_required_path() -> None:
    """A line-pinned ledger that is not gated drifts red on main unnoticed.

    Derived, not hand-maintained: the required set comes from the source, so a
    PR cannot retire a ledger by deleting it from the step and the roster
    together (the hole #3670 fell through). The ledger still exists in tests/,
    so it must still be gated — or be listed above with a reason.
    """
    ledgers = _line_pinned_ledgers()
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
        "line-pinned ledger(s) are not on the required path. fast-gates is the "
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
