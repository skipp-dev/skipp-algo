"""Tests for ``scripts/verify_branch_protection.py``."""
from __future__ import annotations

import importlib
import json
import sys
import types
from pathlib import Path
from unittest.mock import patch

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "verify_branch_protection.py"


@pytest.fixture()
def mod() -> types.ModuleType:
    spec = importlib.util.spec_from_file_location("verify_branch_protection", SCRIPT_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["verify_branch_protection"] = module
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# Unit tests for ProtectionReport
# ---------------------------------------------------------------------------


class TestProtectionReport:
    def test_empty_report_passes(self, mod: types.ModuleType) -> None:
        report = mod.ProtectionReport()
        assert report.passed is True

    def test_all_checks_pass(self, mod: types.ModuleType) -> None:
        report = mod.ProtectionReport()
        report.add("a", True, "ok")
        report.add("b", True, "ok")
        assert report.passed is True

    def test_error_failure_causes_fail(self, mod: types.ModuleType) -> None:
        report = mod.ProtectionReport()
        report.add("a", True, "ok")
        report.add("b", False, "bad", severity="error")
        assert report.passed is False

    def test_warn_failure_does_not_cause_fail(self, mod: types.ModuleType) -> None:
        report = mod.ProtectionReport()
        report.add("a", True, "ok")
        report.add("b", False, "advisory", severity="warn")
        assert report.passed is True


# ---------------------------------------------------------------------------
# Integration-style tests with mocked GitHub API
# ---------------------------------------------------------------------------

_FULL_PROTECTION_RESPONSE = {
    "required_pull_request_reviews": {"required_approving_review_count": 1},
    "required_status_checks": {
        "strict": True,
        "checks": [
            {"context": "smc-fast-pr-gates / fast-gates"},
            {"context": "CI / validate"},
        ],
    },
    "allow_force_pushes": {"enabled": False},
    "allow_deletions": {"enabled": False},
    "enforce_admins": {"enabled": True},
    "required_linear_history": {"enabled": True},
}


class TestCheckBranchProtection:
    def test_full_protection_all_pass(self, mod: types.ModuleType) -> None:
        report = mod.ProtectionReport()
        with patch.object(mod, "_github_get", return_value=(200, _FULL_PROTECTION_RESPONSE)):
            mod._check_branch_protection("fake-token", report)

        errors = [r for r in report.results if r.severity == "error" and not r.passed]
        assert errors == [], [r.name for r in errors]
        assert report.passed is True

    def test_absent_required_reviews_still_passes(self, mod: types.ModuleType) -> None:
        """ADR-0011 (Option C): no required reviews is the EXPECTED baseline.

        The single-committer policy relies on `fast-gates` as the merge gate,
        not approvals; absence of required reviews must not fail the verifier.
        """
        data = json.loads(json.dumps(_FULL_PROTECTION_RESPONSE))
        data["required_pull_request_reviews"] = None
        report = mod.ProtectionReport()
        with patch.object(mod, "_github_get", return_value=(200, data)):
            mod._check_branch_protection("fake-token", report)

        errors = [r for r in report.results if r.severity == "error" and not r.passed]
        assert errors == [], [r.name for r in errors]
        assert report.passed is True
        # The review status is reported informationally (warn), never as error.
        review_results = [r for r in report.results if r.name == "pull_request_reviews"]
        assert review_results and all(r.severity == "warn" for r in review_results)

    def test_api_403_is_warn_not_error(self, mod: types.ModuleType) -> None:
        report = mod.ProtectionReport()
        with patch.object(mod, "_github_get", return_value=(403, {"message": "forbidden"})):
            mod._check_branch_protection("fake-token", report)

        assert report.passed is True
        assert any(r.name == "branch_protection_enabled" and r.severity == "warn" for r in report.results)

    def test_no_protection_fails(self, mod: types.ModuleType) -> None:
        report = mod.ProtectionReport()
        with patch.object(mod, "_github_get", return_value=(404, {})):
            mod._check_branch_protection("fake-token", report)

        assert report.passed is False
        names = [r.name for r in report.results if not r.passed]
        assert "branch_protection_enabled" in names

    def test_missing_required_check_fails(self, mod: types.ModuleType) -> None:
        data = json.loads(json.dumps(_FULL_PROTECTION_RESPONSE))
        data["required_status_checks"]["checks"] = [{"context": "CI / validate"}]
        report = mod.ProtectionReport()
        with patch.object(mod, "_github_get", return_value=(200, data)):
            mod._check_branch_protection("fake-token", report)

        failed = [r for r in report.results if not r.passed and r.severity == "error"]
        assert any("smc-fast-pr-gates" in r.name for r in failed)

    def test_force_push_allowed_fails(self, mod: types.ModuleType) -> None:
        data = json.loads(json.dumps(_FULL_PROTECTION_RESPONSE))
        data["allow_force_pushes"]["enabled"] = True
        report = mod.ProtectionReport()
        with patch.object(mod, "_github_get", return_value=(200, data)):
            mod._check_branch_protection("fake-token", report)

        assert not report.passed
        failed = [r.name for r in report.results if not r.passed]
        assert "force_push_blocked" in failed


class TestCheckRulesets:
    def test_active_rulesets_with_governance_rules(self, mod: types.ModuleType) -> None:
        rulesets_list = [
            {"id": 1, "name": "main-governance", "enforcement": "active"},
        ]
        ruleset_detail = {
            "id": 1,
            "name": "main-governance",
            "enforcement": "active",
            "rules": [
                {"type": "pull_request", "parameters": {"required_approving_review_count": 0}},
                {"type": "required_status_checks", "parameters": {
                    "required_status_checks": [{"context": "fast-gates"}]
                }},
                {"type": "non_fast_forward"},
                {"type": "deletion"},
            ],
        }

        def _mock_get(path: str, token: str) -> tuple[int, Any]:
            if "/rulesets/1" in path:
                return 200, ruleset_detail
            return 200, rulesets_list

        report = mod.ProtectionReport()
        with patch.object(mod, "_github_get", side_effect=_mock_get):
            mod._check_rulesets("fake-token", report)

        names = [r.name for r in report.results]
        assert any("main-governance" in n for n in names)
        assert any(r.name == "ruleset_pr_required" and r.passed for r in report.results)
        assert any(r.name == "ruleset_force_push_blocked" and r.passed for r in report.results)
        assert any("fast-gates" in r.name and r.passed for r in report.results)
        # ADR-0011: review count 0 is the expected baseline -> check passes.
        assert any(r.name == "ruleset_no_required_reviews" and r.passed for r in report.results)

    def test_ruleset_required_reviews_fails(self, mod: types.ModuleType) -> None:
        """ADR-0011: a ruleset requiring approvals must FAIL the verifier."""
        rulesets_list = [
            {"id": 1, "name": "main-governance", "enforcement": "active"},
        ]
        ruleset_detail = {
            "id": 1,
            "name": "main-governance",
            "enforcement": "active",
            "rules": [
                {"type": "pull_request", "parameters": {"required_approving_review_count": 1}},
                {"type": "required_status_checks", "parameters": {
                    "required_status_checks": [{"context": "fast-gates"}]
                }},
            ],
        }

        def _mock_get(path: str, token: str) -> tuple[int, Any]:
            if "/rulesets/1" in path:
                return 200, ruleset_detail
            return 200, rulesets_list

        report = mod.ProtectionReport()
        with patch.object(mod, "_github_get", side_effect=_mock_get):
            mod._check_rulesets("fake-token", report)

        assert not report.passed
        failed = [r.name for r in report.results if not r.passed and r.severity == "error"]
        assert "ruleset_no_required_reviews" in failed

    def test_no_rulesets_warns_only(self, mod: types.ModuleType) -> None:
        report = mod.ProtectionReport()
        with patch.object(mod, "_github_get", return_value=(200, [])):
            mod._check_rulesets("fake-token", report)

        # No rulesets is advisory (classic protection may cover governance).
        assert report.passed is True
        assert any(r.severity == "warn" for r in report.results)


# ---------------------------------------------------------------------------
# Main entrypoint
# ---------------------------------------------------------------------------


class TestMain:
    def test_missing_token_returns_2(self, mod: types.ModuleType) -> None:
        with patch.dict("os.environ", {}, clear=True):
            # Remove GITHUB_TOKEN if present
            os.environ.pop("GITHUB_TOKEN", None)
            result = mod.main()
        assert result == 2

    def test_full_pass_returns_0(self, mod: types.ModuleType) -> None:
        rulesets_list = [{"id": 1, "name": "main-governance", "enforcement": "active"}]
        ruleset_detail = {
            "id": 1, "name": "main-governance", "enforcement": "active",
            "rules": [
                {"type": "pull_request", "parameters": {}},
                {"type": "required_status_checks", "parameters": {
                    "required_status_checks": [{"context": "fast-gates"}]
                }},
                {"type": "non_fast_forward"},
                {"type": "deletion"},
            ],
        }

        def _mock_get(path: str, token: str) -> tuple[int, Any]:
            if "/rulesets/1" in path:
                return 200, ruleset_detail
            if "rulesets" in path:
                return 200, rulesets_list
            return 200, _FULL_PROTECTION_RESPONSE

        with patch.dict("os.environ", {"GITHUB_TOKEN": "fake"}), patch.object(mod, "_github_get", side_effect=_mock_get):
            result = mod.main()
        assert result == 0


import os
from typing import Any
