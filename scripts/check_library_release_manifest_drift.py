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
* a consumer Pine file (``SMC_Long_Dip_Suite.pine``,
  ``SMC_Decision_Board.pine``, ``SMC_Long_Dip_Strategy.pine``) was moved or
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


def _group_title_census(product_cut: dict) -> dict[str, int]:
    """``{groupTitle: occurrences}`` over every preflight bindingLabelGroups."""
    census: dict[str, int] = {}
    for scope in (product_cut.get("preflightScopes") or {}).values():
        for target in scope or []:
            if not isinstance(target, dict):
                continue
            for binding in target.get("bindingLabelGroups") or []:
                if isinstance(binding, dict):
                    title = binding.get("groupTitle")
                    if isinstance(title, str):
                        census[title] = census.get(title, 0) + 1
    return census


def embedded_product_cut_drift(manifest: dict, root: Path) -> list[str]:
    """Compare the embedded ``productCut`` copy against the canonical artifact.

    The 10-angle review of 2026-08-28 found the embedded copy still carrying
    42x 'Lifecycle BUS' / 9x 'Diagnostic Support' — settings-group names that
    #4639 had renamed 16 days earlier — because the copy is a snapshot taken
    at publish time (``readProductCutSummary`` in tv_publish_micro_library.ts
    copies the checked-in artifact verbatim) and nothing compared it back.

    Compared: the ``groupTitle`` census over every preflight scope's
    ``bindingLabelGroups`` plus the ``contracts`` key set. Reported as
    ``::warning::`` (exit stays 0) by DELIBERATE decision: the embedded copy
    lags a registry rename by up to one publish cycle in the ordinary course
    of business, and the drift check runs on the required fast-gates lane —
    a hard failure here would redden every open PR for up to a day after any
    legitimate rename (#4272 relived). At publish time equality holds by
    construction; a drift that persists means the publish cycle stalled, and
    this warning keeps naming it on every heavy-lane PR until it heals.
    """
    product_cut_path = (manifest.get("productCut") or {}).get("manifestPath")
    if not isinstance(product_cut_path, str) or not product_cut_path:
        return ["productCut.manifestPath missing — cannot cross-check the embedded copy"]
    canonical_file = root / product_cut_path
    if not canonical_file.is_file():
        return []  # already reported as a missing referenced path
    try:
        canonical = json.loads(canonical_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        return [f"{product_cut_path} is not parseable JSON ({error}) — cannot cross-check"]

    problems: list[str] = []
    embedded_census = _group_title_census(manifest.get("productCut") or {})
    canonical_census = _group_title_census(canonical)
    if not canonical_census:
        problems.append(
            f"{product_cut_path} yields an EMPTY groupTitle census — the "
            "cross-check would pass vacuously; its structure changed"
        )
    for title in sorted(set(embedded_census) | set(canonical_census)):
        embedded = embedded_census.get(title, 0)
        current = canonical_census.get(title, 0)
        if embedded != current:
            problems.append(
                f"groupTitle {title!r}: embedded copy carries {embedded}, "
                f"canonical product cut carries {current}"
            )

    embedded_contracts = set((manifest.get("productCut") or {}).get("contracts") or {})
    canonical_contracts = set(canonical.get("contracts") or {})
    if embedded_contracts != canonical_contracts:
        problems.append(
            "contracts key set differs: embedded "
            f"{sorted(embedded_contracts - canonical_contracts)} extra, "
            f"{sorted(canonical_contracts - embedded_contracts)} missing"
        )
    return problems


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

    # WARN, never fail (rationale in embedded_product_cut_drift's docstring):
    # the embedded copy is a publish-time snapshot that self-heals with the
    # next library refresh; a persistent warning means the cycle stalled.
    stale = embedded_product_cut_drift(manifest, args.root)
    for problem in stale:
        print(
            "::warning title=library_release_manifest productCut snapshot "
            f"drift::{problem} (self-heals with the next library publish; "
            "persists only if the refresh cycle stalled)"
        )

    if not missing:
        print(
            "OK: library_release_manifest.json is in sync with filesystem "
            f"({len(refs)} referenced paths verified"
            + (f"; {len(stale)} productCut snapshot drift warning(s))" if stale else ")")
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
