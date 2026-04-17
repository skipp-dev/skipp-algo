# WP-20 — Branch-Protection und PR-Disziplin

## Ist-Zustand (2026-04-17)

### Ruleset `skipp-algo` (ID 12576994)

| Eigenschaft | Wert |
|---|---|
| Ziel | Alle Branches (`~ALL`) |
| Enforcement | active |
| Regeln | `copilot_code_review` (push + draft) |
| Required Status Checks | **keine** |
| Pull-Request-Pflicht | **keine** |
| Force-Push-Schutz | **keiner** |

### Bypass-Akteure

- OrganizationAdmin
- RepositoryRole 2, 4, 5 (Maintain, Admin, Custom)
- Integration 29110, 262318, 946600, 1143301 (GitHub Actions / Bots)

### Offene PRs

| PR | Branch | Status | Bewertung |
|---|---|---|---|
| #12 | `docs/smc-unified-architecture-v5-4-final` | CI FAILURE (29.03.) | Docs-only; Inhalt ist in `smc_unified_target_architecture_v5_5_de.md` superseded. Kann geschlossen werden. |

### Merge-Praxis

Alle Commits seit WP-8 wurden direkt auf `main` gepusht. Automatisierte
Workflows (newsapi-refresh, library-refresh) pushen ebenfalls direkt.

---

## Empfohlene Schutzkonfiguration

Minimale Konfiguration für Solo-/Kleinteam-Betrieb in der Freeze-Exit-Phase.

### Regeln (zum bestehenden Ruleset hinzufügen)

1. **`pull_request`** — PRs für Merges in `main` erforderlich
   - Required approvals: `0` (Solo-Betrieb, Self-Merge erlaubt)
   - Dismiss stale reviews on push: `true`
   - Require last push approval: `false`

2. **`required_status_checks`** — CI muss grün sein
   - Checks: `validate` (aus Workflow `CI`)
   - Strict: `true` (Branch muss up-to-date mit base sein)

3. **`non_fast_forward`** — Force-Push-Schutz für `main`

### Bypass-Akteure (beibehalten)

Die bestehenden Bypass-Akteure (Integrations 29110, 262318, 946600,
1143301) müssen erhalten bleiben, damit automatisierte Workflows
(newsapi-refresh, library-refresh) weiterhin direkt auf `main` pushen
können.

### Scope-Einschränkung

Die Regeln `pull_request` und `required_status_checks` sollten nur für
den Default-Branch (`main`) gelten, nicht für `~ALL`. Entweder:
- Bestehenden Ruleset-Scope von `~ALL` auf `refs/heads/main` ändern, oder
- Neuen Ruleset nur für `main` anlegen und den bestehenden für `~ALL` belassen

Empfehlung: **Separater Ruleset für `main`**, damit Feature-Branches
ohne PR-Pflicht bleiben und der bestehende Copilot-Review-Ruleset
unverändert bleibt.

---

## Manuelle Umsetzung (GitHub UI)

Der aktuelle PAT hat keine Administration(write)-Berechtigung.
Die folgenden Schritte müssen manuell in der GitHub-UI durchgeführt werden.

### Schritt 1: Neuen Ruleset erstellen

1. Gehe zu **Settings → Rules → Rulesets → New ruleset → New branch ruleset**
2. Name: `main-protection`
3. Enforcement: `Active`
4. Target branches: **Add target → Include by pattern** → `main`

### Schritt 2: Bypass-Akteure konfigurieren

1. **Add bypass** → Organization Admin, Maintain, Admin roles
2. **Add bypass** → Alle bestehenden GitHub-App-Integrations (Actions, Dependabot, etc.)
3. Bypass mode: `Always`

### Schritt 3: Regeln aktivieren

1. ✅ **Restrict deletions**
2. ✅ **Require a pull request before merging**
   - Required approvals: `0`
   - Dismiss stale pull request approvals when new commits are pushed: ✅
3. ✅ **Require status checks to pass**
   - Add check: `validate` (Workflow: CI)
   - Require branches to be up to date: ✅
4. ✅ **Block force pushes**

### Schritt 4: Speichern

→ **Create** klicken.

### Schritt 5: PR #12 schließen

```
gh pr close 12 --comment "Superseded by smc_unified_target_architecture_v5_5_de.md"
```

---

## Empfohlener PR-Workflow für Freeze-Exit

```bash
# Feature-Branch erstellen
git checkout -b wp-XX/beschreibung

# Arbeiten, committen
git add . && git commit -m "fix(...): beschreibung (WP-XX)"

# Push und PR erstellen
git push -u origin wp-XX/beschreibung
gh pr create --title "fix(...): beschreibung (WP-XX)" --base main

# CI abwarten, dann Self-Merge
gh pr merge --squash --auto
```

---

## Restrisiko

- Bypass-Akteure (Admin, Integrations) können weiterhin direkt pushen.
  Das ist gewollt für automatisierte Workflows, aber ein bewusstes Risiko.
- Bei Solo-Betrieb mit 0 required approvals schützt die PR-Pflicht
  primär über den CI-Gate, nicht über Code-Review.
- `streamlit_terminal.py` hat 16% Coverage und ist der größte
  ungeschützte Risikotreiber für zukünftige Coverage-Regression.
