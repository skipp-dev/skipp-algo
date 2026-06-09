---
description: "Merge alle grünen PRs, löse Konflikte, adressiere Review-Kommentare"
agent: "agent"
---
Für jeden offenen PR in skippALGO/skipp-algo — in dieser Reihenfolge abarbeiten:

1. **CI prüfen**: `gh pr checks <nr>` — nur weitermachen wenn alle Checks grün (SUCCESS/SKIPPED)
2. **Review-Kommentare prüfen**: `gh api repos/skippALGO/skipp-algo/pulls/<nr>/comments --jq '.[].body'`
   - Falls ungelöste Kommentare: adressiere sie (Code-Fix + Push), warte auf neuen CI-Lauf
3. **Merge-Konflikte prüfen**: `gh pr view <nr> --json mergeable`
   - Falls CONFLICTING: `git fetch origin && git checkout <branch> && git merge origin/main`, Konflikte lösen, committen, pushen
   - Bei Konflikten in `docs/DECISIONS.md` oder `artifacts/experiments/`: immer `--theirs` (main) nehmen
4. **Mergen**: `gh pr merge <nr> --squash --admin --delete-branch`
5. **Nach jedem Merge**: `git checkout main && git pull --ff-only`

Regeln:
- KEINE Rückfragen — einfach mergen was grün ist
- Pinned Action SHAs NICHT ändern
- Falls ein PR nicht merge-ready ist: überspringen und Grund melden
- Am Ende: Zusammenfassung was gemergt wurde und was offen bleibt

Antworte auf Deutsch.
