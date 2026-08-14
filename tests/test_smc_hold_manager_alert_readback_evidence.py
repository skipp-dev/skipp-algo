"""The alert readback evidence must cover every channel and carry no secret.

Until 2026-08-14 the contract's basis for "the six alerts exist" was a sentence
in `smc_hold_manager_shadow_alerts_2026-07-28.json`: *"Operator re-confirmed on
2026-07-29 that six correctly configured alerts exist live; no automated
readback is recorded because TradingView alert state is not machine-verifiable
from this repository."*

The second half of that sentence was never tested. It was tested on 2026-08-14
by running a probe, and it is false: the alert list carries stable `data-name`
anchors and reads cleanly. The dated 2026-07-28 artifact is left exactly as it
is -- dated evidence is not rewritten here -- and the refutation lives in the
new artifact, which this test pins.

The secret check is the load-bearing one. An alert's description field is its
full webhook message body and contains the shadow token, so evidence that
quotes it would put a live credential in the repository.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "artifacts" / "governance" / "smc_hold_manager_shadow_contract.json"
READBACK = (
    ROOT
    / "artifacts"
    / "governance"
    / "smc_hold_manager_shadow_alert_readback_2026-08-14.json"
)

_URL_RE = re.compile(r"https?://")
# Long opaque runs are only forbidden in the page-derived subtree; the probe's
# own prose legitimately contains artifact filenames of that shape.
_OPAQUE_RE = re.compile(r"[A-Za-z0-9_\-]{32,}")


def _contract() -> dict:
    return json.loads(CONTRACT.read_text(encoding="utf-8"))


def _readback() -> dict:
    return json.loads(READBACK.read_text(encoding="utf-8"))


def _strings(value: object, trail: str = "$") -> list[tuple[str, str]]:
    if isinstance(value, str):
        return [(trail, value)]
    if isinstance(value, list):
        out: list[tuple[str, str]] = []
        for index, item in enumerate(value):
            out.extend(_strings(item, f"{trail}[{index}]"))
        return out
    if isinstance(value, dict):
        out = []
        for key, item in value.items():
            out.extend(_strings(item, f"{trail}.{key}"))
        return out
    return []


def test_the_contract_points_at_the_readback() -> None:
    state = _contract()["currentState"]

    assert state["alertsReadbackVerified"] is True
    assert state["alertsReadbackEvidence"] == str(READBACK.relative_to(ROOT))
    # The verbal record stays alongside it rather than being replaced.
    assert state["alertsCreatedEvidence"].endswith("alerts_2026-07-28.json")


def test_every_registered_channel_was_read_back_and_is_running() -> None:
    contract = _contract()
    readback = _readback()
    channels = list(contract["activationRequirements"]["holdAlertChannels"])

    assert readback["expectedChannels"] == channels
    assert readback["missingChannels"] == []
    assert readback["notRunningChannels"] == []
    assert [alert["channel"] for alert in readback["alerts"]] == channels
    assert all(alert["running"] is True for alert in readback["alerts"])


def test_the_readback_names_match_the_alert_templates() -> None:
    """Names are the join key between the probe and the alerts that exist.

    If the templates are ever renamed without the probe learning about it, the
    probe would report six missing channels rather than silently pass -- but
    only if the two agree today, which is what this pins.
    """
    templates = json.loads(
        (
            ROOT
            / "artifacts"
            / "governance"
            / "smc_hold_manager_shadow_alert_templates.json"
        ).read_text(encoding="utf-8")
    )
    template_names = {alert["name"] for alert in templates["alerts"]}
    readback_names = {alert["name"] for alert in _readback()["alerts"]}

    assert readback_names == template_names


def test_the_evidence_carries_no_url_anywhere() -> None:
    offenders = [t for t, s in _strings(_readback()) if _URL_RE.search(s)]

    assert not offenders, f"readback evidence contains a URL at {offenders}"


def test_the_page_derived_subtree_carries_no_opaque_token() -> None:
    readback = _readback()
    subtree = {"alerts": readback["alerts"], "tradingView": readback["tradingView"]}

    offenders = [t for t, s in _strings(subtree) if _OPAQUE_RE.search(s)]

    assert not offenders, f"page-derived evidence contains an opaque run at {offenders}"


def test_the_evidence_states_what_it_does_not_prove() -> None:
    """A readback that omitted its limits would be read as proving delivery."""
    limitations = " ".join(_readback()["limitations"]).lower()

    assert "webhook action is enabled" in limitations
    assert "never read" in limitations
    assert "delivery" in limitations


def test_the_refuted_claim_is_recorded_verbatim() -> None:
    superseded = _readback()["supersedes"]

    assert superseded["artifact"].endswith("alerts_2026-07-28.json")
    assert "not machine-verifiable" in superseded["claim"]
    assert superseded["outcome"].startswith("refuted by execution")
