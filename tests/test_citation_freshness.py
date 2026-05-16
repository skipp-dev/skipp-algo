"""R1 + R2 (audit-L-1, 2026-05-12) — citation freshness in docs/comments.

R1 — every workspace-relative path mentioned in a comment, docstring, or
markdown body must exist on disk. Stops the "wrong module path" finding
class (#2155, #2163, #2164, #2165 — ≈11 findings collectively).

R2 — every backtick-quoted ``module.function`` in a pin/ledger test file's
comments/docstrings must resolve via ``importlib.import_module(module)`` +
``getattr(module, function)``. Stops the ``_ts_to_ns``-class drift caught
twice in #2155.

Failure modes are surfaced as test failures, not warnings: the only way to
"silence" a finding is to fix the citation or extend ``_ALLOWLISTED_PATHS``
/ ``_ALLOWLISTED_SYMBOLS`` with a written reason.

See ``docs/AUDIT_L1_REVIEW_RETROSPECTIVE_2026-05-12.md`` §R1, §R2.
"""

from __future__ import annotations

import ast
import importlib
import re
from pathlib import Path

import pytest


_REPO_ROOT = Path(__file__).resolve().parent.parent

# R1 — only enforced on actively-maintained docs/templates whose citations
# guide live operations or audit trails. Historical / archived docs (sprint
# plans, old test reports, archive/, reviews/, reviewer-prompts/) are NOT
# included: their references reflect the state at write-time and rewriting
# them would lose audit fidelity.
_R1_ENFORCED_GLOBS: tuple[str, ...] = (
    # CHANGELOG.md is intentionally NOT enforced: historical entries cite
    # planning/discovery scripts that have since been renamed or removed,
    # and rewriting them would lose audit-trail fidelity.
    "docs/AUDIT_*_2026-*.md",
    "docs/COPILOT_*.md",
    "docs/OPEN_PREP_OPS_QUICK_REFERENCE.md",
    "docs/PROVIDER_*.md",
    ".github/PULL_REQUEST_TEMPLATE.md",
    ".github/workflows/*.yml",
    ".github/workflows/*.yaml",
)

# Glob patterns of files that get the R2 symbol-resolution pass (pin/ledger
# tests where stale symbol citations have caused real maintenance burn).
_PIN_TEST_GLOBS: tuple[str, ...] = (
    "tests/test_*_ledger.py",
    "tests/test_*_budget.py",
    "tests/test_*_pin*.py",
    "tests/test_*_tripwires.py",
    "tests/test_dynamic_import_*.py",
)

# Match e.g. ``open_prep/macro.py``, ``scripts/probe_*.py``, ``.github/workflows/x.yml``.
_PATH_RE = re.compile(
    r"(?P<path>(?:newsstack_fmp|open_prep|scripts|docs|tests|\.github)/"
    r"[A-Za-z0-9_./\-]+\.(?:py|md|yml|yaml|pine|json|txt|toml))"
)

# Match ``module.submodule.function`` inside a backtick pair.
# Restrictions to avoid false positives:
#   - Last segment must be snake_case (lowercase + underscores) AND not
#     end in a known file extension. This filters out filename mentions
#     like ``test_foo.py``, ``MyClass.pine``, ``vars.SMC_GH_HOSTED_RUNNER``.
#   - At least 2 dotted segments required.
_FILENAME_EXTS = ("py", "md", "pine", "yml", "yaml", "toml", "json", "txt", "sh", "cfg", "ini")
_SYMBOL_RE = re.compile(
    r"``(?P<dotted>(?:[A-Za-z_][A-Za-z0-9_]*\.){1,5}[a-z_][a-z0-9_]*)``"
)

