"""Defense-pin: silent error swallow ledger + bare-except zero-surface.

Two related "errors disappear into the void" shapes:

* **Bare ``except:``** — catches ``BaseException`` (including
  ``KeyboardInterrupt`` / ``SystemExit``), making Ctrl-C unkillable
  and turning every bug into a silent shrug. Surface today: 0
  sites. Pinned as a hard zero-surface invariant.

* **``except Exception: pass``** — silently swallows every error
  with no log, no re-raise, no marker. Surface today: 16 sites
  across 12 files (mix of opportunistic best-effort cleanup, data-
  source fallbacks, and Streamlit UI guards). Pinned as a frozen
  ledger so the count cannot grow without explicit acknowledgement.

The ledger is *not* a ban: each existing site can stay. But adding
a new ``except Exception: pass`` requires either (a) actually
handling the error, (b) logging it, or (c) explicitly extending
``_FROZEN_SITES`` here with a justifying comment in the PR.

Defense-only — no production changes. Ledger pattern matches the
hashlib weak-hash pin (#206) and the urllib timeout ledger (#204).
"""

from __future__ import annotations

import ast
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

# ---------------------------------------------------------------------------
# Frozen ledger — every ``except Exception: pass`` site in production code.
# Keys are workspace-relative POSIX paths; values are the linenos of the
# ``except`` clauses themselves. Order is irrelevant; sets give O(1) lookup.
# ---------------------------------------------------------------------------
_FROZEN_SITES: dict[str, frozenset[int]] = {
    "newsstack_fmp/store_sqlite.py": frozenset({176, 283}),
    "open_prep/alerts.py": frozenset({240}),
    "open_prep/macro.py": frozenset({33}),
    "open_prep/run_open_prep.py": frozenset({4511}),
    "open_prep/streamlit_monitor.py": frozenset({75, 126}),
    "scripts/databento_preopen_fast.py": frozenset({574}),
    "scripts/generate_smc_micro_base_from_databento.py": frozenset({1189, 1191, 1239}),
    "scripts/verify_branch_protection.py": frozenset({110}),
    "smc_tv_bridge/smc_api.py": frozenset({85}),
    "streamlit_terminal_alerts.py": frozenset({92}),
    "terminal_spike_scanner.py": frozenset({161}),
}

_FROZEN_TOTAL = sum(len(v) for v in _FROZEN_SITES.values())


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


def _parse(path: Path) -> ast.AST | None:
    try:
        source = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    try:
        return ast.parse(source, filename=str(path))
    except SyntaxError:
        return None


def _is_except_exception_pass(node: ast.ExceptHandler) -> bool:
    """True iff ``except Exception: pass`` (single-statement Pass body)."""
    if not (isinstance(node.type, ast.Name) and node.type.id == "Exception"):
        return False
    return len(node.body) == 1 and isinstance(node.body[0], ast.Pass)


def _scan_except_pass_sites() -> dict[str, set[int]]:
    out: dict[str, set[int]] = {}
    for path in _iter_first_party_py_files():
        tree = _parse(path)
        if tree is None:
            continue
        rel = path.relative_to(ROOT).as_posix()
        for node in ast.walk(tree):
            if isinstance(node, ast.ExceptHandler) and _is_except_exception_pass(node):
                out.setdefault(rel, set()).add(node.lineno)
    return out


def _scan_bare_except_sites() -> list[str]:
    out: list[str] = []
    for path in _iter_first_party_py_files():
        tree = _parse(path)
        if tree is None:
            continue
        rel = path.relative_to(ROOT).as_posix()
        for node in ast.walk(tree):
            if isinstance(node, ast.ExceptHandler) and node.type is None:
                out.append(f"  - {rel}:{node.lineno}  bare except:")
    return out


# ---------------------------------------------------------------------------
# Layer 1: bare except: — zero-surface invariant.
# ---------------------------------------------------------------------------


def test_no_bare_except_clauses() -> None:
    """Bare ``except:`` catches ``BaseException`` — never permitted."""
    findings = _scan_bare_except_sites()
    assert not findings, (
        "bare ``except:`` clause(s) found — catches BaseException "
        "(including KeyboardInterrupt / SystemExit), making Ctrl-C "
        "unkillable and turning every bug into a silent shrug:\n"
        + "\n".join(findings)
        + "\n\nUse ``except Exception:`` (and log!) or a narrower type."
    )


# ---------------------------------------------------------------------------
# Layer 2: ``except Exception: pass`` ledger — frozen, no growth.
# ---------------------------------------------------------------------------


def test_except_exception_pass_total_count_pinned() -> None:
    actual_sites = _scan_except_pass_sites()
    actual_total = sum(len(v) for v in actual_sites.values())
    assert actual_total == _FROZEN_TOTAL, (
        f"silent ``except Exception: pass`` count drifted: "
        f"frozen={_FROZEN_TOTAL}, actual={actual_total}.\n"
        "Each silent swallow either masks a real bug or is a deliberate "
        "best-effort guard. Either:\n"
        "  (a) handle / log the error, or\n"
        "  (b) extend _FROZEN_SITES + _FROZEN_TOTAL with justification."
    )


def test_no_new_except_pass_files() -> None:
    actual_sites = _scan_except_pass_sites()
    new_files = sorted(set(actual_sites) - set(_FROZEN_SITES))
    assert not new_files, (
        "New file(s) with ``except Exception: pass`` not in the ledger:\n  - "
        + "\n  - ".join(new_files)
        + "\n\nAdd to _FROZEN_SITES with justification, or fix the swallow."
    )


def test_no_removed_except_pass_files() -> None:
    actual_sites = _scan_except_pass_sites()
    gone = sorted(set(_FROZEN_SITES) - set(actual_sites))
    assert not gone, (
        "Frozen except-pass file(s) no longer have any silent swallows:\n  - "
        + "\n  - ".join(gone)
        + "\n\nRemove the file from _FROZEN_SITES (also adjust _FROZEN_TOTAL)."
    )


_PARAMS: list[tuple[str, frozenset[int]]] = sorted(_FROZEN_SITES.items())


@pytest.mark.parametrize(("rel", "expected_lines"), _PARAMS, ids=[p[0] for p in _PARAMS])
def test_except_pass_lines_pinned_per_file(rel: str, expected_lines: frozenset[int]) -> None:
    actual_sites = _scan_except_pass_sites()
    actual = actual_sites.get(rel, set())
    drifted = actual ^ expected_lines
    assert not drifted, (
        f"silent ``except Exception: pass`` line drift in {rel}:\n"
        f"  expected lines: {sorted(expected_lines)}\n"
        f"  actual lines:   {sorted(actual)}\n"
        f"  drift:          {sorted(drifted)}\n"
        "Update _FROZEN_SITES if the move is intentional."
    )
