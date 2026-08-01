"""Generate the TEST ONLY Context BUS readback fixture for the R4 parity gate.

``R4-OVERLAY`` asks for the Context structure and zone output to be compared
against Suite and Breakout evidence. It could not be closed because every CTX
channel is plotted with ``display = display.none``: TradingView renders those
nowhere, not even in the Data Window, so the values are not readable from the
UI. See ``docs/SMC_R4_CONTEXT_READBACK_DECISION.md`` for why the previously
recorded blocker ("a second competing observability mechanism is ruled out")
does not hold, and why option C was chosen.

Option C, implemented here:

* every one of the contract's channels is re-flagged to ``display.data_window``
  so the full dump is readable, and
* the structure and zone channels named by the gate additionally render into a
  TEST ONLY on-chart table, so a parity comparison does not depend on hovering
  one bar at a time.

Both live ONLY in this generated fixture. The R2.4 precedent's real constraint
is that a readback must never enter the production surface, and that holds:
``SMC_Context_Bus.pine`` keeps ``display.none`` everywhere and contains no
table. The generator is fail-closed — it refuses to emit unless the parsed
channel labels match ``scripts.smc_context_bus_manifest`` exactly, so source
drift cannot silently produce a fixture that reads back the wrong contract.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Final

from scripts.smc_atomic_write import atomic_write_text
from scripts.smc_context_bus_manifest import (
    CONTEXT_BUS_CHANNELS,
    MAX_CHANNELS,
    SCHEMA_VERSION,
)

ROOT: Final = Path(__file__).resolve().parents[1]
SOURCE: Final = ROOT / "SMC_Context_Bus.pine"
FIXTURE: Final = (
    ROOT / "tests" / "fixtures" / "pine" / "smc_context_bus_r4_readback_fixture.pine"
)
MANIFEST: Final = (
    ROOT
    / "artifacts"
    / "governance"
    / "smc_context_bus_r4_readback_fixture_manifest.json"
)

FIXTURE_SCRIPT_NAME: Final = "SMC Context Bus R4 Readback TEST ONLY"

# The gate compares structure and zone output, so those groups form the table.
PARITY_GROUPS: Final = ("structure", "zone")

_PLOT_RE: Final = re.compile(
    r'^plot\((?P<expr>.+), "(?P<label>CTX [A-Za-z0-9]+)", display = display\.none\)$'
)
_INDICATOR_RE: Final = re.compile(r'^indicator\("SMC Context Bus", overlay = false\)$')
_VERSION_RE: Final = re.compile(r"^//@version=\d+$")


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def parity_channel_names() -> tuple[str, ...]:
    """Contract-ordered channel names the parity table renders."""
    return tuple(c.name for c in CONTEXT_BUS_CHANNELS if c.group in PARITY_GROUPS)


def _parse_channel_plots(source_text: str) -> dict[str, str]:
    """Map ``CTX <Name>`` label to the plotted expression, fail-closed."""
    found: dict[str, str] = {}
    for line in source_text.splitlines():
        match = _PLOT_RE.match(line)
        if match is None:
            continue
        label = match.group("label")
        if label in found:
            raise ValueError(f"duplicate channel plot for {label!r}")
        found[label] = match.group("expr")

    expected = {f"CTX {c.name}" for c in CONTEXT_BUS_CHANNELS}
    if set(found) != expected:
        missing = sorted(expected - set(found))
        extra = sorted(set(found) - expected)
        raise ValueError(
            "parsed channel plots do not match the contract in "
            f"scripts/smc_context_bus_manifest.py — missing={missing} extra={extra}"
        )
    if len(found) != MAX_CHANNELS:
        raise ValueError(f"expected {MAX_CHANNELS} channel plots, parsed {len(found)}")
    return found


def _parity_table_block(plots: dict[str, str]) -> str:
    names = parity_channel_names()
    rows = len(names) + 1
    lines = [
        "",
        "// ── TEST-ONLY R4 PARITY READBACK ─────────────────────────────────────────────",
        "// The structure and zone channels the R4-OVERLAY gate compares against Suite",
        "// and Breakout evidence, rendered so their VALUES are readable without",
        "// hovering one bar at a time. This block exists ONLY in this generated",
        "// fixture — never add it to SMC_Context_Bus.pine.",
        f"var table r4_parity = table.new(position.top_right, 2, {rows}, border_width = 1)",
        "if barstate.islast",
        '    table.cell(r4_parity, 0, 0, "R4 PARITY — TEST ONLY", '
        "text_color = color.white, bgcolor = color.new(color.red, 20))",
        '    table.cell(r4_parity, 1, 0, str.tostring(bar_index), '
        "text_color = color.white, bgcolor = color.new(color.red, 20))",
    ]
    for row, name in enumerate(names, start=1):
        expr = plots[f"CTX {name}"]
        lines.append(f'    table.cell(r4_parity, 0, {row}, "{name}")')
        lines.append(f"    table.cell(r4_parity, 1, {row}, str.tostring({expr}))")
    return "\n".join(lines) + "\n"


def build_fixture(source_text: str) -> str:
    """Return the generated fixture Pine for ``source_text``."""
    plots = _parse_channel_plots(source_text)

    version_lines = [
        line for line in source_text.splitlines() if _VERSION_RE.match(line)
    ]
    if len(version_lines) != 1:
        raise ValueError(
            f"expected exactly one //@version annotation, found {len(version_lines)}"
        )

    out: list[str] = []
    renamed = False
    for line in source_text.splitlines():
        if _VERSION_RE.match(line):
            # Hoisted to line 1 below, matching the R2.4 fixture: the version
            # annotation must precede the generated banner, not follow it.
            continue
        if _INDICATOR_RE.match(line):
            out.append(f'indicator("{FIXTURE_SCRIPT_NAME}", overlay = false)')
            renamed = True
            continue
        match = _PLOT_RE.match(line)
        if match is None:
            out.append(line)
            continue
        out.append(
            f'plot({match.group("expr")}, "{match.group("label")}", '
            "display = display.data_window)"
        )
    if not renamed:
        raise ValueError(
            "canonical indicator declaration not found — refusing to emit a fixture "
            "that would collide with the production saved script name"
        )

    banner = [
        version_lines[0],
        f"// GENERATED FROM SMC_Context_Bus.pine SHA256 {_sha256(source_text)}",
        "// TEST ONLY — DO NOT PUBLISH, DO NOT ADD TO THE MANAGED ROLLOUT",
        "// Regenerate with scripts/generate_smc_context_bus_r4_readback_fixture.py.",
        "// Readback for the R4-OVERLAY parity gate: channels are re-flagged to",
        "// display.data_window and the structure/zone subset also renders in a",
        "// TEST ONLY table. Decision: docs/SMC_R4_CONTEXT_READBACK_DECISION.md",
        "",
    ]
    body = "\n".join(out)
    return "\n".join(banner) + body + "\n" + _parity_table_block(plots)


def build_manifest(source_text: str, fixture_text: str) -> dict:
    return {
        "schemaVersion": 1,
        "generator": "scripts/generate_smc_context_bus_r4_readback_fixture.py",
        "requirementId": "R4-OVERLAY",
        "decisionDoc": "docs/SMC_R4_CONTEXT_READBACK_DECISION.md",
        "canonicalSource": {
            "path": "SMC_Context_Bus.pine",
            "sha256": _sha256(source_text),
        },
        "fixture": {
            "path": "tests/fixtures/pine/smc_context_bus_r4_readback_fixture.pine",
            "sha256": _sha256(fixture_text),
            "savedScript": FIXTURE_SCRIPT_NAME,
            "visibility": "private",
            "publicationStatus": "must_not_be_published",
        },
        "contract": {
            "schemaVersion": SCHEMA_VERSION,
            "channelCount": MAX_CHANNELS,
            "dataWindowChannels": MAX_CHANNELS,
            "parityGroups": list(PARITY_GROUPS),
            "parityChannels": list(parity_channel_names()),
        },
    }


def main() -> None:
    source_text = SOURCE.read_text(encoding="utf-8")
    fixture_text = build_fixture(source_text)
    atomic_write_text(fixture_text, FIXTURE)
    atomic_write_text(
        json.dumps(build_manifest(source_text, fixture_text), indent=2) + "\n",
        MANIFEST,
    )


if __name__ == "__main__":
    main()
