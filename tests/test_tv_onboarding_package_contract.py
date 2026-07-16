"""Contract coverage for the end-user TradingView onboarding packages."""

from __future__ import annotations

import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "tv-onboarding-packages.yml"
CONFIG = ROOT / "automation" / "tradingview" / "config" / "consumer-onboarding.json"
ONBOARDING = ROOT / "scripts" / "tv_onboard_consumers.ts"
PACKAGER = ROOT / "scripts" / "build_tv_onboarding_package.mjs"
DOCS = ROOT / "docs" / "tradingview-onboarding"


def test_config_covers_the_seven_supported_consumers() -> None:
    payload = json.loads(CONFIG.read_text(encoding="utf-8"))
    assert payload["producer"]["scriptName"] == "SMC Long-Dip Suite"
    assert {item["displayName"] for item in payload["consumers"]} == {
        "SMC Decision Board",
        "SMC Long-Dip Strategy",
        "SMC Long-Dip Alerts",
        "SMC Setup Check",
        "SMC Breakout Overlay",
        "SMC Confluence Hub",
        "SMC Long-Dip Mobile",
    }


def test_onboarding_is_partial_for_missing_consumers_and_continues_binding() -> None:
    body = ONBOARDING.read_text(encoding="utf-8")
    assert 'status: "missing"' in body
    assert 'status: "bound"' in body
    assert 'status: "failed"' in body
    assert 'missingConsumers.length > 0\n      ? "partial"' in body
    assert "Other consumers will still be processed." in body
    assert "run SMC Onboarding again" in body


def test_suite_preflight_happens_before_binding_mutation() -> None:
    body = ONBOARDING.read_text(encoding="utf-8")
    source_check = body.index("adapter.isSourceOptionAvailable")
    bind_loop = body.index("adapter.bindConsumer")
    assert source_check < bind_loop
    assert "ONB-SUITE-001" in body
    assert "ONB-SUITE-002" in body
    assert "No consumer bindings were changed." in body


def test_all_user_facing_error_codes_are_documented() -> None:
    body = ONBOARDING.read_text(encoding="utf-8")
    troubleshooting = (DOCS / "TROUBLESHOOTING.md").read_text(encoding="utf-8")
    codes = {
        "ONB-OS-001",
        "ONB-BROWSER-001",
        "ONB-BROWSER-002",
        "ONB-CHART-001",
        "ONB-AUTH-001",
        "ONB-SUITE-001",
        "ONB-SUITE-002",
        "ONB-CONSUMER-000",
        "ONB-BINDING-001",
        "ONB-CONFIG-001",
        "ONB-UNEXPECTED-001",
    }
    for code in codes:
        assert code in body
        assert code in troubleshooting


def test_end_user_documentation_is_complete_and_english() -> None:
    expected = {
        "README.md",
        "WINDOWS.md",
        "MACOS.md",
        "PREPARE_CHART.md",
        "PRIVACY.md",
        "TROUBLESHOOTING.md",
    }
    assert {path.name for path in DOCS.glob("*.md")} == expected
    combined = "\n".join((DOCS / name).read_text(encoding="utf-8") for name in sorted(expected))
    assert "npm is not required" in combined
    assert "run onboarding again" in combined.lower()
    assert "dedicated browser profile" in combined.lower()
    assert "does not upload" in combined.lower()


def test_packager_embeds_node_playwright_launchers_docs_and_integrity_manifest() -> None:
    body = PACKAGER.read_text(encoding="utf-8")
    assert "fs.copyFileSync(process.execPath" in body
    assert 'copyPackage("playwright"' in body
    assert 'copyPackage("playwright-core"' in body
    assert "Start SMC Onboarding.cmd" in body
    assert "Start SMC Onboarding.command" in body
    assert "requiresNpm: false" in body
    assert "sha256" in body
    assert "NODE-LICENSE" in body
    assert "PLAYWRIGHT-LICENSE" in body


def test_workflow_builds_and_smoke_tests_all_supported_packages() -> None:
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    triggers = workflow.get("on", workflow.get(True))
    assert triggers["push"]["branches"] == ["main"]
    assert "pull_request" in triggers
    assert "workflow_dispatch" in triggers
    job = workflow["jobs"]["package"]
    matrix = job["strategy"]["matrix"]["include"]
    assert {(item["platform"], item["arch"]) for item in matrix} == {
        ("windows", "x64"),
        ("macos", "arm64"),
        ("macos", "x64"),
    }
    assert {item["runner"] for item in matrix} == {
        "windows-latest",
        "macos-latest",
        "macos-15-intel",
    }
    steps = job["steps"]
    assert any("--self-test" in step.get("run", "") for step in steps)
    assert any("--browser-smoke" in step.get("run", "") for step in steps)
    assert any("tv:onboarding:package" in step.get("run", "") for step in steps)
    assert job["timeout-minutes"] == 20


def test_package_scripts_are_exposed_for_developers_but_not_required_by_users() -> None:
    package = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
    assert package["scripts"]["tv:onboard"] == "tsx scripts/tv_onboard_consumers.ts"
    assert package["scripts"]["tv:onboarding:package"] == "node scripts/build_tv_onboarding_package.mjs"
    assert package["devDependencies"]["esbuild"].startswith("~0.28.")
