"""Library-context bridge (SC-LIB-001, issue #3872 aftermath).

#3790 declared universe/trust "runtime-sidecar data" while nothing served
them. These tests pin the bridge that closes the gap: generator-controlled
``export const`` parsing, honest None semantics for static libraries, and
the additive ``smc_live`` field contract the sidecar validates.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from services.live_overlay_daemon import library_context_bridge as bridge

# Diese Fixture bildet die Form nach, die der GENERATOR wirklich erzeugt:
# die Teile als ``const string`` OHNE ``export``, daneben ein exportiertes
# ``UNIVERSE_TICKERS`` als KONKATENATION (kein String-Literal).
#
# Bis 2026-09-01 stand hier ``export const string UNIVERSE_TICKERS_PART_1 =
# "AAPL,MSFT"`` — eine Form, die `smc-library-refresh.yml` nie schreibt. Der
# Parser war damit gegen sich selbst bewiesen statt gegen seinen Produzenten,
# und ``universe_member``/``universe_size`` lieferten in Produktion seit Geburt
# fuer JEDES Symbol ``None``. `test_parses_the_real_generated_library` haelt
# das jetzt zusaetzlich an der echten Datei fest.
ENRICHED_PINE = """\
//@version=6
library("smc_micro_profiles_generated", overlay = false)
export const string ASOF_DATE = "2026-07-22"
export const string ASOF_TIME = "2026-07-22T16:40:00Z"
export const int UNIVERSE_SIZE = 4
export const int PROVIDER_COUNT = 3
export const string STALE_PROVIDERS = ""
const string UNIVERSE_TICKERS_PART_1 = "AAPL,MSFT"
const string UNIVERSE_TICKERS_PART_2 = "NVDA,ONDS"
export const string UNIVERSE_TICKERS = UNIVERSE_TICKERS_PART_1 + "," + UNIVERSE_TICKERS_PART_2
"""

# Die alte, exportierte Schreibweise muss weiter geparst werden — der Generator
# koennte sie zurueckbringen, und ein Parser, der nur die neue Form kennt,
# waere derselbe Fehler mit umgekehrtem Vorzeichen.
ENRICHED_PINE_EXPORTED_PARTS = ENRICHED_PINE.replace(
    "const string UNIVERSE_TICKERS_PART_", "export const string UNIVERSE_TICKERS_PART_"
)

STATIC_PINE = """\
//@version=6
library("smc_micro_profiles_generated", overlay = false)
export const string ASOF_DATE = "2026-07-21"
export const string ASOF_TIME = ""
export const int UNIVERSE_SIZE = 6929
export const string UNIVERSE_TICKERS = ""
"""


@pytest.fixture(autouse=True)
def _reset_cache(monkeypatch: pytest.MonkeyPatch):
    bridge._cache.update({"data": None, "mtime_ns": None, "path": None, "fetched_at": None})
    # An explicitly EMPTY url disables the remote source (config._snapshot_url).
    # Without this every test in this file would reach out to api.github.com,
    # because the default URL is derived, not absent — the same convention the
    # evidence-freshness / sweep-trap / reaction-zone bridge tests follow.
    monkeypatch.setenv("LIBRARY_CONTEXT_PINE_URL", "")
    yield


def _point_at(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, text: str) -> None:
    pine = tmp_path / "lib.pine"
    pine.write_text(text, encoding="utf-8")
    monkeypatch.setenv("LIBRARY_CONTEXT_PINE_PATH", str(pine))


def test_enriched_library_yields_membership_and_trust(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _point_at(monkeypatch, tmp_path, ENRICHED_PINE)
    ctx = bridge.context_for_symbol("NASDAQ:ONDS")
    assert ctx == {
        "universe_member": True,
        "universe_size": 4,
        "library_asof_date": "2026-07-22",
        "library_asof_time": "2026-07-22T16:40:00Z",
        "provider_trust_status": "ok",
        "provider_stale_list": None,
    }
    assert bridge.context_for_symbol("TSLA")["universe_member"] is False


def test_static_library_yields_unknown_not_false(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An empty universe means "not scanned at all" — membership must be
    None (unknown), never False ("scanned and absent"), and the misleading
    UNIVERSE_SIZE of a static library must not leak."""
    _point_at(monkeypatch, tmp_path, STATIC_PINE)
    ctx = bridge.context_for_symbol("AAPL")
    assert ctx["universe_member"] is None
    assert ctx["universe_size"] is None
    assert ctx["library_asof_date"] == "2026-07-21"
    assert ctx["library_asof_time"] is None
    assert ctx["provider_trust_status"] is None
    assert ctx["provider_stale_list"] is None


