# Continue Fallback-Regel

## Wann gilt

- `edit_existing_file` oder `single_find_and_replace` hängt.
- Das Tool meldet einen Fehler wie `file does not exist`, `N lines pending`, `<<<<<<< HEAD` / Merge-Block im Output oder bleibt lange ohne Antwort.

## Was dann zu tun ist

1. **Edit-Versuch sofort abbrechen.** Keine Wiederholung mit dem gleichen diff.
2. **Datei atomisch neu schreiben** statt diff-basiert zu ersetzen. Erlaubte Methoden:
   - temporäres Python-Skript, das den neuen Inhalt erzeugt und `os.replace` verwendet.
   - Shell-Redirect: `cat > <pfad> << 'EOF' ... EOF`.
3. **Danach validieren:** `ruff check --fix` + relevante `pytest`-Tests.
4. **Temporäre Patch-Skripte sofort löschen** nach erfolgreicher Validierung.

## Besonders anwenden bei

- Dateien mit > 500 Zeilen.
- Dateien, die in der aktuellen Session bereits Editor-Probleme verursacht haben (z. B. `scripts/smc_signal_quality.py`).
