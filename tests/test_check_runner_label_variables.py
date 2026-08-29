"""Die Sonde, die den WERT der Runner-Variablen prueft -- ausgefuehrt.

Warum es diesen File gibt
=========================

Die Runner-Contract-Tests dieses Repos pinnen den **Ausdruck**
(``"vars.SMC_GH_HOSTED_RUNNER" in runs_on``), nie den **Wert**. Der lebt bei
GitHub. Am 2026-08-29 ueber die volle ``runs-on``-Grundgesamtheit auf ``main``
gemessen: 97 Stellen, davon 80 an ``SMC_GH_HOSTED_RUNNER`` -- inklusive der
beiden einzigen required Kontexte ``fast-gates``/``gate``. Ein Tippfehler dort
haette das Repo lautlos stillgelegt, weil ein unbekanntes Label Jobs nicht rot
macht, sondern verhindert.

Was hier geprueft wird, ist deshalb nicht "das Skript existiert", sondern das
Urteil selbst: ``evaluate`` bekommt gebaute Zustaende und muss sie auseinander
halten. Dazu eine Positivkontrolle gegen die echten Workflows -- eine Ableitung,
die nichts findet, waere ein leeres Ergebnis, kein Befund.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.check_runner_label_variables import (
    derive_runner_variables,
    evaluate,
    fetch_live_values,
    load_allowlist,
    main,
)

_ROOT = Path(__file__).resolve().parent.parent


def _allowlist(**overrides: dict) -> dict:
    base = {
        "SMC_GH_HOSTED_RUNNER": {"allowed": ["ubuntu-latest"], "unset_ok": True},
        "SMC_CI_ARM_RUNNER": {"allowed": ["ubuntu-24.04-arm"], "unset_ok": True},
    }
    base.update(overrides)
    return base


def _derived() -> dict[str, tuple[str, ...]]:
    return {
        "SMC_GH_HOSTED_RUNNER": ("ci.yml", "smc-fast-pr-gates.yml"),
        "SMC_CI_ARM_RUNNER": ("ci.yml",),
    }


# --------------------------------------------------------------------------
# Positivkontrolle: die Ableitung sieht die echte Grundgesamtheit
# --------------------------------------------------------------------------


def test_derivation_finds_the_real_runner_variables() -> None:
    """Ohne diese Kontrolle waere jedes gruene Urteil unten wertlos.

    Eine Ableitung, die nichts findet, laesst `evaluate` mit einer leeren Menge
    laufen -- und eine leere Menge hat nie einen Befund. Genau so sieht ein
    blinder Waechter aus.
    """
    derived = derive_runner_variables()
    assert "SMC_GH_HOSTED_RUNNER" in derived, (
        "die Ableitung findet die Variable nicht mehr, an der die Mehrheit der "
        f"runs-on-Stellen haengt; gefunden: {sorted(derived)}"
    )
    assert "SMC_CI_ARM_RUNNER" in derived
    # Am 2026-08-29 waren es 80 Dateien-Vorkommen fuer die Hosted-Variable. Eine
    # Untergrenze statt der exakten Zahl: das Repo waechst, aber ein Absturz auf
    # eine Handvoll waere ein blind gewordener Scanner.
    assert len(derived["SMC_GH_HOSTED_RUNNER"]) >= 30, (
        f"nur {len(derived['SMC_GH_HOSTED_RUNNER'])} Dateien gefunden — der Scanner "
        "sieht die Grundgesamtheit nicht mehr"
    )


def test_every_derived_variable_has_an_allowlist_entry() -> None:
    """Der eigentliche Anti-Drift-Arm, gegen den ECHTEN Repo-Zustand.

    Eine neue Runner-Variable ist ab ihrer ersten Verwendung abgedeckt; fehlt ihr
    ein Eintrag, faellt das hier auf -- und nicht erst, wenn jemand sie falsch
    setzt.
    """
    findings = evaluate(derive_runner_variables(), load_allowlist(), {})
    missing = [f for f in findings if f.kind == "missing_entry"]
    stale = [f for f in findings if f.kind == "stale_entry"]
    assert not missing, f"Variablen ohne Allowlist-Eintrag: {[f.variable for f in missing]}"
    assert not stale, f"tote Allowlist-Eintraege: {[f.variable for f in stale]}"


# --------------------------------------------------------------------------
# Das Urteil
# --------------------------------------------------------------------------


def test_known_values_produce_no_finding() -> None:
    findings = evaluate(
        _derived(),
        _allowlist(),
        {"SMC_GH_HOSTED_RUNNER": "ubuntu-latest", "SMC_CI_ARM_RUNNER": "ubuntu-24.04-arm"},
    )
    assert findings == [], f"gueltiger Zustand erzeugte Befunde: {findings}"


def test_unset_is_fine_when_declared_optional() -> None:
    assert evaluate(_derived(), _allowlist(), {}) == []


def test_unset_is_a_finding_when_declared_mandatory() -> None:
    allowlist = _allowlist(
        SMC_GH_HOSTED_RUNNER={"allowed": ["ubuntu-latest"], "unset_ok": False}
    )
    findings = evaluate(_derived(), allowlist, {})
    assert [f.kind for f in findings] == ["bad_value"]


@pytest.mark.parametrize(
    "value",
    [
        "ubuntu-latest-arm",  # existiert nicht -- die Falle, die ci.yml benennt
        "ubuntu-24.04-ARM",  # Labels sind nicht case-insensitive
        "ubuntu-24.04",  # gueltiges Label, aber x86 an der arm-Variablen
        "self-hosted",
        " ubuntu-24.04-arm",  # fuehrendes Leerzeichen aus der GitHub-UI
        "",  # von der API als leerer String geliefert
    ],
)
def test_unknown_value_is_found_and_the_message_carries_it(value: str) -> None:
    findings = evaluate(
        _derived(),
        _allowlist(SMC_CI_ARM_RUNNER={"allowed": ["ubuntu-24.04-arm"], "unset_ok": False}),
        {"SMC_CI_ARM_RUNNER": value},
    )
    bad = [f for f in findings if f.variable == "SMC_CI_ARM_RUNNER"]
    assert bad, f"{value!r} wurde durchgelassen"
    text = bad[0].detail + bad[0].as_error_annotation()
    if value:
        assert value in text, f"der Befund nennt den abgelehnten Wert {value!r} nicht: {text}"
    assert "ubuntu-24.04-arm" in text, "der Befund nennt die erlaubte Alternative nicht"
    assert "::error" in bad[0].as_error_annotation()


def test_a_new_runner_variable_without_an_entry_is_a_finding() -> None:
    derived = dict(_derived())
    derived["SMC_NEW_RUNNER"] = ("some-new-workflow.yml",)
    findings = evaluate(derived, _allowlist(), {})
    assert [f.kind for f in findings] == ["missing_entry"]
    assert "some-new-workflow.yml" in findings[0].detail


def test_a_dead_entry_is_a_finding() -> None:
    allowlist = _allowlist(SMC_GONE_RUNNER={"allowed": ["ubuntu-latest"], "unset_ok": True})
    findings = evaluate(_derived(), allowlist, {})
    assert [f.kind for f in findings] == ["stale_entry"]
    assert findings[0].variable == "SMC_GONE_RUNNER"


# --------------------------------------------------------------------------
# Die Sonde als Ganzes: fail-closed statt still gruen
# --------------------------------------------------------------------------


def test_missing_token_is_rc8_not_rc0(monkeypatch: pytest.MonkeyPatch) -> None:
    """Eine Sonde, die nichts messen konnte, hat nichts bewiesen."""
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GH_TOKEN", raising=False)
    assert main(["--repo", "skipp-dev/skipp-algo"]) == 8


def test_api_failure_is_rc8_not_rc0(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "t")

    def boom(repo: str, token: str, fetcher: object = None) -> dict[str, str]:
        raise OSError("TLS handshake failed")

    monkeypatch.setattr(
        "scripts.check_runner_label_variables.fetch_live_values", boom
    )
    assert main(["--repo", "skipp-dev/skipp-algo"]) == 8


def test_bad_live_value_is_rc1_and_the_report_names_it(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Der Bericht geht nach stdout — der Aufrufer teet ihn in die Run-Uebersicht."""
    monkeypatch.setenv("GITHUB_TOKEN", "t")
    monkeypatch.setattr(
        "scripts.check_runner_label_variables.fetch_live_values",
        lambda repo, token, fetcher=None: {"SMC_CI_ARM_RUNNER": "ubuntu-latest-arm"},
    )
    rc = main(["--repo", "skipp-dev/skipp-algo"])
    captured = capsys.readouterr()
    assert rc == 1
    assert "ubuntu-latest-arm" in captured.out, "der Bericht nennt den schlechten Wert nicht"
    assert "SMC_CI_ARM_RUNNER" in captured.out
    assert "::error" in captured.err, "ohne Annotation steht im Run nur ein Exit-Code"


