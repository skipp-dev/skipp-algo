"""Defense-pin: silent error swallow ledger + bare-except zero-surface.

Two related "errors disappear into the void" shapes:

* **Bare ``except:``** — catches ``BaseException`` (including
  ``KeyboardInterrupt`` / ``SystemExit``), making Ctrl-C unkillable
  and turning every bug into a silent shrug. Surface today: 0
  sites. Pinned as a hard zero-surface invariant.

* **``except Exception: pass``** — silently swallows every error
    with no log, no re-raise, no marker. Surface today: 7 sites
    across 5 files (mix of opportunistic best-effort cleanup and
    best-effort fallbacks). Pinned as a
    frozen ledger so the count cannot grow without explicit
    acknowledgement.

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

from tests._guard_corpus import parse_module

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
# Frozen ledger — every ``except Exception: pass`` site in production code,
# pinned by **per-file count**. Keys are workspace-relative POSIX paths;
# values are the number of legitimate ``except Exception: pass`` handlers
# in that file.
#
# Why count, not (path, lineno):
#   The previous incarnation of this ledger pinned each handler's exact
#   line number. That made the test break on every unrelated edit that
#   shifted lines (the ingest_benzinga.py ledger broke twice in a single
#   day in 2026-04-30). The policy this pin enforces is *no growth in the
#   silent-swallow surface*, which is fundamentally a count, not a
#   location. Refactors that move a swallow within a file are now no-ops
#   for this guard; net additions / removals still fail closed.
# ---------------------------------------------------------------------------
_FROZEN_SITES: dict[str, int] = {
    "open_prep/alerts.py": 1,
    # 2026-06-14 C-1 (Audit E-2): 2 of the 3 per-bucket calibration swallows
    # were upgraded to logger.debug(exc_info=True); 1 remaining covers the
    # outer retry guard that re-raises on a later path.
    "scripts/generate_smc_micro_base_from_databento.py": 1,
    "smc_tv_bridge/smc_api.py": 1,
    # 2026-05-17 C12.1 ConstraintHitLog wiring: an audit-log write
    # failure must never block a guard decision. See HardConstraintLayer._log.
    "rl/safety/__init__.py": 1,
    # 2026-06-25 feat/benzinga-rss: one measurement_evidence swallow was
    # replaced with logger.debug(exc_info=...); one intentional swallow remains.
    "smc_integration/measurement_evidence.py": 1,
}

_FROZEN_TOTAL = sum(_FROZEN_SITES.values())


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
    return parse_module(path)


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


_PARAMS: list[tuple[str, int]] = sorted(_FROZEN_SITES.items())


@pytest.mark.parametrize(("rel", "expected_count"), _PARAMS, ids=[p[0] for p in _PARAMS])
def test_except_pass_count_pinned_per_file(rel: str, expected_count: int) -> None:
    """Per-file count of silent swallows must equal the frozen count.

    Net additions / removals within a frozen file fail closed. Movements
    of a swallow within the same file are intentionally not flagged —
    the policy this pin enforces is the size of the silent-swallow
    surface, not the exact lines.
    """
    actual_sites = _scan_except_pass_sites()
    actual_count = len(actual_sites.get(rel, set()))
    assert actual_count == expected_count, (
        f"silent ``except Exception: pass`` count drift in {rel}: "
        f"frozen={expected_count}, actual={actual_count}.\n"
        "Either:\n"
        "  (a) handle / log the new error site, or\n"
        "  (b) update the count in _FROZEN_SITES with justification."
    )
