---
description: "Prüfe CI-Status aller offenen PRs und melde Merge-Readiness"
agent: "agent"
---
Prüfe den CI-Status aller offenen PRs im Repository skippALGO/skipp-algo in einem Durchlauf:

1. Liste alle offenen PRs: `gh pr list --json number,title,headRefName,mergeable,mergeStateStatus`
2. Für jeden PR: `gh pr checks <nr> --json name,state --jq '.[] | select(.state != "SUCCESS" and .state != "SKIPPED" and .state != "CANCELLED")'`
3. Melde pro PR:
   - **Grün**: "PR #NR — ✅ all green, merge-ready"
   - **Laufend**: "PR #NR — ⏳ <check-name> pending"
   - **Fehlgeschlagen**: "PR #NR — ❌ <check-name> failed" + letzte 10 Zeilen aus `gh run view <id> --log-failed`
4. Prüfe auch die letzten 3 Runs auf `main`: `gh run list --branch main --limit 3`
5. Fasse zusammen: wie viele merge-ready, wie viele pending, wie viele failed.

Antworte auf Deutsch. Keine Rückfragen — einfach ausführen.
