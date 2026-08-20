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

2026-08-20 (Geburtsfehler-Sweep, Nachzug): die Population war
``scripts/*.py`` — ein GLOB, keine abgeleitete Menge. Heute liegen alle fuenf
Konstruktionen dort, aber genau der Anlass dieses Tripwires (die Verdrahtung
eines echten ``submit_fn`` beim Paper-Flip) kann ebenso gut unter
``services/`` oder ``automation/`` landen, und dann haette der Wachter
geschwiegen, ohne dass irgendetwas rot wird. Jetzt laeuft er ueber ALLE
getrackten ``*.py`` ausserhalb von ``tests/``; der Beweis, dass die
Verbreiterung traegt, steht als Mutationsprobe unten.
"""

from __future__ import annotations

import ast
from pathlib import Path

from tests._guard_corpus import iter_tracked_files

_REPO_ROOT = Path(__file__).resolve().parent.parent
_WATCHLIST_MODULE = "scripts.execute_ibkr_watchlist"
_CONFIG_CLASS = "IBKRExecutionConfig"
# tests/ exerzieren die Defaults absichtlich; die uebrigen sind kein Produktionscode.
_EXCLUDED_DIRS = ("tests", ".venv", "node_modules", ".git", "build", "dist")


def _watchlist_config_aliases(tree: ast.Module) -> set[str]:
    """Names under which THIS module can construct the watchlist config."""
    aliases: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == _WATCHLIST_MODULE:
            for alias in node.names:
                if alias.name == _CONFIG_CLASS:
                    aliases.add(alias.asname or alias.name)
    return aliases


def _scan(sources: dict[str, str]) -> tuple[list[str], list[str]]:
    """(witnesses, offenders) over any {path: source} mapping.

    Nimmt die Quellen als Argument, damit die Mutationsprobe eine
    synthetische Konstruktion an einem Ort einspeisen kann, den der alte
    ``scripts/*.py``-Glob nie gesehen haette.
    """
    offenders: list[str] = []
    witnesses: list[str] = []
    for name, source in sorted(sources.items()):
        tree = ast.parse(source)
        aliases = _watchlist_config_aliases(tree)
        if name.endswith("execute_ibkr_watchlist.py"):
            aliases.add(_CONFIG_CLASS)  # modul-eigene Konstruktionen
        if not aliases:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not (isinstance(func, ast.Name) and func.id in aliases):
                continue
            witnesses.append(f"{name}:{node.lineno}")
            if not any(kw.arg == "exit_tif" for kw in node.keywords):
                offenders.append(f"{name}:{node.lineno}")
    return witnesses, offenders


def _production_sources() -> dict[str, str]:
    paths = iter_tracked_files("*.py", _EXCLUDED_DIRS, root=_REPO_ROOT)
    return {
        path.relative_to(_REPO_ROOT).as_posix(): path.read_text(encoding="utf-8")
        for path in paths
    }


def test_every_watchlist_execution_config_names_exit_tif() -> None:
    sources = _production_sources()
    assert len(sources) >= 300, (
        f"only {len(sources)} tracked production modules scanned — the corpus "
        "collapsed (git ls-files failed?); 1000+ existed on 2026-08-20."
    )
    witnesses, offenders = _scan(sources)
    assert len(witnesses) >= 3, (
        f"only {witnesses} watchlist-execution-config constructions found — the "
        "scan went vacuous (import resolution or corpus broke); five sites "
        "existed on 2026-08-20, all under scripts/."
    )
    assert not offenders, (
        "watchlist execution config constructed without naming exit_tif: "
        f"{offenders}. Decide it: \"GTC\" so the tp/sl/trail legs survive the "
        "session, or an explicit None WITH a comment when a standing supervised "
        "session makes DAY-everything the design. A silent default re-opens the "
        "C13 zombie class (#4848)."
    )


def test_a_submitter_outside_scripts_is_seen() -> None:
    """Mutationsprobe fuer die Verbreiterung selbst.

    Ohne sie beweist nichts, dass der Wachter mehr als ``scripts/`` liest —
    und genau das war der Geburtsfehler. Der synthetische Verstoss liegt
    unter ``services/``, wo der alte Glob blind war.
    """
    synthetic = {
        "services/commercial_paper_pilot/submit.py": (
            "from scripts.execute_ibkr_watchlist import IBKRExecutionConfig\n"
            "cfg = IBKRExecutionConfig(account='DU1', dry_run=False)\n"
        )
    }
    witnesses, offenders = _scan(synthetic)
    assert witnesses == ["services/commercial_paper_pilot/submit.py:2"], witnesses
    assert offenders == ["services/commercial_paper_pilot/submit.py:2"], (
        "a construction outside scripts/ was not flagged — the population is "
        "still narrower than the class this tripwire names"
    )

    named = {
        path: source.replace("dry_run=False", "dry_run=False, exit_tif='GTC'")
        for path, source in synthetic.items()
    }
    assert _scan(named)[1] == [], "naming exit_tif must clear the finding"
