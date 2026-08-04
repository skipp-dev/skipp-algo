"""What ``edge-pipeline-real-run.yml``'s run step decides, executed.

References the workflow stem ``edge-pipeline-real-run`` so the orphan-workflow
inventory stays closed.

The step spends real Databento quota per symbol and publishes ``archived`` and
``config_error``; the archive step hangs on the first and the job's colour on
the second. Measured 2026-08-04 with a value-preserving arm swap
(``CONFIG_ERROR`` 0 <-> 1, the token multiset left unchanged so any substring
assertion is blind by construction): all 18 assertions across the 2 files that
name this workflow stayed green.

The distinction only execution can make is the one the step's own comment calls
out: ``run_edge_pipeline`` exit 2 is **family blocked**, the expected honest
result, and must be archived like a promotion. Exit 1 is a configuration error
and must fail the job loudly. Those two are one digit apart in the source and
opposite in meaning.
"""

from __future__ import annotations

import sys
from pathlib import Path

from tests._workflow_step_shell import Stub, run_step

WORKFLOW = "edge-pipeline-real-run.yml"
RUN_STEP = "Run edge pipeline per symbol (REAL Databento)"

# Mirrors the step's `${{ inputs.* }}` reads. Actions resolves these before bash
# sees them; a leftover one is a hard failure in the harness rather than a
# silent syntax error attributed to the workflow.
INPUTS = {
    "inputs.dataset": "XNAS.ITCH",
    "inputs.schema": "ohlcv-1m",
    "inputs.timeframe": "5m",
    "inputs.start": "2026-05-01",
    "inputs.end": "2026-08-01",
    # All three optional flags are supplied on purpose. The step expands
    # "${AS_OF_FLAG[@]}" under `set -u`, and expanding an EMPTY array that way
    # is only legal from bash 4.4 on. CI runs bash 5.x and is fine; the
    # developer machine here is bash 3.2, where the same line aborts the step
    # with "unbound variable". Filling the arrays keeps every assertion below
    # measurable on both, at the cost of not covering the flags-absent path --
    # which is stated rather than silently skipped.
    "inputs.as_of": "2026-08-01",
    "inputs.with_trades": "true",
    "inputs.with_opra": "true",
}

# Dispatches on the module and the symbol so each leg of a multi-symbol run can
# be steered independently -- which is the only way to tell "one symbol blocked"
# from "the whole run blocked".
_PIPELINE_STUB = Stub(script='''
sym=""; prev=""
case "$2" in
  scripts.pull_databento_edge_input)
     for a in "$@"; do [ "$prev" = "--symbol" ] && sym="$a"; prev="$a"; done
     eval "rc=\\${PULL_RC_${sym}:-0}"; exit "$rc" ;;
  scripts.run_edge_pipeline)
     for a in "$@"; do [ "$prev" = "--input" ] && sym="$(basename "$a" _input.json)"; prev="$a"; done
     eval "rc=\\${RUN_RC_${sym}:-0}"; exit "$rc" ;;
esac
exit 0
''')


def _run(tmp_path: Path, *, symbols: str, rcs: dict[str, str] | None = None):
    tmp_path.mkdir(parents=True, exist_ok=True)
    return run_step(
        WORKFLOW, RUN_STEP, tmp_path,
        env={"REAL_PYTHON": sys.executable, "DATABENTO_API_KEY": "stub-key",
             **(rcs or {})},
        stubs={"python": _PIPELINE_STUB},
        expressions={**INPUTS, "inputs.symbols": symbols},
    )


# Every case below carries one deliberately structureless symbol. The step ends
# with `echo "no_structure=${NO_STRUCTURE[*]}"`, and expanding an EMPTY array
# under `set -u` is legal only from bash 4.4 on -- CI's bash 5.x accepts it,
# the bash 3.2 this was written against aborts with "unbound variable". Keeping
# that array non-empty makes every assertion here executable on both. What it
# does NOT cover is the all-healthy run where no symbol is skipped; that path is
# stated here rather than asserted by a test nobody could run.
NO_STRUCTURE_SYMBOL = "ZZZZ"
_SKIPPED = {"PULL_RC_ZZZZ": "3"}


