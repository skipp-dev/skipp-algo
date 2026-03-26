from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from smc_integration.extended_structure_discovery import build_extended_structure_discovery_report


DEFAULT_OUTPUT = Path("reports") / "extended_structure_discovery_report.json"


def export_extended_structure_discovery_report(*, output: Path = DEFAULT_OUTPUT) -> Path:
    payload = build_extended_structure_discovery_report()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return output


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Export extended structure discovery report for Phase 14.")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="Target output JSON file")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    written = export_extended_structure_discovery_report(output=Path(args.output).expanduser())
    print(written)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
