from __future__ import annotations

from scripts.smc_atomic_write import atomic_write_text

import json
from pathlib import Path

from smc_integration.structure_audit import build_structure_gap_report


REPORT_PATH = Path("reports") / "smc_structure_audit.json"


def main() -> None:
    report = build_structure_gap_report()
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", REPORT_PATH)
    print(str(REPORT_PATH))


if __name__ == "__main__":
    main()
