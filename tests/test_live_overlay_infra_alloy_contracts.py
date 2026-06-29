"""Structural contract tests for the Grafana Alloy metrics collector config."""
from __future__ import annotations

import re
from pathlib import Path

import pytest

_ALLOY_PATH = Path(__file__).resolve().parents[1] / "services" / "live_overlay_daemon" / "infra" / "alloy" / "config.alloy"


@pytest.fixture
def alloy_config() -> str:
    assert _ALLOY_PATH.exists(), f"Alloy config missing: {_ALLOY_PATH}"
    return _ALLOY_PATH.read_text(encoding="utf-8")


def _block(text: str, start_marker: str, end_marker: str | None = None) -> str:
    """Extract a balanced-brace block starting at start_marker."""
    start = text.find(start_marker)
    assert start != -1, f"{start_marker!r} not found"
    if end_marker is not None:
        end = text.find(end_marker, start)
        assert end != -1, f"{end_marker!r} not found after {start_marker!r}"
        return text[start : end + len(end_marker)]

    # Find the matching top-level closing brace, accounting for nesting.
    brace_open = text.find("{", start)
    assert brace_open != -1, f"opening brace not found after {start_marker!r}"
    depth = 1
    pos = brace_open + 1
    while pos < len(text) and depth > 0:
        ch = text[pos]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
        pos += 1
    assert depth == 0, f"unbalanced braces after {start_marker!r}"
    return text[start:pos]


def test_alloy_config_requires_expected_env_vars(alloy_config: str) -> None:
    required = {
        "OVERLAY_SECRET_TOKEN",
        "OVERLAY_SERVICE_URL",
        "GRAFANA_CLOUD_PROM_URL",
        "GRAFANA_CLOUD_USER",
        "GRAFANA_CLOUD_API_KEY",
    }
    found = set(re.findall(r'sys\.env\("([^"]+)"\)', alloy_config))
    assert required <= found, f"Missing required env vars: {required - found}"


def test_alloy_scrape_uses_metrics_path_with_basic_auth(alloy_config: str) -> None:
    scrape = _block(alloy_config, 'prometheus.scrape "live_overlay"')
    assert '__metrics_path__ = "/metrics"' in scrape
    assert "basic_auth {" in scrape
    assert 'username = "metrics"' in scrape
    assert 'password = sys.env("OVERLAY_SECRET_TOKEN")' in scrape


def test_alloy_remote_write_uses_grafana_cloud_env(alloy_config: str) -> None:
    rw = _block(alloy_config, 'prometheus.remote_write "grafana_cloud"')
    assert 'url = sys.env("GRAFANA_CLOUD_PROM_URL")' in rw
    assert 'username = sys.env("GRAFANA_CLOUD_USER")' in rw
    assert 'password = sys.env("GRAFANA_CLOUD_API_KEY")' in rw


def test_alloy_scrape_forwards_to_remote_write(alloy_config: str) -> None:
    scrape = _block(alloy_config, 'prometheus.scrape "live_overlay"')
    assert "forward_to = [prometheus.remote_write.grafana_cloud.receiver]" in scrape


def test_dockerfile_uses_pinned_alloy_version() -> None:
    dockerfile = _ALLOY_PATH.with_name("Dockerfile")
    assert dockerfile.exists()
    text = dockerfile.read_text(encoding="utf-8")
    match = re.search(r"^FROM grafana/alloy:(\S+)", text, re.MULTILINE)
    assert match, "Alloy Dockerfile missing pinned FROM tag"
    version = match.group(1)
    assert version.startswith("v") and version[1:].replace(".", "", 2).isdigit(), (
        f"Unexpected Alloy version tag: {version}"
    )


def test_dockerfile_binds_http_server_to_railway_port() -> None:
    dockerfile = _ALLOY_PATH.with_name("Dockerfile")
    text = dockerfile.read_text(encoding="utf-8")

    assert "ENTRYPOINT" in text
    assert "sh" in text and "-c" in text
    assert "exec alloy run" in text
    assert "--server.http.listen-addr=0.0.0.0:${PORT:-12345}" in text
    assert "/etc/alloy/config.alloy" in text
