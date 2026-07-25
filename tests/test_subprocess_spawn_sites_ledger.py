"""Defense ledger: ``subprocess.run`` / ``subprocess.Popen`` call-sites.

Pins every production process-spawn call by ``(path, line)``. Every
entry is a deliberate, reviewed external command invocation. New
spawns must be a reviewed change instead of a copy-paste.

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
included helper scripts) spawns external commands only from the reviewed
locations pinned below. The MLflow pilot contributes two of them:

* ``smc_integration/release_policy.py:1210`` — read git HEAD SHA
  (``git rev-parse HEAD``) for release manifest provenance.
* ``open_prep/realtime_signals.py:190`` — locate the realtime
  signals daemon by scanning the process list (``pgrep``).
* ``open_prep/realtime_signals.py:336`` — re-launch the realtime
  signals daemon as a detached child (``Popen`` of
  ``python -m open_prep.realtime_signals``).
* ``scripts/publish_overlay_dashboard.py:151`` — query OS keychain
  for the Grafana API token (``security find-generic-password ...``).
* ``scripts/publish_signals_snapshot.py:73`` — run explicit git argv
    commands to publish the rolling live-signals snapshot branch.
* ``services/mlflow_tracking/server.py:153`` — run the MLflow database schema
  migration synchronously with a 120-second timeout.
* ``services/mlflow_tracking/server.py:182`` — launch the authenticated MLflow
  server as the signal-supervised long-lived child process.

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


def _literal_argv(node: ast.Call) -> str:
    """Return the literal argv words of a spawn call, joined by spaces.

    Non-literal elements (``git_exe``, an f-string, a variable) are rendered
    as ``?`` — the interpreter path is legitimately resolved at runtime via
    ``shutil.which``, so pinning it would be noise. What IS pinned is the
    command identity: ``? rev-parse HEAD`` cannot silently become
    ``? push --force origin HEAD``.
    """
    if not node.args:
        return "<no argv>"
    first = node.args[0]
    if not isinstance(first, (ast.List, ast.Tuple)):
        return f"<non-list: {type(first).__name__}>"
    words = []
    for elt in first.elts:
        if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
            words.append(elt.value)
        else:
            words.append("?")
    return " ".join(words)


def _subprocess_attr_sites(attr: str) -> set[tuple[str, int, str]]:
    """Return ``{(relpath, lineno, argv)}`` for literal ``subprocess.<attr>(...)`` calls.

    ``argv`` is the third element since 2026-07-15. The ledger pinned
    ``(path, lineno)`` only, while its header promises "Every entry is a
    deliberate, reviewed external command invocation" and each entry names its
    exact command in a comment — prose the collector never read. So rewriting
    an allow-listed argv in place::

        [git_exe, "rev-parse", "HEAD"]  ->  [git_exe, "push", "--force", "origin", "HEAD"]

    turned a provenance read into a force-push and passed the pin (verified).
    shell=True is banned elsewhere, so the argv IS the command surface.

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
            sites.add(
                (path.relative_to(ROOT).as_posix(), node.lineno, _literal_argv(node))
            )
    return sites


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
# 2026-07-15: the literal argv is now the THIRD element and is ENFORCED. It
# used to live only in the "# `git rev-parse HEAD` for ..." comments above each
# entry, so an allow-listed provenance read could be rewritten in place into a
# force-push and the pin stayed green. "?" marks a runtime-resolved element
# (the interpreter path via shutil.which, a variable) — the command identity is
# what this pins, not the absolute paths.
SUBPROCESS_RUN_LEDGER: set[tuple[str, int, str]] = {
    # `git rev-parse HEAD` for release-manifest provenance.
    # Rebaselined 2026-06-11: RECALIBRATION_REQUIRED annotation on the
    # calibrated-ECE degradation added lines above this site (1107 -> 1119).
    # 2026-06-19 (timeframe expansion): import of CANONICAL_TIMEFRAMES shifted
    # the subprocess.run call 1119 -> 1121.
    # 2026-07-13: in-sample-disclosure docstring on MeasurementShadowThresholds shifted 1121 -> 1137.
    # 2026-07-13: OOS advisory ceilings (thresholds/registry/checks) shifted 1137 -> 1210.
    ("smc_integration/release_policy.py", 1210, "? rev-parse HEAD"),
    # `pgrep` to discover the realtime-signals daemon PID.
    # Rebaselined 2026-05-15 after PR #2233 mainline merge restored the
    # branch-local realtime_signals layout.
    # Shifted 190 -> 191 after import hmac + lock fix added lines above.
    # 2026-06-28 (semantic monitoring): shifted +20 lines by _extract_snapshot_epoch helper.
    # 2026-07-03 (WP-4 holiday gate): shifted +2 (import block above).
    # 2026-07-12: +1 (DATA_STALL_SECONDS constant added above).
    ("open_prep/realtime_signals.py", 220, "? -f python.*-m open_prep.realtime_signals"),  # 2026-07-25 (databento-signal-migration): 219->220
    # 2026-06-22: Grafana dashboard publish script keychain token lookup.
    # Line shifted 151 -> 173 after ADR-0025 App Platform (/apis
    # dashboard.grafana.app/v1) migration added namespace/folder args above.
    ("scripts/publish_overlay_dashboard.py", 173, "? find-generic-password -s ? -a ? -w"),
    # 2026-06-23: host helper publishing latest realtime signals snapshot to
    # rolling bot branch via explicit git argv subprocess calls.
    # Generic `[git_exe, *args]` wrapper: the argv is dynamic BY DESIGN, so "? ?"
    # is all this pin can say here — its callers are the reviewable surface, not
    # this line. Stated rather than papered over.
    ("scripts/publish_signals_snapshot.py", 73, "? ?"),
    # MLflow schema migration before the server accepts traffic. Executable is
    # resolved with shutil.which; token-list argv, check=True, timeout=120,
    # shell=False. DATABASE_URL is one opaque argv item, never shell-parsed.
    ("services/mlflow_tracking/server.py", 153, "? db upgrade ?"),  # 2026-07-18 strict host/CORS/S3 preflight: 96->153
}

SUBPROCESS_POPEN_LEDGER: set[tuple[str, int, str]] = {
    # Detached re-launch of the realtime-signals daemon.
    # Shifted 336 -> 337 -> 341 after import hmac + lock fix + do_HEAD addition.
    # 2026-06-28 (semantic monitoring): shifted +20 lines by _extract_snapshot_epoch helper.
    # 2026-07-03 (WP-4 holiday gate): shifted +2 (import block above).
    ("open_prep/realtime_signals.py", 385, "? -m open_prep.realtime_signals --interval ?"),  # 2026-07-25 (databento-signal-migration): 384->385
    # Authenticated MLflow server. `args` is assembled solely from fixed flags
    # and validated environment values; Popen receives the list directly with
    # shell=False. The launcher forwards SIGTERM/SIGINT and waits for the child.
    ("services/mlflow_tracking/server.py", 182, "<non-list: Name>"),  # 2026-07-18 strict host/CORS/S3 preflight: 121->182
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
