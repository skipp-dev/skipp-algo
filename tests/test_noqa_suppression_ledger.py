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
# * ``smc_integration/release_policy.py``: invokes ``git rev-parse HEAD``
#   via a ``shutil.which("git")``-resolved executable with a hardcoded
#   argv list. Bandit S603 is a false positive.
#
# All other first-party noqa suppressions remain forbidden.
_FROZEN_SITES: dict[str, int] = {
    "streamlit_terminal_alerts.py": 1,
    "scripts/scan_manifests_for_pytest_provenance.py": 3,
    "governance/run_manifest.py": 1,
    "open_prep/realtime_signals.py": 2,
    "scripts/ib_client_id.py": 2,
    "scripts/measure_databento_ops_run.py": 1,
    "scripts/smc_micro_publish_guard.py": 1,
    "scripts/smc_zone_priority_calibration.py": 1,
    "scripts/start_open_prep_suite.py": 3,
    "smc_integration/release_policy.py": 1,
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
