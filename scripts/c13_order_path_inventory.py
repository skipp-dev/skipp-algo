"""Derive the C13 paper-submit ORDER-PATH file inventory.

The deploy-hygiene guard in ``automation/launchd/run-c13-phase-a.sh`` publishes
how many commits the order path is behind ``origin/main``
(``submit_code_behind_commits`` -> the ``C13 submitter on stale checkout``
alert). Until 2026-08-18 (Doppelgaenger-Sweep E1) that guard measured a
HAND-LISTED set of five files while the real order path was the import closure
of its entry points — 80+ Python files plus the sourced ET-gate library and the
risk-limits config. A fix landing in ``scripts/live_risk_limits.py`` (or the ET
window itself) kept ``behind=0`` and the alert silent: exactly the silent
deploy gap the guard was built for (#3297), one import level deeper.

This module IS the derivation. It walks the first-party import closure of the
submit entry points and adds the non-Python order-path files the closure cannot
see. The driver consumes its stdout (one repo-relative path per line);
``tests/test_c13_order_path_inventory.py`` pins the population.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# The scripts the driver actually executes on the submit path.
ENTRY_POINTS: tuple[str, ...] = (
    "scripts/build_phase_a_inputs.py",
    "scripts/run_smc_live_incubation.py",
    "scripts/smc_to_ibkr_adapter.py",
    "scripts/execute_ibkr_watchlist.py",
    "scripts/c13_eod_flatten.py",
)

# Order-path files no Python import can reach: every launchd driver that
# invokes a submit entry point, every shell library they source (the ET gate
# decides WHETHER orders are placed at all), and the CLI-referenced configs
# that decide whether and how large an order goes out.
#
# 2026-08-19 (Geburtsfehler-Sweep A): born with the phase-a driver only. The
# commercial pilot is the SECOND paper submitter — run-c13-commercial-shadow.sh
# runs the real submitter (--place-paper-orders --prospective-paper-pilot)
# behind its double interlock — and neither its driver nor its interlock config
# was in the population. Measured that day: five merged commits that changed
# exactly that submitter (#4769 which created it, #4785, #4790, #4792, #4799
# "harden against duplicate submits", #4833, #4870) each counted as 0, so a Mac
# sitting on any of them kept submit_code_behind_commits=0 and the
# "C13 submitter on stale checkout" alert silent — the #3297 gap one driver
# over. tests/test_c13_order_path_inventory.py now DERIVES the driver set, so
# a future submitting driver cannot be forgotten here.
NON_PYTHON_ORDER_PATH: tuple[str, ...] = (
    "automation/launchd/run-c13-phase-a.sh",
    "automation/launchd/run-c13-eod-flatten.sh",
    "automation/launchd/run-c13-commercial-shadow.sh",
    "automation/launchd/lib_c13_et_gate.sh",
    "automation/launchd/lib_c13_data_push.sh",
    "configs/portfolio_risk_limits.json",
    "configs/commercial_paper_submission.json",
)


def _module_candidates(module: str, names: tuple[str, ...]) -> list[Path]:
    """Repo paths a ``from module import names`` statement may resolve to."""
    base = module.replace(".", "/")
    candidates = [REPO_ROOT / f"{base}.py", REPO_ROOT / base / "__init__.py"]
    for name in names:
        candidates.append(REPO_ROOT / base / f"{name}.py")
    return candidates


def _imports_of(path: Path) -> set[Path]:
    """First-party files imported by ``path`` (absolute imports only —

    the repo's production modules import via top-level package paths).
    """
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError):
        return set()
    found: set[Path] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            specs = [(alias.name, ()) for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            specs = [(node.module, tuple(alias.name for alias in node.names))]
        else:
            continue
        for module, names in specs:
            for candidate in _module_candidates(module, names):
                if candidate.is_file() and candidate.is_relative_to(REPO_ROOT):
                    found.add(candidate)
    return found


def order_path_files() -> tuple[str, ...]:
    """The full derived order-path population, repo-relative and sorted."""
    seen: set[Path] = set()
    queue = [REPO_ROOT / entry for entry in ENTRY_POINTS]
    while queue:
        current = queue.pop()
        if current in seen or not current.is_file():
            continue
        seen.add(current)
        queue.extend(_imports_of(current))
    files = {path.relative_to(REPO_ROOT).as_posix() for path in seen}
    files.update(NON_PYTHON_ORDER_PATH)
    return tuple(sorted(files))


def main() -> int:
    files = order_path_files()
    # Anti-vacuity floor: the real closure is 80+ files. A tiny result means
    # the derivation broke (moved entry point, parse failure) — refuse to emit
    # a list that would make the freshness guard silently blind again.
    if len(files) < 20:
        print(
            f"c13_order_path_inventory: derivation collapsed to {len(files)} "
            "files — refusing to emit a blind inventory",
            file=sys.stderr,
        )
        return 1
    print("\n".join(files))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
