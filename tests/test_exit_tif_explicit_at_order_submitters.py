"""Every production construction of the watchlist execution config must
decide ``exit_tif`` explicitly.

2026-08-18/19 (Review zu #4848, Finding #7): Die C13-Kampagne platzierte
DAY-only-Bracket-Exits, weil ``exit_tif`` im Executor auf ``None`` defaultete
und keine Call-Site etwas anderes sagen MUSSTE; Positionen, die die Session
ueberlebten, verloren am Bell ihren Schutz (9 Zombies seit Juni). #4848 hat
den C13-Treiber repariert — dieser Tripwire schliesst die KLASSE: der naechste
Submitter (z. B. die Verdrahtung eines echten ``submit_fn`` beim Paper-Flip
der Commercial-Familie) kann keine Watchlist-Execution-Config mehr bauen,
ohne ``exit_tif`` zu benennen — ``"GTC"``, oder ein explizites ``None`` dort,
wo eine stehende, supervidierte Session DAY-alles zum Design macht (siehe
``run_ibkr_open_execution.py``).

Import-aufgeloest per AST, damit der gleichnamige Adapter-Alias
(``scripts.smc_to_ibkr_adapter.IBKRExecutionConfig`` = ``IBKRAdapterConfig``,
reine Connection-Metadaten ohne tif-Begriff) nicht als False Positive zaehlt.
Tests sind ausgenommen: sie exerzieren die Defaults absichtlich.
"""

from __future__ import annotations

import ast
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_WATCHLIST_MODULE = "scripts.execute_ibkr_watchlist"
_CONFIG_CLASS = "IBKRExecutionConfig"


def _watchlist_config_aliases(tree: ast.Module) -> set[str]:
    """Names under which THIS module can construct the watchlist config."""
    aliases: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == _WATCHLIST_MODULE:
            for alias in node.names:
                if alias.name == _CONFIG_CLASS:
                    aliases.add(alias.asname or alias.name)
    return aliases


def test_every_watchlist_execution_config_in_scripts_names_exit_tif() -> None:
    offenders: list[str] = []
    witnesses: list[str] = []
    for path in sorted((_REPO_ROOT / "scripts").glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        aliases = _watchlist_config_aliases(tree)
        if path.name == "execute_ibkr_watchlist.py":
            aliases.add(_CONFIG_CLASS)  # modul-eigene Konstruktionen
        if not aliases:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not (isinstance(func, ast.Name) and func.id in aliases):
                continue
            witnesses.append(f"{path.name}:{node.lineno}")
            if not any(kw.arg == "exit_tif" for kw in node.keywords):
                offenders.append(f"{path.name}:{node.lineno}")
    assert len(witnesses) >= 3, (
        f"only {witnesses} watchlist-execution-config constructions found in "
        "scripts/ — the scan went vacuous (import resolution or glob broke); "
        "three sites existed on 2026-08-19."
    )
    assert not offenders, (
        "watchlist execution config constructed without naming exit_tif: "
        f"{offenders}. Decide it: \"GTC\" so the tp/sl/trail legs survive the "
        "session, or an explicit None WITH a comment when a standing supervised "
        "session makes DAY-everything the design. A silent default re-opens the "
        "C13 zombie class (#4848)."
    )
