"""Defense-pin: ``subprocess.*`` call site ledger + ``shell=True`` invariant.

Pinning the surface of subprocess calls is a high-leverage defense:

* ``shell=True`` is the canonical CWE-78 (OS command injection) foot-gun.
  This repo currently has **zero** ``shell=True`` sites — that is a hard
  invariant we want to keep. ``test_no_shell_true_anywhere`` enforces it.
* New subprocess sites usually deserve review (auth surface, working dir,
  env propagation, signal handling). The per-file ledger forces an explicit
  bump when one is added.
* ``subprocess.run / Popen / check_call / check_output / call`` are pinned
  individually so swapping ``run`` → ``Popen`` (which has different
  default semantics for stdout/stderr) is also visible.

Defense-only — no production code changes.
"""

from __future__ import annotations

import ast
from collections import Counter
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

_DIR_EXCLUDE = frozenset(
    {
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
)

# Methods on ``subprocess`` we treat as "spawning a process". This pins
# the API surface; a brand-new spawning method (``subprocess.foo``)
# would require an explicit allow-list bump.
_SPAWN_ATTRS = frozenset(
    {"run", "Popen", "call", "check_call", "check_output"}
)

# Per-(file, subprocess.attr) ledger of call counts in first-party
# production / scripts / streamlit code.
#
# Convention on this repo today:
#   * ``run`` is the default — ``check=True`` is the recommended idiom.
#   * ``Popen`` is reserved for genuinely streaming or non-blocking flows
#     (``open_prep/realtime_signals.py`` background process,
#      ``scripts/start_open_prep_suite.py`` orchestrator).
#   * ``check_output`` only appears in ``scan_manifests_for_pytest_provenance``
#     because the script needs the captured stdout for grep-style scans.
#
# Adding/removing any site MUST update this ledger in the same PR.
_FROZEN_SITES: dict[tuple[str, str], int] = {
    # governance/run_manifest.py captures `git rev-parse HEAD` once per
    # process to stamp the run manifest. Token-list args, no shell=True,
    # 2.0s timeout, stderr discarded, lru_cached.
    ("governance/run_manifest.py", "check_output"): 1,
    # scripts/analyze_publish_cadence.py runs `git log --format=%ct\t%h --`
    # once per pathspec to compute publish-cadence stats. Token-list args,
    # no shell=True, read-only dev/analysis helper.
    ("scripts/analyze_publish_cadence.py", "run"): 1,
    ("open_prep/realtime_signals.py", "Popen"): 1,
    ("open_prep/realtime_signals.py", "run"): 1,
    ("scripts/measure_databento_ops_run.py", "run"): 1,
    # scripts/phase5_perf_trend.py wraps `gh run list` once per workflow to
    # compute the larger-runner perf trend artifact (review-v3 phase 5).
    # Token-list args, no shell=True, dev-only/manually invoked.
    ("scripts/phase5_perf_trend.py", "check_output"): 1,
    # perf(tools): local/manual pytest-duration profiling helper. Args are
    # assembled from argparse + shlex into a token-list command, cwd is pinned
    # to the repo root, and shell=True remains forbidden.
    ("scripts/profile_pytest_durations.py", "run"): 1,
    # perf(tools) helper: py-spy wrapper for profiling cron entry points
    # (#2281). Token-list args (argparse + shlex.split), no shell=True,
    # dev-only/manually invoked from a self-hosted runner.
    ("scripts/profile_cron_with_pyspy.py", "run"): 1,
    # security helper: verifies TradingView storage-state file permissions
    # via a one-shot `icacls` token-list call. No shell=True, no untrusted
    # input, dev/CI gate only.
    ("scripts/check_tradingview_storage_state_security.py", "run"): 1,
    # perf(ci) PR #2283: lockfile regenerator wraps two `uv pip compile`
    # invocations (compile + verify). Token-list args, no shell=True, dev/CI
    # helper only; both call sites marked with `# noqa: S603`.
    ("scripts/regenerate_requirements_lock.py", "run"): 2,
    ("scripts/scan_manifests_for_pytest_provenance.py", "check_output"): 2,
    ("scripts/smc_micro_publish_guard.py", "run"): 1,
    ("scripts/smc_zone_priority_calibration.py", "run"): 1,
    ("scripts/start_open_prep_suite.py", "Popen"): 1,
    ("scripts/start_open_prep_suite.py", "run"): 2,
    ("smc_integration/release_policy.py", "run"): 1,
}
_FROZEN_TOTAL = sum(_FROZEN_SITES.values())


def _iter_first_party_py_files() -> list[Path]:
    out: list[Path] = []
    for path in ROOT.rglob("*.py"):
        try:
            rel_parts = path.relative_to(ROOT).parts
        except ValueError:
            continue
        if any(part in _DIR_EXCLUDE for part in rel_parts):
            continue
        out.append(path)
    return sorted(out)


def _is_subprocess_call(node: ast.Call) -> str | None:
    """Return the ``subprocess.<attr>`` name if the call matches, else ``None``."""
    func = node.func
    if not isinstance(func, ast.Attribute):
        return None
    if not (isinstance(func.value, ast.Name) and func.value.id == "subprocess"):
        return None
    return func.attr


def _has_shell_true(node: ast.Call) -> bool:
    for kw in node.keywords:
        if kw.arg == "shell" and isinstance(kw.value, ast.Constant) and kw.value.value is True:
            return True
    return False


def _scan_file(path: Path) -> tuple[Counter[tuple[str, str]], list[int]]:
    """Return ((site_counts, shell_true_lines)) for this file."""
    counts: Counter[tuple[str, str]] = Counter()
    shell_true_lines: list[int] = []
    try:
        source = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return counts, shell_true_lines
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError:
        return counts, shell_true_lines
    rel = path.relative_to(ROOT).as_posix()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        attr = _is_subprocess_call(node)
        if attr is None:
            continue
        counts[(rel, attr)] += 1
        if _has_shell_true(node):
            shell_true_lines.append(node.lineno)
    return counts, shell_true_lines


def _observed_counts() -> dict[tuple[str, str], int]:
    out: Counter[tuple[str, str]] = Counter()
    for path in _iter_first_party_py_files():
        c, _ = _scan_file(path)
        out.update(c)
    return dict(out)


def _observed_shell_true() -> list[tuple[str, int]]:
    out: list[tuple[str, int]] = []
    for path in _iter_first_party_py_files():
        _, lines = _scan_file(path)
        rel = path.relative_to(ROOT).as_posix()
        for ln in lines:
            out.append((rel, ln))
    return sorted(out)


def test_no_shell_true_anywhere() -> None:
    """Hard invariant: no ``subprocess.X(..., shell=True)`` in first-party code (CWE-78)."""
    sites = _observed_shell_true()
    assert not sites, (
        "CWE-78 surface re-opened — subprocess(..., shell=True) sites "
        "found:\n"
        + "\n".join(f"  - {rel}:{ln}" for rel, ln in sites)
        + "\n\nUse a token list (``[arg, ...]``) instead, or wrap in "
        "``shlex.split`` only after explicit allow-list validation."
    )


def test_no_new_subprocess_attrs() -> None:
    """Refuse new ``subprocess.<attr>`` spawning methods without a ledger bump."""
    observed = _observed_counts()
    new_attrs = sorted({attr for (_, attr) in observed} - _SPAWN_ATTRS)
    assert not new_attrs, (
        "New subprocess spawning method(s) introduced — these escape the "
        "ledger contract:\n"
        + "\n".join(f"  - subprocess.{a}" for a in new_attrs)
        + "\n\nUpdate _SPAWN_ATTRS + _FROZEN_SITES with rationale."
    )


def test_no_new_subprocess_sites() -> None:
    """No new ``(file, subprocess.attr)`` site without a ledger bump."""
    observed = _observed_counts()
    new_sites = sorted(set(observed) - set(_FROZEN_SITES))
    assert not new_sites, (
        "New subprocess site(s) — process-spawn surface expanded:\n"
        + "\n".join(
            f"  - {rel} [subprocess.{attr}] count={observed[(rel, attr)]}"
            for (rel, attr) in new_sites
        )
        + "\n\nIf the site is genuinely needed, add it to _FROZEN_SITES "
        "with a justifying comment (no shell=True, token-list args)."
    )


def test_no_removed_subprocess_sites() -> None:
    """A site disappearing is great — drop it from the ledger explicitly."""
    observed = _observed_counts()
    missing = sorted(set(_FROZEN_SITES) - set(observed))
    assert not missing, (
        "Frozen subprocess site(s) no longer present — drop from "
        "_FROZEN_SITES in the same PR:\n"
        + "\n".join(f"  - {rel} [subprocess.{attr}]" for (rel, attr) in missing)
    )


@pytest.mark.parametrize(
    "rel,attr,expected",
    sorted((rel, attr, n) for (rel, attr), n in _FROZEN_SITES.items()),
)
def test_frozen_subprocess_count_still_matches(
    rel: str, attr: str, expected: int
) -> None:
    """Per-(file, subprocess.attr) count must match the ledger exactly."""
    path = ROOT / rel
    assert path.is_file(), f"frozen site missing on disk: {rel}"
    actual = _scan_file(path)[0].get((rel, attr), 0)
    assert actual == expected, (
        f"subprocess.{attr} count drifted in {rel}: "
        f"expected {expected}, got {actual}. "
        "Update _FROZEN_SITES in the same PR."
    )


def test_total_subprocess_count_pinned() -> None:
    """Aggregate cross-check against per-(file, attr) ledger drift."""
    observed = _observed_counts()
    total = sum(observed.values())
    assert total == _FROZEN_TOTAL, (
        f"subprocess call total drifted: expected {_FROZEN_TOTAL}, "
        f"got {total}. Per-site = {sorted(observed.items())}"
    )
