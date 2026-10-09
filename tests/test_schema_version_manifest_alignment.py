"""Drift guard: ``SCHEMA_VERSION`` constant must match the published Pine manifest.

Audit lineage
-------------
Today's audit (2026-05-28..29) of the 5-week silent-publish-skip incident
uncovered a second, latent drift: the canonical schema constant in
:mod:`smc_core.schema_version` (``SCHEMA_VERSION``) had been bumped to
``3.0.0`` on 2026-04-23 (PR #23) but the committed Pine library manifest
``pine/generated/smc_micro_profiles_generated.json`` was never regenerated
and continued to declare ``schema_version="2.0.0"``. When the override
publish run (26598144143) finally regenerated the manifest it correctly
reported the bump as a MAJOR breaking change — but had no static lint
told us about the drift earlier, the next operator could just as easily
have published the wrong schema, skipped the bump signal, or wasted hours
re-investigating the same surprise.

Invariant
---------
For every release-tracked Pine library manifest under ``pine/generated/``
that declares a ``schema_version`` field, that value MUST equal
:data:`smc_core.schema_version.SCHEMA_VERSION`. The generator
(``scripts/generate_smc_micro_profiles.py``) is the single writer; the
test simply pins the equality so that bumping the constant without
regenerating fails fast in PR CI rather than silently in the next
publish.

Scope: this guard intentionally targets only the canonical generator
output. Test fixtures and sample manifests (``tests/fixtures/...``,
``samples/...``) are excluded — they pin historical schema versions for
regression coverage and must not be auto-rewritten.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from smc_core.schema_version import SCHEMA_VERSION

REPO_ROOT = Path(__file__).resolve().parent.parent

# Single canonical generator output. Add additional generator-owned
# manifests here if/when new Pine libraries adopt the same pattern.
TRACKED_MANIFESTS: tuple[Path, ...] = (
    REPO_ROOT / "pine" / "generated" / "smc_micro_profiles_generated.json",
)


@pytest.mark.parametrize("manifest_path", TRACKED_MANIFESTS, ids=lambda p: p.name)
def test_manifest_schema_version_matches_constant(manifest_path: Path) -> None:
    if not manifest_path.is_file():
        pytest.skip(f"manifest not present in working tree: {manifest_path}")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest_value = manifest.get("schema_version")
    assert manifest_value is not None, (
        f"{manifest_path.relative_to(REPO_ROOT).as_posix()} is missing the "
        "'schema_version' field. The generator must emit it on every run."
    )
    assert manifest_value == SCHEMA_VERSION, (
        f"Schema drift: smc_core.schema_version.SCHEMA_VERSION='{SCHEMA_VERSION}' "
        f"but {manifest_path.relative_to(REPO_ROOT).as_posix()} declares "
        f"schema_version='{manifest_value}'.\n"
        "Fix: regenerate the manifest with `python -m scripts.generate_smc_micro_profiles` "
        "and commit the result alongside the constant bump.\n"
        "Background: this drift caused the surprise MAJOR-bump diagnosed in run "
        "26598144143 (audit 2026-05-29)."
    )
