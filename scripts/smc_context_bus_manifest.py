"""Canonical Context BUS v3 channel contract.

The producer and consumer deliberately use a separate domain-first transport
from Engine BUS v2.  Keep this module small and dependency-free so CI, binding
automation, and release tooling can all consume the same ordered contract.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path

from scripts.smc_atomic_write import atomic_write_text

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "artifacts/governance/smc_context_bus_v3_manifest.json"

SCHEMA_VERSION = 8001
CHANNEL_PREFIX = "CTX "
TRADINGVIEW_PLOT_LIMIT = 64
# 2026-07-31: 60 -> 62. Two of the four reserved slots were spent on the
# session-MSS channels (SessionMssBull/Bear) that close the gap recorded by
# the R5 Pro-HTF preset decision. The schema stays 8001: the reserve exists
# precisely for ADDITIVE growth, bindings are by name, and a bump would blind
# every deployed 8001 consumer (the R4 shadow overlay) until re-saved.
MAX_CHANNELS = 62
MIN_RESERVED_CHANNELS = 2


@dataclass(frozen=True)
class ContextChannel:
    name: str
    group: str
    value_type: str
    required: bool = False

    @property
    def label(self) -> str:
        return f"{CHANNEL_PREFIX}{self.name}"


CONTEXT_BUS_CHANNELS: tuple[ContextChannel, ...] = (
    ContextChannel("SchemaVersion", "meta", "int", True),
    ContextChannel("Ready", "meta", "bool", True),
    ContextChannel("AvailabilityMask", "meta", "int", True),
    ContextChannel("ConfirmedEpoch", "meta", "unix_seconds", True),
    ContextChannel("Bias", "aggregate", "direction", True),
    ContextChannel("AvailableDomains", "aggregate", "int", True),
    ContextChannel("QualityScore", "aggregate", "percent", True),
    ContextChannel("StructureTrend", "structure", "direction"),
    ContextChannel("StructureBos", "structure", "bool"),
    ContextChannel("StructureChoch", "structure", "bool"),
    ContextChannel("StructureEventDirection", "structure", "direction"),
    ContextChannel("StructureResistance", "structure", "price"),
    ContextChannel("StructureSupport", "structure", "price"),
    ContextChannel("StructureEventAgeBars", "structure", "int"),
    ContextChannel("ImbalanceState", "imbalance", "enum"),
    ContextChannel("FvgBias", "imbalance", "direction"),
    ContextChannel("BullFvgActive", "imbalance", "bool"),
    ContextChannel("BearFvgActive", "imbalance", "bool"),
    ContextChannel("BullFvgTop", "imbalance", "price"),
    ContextChannel("BullFvgBottom", "imbalance", "price"),
    ContextChannel("BearFvgTop", "imbalance", "price"),
    ContextChannel("BearFvgBottom", "imbalance", "price"),
    ContextChannel("BprActive", "imbalance", "bool"),
    ContextChannel("BprDirection", "imbalance", "direction"),
    ContextChannel("BprTop", "imbalance", "price"),
    ContextChannel("BprBottom", "imbalance", "price"),
    ContextChannel("LiquidityVoidActive", "imbalance", "bool"),
    ContextChannel("LiquidityVoidTop", "imbalance", "price"),
    ContextChannel("LiquidityVoidBottom", "imbalance", "price"),
    ContextChannel("ZoneState", "zone", "enum"),
    ContextChannel("ObBias", "zone", "direction"),
    ContextChannel("BullObTop", "zone", "price"),
    ContextChannel("BullObBottom", "zone", "price"),
    ContextChannel("BearObTop", "zone", "price"),
    ContextChannel("BearObBottom", "zone", "price"),
    ContextChannel("BullObNew", "zone", "bool"),
    ContextChannel("BearObNew", "zone", "bool"),
    ContextChannel("BullObBroken", "zone", "bool"),
    ContextChannel("BearObBroken", "zone", "bool"),
    ContextChannel("SweepDirection", "sweep", "direction"),
    ContextChannel("SweepType", "sweep", "enum"),
    ContextChannel("SweepZoneTop", "sweep", "price"),
    ContextChannel("SweepZoneBottom", "sweep", "price"),
    ContextChannel("SweepReclaimActive", "sweep", "bool"),
    ContextChannel("SweepQualityScore", "sweep", "score_0_5"),
    ContextChannel("SweepEventAgeBars", "sweep", "int"),
    ContextChannel("BuyPoolLevel", "pool", "price"),
    ContextChannel("SellPoolLevel", "pool", "price"),
    ContextChannel("BuyPoolStrength", "pool", "score_0_5"),
    ContextChannel("SellPoolStrength", "pool", "score_0_5"),
    ContextChannel("PoolMagnetDirection", "pool", "direction"),
    ContextChannel("PoolImbalance", "pool", "ratio_minus1_plus1"),
    ContextChannel("SessionCode", "session", "enum"),
    ContextChannel("SessionKillzone", "session", "bool"),
    ContextChannel("SessionRangeTop", "session", "price"),
    ContextChannel("SessionRangeBottom", "session", "price"),
    ContextChannel("OpeningRangeActive", "session", "bool"),
    ContextChannel("OpeningRangeTop", "session", "price"),
    ContextChannel("OpeningRangeBottom", "session", "price"),
    ContextChannel("SessionDirection", "session", "direction"),
    # Session-level MSS: the confirmed close crossing the PREVIOUS session's
    # extreme (one-bar pulse). NOT the structure event during a session — that
    # is derivable from StructureBos/StructureChoch/StructureEventDirection.
    # Appended (not inserted) because producer plots and consumer bindings are
    # order-pinned to this list, and operators bind top-to-bottom.
    ContextChannel("SessionMssBull", "session", "bool"),
    ContextChannel("SessionMssBear", "session", "bool"),
)


def build_manifest() -> dict[str, object]:
    channels = [
        {
            "index": index,
            "label": channel.label,
            **asdict(channel),
        }
        for index, channel in enumerate(CONTEXT_BUS_CHANNELS, start=1)
    ]
    return {
        "manifestVersion": 1,
        "producer": "SMC_Context_Bus.pine",
        "consumer": "SMC_Context_Overlay.pine",
        "schemaVersion": SCHEMA_VERSION,
        "channelPrefix": CHANNEL_PREFIX,
        "channelCount": len(channels),
        "plotLimit": TRADINGVIEW_PLOT_LIMIT,
        "reservedChannels": TRADINGVIEW_PLOT_LIMIT - len(channels),
        "maxChannels": MAX_CHANNELS,
        "minReservedChannels": MIN_RESERVED_CHANNELS,
        "channels": channels,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    rendered = json.dumps(build_manifest(), indent=2, sort_keys=False) + "\n"
    if args.check:
        if not args.output.exists() or args.output.read_text(encoding="utf-8") != rendered:
            raise SystemExit(f"Context BUS manifest drift: regenerate {args.output}")
        return 0

    atomic_write_text(rendered, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
