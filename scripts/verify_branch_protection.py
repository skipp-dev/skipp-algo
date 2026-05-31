"""Verify GitHub branch-protection settings for ``main``.

Checks the ``main`` branch ruleset against the governance requirements
documented in ``docs/smc_branch_protection_and_release_gates.md``.

Usage
-----
Requires a ``GITHUB_TOKEN`` environment variable with ``repo`` scope
(or fine-grained ``administration:read`` + ``metadata:read`` permissions).

    python scripts/verify_branch_protection.py

Exit codes
----------
0  All checks pass.
1  One or more checks failed.
2  Network / auth / API error.
"""
from __future__ import annotations

import contextlib
import json
import os
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

OWNER = "skippALGO"
REPO = "skipp-algo"
BRANCH = "main"

# Required status checks — the minimum blocking baseline.
REQUIRED_STATUS_CHECKS: list[str] = [
    "smc-fast-pr-gates / fast-gates",
]

# Optional additional status checks — recommended but not hard-required.
RECOMMENDED_STATUS_CHECKS: list[str] = [
    "CI / validate",
]

API_BASE = "https://api.github.com"


# ---------------------------------------------------------------------------
# Result model
# ---------------------------------------------------------------------------


@dataclass
class CheckResult:
    name: str
    passed: bool
    detail: str
    severity: str = "error"  # "error" or "warn"


@dataclass
class ProtectionReport:
    results: list[CheckResult] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(r.passed for r in self.results if r.severity == "error")

    def add(self, name: str, passed: bool, detail: str, *, severity: str = "error") -> None:
        self.results.append(CheckResult(name=name, passed=passed, detail=detail, severity=severity))

    def print_summary(self) -> None:
        max_name = max((len(r.name) for r in self.results), default=20)
        for r in self.results:
            icon = "\u2705" if r.passed else ("\u26A0\uFE0F " if r.severity == "warn" else "\u274C")
            print(f"  {icon} {r.name:<{max_name}}  {r.detail}")
        print()
        if self.passed:
            print("Result: PASS — branch protection meets governance requirements.")
        else:
            print("Result: FAIL — one or more governance checks did not pass.")


# ---------------------------------------------------------------------------
# GitHub API helpers
# ---------------------------------------------------------------------------


def _github_get(path: str, token: str) -> tuple[int, Any]:
    """Perform an authenticated GET against the GitHub REST API."""
    url = f"{API_BASE}{path}"
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = json.loads(resp.read())
            return resp.status, body
    except urllib.error.HTTPError as exc:
        body = {}
        with contextlib.suppress(Exception):
            body = json.loads(exc.read())
        return exc.code, body


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------


