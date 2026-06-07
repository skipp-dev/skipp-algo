# Guard-Test-Taxonomie und gemeinsamer AST-Korpus

Dieses Repo hat eine grosse Menge an "Guard"-Tests unter `tests/` — kleine
AST-basierte Tripwires, die Regressionen gegen reale Vorfaelle festzurren
(z. B. tote `setup-python`-Versionen, schwache Hashes ohne
`usedforsecurity=False`, `open()` ohne `encoding=`). Die Coverage ist
gewollt: jede Regel kodiert eine Lektion. Was historisch gewuchert ist, sind
**acht verschiedene Namens-Suffixe fuer im Kern dieselbe Idee**. Dieses
Dokument definiert die Suffixe, gibt eine Entscheidungsregel und beschreibt
den gemeinsamen AST-Korpus-Cache, den neue Guards verwenden sollen.

## Suffix-Bedeutungen (Ist-Zustand)

| Suffix | Bedeutung | Fehlschlag, wenn ... |
| --- | --- | --- |
| `_pin` | Friert einen exakten Wert/Ort ein (Anzahl oder Zeilennummern). | der eingefrorene Fakt driftet. |
| `_ledger` | Explizit aufgezaehltes Inventar bekannter Vorkommen (pro Datei/Ort). | ein Eintrag neu/entfernt/verschoben ist. |
| `_budget` | Numerische Obergrenze (`<= N`) fuer ein Muster. | die Grenze ueberschritten wird. |
| `_discipline` | Erzwingt eine Coding-Regel ueberall (z. B. `encoding=`-Pflicht). | irgendein Verstoss existiert. |
| `_invariant` | Eigenschaft, die immer gelten muss (z. B. `Thread(daemon=...)`). | die Eigenschaft irgendwo verletzt ist. |
| `_contract` | Strukturpruefung eines konkreten Artefakts (z. B. Workflow-YAML). | das Artefakt von der erwarteten Form abweicht. |
| `_guard` | Generischer Sammelbegriff fuer einen Tripwire. | (uneinheitlich.) |
| `_posture` | Buendel zusammengehoeriger Security-/Qualitaets-Checks. | irgendein Check im Buendel bricht. |

Zusatzform `_zero_surface`: Spezialfall von `_discipline` — behauptet **null**
Vorkommen eines Musters (z. B. kein `eval`, kein `pickle`, kein
`verify=False`).

## Entscheidungsregel (Soll-Zustand: 4 kanonische Kategorien)

Die acht Suffixe lassen sich verlustfrei auf vier Kategorien abbilden. Fuer
**neue** Guards bitte nur diese vier verwenden:

- **`_pin`** — exakter, eingefrorener Fakt oder aufgezaehltes Inventar.
  Absorbiert das alte `_ledger` (ein Ledger ist ein Pin auf eine Liste).
  Nutzen, wenn ein bekanntes Restvorkommen Zeile fuer Zeile festgehalten
  werden soll.
- **`_budget`** — numerische Obergrenze, die nach unten gezurrt wird. Nutzen,
  wenn Restvorkommen schrittweise abgebaut werden (Ratchet), aber noch nicht
  null sind.
- **`_discipline`** — Null-Toleranz-Regel ueber den ganzen Code. Absorbiert
  `_invariant`, `_zero_surface`, `_posture` und das generische `_guard`.
  Nutzen, wenn ein Muster ab jetzt nirgends mehr auftauchen darf.
- **`_contract`** — Form-/Strukturpruefung eines einzelnen Artefakts (Workflow,
  Manifest, Schema). Eigene Kategorie, da nicht code-weit, sondern
  artefakt-lokal.

Faustregel: *Exakter Wert?* → `_pin`. *Obergrenze?* → `_budget`. *Regel
ueberall?* → `_discipline`. *Form eines Artefakts?* → `_contract`.

Bestehende Dateien werden **nicht** umbenannt (sie sind in CI-Fast-Gates,
`tests/_fast_inventory.py` und Coverage-Guards namentlich verdrahtet — ein
Rename braeuchte koordinierte Folgeaenderungen). Die Regel gilt fuer Neuzugaenge
und schrittweise Konsolidierung.

## Gemeinsamer AST-Korpus-Cache (`tests/_guard_corpus.py`)

Jeder Guard fand und parste den Quellbaum frueher selbst. Bei parametrisierten
Ledgern wurde dadurch der gesamte Korpus **pro Parameterfall** neu geparst —
der Hauptgrund fuer die langsame Guard-Suite. `tests/_guard_corpus.py` stellt
einen prozessweiten Cache bereit, der jede Datei **einmal** liest und parst
(Schluessel: Pfad + `mtime` + Groesse, sodass Edits korrekt invalidieren).

API:

- `parse_module(path) -> ast.Module | None` — geteilter, gecachter AST.
  Gibt `None` zurueck bei fehlender, nicht dekodierbarer oder syntaktisch
  kaputter Datei.
- `read_source(path) -> str | None` — gecachter Quelltext (z. B. fuer
  Zeilen-Snippets).
- `iter_py_files(exclude_dirs, *, root=None) -> list[Path]` — sortierte
  `*.py`-Liste, ueberspringt Pfade mit ausgeschlossenen Komponenten.
- `repo_root() -> Path` — Repo-Wurzel.

### Vertrag

- Der zurueckgegebene Baum wird **schreibgeschuetzt geteilt**. Guards duerfen
  nur `ast.walk` o. ae. lesen, **niemals** Knoten mutieren.
- Datei-*Findung* bleibt Sache des einzelnen Guards (jeder Guard hat seinen
  eigenen Scope/`_DIR_EXCLUDE`). Zentralisiert ist nur das *Parsen*.
- Fehlerfaelle liefern `None` — Aufrufer pruefen `if tree is None: continue`.

### So schreibt man einen Guard

```python
from tests._guard_corpus import parse_module

def _scan() -> dict[str, int]:
    out: dict[str, int] = {}
    for path in _iter_first_party_py():   # eigener Scope des Guards
        tree = parse_module(path)
        if tree is None:
            continue
        out[path.name] = sum(1 for n in ast.walk(tree) if _is_hit(n))
    return out
```

Wird `_scan()` von mehreren Tests oder Parameterfaellen aufgerufen, zusaetzlich
`@functools.cache` darueber setzen — dann laeuft die Sammlung genau einmal und
alle Faelle teilen sich das Ergebnis (Resultat nur lesend verwenden).

### Wirkung

Migration der schwersten Ledger auf den Cache senkte z. B. das
weak-hash-Trio von 28,84s auf 4,53s (6,4x) bei identischer Pass-Zahl. Der
Gewinn ist im vollen Suite-Lauf aggregiert: der Korpus wird einmal geparst und
von allen migrierten Guards geteilt.
