"""Security contracts for the SMC TV bridge Node dependency lock."""

from __future__ import annotations

import json
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_PACKAGE_LOCK = _REPO_ROOT / "smc_tv_bridge" / "package-lock.json"


def test_body_parser_lock_excludes_cve_2026_12590() -> None:
    """Keep the transitive body-parser lock outside the vulnerable ranges."""
    lock = json.loads(_PACKAGE_LOCK.read_text(encoding="utf-8"))
    package = lock["packages"].get("node_modules/body-parser")
    if package is None:
        return

    version_text = package["version"]
    version = tuple(int(part) for part in version_text.split("."))

    vulnerable = version < (1, 20, 6) or (2, 0, 0) <= version < (2, 3, 0)

    assert not vulnerable, (
        f"body-parser {version_text} is affected by CVE-2026-12590; "
        "lock at least 1.20.6 (or 2.3.0 on the 2.x line)"
    )
