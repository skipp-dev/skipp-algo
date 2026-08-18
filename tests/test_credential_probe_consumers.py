"""Cross-consumer guard for ``scripts/credential_health_check.py``.

Regression this prevents
------------------------
``scripts/credential_health_check.py`` is invoked by **more than one**
workflow, and ``overall_severity`` is computed from the probes that
actually RUN. So a probe that returns ``error`` on an empty key breaks
*every* consumer that neither wires the key nor skips the probe — even
consumers that have nothing to do with that provider.

This has now happened three times to ``smc-library-refresh.yml`` alone:

* **2026-07-09 — Benzinga.** Became load-bearing 2026-07-08; the probe
  was not skipped and the key was not wired, so the preflight aborted on
  an empty key and the TV storage refresh failed for three days while
  the capture itself succeeded.
* **2026-08-03 — NewsAPI.** The retired NewsAPI key 401'd and
  permanently blocked the daily refresh (run 30805042119). Fixed by
  #4335; ``smc-library-refresh.yml`` was "the missed third site".
* **2026-08-03 — Composio.** PR #4333 (``5aeda8988``) added
  ``probe_composio_accounts`` to the shared script and wired the Composio
  env block into ``credential-health-check.yml`` — but touched neither of
  the other two consumers. ``smc-library-refresh.yml`` then failed 12
  consecutive runs the same day (every other probe ``ok``;
  ``composio_accounts`` the only ``error``), and
  ``tradingview-storage-refresh.yml`` was green only because it had not
  run since 04:16Z, before #4333 landed.

Why this guard and not the existing one
---------------------------------------
``tests/test_credential_health_workflow.py`` hard-pins a single workflow
path, so it can only ever inspect ``credential-health-check.yml`` — the
one consumer that #4333 *did* update. The blind spot is structural: it
cannot see consumer number two or three.

Two design constraints follow from the #4333 failure mode and are
load-bearing here:

1. **The consumer set is DERIVED, never hand-listed.** A hand-list is
   exactly what made the third consumer invisible; a new workflow that
   invokes the script joins this guard automatically.
2. **This file must sit on the required path unconditionally.** A PR
   that adds a probe to ``credential_health_check.py`` touches *no*
   workflow file, so the diff-driven "Run every guard that reads a
   workflow this PR changed" step in ``smc-fast-pr-gates.yml`` selects
   nothing. Hence the explicit registration in the "Run pin / ledger
   drift guard" step (``fast-gates`` is the only required check —
   ADR-0011), mirrored in
   ``tests/test_fast_gates_silent_skip_coverage.py`` and
   ``tests/_fast_inventory.py``.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import yaml

from scripts.credential_health_check import (
    DATABENTO_TIMEOUT_SECONDS,
    HTTP_TIMEOUT_SECONDS,
    TRANSIENT_RETRY_ATTEMPTS,
    TRANSIENT_RETRY_SLEEP_SECONDS,
    _composio_declared_pins,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_DIR = REPO_ROOT / ".github" / "workflows"
SCRIPT = REPO_ROOT / "scripts" / "credential_health_check.py"

SCRIPT_REF = "credential_health_check.py"
COMPOSIO_KEY_ENV = "COMPOSIO_PROD_API_KEY"

_SKIP_FLAG_RE = re.compile(r"--skip-[a-z0-9-]+")

# Frozen roster of every ``--skip-*`` flag ``credential_health_check.py``
# offers, snapshot 2026-08-03 (post-#4333). This is an INDEPENDENT source
# of truth, deliberately duplicating the script's argparse: adding a probe
# means adding its skip flag, which turns this tuple red until a human
# updates it. That forced edit is the point — it is the moment at which the
# per-consumer decision (wire the credential, or skip the probe) has to be
# made for EVERY workflow in `_consumers()`, which is precisely the step
# #4333 skipped. Do not "fix" a failure here by widening the roster without
# also auditing each consumer below.
EXPECTED_SKIP_FLAGS: tuple[str, ...] = (
    "--skip-benzinga",
    "--skip-composio",
    "--skip-databento",
    "--skip-finnhub",
    "--skip-fmp",
    "--skip-gh-pat",
    "--skip-newsapi",
    "--skip-tv",
)

# Minimum number of workflows known to invoke the script (2026-08-03:
# credential-health-check.yml, smc-library-refresh.yml,
# tradingview-storage-refresh.yml). Non-vacuity witness: a scan that
# silently matches nothing and reports green is the exact failure class
# this repository has been closing, so refuse to pass on an empty corpus.
MIN_CONSUMERS = 3


def _strip_comment(line: str) -> str:
    """Drop a YAML/shell ``#`` comment tail.

    Crude but sufficient here: the invocations this guard reads are plain
    ``python scripts/credential_health_check.py ...`` command lines with no
    ``#`` inside a quoted string. Comments MUST be stripped, because both
    fixed workflows now *discuss* ``--skip-composio`` in prose right next
    to the invocation — a whole-file substring check would pass vacuously
    on the comment alone.
    """
    return line.split("#", 1)[0] if "#" in line else line


def _invocations(text: str) -> list[str]:
    """Every full (line-continuation-joined) invocation of the script."""
    lines = text.splitlines()
    found: list[str] = []
    for index, raw in enumerate(lines):
        code = _strip_comment(raw)
        if SCRIPT_REF not in code:
            continue
        parts = [code.strip()]
        cursor = index
        while parts[-1].endswith("\\") and cursor + 1 < len(lines):
            cursor += 1
            parts[-1] = parts[-1][:-1]
            parts.append(_strip_comment(lines[cursor]).strip())
        found.append(" ".join(part.strip() for part in parts))
    return found


def _consumers() -> dict[str, list[str]]:
    """Map workflow filename -> its invocations of the script.

    DERIVED from the filesystem on purpose — see the module docstring.
    """
    consumers: dict[str, list[str]] = {}
    for path in sorted(WORKFLOW_DIR.glob("*.yml")):
        text = path.read_text(encoding="utf-8")
        invocations = _invocations(text)
        if invocations:
            consumers[path.name] = invocations
    return consumers


def _wires_composio_key(path: Path) -> bool:
    """True if the workflow references the Composio key env outside comments."""
    return any(
        COMPOSIO_KEY_ENV in _strip_comment(raw)
        for raw in path.read_text(encoding="utf-8").splitlines()
    )


def _script_skip_flags() -> set[str]:
    """Every ``--skip-*`` flag registered on the script's own argparse."""
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"), filename=str(SCRIPT))
    flags: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not isinstance(func, ast.Attribute) or func.attr != "add_argument":
            continue
        for arg in node.args:
            if (
                isinstance(arg, ast.Constant)
                and isinstance(arg.value, str)
                and arg.value.startswith("--skip-")
            ):
                flags.add(arg.value)
    return flags


