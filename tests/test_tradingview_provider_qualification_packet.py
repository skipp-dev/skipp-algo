"""Contract pins for the TradingView provider-qualification packet."""

import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_PACKET = _ROOT / "docs" / "tradingview_provider_qualification_packet.md"
_REQUEST = _ROOT / "docs" / "tradingview_provider_qualification_request.md"


def _read(path: Path) -> str:
    assert path.exists(), f"missing qualification artifact: {path}"
    return path.read_text(encoding="utf-8")


def _prose(path: Path) -> str:
    return re.sub(r"\s+", " ", _read(path))


def test_packet_pins_target_and_rejects_lookalike_integrations() -> None:
    text = _read(_PACKET)
    for required in (
        "tradingview.com",
        "read the same series from Pine",
        "not** an Advanced Charts Datafeed API request",
        "not** a broker integration request",
        "unsupported Pine HTTP calls",
    ):
        assert required in text


def test_packet_defines_a_small_semantic_pilot() -> None:
    text = _read(_PACKET)
    for required in (
        "AAPL, MSFT, NVDA",
        "15-minute observations",
        "news_strength",
        "flow_rel_vol",
        "global_heat",
        "candidate non-price series, not synthetic prices",
    ):
        assert required in text


def test_packet_keeps_every_source_right_blocked_until_evidenced() -> None:
    text = _read(_PACKET)
    for source in ("Databento", "Financial Modeling Prep (FMP)", "Benzinga"):
        row = next(line for line in text.splitlines() if line.startswith(f"| {source}"))
        assert "**UNVERIFIED**" in row
        assert "BLOCKED" in row
    assert "No pilot data may be transmitted" in text
    assert "A right to consume source data does not imply a right to redistribute" in text


def test_packet_requires_written_tradingview_and_pine_answers() -> None:
    text = _prose(_PACKET)
    for required in (
        "Questions TradingView must answer in writing",
        "hosted in TradingView's own infrastructure",
        "Can Pine scripts read those series?",
        "documented Pine API",
        "Questions 1 through 3 must all be answered positively",
    ):
        assert required in text


def test_packet_does_not_invent_missing_commercial_identity() -> None:
    text = _prose(_PACKET)
    for required in (
        "applicant's legal entity",
        "expected user count and regions",
        "Those facts are not invented",
        "contacting the team requires a paid plan",
    ):
        assert required in text


def test_routing_request_is_non_confidential_and_precisely_scoped() -> None:
    text = _prose(_REQUEST)
    for required in (
        "official TradingView data/content-provider integration",
        "discoverable on tradingview.com",
        "not an Advanced Charts Datafeed API request",
        "not a broker integration request",
        "read by Pine",
        "Do not add credentials",
    ):
        assert required in text

    raw_text = _read(_REQUEST)
    message = raw_text.split("## Message", 1)[1].split("## Submission rule", 1)[0]
    assert len(message.split()) <= 300
    assert "@tradingview.com" not in message
    assert "Pending" not in message
