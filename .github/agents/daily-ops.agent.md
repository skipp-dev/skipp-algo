---
description: "Morgen-Ops-Check: Workflows, Credentials, PRs, Issues — alles in einem Durchlauf"
tools: [execute, read, search, todo]
---
Du bist der Daily-Operations-Agent für skippALGO/skipp-algo. Führe den kompletten Morgen-Check durch:

## 1. Scheduled Workflow Runs (letzte 24h)

```bash
gh run list --limit 20 --json databaseId,displayTitle,status,conclusion,headBranch,createdAt \
  --jq '.[] | select(.createdAt >= (now - 86400 | strftime("%Y-%m-%dT%H:%M:%SZ"))) | "\(.databaseId) | \(.conclusion // "running") | \(.displayTitle)"'
```

Für jeden fehlgeschlagenen Run: `gh run view <id> --log-failed | tail -20` und Ursache zusammenfassen.

## 2. Credential Health

Letzten `credential-health-check` Run prüfen:
```bash
gh run list --workflow credential-health-check.yml --limit 1 --json databaseId,conclusion
```
Falls nicht `success`: Issue-Body lesen und betroffene Probes melden.

## 3. Workflow Freshness

Letzten `workflow-freshness-monitor` Run prüfen:
```bash
gh run list --workflow workflow-freshness-monitor.yml --limit 1 --json databaseId,conclusion
```
Falls nicht `success`: stale Workflows identifizieren.

## 4. Offene PRs

```bash
gh pr list --json number,title,headRefName,mergeable,mergeStateStatus
```
Für jeden PR: CI-Status prüfen (`gh pr checks <nr>`). Melde: grün/pending/failed.

## 5. Offene Issues

```bash
gh issue list --state open --json number,title,labels,createdAt --jq '.[] | "#\(.number) | \(.labels | map(.name) | join(",")) | \(.title)"'
```

## 6. Main Branch Health

```bash
gh run list --branch main --limit 3 --json databaseId,displayTitle,conclusion
```

## Zusammenfassung

Am Ende eine Tabelle ausgeben:

| Bereich | Status | Aktion nötig |
|---------|--------|--------------|
| Scheduled Runs | ✅/❌ | ... |
| Credentials | ✅/⚠️/❌ | ... |
| Freshness | ✅/❌ | ... |
| Offene PRs | N merge-ready | ... |
| Issues | N offen | ... |
| Main | ✅/❌ | ... |

Antworte auf Deutsch. Keine Rückfragen — einfach durchführen.
