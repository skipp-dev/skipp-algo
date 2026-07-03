"""Error-path coverage for the Grafana upsert scripts (audit PHASE-1 MED/LOW).

- grafana_alert_rules_upsert.main(): HTTPError / URLError / CalledProcessError
  mid-upsert return exit 1 with a diagnostic; empty-token RuntimeError from the
  keychain fallback also returns 1.
- grafana_dashboard_upsert.main(): success, HTTPError, and URLError (previously
  a URLError escaped as an unhandled traceback).
"""

from __future__ import annotations

import io
import subprocess
import urllib.error
from unittest.mock import MagicMock, patch

import scripts.grafana_alert_rules_upsert as alert_mod
import scripts.grafana_dashboard_upsert as dash_mod


def _http_error(code: int = 500, body: bytes = b"boom") -> urllib.error.HTTPError:
    return urllib.error.HTTPError("https://grafana", code, "err", {}, io.BytesIO(body))


# ── grafana_alert_rules_upsert main() error paths ───────────────────────────

def _patch_valid_groups():
    groups = [{"folder": "F", "name": "g1", "rules": []}]
    return (
        patch.object(alert_mod, "load_alert_groups", return_value=groups),
        patch.object(alert_mod, "validate_alert_groups", return_value=[]),
    )


def test_alert_upsert_httperror_returns_1(capsys) -> None:
    lg, vg = _patch_valid_groups()
    with (
        lg, vg,
        patch.object(alert_mod, "_api_key", return_value="tok"),
        patch.object(alert_mod, "upsert_group", side_effect=_http_error(503)),
    ):
        rc = alert_mod.main([])
    assert rc == 1
    err = capsys.readouterr().err
    assert "503" in err


def test_alert_upsert_urlerror_returns_1(capsys) -> None:
    lg, vg = _patch_valid_groups()
    with (
        lg, vg,
        patch.object(alert_mod, "_api_key", return_value="tok"),
        patch.object(alert_mod, "upsert_group", side_effect=urllib.error.URLError("no route")),
    ):
        rc = alert_mod.main([])
    assert rc == 1
    assert "Alert rules upsert failed" in capsys.readouterr().err


def test_alert_upsert_calledprocesserror_returns_1(capsys) -> None:
    lg, vg = _patch_valid_groups()
    with (
        lg, vg,
        patch.object(alert_mod, "_api_key", return_value="tok"),
        patch.object(
            alert_mod, "upsert_group",
            side_effect=subprocess.CalledProcessError(1, ["security"]),
        ),
    ):
        rc = alert_mod.main([])
    assert rc == 1
    assert "Alert rules upsert failed" in capsys.readouterr().err


def test_alert_upsert_keychain_empty_token_runtimeerror_returns_1(capsys) -> None:
    lg, vg = _patch_valid_groups()
    with (
        lg, vg,
        patch.object(
            alert_mod, "_api_key",
            side_effect=RuntimeError("empty Grafana API key"),
        ),
    ):
        rc = alert_mod.main([])
    assert rc == 1
    assert "empty Grafana API key" in capsys.readouterr().err


# ── grafana_dashboard_upsert main() ─────────────────────────────────────────

def _dashboard_success_ctx():
    resp = MagicMock()
    resp.read.return_value = b'{"url": "/d/smc-live-overlay-v1"}'
    cm = MagicMock()
    cm.__enter__.return_value = resp
    cm.__exit__.return_value = False
    return cm


def test_dashboard_upsert_success(capsys) -> None:
    with (
        patch.object(dash_mod, "_api_key", return_value="tok"),
        patch.object(dash_mod.urllib.request, "urlopen", return_value=_dashboard_success_ctx()),
    ):
        rc = dash_mod.main()
    assert rc == 0
    assert "Dashboard upserted" in capsys.readouterr().out


def test_dashboard_upsert_httperror_returns_1(capsys) -> None:
    with (
        patch.object(dash_mod, "_api_key", return_value="tok"),
        patch.object(dash_mod.urllib.request, "urlopen", side_effect=_http_error(500)),
    ):
        rc = dash_mod.main()
    assert rc == 1
    assert "HTTP 500" in capsys.readouterr().err


def test_dashboard_upsert_urlerror_returns_1_not_traceback(capsys) -> None:
    with (
        patch.object(dash_mod, "_api_key", return_value="tok"),
        patch.object(dash_mod.urllib.request, "urlopen", side_effect=urllib.error.URLError("refused")),
    ):
        rc = dash_mod.main()
    assert rc == 1
    assert "Dashboard upsert failed" in capsys.readouterr().err