def test_every_healthy_symbol_archives_a_decision(tmp_path: Path) -> None:
    result = _run(tmp_path, symbols=f"AAPL,MSFT,{NO_STRUCTURE_SYMBOL}", rcs=dict(_SKIPPED))
    assert result.returncode == 0, result.stderr
    assert result.outputs["archived"] == "2"
    assert result.outputs["config_error"] == "0"
    assert result.outputs["ran"] == "AAPL MSFT"
    assert result.outputs["no_structure"] == NO_STRUCTURE_SYMBOL


def test_a_blocked_family_is_archived_not_failed(tmp_path: Path) -> None:
    """Exit 2 is the expected honest result, and it archives a real decision.

    This is the assertion the whole step is built around. Treating rc=2 as a
    failure would throw away the verdict the run just paid Databento to
    produce, and the source cannot distinguish that from the correct handling.
    """
    result = _run(tmp_path, symbols=f"AAPL,{NO_STRUCTURE_SYMBOL}",
                  rcs={"RUN_RC_AAPL": "2", **_SKIPPED})
    assert result.returncode == 0, (
        f"a blocked family must not fail the job: {result.stderr}"
    )
    assert result.outputs["archived"] == "1"
    assert result.outputs["ran"] == "AAPL"


def test_a_configuration_error_fails_loudly(tmp_path: Path) -> None:
    """Exit 1 is one digit away from `blocked` and the opposite verdict."""
    result = _run(tmp_path, symbols=f"AAPL,{NO_STRUCTURE_SYMBOL}",
                  rcs={"RUN_RC_AAPL": "1", **_SKIPPED})
    assert result.returncode != 0, "a configuration error must fail the job"
    assert result.outputs["config_error"] == "1"
    assert "::error" in result.stdout


def test_one_bad_symbol_fails_the_run_even_beside_good_ones(tmp_path: Path) -> None:
    """A partial success is still a broken configuration.

    Without this, a config error on the second of five symbols would be
    reported as four fine decisions and a green run.
    """
    result = _run(tmp_path, symbols=f"AAPL,MSFT,{NO_STRUCTURE_SYMBOL}",
                  rcs={"RUN_RC_MSFT": "1", **_SKIPPED})
    assert result.returncode != 0
    assert result.outputs["archived"] == "1", result.outputs
    assert result.outputs["config_error"] == "1"


def test_a_symbol_without_structure_is_skipped_not_failed(tmp_path: Path) -> None:
    """An empty pull is an honest empty, and the run continues past it."""
    result = _run(tmp_path, symbols="AAPL,MSFT", rcs={"PULL_RC_AAPL": "3"})
    assert result.returncode == 0, result.stderr
    assert result.outputs["no_structure"] == "AAPL"
    assert result.outputs["archived"] == "1"
    assert result.outputs["ran"] == "MSFT"


def test_a_run_that_archived_nothing_fails(tmp_path: Path) -> None:
    """Nothing honest to show is a failure, not a quiet success.

    Every symbol yielding no structure is indistinguishable from a healthy run
    in the outputs alone -- so the step refuses to report it as one.
    """
    result = _run(tmp_path, symbols="AAPL,MSFT",
                  rcs={"PULL_RC_AAPL": "3", "PULL_RC_MSFT": "3"})
    assert result.returncode != 0, "an empty run must not be green"
    assert result.outputs["archived"] == "0"
    assert result.outputs["config_error"] == "0", (
        "an empty run is not a configuration error and must not be reported as one"
    )


def test_symbols_are_trimmed_before_use(tmp_path: Path) -> None:
    """`AAPL, MSFT` is what an operator actually types into the dispatch form."""
    result = _run(tmp_path, symbols=f"AAPL, MSFT ,{NO_STRUCTURE_SYMBOL}",
                  rcs=dict(_SKIPPED))
    assert result.outputs["ran"] == "AAPL MSFT", result.outputs
    assert result.outputs["archived"] == "2"