# Wall-clock cost of ONE probed endpoint in the worst case: every attempt
# burns its full timeout and the gaps in between are slept.
#
# HTTP requests per probe. The Databento probe pair (auth + delivery) is the
# only one on the longer timeout — 2026-08-04, #4382: its endpoint's measured
# time-to-first-byte is bimodal (0.4s warm, 17-30s cold), which is what the
# retry and the raised timeout exist for.
_REQUESTS_PER_PROBE: dict[str, int] = {
    "gh-pat": 1,
    "databento": 2,  # probe_databento + probe_databento_delivery
    "fmp": 1,
    "benzinga": 1,
    "finnhub": 1,
    "newsapi": 1,
    # composio: one request per declared account pin — counted below.
}
# probe_tv_storage_state parses a secret, it opens no socket, so it is absent
# here on purpose (and --skip-tv therefore changes nothing in this arithmetic).

# Seconds a consumer's job needs for everything that is NOT probing: checkout,
# pinned-Python setup, report upload, issue filing. Deliberately generous — the
# point of this guard is margin, not a tight fit.
JOB_OVERHEAD_RESERVE_SECONDS = 120


def _worst_case_seconds(timeout: float) -> float:
    """Worst-case wall clock for one endpoint, retries included."""
    return TRANSIENT_RETRY_ATTEMPTS * timeout + (TRANSIENT_RETRY_ATTEMPTS - 1) * (
        TRANSIENT_RETRY_SLEEP_SECONDS
    )


def _probe_budget_seconds(invocation: str) -> float:
    """Worst-case probing time for one ``credential_health_check.py`` command."""
    total = 0.0
    for probe, requests in _REQUESTS_PER_PROBE.items():
        if f"--skip-{probe}" in invocation:
            continue
        timeout = DATABENTO_TIMEOUT_SECONDS if probe == "databento" else HTTP_TIMEOUT_SECONDS
        total += requests * _worst_case_seconds(timeout)
    if "--skip-composio" not in invocation:
        total += len(_composio_declared_pins()) * _worst_case_seconds(HTTP_TIMEOUT_SECONDS)
    return total


def _job_timeouts(path: Path) -> dict[str, int]:
    """Map job id -> ``timeout-minutes`` for every job that runs the script."""
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    jobs = document.get("jobs") if isinstance(document, dict) else None
    if not isinstance(jobs, dict):
        return {}
    timeouts: dict[str, int] = {}
    for job_id, job in jobs.items():
        if not isinstance(job, dict):
            continue
        steps = job.get("steps")
        if not isinstance(steps, list):
            continue
        runs_script = any(
            isinstance(step, dict)
            and SCRIPT_REF in "".join(_strip_comment(line) for line in str(step.get("run", "")).splitlines())
            for step in steps
        )
        if runs_script:
            timeouts[str(job_id)] = job.get("timeout-minutes")
    return timeouts


