"""Generate a showcase summary from reference_enrichment.json.

Extracts the lean surface from the hand-maintained showcase fixture,
rebuilds adapter-derivable blocks (event_risk_light from broad event_risk,
signal_quality from lean blocks), and outputs a consolidated summary.

This is the **showcase artifact lane** — parallel to the seed lane
(generate_smc_micro_profiles.py) but for the enriched reference.

Usage::

    python scripts/generate_showcase_summary.py

Produces: tests/fixtures/showcase_adapter_summary.json
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

FIXTURE = ROOT / "tests" / "fixtures" / "reference_enrichment.json"
OUTPUT = ROOT / "tests" / "fixtures" / "showcase_adapter_summary.json"

# The 6 lean families
LEAN_FAMILIES = [
    "event_risk_light",
    "session_context_light",
    "ob_context_light",
    "fvg_lifecycle_light",
    "structure_state_light",
    "signal_quality",
]


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


def main() -> None:
    summary = generate()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT, "w") as f:
        json.dump(summary, f, indent=2)
    print(f"Showcase adapter summary written to {OUTPUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
