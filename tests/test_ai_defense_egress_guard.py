"""Prevent new LLM generation egress from bypassing Cisco AI Defense."""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_EXCLUDED_PARTS = {".git", ".venv", "artifacts", "docs", "node_modules", "tests"}
_GENERATION_ENDPOINTS = (
    "api.openai.com/v1/chat/completions",
    "api.anthropic.com/v1/messages",
)
_EXPECTED_DIRECT_EGRESS = {
    "terminal_ai_insights.py",
    "terminal_fmp_insights.py",
}


def _production_python() -> list[Path]:
    return [
        path
        for path in ROOT.rglob("*.py")
        if not any(part in _EXCLUDED_PARTS or part.startswith(".") for part in path.relative_to(ROOT).parts)
    ]


def test_direct_llm_egress_inventory_is_exact_and_guarded():
    hits = set()
    for path in _production_python():
        text = path.read_text(encoding="utf-8")
        if any(endpoint in text for endpoint in _GENERATION_ENDPOINTS):
            relative = path.relative_to(ROOT).as_posix()
            hits.add(relative)
            tree = ast.parse(text, filename=relative)
            calls = [
                node
                for node in ast.walk(tree)
                if isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "inspect_messages"
            ]
            phases = {
                keyword.value.value
                for call in calls
                for keyword in call.keywords
                if keyword.arg == "phase"
                and isinstance(keyword.value, ast.Constant)
                and isinstance(keyword.value.value, str)
            }
            assert phases == {"request", "response"}, f"{relative} must inspect both LLM directions"

    assert hits == _EXPECTED_DIRECT_EGRESS


def test_provider_sdk_imports_require_an_explicit_ai_defense_boundary():
    provider_modules = {"openai", "anthropic", "litellm", "google.generativeai"}
    offenders = []
    for path in _production_python():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
        if imported & provider_modules and "cisco_ai_defense" not in imported:
            offenders.append(path.relative_to(ROOT).as_posix())

    assert not offenders, f"provider SDK imports without Cisco AI Defense boundary: {offenders}"


def test_agent_and_mcp_runtimes_remain_default_deny_until_reviewed():
    """Adding a dependency is inert; activating its client is a new trust boundary."""
    agent_mcp_modules = {
        "claude_agent_sdk",
        "langchain",
        "langgraph",
        "mcp",
        "openai.agents",
    }
    offenders = []
    for path in _production_python():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
        if any(
            imported_name == protected_name or imported_name.startswith(f"{protected_name}.")
            for imported_name in imported
            for protected_name in agent_mcp_modules
        ):
            offenders.append(path.relative_to(ROOT).as_posix())

    assert not offenders, (
        "first-party agent/MCP runtime added before dedicated Cisco runtime, "
        f"tool-policy, and supply-chain review: {offenders}"
    )
