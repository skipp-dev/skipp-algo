"""Drift check between ``library_release_manifest.json`` and filesystem.

Closes the **B follow-up** to PR #105: extends the Pine drift-lint family
with a guard that the canonical TradingView library release manifest
(``artifacts/tradingview/library_release_manifest.json``) does not
silently fall out of sync with the actual files it references.

Background
----------
The shared Pine-library publishing flow has historically tripped on
silent renames:

* a ``pine/generated/*`` source file was renamed without updating the
  manifest's ``library.sourceManifest`` / ``library.sourceSnippet``;
* a consumer Pine file (``SMC_Core_Engine.pine``,
  ``SMC_Dashboard.pine``, ``SMC_Long_Strategy.pine``) was moved or
  retired without updating the manifest's ``consumers[]`` and
  ``productCut.mainlineFiles[]`` lists;
* the canonical product-cut manifest itself (``productCut.manifestPath``)
  was renamed.

See ``/memories/repo/pine-canonical-lean-shared-exports.md`` for the
class of bugs this guard is meant to prevent.

Invariants
----------
1. ``library.sourceManifest`` path resolves to an existing file.
2. ``library.sourceSnippet`` path resolves to an existing file.
3. Every ``consumers[].file`` resolves to an existing file under the repo
   root.
4. Every ``productCut.mainlineFiles[]`` resolves to an existing file
   under the repo root.
5. ``productCut.manifestPath`` resolves to an existing file.

Exits non-zero with a per-invariant diff when any check fails. Designed
to be wired into ``smc-fast-pr-gates`` as a sub-second step.
"""

from __future__ import annotations

# F-V5-A1-2 / F-CI-O1 (2026-05-01): bootstrap root logging so the
# logger.info(...) progress messages this entry point emits actually
# surface in CI logs (default WARNING-only handler would drop them).
try:
    from scripts._logging_init import init_cli_logging
except ImportError:  # script-style invocation: `python scripts/X.py`
    import sys as _v5a12_sys
    from pathlib import Path as _v5a12_Path

    _v5a12_sys.path.insert(0, str(_v5a12_Path(__file__).resolve().parents[1]))
    from scripts._logging_init import init_cli_logging  # type: ignore[no-redef]


import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MANIFEST = REPO_ROOT / "artifacts" / "tradingview" / "library_release_manifest.json"


def load_manifest(manifest_path: Path) -> dict:
    """Read and JSON-decode the manifest, raising on missing file."""
    if not manifest_path.is_file():
        raise FileNotFoundError(f"library_release_manifest.json not found at {manifest_path}")
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def collect_referenced_paths(manifest: dict) -> list[tuple[str, str]]:
    """Return ``(json_pointer, relative_path)`` pairs the manifest claims.

    Order matches a deterministic traversal so failure output is stable.
    Missing structural keys are simply skipped — they will surface as
    distinct violations rather than crashing the lint.
    """
    refs: list[tuple[str, str]] = []
    library = manifest.get("library") or {}
    for key in ("sourceManifest", "sourceSnippet"):
        value = library.get(key)
        if isinstance(value, str) and value:
            refs.append((f"library.{key}", value))
    for index, consumer in enumerate(manifest.get("consumers") or []):
        if not isinstance(consumer, dict):
            continue
        value = consumer.get("file")
        if isinstance(value, str) and value:
            refs.append((f"consumers[{index}].file", value))
    product_cut = manifest.get("productCut") or {}
    manifest_path_value = product_cut.get("manifestPath")
    if isinstance(manifest_path_value, str) and manifest_path_value:
        refs.append(("productCut.manifestPath", manifest_path_value))
    for index, name in enumerate(product_cut.get("mainlineFiles") or []):
        if isinstance(name, str) and name:
            refs.append((f"productCut.mainlineFiles[{index}]", name))
    return refs


def find_missing(refs: list[tuple[str, str]], root: Path) -> list[tuple[str, str]]:
    """Return the subset of references whose path does not exist on disk."""
    missing: list[tuple[str, str]] = []
    for pointer, rel in refs:
        if not (root / rel).is_file():
            missing.append((pointer, rel))
    return missing


def main(argv: list[str] | None = None) -> int:
    init_cli_logging()  # F-V5-A1-2 (2026-05-01)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=REPO_ROOT,
        help="Repository root (default: derived from script location).",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=DEFAULT_MANIFEST,
        help="Path to library_release_manifest.json.",
    )
    args = parser.parse_args(argv)

    manifest = load_manifest(args.manifest)
    refs = collect_referenced_paths(manifest)
    missing = find_missing(refs, args.root)

    if not refs:
        print("FAIL: library_release_manifest.json declares no referenced paths.")
        return 1

    if not missing:
        print(
            "OK: library_release_manifest.json is in sync with filesystem "
            f"({len(refs)} referenced paths verified)."
        )
        return 0

    print("FAIL: library_release_manifest.json references files that do not exist.")
    print()
    print("Missing files:")
    for pointer, rel in missing:
        print(f"  - {pointer}: {rel}")
    print()
    print("Update library_release_manifest.json or restore the renamed/removed file.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
