from __future__ import annotations

import argparse
import json
import logging
import os
from pathlib import Path
from typing import Any

import pandas as pd

_LOGGER = logging.getLogger(__name__)

# F-V8-D5 (2026-05-16): A9b.5 cutover - the sharded producer can emit a
# merged manifest with `partial_run=true` and a populated `failed_shard_ids`
# list when one or more producer shards die before writing their manifest.
# The historical monolithic producer had no such mode, so existing callers
# of `load_export_bundle` implicitly assumed complete coverage. This helper
# makes the contract explicit: fail-fast by default; allow opt-in lenient
# mode via the SMC_ALLOW_PARTIAL_BUNDLE env var so an operator can
# deliberately accept a partial bundle (e.g. for a dry-run or audit) without
# editing source.
_ALLOW_PARTIAL_ENV = "SMC_ALLOW_PARTIAL_BUNDLE"


def assert_bundle_is_complete(
    payload: dict[str, Any],
    *,
    scope: str = "export bundle",
) -> None:
    """Raise if the loaded bundle's manifest reports a partial sharded run.

    Pass `scope` (e.g. "baseline bundle") for a more specific error
    message. Set ``SMC_ALLOW_PARTIAL_BUNDLE=1`` in the environment to
    downgrade the failure to a warning.
    """

    manifest = payload.get("manifest") if isinstance(payload.get("manifest"), dict) else {}
    if not manifest.get("partial_run"):
        return
    inner = manifest.get("manifest") if isinstance(manifest.get("manifest"), dict) else {}
    failed = manifest.get("failed_shard_ids") or inner.get("failed_shard_ids") or []
    expected = manifest.get("expected_shard_count")
    actual = manifest.get("shard_count")
    msg = (
        f"{scope} manifest reports partial_run=true "
        f"(shard_count={actual!r}, expected_shard_count={expected!r}, "
        f"failed_shard_ids={failed!r}). This script assumes complete shard "
        f"coverage. Re-run the sharded producer for the missing shards, or "
        f"set {_ALLOW_PARTIAL_ENV}=1 to proceed with degraded data."
    )
    if os.environ.get(_ALLOW_PARTIAL_ENV) == "1":
        _LOGGER.warning("%s (override: %s=1)", msg, _ALLOW_PARTIAL_ENV)
        return
    raise RuntimeError(msg)


def _manifest_frame_names(manifest_path: Path) -> set[str]:
    basename = manifest_path.name.removesuffix("_manifest.json")
    return {
        path.stem.removeprefix(f"{basename}__")
        for path in manifest_path.parent.glob(f"{basename}__*.parquet")
    }


def _manifest_candidates(directory: Path, *, manifest_prefix: str | None = None) -> list[Path]:
    from scripts.smc_artifact_resolver import sorted_by_filename_iso
    pattern = f"{manifest_prefix}*_manifest.json" if manifest_prefix else "*_manifest.json"
    return sorted_by_filename_iso(directory.glob(pattern))


def _manifest_json_is_parseable(manifest_path: Path) -> bool:
    try:
        json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception:
        return False
    return True


def _resolve_manifest_from_directory(
    directory: Path,
    *,
    required_frames: tuple[str, ...] | None = None,
    manifest_prefix: str | None = None,
) -> Path | None:
    required = set(required_frames or ())
    candidates = _manifest_candidates(directory, manifest_prefix=manifest_prefix)
    parseable_empty: Path | None = None
    for manifest_path in candidates:
        if not _manifest_json_is_parseable(manifest_path):
            continue
        frame_names = _manifest_frame_names(manifest_path)
        if not frame_names:
            # Sub-manifests (e.g. ``..._smc_microstructure_base_manifest.json``)
            # match the same ``{prefix}*_manifest.json`` glob but reference no
            # sibling ``{basename}__*.parquet`` frames. When a real
            # frame-bearing manifest also lives in the directory, skipping the
            # empty one prevents the sub-manifest from hijacking default
            # selection (and silently returning an empty bundle).
            #
            # However, when *no* frame-bearing manifest is present the empty
            # manifest is a legitimate standalone metadata file (e.g. an
            # exact-named watchlist export whose parquets are not bundle-
            # prefixed). We fall back to it below so metadata discovery keeps
            # working for those flows.
            if parseable_empty is None:
                parseable_empty = manifest_path
            continue
        if required and not required.issubset(frame_names):
            continue
        return manifest_path
    if not required:
        return parseable_empty
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

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise RuntimeError(f"Manifest read/parse failed after resolve: {manifest_path}") from exc
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
