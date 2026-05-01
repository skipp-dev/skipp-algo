"""Audit guard: ``scripts/databento_production_export.main`` must call
``logging.basicConfig`` so its ``logger.info(...)`` progress messages reach
the GHA log stream.

History: on 2026-04-30 the workflow ran for 63 minutes with zero log output
before runner eviction. Root cause: ``main`` configured no root logging,
so all ``logger`` calls were dropped by the default ``WARNING``-only handler.

Audit marker: F-V5-A1 / F-CI-O1 (2026-05-01).
"""
from __future__ import annotations

import pathlib


def test_databento_production_export_main_configures_logging() -> None:
    src = (
        pathlib.Path(__file__).resolve().parents[1]
        / "scripts"
        / "databento_production_export.py"
    ).read_text(encoding="utf-8")

    main_marker = "def main("
    assert main_marker in src, "scripts/databento_production_export.py: no def main"
    main_body = src.split(main_marker, 1)[1].split("\ndef ", 1)[0]

    assert "basicConfig" in main_body or "dictConfig" in main_body, (
        "scripts/databento_production_export.py::main lacks logging.basicConfig "
        "(or logging.config.dictConfig). Without root-logger configuration, "
        "logger.info/_progress calls are dropped silently in CI. "
        "Regression of F-V5-A1 / F-CI-O1."
    )
