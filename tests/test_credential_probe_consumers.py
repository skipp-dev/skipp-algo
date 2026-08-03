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