def test_consumer_scan_is_not_vacuous() -> None:
    """Witness: the derived corpus is non-empty and matches reality."""
    assert SCRIPT.exists(), f"missing probe script: {SCRIPT}"
    consumers = _consumers()
    assert len(consumers) >= MIN_CONSUMERS, (
        f"expected at least {MIN_CONSUMERS} workflows invoking {SCRIPT_REF}, "
        f"found {len(consumers)}: {sorted(consumers)}. Either the scan broke "
        "(then fix _invocations/_consumers — a guard that scans nothing and "
        "reports green is worse than no guard) or consumers were genuinely "
        "removed (then lower MIN_CONSUMERS in the same PR, with a reason)."
    )
    for name, invocations in consumers.items():
        assert invocations, f"{name}: recorded as a consumer with no invocation"


def test_every_consumer_handles_the_composio_probe() -> None:
    """Each consumer must either skip the Composio probe or wire its key.

    ``probe_composio_accounts`` returns ``error`` on an empty key, and an
    empty key is what every workflow that does not wire
    ``COMPOSIO_PROD_API_KEY`` has. Because ``overall_severity`` is derived
    from the probes that RUN, an unhandled probe fails the whole consumer.
    """
    offenders: list[str] = []
    for name, invocations in _consumers().items():
        path = WORKFLOW_DIR / name
        if _wires_composio_key(path):
            continue
        for invocation in invocations:
            if "--skip-composio" not in invocation:
                offenders.append(name)
                break

    assert not offenders, (
        f"{sorted(offenders)} invoke {SCRIPT_REF} without handling the "
        "Composio probe. probe_composio_accounts returns severity=error on an "
        f"empty {COMPOSIO_KEY_ENV}, so overall_severity becomes 'error' and the "
        "job aborts. Pick exactly one remedy per workflow:\n"
        "  (a) the workflow does NOT use Composio -> add '--skip-composio' to "
        "the credential_health_check.py invocation (preferred; do not hand a "
        "workflow a credential it never uses), or\n"
        f"  (b) the workflow DOES use Composio -> wire {COMPOSIO_KEY_ENV} (plus "
        "COMPOSIO_ENVIRONMENT and the account-id envs) into the step, as "
        "credential-health-check.yml does.\n"
        "This is the #4333 regression: 12 failed smc-library-refresh runs on "
        "2026-08-03, every other probe ok."
    )


def test_retry_budget_fits_inside_every_consumer_job_timeout() -> None:
    """The retry must not convert a vendor outage into a hard job timeout.

    2026-08-04 (#4382): the probes now retry the inconclusive
    network/timeout class and give Databento a 30s timeout, because a valid
    key was reported as ``warn`` on four separate days. That buys quiet at the
    cost of wall clock, and the daily cron probes every endpoint SERIALLY
    inside one ``timeout-minutes``. Cross a job timeout and the failure mode
    flips from "warn issue nobody needed" to "red cron with no report at all"
    — strictly worse. So the arithmetic is a guard, not a comment: raising
    :data:`TRANSIENT_RETRY_ATTEMPTS` or a timeout without raising the job
    budget fails here, on the required path, before it fails in production.
    """
    checked = 0
    for name, invocations in _consumers().items():
        path = WORKFLOW_DIR / name
        timeouts = _job_timeouts(path)
        assert timeouts, (
            f"{name} invokes {SCRIPT_REF} but no job could be matched to it — "
            "the YAML walk in _job_timeouts broke, so this budget guard is "
            "vacuous for that consumer. Fix the walk."
        )
        for job_id, timeout_minutes in timeouts.items():
            assert timeout_minutes is not None, (
                f"{name}:{job_id} runs {SCRIPT_REF} with no timeout-minutes — "
                "an unbounded job cannot be budgeted. Set one."
            )
            budget = max(_probe_budget_seconds(invocation) for invocation in invocations)
            available = timeout_minutes * 60 - JOB_OVERHEAD_RESERVE_SECONDS
            assert budget <= available, (
                f"{name}:{job_id} — worst-case probing needs {budget:.0f}s but the job "
                f"allows {timeout_minutes}min minus {JOB_OVERHEAD_RESERVE_SECONDS}s "
                f"overhead = {available:.0f}s. Every vendor being unreachable would "
                "kill the job before it can report anything. Either raise "
                f"timeout-minutes on {name}:{job_id}, or lower "
                "TRANSIENT_RETRY_ATTEMPTS / the probe timeouts."
            )
            checked += 1
    assert checked >= MIN_CONSUMERS, (
        f"budgeted only {checked} job(s); expected at least {MIN_CONSUMERS} — "
        "the scan silently lost consumers."
    )


