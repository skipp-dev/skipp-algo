"""Lint-debt no-regression gate (issue #1855).

Six lint rules are intentionally in the global ``ignore`` list in
``pyproject.toml`` — the Pine-style identifier rules (``N802``/``N803``/
``N806``) and the readability rules (``SIM102``/``SIM105``/``SIM108``).
``ruff check .`` therefore stays green while violations of them accumulate.
Issue #1855 tracked their manual cleanup, but new code kept *adding*
violations faster than cleanup removed them (e.g. N806 111 -> 124, N802
16 -> 27 between 2026-06-13 and 2026-07-12).

This gate caps each rule at its current count so new code cannot ADD
violations. Cleanup that *lowers* a count always passes; when a count
drops, lower the matching :data:`_BASELINE` entry to ratchet the cap down
(the test prints the suggested new values). Never raise a cap to
accommodate a new violation — fix it, or, for a genuinely intentional
Pine-style identifier, add a targeted ``# noqa: <RULE>``.

The rules stay globally ignored, so ``ruff check .`` is unaffected; this
test re-runs ruff with ``--select <rules> --config lint.ignore=[]`` purely
to count them. It invokes ruff via ``sys.executable -m ruff`` so the count
matches the version fast-gates uses (``requirements.txt``: ruff==0.15.16;
counts verified identical under 0.15.16 and 0.15.20).
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent

# Per-rule caps = counts on main (2026-07-12). Lower after cleanup; never raise.
_BASELINE: dict[str, int] = {
    "N802": 27,   # invalid-function-name (pytest helpers / IBKR API mocks)
    "N803": 61,   # invalid-argument-name (Pine-style args)
    "N806": 124,  # non-lowercase-variable-in-function (Pine-style locals)
    "SIM102": 9,  # collapsible-if
    "SIM105": 11,  # suppressible-exception
    "SIM108": 23,  # if-else-block-instead-of-if-exp
}


def _current_counts() -> dict[str, int]:
    """Count live violations of the tracked (globally-ignored) rules."""
    proc = subprocess.run(
        [
            sys.executable, "-m", "ruff", "check", ".",
            "--select", ",".join(sorted(_BASELINE)),
            "--config", "lint.ignore=[]",
            "--output-format", "json",
        ],
        cwd=str(_REPO_ROOT),
        capture_output=True,
        text=True,
        check=False,  # ruff exits 1 when violations exist; JSON still on stdout
        timeout=180,
    )
    payload = proc.stdout.strip()
    if not payload:
        raise AssertionError(
            f"ruff produced no JSON (rc={proc.returncode}); stderr:\n{proc.stderr}"
        )
    counts = dict.fromkeys(_BASELINE, 0)
    for violation in json.loads(payload):
        code = violation.get("code")
        if code in counts:
            counts[code] += 1
    return counts


def test_tracked_lint_rules_do_not_regress() -> None:
    counts = _current_counts()

    regressions = {
        rule: (counts[rule], cap)
        for rule, cap in _BASELINE.items()
        if counts[rule] > cap
    }
    assert not regressions, (
        "New violations were added in globally-ignored lint rules (#1855). "
        "Fix them, or for a genuinely intentional Pine-style identifier add a "
        "targeted `# noqa: <RULE>`:\n"
        + "\n".join(
            f"  {rule}: {now} > cap {cap} (+{now - cap})"
            for rule, (now, cap) in sorted(regressions.items())
        )
    )

    # Cleanup happened — nudge (not a failure) to ratchet the caps down.
    improved = {
        rule: (counts[rule], cap)
        for rule, cap in _BASELINE.items()
        if counts[rule] < cap
    }
    if improved:
        print(
            "Lint debt reduced — lower these _BASELINE caps to lock in the gain: "
            + ", ".join(
                f"{rule} {cap}->{now}" for rule, (now, cap) in sorted(improved.items())
            )
        )
