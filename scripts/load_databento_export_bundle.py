from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd


def resolve_manifest_path(export_dir: str | Path) -> Path | None:
    candidate = Path(export_dir)
    if candidate.is_file() and candidate.name.endswith("_manifest.json"):
        return candidate
    if not candidate.is_dir():
        manifest_path = candidate.with_name(f"{candidate.name}_manifest.json")
        if manifest_path.exists():
            return manifest_path
    if candidate.suffix:
        manifest_path = candidate.with_name(f"{candidate.name}_manifest.json")
        return manifest_path if manifest_path.exists() else None
    directory = candidate if candidate.is_dir() else candidate.parent
    manifests = sorted(directory.glob("*_manifest.json"))
    return manifests[-1] if manifests else None


def load_export_bundle(export_dir: str | Path) -> dict[str, Any]:
    manifest_path = resolve_manifest_path(export_dir)
    if manifest_path is None:
        raise FileNotFoundError(f"No export manifest found for {export_dir}")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    basename = manifest_path.name.removesuffix("_manifest.json")
    frames: dict[str, pd.DataFrame] = {}
    for path in sorted(manifest_path.parent.glob(f"{basename}__*.parquet")):
        frame_name = path.stem.removeprefix(f"{basename}__")
        frames[frame_name] = pd.read_parquet(path)
    return {
        "manifest_path": manifest_path,
        "manifest": manifest,
        "base_prefix": basename,
        "frames": frames,
    }


def build_bundle_summary(bundle: dict[str, Any]) -> pd.DataFrame:
    frames = bundle.get("frames", {}) if isinstance(bundle, dict) else {}
    return pd.DataFrame(
        {
            "table": sorted(frames.keys()),
            "rows": [len(frames[name]) for name in sorted(frames.keys())],
        }
    )