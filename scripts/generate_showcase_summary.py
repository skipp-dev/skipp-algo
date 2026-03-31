"""Generate showcase artifacts from reference_enrichment.json.

Extracts the lean surface from the hand-maintained showcase fixture,
rebuilds adapter-derivable blocks (event_risk_light from broad event_risk,
signal_quality from lean blocks), and outputs:

  1. ``showcase_adapter_summary.json`` — fixture-vs-derived comparison
  2. ``showcase_lean_surface.pine`` — Pine const-block for review
  3. ``showcase_manifest.json`` — machine-readable artifact registry

This is the **showcase artifact lane** — parallel to the seed lane
(generate_smc_micro_profiles.py) but for the enriched reference.

Usage::

    python scripts/generate_showcase_summary.py

Produces: tests/fixtures/generated_showcase/
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

FIXTURE = ROOT / "tests" / "fixtures" / "reference_enrichment.json"
OUTPUT_DIR = ROOT / "tests" / "fixtures" / "generated_showcase"

# Also keep legacy path for backward compat
LEGACY_OUTPUT = ROOT / "tests" / "fixtures" / "showcase_adapter_summary.json"

# The 6 lean families
LEAN_FAMILIES = [
    "event_risk_light",
    "session_context_light",
    "ob_context_light",
    "fvg_lifecycle_light",
    "structure_state_light",
    "signal_quality",
]

# Pine type mapping
_PINE_TYPE_MAP = {
    str: "string",
    int: "int",
    float: "float",
    bool: "bool",
}


def _pine_literal(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return f'"{value}"'
    return str(value)


def generate() -> dict:
    """Build showcase summary from fixture lean blocks.

    - event_risk_light is re-derived from the broad event_risk block
      to verify fixture consistency.
    - signal_quality is re-derived from the lean blocks to verify
      the fixture's SQ values are plausible.
    - Other lean blocks are accepted as-is (hand-maintained fixtures with
      no broad source block in the fixture).
    """
    with open(FIXTURE) as f:
        enr = json.load(f)

    from scripts.smc_event_risk_light import build_event_risk_light
    from scripts.smc_signal_quality import build_signal_quality

    # Re-derive event_risk_light from broad event_risk
    erl_derived = build_event_risk_light(event_risk=enr.get("event_risk"))

    # Accept hand-maintained lean blocks for families without broad source
    scl = enr.get("session_context_light", {})
    ob = enr.get("ob_context_light", {})
    fvg = enr.get("fvg_lifecycle_light", {})
    ssl = enr.get("structure_state_light", {})

    # Re-derive signal_quality from lean blocks
    sq_enrichment = {
        "event_risk_light": erl_derived,
        "session_context_light": scl,
        "ob_context_light": ob,
        "fvg_lifecycle_light": fvg,
        "structure_state_light": ssl,
    }
    sq_derived = build_signal_quality(enrichment=sq_enrichment)

    return {
        "_meta": {
            "source": "tests/fixtures/reference_enrichment.json",
            "generator": "scripts/generate_showcase_summary.py",
            "description": "Showcase lean surface — adapter-verified where possible",
        },
        "event_risk_light": {
            "fixture": enr.get("event_risk_light", {}),
            "derived": erl_derived,
        },
        "session_context_light": scl,
        "ob_context_light": ob,
        "fvg_lifecycle_light": fvg,
        "structure_state_light": ssl,
        "signal_quality": {
            "fixture": enr.get("signal_quality", {}),
            "derived": sq_derived,
        },
    }


def generate_pine_surface(enr: dict) -> str:
    """Generate a Pine const-block showing the lean surface with enriched values."""
    lines = [
        "//@version=6",
        '// Showcase Lean Surface — generated from reference_enrichment.json',
        '// This file is for REVIEW ONLY, not published as a library.',
        '',
    ]
    for family in LEAN_FAMILIES:
        block = enr.get(family, {})
        lines.append(f'// ── {family} ──')
        for key, val in block.items():
            pine_type = _PINE_TYPE_MAP.get(type(val), "string")
            lines.append(f'export const {pine_type} {key} = {_pine_literal(val)}')
        lines.append('')

    return '\n'.join(lines)


def generate_manifest(summary: dict, artifacts: list[str]) -> dict:
    """Build machine-readable manifest for the showcase artifact set."""
    from smc_core.schema_version import SCHEMA_VERSION

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": time.time(),
        "generator": "scripts/generate_showcase_summary.py",
        "source_fixture": "tests/fixtures/reference_enrichment.json",
        "lean_families": LEAN_FAMILIES,
        "artifacts": artifacts,
    }


def main() -> None:
    summary = generate()

    # Read fixture for Pine surface generation
    with open(FIXTURE) as f:
        enr = json.load(f)

    pine_surface = generate_pine_surface(enr)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # 1. Adapter summary
    summary_path = OUTPUT_DIR / "showcase_adapter_summary.json"
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2)

    # Legacy path (backward compat for existing tests)
    LEGACY_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with open(LEGACY_OUTPUT, "w") as f:
        json.dump(summary, f, indent=2)

    # 2. Pine lean surface
    pine_path = OUTPUT_DIR / "showcase_lean_surface.pine"
    pine_path.write_text(pine_surface, encoding="utf-8")

    # 3. Manifest
    artifacts = ["showcase_adapter_summary.json", "showcase_lean_surface.pine"]
    manifest = generate_manifest(summary, artifacts)
    manifest_path = OUTPUT_DIR / "showcase_manifest.json"
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)

    rel = OUTPUT_DIR.relative_to(ROOT)
    print(f"Showcase artifacts written to {rel}/")
    for a in artifacts + ["showcase_manifest.json"]:
        print(f"  {a}")


if __name__ == "__main__":
    main()
