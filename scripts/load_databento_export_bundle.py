from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd


def _manifest_frame_names(manifest_path: Path) -> set[str]:
    basename = manifest_path.name.removesuffix("_manifest.json")
    return {path.stem.removeprefix(f"{basename}__") for path in manifest_path.parent.glob(f"{basename}__*.parquet")}


def _manifest_candidates(directory: Path, *, manifest_prefix: str | None = None) -> list[Path]:
    pattern = f"{manifest_prefix}*_manifest.json" if manifest_prefix else "*_manifest.json"
    return sorted(directory.glob(pattern), key=lambda path: path.stat().st_mtime, reverse=True)


def _resolve_manifest_from_directory(
    directory: Path,
    *,
    required_frames: tuple[str, ...] | None = None,
    manifest_prefix: str | None = None,
) -> Path | None:
    required = set(required_frames or ())
    for manifest_path in _manifest_candidates(directory, manifest_prefix=manifest_prefix):
        if not required:
            return manifest_path
        if required.issubset(_manifest_frame_names(manifest_path)):
            return manifest_path
    return None


def resolve_manifest_path(
    export_dir: str | Path,
    *,
    required_frames: tuple[str, ...] | None = None,
    manifest_prefix: str | None = None,
) -> Path | None:
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
    return _resolve_manifest_from_directory(
        directory,
        required_frames=required_frames,
        manifest_prefix=manifest_prefix,
    )


def load_export_bundle(
    export_dir: str | Path,
    *,
    required_frames: tuple[str, ...] | None = None,
    manifest_prefix: str | None = None,
) -> dict[str, Any]:
    manifest_path = resolve_manifest_path(
        export_dir,
        required_frames=required_frames,
        manifest_prefix=manifest_prefix,
    )
    if manifest_path is None:
        required_text = f" required_frames={list(required_frames)}" if required_frames else ""
        prefix_text = f" manifest_prefix={manifest_prefix}" if manifest_prefix else ""
        raise FileNotFoundError(f"No export manifest found for {export_dir}{required_text}{prefix_text}")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    basename = manifest_path.name.removesuffix("_manifest.json")
    frames: dict[str, pd.DataFrame] = {}
    for path in sorted(manifest_path.parent.glob(f"{basename}__*.parquet")):
        frame_name = path.stem.removeprefix(f"{basename}__")
        frames[frame_name] = pd.read_parquet(path)

    required = set(required_frames or ())
    if required:
        missing = sorted(required.difference(frames.keys()))
        if missing:
            raise ValueError(
                "Resolved manifest is missing required bundle frames: "
                f"{missing}. Manifest={manifest_path}"
            )

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