# ── Allowlists ──────────────────────────────────────────────────────────────
# Cited paths that legitimately do NOT exist (e.g. removed historical files,
# placeholder examples, glob patterns rendered literally).
_ALLOWLISTED_PATHS: frozenset[str] = frozenset(
    {
        # Glob patterns rendered as literals in docs / templates.
        "scripts/probe_*.py",
        "docs/AUDIT_*_*.md",
        "docs/PROVIDER_RATIONALIZATION_AUDIT_*.md",
        # Future-tense placeholders in retrospective doc (R-items not yet implemented).
        "tests/test_citation_freshness.py",
        "tests/test_secret_leakage_probes.py",
        "tests/test_module_test_coverage_pin.py",
        "tests/test_import_safety.py",
        "tests/test_fmpclient_stats_concurrency.py",  # exists on PR-B branch / post-merge
        "tests/test_feature_flag_centralization.py",  # planned for PR-D
        "tools/check_defaults_table.py",
        "tools/check_audit_doc_consistency.py",
        ".github/PULL_REQUEST_TEMPLATE.md",            # planned for PR-C R3-regex
        # Forward-reference: defaults-table doc is the deliverable that
        # ``tools/check_defaults_table.py --strict`` will start enforcing
        # in a follow-up PR. Currently warn-only.
        "docs/CONFIG_DEFAULTS_TABLE.md",
        # Forward-references to extracted modules (PR-D R4 SSOT migration).
        "open_prep/opra_uoa.py",
        "newsstack_fmp/ingest_opra_options.py",
        # OPS_QUICK_REFERENCE — runtime artifacts produced by the daily run
        # (not committed to git but cited as paths in the operator runbook).
        "open_prep/latest/latest_open_prep_run.json",
        "open_prep/latest/latest_realtime_signals.json",
        "open_prep/latest/latest_vd_signals.json",
        "open_prep/latest/news_result.json",
        "open_prep/outcomes/outcomes_YYYY-MM-DD.json",
        # OPS_QUICK_REFERENCE also cites feature-importance artifacts under
        # artifacts/open_prep/...; regex captures the open_prep/... suffix.
        "open_prep/feature_importance/latest.json",
        "open_prep/outcomes/feature_importance/fi_samples_YYYY-MM-DD.json",
        # Workflow-generated history JSONs (committed by automation, may not
        # exist in a fresh clone or before first run).
        "docs/calibration/calibration_report_public_history.json",
        "open_prep/outcomes/feature_importance/latest.json",
        "docs/ab/g23_history.json",
        "docs/plan_2_8_history.json",
        # Historical / renamed audit docs cited for traceability.
        "docs/audits/smc-system-review-2026-04-24.md",
        "docs/BOUNDARY_CONTRACT.md",
        "docs/calibration/schemas/v1.2.0_public_schema_pin.json",
        # Test cited from another test as a sibling reference (rename-safe).
        "tests/test_changelog_category_lint.py",
    }
)

# Cited symbols that legitimately do NOT resolve (e.g. internal helpers
# whose import path is private, or placeholder docs examples).
_ALLOWLISTED_SYMBOLS: frozenset[str] = frozenset(
    {
        # Future-tense references in retrospective doc.
        "tests.test_citation_freshness",
        "tests.test_secret_leakage_probes",
        # Standard-library + dataclasses references that are described
        # textually but not directly importable as `pkg.attr`.
        "collections.Counter",
        "threading.Lock",
        "contextvars.ContextVar",
        "dataclasses.field",
        "importlib.import_module",
        # Placeholder/example identifiers in pin-test docstrings.
        "subprocess.foo",
        "session.post",          # truncated requests.Session.post example
        "Path.write_text",       # truncated pathlib.Path.write_text example
        "scripts.run_ab_comparison",       # script not importable as module (no __init__.py)
        "scripts.emit_fvg_context_pine",   # script not importable as module (no __init__.py)
        # Pine Script (TradingView) qualified identifiers, not Python.
        "syminfo.period",
        "timeframe.period",
        # Optional-dep references whose import would gate the test.
        "scipy.stats.norm.cdf",
    }
)

def _iter_r1_files() -> list[Path]:
    """Return the actively-maintained docs/templates enforced by R1."""

    out: set[Path] = set()
    for glob in _R1_ENFORCED_GLOBS:
        out.update(_REPO_ROOT.glob(glob))
    return sorted(out)


