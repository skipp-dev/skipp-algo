"""A secret-backed env var may not be read with a two-argument get() default.

GitHub Actions maps an env var to a MISSING secret as the empty string, not as
an absent variable. So `os.environ.get("X", fallback)` never returns `fallback`
for anything a workflow feeds from `secrets.X` — the code silently proceeds with
"".

Measured 2026-08-03, run 30845071629: the live-overlay deploy-trigger guard had
been asking Railway about service "" ever since it was written, because
`RAILWAY_LIVE_OVERLAY_SERVICE_ID` is mapped from a secret that does not exist.
It stayed invisible for weeks — Railway refused the query on other grounds
before the service id could matter — and only surfaced when a fail-closed
fallback had to locate the service by id.

The whole class was one site at the time this guard was written. This test is
what keeps it that way.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_SOURCE_DIRS = ("scripts", "services")
_SECRET_ENV = re.compile(r"^\s*([A-Z][A-Z0-9_]{2,}):\s*\$\{\{\s*secrets\.", re.M)


def _secret_backed_env_vars() -> dict[str, set[str]]:
    """Env var -> workflows that feed it from a secret."""
    mapped: dict[str, set[str]] = {}
    for workflow in sorted((_ROOT / ".github" / "workflows").glob("*.yml")):
        for match in _SECRET_ENV.finditer(workflow.read_text(encoding="utf-8")):
            mapped.setdefault(match.group(1), set()).add(workflow.name)
    return mapped


def _is_environ_get(node: ast.Call) -> bool:
    func = node.func
    return (
        isinstance(func, ast.Attribute)
        and func.attr == "get"
        and isinstance(func.value, ast.Attribute)
        and func.value.attr == "environ"
    )


def _offending_reads(mapped: dict[str, set[str]]) -> list[str]:
    offenders = []
    for source_dir in _SOURCE_DIRS:
        for path in sorted((_ROOT / source_dir).rglob("*.py")):
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except SyntaxError:  # pragma: no cover - not this test's business
                continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call) or not _is_environ_get(node):
                    continue
                if len(node.args) != 2:
                    continue
                name, default = node.args
                if not isinstance(name, ast.Constant) or name.value not in mapped:
                    continue
                # `get(X, "")` is honest: it wants "" and would get "" anyway.
                if isinstance(default, ast.Constant) and default.value == "":
                    continue
                offenders.append(
                    f"{path.relative_to(_ROOT)}:{node.lineno} reads "
                    f"{name.value} (fed from a secret by "
                    f"{', '.join(sorted(mapped[name.value]))}) with a get() "
                    "default that a missing secret will never trigger — use "
                    "`os.environ.get(...) or <default>`"
                )
    return offenders


def test_workflows_still_feed_env_vars_from_secrets():
    """Guards the guard: if the workflow scan broke, the real test would pass
    vacuously on an empty mapping rather than because the tree is clean."""
    mapped = _secret_backed_env_vars()
    assert len(mapped) >= 20, f"only {len(mapped)} secret-backed env vars found"
    assert "RAILWAY_LIVE_OVERLAY_SERVICE_ID" in mapped


def test_no_secret_backed_env_var_is_read_with_a_get_default():
    offenders = _offending_reads(_secret_backed_env_vars())
    assert not offenders, "\n".join(offenders)


def test_the_detector_catches_the_pattern_it_exists_for(tmp_path, monkeypatch):
    """Counter-proof, self-contained: the shape that shipped must be flagged."""
    source = tmp_path / "scripts"
    source.mkdir()
    (source / "sample.py").write_text(
        'import os\n'
        '_DEFAULT = "705582c5"\n'
        'x = os.environ.get("RAILWAY_LIVE_OVERLAY_SERVICE_ID", _DEFAULT)\n'
        'y = os.environ.get("RAILWAY_LIVE_OVERLAY_SERVICE_ID") or _DEFAULT\n',
        encoding="utf-8",
    )
    monkeypatch.setattr("tests.test_workflow_env_var_defaults._ROOT", tmp_path)
    monkeypatch.setattr("tests.test_workflow_env_var_defaults._SOURCE_DIRS", ("scripts",))
    offenders = _offending_reads({"RAILWAY_LIVE_OVERLAY_SERVICE_ID": {"guard.yml"}})
    # Exactly one: the `or` form on the next line must NOT be flagged.
    assert len(offenders) == 1, offenders
    assert "sample.py:3" in offenders[0]
