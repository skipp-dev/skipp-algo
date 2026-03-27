"""Central resolver for the SMC microstructure profile schema path.

Every script, test, and runtime entry-point that needs the microstructure
profile schema should call ``resolve_microstructure_schema_path()`` instead
of hardcoding a path.
"""
from __future__ import annotations

from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_CANONICAL_PATH = _REPO_ROOT / "spec" / "smc_microstructure_profile.schema.json"


def resolve_microstructure_schema_path() -> Path:
    """Return the canonical schema path, raising if the file is missing."""
    if not _CANONICAL_PATH.exists():
        raise FileNotFoundError(
            f"Microstructure profile schema not found at canonical location: {_CANONICAL_PATH}"
        )
    return _CANONICAL_PATH
