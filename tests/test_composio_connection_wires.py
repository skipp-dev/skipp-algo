"""Die zwei Draehte gegen einen stillen Verbindungstod — und der Drift-Text.

Aus der Recherche vom 2026-08-30 (Bericht im Artefakt, Notiz
``skipp-composio-failclosed-research``): eine Vorwarnung vor dem Ablauf eines
OAuth-Tokens gibt es bei Composio NICHT. Das Ereignis
``composio.connected_account.expired`` feuert erst NACH dem gescheiterten
Refresh und hat weder Zustell-SLA noch Retry noch Dead-Letter. Ein verlorenes
Ereignis waere unbemerkbar — deshalb braucht es zwei Draehte, und der
Zustands-Poll ist der fail-closed-Boden darunter.

Was hier gepinnt wird:

* Der Poll deckt die vier WRITE-Verbindungen ab, die keine Probe je anfasst.
* Ein nicht auffindbarer Account ist ein Befund, kein Schweigen — das ist der
  Zustand vom 26.8., als ein Dashboard-Reconnect Accounts unter einer
  ``pg-test``-Entity anlegte und die Produktions-Pins ins Leere zeigten.
* Der Status wird per ALLOW-Liste bewertet: alles ausser ``ACTIVE`` ist rot,
  damit ein neuer, hier unbekannter Status nicht still als gesund durchgeht
  (dieselbe Lehre wie beim meta-watchdog, #5199).
* Der Drift-Bericht liefert den AENDERUNGSTEXT und faellt bewusst kein
  Urteil — das besitzt der Contract-Check. Zwei Urteile ueber dieselbe
  Tatsache waeren der Doppelgaenger, gegen den dieses Repo einen Sweep faehrt.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from scripts.composio_connection_poll import ACCESS, TOOLKITS, evaluate, pinned_accounts
from scripts.composio_pin_drift import drift_lines

WORKFLOW_PFAD = (
    Path(__file__).resolve().parents[1] / ".github" / "workflows" / "composio-canary.yml"
)


@pytest.fixture(scope="module")
def workflow() -> dict:
    return yaml.safe_load(WORKFLOW_PFAD.read_text(encoding="utf-8"))


def _konto(status: str = "ACTIVE", **rest: object) -> dict:
    return {"id": "ca_x", "status": status, **rest}


# --- Draht B: der Zustands-Poll ---------------------------------------------

def test_the_poll_covers_the_write_side_no_probe_ever_touches() -> None:
    """Der eigentliche Zugewinn: alle Proben sind read-only.

    ``composio_canary.py`` fuehrt vier Proben, alle mit ``access="read"``.
    Die vier WRITE-Verbindungen — Alert-DMs, Research-Digest, Ops-Digest,
    Incident-Issues — waeren erst im Ernstfall als tot aufgefallen.
    """
    assert "WRITE" in ACCESS and "READ" in ACCESS
    env = {f"COMPOSIO_{t}_{a}_ACCOUNT_ID": f"ca_{t.lower()}_{a.lower()}"
           for t in TOOLKITS for a in ACCESS}
    gepinnt = pinned_accounts(env)
    assert len(gepinnt) == 8, gepinnt
    assert sum(1 for k in gepinnt if k.endswith(".write")) == 4


def test_a_missing_variable_is_not_invented() -> None:
    """Was nicht gepinnt ist, wird nicht behauptet — nur gezaehlt, was da ist."""
    gepinnt = pinned_accounts({"COMPOSIO_SLACK_READ_ACCOUNT_ID": "ca_a"})
    assert gepinnt == {"slack.read": "ca_a"}


def test_an_account_that_vanished_is_a_finding() -> None:
    """Der Zustand vom 26.8.: der Pin zeigte auf eine fremde Entity."""
    befunde, ok = evaluate({"slack.read": "ca_weg"}, {})
    assert not ok
    assert len(befunde) == 1 and "NICHT GEFUNDEN" in befunde[0]


def test_any_status_other_than_active_is_a_finding() -> None:
    """ALLOW-Liste: ein unbekannter Status darf nicht still gesund sein."""
    for status in ("EXPIRED", "FAILED", "INITIATED", "IRGENDWAS_NEUES"):
        befunde, ok = evaluate(
            {"slack.read": "ca_x"},
            {"ca_x": _konto(status, status_reason="refresh failed")},
        )
        assert not ok, status
        assert len(befunde) == 1 and status in befunde[0], status
        assert "refresh failed" in befunde[0], "status_reason fehlt im Befund"


def test_a_disabled_account_is_a_finding_even_when_active() -> None:
    befunde, _ = evaluate({"slack.read": "ca_x"}, {"ca_x": _konto(is_disabled=True)})
    assert len(befunde) == 1 and "is_disabled" in befunde[0]


def test_a_healthy_account_passes() -> None:
    """Positivkontrolle — sonst koennte alles oben aus Dauer-Rot entstehen."""
    befunde, ok = evaluate({"slack.read": "ca_x"}, {"ca_x": _konto()})
    assert not befunde and len(ok) == 1


def test_the_poll_is_judged_by_the_fail_gate(workflow: dict) -> None:
    """Ein Draht, dessen Befund den Job nicht rot macht, ist eine Notiz."""
    schritte = {s.get("id"): s for s in workflow["jobs"]["probe"]["steps"]}
    assert "poll" in schritte, "der Poll-Step ist verschwunden"
    gate = next(
        s for s in workflow["jobs"]["probe"]["steps"]
        if str(s.get("name", "")).startswith("Fail when any check")
    )
    assert "steps.poll.outputs.rc" in gate["if"], (
        "der Poll steht nicht im Fail-Gate — sein Befund waere folgenlos"
    )


# --- Drift-Anreicherung ------------------------------------------------------

_KATALOG = {
    "notion": {
        "name": "notion",
        "versions": [
            {"version": "20260819_00",
             "changelog": "## Changelog for `notion`\n\n### Changed\n- Webhook trigger response schemas now use explicit match operators.\n"},
            {"version": "20260730_00", "changelog": ""},
        ],
    },
    "slack": {"name": "slack", "versions": [{"version": "20260826_00", "changelog": ""}]},
}


def test_the_drift_report_names_what_actually_changed() -> None:
    """Der Beitrag dieses Bausteins: nicht DASS, sondern WAS sich aenderte.

    "Version ist alt" ist keine Aussage, mit der ein Operator entscheiden
    kann. "Webhook trigger response schemas now use explicit match operators"
    ist eine.
    """
    zeilen = drift_lines({"notion": "20260730_00"}, _KATALOG)
    text = "\n".join(zeilen)
    assert "1 Version(en) hinter 20260819_00" in text
    assert "explicit match operators" in text, (
        "der Aenderungstext fehlt — dann ist der Baustein nur eine zweite "
        "Meinung zur Frage, die der Contract-Check schon beantwortet"
    )


def test_a_current_pin_produces_no_warning() -> None:
    zeilen = drift_lines({"slack": "20260826_00"}, _KATALOG)
    assert zeilen == ["  aktuell  slack: 20260826_00"]


def test_a_pin_that_vanished_from_the_catalog_is_flagged() -> None:
    """Eine zurueckgezogene Version ist etwas anderes als eine veraltete."""
    zeilen = drift_lines({"notion": "20250101_00"}, _KATALOG)
    assert any("NICHT im Katalog" in z for z in zeilen), zeilen


def test_an_unknown_toolkit_is_flagged_not_skipped() -> None:
    zeilen = drift_lines({"gibtsnicht": "1"}, _KATALOG)
    assert len(zeilen) == 1 and "nicht im Katalog" in zeilen[0]


def test_the_drift_step_deliberately_carries_no_verdict(workflow: dict) -> None:
    """Kein Doppelgaenger: das Urteil ueber die Pin-Aktualitaet hat EINEN Halter.

    ``composio_contract_check.py`` vergleicht gegen
    ``/api/v3.1/tools?toolkit_versions=latest`` und faellt dort das Urteil.
    Der Drift-Step liest den Changelog-Katalog — eine ZWEITE Quelle. Gaebe er
    ein eigenes Urteil ab, koennten die beiden auseinanderdriften, und man
    glaubte der falschen. Deshalb hat er bewusst kein `id` und steht in
    keinem Gate.
    """
    schritt = next(
        s for s in workflow["jobs"]["probe"]["steps"]
        if "composio_pin_drift" in str(s.get("run", ""))
    )
    assert "id" not in schritt, (
        "der Drift-Step hat ein `id` bekommen — dann landet er ueber die "
        "abgeleitete Population im Fail-Gate und wird zum zweiten Urteil "
        "ueber die Pin-Aktualitaet"
    )
    gate = next(
        s for s in workflow["jobs"]["probe"]["steps"]
        if str(s.get("name", "")).startswith("Fail when any check")
    )
    assert "drift" not in gate["if"], "der Drift-Step darf kein Urteil faellen"
