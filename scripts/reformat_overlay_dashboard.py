#!/usr/bin/env python3
"""Reformat the live-overlay Grafana dashboard JSON with stable indent=2 output.

This is a no-op content change; it exists only to make subsequent UX diffs
reviewable by separating formatting from semantic changes.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

DEFAULT_DASHBOARD_PATH = Path("services/live_overlay_daemon/infra/grafana/dashboard.json")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Reformat Grafana dashboard JSON.")
    parser.add_argument("dashboard_path", nargs="?", type=Path, default=DEFAULT_DASHBOARD_PATH)
    args = parser.parse_args(argv)

    path = args.dashboard_path
    data = json.loads(path.read_text(encoding="utf-8"))
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Reformatted {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
