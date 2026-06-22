#!/usr/bin/env python3
"""Reformat the live-overlay Grafana dashboard JSON with stable indent=2 output.

This is a no-op content change; it exists only to make subsequent UX diffs
reviewable by separating formatting from semantic changes.
"""
from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path

DEFAULT_DASHBOARD_PATH = Path("services/live_overlay_daemon/infra/grafana/dashboard.json")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Reformat Grafana dashboard JSON.")
    parser.add_argument("dashboard_path", nargs="?", type=Path, default=DEFAULT_DASHBOARD_PATH)
    args = parser.parse_args(argv)

    path = args.dashboard_path
    data = json.loads(path.read_text(encoding="utf-8"))
    payload = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        prefix=f"{path.name}.",
        suffix=".tmp",
        dir=str(path.parent),
        text=True,
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            handle.write(payload)
        os.replace(tmp_path, path)
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
    print(f"Reformatted {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