def test_probe_request_map_covers_every_skippable_network_probe() -> None:
    """Keep the budget arithmetic honest when a probe is added.

    A new vendor probe means a new ``--skip-*`` flag; if it is not accounted
    for in :data:`_REQUESTS_PER_PROBE` the budget above silently under-counts
    and the guard degrades into decoration.
    """
    skippable = {flag.removeprefix("--skip-") for flag in _script_skip_flags()}
    # tv parses a secret and composio is counted from the declared pins.
    network_probes = skippable - {"tv", "composio"}
    missing = sorted(network_probes - set(_REQUESTS_PER_PROBE))
    stale = sorted(set(_REQUESTS_PER_PROBE) - network_probes)
    assert not missing and not stale, (
        f"_REQUESTS_PER_PROBE drifted from the script's probes: missing={missing} "
        f"stale={stale}. Add the probe's HTTP request count (and its timeout, if it "
        "is not the default) so the job-timeout budget stays truthful."
    )
    assert _composio_declared_pins(), (
        "zero Composio pins parsed — the budget would ignore the probe that "
        "issues the most requests. Check configs/composio_auth_policy.json."
    )


def test_script_skip_flag_roster_is_frozen() -> None:
    """Pin the script's ``--skip-*`` surface so new probes force a decision.

    Adding a probe to ``credential_health_check.py`` normally touches no
    workflow, so nothing in the diff-driven guard selection reacts. This
    test does: the new flag makes the derived set differ from
    :data:`EXPECTED_SKIP_FLAGS` and fails on the required path. Updating the
    roster is the prompt to walk every consumer in :func:`_consumers` and
    decide, per workflow, wire-the-credential vs skip-the-probe.
    """
    actual = _script_skip_flags()
    assert actual, (
        f"parsed zero '--skip-*' flags out of {SCRIPT} — the AST scan broke "
        "(argparse refactored?), so this guard is vacuous. Fix the scan."
    )
    expected = set(EXPECTED_SKIP_FLAGS)
    added = sorted(actual - expected)
    removed = sorted(expected - actual)
    assert not added and not removed, (
        f"{SCRIPT_REF} skip-flag roster drifted: added={added} removed={removed}.\n"
        "If you ADDED a probe: for every workflow in "
        f"{sorted(_consumers())} decide whether it wires that provider's "
        "credential or passes the new --skip flag, apply it, and only THEN add "
        "the flag to EXPECTED_SKIP_FLAGS in this file. Skipping that walk is "
        "exactly what #4333 did and it cost 12 failed production runs.\n"
        "If you REMOVED a probe: drop the flag from EXPECTED_SKIP_FLAGS and "
        "from every consumer invocation that still passes it (an unknown flag "
        "makes argparse exit 2)."
    )


def test_shell_consumers_skip_every_probe_except_tv() -> None:
    """Shell consumers live outside the workflow glob — derive them too.

    2026-08-18 (Doppelgaenger-Sweep E4): ``_consumers()`` above derives the
    consumer set from ``.github/workflows/*.yml`` only. The operator rotation
    script ``scripts/tv_rotate_storage_state_secret.sh`` is a fourth consumer
    whose comment claimed it mirrored the CI invocation "verbatim, including
    every --skip" — measured, it was missing ``--skip-composio``, so the probe
    class that produced 12 failed runs on 2026-08-03 (#4333/#4363) could veto
    an unrelated TV rotation. The #4333 shape, one consumer to the right.

    Contract enforced here: a shell consumer of the probe script exists to
    check exactly ONE probe (the TV cookie), so it must skip every other
    probe the script grows. A future shell consumer with a different purpose
    will fail this test — that failure is the forced per-consumer decision
    this module's docstring demands, not noise; split the assertion by
    consumer name when that day comes.
    """
    shell_paths = sorted((REPO_ROOT / "scripts").glob("*.sh")) + sorted(
        (REPO_ROOT / "automation" / "launchd").glob("*.sh")
    )
    consumers: dict[str, list[str]] = {}
    for path in shell_paths:
        invocations = _invocations(path.read_text(encoding="utf-8"))
        if invocations:
            consumers[path.name] = invocations
    assert consumers, (
        "zero shell consumers of credential_health_check.py found — the glob "
        "went vacuous (script moved or renamed?); this guard must scan the "
        "operator scripts, not silently pass on an empty corpus."
    )

    expected = _script_skip_flags() - {"--skip-tv"}
    for name, invocations in consumers.items():
        for invocation in invocations:
            present = {flag for flag in _script_skip_flags() if flag in invocation}
            missing = sorted(expected - present)
            assert not missing, (
                f"{name} invokes the probe script without {missing}. A shell "
                "consumer probes ONLY the TV cookie; every other probe must be "
                "skipped or an unrelated expired key blocks the TV rotation."
            )
