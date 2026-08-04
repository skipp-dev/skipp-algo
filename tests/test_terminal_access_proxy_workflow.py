"""Pin the terminal-access-proxy workflow to the candidate export surface."""

from pathlib import Path

import yaml

WORKFLOW = Path(__file__).resolve().parents[1] / ".github/workflows/terminal-access-proxy.yml"


def test_terminal_access_proxy_workflow_is_bounded_and_pinned() -> None:
    raw = WORKFLOW.read_text(encoding="utf-8")
    workflow = yaml.safe_load(raw)
    job = workflow["jobs"]["test"]

    assert workflow["permissions"] == {"contents": "read"}
    assert job["runs-on"] == "${{ vars.SMC_GH_HOSTED_RUNNER || 'ubuntu-latest' }}"
    assert job["defaults"]["run"]["working-directory"] == "services/terminal_access_proxy"
    assert "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1" in raw
    assert "actions/setup-go@b7ad1dad31e06c5925ef5d2fc7ad053ef454303e" in raw
    assert job["steps"][-2:] == [{"run": "go test ./..."}, {"run": "go build ./..."}]
