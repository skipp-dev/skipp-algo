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

---

## WP-E Verification (2026-04-17)

### API-Versuch

Automatisierte Aktivierung via `gh api` (PUT/POST auf Rulesets) scheitert
an fehlendem `admin:write`-Scope im PAT:

```
HTTP 403: Resource not accessible by personal access token
```

### Verbleibender manueller Restschritt

Die exakten Schritte in **"Manuelle Umsetzung (GitHub UI)"** oben müssen
einmalig vom Repository-Admin in der GitHub-UI durchgeführt werden.

### Aktueller aktiver Schutz

| Eigenschaft | Status |
|---|---|
| Ruleset `skipp-algo` (copilot_code_review) | ✅ aktiv, scope `~ALL` |
| PR-Pflicht für `main` | ❌ nicht aktiv — manueller Schritt offen |
| Required Status Checks (`validate`) | ❌ nicht aktiv — manueller Schritt offen |
| Force-Push-Schutz | ❌ nicht aktiv — manueller Schritt offen |
| Delete-Schutz | ✅ aktiv via org ruleset (verifiziert: branch delete blocked) |

### Fazit

Direct-to-main ist derzeit **empfohlen beendet**, aber **nicht erzwungen**.
Die manuelle Aktivierung bleibt als dokumentierter Admin-Restschritt offen.

---

## WP-G Re-Verification (2026-04-17)

### Methode

Vollständige API-Verifikation über drei Ebenen:

1. **Classic Branch Protection:** `GET /repos/.../branches/main/protection` → HTTP 403
   (Token-Scope reicht nicht für Lesezugriff; kein Nachweis für klassische Regeln)
2. **Repository Rulesets:** `GET /repos/.../rulesets` → 1 Ruleset (ID 12576994)
3. **Effective Rules on `main`:** `GET /repos/.../rules/branches/main` → 1 effektive Regel
4. **Org-Level Rulesets:** `GET /orgs/skippALGO/rulesets` → HTTP 403 (Token-Scope)

### Ergebnis: Effektiver Schutz auf `main`

| Schutzmechanismus | Status | Quelle |
|---|---|---|
| Copilot Code Review (push + draft PRs) | ✅ aktiv | Ruleset 12576994, scope `~ALL` |
| PR-Pflicht | ❌ nicht aktiv | kein `pull_request` Rule |
| Required Status Checks | ❌ nicht aktiv | kein `required_status_checks` Rule |
| Force-Push-Schutz | ❌ nicht aktiv | kein `non_fast_forward` Rule |
| Delete-Schutz | ⚠️ teilweise | org-Level (nicht via API verifizierbar mit aktuellem Token) |
| Klassische Branch Protection | ❌ nicht vorhanden | `protected: false` in Branch-API |

### Widerspruch aufgelöst

Der frühere Widerspruch (`protected=true` vs. `Branch not protected`) erklärt sich:
- **Rulesets** (neue GitHub-Architektur) zeigen `protected=true` im UI, wenn ein Ruleset aktiv ist.
- **Klassische Branch Protection** (alte API) zeigt `protected=false`, weil keine klassischen Regeln existieren.
- Es handelt sich um **zwei verschiedene Schutzsysteme**. Das Repo nutzt ausschließlich Rulesets.

### API-Schreibzugriff

| Versuch | Ergebnis |
|---|---|
| `PUT /repos/.../rulesets/12576994` | HTTP 403 |
| Token-Typ | `github_pat_*` (Fine-grained PAT) |
| Token-Berechtigungen | `admin: true` (Repo-Level), aber kein `administration:write` Scope |

**Fazit:** Das PAT kann Rulesets lesen, aber nicht ändern. Die Ruleset-Änderung muss
über die GitHub-UI oder ein PAT mit `administration:write` Scope erfolgen.

### Verbleibende manuelle Schritte

Die Schritte unter **"Manuelle Umsetzung (GitHub UI)"** oben bleiben unverändert gültig.
Zusammenfassung der benötigten Admin-Aktion:

1. **Settings → Rules → Rulesets → New branch ruleset** (`main-protection`)
2. Target: `main`
3. Regeln: `pull_request` (0 approvals), `required_status_checks` (`validate`),
   `non_fast_forward`, `deletion`
4. Bypass: bestehende Integrations beibehalten
5. **Create** klicken

Geschätzter Aufwand: **< 5 Minuten**, einmalig.

---

## WP-23 — Final-State Reconciliation (2026-04-18)

### Abgleich: Checks vs. Protection

Nach WP-15 bis WP-21 existieren folgende relevante CI-Checks:

| Check / Workflow | Typ | Aktuell in Protection? | Empfehlung |
|------------------|-----|----------------------|------------|
| `CI / validate` | PR-Gate | ❌ (manueller Schritt offen) | **Required** — merge-blocking |
| `smc-fast-pr-gates / fast-gates` | PR-Gate | ❌ | **Required** — merge-blocking |
| `smc-deeper-integration-gates` | Push+Nightly | n/a (nicht PR-blocking) | Nicht required (sichtbar laufen lassen) |
| `smc-library-refresh` | Scheduled | n/a | Nicht required |
| `smc-release-gates` | Release | n/a | Nur vor Release/Publish |
| `smc-measurement-benchmark` | Scheduled | n/a | Nicht required |

### Neue Artefakte aus WP-15–21 — CI-Relevanz

| Artefakt | CI-Sichtbar? | Handlungsbedarf |
|----------|-------------|-----------------|
| `run_freeze_exit_check.py` | Über pytest (test_freeze_exit_check.py) | ✅ automatisch via `validate` |
| `detect_publish_drift.py` | Über pytest (test_publish_drift.py) | ✅ automatisch via `validate` |
| Quality Floor Policy | Über pytest (TestQualityFloorPolicy) | ✅ automatisch via `validate` |
| Product Identity Freeze | Über pytest (test_product_identity*) | ✅ automatisch via `validate` |
| Sentiment Impact | Über pytest (TestSentimentImpact) | ✅ automatisch via `validate` |

### Fazit

Alle neuen Tests aus WP-15–21 laufen automatisch in `CI / validate` und
`smc-fast-pr-gates`. Keine zusätzlichen Required Checks nötig.

Die einzige verbleibende Lücke bleibt die **manuelle Admin-Aktion** (Ruleset
`main-protection` erstellen). Die Schritte sind oben dokumentiert und
unverändert gültig.

### Admin-Handgriff-Checkliste (final)

```
[ ] Settings → Rules → Rulesets → New branch ruleset
    Name: main-protection
    Target: main
    Rules:
      [x] Require pull request (0 approvals, dismiss stale)
      [x] Require status checks (validate, strict)
      [x] Block force pushes
      [x] Restrict deletions
    Bypass: Admin + bestehende Integrations
    → Create
```