def _check_branch_protection(token: str, report: ProtectionReport) -> None:
    """Check classic branch-protection rules for *main*.

    Note: when the token lacks ``administration:read`` scope, this check
    returns a 403.  That is acceptable when rulesets provide the same
    governance — downstream ``_check_rulesets`` will verify that.
    """
    status, data = _github_get(
        f"/repos/{OWNER}/{REPO}/branches/{BRANCH}/protection",
        token,
    )

    if status == 403:
        # Token lacks admin scope — skip classic check (rulesets will cover it).
        report.add(
            "branch_protection_enabled",
            True,
            "Classic protection API inaccessible (403) — relying on rulesets.",
            severity="warn",
        )
        return

    if status == 404:
        report.add(
            "branch_protection_enabled",
            False,
            "No branch protection rule found for 'main'.",
        )
        return

    if status != 200:
        msg = data.get("message", f"HTTP {status}")
        report.add("branch_protection_enabled", False, f"API error: {msg}")
        return

    report.add("branch_protection_enabled", True, "Branch protection rule exists.")

    # --- PR review requirement (ADR-0011) ---
    # ADR-0011 (Option C) intentionally drops required reviews on `main`: the
    # repo is single-committer and the real merge gate is the `fast-gates`
    # required status check, not an approval. Absence of required reviews is
    # therefore the EXPECTED baseline, not a failure — reported informationally
    # here. The hard gate is the required status-check assertion below.
    pr_reviews = data.get("required_pull_request_reviews")
    report.add(
        "pull_request_reviews",
        True,
        (
            "Required reviews enabled (stricter than the ADR-0011 baseline)."
            if pr_reviews is not None
            else "No required reviews — matches ADR-0011 (Option C) single-committer baseline."
        ),
        severity="warn",
    )

    # --- Required status checks ---
    status_checks = data.get("required_status_checks")
    if status_checks is None:
        report.add(
            "required_status_checks",
            False,
            "Required status checks are NOT enabled.",
        )
    else:
        report.add("required_status_checks", True, "Required status checks enabled.")

        contexts: list[str] = []
        checks_list = status_checks.get("checks", [])
        contexts = [c.get("context", "") for c in checks_list] if checks_list else status_checks.get("contexts", [])

        for req_check in REQUIRED_STATUS_CHECKS:
            found = req_check in contexts
            report.add(
                f"required_check::{req_check}",
                found,
                f"'{req_check}' is required." if found else f"'{req_check}' is NOT in required checks.",
            )

        for rec_check in RECOMMENDED_STATUS_CHECKS:
            found = rec_check in contexts
            report.add(
                f"recommended_check::{rec_check}",
                found,
                f"'{rec_check}' is required." if found else f"'{rec_check}' is NOT in required checks (recommended).",
                severity="warn",
            )

    # --- Force-push protection ---
    allow_force = data.get("allow_force_pushes", {})
    force_enabled = allow_force.get("enabled", True) if isinstance(allow_force, dict) else True
    report.add(
        "force_push_blocked",
        not force_enabled,
        "Force pushes are blocked." if not force_enabled else "Force pushes are ALLOWED.",
    )

    # --- Deletion protection ---
    allow_del = data.get("allow_deletions", {})
    del_enabled = allow_del.get("enabled", True) if isinstance(allow_del, dict) else True
    report.add(
        "deletion_blocked",
        not del_enabled,
        "Branch deletion is blocked." if not del_enabled else "Branch deletion is ALLOWED.",
    )

    # --- Enforce admins ---
    enforce = data.get("enforce_admins", {})
    enforce_enabled = enforce.get("enabled", False) if isinstance(enforce, dict) else False
    report.add(
        "enforce_admins",
        enforce_enabled,
        "Rules enforced for admins." if enforce_enabled else "Admin bypass is ALLOWED.",
        severity="warn",
    )

    # --- Linear history ---
    linear = data.get("required_linear_history", {})
    linear_enabled = linear.get("enabled", False) if isinstance(linear, dict) else False
    report.add(
        "linear_history",
        linear_enabled,
        "Linear history required." if linear_enabled else "Linear history is NOT required.",
        severity="warn",
    )


