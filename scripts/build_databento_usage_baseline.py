"""Build a secret-free Databento dataset inventory from one Git revision."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from collections import Counter
from pathlib import Path

DATASETS = (
    "DBEQ.BASIC",
    "EQUS.MINI",
    "EQUS.SUMMARY",
    "XNAS.ITCH",
    "XNAS.BASIC",
    "XNYS.PILLAR",
    "XASE.PILLAR",
    "ARCX.PILLAR",
    "OPRA.PILLAR",
    "GLBX.MDP3",
)
OVERRIDES = (
    "DATABENTO_DATASET",
    "DATABENTO_EQUITY_INTRADAY_DATASET",
    "DATABENTO_EQUITY_EOD_DATASET",
    "DATABENTO_OPTIONS_LIVE_DATASET",
)
TEXT_SUFFIXES = {".py", ".md", ".yml", ".yaml", ".toml", ".json", ".sh"}


def _git(*args: str) -> str:
    executable = shutil.which("git")
    if executable is None:
        raise RuntimeError("git executable not found")
    return subprocess.run(  # noqa: S603 - fixed executable plus explicit argv
        [executable, *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout


def _classification(path: str) -> str:
    if path.startswith("tests/"):
        return "test_fixture"
    if path.startswith(".github/workflows/"):
        return "workflow_configuration"
    if path.startswith(("docs/", "README", "CHANGELOG")):
        return "documentation"
    if path.startswith(("artifacts/", "reports/")):
        return "historical_artifact_or_report"
    name = Path(path).name
    if name.startswith(("probe_", "analyze_", "benchmark_", "study_")):
        return "research_or_cli"
    return "runtime_or_library"


def build_inventory(revision: str) -> dict:
    resolved = _git("rev-parse", revision).strip()
    paths = _git("ls-tree", "-r", "--name-only", revision).splitlines()
    findings: list[dict] = []
    needles = DATASETS + OVERRIDES
    for path in paths:
        if Path(path).suffix not in TEXT_SUFFIXES:
            continue
        try:
            text = _git("show", f"{revision}:{path}")
        except subprocess.CalledProcessError:
            continue
        for line_number, line in enumerate(text.splitlines(), 1):
            matches = sorted(needle for needle in needles if needle in line)
            if matches:
                findings.append(
                    {
                        "path": path,
                        "line": line_number,
                        "classification": _classification(path),
                        "matches": matches,
                    }
                )
    counts = Counter(item["classification"] for item in findings)
    return {
        "version": "databento-baseline/v1",
        "revision": resolved,
        "source_revision": revision,
        "generated_without_provider_calls": True,
        "portal_usage": {"current_month": None, "previous_month": None, "status": "not_collected"},
        "production_export_runs": {"runs_requested": 10, "runs_observed": None, "status": "not_collected"},
        "subscriptions": [
            {
                "name": "Databento US Equities Standard",
                "monthly_cost_usd": 199,
                "renews_on": "2026-08-01",
                "exchange_or_distribution_fees_usd": None,
            },
            {
                "name": "OPRA Standard",
                "monthly_cost_usd": 199,
                "renews_on": "2026-08-01",
                "exchange_or_distribution_fees_usd": None,
            },
        ],
        "classification_counts": dict(sorted(counts.items())),
        "findings": findings,
    }


def _markdown(payload: dict) -> str:
    lines = [
        "# Databento usage baseline",
        "",
        f"Revision: `{payload['revision']}`",
        "",
        "This baseline was generated from Git only. No provider portal, API key,",
        "request header or raw market data was accessed. Missing external usage and",
        "run telemetry are `unknown`, not zero.",
        "",
        "## Subscription cost picture",
        "",
        "| Subscription | Monthly base cost | Extra exchange/distribution fees | Renewal |",
        "|---|---:|---:|---|",
    ]
    for item in payload["subscriptions"]:
        extra = "unknown" if item["exchange_or_distribution_fees_usd"] is None else item["exchange_or_distribution_fees_usd"]
        lines.append(
            f"| {item['name']} | ${item['monthly_cost_usd']} | {extra} | {item['renews_on']} |"
        )
    lines.extend(["", "## Classified repository occurrences", ""])
    for name, count in payload["classification_counts"].items():
        lines.append(f"- `{name}`: {count}")
    lines.extend(
        [
            "",
            "The complete path, line, classification and matched literal inventory is",
            "stored in the companion JSON artifact.",
            "",
            "## External evidence still required",
            "",
            "- Provider portal usage for the current and previous billing month: unknown.",
            "- Ten production-export run durations, rows, cache states and errors: unknown.",
            "- Additional exchange or commercial distribution fees: unknown.",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--revision", default="origin/main")
    parser.add_argument(
        "--json-output",
        type=Path,
        default=Path("artifacts/monitoring/databento_usage_baseline_2026-07-18.json"),
    )
    parser.add_argument(
        "--markdown-output",
        type=Path,
        default=Path("reports/databento_usage_baseline_2026-07-18.md"),
    )
    args = parser.parse_args()
    payload = build_inventory(args.revision)
    args.json_output.parent.mkdir(parents=True, exist_ok=True)
    args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
    args.json_output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    args.markdown_output.write_text(_markdown(payload), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
