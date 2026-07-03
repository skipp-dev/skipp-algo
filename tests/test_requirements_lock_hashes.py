from __future__ import annotations

from pathlib import Path

import pytest


@pytest.mark.parametrize("lock_path", (Path("requirements.lock"), Path("requirements-dashboard.lock")))
def test_requirements_locks_carry_hashes(lock_path: Path) -> None:
    lock = lock_path.read_text(encoding="utf-8")
    assert "--hash=sha256:" in lock, f"SC-04: {lock_path} must be generated with --generate-hashes"


@pytest.mark.parametrize("dockerfile", (Path("Dockerfile"), Path("Dockerfile.dashboard")))
def test_dockerfiles_require_hash_verified_installs(dockerfile: Path) -> None:
    contents = dockerfile.read_text(encoding="utf-8")
    assert "--require-hashes" in contents, f"SC-04: {dockerfile} must enforce hash-verified pip installs"
