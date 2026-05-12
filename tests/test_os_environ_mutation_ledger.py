"""Defense-pin: ``os.environ[...] = ...`` / ``.setdefault(...)`` site ledger.

Mutating ``os.environ`` at runtime is a quietly dangerous foot-gun:

* It leaks across the rest of the process, the rest of the test session,
  and any subprocess spawned afterwards — invisible action-at-a-distance
  for anything that reads env later (e.g. SSL/CA, SDK auth, Streamlit
  secrets fall-through, NewsAPI cursor, etc.).
* New write sites usually mean a missing config layer or a forgotten
  ``contextlib.ExitStack`` / ``monkeypatch`` in tests.
* Removing a write site is great — but should be acknowledged so the
  ledger stays an accurate map of "where production state escapes".

This module freezes the inventory by ``(file, op, count)`` for the two
mutation classes we observe today:

* ``WRITE``  — ``os.environ[KEY] = VALUE`` (the dangerous one).
* ``SDFLT``  — ``os.environ.setdefault(KEY, VALUE)`` (idempotent;
  still freezes because it is *also* observable across the process).

``.update(...)`` and ``.pop(...)`` are not currently used in first-party
production / script / streamlit code — adding either one will trip
``test_no_new_environ_op_kinds``.

Defense-only — no production code changes.
"""

from __future__ import annotations

import ast
from collections import Counter
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

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
        "tests",
        "SMC++",
    }
)

_OP_WRITE = "WRITE"   # os.environ[K] = V
_OP_SDFLT = "SDFLT"   # os.environ.setdefault(K, V)
_OP_POP = "POP"       # os.environ.pop(K, default)

# Per-file ledger: (rel_path, op_kind) -> exact count.
#
# Convention on this repo today:
#   * WRITE sites are CA-bundle wiring (databento*, open_prep/macro) and
#     Streamlit secrets fall-through into env (streamlit_terminal,
#     open_prep/streamlit_monitor, open_prep/realtime_signals).
#   * SDFLT sites are explicit "respect operator-set value" defaults for
#     NewsAPI / Streamlit / probe scripts.
#   * POP sites belong to the FinnhubClient adapter shim in open_prep/macro.py:
#     ``terminal_finnhub._get`` reads ``FINNHUB_API_KEY`` from the env (not from
#     a parameter), so the FinnhubClient.from_env adapter does a save-set-restore
#     around each call: 1× WRITE on entry, 1× POP (or 1× WRITE) on restore.
#     This pairs with the 2× new WRITE sites in the same finally block.
#
# Adding/removing any site MUST update this ledger in the same PR.
_FROZEN_SITES: dict[tuple[str, str], int] = {
    ("databento_client.py", _OP_WRITE): 1,
    ("databento_volatility_screener.py", _OP_WRITE): 1,
    ("open_prep/macro.py", _OP_WRITE): 3,  # CA-bundle (148) + FinnhubClient save-set-restore (2003, 2012)
    ("open_prep/macro.py", _OP_POP): 1,    # FinnhubClient restore branch when prev was unset (2010)
    ("open_prep/realtime_signals.py", _OP_WRITE): 1,
    ("open_prep/streamlit_monitor.py", _OP_WRITE): 1,
    ("streamlit_terminal.py", _OP_WRITE): 1,
    ("open_prep/streamlit_monitor.py", _OP_SDFLT): 1,
    ("scripts/probe_newsapi_feed_cursor.py", _OP_SDFLT): 1,
    ("streamlit_terminal.py", _OP_SDFLT): 1,
}
_FROZEN_TOTAL = sum(_FROZEN_SITES.values())

# Operator kinds that are not currently used and should not be introduced
# without an explicit ledger entry. Any new kind found here trips a test.
_ALLOWED_OP_KINDS = frozenset({_OP_WRITE, _OP_SDFLT, _OP_POP})


def _iter_first_party_py_files() -> list[Path]:
    out: list[Path] = []
    for path in ROOT.rglob("*.py"):
        try:
            rel_parts = path.relative_to(ROOT).parts
        except ValueError:
            continue
        if any(part in _DIR_EXCLUDE for part in rel_parts):
            continue
        out.append(path)
    return sorted(out)