def _check_rulesets(token: str, report: ProtectionReport) -> None:
    """Check repository rulesets that target *main* (newer GitHub rulesets API)."""
    status, data = _github_get(
        f"/repos/{OWNER}/{REPO}/rulesets",
        token,
    )
    if status == 404:
        report.add("rulesets_available", True, "No rulesets configured (classic protection only).", severity="warn")
        return
    if status != 200:
        report.add("rulesets_available", False, f"Rulesets API error (HTTP {status}).", severity="warn")
        return

    if not data:
        report.add("rulesets_available", True, "No rulesets configured.", severity="warn")
        return

    # Summarise rulesets that are active
    active = [r for r in data if r.get("enforcement") == "active"]
    report.add(
        "active_rulesets",
        len(active) > 0,
        f"{len(active)} active ruleset(s) found." if active else "No active rulesets.",
    )
    for rs in active:
        name = rs.get("name", "unnamed")
        rs_id = rs.get("id", "?")
        report.add(
            f"ruleset::{name}",
            True,
            f"Ruleset '{name}' (id={rs_id}) is active.",
        )

    # Deep-inspect each active ruleset for governance rules.
    has_pr_rule = False
    has_required_checks = False
    has_non_ff = False
    has_deletion = False
    found_check_contexts: list[str] = []
    # Highest required-review count seen across any active ruleset PR rule.
    # ADR-0011 (Option C) mandates this stays 0 on `main`: a non-zero count is
    # never legitimately satisfiable for a single-committer repo and only
    # trains the admin-bypass reflex (see ADR-0011 rationale).
    max_ruleset_review_count = 0

    for rs in active:
        rs_id = rs.get("id")
        if not rs_id:
            continue
        detail_status, detail = _github_get(
            f"/repos/{OWNER}/{REPO}/rulesets/{rs_id}",
            token,
        )
        if detail_status != 200:
            continue
        for rule in detail.get("rules", []):
            rtype = rule.get("type", "")
            if rtype == "pull_request":
                has_pr_rule = True
                review_count = rule.get("parameters", {}).get(
                    "required_approving_review_count", 0
                )
                if isinstance(review_count, int):
                    max_ruleset_review_count = max(max_ruleset_review_count, review_count)
            elif rtype == "required_status_checks":
                has_required_checks = True
                for chk in rule.get("parameters", {}).get("required_status_checks", []):
                    ctx = chk.get("context", "")
                    if ctx:
                        found_check_contexts.append(ctx)
            elif rtype == "non_fast_forward":
                has_non_ff = True
            elif rtype == "deletion":
                has_deletion = True

    report.add(
        "ruleset_pr_required",
        has_pr_rule,
        "PR required via ruleset." if has_pr_rule else "No PR requirement in any ruleset.",
    )
    # ADR-0011 (Option C): required reviews must stay disabled. A ruleset can
    # silently re-introduce an approval requirement that the classic-protection
    # check above cannot see; this is the only place that gap is caught.
    report.add(
        "ruleset_no_required_reviews",
        max_ruleset_review_count == 0,
        (
            "No required reviews in any ruleset \u2014 matches ADR-0011 baseline."
            if max_ruleset_review_count == 0
            else (
                f"A ruleset requires {max_ruleset_review_count} approving review(s); "
                "ADR-0011 (Option C) mandates 0 for this single-committer repo "
                "(non-zero only trains the admin-bypass reflex)."
            )
        ),
    )
    report.add(
        "ruleset_required_checks",
        has_required_checks,
        f"Required checks via ruleset: {found_check_contexts}" if has_required_checks else "No required checks in any ruleset.",
    )

    # Verify our expected check is present.
    for req_check in REQUIRED_STATUS_CHECKS:
        # Rulesets use the job name (e.g. "fast-gates") not the full workflow/job path.
        job_name = req_check.split(" / ")[-1] if " / " in req_check else req_check
        found = job_name in found_check_contexts or req_check in found_check_contexts
        report.add(
            f"ruleset_check::{req_check}",
            found,
            f"'{req_check}' is enforced via ruleset." if found else f"'{req_check}' is NOT in ruleset required checks.",
        )

    report.add(
        "ruleset_force_push_blocked",
        has_non_ff,
        "Force pushes blocked via ruleset." if has_non_ff else "No force-push block in any ruleset.",
    )
    report.add(
        "ruleset_deletion_blocked",
        has_deletion,
        "Branch deletion blocked via ruleset." if has_deletion else "No deletion block in any ruleset.",
        severity="warn",
    )


# ---------------------------------------------------------------------------
# Pre-activation checklist (printed as guidance, not gated)
# ---------------------------------------------------------------------------

_PRE_ACTIVATION_CHECKLIST = """\
Governance verification notes:
  • Rulesets are the primary enforcement mechanism (classic branch protection is optional).
  • Required check context should match the GitHub Actions job name (e.g. 'fast-gates').
  • To verify attestations: gh attestation verify <artifact>
  • To re-run this check: GITHUB_TOKEN=<token> python scripts/verify_branch_protection.py
"""


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    token = os.environ.get("GITHUB_TOKEN", "")
    if not token:
        print("Error: GITHUB_TOKEN environment variable is required.", file=sys.stderr)
        print("  Set a token with repo scope (or administration:read + metadata:read).", file=sys.stderr)
        return 2

    print(f"Verifying branch protection for {OWNER}/{REPO}:{BRANCH}\n")

    report = ProtectionReport()

    _check_branch_protection(token, report)
    _check_rulesets(token, report)

    report.print_summary()

    print()
    print(_PRE_ACTIVATION_CHECKLIST)

    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
