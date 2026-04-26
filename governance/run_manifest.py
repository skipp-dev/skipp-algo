"""Sprint X3 — Run-Manifest helper for reproducibility headers.

Sprint scripts (C2/C3/C4/C6) emit JSON artifacts without a uniform
provenance header. Re-runs on new datasets can silently drift because
``(git_sha, schema_version, seed, dataset_fingerprint)`` is not visible
in the output.

This module provides a single ``build_manifest(...)`` helper plus a
``RunManifest`` TypedDict so every primary artifact can carry the
canonical reproducibility tuple. CI test
``tests/test_run_manifest_required.py`` round-trips the schema.

Numpy-only, stdlib-only.

Roadmap: docs/IMPROVEMENTS_C2_C12_ROADMAP_2026-04-26.md#x3
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import subprocess
import sys
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any, TypedDict

MANIFEST_SCHEMA_VERSION = 1
REQUIRED_FIELDS = (
    "schema_version",
    "sprint",
    "git_sha",
    "seed",
    "dataset_fingerprint",
    "wf_scheme",
    "wf_embargo",
    "created_at",
    "python_version",
    "platform",
)


class RunManifest(TypedDict, total=False):
    schema_version: int
    sprint: str
    git_sha: str
    seed: int
    dataset_fingerprint: str
    wf_scheme: str
    wf_embargo: int
    created_at: float
    python_version: str
    platform: str
    extras: dict[str, Any]


def _git_sha() -> str:
    """Best-effort ``git rev-parse HEAD``; falls back to empty string."""
    sha = os.environ.get("GIT_SHA")
    if sha:
        return sha
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            stderr=subprocess.DEVNULL,
            cwd=Path(__file__).resolve().parent,
            timeout=2.0,
        )
        return out.decode("ascii", errors="replace").strip()
    except (subprocess.SubprocessError, FileNotFoundError, OSError):
        return ""


def fingerprint_data(payload: Any) -> str:
    """Stable sha256 hex of any JSON-serialisable payload (sorted keys)."""
    blob = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def fingerprint_path(path: Path | str) -> str:
    """sha256 of file bytes; raises FileNotFoundError on missing input."""
    p = Path(path)
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def build_manifest(
    *,
    sprint: str,
    seed: int,
    dataset_fingerprint: str,
    wf_scheme: str = "expanding",
    wf_embargo: int = 1,
    git_sha: str | None = None,
    extras: Mapping[str, Any] | None = None,
) -> RunManifest:
    """Construct a fully-populated ``RunManifest``.

    All required fields are filled with sensible defaults so callers
    only need to provide the inputs they actually have. ``extras`` is
    free-form and survives serialisation.
    """
    if not sprint:
        raise ValueError("sprint must be a non-empty string")
    if seed < 0:
        raise ValueError(f"seed must be >= 0, got {seed}")
    manifest: RunManifest = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "sprint": sprint,
        "git_sha": git_sha if git_sha is not None else _git_sha(),
        "seed": int(seed),
        "dataset_fingerprint": dataset_fingerprint,
        "wf_scheme": wf_scheme,
        "wf_embargo": int(wf_embargo),
        "created_at": time.time(),
        "python_version": sys.version.split()[0],
        "platform": platform.platform(terse=True),
        "extras": dict(extras) if extras else {},
    }
    return manifest


def validate(manifest: Mapping[str, Any]) -> None:
    """Raise ``ValueError`` if ``manifest`` is missing a required field."""
    missing = [k for k in REQUIRED_FIELDS if k not in manifest]
    if missing:
        raise ValueError(f"manifest missing required fields: {missing}")
    if manifest["schema_version"] != MANIFEST_SCHEMA_VERSION:
        raise ValueError(
            f"unsupported schema_version: {manifest['schema_version']} "
            f"(expected {MANIFEST_SCHEMA_VERSION})"
        )
    if not isinstance(manifest["seed"], int):
        raise ValueError(f"seed must be int, got {type(manifest['seed']).__name__}")
    if not isinstance(manifest["wf_embargo"], int):
        raise ValueError("wf_embargo must be int")


def attach(payload: dict[str, Any], manifest: RunManifest) -> dict[str, Any]:
    """Return a shallow-copied ``payload`` with ``manifest`` injected under
    the canonical key ``run_manifest``."""
    if not isinstance(payload, dict):
        raise TypeError(f"payload must be a dict, got {type(payload).__name__}")
    out = dict(payload)
    out["run_manifest"] = dict(manifest)
    return out


def extract(payload: Mapping[str, Any]) -> RunManifest:
    """Pull the embedded ``run_manifest`` and ``validate`` it before returning."""
    if "run_manifest" not in payload:
        raise ValueError("payload has no 'run_manifest' key")
    manifest = payload["run_manifest"]
    validate(manifest)
    return manifest  # type: ignore[return-value]


__all__ = [
    "MANIFEST_SCHEMA_VERSION",
    "REQUIRED_FIELDS",
    "RunManifest",
    "attach",
    "build_manifest",
    "extract",
    "fingerprint_data",
    "fingerprint_path",
    "validate",
]
