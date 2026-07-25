"""Zero-surface defense pin for ``hmac`` call sites in production code.

``hmac`` is the project's *only* primitive for authenticated message
integrity (webhook signing) and constant-time secret comparison
(token / API-key auth).  Both call sites are security-critical:

* ``hmac.new(secret, payload, sha256)`` — webhook HMAC signing.
  Drift here (e.g. swapping the digest, changing key encoding,
  silently accepting empty secrets) silently breaks downstream
  signature verification *without* test failure.
* ``hmac.compare_digest(a, b)`` — the constant-time string compare
  used to validate auth tokens.  Replacing it with ``==`` re-introduces
  a timing oracle (CWE-208).  Adding new ``compare_digest`` callers is
  fine, but each one MUST be appended to the allow-list below to
  prove a security review happened.

This test only enumerates ``(path, line, attr)`` for every
``hmac.<attr>(...)`` call discovered via AST.  It does not import
production modules and does not modify any production file.
"""

from __future__ import annotations

import ast
from pathlib import Path

from tests._guard_corpus import parse_module

ROOT = Path(__file__).resolve().parent.parent

# Each entry is (relative_path, line_number, attribute_name).
HMAC_ALLOWED: set[tuple[str, int, str]] = {
    # TradersPost webhook payload signing (HMAC-SHA256). Line shifted
    # 765 → 769 (deep-audit fallback-buffer lock refresh) → 766
    # (2026-07-13 ledger reconcile: _sign_payload unchanged, upstream edits shifted it).
    ("terminal_export.py", 766, "new"),
    ("terminal_auth.py", 30, "compare_digest"),
    # 2026-06-16 (feat/live-overlay-daemon, PR #2794): token auth in FastAPI
    # endpoint uses hmac.compare_digest for constant-time comparison.
    # 2026-06-19 (fix/live-overlay-daemon-security, C1): _ct_eq compare site
    # moved repeatedly with daemon endpoint updates.
    # 2026-06-21 (merge refresh): combined branch changes shifted
    # compare_digest call; latest line pin is 418.
    # 2026-06-22 (fix/live-overlay-market-open-multiregion): main-merge +
    # provider-news rework shifted the same compare_digest call 418 → 421.
    # 2026-06-30 (Railway PORT follow-up): daemon entrypoint refactor shifted
    # the reviewed constant-time token compare call 422 → 442.
    # 2026-06-24 (signals auth): realtime /signals bearer-token checks use
    # constant-time comparison at two call sites.
    # 2026-07-09 (merge refresh): near-a0 re-poller (#3302) + trade-context
    # (#3309) + review-invariants (#3301) shifted the two realtime /signals
    # bearer-token compare sites 968/999 → 1160/1192 and the daemon HMAC compare
    # 451 → 457. (This ledger is NOT in the fast-gates set, so it had drifted red
    # on main unnoticed.)
    # 2026-07-13 (ledger reconcile): the two realtime /signals bearer-token compare
    # sites shifted again 1160/1192 → 1172/1204 (unchanged constant-time checks,
    # each guarded by `if _auth_token:`); main.py compare unchanged at 457.
    # 2026-07-15 (ledger reconcile): shifted again 1172/1204 → 1196/1228 by edits
    # ABOVE both blocks — #3584 (direction-aligned news upgrade + fast-lane bracket)
    # and #3587 (truth-disclosures), net +24 lines. Verified a pure line drift, NOT a
    # new surface: both auth blocks are byte-identical to their pinned versions at
    # ac7a83e5a (the /signals.json|/signals and the /metrics bearer check, each still
    # guarded by `if _auth_token:`), and the file still holds exactly 2 compare_digest
    # sites — the same count as when last reviewed. main.py compare unchanged at 457.
    ("open_prep/realtime_signals.py", 1328, "compare_digest"),  # 2026-07-22 client-disabled visibility shifted site: 1311->1328
    ("open_prep/realtime_signals.py", 1362, "compare_digest"),  # 2026-07-22 client-disabled visibility shifted site: 1345->1362
    # 2026-07-22 (stale-flag data-freshness helper + 5m block): 457->476
    # 2026-07-22 (SC-LIB-001 library-context payload merge): 476->481
    # 2026-07-22 (cache-miss context+VIX served): 481->489
    # 2026-07-24 (S2 stale close-based recency: _latest_bar_age_secs helper grew
    # +8 lines ABOVE this block): pure line drift, unchanged constant-time compare,
    # still exactly one main.py compare_digest site: 493->501
    ("services/live_overlay_daemon/main.py", 506, "compare_digest"),  # 2026-07-25 TF-history sizing: 501->506
    # 2026-07-13 (security review): Composio ChatOps webhook token check. Constant-
    # time compare of the URL-path token vs COMPOSIO_CHATOPS_WEBHOOK_TOKEN; the
    # endpoint raises 503 when the secret is unset (no empty-secret bypass) and 401
    # on mismatch. Added when the Composio-ops webhook landed without updating this
    # (ungated) ledger.
    ("services/live_overlay_daemon/composio_chatops.py", 133, "compare_digest"),
}

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
    "scripts",
}


