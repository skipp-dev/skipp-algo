"""Pin: Pine library imports respect declared owner-boundary permissions.

Background
==========

Some Pine libraries are **private** to a specific consumer cluster
(e.g. ``smc_bus_private`` is only safe to import from the SMC core
engine and the SMC++ helper layer). Cross-cluster imports leak
internal state machines and force premature stabilisation of internal
APIs.

This test enforces a per-library *allowlist of importer path
prefixes*. Adding a new importer outside the allowlist requires
either updating the prefix set (with reviewer awareness) or refactoring
the import to go through a public seam.

See also:
* /memories/repo/pine-bus-private-export-surface.md
* /memories/repo/pine-canonical-lean-shared-exports.md
* /memories/repo/smc-bus-v2-freeze-endpoint.md
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Per-library allowlist of importer file-path prefixes (relative to
# repo root, forward-slash form). A library NOT listed here is treated
# as public — any importer is allowed.
#
# Rule: the importer path MUST start with one of the listed prefixes.
# Empty tuple = library is locked out (no importer allowed). Use
# ``("",)`` to allow every path explicitly.
_LIBRARY_PERMISSIONS: dict[str, tuple[str, ...]] = {
    # Internal bus: only the engine and the SMC++ context resolvers
    # may import. Other Pine consumers must read public ``mp.*`` consts.
    "smc_bus_private": ("SMC_Core_Engine.pine", "SMC++/"),
    # Lifecycle private API: engine only.
    "smc_lifecycle_private": ("SMC_Core_Engine.pine",),
    # Observability private API: engine + SMC++ helpers.
    "smc_observability_private": ("SMC_Core_Engine.pine", "SMC++/"),
    # Profile engine: engine only (consumers should use mp.* exports).
    "smc_profile_engine": ("SMC_Core_Engine.pine",),
    # Context resolvers: engine only.
    "smc_context_resolvers": ("SMC_Core_Engine.pine",),
}

_IMPORT_RE = re.compile(
    r"^\s*import\s+preuss_steffen/(?P<lib>[A-Za-z0-9_]+)/\d+\s+as\s+\w+",
    re.MULTILINE,
)


def _all_pine_files() -> list[Path]:
    return sorted(REPO_ROOT.glob("**/*.pine"))


def _relative(p: Path) -> str:
    return str(p.relative_to(REPO_ROOT)).replace("\\", "/")


def test_pine_library_imports_respect_permissions() -> None:
    violations: list[str] = []
    for path in _all_pine_files():
        # Ignore generated/snippet files — they are reproducible artifacts.
        rel = _relative(path)
        if "/generated/" in f"/{rel}" or rel.startswith("tests/fixtures/"):
            continue
        text = path.read_text(encoding="utf-8")
        for match in _IMPORT_RE.finditer(text):
            lib = match.group("lib")
            allowlist = _LIBRARY_PERMISSIONS.get(lib)
            if allowlist is None:
                continue  # public library
            if not any(rel.startswith(prefix) for prefix in allowlist):
                violations.append(
                    f"{rel}: imports private library {lib!r}; allowlist "
                    f"is {allowlist}. Either route through a public "
                    "library (mp.*, ct.*, u.*) or extend the allowlist "
                    "in tests/test_pine_library_import_permissions.py "
                    "with reviewer awareness."
                )
    assert not violations, (
        "Pine library import-permission violations:\n  "
        + "\n  ".join(violations)
    )


def test_permission_table_covers_known_private_libraries() -> None:
    """Every ``*_private`` library in the repo must appear in the table."""
    private_seen: set[str] = set()
    for path in _all_pine_files():
        rel = _relative(path)
        if "/generated/" in f"/{rel}":
            continue
        for match in _IMPORT_RE.finditer(path.read_text(encoding="utf-8")):
            lib = match.group("lib")
            if lib.endswith("_private"):
                private_seen.add(lib)
    missing = private_seen - set(_LIBRARY_PERMISSIONS)
    assert not missing, (
        f"Private libraries imported but not pinned in the permission "
        f"table: {sorted(missing)}. Add an explicit allowlist entry."
    )
