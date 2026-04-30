"""Sprint X3 — Run-Manifest helper for reproducibility headers.

Sprint scripts (C2/C3/C4/C6) emit JSON artifacts without a uniform
provenance header. Re-runs on new datasets can silently drift because
``(git_sha, schema_version, seed, dataset_fingerprint)`` is not visible
in the output.

This module provides a single ``build_manifest(...)`` helper plus a
``RunManifest`` TypedDict so every primary artifact can carry the
canonical reproducibility tuple. CI test
``tests/test_run_manifest_required.py`` round-trips the schema.

Stdlib-only.

Roadmap: docs/IMPROVEMENTS_C2_C12_ROADMAP_2026-04-26.md#x3
"""
from __future__ import annotations

import functools
import hashlib
import json
import os
import platform
import shutil
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


@functools.lru_cache(maxsize=1)
def _git_sha() -> str:
    """Best-effort ``git rev-parse HEAD``; falls back to empty string.

    Cached for the lifetime of the process to avoid spawning a
    subprocess on every ``build_manifest`` call.
    """
    sha = os.environ.get("GIT_SHA")
    if sha:
        return sha
    try:
        git_exe = shutil.which("git") or "git"
        out = subprocess.check_output(  # noqa: S603 -- hardcoded git argv resolved via shutil.which (no shell, no user input)
            [git_exe, "rev-parse", "HEAD"],
            stderr=subprocess.DEVNULL,
            cwd=Path(__file__).resolve().parent,
            timeout=2.0,
        )
        return out.decode("ascii", errors="replace").strip()
    except (subprocess.SubprocessError, FileNotFoundError, OSError):
        return ""


def fingerprint_data(payload: Any) -> str:
    """Stable sha256 hex of any JSON-serialisable payload (sorted keys).

    The payload must be strictly JSON-serialisable: ``dict``, ``list``,
    ``tuple``, ``str``, ``int``, ``float``, ``bool``, or ``None``. Types
    like ``set``, ``Path`` or ``datetime`` are rejected via ``TypeError``
    rather than coerced to a possibly non-deterministic string, because
    the stability guarantee is the entire point of this function.
    Callers needing those types should canonicalise them first.
    """
    blob = json.dumps(payload, sort_keys=True).encode("utf-8")
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
    if not isinstance(dataset_fingerprint, str) or not dataset_fingerprint:
        raise ValueError("dataset_fingerprint must be a non-empty string")
    if not isinstance(wf_scheme, str) or not wf_scheme:
        raise ValueError("wf_scheme must be a non-empty string")
    if wf_embargo < 0:
        raise ValueError(f"wf_embargo must be >= 0, got {wf_embargo}")
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
    if not isinstance(manifest, Mapping):
        raise ValueError(
            f"manifest must be a mapping, got {type(manifest).__name__}"
        )
    missing = [k for k in REQUIRED_FIELDS if k not in manifest]
    if missing:
        raise ValueError(f"manifest missing required fields: {missing}")
    if manifest["schema_version"] != MANIFEST_SCHEMA_VERSION:
        raise ValueError(
            f"unsupported schema_version: {manifest['schema_version']} "
            f"(expected {MANIFEST_SCHEMA_VERSION})"
        )
    # ``bool`` is a subclass of ``int`` in Python; reject it explicitly so
    # ``True``/``False`` are not silently accepted as seed/embargo values.
    seed = manifest["seed"]
    if type(seed) is not int:
        raise ValueError(f"seed must be int, got {type(seed).__name__}")
    embargo = manifest["wf_embargo"]
    if type(embargo) is not int:
        raise ValueError(f"wf_embargo must be int, got {type(embargo).__name__}")


def attach(
    payload: dict[str, Any],
    manifest: RunManifest,
    *,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Return a shallow-copied ``payload`` with ``manifest`` injected under
    the canonical key ``run_manifest``.

    Raises ``ValueError`` if ``payload`` already has a ``run_manifest`` key
    unless ``overwrite=True``.
    """
    if not isinstance(payload, dict):
        raise TypeError(f"payload must be a dict, got {type(payload).__name__}")
    if "run_manifest" in payload and not overwrite:
        raise ValueError(
            "payload already has a 'run_manifest' key; pass overwrite=True to replace"
        )
    out = dict(payload)
    out["run_manifest"] = dict(manifest)
    return out


def extract(payload: Mapping[str, Any]) -> RunManifest:
    """Pull the embedded ``run_manifest`` and ``validate`` it before returning."""
    if not isinstance(payload, Mapping):
        raise ValueError(
            f"payload must be a mapping, got {type(payload).__name__}"
        )
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
