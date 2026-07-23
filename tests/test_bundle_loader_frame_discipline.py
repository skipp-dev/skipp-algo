"""Every ``load_export_bundle`` caller must declare which frames it needs.

Root cause of the 2026-07-23 runner deaths (5x "The runner has received a
shutdown signal", exit 143, private-repo ubuntu-latest = 2 vCPU / 7 GB RAM):
``smc_integration.service._load_symbol_bars_for_context`` loaded the ENTIRE
export bundle to read three frames. After #3941 restored the intraday grain the
full bundle materialises at ~6-8 GB, and a single pytest worker ballooned to
5.95 GB (measured locally: gate tests WITH real bundle peak 6.22 GB, WITHOUT it
0.52 GB — the delivery/export-bundle tests call the service unmocked).

The loader gained ``only_frames`` in #3951 but only the base derivation used
it. This contract makes need-declaration the default for every caller: either
pass ``only_frames=`` near the call, or be on the documented full-bundle
allowlist below.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]

#: Callers allowed to load the full bundle, with why. Tightening each of these
#: is a per-caller follow-up; new callers must NOT be added here casually.
FULL_BUNDLE_ALLOWLIST = {
    # The bundle CLI itself: its purpose is to inspect whole bundles.
    "scripts/load_databento_export_bundle.py",
    # Writes the canonical multi-sheet workbook - legitimately touches most frames.
    "scripts/databento_production_workbook.py",
    # Cron CLIs, not in the refresh path; each should get its own only_frames pass.
    "scripts/databento_preopen_fast.py",
    "scripts/generate_bullish_quality_scanner.py",
    "scripts/generate_databento_watchlist.py",
}

CALL_RE = re.compile(r"load_export_bundle\(")


def _call_sites() -> list[tuple[str, int, str]]:
    sites: list[tuple[str, int, str]] = []
    for base in ("scripts", "smc_integration", "services"):
        root = REPO / base
        if not root.exists():
            continue
        for path in sorted(root.rglob("*.py")):
            text = path.read_text(encoding="utf-8")
            if "def load_export_bundle(" in text and path.name == "load_databento_export_bundle.py":
                continue  # the definition module is covered via the allowlist for its CLI
            for match in CALL_RE.finditer(text):
                line_start = text.rfind("\n", 0, match.start()) + 1
                prefix = text[line_start: match.start()]
                if prefix.count('"') % 2 == 1 or prefix.count("'") % 2 == 1:
                    continue  # occurrence inside a string literal (log/help text)
                # the argument window: from the call to ~12 lines below
                window = text[match.start(): match.start() + 700]
                lineno = text.count("\n", 0, match.start()) + 1
                sites.append((str(path.relative_to(REPO)), lineno, window))
    return sites


def test_every_bundle_load_declares_its_frames() -> None:
    sites = _call_sites()
    assert sites, "no load_export_bundle call sites found - the scan is broken"
    offenders = [
        f"{rel}:{lineno}"
        for rel, lineno, window in sites
        if "only_frames=" not in window and rel not in FULL_BUNDLE_ALLOWLIST
    ]
    assert not offenders, (
        "load_export_bundle called without only_frames= outside the documented "
        f"full-bundle allowlist: {offenders}. Declare the frames the caller "
        "actually reads, or justify a full load in FULL_BUNDLE_ALLOWLIST."
    )


def test_service_context_bars_load_exactly_what_they_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The killer call site: the service reads three frames, so it must request three."""
    import smc_integration.service as service

    captured: dict[str, object] = {}

    def fake_load(*args, **kwargs):
        captured.update(kwargs)
        return {"frames": {}}

    # monkeypatch.setattr instead of manual assign+try/finally: same semantics,
    # but restoration is fixture-managed and holds under xdist same-process runs.
    monkeypatch.setattr(service, "load_export_bundle", fake_load)
    service._load_symbol_bars_for_context("AAPL", "15m")

    assert captured.get("only_frames") == (
        "daily_bars",
        "benchmark_universe_ohlcv_1m",
        "full_universe_second_detail_open",
    ), f"service must request exactly the frames it reads; got {captured.get('only_frames')!r}"
