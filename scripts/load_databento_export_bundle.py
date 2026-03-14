from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd


def _manifest_frame_names(manifest_path: Path) -> set[str]:
    basename = manifest_path.name.removesuffix("_manifest.json")
    return {
        path.stem.removeprefix(f"{basename}__")
        for path in manifest_path.parent.glob(f"{basename}__*.parquet")
    }


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
        if not required or required.issubset(_manifest_frame_names(manifest_path)):
            return manifest_path
    return None


def resolve_manifest_path(
    bundle: str | Path,
    *,
    required_frames: tuple[str, ...] | None = None,
    manifest_prefix: str | None = None,
) -> Path | None:
    path = Path(bundle).expanduser()

    if path.is_file() and path.name.endswith("_manifest.json"):
        return path

    if not path.is_dir():
        candidate = path.with_name(f"{path.name}_manifest.json")
        if candidate.exists():
            return candidate

    if path.suffix:
        candidate = path.with_name(f"{path.name}_manifest.json")
        return candidate if candidate.exists() else None

    directory = path if path.is_dir() else path.parent
    return _resolve_manifest_from_directory(
        directory,
        required_frames=required_frames,
        manifest_prefix=manifest_prefix,
    )


def load_export_bundle(
    bundle: str | Path,
    *,
    required_frames: tuple[str, ...] | None = None,
    manifest_prefix: str | None = None,
) -> dict[str, Any]:
    manifest_path = resolve_manifest_path(
        bundle,
        required_frames=required_frames,
        manifest_prefix=manifest_prefix,
    )
    if manifest_path is None:
        required_text = f" required_frames={list(required_frames)}" if required_frames else ""
        prefix_text = f" manifest_prefix={manifest_prefix}" if manifest_prefix else ""
        raise FileNotFoundError(f"No export manifest found for {bundle}{required_text}{prefix_text}")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    base_prefix = manifest_path.name[: -len("_manifest.json")]
    bundle_dir = manifest_path.parent

    frames: dict[str, pd.DataFrame] = {}
    for parquet_path in sorted(bundle_dir.glob(f"{base_prefix}__*.parquet")):
        table_name = parquet_path.stem.split("__", 1)[1]
        frames[table_name] = pd.read_parquet(parquet_path)

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
        "bundle_dir": bundle_dir,
        "base_prefix": base_prefix,
        "manifest": manifest,
        "frames": frames,
    }


def build_bundle_summary(bundle_payload: dict[str, Any]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for table_name, frame in sorted(bundle_payload["frames"].items()):
        rows.append(
            {
                "table": table_name,
                "rows": len(frame),
                "columns": len(frame.columns),
                "column_names": ", ".join(frame.columns.astype(str).tolist()),
            }
        )
    return pd.DataFrame(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="Load a Databento screener export bundle from manifest plus Parquet artifacts.")
    parser.add_argument(
        "bundle",
        nargs="?",
        default=str(Path.home() / "Downloads"),
        help="Manifest path, export directory, or bundle basename without the _manifest.json suffix.",
    )
    parser.add_argument("--head", type=int, default=3, help="How many preview rows per table to print.")
    args = parser.parse_args()

    payload = load_export_bundle(args.bundle)
    summary = build_bundle_summary(payload)

    print("MANIFEST_PATH", payload["manifest_path"])
    print("BASE_PREFIX", payload["base_prefix"])
    print("MANIFEST")
    print(json.dumps(payload["manifest"], indent=2, sort_keys=True, default=str))
    print("TABLE_SUMMARY")
    print(summary.to_string(index=False))

    for table_name, frame in sorted(payload["frames"].items()):
        print(f"PREVIEW {table_name}")
        if frame.empty:
            print("<empty>")
        else:
            print(frame.head(args.head).to_string(index=False))


if __name__ == "__main__":
    main()