"""Prevent new LLM generation egress from bypassing Cisco AI Defense."""

from __future__ import annotations

import ast
from pathlib import Path

from tests._guard_corpus import iter_production_py_files

ROOT = Path(__file__).resolve().parents[1]
_EXCLUDED_PARTS = {".git", ".venv", "artifacts", "docs", "node_modules", "tests"}

# Hosts that can serve a model completion. Matching the HOST rather than one
# exact path is deliberate: pinning ``api.openai.com/v1/chat/completions`` let
# ``/v1/responses`` (and every future route on the same host) through, and the
# 2026-08-28 demo review measured exactly that gap. A new provider host in
# production code is now a review question, not a silent new egress path.
_PROVIDER_HOSTS = (
    "api.openai.com",
    "api.anthropic.com",
    "openai.azure.com",
    "generativelanguage.googleapis.com",
    "api.mistral.ai",
    "api.cohere.com",
    "api.cohere.ai",
)

# Route fragments that carry a prompt and return a completion. Used to prove
# that the reviewed non-generation exemption below cannot be abused: a file
# listed there must not contain any of these.
_GENERATION_ROUTES = (
    "/chat/completions",
    "/v1/completions",
    "/v1/responses",
    "/v1/messages",
    ":generateContent",
    ":streamGenerateContent",
    "/openai/deployments/",
)

_EXPECTED_DIRECT_EGRESS = {
    # 2026-07-21: terminal_ai_insights dead engine removed (no production
    # caller; Producer egress lives in terminal_fmp_insights).
    "terminal_fmp_insights.py",
}

# Files that reach a provider host WITHOUT sending a prompt or receiving a
# completion. Each entry is reviewed individually and must stay content-free;
# the test below re-proves that by rejecting any generation route in them, so
# this set cannot be used to smuggle an uninspected completion call in.
_EXPECTED_NON_GENERATION_PROVIDER_CALLS = {
    # GET /v1/models availability/credential probe: no prompt, no completion,
    # nothing for AI Defense to inspect (see docs/CISCO_AI_DEFENSE_IMPLEMENTATION.md).
    "scripts/probe_providers.py",
}

_PROVIDER_MODULES = (
    "openai",
    "anthropic",
    "litellm",
    "google.generativeai",
    "mistralai",
    "cohere",
)

_AGENT_MCP_MODULES = (
    "claude_agent_sdk",
    "langchain",
    "langgraph",
    "mcp",
    "openai.agents",
)


def _production_python() -> list[Path]:
    return iter_production_py_files(_EXCLUDED_PARTS)


def imported_modules(source: str, *, filename: str = "<synthetic>") -> set[str]:
    """Return every module name imported by *source*."""
    tree = ast.parse(source, filename=filename)
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    return imported


def matching_modules(imported: set[str], protected: tuple[str, ...]) -> set[str]:
    """Return the protected modules hit by *imported*, submodules included.

    ``from openai.types import X`` and ``import openai.resources`` are the same
    trust boundary as ``import openai``; an exact-match set missed both. The
    boundary is a dotted-prefix, so ``openai_helper`` must NOT match.
    """
    return {
        name
        for name in imported
        for protected_name in protected
        if name == protected_name or name.startswith(f"{protected_name}.")
    }


def provider_hosts_in(source: str) -> set[str]:
    """Return the provider hosts mentioned anywhere in *source*."""
    return {host for host in _PROVIDER_HOSTS if host in source}


def generation_routes_in(source: str) -> set[str]:
    """Return the completion-carrying route fragments mentioned in *source*."""
    return {route for route in _GENERATION_ROUTES if route in source}


def inspected_phases(source: str, *, filename: str = "<synthetic>") -> set[str]:
    """Return the ``phase=`` literals passed to ``inspect_messages`` in *source*."""
    tree = ast.parse(source, filename=filename)
    return {
        keyword.value.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "inspect_messages"
        for keyword in node.keywords
        if keyword.arg == "phase"
        and isinstance(keyword.value, ast.Constant)
        and isinstance(keyword.value.value, str)
    }


def test_direct_llm_egress_inventory_is_exact_and_guarded():
    generation: set[str] = set()
    non_generation: set[str] = set()
    sources = _production_python()
    assert sources, "no production module was scanned — the checks below would pass vacuously"
    for path in sources:
        text = path.read_text(encoding="utf-8")
        if not provider_hosts_in(text):
            continue
        relative = path.relative_to(ROOT).as_posix()
        if generation_routes_in(text):
            generation.add(relative)
            phases = inspected_phases(text, filename=relative)
            assert phases == {"request", "response"}, f"{relative} must inspect both LLM directions"
        else:
            non_generation.add(relative)

    assert generation == _EXPECTED_DIRECT_EGRESS
    assert non_generation == _EXPECTED_NON_GENERATION_PROVIDER_CALLS


