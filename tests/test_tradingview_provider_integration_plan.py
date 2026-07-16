"""Contract pins for ADR-0028's real TradingView provider plan."""

from pathlib import Path

_PLAN = (
    Path(__file__).resolve().parents[1]
    / "docs"
    / "adr"
    / "0028-tradingview-data-provider-integration.md"
)


def _plan() -> str:
    assert _PLAN.exists(), "ADR-0028 provider plan is missing"
    return _PLAN.read_text(encoding="utf-8")


def test_plan_requires_real_tradingview_and_pine_qualification() -> None:
    text = _plan()
    for required in (
        "TradingView-hosted provider integration",
        "available on tradingview.com",
        "consumable by Pine",
        "no-go",
        "Provider acceptance",
        "conformance",
    ):
        assert required in text


def test_plan_does_not_misrepresent_advanced_charts_as_pine_delivery() -> None:
    text = _plan()
    assert "Advanced Charts Datafeed integration" in text
    assert "does **not** satisfy this decision" in text
    assert "embedded Skipp chart" in text


def test_plan_gates_redistribution_and_end_to_end_evidence() -> None:
    text = _plan()
    for required in (
        "Databento",
        "FMP",
        "redistribution",
        "source observation → adapter → TradingView → chart/Pine",
        "controlled delivery stop",
    ):
        assert required in text
