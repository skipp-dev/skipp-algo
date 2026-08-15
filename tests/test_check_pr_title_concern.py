"""Tests for ``scripts/check_pr_title_concern.py`` (ADR-0013 enforcement).

Also references the companion workflow basename ``pr-title-concern-lint``
so the workflow is not flagged by ``test_workflow_orphan_inventory``.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "check_pr_title_concern.py"
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "pr-title-concern-lint.yml"
LIBRARY_REFRESH_WORKFLOW_PATH = (
    REPO_ROOT / ".github" / "workflows" / "smc-library-refresh.yml"
)


def _load_module():
    spec = importlib.util.spec_from_file_location("check_pr_title_concern", SCRIPT_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["check_pr_title_concern"] = module
    spec.loader.exec_module(module)
    return module


mod = _load_module()


VALID_TITLES = [
    "feat(test): ADR-0010 generic cron-invariants suite",
    "fix(credential-health): atomic-write exempt marker",
    "ci(actions): bump upload-artifact to v7 across all workflows",
    "test(workflows): pin live-window marker",
    "refactor(ledger): move allowlist to TOML",
    "chore(deps): bump pyyaml",
    "feat(api)!: drop legacy v1 endpoint",
    'Revert "feat(test): ADR-0010 generic cron-invariants suite"',
]

INVALID_TITLES = [
    "",
    "   ",
    "add a new feature",  # no concern prefix
    "feat: missing scope",  # scope required
    "Feature(test): capitalised concern",  # concern must be lowercase
    "bump(deps): unknown concern type",  # 'bump' not accepted
    "feat(): empty scope",
    "feat(test):",  # empty subject
    "feat(test): ",  # whitespace-only subject
]


@pytest.mark.parametrize("title", VALID_TITLES)
def test_valid_titles_pass(title: str) -> None:
    assert mod.validate_pr_title(title) == [], title


@pytest.mark.parametrize("title", INVALID_TITLES)
def test_invalid_titles_fail(title: str) -> None:
    assert mod.validate_pr_title(title) != [], title


def test_missing_scope_gives_actionable_hint() -> None:
    reasons = mod.validate_pr_title("feat: no scope here")
    assert any("scope is required" in r.lower() for r in reasons)


def test_unknown_concern_lists_accepted_types() -> None:
    reasons = mod.validate_pr_title("bump(deps): x")
    assert any("feat" in r and "fix" in r for r in reasons)


def test_main_reads_pr_title_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PR_TITLE", "feat(test): valid title")
    assert mod.main([]) == 0


def test_main_rejects_bad_title_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PR_TITLE", "not a valid title")
    assert mod.main([]) == 1


def test_main_no_title_returns_2(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PR_TITLE", raising=False)
    assert mod.main([]) == 2


def test_env_takes_precedence_over_argv(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PR_TITLE", "feat(test): from env")
    # argv title is invalid, but env (valid) wins → exit 0
    assert mod.main(["garbage title"]) == 0


def test_accepted_concerns_are_lowercase() -> None:
    assert all(c.islower() for c in mod.ACCEPTED_CONCERNS)


def test_companion_workflow_exists() -> None:
    """ADR-0013 enforcement is only real if the workflow ships with it."""
    assert WORKFLOW_PATH.is_file(), (
        "pr-title-concern-lint.yml workflow must exist to enforce ADR-0013 in CI."
    )


def _rendered(template: str) -> str:
    """Substitute shell/Actions placeholders with dummies; the concern prefix
    under test is always literal, placeholders only ever sit in the subject."""
    import re

    rendered = re.sub(r"\$\{\{[^}]*\}\}", "986", template)
    rendered = re.sub(r"\$\([^)]*\)", "2026-07-27", rendered)
    rendered = re.sub(r"\$\{[^}]*\}", "986", rendered)
    return re.sub(r"\$\w+", "986", rendered)


def _generated_pr_titles() -> list[tuple[str, str]]:
    """(workflow name, title template) for EVERY ``gh pr create`` in the corpus.

    2026-08-15: the predecessor of this test checked exactly ONE workflow
    (smc-library-refresh), which is why the R1 re-attestation proposer could
    ship ``governance: …`` — a title the lint rejects — and every one of its
    proposal PRs carried a red lint-title check. The claim "bot-generated PR
    titles pass ADR-0013" is a claim about the set of all PR-creating
    workflows, so this walks that set. Issue titles (``gh issue create``) are
    not linted and stay out of the population.

    A ``--title "$VAR"`` site resolves through the literal ``VAR="…"``
    assignments in the same run body (all of them — a branchy assignment must
    pass on every branch). A site this cannot resolve fails the test by name:
    keep generated titles statically checkable.
    """
    import re

    import yaml

    found: list[tuple[str, str]] = []
    workflow_dir = REPO_ROOT / ".github" / "workflows"
    for path in sorted(workflow_dir.glob("*.yml")) + sorted(workflow_dir.glob("*.yaml")):
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(document, dict):
            continue
        for job in (document.get("jobs") or {}).values():
            if not isinstance(job, dict):
                continue
            for step in job.get("steps") or []:
                if not isinstance(step, dict):
                    continue
                body = step.get("run")
                if not (isinstance(body, str) and "gh pr create" in body):
                    continue
                # EXCLUDE known non-invocations (a comment, or an error
                # message like `echo "… gh pr create failed"`); everything
                # else counts and MUST parse a --title below. Deliberately
                # not the inverse (accept known command shapes): the first
                # version of this filter did that, and the capture shapes
                # `pr_stderr=$(gh pr create` / `if ! pr_err="$(gh pr create`
                # silently dropped tv-save-consumer-source and fvg-quality
                # from the population while the corpus-size floor still
                # passed. An unknown NEW shape now fails loudly instead of
                # vanishing.
                invocation_starts = [
                    m.start()
                    for m in re.finditer(r"gh pr create", body)
                    if not any(
                        marker in body[body.rfind("\n", 0, m.start()) + 1 : m.start()]
                        for marker in ("#", "echo ")
                    )
                ]
                assert invocation_starts, (
                    f"{path.name}: a run body mentions gh pr create but the "
                    "exclusion filter dropped every occurrence — if this body "
                    "really only TALKS about gh pr create (comment/echo), "
                    "adjust the filter consciously rather than letting the "
                    "site vanish from the population"
                )
                for invocation_start in invocation_starts:
                    # a shell invocation extends over backslash continuations
                    lines = body[invocation_start:].splitlines()
                    invocation_lines = []
                    for line in lines:
                        invocation_lines.append(line)
                        if not line.rstrip().endswith("\\"):
                            break
                    invocation = "\n".join(invocation_lines)
                    title_match = re.search(r'--title "([^"]*)"', invocation)
                    assert title_match, (
                        f"{path.name}: gh pr create without a parseable "
                        f'--title "…" — keep generated titles statically checkable'
                    )
                    template = title_match.group(1)
                    variable = re.fullmatch(r"\$\{?(\w+)\}?", template)
                    if variable is None:
                        found.append((path.name, template))
                        continue
                    assignments = re.findall(
                        rf'^\s*{variable.group(1)}="([^"]*)"', body, flags=re.M
                    )
                    assert assignments, (
                        f"{path.name}: --title uses ${variable.group(1)} but no "
                        f'literal {variable.group(1)}="…" assignment exists in the '
                        "same run body — keep generated titles statically checkable"
                    )
                    found.extend((path.name, template) for template in assignments)
    return found


def test_every_generated_pr_title_satisfies_adr_0013() -> None:
    titles = _generated_pr_titles()
    # Corpus collapse guard: a discovery bug that finds nothing would make
    # this test pass over an empty set. Measured 2026-08-15: 16 sites.
    assert len(titles) >= 10, (
        f"only {len(titles)} generated PR titles discovered — the corpus walk "
        f"is broken, not the workflows: {titles}"
    )
    failures = [
        f"{workflow}: {template!r} -> {mod.validate_pr_title(_rendered(template))}"
        for workflow, template in titles
        if mod.validate_pr_title(_rendered(template)) != []
    ]
    assert failures == [], (
        "bot-generated PR titles the lint would reject (every proposal PR "
        "from these workflows carries a permanently red lint-title check, "
        "and permanent red trains people to ignore red):\n" + "\n".join(failures)
    )
