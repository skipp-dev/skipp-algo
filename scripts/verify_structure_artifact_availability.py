"""Fail closed unless primary per-timeframe structure artifacts are consumable."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]

from smc_integration.structure_contract import normalize_structure_contract


def verify_structure_artifact_availability(root: Path, timeframes: list[str]) -> dict[str, Any]:
    artifact_dir = root / "reports" / "smc_structure_artifacts"
    failures: list[str] = []
    verified: dict[str, int] = {}
    for timeframe in timeframes:
        manifest_path = artifact_dir / f"manifest_{timeframe}.json"
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            failures.append(f"{timeframe}: manifest unavailable or invalid ({type(exc).__name__})")
            continue
        rows = manifest.get("artifacts")
        if not isinstance(rows, list) or not rows:
            failures.append(f"{timeframe}: manifest has no artifacts")
            continue
        if manifest.get("errors"):
            failures.append(f"{timeframe}: manifest reports producer errors")
            continue
        loaded = 0
        for row in rows:
            if not isinstance(row, dict) or not str(row.get("artifact_path", "")).strip():
                failures.append(f"{timeframe}: malformed manifest artifact row")
                continue
            artifact_path = (root / str(row["artifact_path"])).resolve()
            try:
                payload = json.loads(artifact_path.read_text(encoding="utf-8"))
                contract = normalize_structure_contract(payload)
            except (OSError, ValueError, TypeError) as exc:
                failures.append(
                    f"{timeframe}: artifact {artifact_path.name} unavailable or invalid ({type(exc).__name__})"
                )
                continue
            if contract.symbol != str(row.get("symbol", "")).strip().upper() or contract.timeframe != timeframe:
                failures.append(f"{timeframe}: artifact identity does not match manifest row")
                continue
            loaded += 1
        if loaded:
            verified[timeframe] = loaded
    return {"ok": not failures and set(verified) == set(timeframes), "verified": verified, "failures": failures}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeframes", required=True, help="Comma-separated required timeframes")
    parser.add_argument("--root", type=Path, default=REPO_ROOT)
    args = parser.parse_args()
    timeframes = [value.strip() for value in args.timeframes.split(",") if value.strip()]
    if not timeframes:
        parser.error("--timeframes must contain at least one timeframe")
    report = verify_structure_artifact_availability(args.root.resolve(), timeframes)
    print(json.dumps(report, sort_keys=True))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
