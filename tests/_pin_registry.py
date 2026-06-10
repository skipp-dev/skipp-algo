"""Loader for ``pin_registry.toml`` — single source of truth for ledger pins.

Each accessor returns the slice owned by exactly one ledger test under
``tests/``. Tests must import from this module (never parse the TOML
directly) so the schema stays enforceable in one place.

See ``docs/adr/0009-pin-ledger-consolidation.md`` (Accepted, Option B).
"""

from __future__ import annotations

import tomllib
from functools import lru_cache
from pathlib import Path
from typing import Any

_REGISTRY_PATH = Path(__file__).resolve().parent.parent / "pin_registry.toml"


@lru_cache(maxsize=1)
def _load() -> dict[str, Any]:
    with _REGISTRY_PATH.open("rb") as fp:
        return tomllib.load(fp)


def pytest_skip_file_counts() -> dict[str, int]:
    """Return the frozen pytest.skip count per test file (relative posix)."""
    return dict(_load()["pytest_skip_budget"]["file_counts"])


def urllib_urlopen_sites() -> dict[str, frozenset[int]]:
    """Return frozen urlopen sites: ``rel_posix -> frozenset[lineno]``."""
    raw = _load()["urllib_urlopen_ledger"]["sites"]
    return {rel: frozenset(linenos) for rel, linenos in raw.items()}


def noqa_sites() -> frozenset[tuple[str, int, tuple[str, ...]]]:
    """Return frozen noqa sites as a set of ``(file, line, sorted-codes)``."""
    raw = _load()["noqa_budget"]["sites"]
    return frozenset(
        (entry["file"], int(entry["line"]), tuple(entry["codes"]))
        for entry in raw
    )


def workflow_allowed_orphans() -> frozenset[str]:
    """Return workflow basenames explicitly allowed to be orphans."""
    return frozenset(_load()["workflow_orphan_inventory"]["allowed"])


def workflow_set_plus_e_allowed() -> dict[str, int]:
    """Return ``set +e`` occurrence budget per workflow basename."""
    return dict(_load()["workflow_set_plus_e_inventory"]["allowed"])


def subprocess_shell_sites() -> dict[tuple[str, str], int]:
    """Return frozen subprocess sites: ``(file, attr) -> count``."""
    raw = _load()["subprocess_shell_injection_pin"]["sites"]
    return {(entry["file"], entry["attr"]): int(entry["count"]) for entry in raw}


def upload_artifact_frozen_major() -> str:
    """Return the frozen major version (e.g. ``"v7"``) for upload-artifact."""
    return str(_load()["workflow_upload_artifact_uniform_version"]["frozen_major"])


def upload_artifact_sha_allowlist() -> dict[str, str]:
    """Return SHA→major mapping for SHA-pinned upload-artifact references."""
    return dict(
        _load()["workflow_upload_artifact_uniform_version"][
            "sha_to_major_allowlist"
        ]
    )


def field_preference_chain_file_counts() -> dict[str, int]:
    """Return the frozen per-file count of field-preference ``or``-chains.

    A site is one ``or`` chain containing >=2 ``.get("literal")`` calls
    with >=2 distinct keys (audit #2670 G1). Keys are repo-relative posix
    paths; values are site counts per file.
    """
    return {
        rel: int(count)
        for rel, count in _load()["field_preference_chain_ledger"][
            "file_counts"
        ].items()
    }
