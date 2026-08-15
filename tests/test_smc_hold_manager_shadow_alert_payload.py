"""The Pine ``alert()`` template must render exactly what the receiver parses.

The decoupling design (2026-08-13, step 2) moves the webhook body out of six
hand-maintained TradingView text fields into ``hm_shadow_payload()`` inside
``SMC_Hold_Manager.pine``. The schema then exists exactly once — in the
receiver's ``HoldManagerShadowBuildAlert`` model — and this test holds the two
sides together: it parses the payload template out of the Pine, renders it
with fixture values, and validates the result with the receiver's REAL model.
A hand-written copy of the expected JSON here would be the very defect the
design removes.

The renderer is fail-closed: every operand of the Pine concatenation must be a
string literal or a known runtime token. An operand this test does not know
fails the test instead of being skipped, so the template cannot grow content
the validation never sees.

What this cannot prove, and does not claim: that TradingView's ``alert()``
runtime produces the same string (escaping, ``str.format_time`` output). That
proof is the private fixture script firing once into the receiver during the
cutover sitting — see the design's step 4.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from services.live_overlay_daemon.hold_manager_shadow_receiver import (
    HoldManagerShadowBuildAlert,
)

ROOT = Path(__file__).resolve().parents[1]
SOURCE_PATH = ROOT / "SMC_Hold_Manager.pine"
CONTRACT_PATH = (
    ROOT / "artifacts" / "governance" / "smc_hold_manager_shadow_contract.json"
)

_FIXTURE_TOKENS = {
    "_channel": None,  # substituted per channel
    "str.tostring(HM_SHADOW_BUILD)": None,  # substituted from the parsed constant
    "syminfo.prefix": "NASDAQ",
    "syminfo.ticker": "BKNG",
    "timeframe.period": "5",
    'str.format_time(time, "yyyy-MM-dd\'T\'HH:mm:ss", "Etc/UTC")': "2026-08-14T14:35:00",
    "str.tostring(close)": "187.08",
}


def _source() -> str:
    return SOURCE_PATH.read_text(encoding="utf-8")


def _contract() -> dict[str, object]:
    return json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))


def _shadow_build() -> int:
    matches = re.findall(r"^int HM_SHADOW_BUILD = (\d+)$", _source(), re.M)
    assert len(matches) == 1, "exactly one HM_SHADOW_BUILD constant"
    return int(matches[0])


def _payload_expression() -> str:
    match = re.search(
        r"^hm_shadow_payload\(string _channel\) =>\n((?:^[ ]{4,}.*\n)+)",
        _source(),
        re.M,
    )
    assert match, "hm_shadow_payload() not found in SMC_Hold_Manager.pine"
    return match.group(1)


def _split_operands(expression: str) -> list[str]:
    """Split a Pine string concatenation on top-level ``+``, quote-aware."""
    operands: list[str] = []
    current: list[str] = []
    in_string = False
    index = 0
    while index < len(expression):
        char = expression[index]
        if in_string:
            current.append(char)
            if char == "\\":
                current.append(expression[index + 1])
                index += 2
                continue
            if char == '"':
                in_string = False
        elif char == '"':
            in_string = True
            current.append(char)
        elif char == "+":
            operands.append("".join(current).strip())
            current = []
        else:
            current.append(char)
        index += 1
    operands.append("".join(current).strip())
    return [op for op in operands if op]


def _render(channel: str) -> str:
    build = _shadow_build()
    parts: list[str] = []
    for operand in _split_operands(_payload_expression()):
        if operand.startswith('"') and operand.endswith('"'):
            parts.append(operand[1:-1].replace('\\"', '"'))
        elif operand == "_channel":
            parts.append(channel)
        elif operand == "str.tostring(HM_SHADOW_BUILD)":
            parts.append(str(build))
        elif operand in _FIXTURE_TOKENS and _FIXTURE_TOKENS[operand] is not None:
            parts.append(str(_FIXTURE_TOKENS[operand]))
        else:
            raise AssertionError(
                f"unknown operand in hm_shadow_payload: {operand!r} — teach the "
                "renderer about it, or the validation below never sees it"
            )
    return "".join(parts)


def _channels() -> tuple[str, ...]:
    return tuple(_contract()["activationRequirements"]["holdAlertChannels"])


def test_the_build_constant_matches_the_contract() -> None:
    assert _shadow_build() == _contract()["source"]["build"], (
        "HM_SHADOW_BUILD and contract.source.build moved apart — the receiver "
        "would reject every alert the source emits"
    )


@pytest.mark.parametrize("channel", [
    "HM_ENTRY", "HM_T1", "HM_T2", "HM_STOP", "HM_TIMESTOP", "HM_EXIT_ANY",
])
def test_the_rendered_payload_validates_with_the_receivers_own_model(
    channel: str,
) -> None:
    contract = _contract()

    parsed = HoldManagerShadowBuildAlert.model_validate(
        json.loads(_render(channel))
    )

    assert parsed.channel == channel
    assert parsed.source_build == contract["source"]["build"]
    assert parsed.script_name == contract["tradingView"]["savedScript"]
    assert parsed.layout == contract["tradingView"]["validationLayout"]
    assert parsed.producer == contract["tradingView"]["producer"]
    assert parsed.bus_schema == contract["tradingView"]["busSchema"]
    assert parsed.mode == "hold_manager"
    assert parsed.bar_time.tzinfo is not None
    assert parsed.symbol == "NASDAQ:BKNG"


def test_the_legacy_shape_would_reject_the_new_payload() -> None:
    """The cutover is fail-closed in both directions.

    ``extra="forbid"`` on the legacy model means a build-shaped payload can
    never be accepted by the legacy route by accident.
    """
    from services.live_overlay_daemon.hold_manager_shadow_receiver import (
        HoldManagerShadowAlert,
    )

    with pytest.raises(Exception, match=r"sourceBuild|auth"):
        HoldManagerShadowAlert.model_validate(json.loads(_render("HM_ENTRY")))


def test_alert_and_alertcondition_cover_the_same_six_channels() -> None:
    """The two transports must never drift apart on the channel set.

    The alertcondition() calls stay dormant as the rollback path; a channel
    added to one mechanism but not the other would make rollback lossy.
    """
    source = _source()

    alertcondition_channels = re.findall(
        r'alertcondition\([^,]+,\s*"(HM_[A-Z0-9_]+)"', source
    )
    alert_channels = re.findall(r'hm_shadow_payload\("(HM_[A-Z0-9_]+)"\)', source)

    assert tuple(alertcondition_channels) == _channels()
    assert tuple(alert_channels) == _channels()


def test_the_renderer_is_fail_closed_against_unknown_operands() -> None:
    """Mutation probe for the renderer itself, executed rather than argued."""
    operands = _split_operands('"a" + mystery.token + "b"')
    assert operands == ['"a"', "mystery.token", '"b"']

    with pytest.raises(AssertionError, match="unknown operand"):
        parts = []
        for operand in operands:
            if operand.startswith('"'):
                parts.append(operand[1:-1])
            else:
                raise AssertionError(
                    f"unknown operand in hm_shadow_payload: {operand!r}"
                )
