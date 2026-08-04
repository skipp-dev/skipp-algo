#!/usr/bin/env python3
"""Report R1 companion pin drift against the published library version.

Since #4435 the library refresh HOLDS the R1-attested companions, so their
``smc_micro_profiles_generated`` import pin never moves automatically. The
library is the generated micro-profile data, so a growing lag is potentially
trade-relevant, not cosmetic. This watcher makes the lag visible (issue via
workflow-freshness-monitor); moving the pin stays a deliberate re-attestation
(design: docs/superpowers/specs/2026-08-04-r1-reattestation-design.md).

Read-only: reads the rollout contract and the release manifest, writes a
report under artifacts/ci/ and $GITHUB_OUTPUT. Never touches TradingView.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from scripts.smc_atomic_write import atomic_write_text

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "artifacts" / "tradingview" / "library_release_manifest.json"
DEFAULT_REPORT = ROOT / "artifacts" / "ci" / "r1_pin_drift.json"
# >= 3 versions behind (operator decision 2026-08-04): ~2 trading days of
# library movement. Weekend gaps do not trigger; real drift shows within days.
THRESHOLD = 3


def compute_pin_drift(
    manifest_path: Path | None,
    *,
    targets: list[dict] | None = None,
    threshold: int = THRESHOLD,
) -> dict:
    """Pure verdict. ``None`` arguments mean "read the live tree"."""
    if targets is None:
        from scripts.smc_r1_rollout_contract import build_rollout_contract

        targets = build_rollout_contract()["targets"]
    if not targets:
        raise ValueError("refusing an empty target roster — vacuous all-clear")

    manifest = json.loads(
        (manifest_path or MANIFEST).read_text(encoding="utf-8")
    )
    published = manifest["library"]["publishedVersion"]
    if not isinstance(published, int):
        raise ValueError(f"library.publishedVersion is not an int: {published!r}")

    rows: list[dict] = []
    for target in targets:
        pin = target.get("libraryPin")
        if pin is None:
            # Exit_Signal has no library import — by design, not an error.
            rows.append({"path": target["path"], "driftCapable": False})
            continue
        rows.append(
            {
                "path": target["path"],
                "driftCapable": True,
                "pinVersion": pin["version"],
                "publishedVersion": published,
                "lag": published - pin["version"],
            }
        )
    capable = [r for r in rows if r["driftCapable"]]
    if not capable:
        raise ValueError(
            "no drift-capable target left — the watcher would be vacuously "
            "green forever; if the last libraryPin was removed on purpose, "
            "remove this watcher with it"
        )
    max_lag = max(r["lag"] for r in capable)
    return {
        "schemaVersion": 1,
        "threshold": threshold,
        "maxLag": max_lag,
        "drifted": max_lag >= threshold,
        "targets": rows,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=DEFAULT_REPORT)
    parser.add_argument(
        "--github-output", default=os.environ.get("GITHUB_OUTPUT")
    )
    args = parser.parse_args(argv)

    report = compute_pin_drift(None)
    atomic_write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", args.out)

    verdict = "DRIFTED" if report["drifted"] else "ok"
    print(f"r1 pin drift: {verdict} (maxLag={report['maxLag']}, threshold={report['threshold']})")
    for row in report["targets"]:
        if row["driftCapable"]:
            print(f"  {row['path']}: pin {row['pinVersion']} vs published {row['publishedVersion']}")
        else:
            print(f"  {row['path']}: no libraryPin — not drift-capable (by design)")

    if args.github_output:
        with Path(args.github_output).open("a", encoding="utf-8") as handle:
            handle.write(f"drifted={'true' if report['drifted'] else 'false'}\n")
            handle.write(f"max_lag={report['maxLag']}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