def test_non_generation_exemption_cannot_hide_a_completion_call():
    """The exemption list is only allowed to contain content-free provider calls."""
    assert _EXPECTED_NON_GENERATION_PROVIDER_CALLS, "exemption inventory collapsed to nothing"
    for relative in sorted(_EXPECTED_NON_GENERATION_PROVIDER_CALLS):
        path = ROOT / relative
        assert path.is_file(), f"exempted file no longer exists: {relative}"
        routes = generation_routes_in(path.read_text(encoding="utf-8"))
        assert not routes, (
            f"{relative} is exempted from AI Defense inspection but now contains "
            f"generation route(s) {sorted(routes)} — inspect it or drop the exemption"
        )


def test_provider_sdk_imports_require_an_explicit_ai_defense_boundary():
    offenders = []
    for path in _production_python():
        imported = imported_modules(path.read_text(encoding="utf-8"), filename=str(path))
        if matching_modules(imported, _PROVIDER_MODULES) and "cisco_ai_defense" not in imported:
            offenders.append(path.relative_to(ROOT).as_posix())

    assert not offenders, f"provider SDK imports without Cisco AI Defense boundary: {offenders}"


def test_agent_and_mcp_runtimes_remain_default_deny_until_reviewed():
    """Adding a dependency is inert; activating its client is a new trust boundary."""
    offenders = []
    for path in _production_python():
        imported = imported_modules(path.read_text(encoding="utf-8"), filename=str(path))
        if matching_modules(imported, _AGENT_MCP_MODULES):
            offenders.append(path.relative_to(ROOT).as_posix())

    assert not offenders, (
        "first-party agent/MCP runtime added before dedicated Cisco runtime, "
        f"tool-policy, and supply-chain review: {offenders}"
    )


# ---------------------------------------------------------------------------
# Positive controls.
#
# The three guards above assert over a corpus that currently contains no
# offender, so "green" alone proves nothing about their detection power — the
# 2026-08-28 review measured four patterns the previous version missed while
# reporting success. These cases feed a synthetic offender through the same
# helper functions the guards use, so a regression in the matching logic fails
# here instead of silently widening the allowed egress surface.
# ---------------------------------------------------------------------------


def test_provider_import_detection_catches_submodules_and_new_vendors():
    caught = {
        "import openai",
        "from openai import OpenAI",
        "from openai.types import ChatCompletion",
        "import openai.resources as resources",
        "import anthropic",
        "from anthropic.resources import messages",
        "import mistralai",
        "from google.generativeai import GenerativeModel",
        "import cohere",
    }
    for source in sorted(caught):
        imported = imported_modules(source)
        assert matching_modules(imported, _PROVIDER_MODULES), f"missed provider import: {source}"


def test_provider_import_detection_does_not_fire_on_lookalike_modules():
    for source in ("import openai_helper", "from anthropic_stub import x", "import cohere_utils"):
        imported = imported_modules(source)
        assert not matching_modules(imported, _PROVIDER_MODULES), f"false positive: {source}"


def test_generation_endpoint_detection_catches_routes_beyond_chat_completions():
    caught = {
        'httpx.post("https://api.openai.com/v1/chat/completions")',
        'httpx.post("https://api.openai.com/v1/responses")',
        'httpx.post("https://api.anthropic.com/v1/messages")',
        'httpx.post("https://acme.openai.azure.com/openai/deployments/gpt/chat/completions")',
        'httpx.post("https://generativelanguage.googleapis.com/v1beta/models/x:generateContent")',
        'httpx.post("https://api.mistral.ai/v1/chat/completions")',
    }
    for source in sorted(caught):
        assert provider_hosts_in(source), f"missed provider host: {source}"
        assert generation_routes_in(source), f"missed generation route: {source}"


def test_generation_detection_separates_a_content_free_probe():
    probe = 'httpx.get("https://api.openai.com/v1/models")'
    assert provider_hosts_in(probe), "a provider host must still be discovered in a probe"
    assert not generation_routes_in(probe), "GET /v1/models carries no prompt and no completion"


def test_phase_extraction_requires_both_directions():
    one_phase = 'inspect_messages(m, phase="request", source="s", model="m")'
    both = one_phase + '\ninspect_messages(m, phase="response", source="s", model="m")'
    assert inspected_phases(one_phase) == {"request"}
    assert inspected_phases(both) == {"request", "response"}
    assert inspected_phases("pass") == set()
