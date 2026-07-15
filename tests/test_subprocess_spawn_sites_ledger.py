"""Defense ledger: ``subprocess.run`` / ``subprocess.Popen`` call-sites.

Pins every production process-spawn call by ``(path, line, argv)``. Every
entry is a deliberate, reviewed external command invocation. New
spawns must be a reviewed change instead of a copy-paste — and so must a
new *command* at an existing site, which the ``argv`` element is what
catches.

Why pin sites (in addition to the existing kwarg-shape invariants):

* ``test_subprocess_run_check_invariant.py`` already enforces
  ``check=`` is passed.
* ``test_dangerous_call_tripwires.py`` /
  ``test_shell_true_tripwire.py`` already ban ``shell=True``.
* But neither covers *where* commands are spawned. The site ledger
  is the missing piece — it surfaces drift, doubles as a one-grep
  audit of every place we shell out, and forces a reviewer to ask
  "is this new shell-out actually necessary?".

Today the audited repository surface (production modules + explicitly
included helper scripts) spawns external commands from exactly five
locations. The ledgers below are the authority for the line numbers — this
list names the module and its purpose only, so it cannot drift out of date the
way a duplicated line reference does:

* ``smc_integration/release_policy.py`` — read git HEAD SHA
  (``git rev-parse HEAD``) for release manifest provenance.
* ``open_prep/realtime_signals.py`` — locate the realtime
  signals daemon by scanning the process list (``pgrep``).
* ``open_prep/realtime_signals.py`` — re-launch the realtime
  signals daemon as a detached child (``Popen`` of
  ``python -m open_prep.realtime_signals``).
* ``scripts/publish_overlay_dashboard.py`` — query OS keychain
  for the Grafana API token (``security find-generic-password ...``).
* ``scripts/publish_signals_snapshot.py`` — run explicit git argv
    commands to publish the rolling live-signals snapshot branch.

(Those references read ``:190``, ``:336`` and ``:151`` until 2026-07-15; the
real sites were 218, 383 and 173. The prose duplicated line numbers the
reconciles below kept moving, and nothing checked it.)

Defense-only — no production changes.
"""

from __future__ import annotations

import ast
from pathlib import Path

from tests._guard_corpus import iter_tracked_files, parse_module

ROOT = Path(__file__).resolve().parents[1]

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
    "scripts",
}


def _iter_py_files() -> list[Path]:
    out = iter_tracked_files("*.py", _DIR_EXCLUDE, root=ROOT)
    publish_overlay = ROOT / "scripts/publish_overlay_dashboard.py"
    publish_signals = ROOT / "scripts/publish_signals_snapshot.py"
    if publish_overlay.is_file() and publish_overlay not in out:
        out.append(publish_overlay)
    if publish_signals.is_file() and publish_signals not in out:
        out.append(publish_signals)
    return out


def _subprocess_attr_sites(attr: str) -> set[tuple[str, int, str]]:
    """Return ``{(relpath, lineno, argv)}`` for literal ``subprocess.<attr>(...)`` calls.

    Detects only the ``subprocess.<attr>`` shape: an attribute call whose
    receiver is exactly ``Name('subprocess')``. Aliased imports
    (``import subprocess as sp``) and direct imports
    (``from subprocess import run``) are intentionally out of scope here
    — the companion ``test_subprocess_alias_import_zero_surface_pin``
    separately fails closed if either import form appears in production
    code, while this helper remains limited to literal
    ``subprocess.<attr>(...)`` call sites. In-module rebindings
    (e.g. ``sp = subprocess; sp.run(...)`` or
    ``run = subprocess.run; run(...)``) are NOT detected by either
    helper and would still bypass the ledger; treat the pin as a
    high-signal review gate, not a hermetic bypass-proof guarantee.
    """

    sites: set[tuple[str, int]] = set()
    for path in _iter_py_files():
        tree = parse_module(path)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not isinstance(func, ast.Attribute):
                continue
            if func.attr != attr:
                continue
            if not (isinstance(func.value, ast.Name) and func.value.id == "subprocess"):
                continue
            sites.add((path.relative_to(ROOT).as_posix(), node.lineno, _argv_src(node)))
    return sites


