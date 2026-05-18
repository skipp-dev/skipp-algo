"""Defense pin: frozen ledger of ``# noqa`` lint-suppression markers in
first-party non-test code.

Rationale
---------
``# noqa`` (with or without specific code list) silences linter findings.
Each suppression is a deliberate decision that should require justification.
Without a ledger, suppressions accumulate silently and the codebase drifts
toward unmaintained-quality regions.

Sister of #213 (silent-error-swallow ledger), #218 (Path text-IO encoding),
#220 (built-in open encoding). The ledger may only **shrink**: removing
suppressions is welcome; adding new ones requires a deliberate ledger bump
in the same PR.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]

_DIR_EXCLUDE = {
    ".git",
    ".github",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "venv",
    "node_modules",
    "artifacts",
    "docs",
    "tests",
    "SMC++",
}

_NOQA_RE = re.compile(r"#\s*noqa\b", re.IGNORECASE)

# Frozen ledger — exactly today's surface (2026-04-29).
#
# The following suppressions are intentional and registered here:
#
# * ``streamlit_terminal_alerts.py``: validates that a webhook URL host is
#   not "0.0.0.0" / localhost — string-matching, *not* binding a server.
#   Bandit S104 is a false positive in this context.
# * ``scripts/scan_manifests_for_pytest_provenance.py``: contains a regex
#   literal ``r"/tmp/pytest-of-..."`` used to *detect* pytest tmp-path
#   leakage in shipped manifests. The path is a search pattern, not a
#   file Python opens. Bandit S108 is a false positive. Additionally,
#   two ``subprocess.check_output`` calls invoke ``git diff --cached``
#   and ``git ls-files`` via a ``shutil.which("git")``-resolved
#   executable with hardcoded argv lists; Bandit S603 is a false
#   positive in this trusted-binary, fixed-args context.
# * ``governance/run_manifest.py``: invokes ``git rev-parse HEAD`` via a
#   ``shutil.which("git")``-resolved executable with a hardcoded argv
#   list. No untrusted input reaches subprocess; Bandit S603 is a false
#   positive in this trusted-binary, fixed-args context.
# * ``open_prep/realtime_signals.py``: spawns the realtime engine via
#   ``sys.executable -m open_prep.realtime_signals`` and probes for an
#   existing instance via ``shutil.which("pgrep")`` with hardcoded
#   argv. Bandit S603 is a false positive in both trusted-binary,
#   fixed-args contexts.
# * ``scripts/resolve_workflow_runner.py``: queries the fixed GitHub REST
#   runner-inventory endpoint via ``urllib.request.urlopen`` with a
#   repository argument and auth header assembled by trusted workflow
#   control-plane code. Bandit S310 is a false positive in this
#   fixed-domain GitHub API context.
# * ``scripts/measure_databento_ops_run.py``: invokes
#   ``sys.executable -c <runner>`` with a hardcoded inline runner script.
#   Bandit S603 is a false positive (no untrusted argv element).
# * ``scripts/smc_micro_publish_guard.py``: invokes the project's
#   ``npm run tv:publish-micro-library`` task with a hardcoded argv
#   list. Bandit S603 is a false positive.
# * ``scripts/smc_zone_priority_calibration.py``: invokes
#   ``git rev-parse HEAD`` via a ``shutil.which("git")``-resolved
#   executable with a hardcoded argv list. Bandit S603 is a false
#   positive.
# * ``scripts/start_open_prep_suite.py``: launches the open-prep run
#   (``python_exe -m open_prep.run_open_prep``), stops any prior
#   streamlit monitor (``shutil.which("pkill")``), and spawns a
#   streamlit binary derived from the same Python sibling path. All
#   three sites use hardcoded argv lists; Bandit S603 is a false
#   positive in each.
# * ``scripts/resolve_workflow_runner.py``: queries the fixed GitHub
#   Actions runners REST endpoint via ``urllib.request.urlopen``.
#   Bandit S310 is a false positive because the URL is a hardcoded
#   GitHub API path and never comes from user input.
# * ``smc_integration/release_policy.py``: invokes ``git rev-parse HEAD``
#   via a ``shutil.which("git")``-resolved executable with a hardcoded
#   argv list. Bandit S603 is a false positive.
#
# All other first-party noqa suppressions remain forbidden.
_FROZEN_SITES: dict[str, int] = {
    "streamlit_terminal_alerts.py": 1,
    "databento_volatility_screener.py": 1,
    "newsstack_fmp/pipeline.py": 1,
    "open_prep/run_open_prep.py": 1,
    "smc_tv_bridge/smc_api.py": 1,
    # 2026-05-13 (#2171 follow-up): module-import-time hardening for the
    # OPRA-options-flow integration so streamlit_monitor stays importable
    # even when the optional ingest module fails to import. Single BLE001.
    "open_prep/streamlit_monitor.py": 1,
    "scripts/scan_manifests_for_pytest_provenance.py": 3,
    "governance/run_manifest.py": 1,
    "open_prep/realtime_signals.py": 2,
    "scripts/resolve_workflow_runner.py": 1,
    "scripts/ib_client_id.py": 2,
    "scripts/measure_databento_ops_run.py": 2,
    "scripts/smc_micro_publish_guard.py": 1,
    "scripts/smc_zone_priority_calibration.py": 2,
    "scripts/start_open_prep_suite.py": 3,
    "smc_integration/release_policy.py": 1,
    # E402 after sys.path bootstrap (system review 2026-04-30):
    # both scripts insert repo root into sys.path before importing
    # first-party modules; ruff-isort cannot statically prove the
    # ordering is required for runnability when invoked as a path
    # rather than as a -m module.
    # Rebaselined 2026-05-03 (after PR #2035): bumped 1 → 3 / 2 → 4
    # because the import-order fix added the ``_bootstrap_sys_mod``
    # helper which contributes two new ``# noqa: E402`` lines per
    # script (the ``sys = _bootstrap_sys_mod`` rebinding and the
    # subsequent ``from scripts._logging_init import init_cli_logging``).
    "scripts/collect_smc_gate_evidence.py": 3,
    "scripts/run_smc_pre_release_artifact_refresh.py": 4,
    # SMC review v3 ledger sync (2026-05-01, F-V3-18): rolling-bench / smoke /
    # FVG quality scripts that were added in #1947–#1972 without bumping the
    # ledger. All are E402 after sys.path bootstrap or T201/print() in
    # one-shot CLI tools — never on hot/prod codepaths.
    "scripts/analyze_smc_contextual_calibration_history.py": 3,
    # Rebaselined 2026-05-03 (after PR #2035): bumped 1 → 3 because
    # the import-order fix added the ``_bootstrap_sys_mod`` helper
    # (two new ``# noqa: E402`` lines per script).
    "scripts/e2e_smoke_ci.py": 3,
    "scripts/execute_ibkr_watchlist.py": 1,
    "scripts/export_open_prep_lists.py": 2,
    "scripts/export_open_prep_reports.py": 2,
    "scripts/fvg_asia_real_sample.py": 1,
    "scripts/fvg_label_audit.py": 1,
    # Rebaselined 2026-05-03 (after PR #2035): bumped 1 → 3, see e2e_smoke_ci.py.
    "scripts/fvg_quality_recalibration.py": 3,
    "scripts/generate_performance_report.py": 1,
    "scripts/probe_newsapi_feed_cursor.py": 5,
    "scripts/run_smc_e2e_smoke_test.py": 1,
    "scripts/run_smc_measurement_benchmark.py": 2,
    # Rebaselined 2026-05-03 (after PR #2035): bumped 1 → 3, see e2e_smoke_ci.py.
    "scripts/run_smc_release_gates.py": 3,
    "scripts/smc_performance_report.py": 1,
    # F-V4-E1 (2026-05-01): databento_safe_fetch.safe_get_range catches
    # ``Exception`` deliberately so it can string-classify the ~half-dozen
    # Databento error types (HTTP 422 / data_start_after_available_end /
    # BentoClientError) and re-raise unclassified errors. BLE001 noqa
    # is justified by the docstring + classification dispatch table.
    "scripts/databento_safe_fetch.py": 1,
    # Added 2026-05-03 (after PR #2035): each carries the two
    # ``# noqa: E402`` lines from the ``_bootstrap_sys_mod`` helper
    # (``sys = _bootstrap_sys_mod`` rebinding + the immediately
    # following ``from scripts._logging_init import init_cli_logging``).
    "scripts/check_pine_legacy_drift.py": 2,
    "scripts/emit_fvg_context_pine.py": 2,
    "scripts/fvg_quality_quartile_gate.py": 2,
    "scripts/g23_ab_watchdog.py": 2,
    # A9b.3 reduce-step: single `# noqa: E402` for the
    # `from scripts.smc_atomic_write import atomic_write_json` import
    # which must follow the sys.path bootstrap (see import-order ledger).
    "scripts/databento_production_merge_shards.py": 1,
    # 2026-05-12 PR #2157: Databento entitlement probe wraps each
    # provider request in a generic ``except Exception`` so it can
    # surface the original error message in the probe report. BLE001
    # noqa is justified by the diagnostic-only nature of the script.
    # Rebaselined 2026-05-13: bumped 1 → 3 to cover ImportError surface
    # in __main__ guard (`databento_client` import + `_make_databento_client`
    # construction + `PREFERRED_DATABENTO_DATASETS` import) — each is a
    # diagnostic-only ``# noqa: SECLEAK`` because the surfaced text contains
    # only module/path identifiers, not credentials.
    "scripts/probe_databento_entitlement.py": 3,
    # 2026-05-12 PR #2154: scripts/probe_fmp_13f_endpoints.py needs 3
    # noqa suppressions: 1× S310 for the urllib.request.urlopen call
    # (probe whitelisted-domain via deliberate URL inspection) and 2×
    # BLE001 for the discovery loop's generic exception-catch (probe
    # must surface every endpoint's error, not let one tear down the
    # report). Diagnostic-only script.
    "scripts/probe_fmp_13f_endpoints.py": 3,
    # 2026-05-13: scripts/probe_providers.py preflight + notification
    # dispatcher catches ``Exception`` deliberately (broad logging.exception
    # in two error-recovery paths) so a transient dispatcher failure does
    # not abort the multi-provider preflight run. Each call site carries
    # ``# noqa: SECLEAK`` because the dispatcher logs only the exception
    # type / message (no API keys live in the exception stack frame).
    "scripts/probe_providers.py": 2,
}
_FROZEN_TOTAL = sum(_FROZEN_SITES.values())


def _iter_python_files() -> list[Path]:
    out: list[Path] = []
    for path in _ROOT.rglob("*.py"):
        if any(part in _DIR_EXCLUDE for part in path.relative_to(_ROOT).parts):
            continue
        out.append(path)
    return out


def _observed_counts() -> dict[str, int]:
    counts: dict[str, int] = {}
    for path in _iter_python_files():
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        n = sum(1 for line in text.splitlines() if _NOQA_RE.search(line))
        if n:
            counts[path.relative_to(_ROOT).as_posix()] = n
    return counts


def test_noqa_total_does_not_grow() -> None:
    observed = _observed_counts()
    total = sum(observed.values())
    assert total <= _FROZEN_TOTAL, (
        f"Total `# noqa` suppressions grew: frozen={_FROZEN_TOTAL}, "
        f"observed={total}. Justify and update _FROZEN_SITES + _FROZEN_TOTAL "
        "in the same PR, or remove the suppression."
    )


def test_no_new_noqa_files() -> None:
    observed = _observed_counts()
    new_files = sorted(set(observed) - set(_FROZEN_SITES))
    assert not new_files, (
        "New file(s) introduced `# noqa` suppressions. Either fix the "
        f"underlying lint warning or update _FROZEN_SITES. New: {new_files}"
    )


@pytest.mark.parametrize("rel,expected", sorted(_FROZEN_SITES.items()))
def test_per_file_noqa_count_does_not_grow(rel: str, expected: int) -> None:
    observed = _observed_counts()
    actual = observed.get(rel, 0)
    assert actual <= expected, (
        f"{rel}: `# noqa` suppression count grew from {expected} to {actual}. "
        "Either fix the lint warning or bump _FROZEN_SITES in the same PR."
    )
