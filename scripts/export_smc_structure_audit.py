from __future__ import annotations

import json
from pathlib import Path

from smc_integration.structure_audit import build_structure_gap_report


REPORT_PATH = Path("reports") / "smc_structure_audit.json"


def main() -> None:
    report = build_structure_gap_report()
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(str(REPORT_PATH))


if __name__ == "__main__":
    main()