def _argv_src(node: ast.Call) -> str:
    """Source text of the argv this call spawns, or ``<no argv>``.

    The ledger below documents *which command* each site runs — "git rev-parse
    HEAD", "pgrep to discover the daemon PID", "keychain token lookup". A
    ``(path, lineno)`` pin cannot see any of it: swapping the argv of an
    already-ledgered line changes what gets executed without moving the line,
    and the pin stays green. Pinning the argv is what makes those per-entry
    claims checkable.

    argv[0] alone would not do. It is a resolved-path variable at every site
    (``git_exe``, ``pgrep_exe``, ``security_bin``, ``sys.executable``), so
    ``[git_exe, 'rev-parse', 'HEAD']`` -> ``[git_exe, 'push', '--force']`` would
    keep it identical. The whole argv is pinned instead.
    """

    if not node.args:
        return "<no argv>"
    return ast.unparse(node.args[0])


def _subprocess_alias_or_direct_import_sites() -> set[tuple[str, int, str]]:
    """Return ``(path, lineno, form)`` for any aliased / direct ``subprocess`` import.

    Catches ``import subprocess as <alias>`` and
    ``from subprocess import <name>``, both of which would let a future
    caller bypass the literal ``subprocess.<attr>(...)`` ledger.
    """

    found: set[tuple[str, int, str]] = set()
    for path in _iter_py_files():
        tree = parse_module(path)
        if tree is None:
            continue
        rel = path.relative_to(ROOT).as_posix()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "subprocess" and alias.asname:
                        found.add((rel, node.lineno, f"import subprocess as {alias.asname}"))
            elif (
                isinstance(node, ast.ImportFrom)
                and node.module == "subprocess"
                and node.level == 0
            ):
                for alias in node.names:
                    found.add((rel, node.lineno, f"from subprocess import {alias.name}"))
    return found


# Locked surface — every entry is a reviewed external command.
# The third element is the argv the site spawns; it used to live only in
# these comments, where nothing read it (2026-07-15).
SUBPROCESS_RUN_LEDGER: set[tuple[str, int, str]] = {
    # `git rev-parse HEAD` for release-manifest provenance.
    # Rebaselined 2026-06-11: RECALIBRATION_REQUIRED annotation on the
    # calibrated-ECE degradation added lines above this site (1107 -> 1119).
    # 2026-06-19 (timeframe expansion): import of CANONICAL_TIMEFRAMES shifted
    # the subprocess.run call 1119 -> 1121.
    # 2026-07-13: in-sample-disclosure docstring on MeasurementShadowThresholds shifted 1121 -> 1137.
    # 2026-07-13: OOS advisory ceilings (thresholds/registry/checks) shifted 1137 -> 1210.
    ("smc_integration/release_policy.py", 1210, "[git_exe, 'rev-parse', 'HEAD']"),
    # `pgrep` to discover the realtime-signals daemon PID.
    # Rebaselined 2026-05-15 after PR #2233 mainline merge restored the
    # branch-local realtime_signals layout.
    # Shifted 190 -> 191 after import hmac + lock fix added lines above.
    # 2026-06-28 (semantic monitoring): shifted +20 lines by _extract_snapshot_epoch helper.
    # 2026-07-03 (WP-4 holiday gate): shifted +2 (import block above).
    # 2026-07-12: +1 (DATA_STALL_SECONDS constant added above).
    ("open_prep/realtime_signals.py", 218, "[pgrep_exe, '-f', 'python.*-m open_prep.realtime_signals']"),
    # 2026-06-22: Grafana dashboard publish script keychain token lookup.
    # Line shifted 151 -> 173 after ADR-0025 App Platform (/apis
    # dashboard.grafana.app/v1) migration added namespace/folder args above.
    ("scripts/publish_overlay_dashboard.py", 173, "[security_bin, 'find-generic-password', '-s', keychain_service, '-a', os.environ.get('USER', ''), '-w']"),
    # 2026-06-23: host helper publishing latest realtime signals snapshot to
    # rolling bot branch via explicit git argv subprocess calls.
    ("scripts/publish_signals_snapshot.py", 73, '[git_exe, *args]'),
}

