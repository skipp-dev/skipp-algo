#!/usr/bin/env python3
"""Fügt die je Shard aufgezeichneten Laufzeiten zu einer ``.test_durations`` zusammen.

``record-test-durations.yml`` misst in vier getrennten Prozessen, weil genau das
die Form der PR-Lane ist (``ci.yml``: ``--splits 4 --group N``, seriell). Jeder
Shard schreibt nur die Tests, die er selbst gefahren hat; erst die Vereinigung
ist die Datei, die ``pytest-split`` liest.

Warum das Zusammenfügen ein eigenes Skript ist und keine Zeile ``jq`` im
Workflow: es hat drei Weigerungen, die eine stille Fehlmessung verhindern, und
die gehören getestet, nicht in ein YAML-Feld.

1. **Fehlende Shard-Datei.** Fehlt einer von vier, deckt das Ergebnis ein
   Viertel der Suite nicht ab — und ``pytest-split`` gibt jedem unbekannten
   Test kommentarlos den MITTELWERT. Das Ergebnis sähe vollständig aus und wäre
   es nicht. Deshalb ``--expected-shards``.

2. **Leere Datei.** Ein Shard, der 0 Einträge schreibt, ist ein Werkzeugfehler,
   kein Befund (vgl. die Positivkontroll-Regel: ein leeres Ergebnis muss sich
   als leer BEWEISEN, nicht bloß so aussehen).

3. **Überlappung.** Zwei Shards dürfen denselben Test nicht kennen — täten sie
   es, wäre die Aufteilung nicht disjunkt, und die Messung träfe eine andere
   Zerlegung als die, die in ``ci.yml`` läuft.

Aufruf::

    python scripts/merge_shard_durations.py --shards /tmp/durations \\
        --expected-shards 4 --out .test_durations

Auf stdout landen ``key=value``-Zeilen für ``$GITHUB_OUTPUT`` (entries,
coverage, slowest, slowest_test) — dieselben Zahlen, die der PR-Text zeigt.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from scripts.smc_atomic_write import atomic_write_text

REPO_ROOT = Path(__file__).resolve().parent.parent


def _iter_test_files(root: Path) -> set[str]:
    """Jede gesammelte Testdatei, relativ zur Repo-Wurzel."""
    return {
        p.relative_to(root).as_posix()
        for p in (root / "tests").rglob("test_*.py")
        if "__pycache__" not in p.parts
    }


def merge_shards(shard_dir: Path, expected: int) -> dict[str, float]:
    """Vereinigt die Shard-Dateien und weigert sich bei jeder der drei Fallen."""
    files = sorted(shard_dir.glob("durations-*.json"))
    if len(files) != expected:
        names = ", ".join(f.name for f in files) or "(keine)"
        raise SystemExit(
            f"{len(files)} Shard-Dateien in {shard_dir}, erwartet {expected}: {names}. "
            "Eine fehlende Datei laesst pytest-split jedem Test dieses Viertels den "
            "MITTELWERT geben — das Ergebnis saehe vollstaendig aus und waere es nicht."
        )

    merged: dict[str, float] = {}
    for path in files:
        shard = json.loads(path.read_text(encoding="utf-8"))
        if not shard:
            raise SystemExit(
                f"{path.name} ist leer. Ein Shard ohne Eintraege ist ein Werkzeugfehler, "
                "kein Befund — die Messung ist unbrauchbar."
            )
        overlap = merged.keys() & shard.keys()
        if overlap:
            example = sorted(overlap)[:3]
            raise SystemExit(
                f"{path.name} teilt {len(overlap)} Tests mit einem frueheren Shard "
                f"(z. B. {example}). Die Aufteilung ist dann nicht disjunkt, und die "
                "Messung trifft eine andere Zerlegung als die in ci.yml."
            )
        merged.update(shard)
    return merged


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--shards", type=Path, required=True)
    parser.add_argument("--expected-shards", type=int, default=4)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    args = parser.parse_args(argv)

    merged = merge_shards(args.shards, args.expected_shards)

    test_files = _iter_test_files(args.repo_root)
    recorded_files = {key.split("::")[0] for key in merged}
    coverage = 100.0 * len(test_files & recorded_files) / len(test_files) if test_files else 0.0

    slowest_test, slowest = max(merged.items(), key=lambda kv: kv[1])

    # Atomar: ein abgebrochener Schreibvorgang darf keine halbe
    # `.test_durations` hinterlassen — die waere syntaktisch kaputt und
    # brächte jeden folgenden pytest-split-Lauf zum Scheitern.
    atomic_write_text(json.dumps(dict(sorted(merged.items())), indent=2) + "\n", args.out)

    print(f"entries={len(merged)}")
    print(f"coverage={coverage:.1f}")
    print(f"slowest={slowest:.2f}")
    print(f"slowest_test={slowest_test}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