def test_report_discloses_which_token_source_was_used(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Sonst wird aus 'das falsche Token war gesetzt' ein unauffindbares 403."""
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.setenv("GH_TOKEN", "t")
    monkeypatch.setattr(
        "scripts.check_runner_label_variables.fetch_live_values",
        lambda repo, token, fetcher=None: {},
    )
    assert main(["--repo", "skipp-dev/skipp-algo"]) == 0
    assert "GH_TOKEN" in capsys.readouterr().out


def test_healthy_live_state_is_rc0(monkeypatch: pytest.MonkeyPatch) -> None:
    """Positivkontrolle gegen die ECHTE Allowlist und die echten Workflows."""
    allowed = load_allowlist()
    live = {name: entry["allowed"][0] for name, entry in allowed.items()}
    monkeypatch.setenv("GITHUB_TOKEN", "t")
    monkeypatch.setattr(
        "scripts.check_runner_label_variables.fetch_live_values",
        lambda repo, token, fetcher=None: live,
    )
    assert main(["--repo", "skipp-dev/skipp-algo"]) == 0


# --------------------------------------------------------------------------
# Paginierung: eine verlorene Variable liest `evaluate` als "nicht gesetzt"
# --------------------------------------------------------------------------


def test_pagination_does_not_silently_drop_variables() -> None:
    pages = {
        1: {"total_count": 3, "variables": [{"name": "A", "value": "1"}, {"name": "B", "value": "2"}]},
        2: {"total_count": 3, "variables": [{"name": "C", "value": "3"}]},
    }
    seen: list[int] = []

    def fetcher(url: str, headers: dict[str, str]) -> dict:
        page = int(url.rsplit("page=", 1)[1])
        seen.append(page)
        return pages[page]

    values = fetch_live_values("o/r", "t", fetcher=fetcher)
    assert values == {"A": "1", "B": "2", "C": "3"}, (
        "eine Variable ging beim Paginieren verloren — `evaluate` haette sie als "
        "'nicht gesetzt' gelesen, also im Zweifel als in Ordnung"
    )
    assert seen == [1, 2]


def test_unusable_api_shape_raises_rather_than_returning_empty() -> None:
    with pytest.raises(ValueError):
        fetch_live_values("o/r", "t", fetcher=lambda url, headers: {"message": "Not Found"})


def test_broken_allowlist_raises_rather_than_passing(tmp_path: Path) -> None:
    broken = tmp_path / "a.json"
    broken.write_text(json.dumps({"variables": {"X": {"allowed": []}}}), encoding="utf-8")
    with pytest.raises(ValueError):
        load_allowlist(broken)
