"""A secret-backed env var may not be read with a fallback ARGUMENT.

GitHub Actions maps an env var to a MISSING secret as the empty string, not as
an absent variable. So `os.environ.get("X", fallback)` — and `os.getenv`, and the
`default=` keyword form — never returns `fallback` for anything a workflow feeds
from `secrets.X`; the code silently proceeds with "". Only `... or fallback`
survives an empty value.

Measured 2026-08-03, run 30845071629: the live-overlay deploy-trigger guard had
been asking Railway about service "" ever since it was written, because
`RAILWAY_LIVE_OVERLAY_SERVICE_ID` is mapped from a secret that does not exist.
It stayed invisible for weeks — Railway refused the query on other grounds
before the service id could matter — and only surfaced when a fail-closed
fallback had to locate the service by id.

The class was FOUR sites, not one. The first version of this test said one,
because it matched only ``os.environ.get`` — ``scripts/update_overlay_dashboard.py``
spells the identical pattern ``os.getenv``, three times, for three of the same
secret-backed names (latent: no workflow that runs it sets them, so the defaults
do apply today). A detector that cannot see the second spelling does not measure
the class, it measures itself. Hence the counter-proof below covers every
spelling, including the ``default=`` keyword form, which works at runtime.
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


def _is_env_read(node: ast.Call) -> bool:
    """Every spelling of "read an env var with a fallback" in this repo.

    The first version matched only ``<x>.environ.get`` and therefore reported
    the class as one site. It was four: ``scripts/update_overlay_dashboard.py``
    spells the identical pattern ``os.getenv`` three times, for three of the
    same secret-backed names, and a fourth for the signals producer. A detector
    that cannot see the second spelling does not measure the class, it measures
    itself.
    """
    func = node.func
    if isinstance(func, ast.Name):  # from os import getenv
        return func.id == "getenv"
    if not isinstance(func, ast.Attribute):
        return False
    if func.attr == "getenv":  # os.getenv(...)
        return True
    if func.attr != "get":
        return False
    # os.environ.get(...) and, after `from os import environ`, environ.get(...)
    return (isinstance(func.value, ast.Attribute) and func.value.attr == "environ") or (
        isinstance(func.value, ast.Name) and func.value.id == "environ"
    )


def _default_arg(node: ast.Call) -> ast.expr | None:
    """The fallback, positional or keyword.

    ``os.environ.get("X", default=Y)`` works at runtime — ``os._Environ`` inherits
    ``MutableMapping.get``, a plain Python def — so a detector that only reads
    ``args[1]`` misses it.
    """
    if len(node.args) > 1:
        return node.args[1]
    for keyword in node.keywords:
        if keyword.arg == "default":
            return keyword.value
    return None


def _offending_reads(mapped: dict[str, set[str]]) -> list[str]:
    offenders = []
    for source_dir in _SOURCE_DIRS:
        for path in sorted((_ROOT / source_dir).rglob("*.py")):
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except SyntaxError:  # pragma: no cover - not this test's business
                continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call) or not _is_env_read(node):
                    continue
                if not node.args:
                    continue
                name = node.args[0]
                default = _default_arg(node)
                if default is None:
                    continue
                if not isinstance(name, ast.Constant) or name.value not in mapped:
                    continue
                # `get(X, "")` is honest: it wants "" and would get "" anyway.
                if isinstance(default, ast.Constant) and default.value == "":
                    continue
                offenders.append(
                    f"{path.relative_to(_ROOT)}:{node.lineno} reads "
                    f"{name.value} (fed from a secret by "
                    f"{', '.join(sorted(mapped[name.value]))}) with a fallback "
                    "argument that a missing secret will never trigger — use "
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
        "import os\n"
        "from os import environ, getenv\n"
        '_DEFAULT = "705582c5"\n'
        # Every spelling that silently swallows a missing secret:
        'a = os.environ.get("RAILWAY_LIVE_OVERLAY_SERVICE_ID", _DEFAULT)\n'
        'b = os.getenv("RAILWAY_LIVE_OVERLAY_SERVICE_ID", _DEFAULT)\n'
        'c = environ.get("RAILWAY_LIVE_OVERLAY_SERVICE_ID", _DEFAULT)\n'
        'd = getenv("RAILWAY_LIVE_OVERLAY_SERVICE_ID", _DEFAULT)\n'
        'e = os.environ.get("RAILWAY_LIVE_OVERLAY_SERVICE_ID", default=_DEFAULT)\n'
        # And the forms that must NOT be flagged:
        'f = os.environ.get("RAILWAY_LIVE_OVERLAY_SERVICE_ID") or _DEFAULT\n'
        'g = os.getenv("RAILWAY_LIVE_OVERLAY_SERVICE_ID") or _DEFAULT\n'
        'h = os.environ.get("RAILWAY_LIVE_OVERLAY_SERVICE_ID", "")\n'
        'i = os.environ.get("SOME_OTHER_VAR", _DEFAULT)\n',
        encoding="utf-8",
    )
    monkeypatch.setattr("tests.test_workflow_env_var_defaults._ROOT", tmp_path)
    monkeypatch.setattr("tests.test_workflow_env_var_defaults._SOURCE_DIRS", ("scripts",))
    offenders = _offending_reads({"RAILWAY_LIVE_OVERLAY_SERVICE_ID": {"guard.yml"}})
    # Exactly the five swallowing forms; the `or`, the honest "", and the
    # unmapped variable must all stay unflagged.
    flagged = sorted(int(o.split(":")[1].split(" ")[0]) for o in offenders)
    assert flagged == [4, 5, 6, 7, 8], offenders
