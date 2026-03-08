from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd


def resolve_manifest_path(bundle: str | Path) -> Path:
    path = Path(bundle).expanduser()
    if path.is_file() and path.suffix == ".json":
        return path
    if path.is_dir():
        manifests = sorted(path.glob("*_manifest.json"), key=lambda candidate: candidate.stat().st_mtime, reverse=True)
        if manifests:
            return manifests[0]
        raise FileNotFoundError(f"No *_manifest.json file found in {path}")
    candidate = path.with_name(f"{path.name}_manifest.json")
    if candidate.exists():
        return candidate
    raise FileNotFoundError(f"Could not resolve manifest for bundle input: {bundle}")


def load_export_bundle(bundle: str | Path) -> dict[str, Any]:
    manifest_path = resolve_manifest_path(bundle)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    base_prefix = manifest_path.name[: -len("_manifest.json")]
    bundle_dir = manifest_path.parent

    frames: dict[str, pd.DataFrame] = {}
    for parquet_path in sorted(bundle_dir.glob(f"{base_prefix}__*.parquet")):
        table_name = parquet_path.stem.split("__", 1)[1]
        frames[table_name] = pd.read_parquet(parquet_path)

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