def test_degraded_and_unavailable_provider_status(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    degraded = ENRICHED_PINE.replace(
        'export const string STALE_PROVIDERS = ""',
        'export const string STALE_PROVIDERS = "benzinga,newsapi"',
    )
    _point_at(monkeypatch, tmp_path, degraded)
    ctx = bridge.context_for_symbol("AAPL")
    assert ctx["provider_trust_status"] == "degraded"
    assert ctx["provider_stale_list"] == "benzinga,newsapi"

    dead = ENRICHED_PINE.replace(
        "export const int PROVIDER_COUNT = 3", "export const int PROVIDER_COUNT = 0"
    )
    _point_at(monkeypatch, tmp_path, dead)
    bridge._cache.update({"data": None, "mtime_ns": None, "path": None})
    assert bridge.context_for_symbol("AAPL")["provider_trust_status"] == "unavailable"


def test_missing_file_fails_soft(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LIBRARY_CONTEXT_PINE_PATH", str(tmp_path / "absent.pine"))
    ctx = bridge.context_for_symbol("AAPL")
    assert all(value is None for value in ctx.values())


def test_cache_refreshes_on_mtime_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pine = tmp_path / "lib.pine"
    pine.write_text(ENRICHED_PINE, encoding="utf-8")
    monkeypatch.setenv("LIBRARY_CONTEXT_PINE_PATH", str(pine))
    assert bridge.context_for_symbol("ONDS")["universe_member"] is True
    updated = ENRICHED_PINE.replace('"NVDA,ONDS"', '"NVDA"')
    pine.write_text(updated, encoding="utf-8")
    import os

    os.utime(pine, ns=(pine.stat().st_atime_ns, pine.stat().st_mtime_ns + 1_000_000))
    assert bridge.context_for_symbol("ONDS")["universe_member"] is False


# ---------------------------------------------------------------------------
# Runtime source (2026-09-01). Until then this bridge read ONLY the copy baked
# into the container image, justified by "the daemon redeploys on every main
# push". Measured over 2026-07-22..08-31: 90 git-bound deployments against 511
# main commits, one silence of 238 h during which the daemon decided
# ``universe_member`` against a nine-day-old ticker list. These tests pin the
# runtime source and — just as important — the fallbacks that must NOT quietly
# serve an empty context.

REFRESHED_PINE = ENRICHED_PINE.replace('"NVDA,ONDS"', '"NVDA,TSLA"')


def test_parses_the_real_generated_library(monkeypatch: pytest.MonkeyPatch) -> None:
    """Gegen den PRODUZENTEN, nicht gegen eine erfundene Form.

    Der Parser lief bis 2026-09-01 gegen eine Fixture, die der Generator nie
    erzeugt (``export`` vor den Teilen), und lieferte darum in Produktion fuer
    JEDES Symbol ``universe_member=None`` / ``universe_size=None`` — nachweisbar
    an AAPL, NVDA und einem Phantasie-Ticker gleichermassen. Nur ein Test, der
    die echte Datei liest, faengt das: sie ist die einzige Autoritaet darueber,
    was der Generator schreibt.
    """
    real = Path(__file__).resolve().parents[1] / "pine/generated/smc_micro_profiles_generated.pine"
    # Kein `pytest.skip`: die Datei ist versioniert und der Daemon backt sie ins
    # Image. Waere sie weg, ist das ein Befund und kein Grund zu schweigen — ein
    # uebersprungener Test sieht von aussen aus wie ein bestandener.
    assert real.exists(), f"generierte Bibliothek fehlt: {real}"
    monkeypatch.setenv("LIBRARY_CONTEXT_PINE_PATH", str(real))
    data = bridge._load()

    assert data["universe"], (
        "Universum leer — der Parser trifft die Deklarationsform des Generators "
        "nicht. Genau dieser Zustand sah wie eine statische Bibliothek aus und "
        "blieb dadurch unentdeckt."
    )
    assert data["universe_size"] == len(data["universe"]), (
        f"UNIVERSE_SIZE={data['universe_size']} passt nicht zu "
        f"{len(data['universe'])} geparsten Tickern — Teil-Zeilen verloren"
    )
    assert data["library_asof_time"], "ASOF_TIME nicht geparst"
    # Ein Symbol, das im US-Universum praktisch immer enthalten ist, und eines,
    # das es nicht geben kann: beide Richtungen, nicht nur die bejahende.
    assert bridge.context_for_symbol("AAPL")["universe_member"] is True
    assert bridge.context_for_symbol("ZZZZ_KEIN_TICKER")["universe_member"] is False


def test_exported_ticker_parts_still_parse(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Die alte Schreibweise darf nicht rausfallen, wenn der Generator sie wiederbringt."""
    _point_at(monkeypatch, tmp_path, ENRICHED_PINE_EXPORTED_PARTS)
    assert bridge.context_for_symbol("ONDS")["universe_member"] is True
    assert bridge.context_for_symbol("ZZZZ")["universe_member"] is False


def _serve(monkeypatch: pytest.MonkeyPatch, body: str | None) -> list[str]:
    """Point the bridge at a fake remote; returns the list of URLs fetched."""
    seen: list[str] = []

    def _fake(url: str, token: str, timeout: float = 10.0) -> str | None:
        seen.append(url)
        return body

    monkeypatch.setenv("LIBRARY_CONTEXT_PINE_URL", "https://example.invalid/lib.pine")
    monkeypatch.setattr(bridge, "_fetch_url", _fake)
    return seen


def test_runtime_source_wins_over_the_baked_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """THE regression: a library refresh must land without a redeploy."""
    _point_at(monkeypatch, tmp_path, ENRICHED_PINE)  # the stale image copy
    _serve(monkeypatch, REFRESHED_PINE)  # what main actually holds now
    ctx = bridge.context_for_symbol("TSLA")
    assert ctx["universe_member"] is True, "fetched library ignored — image copy served"
    assert bridge.context_for_symbol("ONDS")["universe_member"] is False


def test_fetch_failure_falls_back_to_the_baked_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _point_at(monkeypatch, tmp_path, ENRICHED_PINE)
    _serve(monkeypatch, None)
    assert bridge.context_for_symbol("ONDS")["universe_member"] is True


def test_github_base64_envelope_is_decoded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import base64
    import json

    _point_at(monkeypatch, tmp_path, ENRICHED_PINE)
    envelope = json.dumps(
        {
            "encoding": "base64",
            "content": base64.b64encode(REFRESHED_PINE.encode("utf-8")).decode("ascii"),
        }
    )
    _serve(monkeypatch, envelope)
    assert bridge.context_for_symbol("TSLA")["universe_member"] is True


@pytest.mark.parametrize(
    "body",
    [
        '{"message":"Not Found"}',  # GitHub error JSON
        "<html><body>502 Bad Gateway</body></html>",  # proxy error page
        "",  # truncated / empty response
    ],
)
def test_unusable_body_falls_back_instead_of_serving_empty(
    body: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A body that parses to nothing must NOT look like a static library.

    An empty context renders as "—" and is indistinguishable from an honest
    static generation — it would read as "scanned, nothing to report" while the
    truth is "the fetch failed". Fail over to the baked copy instead.
    """
    _point_at(monkeypatch, tmp_path, ENRICHED_PINE)
    _serve(monkeypatch, body)
    assert bridge.context_for_symbol("ONDS")["universe_member"] is True


def test_fetched_library_expires_on_the_ttl(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Without expiry the fetch would happen once per process — i.e. per deploy.

    That is the very failure this change removes, so the clock is pinned here
    rather than assumed.
    """
    _point_at(monkeypatch, tmp_path, ENRICHED_PINE)
    seen = _serve(monkeypatch, ENRICHED_PINE)
    clock = {"now": 1000.0}
    monkeypatch.setattr(bridge.time, "monotonic", lambda: clock["now"])

    bridge.context_for_symbol("AAPL")
    bridge.context_for_symbol("AAPL")
    assert len(seen) == 1, "cache did not hold within the TTL"

    ttl = bridge.config.library_context_cache_ttl_secs()
    clock["now"] += ttl + 1
    bridge.context_for_symbol("AAPL")
    assert len(seen) == 2, "cache never expired — a refresh would need a redeploy"