def _extract_text_to_scan(path: Path) -> str:
    """For .py: docstrings + comments. For .md/.yml: full body."""

    if path.suffix == ".py":
        try:
            source = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return ""
        # Comments: everything after `#` on each line that isn't inside a string.
        comments: list[str] = []
        for line in source.splitlines():
            stripped = line.lstrip()
            if stripped.startswith("#"):
                comments.append(stripped[1:])
        # Docstrings: walk AST.
        docstrings: list[str] = []
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return "\n".join(comments)
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                doc = ast.get_docstring(node)
                if doc:
                    docstrings.append(doc)
        return "\n".join(comments + docstrings)
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""


# --------------------------------------------------------------------------- #
# R1 — file/path citation freshness
# --------------------------------------------------------------------------- #
def test_r1_cited_paths_exist_on_disk() -> None:
    """Every cited workspace path must exist (or be allowlisted)."""

    misses: list[tuple[str, str]] = []  # (citing_file, missing_path)
    stale_allowlist: set[str] = set()  # paths in allowlist that DO now exist
    for doc in _iter_r1_files():
        text = _extract_text_to_scan(doc)
        for match in _PATH_RE.finditer(text):
            cited = match.group("path")
            # Check existence FIRST so the allowlist cannot silently mask a
            # later deletion of a currently-existing file (audit-L-1 §R14:
            # Copilot #4).
            if (_REPO_ROOT / cited).exists():
                if cited in _ALLOWLISTED_PATHS:
                    stale_allowlist.add(cited)
                continue
            if cited in _ALLOWLISTED_PATHS:
                continue
            misses.append((str(doc.relative_to(_REPO_ROOT)), cited))

    if misses:
        formatted = "\n  - ".join(f"{src} -> {cited}" for src, cited in sorted(set(misses)))
        raise AssertionError(
            "Stale workspace-path citations (file does not exist on disk). "
            "Either fix the citation, rename the file, or extend "
            "`_ALLOWLISTED_PATHS` with a written reason:\n  - " + formatted
        )


# --------------------------------------------------------------------------- #
# R2 — function/symbol citation freshness in pin-test files
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "pin_test_file",
    sorted(
        {
            str(p.relative_to(_REPO_ROOT))
            for glob in _PIN_TEST_GLOBS
            for p in _REPO_ROOT.glob(glob)
        }
    ),
)
def test_r2_pin_test_symbol_citations_resolve(pin_test_file: str) -> None:
    """Backtick-quoted ``module.function`` in pin-test docstrings must resolve."""

    path = _REPO_ROOT / pin_test_file
    text = _extract_text_to_scan(path)
    unresolved: list[str] = []

    for match in _SYMBOL_RE.finditer(text):
        dotted = match.group("dotted")
        if dotted in _ALLOWLISTED_SYMBOLS:
            continue
        # Skip filename-shaped citations (``foo.py``, ``vars.X``, etc.).
        last = dotted.rsplit(".", 1)[-1]
        if last in _FILENAME_EXTS:
            continue
        # Skip obvious non-imports (e.g. ``self.attr.method``, ``foo.bar.baz``
        # with a leading lowercase that doesn't map to a module).
        head = dotted.split(".", 1)[0]
        if head in {
            "self", "cls", "obj", "client", "result", "data",
            "args", "kwargs", "vars", "env", "config", "request",
        }:
            continue
        # Try progressively shorter module prefixes.
        parts = dotted.split(".")
        resolved = False
        for split_at in range(len(parts) - 1, 0, -1):
            module_path = ".".join(parts[:split_at])
            attr_path = parts[split_at:]
            try:
                obj = importlib.import_module(module_path)
            except (ImportError, ValueError):
                continue
            try:
                for attr in attr_path:
                    obj = getattr(obj, attr)
                resolved = True
                break
            except AttributeError:
                continue
        if not resolved:
            unresolved.append(dotted)

    if unresolved:
        formatted = ", ".join(sorted(set(unresolved)))
        raise AssertionError(
            f"{pin_test_file}: cited symbols no longer resolve via importlib + "
            f"getattr — refresh the citation or add to `_ALLOWLISTED_SYMBOLS` "
            f"with a written reason: {formatted}"
        )
