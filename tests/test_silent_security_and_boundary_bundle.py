"""Defense-pin bundle: silent-security tripwires + library boundaries.

Six independent guards over first-party production Python:

1. **TLS verify=False** — banned in any call kwargs (httpx/requests).
   Inventory 0, pure tripwire.

2. **tempfile.mktemp** — race-condition prone, replaced by mkstemp().
   Inventory 0, pure tripwire.

3. **stdlib xml.* imports** — XXE-vulnerable; use defusedxml instead.
   Inventory 0, pure tripwire.

4. **warnings.simplefilter("ignore") / filterwarnings("ignore")** in
   production code — hides Deprecation/Runtime warnings. Inventory 0,
   pure tripwire.

5. **logging.basicConfig(...)** frozen 7-site ledger — must be confined
   to entry-point scripts. Library modules must not configure the root
   logger.

6. **sys.path.insert / sys.path.append** frozen 6-site ledger — path
   hacks confined to known Streamlit/SMC bridge entry-point shims.

Defense-only — no production changes.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from tests._guard_corpus import parse_module

ROOT = Path(__file__).resolve().parents[1]

_DIR_EXCLUDE = frozenset({
    ".git", ".github", ".mypy_cache", ".pytest_cache", ".ruff_cache",
    ".venv", "venv", "node_modules", "artifacts", "docs", "scripts",
    "tests", "SMC++",
})


def _iter_prod_py() -> list[Path]:
    out: list[Path] = []
    for p in sorted(ROOT.rglob("*.py")):
        rel_parts = p.relative_to(ROOT).parts
        if any(part in _DIR_EXCLUDE for part in rel_parts):
            continue
        out.append(p)
    return out


def _parse(p: Path) -> ast.AST | None:
    return parse_module(p)


# ---------------------------------------------------------------------------
# Layer 1: TLS verify=False
# ---------------------------------------------------------------------------


def test_no_tls_verify_false() -> None:
    hits: list[str] = []
    for p in _iter_prod_py():
        tree = _parse(p)
        if tree is None:
            continue
        rel = p.relative_to(ROOT).as_posix()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            for kw in node.keywords or []:
                if (
                    kw.arg == "verify"
                    and isinstance(kw.value, ast.Constant)
                    and kw.value.value is False
                ):
                    hits.append(f"{rel}:{node.lineno}: verify=False")
    assert not hits, (
        "TLS verification disabled — disables MITM protection:\n  "
        + "\n  ".join(hits)
    )


# ---------------------------------------------------------------------------
# Layer 2: tempfile.mktemp
# ---------------------------------------------------------------------------


def test_no_tempfile_mktemp() -> None:
    hits: list[str] = []
    for p in _iter_prod_py():
        tree = _parse(p)
        if tree is None:
            continue
        rel = p.relative_to(ROOT).as_posix()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            f = node.func
            if (
                isinstance(f, ast.Attribute)
                and f.attr == "mktemp"
                and isinstance(f.value, ast.Name)
                and f.value.id == "tempfile"
            ):
                hits.append(f"{rel}:{node.lineno}: tempfile.mktemp")
    assert not hits, (
        "tempfile.mktemp is race-condition prone — use tempfile.mkstemp() "
        "or NamedTemporaryFile:\n  " + "\n  ".join(hits)
    )


# ---------------------------------------------------------------------------
# Layer 3: stdlib xml.* imports (XXE)
# ---------------------------------------------------------------------------


def test_no_stdlib_xml_imports() -> None:
    hits: list[str] = []
    for p in _iter_prod_py():
        tree = _parse(p)
        if tree is None:
            continue
        rel = p.relative_to(ROOT).as_posix()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for a in node.names:
                    if a.name == "xml" or a.name.startswith("xml."):
                        hits.append(f"{rel}:{node.lineno}: import {a.name}")
            elif isinstance(node, ast.ImportFrom):
                m = node.module or ""
                if m == "xml" or m.startswith("xml."):
                    hits.append(f"{rel}:{node.lineno}: from {m}")
    assert not hits, (
        "stdlib xml.* is XXE-vulnerable — use the defusedxml package:\n  "
        + "\n  ".join(hits)
    )


# ---------------------------------------------------------------------------
# Layer 4: warnings.simplefilter("ignore") / filterwarnings("ignore")
# ---------------------------------------------------------------------------


def test_no_warnings_ignore_in_prod() -> None:
    hits: list[str] = []
    for p in _iter_prod_py():
        tree = _parse(p)
        if tree is None:
            continue
        rel = p.relative_to(ROOT).as_posix()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            f = node.func
            if not (
                isinstance(f, ast.Attribute)
                and f.attr in ("simplefilter", "filterwarnings")
                and isinstance(f.value, ast.Name)
                and f.value.id == "warnings"
            ):
                continue
            args = node.args
            if args and isinstance(args[0], ast.Constant) and args[0].value == "ignore":
                hits.append(f"{rel}:{node.lineno}: warnings.{f.attr}('ignore')")
    assert not hits, (
        "Blanket 'ignore' suppresses Deprecation/Runtime warnings — narrow "
        "to category= or message= filters:\n  " + "\n  ".join(hits)
    )


# ---------------------------------------------------------------------------
# Layer 5: logging.basicConfig frozen 7-site ledger
# ---------------------------------------------------------------------------


_FROZEN_BASIC_CONFIG_SITES: frozenset[tuple[str, int]] = frozenset({
    ("newsstack_fmp/run.py", 22),
    ("open_prep/candidate_weights.py", 207),
    # 2026-06-13 (audit-e2/aw7-reader-observability, PR #2759): _load_previous_latest
    #   DEBUG log insertion shifted logging.basicConfig from 305 → 306.
    ("open_prep/feature_importance_report.py", 306),
    # 2026-06-11 (backfill defer-unpublished): 418→457.
    # 2026-06-11 (eval-findings B1/B2): direction+TB code shifted 457→536.
    # 2026-06-11 (c10b FI component persistence): era-gate block 536→558.
    # 2026-06-11 (Copilot sweep #2677): deferred-summary accounting 558→570.
    # 2026-06-12 (pytest write-guard merge): guard import/call + sweep
    # combined — measured 579.
    # 2026-06-12 (Copilot #2729): main() exit-semantics docstring +6 → 585.
    # 2026-06-17 (F1 lint fix): remove unused import sys → 585→584.
    ("open_prep/outcome_backfill.py", 584),
    ("open_prep/realtime_signals.py", 2723),
    # 2026-06-16 (feat/live-overlay-daemon): entry-point main.py configures
    # root logger at startup (Railway container, no other logger setup).
    # 2026-06-19 (fix/live-overlay-post-merge-bugs): import additions for
    # non-finite JSON sanitization shifted basicConfig line to 32.
    # 2026-06-19 (findings cleanup): restored accidental docstring pollution,
    # shifting basicConfig line 32 -> 31.
    # 2026-06-20 (market-hours extraction + readiness/basic-auth updates):
    # import and endpoint movement shifted basicConfig to line 39.
    # 2026-06-21 (auth decode hardening): binascii import shifted
    # basicConfig to line 40.
    ("services/live_overlay_daemon/main.py", 40),
    # 2026-06-10 (#2670 W2/W4): source-disclosure edits shifted +25 (5840→5865).
    # 2026-06-11 (trend-state features): 5865→5876, enrichment-loop stamping.
    # 2026-06-11 (eval-findings D7): import block +8, enrichment +15
    # (5876→5899); vix9d D5 fetch+stamp +19 → 5918.
    # 2026-06-11 (Copilot sweep #2688): VIX9D fail-closed guard +5 → 5923.
    # 2026-06-12 (merge #2713 into #2696): +1 net → 5924.
    # 2026-06-12 (backlog-resilience): fail-loud outcome storage +18 → 5942.
    # 2026-06-12 (copilot-followup): rename + 3-line comment → 5945.
    ("open_prep/run_open_prep.py", 6059),
    # WP-H (PR #2612): 35 -> 37, VIX import + helper block added above.
    ("smc_tv_bridge/smc_api.py", 37),
})


def _scan_basic_config() -> set[tuple[str, int]]:
    out: set[tuple[str, int]] = set()
    for p in _iter_prod_py():
        tree = _parse(p)
        if tree is None:
            continue
        rel = p.relative_to(ROOT).as_posix()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            f = node.func
            if (
                isinstance(f, ast.Attribute)
                and f.attr == "basicConfig"
                and isinstance(f.value, ast.Name)
                and f.value.id == "logging"
            ):
                out.add((rel, node.lineno))
    return out


def test_no_new_basic_config_sites() -> None:
    found = _scan_basic_config()
    new = sorted(found - _FROZEN_BASIC_CONFIG_SITES)
    assert not new, (
        f"New logging.basicConfig site(s): {new}. Library code must not "
        "configure the root logger — confine to entry-point scripts. If "
        "this is an entry point, add to _FROZEN_BASIC_CONFIG_SITES."
    )


def test_no_stale_basic_config_ledger_entries() -> None:
    found = _scan_basic_config()
    stale = sorted(_FROZEN_BASIC_CONFIG_SITES - found)
    assert not stale, (
        f"Stale logging.basicConfig ledger entries (no longer found at the "
        f"recorded line): {stale}. Update line numbers or remove the entry."
    )


# ---------------------------------------------------------------------------
# Layer 6: sys.path.insert / sys.path.append frozen 6-site ledger
# ---------------------------------------------------------------------------


_FROZEN_SYSPATH_SITES: frozenset[tuple[str, int, str]] = frozenset({
    ("open_prep/realtime_signals.py", 1133, "insert"),
    ("open_prep/streamlit_monitor.py", 34, "insert"),
    # WP-H (PR #2612): 32 -> 34, VIX import + helper block added above.
    ("smc_tv_bridge/smc_api.py", 34, "insert"),
    ("streamlit_databento_volatility_screener.py", 8, "insert"),
    ("streamlit_smc_micro_base_generator.py", 8, "insert"),
    ("streamlit_terminal.py", 275, "insert"),
})


def _scan_syspath() -> set[tuple[str, int, str]]:
    out: set[tuple[str, int, str]] = set()
    for p in _iter_prod_py():
        tree = _parse(p)
        if tree is None:
            continue
        rel = p.relative_to(ROOT).as_posix()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            f = node.func
            if not isinstance(f, ast.Attribute):
                continue
            if f.attr not in ("insert", "append"):
                continue
            if not (
                isinstance(f.value, ast.Attribute)
                and f.value.attr == "path"
                and isinstance(f.value.value, ast.Name)
                and f.value.value.id == "sys"
            ):
                continue
            out.add((rel, node.lineno, f.attr))
    return out


def test_no_new_syspath_mutation_sites() -> None:
    found = _scan_syspath()
    new = sorted(found - _FROZEN_SYSPATH_SITES)
    assert not new, (
        f"New sys.path mutation site(s): {new}. Path-hacks must be confined "
        "to known entry-point shims. If this is one, add to "
        "_FROZEN_SYSPATH_SITES; otherwise refactor to package imports."
    )


def test_no_stale_syspath_ledger_entries() -> None:
    found = _scan_syspath()
    stale = sorted(_FROZEN_SYSPATH_SITES - found)
    assert not stale, (
        f"Stale sys.path mutation ledger entries: {stale}. Update or "
        "remove the entry."
    )


# ---------------------------------------------------------------------------
# Inventory sanity
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "rel_path",
    sorted({s[0] for s in _FROZEN_BASIC_CONFIG_SITES} | {s[0] for s in _FROZEN_SYSPATH_SITES}),
)
def test_ledger_files_exist(rel_path: str) -> None:
    assert (ROOT / rel_path).is_file(), (
        f"Ledger references missing file: {rel_path}. Update the ledger if "
        "the file was renamed or removed."
    )


def test_prod_inventory_sane() -> None:
    files = _iter_prod_py()
    assert len(files) >= 30, (
        f"Expected >=30 first-party prod *.py files, got {len(files)}. "
        "Inventory walker may be misconfigured."
    )