SUBPROCESS_POPEN_LEDGER: set[tuple[str, int, str]] = {
    # Detached re-launch of the realtime-signals daemon.
    # Shifted 336 -> 337 -> 341 after import hmac + lock fix + do_HEAD addition.
    # 2026-06-28 (semantic monitoring): shifted +20 lines by _extract_snapshot_epoch helper.
    # 2026-07-03 (WP-4 holiday gate): shifted +2 (import block above).
    ("open_prep/realtime_signals.py", 383, "[sys.executable, '-m', 'open_prep.realtime_signals', '--interval', str(poll_interval)]"),  # 2026-07-13 (rt_engine_status liveness re-validate above): 368->383
}


def test_subprocess_inventory_sane() -> None:
    # Guard against silent coverage loss (sparse checkout, layout change,
    # CI misconfiguration). The repo has well over 100 first-party .py
    # files; a sudden drop to a handful means the AST scan saw nothing
    # and would silently false-pass.
    files = _iter_py_files()
    assert len(files) >= 50, (
        f"first-party python file count collapsed to {len(files)} — "
        "the AST scan is likely seeing an empty tree, which would let "
        "new subprocess.run / subprocess.Popen callers slip in unnoticed."
    )


def test_subprocess_alias_import_zero_surface_pin() -> None:
    # The ledgers below only catch literal ``subprocess.<attr>(...)``.
    # Aliased imports (``import subprocess as sp``) and direct imports
    # (``from subprocess import run``) would silently bypass them.
    # Forbid both forms so the ledger's narrow scope can't be circumvented.
    found = _subprocess_alias_or_direct_import_sites()
    assert not found, (
        "Aliased or direct ``subprocess`` import detected. These forms "
        "bypass the ``subprocess.<attr>(...)`` ledgers below. Use "
        "plain ``import subprocess`` and qualified "
        "``subprocess.run(...)`` / ``subprocess.Popen(...)`` calls only.\n"
        f"found = {sorted(found)}"
    )


def test_subprocess_run_site_ledger_pin() -> None:
    sites = _subprocess_attr_sites("run")

    unexpected = sites - SUBPROCESS_RUN_LEDGER
    assert not unexpected, (
        "New ``subprocess.run(...)`` call site detected. Every shell-"
        "out is a reviewable surface — argument injection, "
        "exit-code mishandling, PATH-dependence, and platform "
        "portability are all real risks. If this is a legitimate new "
        "external command, append the (path, line) tuple to "
        "SUBPROCESS_RUN_LEDGER and document the command + safety "
        "posture (argv list, ``check=``, ``timeout=``, ``shell=False``) "
        "in the commit message.\n"
        f"unexpected = {sorted(unexpected)}"
    )

    missing = SUBPROCESS_RUN_LEDGER - sites
    assert not missing, (
        "SUBPROCESS_RUN_LEDGER entries no longer present at the "
        "recorded (path, line). Update the ledger to match the "
        "current call sites and verify the underlying command is "
        "unchanged.\n"
        f"missing = {sorted(missing)}"
    )


def test_subprocess_popen_site_ledger_pin() -> None:
    sites = _subprocess_attr_sites("Popen")

    unexpected = sites - SUBPROCESS_POPEN_LEDGER
    assert not unexpected, (
        "New ``subprocess.Popen(...)`` call site detected. "
        "``Popen`` is even riskier than ``run`` — it spawns a "
        "long-lived child whose lifetime, stdio buffering, and "
        "termination semantics are owned by the caller. Prefer "
        "``subprocess.run`` for synchronous one-shot commands. If a "
        "detached child process is genuinely required, append the "
        "(path, line) tuple to SUBPROCESS_POPEN_LEDGER and document "
        "the lifecycle ownership in the commit message.\n"
        f"unexpected = {sorted(unexpected)}"
    )

    missing = SUBPROCESS_POPEN_LEDGER - sites
    assert not missing, (
        "SUBPROCESS_POPEN_LEDGER entries no longer present at the "
        "recorded (path, line). Update the ledger to match the "
        "current call sites.\n"
        f"missing = {sorted(missing)}"
    )
