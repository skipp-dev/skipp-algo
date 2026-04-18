"""Detect drift between local Pine files and the last published state.

Usage:
    python scripts/detect_publish_drift.py [--manifest PATH] [--pine-dir PATH]

Exit code:
    0 — no drift detected
    1 — drift detected (local file differs from published hash)
    2 — manifest entry missing for a tracked file
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MANIFEST = ROOT / "artifacts" / "publish_manifest.json"

# Pine files that are published as TradingView libraries/scripts.
# Extend this list as new scripts are published.
TRACKED_PINE_FILES: tuple[str, ...] = (
    "pine/generated/smc_micro_profiles_generated.pine",
    "pine/skipp_calibration.pine",
    "pine/skipp_indicators.pine",
    "pine/skipp_labels.pine",
    "pine/skipp_math.pine",
    "pine/skipp_scoring.pine",
    "SMC_Core_Engine.pine",
    "SMC_Dashboard.pine",
    "SMC_Long_Strategy.pine",
    "SMC_Event_Overlay.pine",
    "SMC_HTF_Confluence.pine",
    "SMC_Liquidity_Context.pine",
    "SMC_Liquidity_Structure.pine",
    "SMC_Imbalance_Context.pine",
)


def content_hash(path: Path) -> str:
    """SHA-256 of file content, ignoring trailing whitespace per line."""
    lines = path.read_text(encoding="utf-8").splitlines()
    normalized = "\n".join(line.rstrip() for line in lines) + "\n"
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def load_manifest(path: Path) -> dict:
    if not path.exists():
        return {"manifest_version": 1, "entries": []}
    return json.loads(path.read_text(encoding="utf-8"))


def save_manifest(manifest: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def record_publish(
    manifest_path: Path,
    file_relpath: str,
    *,
    library_name: str = "",
    version: str = "",
    publish_time: str = "",
    expected_live_state: str = "published",
) -> None:
    """Record a successful publish into the manifest."""
    manifest = load_manifest(manifest_path)
    file_path = ROOT / file_relpath
    if not file_path.exists():
        raise FileNotFoundError(f"Cannot record publish: {file_relpath} not found")

    h = content_hash(file_path)
    # Remove old entry for same file
    manifest["entries"] = [
        e for e in manifest["entries"] if e.get("file") != file_relpath
    ]
    manifest["entries"].append({
        "file": file_relpath,
        "library_name": library_name or file_relpath,
        "version": version,
        "content_hash": h,
        "publish_time": publish_time,
        "expected_live_state": expected_live_state,
    })
    save_manifest(manifest, manifest_path)


def detect_drift(manifest_path: Path) -> list[dict]:
    """Return list of drift records. Empty = no drift."""
    manifest = load_manifest(manifest_path)
    entries_by_file = {e["file"]: e for e in manifest.get("entries", [])}
    drifts: list[dict] = []

    for rel in TRACKED_PINE_FILES:
        full_path = ROOT / rel
        if not full_path.exists():
            continue

        entry = entries_by_file.get(rel)
        if entry is None:
            drifts.append({
                "file": rel,
                "status": "no_manifest_entry",
                "local_hash": content_hash(full_path),
                "published_hash": None,
            })
            continue

        local_h = content_hash(full_path)
        pub_h = entry.get("content_hash", "")
        if local_h != pub_h:
            drifts.append({
                "file": rel,
                "status": "drift",
                "local_hash": local_h,
                "published_hash": pub_h,
                "published_version": entry.get("version", ""),
                "publish_time": entry.get("publish_time", ""),
            })

    return drifts


# ---------------------------------------------------------------------------
# Live-State Reconciliation (WP-17)
# ---------------------------------------------------------------------------

def reconcile_live_state(manifest_path: Path) -> dict:
    """Produce a reconciliation summary comparing local, manifest, and expected live state.

    Returns a dict with:
        - consistent: files where local == manifest hash
        - drift: files where local != manifest hash
        - publish_outstanding: files not yet in manifest
        - state_unknown: files missing expected_live_state marker
        - summary: counts
    """
    manifest = load_manifest(manifest_path)
    entries_by_file = {e["file"]: e for e in manifest.get("entries", [])}

    consistent: list[dict] = []
    drift: list[dict] = []
    publish_outstanding: list[dict] = []
    state_unknown: list[dict] = []

    for rel in TRACKED_PINE_FILES:
        full_path = ROOT / rel
        if not full_path.exists():
            continue

        local_h = content_hash(full_path)
        entry = entries_by_file.get(rel)

        if entry is None:
            publish_outstanding.append({"file": rel, "local_hash": local_h})
            continue

        pub_h = entry.get("content_hash", "")
        live_state = entry.get("expected_live_state", "")

        if local_h == pub_h:
            if live_state:
                consistent.append({
                    "file": rel,
                    "hash": local_h[:12],
                    "expected_live_state": live_state,
                })
            else:
                state_unknown.append({
                    "file": rel,
                    "hash": local_h[:12],
                    "reason": "no expected_live_state in manifest",
                })
        else:
            drift.append({
                "file": rel,
                "local_hash": local_h[:12],
                "published_hash": pub_h[:12],
                "publish_time": entry.get("publish_time", ""),
            })

    return {
        "consistent": consistent,
        "drift": drift,
        "publish_outstanding": publish_outstanding,
        "state_unknown": state_unknown,
        "summary": {
            "total_tracked": len(TRACKED_PINE_FILES),
            "consistent": len(consistent),
            "drift": len(drift),
            "publish_outstanding": len(publish_outstanding),
            "state_unknown": len(state_unknown),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Detect TradingView publish drift")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--record", metavar="FILE", help="Record a publish for FILE")
    parser.add_argument("--library-name", default="")
    parser.add_argument("--version", default="")
    parser.add_argument("--publish-time", default="")
    parser.add_argument("--reconcile", action="store_true", help="Show live-state reconciliation summary")
    args = parser.parse_args()

    if args.record:
        record_publish(
            args.manifest,
            args.record,
            library_name=args.library_name,
            version=args.version,
            publish_time=args.publish_time,
        )
        print(f"Recorded publish for {args.record}")
        return 0

    if args.reconcile:
        result = reconcile_live_state(args.manifest)
        s = result["summary"]
        print(f"Reconciliation: {s['consistent']} consistent, {s['drift']} drift, "
              f"{s['publish_outstanding']} outstanding, {s['state_unknown']} unknown")
        print(json.dumps(result, indent=2))
        return 1 if s["drift"] > 0 else 0

    drifts = detect_drift(args.manifest)
    if not drifts:
        print("No publish drift detected.")
        return 0

    print(f"Publish drift detected: {len(drifts)} file(s)")
    for d in drifts:
        status = d["status"]
        if status == "no_manifest_entry":
            print(f"  {d['file']}: not in manifest (never published?)")
        else:
            print(f"  {d['file']}: DRIFT (published={d.get('published_hash', '?')[:12]}… local={d['local_hash'][:12]}…)")
    return 1


if __name__ == "__main__":
    sys.exit(main())