def _is_os_environ(node: ast.AST) -> bool:
    """True if ``node`` is an ``ast.Attribute`` resolving to ``os.environ``."""
    return (
        isinstance(node, ast.Attribute)
        and node.attr == "environ"
        and isinstance(node.value, ast.Name)
        and node.value.id == "os"
    )


def _scan_file(path: Path) -> Counter[tuple[str, str]]:
    counts: Counter[tuple[str, str]] = Counter()
    try:
        source = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return counts
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError:
        return counts
    rel = path.relative_to(ROOT).as_posix()
    for node in ast.walk(tree):
        # WRITE: os.environ[...] = ...
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if (
                    isinstance(target, ast.Subscript)
                    and _is_os_environ(target.value)
                ):
                    counts[(rel, _OP_WRITE)] += 1
        # SDFLT / other method calls on os.environ
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and _is_os_environ(node.func.value)
        ):
            if node.func.attr == "setdefault":
                counts[(rel, _OP_SDFLT)] += 1
            elif node.func.attr in {"update", "pop", "__setitem__", "clear"}:
                # Treat as a generic write so an unknown-op test trips it.
                counts[(rel, node.func.attr.upper())] += 1
    return counts


def _observed_counts() -> dict[tuple[str, str], int]:
    out: Counter[tuple[str, str]] = Counter()
    for path in _iter_first_party_py_files():
        out.update(_scan_file(path))
    return dict(out)


def test_no_new_environ_op_kinds() -> None:
    """Refuse new mutation kinds (e.g. ``.update``, ``.pop``) without a ledger update."""
    observed = _observed_counts()
    new_kinds = sorted({op for (_, op) in observed} - _ALLOWED_OP_KINDS)
    assert not new_kinds, (
        "New os.environ mutation kind(s) introduced — these escape the "
        "ledger contract:\n"
        + "\n".join(f"  - {op}" for op in new_kinds)
        + "\n\nUpdate _ALLOWED_OP_KINDS + _FROZEN_SITES with rationale, "
        "or refactor to a scoped helper (contextmanager / monkeypatch)."
    )


def test_no_new_environ_mutation_sites() -> None:
    """No new ``(file, op)`` site may appear without a ledger bump."""
    observed = _observed_counts()
    new_sites = sorted(set(observed) - set(_FROZEN_SITES))
    assert not new_sites, (
        "New os.environ mutation site(s) — silent action-at-a-distance:\n"
        + "\n".join(
            f"  - {rel} [{op}] count={observed[(rel, op)]}"
            for (rel, op) in new_sites
        )
        + "\n\nIf the site is genuinely needed, add it to _FROZEN_SITES "
        "in the same PR with a justifying comment."
    )


def test_no_removed_environ_mutation_sites() -> None:
    """A site disappearing is great — drop it from the ledger explicitly."""
    observed = _observed_counts()
    missing = sorted(set(_FROZEN_SITES) - set(observed))
    assert not missing, (
        "Frozen os.environ mutation site(s) no longer present — drop "
        "from _FROZEN_SITES in the same PR:\n"
        + "\n".join(f"  - {rel} [{op}]" for (rel, op) in missing)
    )


@pytest.mark.parametrize(
    "rel,op,expected",
    sorted((rel, op, n) for (rel, op), n in _FROZEN_SITES.items()),
)
def test_frozen_environ_count_still_matches(rel: str, op: str, expected: int) -> None:
    """Per-(file, op) count must match the ledger exactly."""
    path = ROOT / rel
    assert path.is_file(), f"frozen site missing on disk: {rel}"
    actual = _scan_file(path).get((rel, op), 0)
    assert actual == expected, (
        f"os.environ {op} count drifted in {rel}: "
        f"expected {expected}, got {actual}. "
        "Update _FROZEN_SITES in the same PR."
    )


def test_total_environ_mutation_count_pinned() -> None:
    """Aggregate cross-check against per-(file, op) ledger drift."""
    observed = _observed_counts()
    total = sum(observed.values())
    assert total == _FROZEN_TOTAL, (
        f"os.environ mutation total drifted: expected {_FROZEN_TOTAL}, "
        f"got {total}. Per-site = {sorted(observed.items())}"
    )
