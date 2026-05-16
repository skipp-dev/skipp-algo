"""Audit pin: ``# noqa`` frozen-inventory budget with code-set capture.

Every ``# noqa`` is a deliberate lint suppression. We freeze the
current inventory (27 sites) so that:

* New ``# noqa`` additions trip ``test_no_new_noqa_sites`` and force a
  deliberate review (could the code be fixed instead of suppressed?).
* The exact ruff/flake8 code set is captured per site — silently
  widening a suppression (e.g. adding ``F811`` to an existing ``# noqa:
  F401``) trips the parametrised stale-site guard.
* Bare ``# noqa`` (no code list) is allowed but recorded as ``()``.

Categories observed in the current ledger:

* ``F401`` — re-export-only `__init__.py` imports (``terminal_tabs``).
* ``E402`` — deferred imports after sys.path manipulation / atexit.
* ``F401, F811`` — typing-only optional imports (``terminal_bitcoin``).
* ``PLW0603`` — module-singleton ``global`` (already pinned via
  ``test_global_statement_budget.py``).
* ``PERF203`` — explicit retry-loop ``try/except`` shape.
* ``ANN001`` — `*args, **kwargs` callback signature.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent

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
        "scripts",
        "tests",
        "SMC++",
    }
)

# Match ``noqa`` (bare) or ``noqa: CODE[, CODE...]`` markers in source.
# Codes are ASCII letters + digits with optional commas/spaces between.
_NOQA_RE = re.compile(r"#\s*noqa(?::\s*([A-Z0-9, ]+))?")


def _iter_prod_files() -> list[Path]:
    out: list[Path] = []
    for path in _REPO_ROOT.rglob("*.py"):
        if any(part in _DIR_EXCLUDE for part in path.relative_to(_REPO_ROOT).parts):
            continue
        out.append(path)
    return sorted(out)


def _parse_codes(raw: str | None) -> tuple[str, ...]:
    if not raw:
        return ()
    return tuple(sorted({c.strip() for c in raw.split(",") if c.strip()}))


def _all_sites() -> list[tuple[str, int, tuple[str, ...]]]:
    out: list[tuple[str, int, tuple[str, ...]]] = []
    for path in _iter_prod_files():
        rel = path.relative_to(_REPO_ROOT).as_posix()
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:  # pragma: no cover - defensive
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            match = _NOQA_RE.search(line)
            if match:
                out.append((rel, lineno, _parse_codes(match.group(1))))
    return out


# Frozen inventory of noqa-suppression sites at the time this pin landed.
# Each tuple is ``(rel, lineno, sorted-code-tuple)``.
#
# As of the RUF100 cleanup wave (April 2026), the codebase contains a
# small set of intentional first-party noqa suppressions. The
# ledger remains as a tripwire: any new suppression will trip
# ``test_no_new_noqa_sites`` and force a deliberate review + ledger
# update in the same PR.
#
# Sister ledger ``test_noqa_suppression_ledger.py`` carries the same
# entries with explanatory rationale; both must be kept in sync.
_FROZEN_SITES: frozenset[tuple[str, int, tuple[str, ...]]] = frozenset(
    {
        # streamlit_terminal_alerts.py:76 — Bandit S104 false positive:
        # validates a webhook URL host string ("0.0.0.0") rather than
        # binding a server.
        ("streamlit_terminal_alerts.py", 76, ("S104",)),
        # governance/run_manifest.py:73 — Bandit S603 false positive:
        # subprocess.check_output called with a ``shutil.which("git")``
        # executable and a hardcoded argv list. No untrusted input.
        ("governance/run_manifest.py", 73, ("S603",)),
        # open_prep/realtime_signals.py:187,333 — Bandit S603 false
        # positives: hardcoded pgrep / sys.executable -m argv lists.
        ("open_prep/realtime_signals.py", 187, ("S603",)),
        ("open_prep/realtime_signals.py", 333, ("S603",)),
        # smc_integration/release_policy.py:1072 — Bandit S603 false
        # positive: ``git rev-parse HEAD`` via shutil.which("git").
        ("smc_integration/release_policy.py", 1085, ("S603",)),
        # open_prep/streamlit_monitor.py:205 — module-import-time hardening:
        # the OPRA-options-flow integration is wrapped in a try/except so
        # that ImportError, env-parse ValueError, or any other startup
        # failure degrades gracefully and keeps streamlit_monitor
        # importable. BLE001 noqa documents the deliberate broad catch.
        ("open_prep/streamlit_monitor.py", 205, ("BLE001",)),
        # E402 outliers — late imports after sys.path/streamlit setup
        # blocks that pyproject's per-file-ignores cannot easily cover
        # without disabling E402 for too-broad surface area.
        ("databento_volatility_screener.py", 123, ("E402",)),
        ("newsstack_fmp/pipeline.py", 1183, ("E402",)),
        ("open_prep/run_open_prep.py", 472, ("E402",)),
        ("smc_tv_bridge/smc_api.py", 176, ("E402", "I001")),
    }
)


def test_no_new_noqa_sites() -> None:
    """Tripwire: every new ``# noqa`` deserves a deliberate review."""
    current = set(_all_sites())
    new_sites = sorted(current - _FROZEN_SITES)
    assert not new_sites, (
        "New ``# noqa`` suppression detected — could the underlying lint "
        "be fixed instead? If suppression is genuinely required, extend "
        "_FROZEN_SITES with the (file, line, sorted-codes) tuple:\n  - "
        + "\n  - ".join(
            f"{rel}:{lineno} {codes}" for rel, lineno, codes in new_sites
        )
    )


@pytest.mark.parametrize(
    ("rel", "lineno", "codes"),
    sorted(_FROZEN_SITES),
)
def test_frozen_noqa_site_still_present(
    rel: str, lineno: int, codes: tuple[str, ...]
) -> None:
    """Stale guard: every ledger entry must still match a ``# noqa`` with the same code set."""
    path = _REPO_ROOT / rel
    assert path.is_file(), f"{rel} no longer exists — refresh frozen ledger"
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    assert 1 <= lineno <= len(lines), (
        f"{rel}:{lineno} is past EOF (file has {len(lines)} lines)"
    )
    match = _NOQA_RE.search(lines[lineno - 1])
    assert match, (
        f"{rel}:{lineno}: ``# noqa`` no longer present — "
        f"refresh _FROZEN_SITES (suppression may have moved or been removed)."
    )
    actual = _parse_codes(match.group(1))
    assert actual == codes, (
        f"{rel}:{lineno}: ``# noqa`` code set changed "
        f"(expected {codes!r}, found {actual!r}) — refresh _FROZEN_SITES."
    )


def test_noqa_inventory_parity() -> None:
    """Bidirectional parity: ledger ∪ scan must be identical."""
    current = set(_all_sites())
    missing_from_ledger = current - _FROZEN_SITES
    stale_in_ledger = _FROZEN_SITES - current
    assert not missing_from_ledger and not stale_in_ledger, (
        f"# noqa ledger drift: "
        f"new={sorted(missing_from_ledger)} "
        f"stale={sorted(stale_in_ledger)}"
    )


def test_prod_file_inventory_sane() -> None:
    files = _iter_prod_files()
    assert len(files) >= 50, (
        f"Production *.py scan only found {len(files)} files — "
        f"_DIR_EXCLUDE may be over-broad or sparse-checkout incomplete."
    )
