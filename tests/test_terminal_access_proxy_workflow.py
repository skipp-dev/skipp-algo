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
    assert "actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd" in raw
    assert "actions/setup-go@924ae3a1cded613372ab5595356fb5720e22ba16" in raw
    assert job["steps"][-2:] == [{"run": "go test ./..."}, {"run": "go build ./..."}]