def _iter_py_files() -> list[Path]:
    out: list[Path] = []
    for p in ROOT.rglob("*.py"):
        rel_parts = p.relative_to(ROOT).parts
        # Exclude dot-directories and any path segment matching an
        # excluded directory name. Single check covers both nested
        # and top-level cases.
        if any(part in _DIR_EXCLUDE or part.startswith(".") for part in rel_parts):
            continue
        out.append(p)
    return out


def _hmac_calls() -> set[tuple[str, int, str]]:
    found: set[tuple[str, int, str]] = set()

    class _HmacCallVisitor(ast.NodeVisitor):
        def __init__(self, path: Path, out: set[tuple[str, int, str]]) -> None:
            self._rel = path.relative_to(ROOT).as_posix()
            self._out = out

        def visit_Call(self, node: ast.Call) -> None:
            func = node.func
            if isinstance(func, ast.Attribute):
                value = func.value
                if isinstance(value, ast.Name) and value.id == "hmac":
                    self._out.add((self._rel, node.lineno, func.attr))
            self.generic_visit(node)

    for path in _iter_py_files():
        tree = parse_module(path)
        if tree is None:
            continue
        _HmacCallVisitor(path, found).visit(tree)
    return found


def test_hmac_zero_surface_pin() -> None:
    found = _hmac_calls()
    extra = found - HMAC_ALLOWED
    missing = HMAC_ALLOWED - found
    assert not extra, (
        "New hmac.* call site detected. Auth/integrity primitive — "
        "requires security review. Append (path, line, attr) to "
        f"HMAC_ALLOWED if approved. Extra: {sorted(extra)}"
    )
    assert not missing, (
        "Allow-listed hmac.* call site disappeared. If intentional, "
        f"remove from HMAC_ALLOWED. Missing: {sorted(missing)}"
    )


def _tautological_compare_digest_sites() -> set[tuple[str, int, str]]:
    """Return ``hmac.compare_digest(x, x)`` sites — a compare that always passes.

    ``HMAC_ALLOWED`` pins ``(path, lineno, attr)``. ``attr`` buys exactly one of
    this module's claims — swapping ``compare_digest`` for ``==`` drops the entry
    and fails. It says nothing about WHAT is compared, so mutating an
    allow-listed site to compare a value against ITSELF keeps the tuple
    identical and the pin green while the check becomes a tautology that
    authenticates every caller.

    That is not hypothetical for ``composio_chatops.webhook``: verified
    2026-07-15, rewriting its token check to ``compare_digest(token, token)``
    passed this pin AND the whole composio suite, because the endpoint has no
    behaviour test (see test_composio_chatops_webhook_rejects_wrong_token, added
    alongside this).

    Structural only: it catches the degenerate self-compare, not a compare
    against the wrong-but-different operand. Operand *correctness* is what
    behaviour tests are for; this closes the shape a ledger CAN see.
    """
    offenders: set[tuple[str, int, str]] = set()
    for path in _iter_py_files():
        tree = parse_module(path)
        if tree is None:
            continue
        rel = path.relative_to(ROOT).as_posix()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not isinstance(func, ast.Attribute) or func.attr != "compare_digest":
                continue
            value = func.value
            if not isinstance(value, ast.Name) or value.id != "hmac":
                continue
            if len(node.args) == 2 and ast.dump(node.args[0]) == ast.dump(node.args[1]):
                offenders.add((rel, node.lineno, ast.unparse(node.args[0])))
    return offenders


def test_compare_digest_never_compares_a_value_with_itself() -> None:
    """``hmac.compare_digest(x, x)`` is always True — an auth bypass, not a check."""
    offenders = _tautological_compare_digest_sites()
    assert not offenders, (
        "hmac.compare_digest(x, x) compares a value with itself and is therefore "
        "always True — every caller authenticates. The (path, line, attr) ledger "
        "cannot see this: the tuple is unchanged, so the pin stays green. Compare "
        "the supplied value against the EXPECTED secret.\n"
        f"offenders = {sorted(offenders)}"
    )
