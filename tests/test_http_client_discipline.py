"""Audit pins: HTTP client discipline in production modules.

Two sibling pins enforced over the same first-party AST walk:

1. **No ``requests`` library** in production.

   The codebase standardised on ``httpx`` (with the budget × singleton ×
   timeout-consistency × named-timeout Quartett pinned elsewhere).
   Any new ``import requests`` / ``from requests import ...`` / call to
   ``requests.<method>(...)`` would silently bypass that discipline.
   This pin freezes the inventory at zero — no allowlist.

2. **``urlopen()`` must pass ``timeout=``** in production.

    ``urllib.request.urlopen`` defaults to a *blocking* socket with no
    timeout, which can wedge a worker thread indefinitely.  All current
    production sites already pass ``timeout=``; this pin freezes that
    invariant.  Detection covers both bound forms:

   * ``urlopen(req, timeout=...)``  (after ``from urllib.request import urlopen``)
   * ``urllib.request.urlopen(req, timeout=...)``
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from tests._guard_corpus import parse_module

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


def _iter_prod_files() -> list[Path]:
    out: list[Path] = []
    for path in _REPO_ROOT.rglob("*.py"):
        rel = path.relative_to(_REPO_ROOT)
        rel_posix = rel.as_posix()
        if any(part in _DIR_EXCLUDE for part in rel.parts) and rel_posix != "scripts/publish_overlay_dashboard.py":
            continue
        out.append(path)
    return sorted(out)


# ---------------------------------------------------------------------------
# Pin 1: no ``requests`` library in production.
# ---------------------------------------------------------------------------


def _requests_violations(tree: ast.AST) -> list[tuple[int, str]]:
    hits: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".", 1)[0]
                if root == "requests":
                    hits.append((node.lineno, f"import {alias.name}"))
        elif isinstance(node, ast.ImportFrom):
            if node.module and node.module.split(".", 1)[0] == "requests":
                hits.append((node.lineno, f"from {node.module} import ..."))
        elif isinstance(node, ast.Call):
            func = node.func
            if (
                isinstance(func, ast.Attribute)
                and isinstance(func.value, ast.Name)
                and func.value.id == "requests"
            ):
                hits.append((node.lineno, f"requests.{func.attr}(...)"))
    return hits


def test_no_requests_library_in_production() -> None:
    """Tripwire: ``requests`` library must not appear in production modules."""
    violations: list[str] = []
    for path in _iter_prod_files():
        rel = path.relative_to(_REPO_ROOT).as_posix()
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError as exc:  # pragma: no cover - defensive
            violations.append(f"{rel}: parse error {exc!r}")
            continue
        for lineno, label in _requests_violations(tree):
            violations.append(
                f"{rel}:{lineno}: {label} — codebase uses httpx; do not "
                f"reintroduce the ``requests`` library (bypasses httpx "
                f"timeout/budget/singleton discipline)."
            )
    assert not violations, (
        "Production ``requests`` library usage detected:\n  - "
        + "\n  - ".join(violations)
    )


# ---------------------------------------------------------------------------
# Pin 2: every prod ``urlopen()`` call must pass ``timeout=``.
# ---------------------------------------------------------------------------


def _is_urlopen_call(node: ast.Call) -> bool:
    func = node.func
    # Bare ``urlopen(...)`` (after ``from urllib.request import urlopen``).
    if isinstance(func, ast.Name) and func.id == "urlopen":
        return True
    # ``urllib.request.urlopen(...)``.
    return bool(
        isinstance(func, ast.Attribute)
        and func.attr == "urlopen"
        and isinstance(func.value, ast.Attribute)
        and func.value.attr == "request"
        and isinstance(func.value.value, ast.Name)
        and func.value.value.id == "urllib"
    )


def _has_timeout_kwarg(node: ast.Call) -> bool:
    return any(kw.arg == "timeout" for kw in node.keywords)


# Frozen inventory of compliant urlopen call sites at the time this pin
# landed.  Used by the stale-site guard below.  Extend deliberately when
# new compliant sites are added (or removed when a site moves).
_FROZEN_URLOPEN_SITES: frozenset[tuple[str, int]] = frozenset(
    {
        ("databento_universe.py", 306),
        # 2026-05-23 PR #2338: shifted +35 (1263→1298) by partial-cache
        # marker / coverage-validation block in _load_daily_bars.
        # PR #2339: +115 (1298→1413) by universe-version metadata helpers and
        # drift detector block above build_cache_path; later +10 (1413→1423)
        # by the explicit missing-symbols-key warn-and-refetch branch added
        # to ``_load_cache_with_drift_check``.
        # 2026-06-10: +5 (1423→1428).
        ("databento_volatility_screener.py", 1430),
        ("open_prep/bea.py", 94),
        # open_prep/macro.py:691 — shifted by ruff RUF046/B904/SIM103 cleanup;
        # was 692 after audit/discipline-pattern-v4 (originally 600).
        # Shifted by +92 lines: ``import re`` at module top (+1), the
        # _HTTP_CODE_RE / _TRANSIENT_HTTP_CODES classifier constants (+8),
        # the ``_is_permanent_feature_failure`` helper (+~30), the
        # extended ``_log_feature_unavailable_once`` signature with
        # transient/permanent dispatch (+~50), and the math import + NaN
        # guard in ``_parse_retry_after_seconds``. The urlopen call itself
        # is unchanged (still ``timeout=...``).
        # 2026-05-12 PR #2154: shifted +5 (704→709) by FMP-13F probe
        # instrumentation block in macro.py.
        # 2026-06-11 (eval-findings B8): surprise-scale comment +8 (713→721).
        # 2026-06-13: profile-bulk pagination constant shifted +1 (721→722).
        ("open_prep/macro.py", 740),  # R-E2 (2026-06-14): +14 from TLS lock guard; +1 iteration-limit; +3 rebase
        ("open_prep/sentiment_fng.py", 100),
        ("terminal_finnhub.py", 245),
        ("terminal_notifications.py", 255),
        ("terminal_notifications.py", 319),
        ("terminal_tradingview_news.py", 423),
        # 2026-06-21: live-overlay external bridge polling via urllib with
        # explicit timeout discipline.
        ("services/live_overlay_daemon/github_workflow_bridge.py", 101),
        ("services/live_overlay_daemon/uptimerobot_bridge.py", 76),
        # 2026-06-22: Grafana dashboard publisher API upsert over urllib.
        ("scripts/publish_overlay_dashboard.py", 212),
    }
)


def _all_urlopen_sites() -> list[tuple[str, int, ast.Call]]:
    sites: list[tuple[str, int, ast.Call]] = []
    for path in _iter_prod_files():
        rel = path.relative_to(_REPO_ROOT).as_posix()
        tree = parse_module(path)
        if tree is None:  # pragma: no cover - defensive
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and _is_urlopen_call(node):
                sites.append((rel, node.lineno, node))
    return sites


def test_urlopen_calls_pass_timeout() -> None:
    """Every production ``urlopen(...)`` call must pass ``timeout=``."""
    violations: list[str] = []
    for rel, lineno, node in _all_urlopen_sites():
        if not _has_timeout_kwarg(node):
            violations.append(
                f"{rel}:{lineno}: urlopen(...) without ``timeout=`` — "
                f"add an explicit timeout (urllib defaults to blocking, "
                f"which can wedge a worker thread indefinitely)."
            )
    assert not violations, (
        "urllib urlopen timeout discipline violations:\n  - "
        + "\n  - ".join(violations)
    )


def test_no_new_urlopen_sites() -> None:
    """Tripwire: any new ``urlopen`` site requires explicit ledger update."""
    current = {(rel, lineno) for rel, lineno, _ in _all_urlopen_sites()}
    new_sites = sorted(current - _FROZEN_URLOPEN_SITES)
    assert not new_sites, (
        "New urlopen call site detected — extend _FROZEN_URLOPEN_SITES "
        "after confirming the call passes timeout=:\n  - "
        + "\n  - ".join(f"{rel}:{lineno}" for rel, lineno in new_sites)
    )


@pytest.mark.parametrize(("rel", "lineno"), sorted(_FROZEN_URLOPEN_SITES))
def test_frozen_urlopen_site_still_present(rel: str, lineno: int) -> None:
    """Stale guard: every frozen site must still be a ``urlopen`` call."""
    path = _REPO_ROOT / rel
    assert path.is_file(), f"{rel} no longer exists — refresh frozen ledger"
    tree = parse_module(path)
    assert tree is not None, f"{rel} no longer parses — refresh frozen ledger"
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and node.lineno == lineno
            and _is_urlopen_call(node)
        ):
            assert _has_timeout_kwarg(node), (
                f"{rel}:{lineno}: urlopen(...) lost its timeout= kwarg"
            )
            return
    raise AssertionError(
        f"{rel}:{lineno} is no longer a urlopen(...) call — refresh "
        f"_FROZEN_URLOPEN_SITES."
    )


def test_prod_file_inventory_sane() -> None:
    """Path-drift sanity: production scan must find a non-trivial set."""
    files = _iter_prod_files()
    assert len(files) >= 50, (
        f"Production *.py scan only found {len(files)} files — "
        f"_DIR_EXCLUDE may be over-broad or sparse-checkout incomplete."
    )
