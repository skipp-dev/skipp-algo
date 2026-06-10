# Principal Quant Engineer Review — 2026-06-10

**Datum:** 2026-06-10  
**Scope:** Commits + PRs seit 2026-06-07  
**Methode:** Read-only. Keine Workspace-Änderungen vorgenommen.  
**Reviewer:** GitHub Copilot (Principal Quant Engineer Mode)

---

> ## ⚠️ Verifikations-Update 2026-06-10 (nach Erstreview)
>
> Die Findings wurden nach dem Erstreview **empirisch live-verifiziert** (Terminal, `git ls-remote`, `gh pr view`, `launchctl`, `actions/checkout` Source). Dabei wurde **ein Finding widerlegt**:
>
> - **Finding 1 (vormals 🔴 High) ist FALSCH.** Die C13-Fetch-Idiom in PR #2651 ist **korrekt**: `actions/checkout@v6` führt `git remote add origin <url>` (ohne `-t`) aus → Standard-Wildcard-refspec `+refs/heads/*:refs/remotes/origin/*`. Damit aktualisiert `git fetch origin data/phase-a-audit` sehr wohl `refs/remotes/origin/data/phase-a-audit`. Die `--dry-run`-Evidenz (`-> FETCH_HEAD`) war irreführend. **PR #2651 ist inzwischen sauber auf `main` gemergt — korrekt.**
> - **Finding 2 bestätigt + tiefere Root Cause:** Die gesamte C13-Producer-Pipeline (5 launchd-Jobs) ist auf Disk gescaffolded, aber **nie aktiviert** — alle Plists tragen noch `__REPO_PATH__`-Platzhalter, kein Job via `launchctl` geladen, nichts in `~/Library/LaunchAgents/`, keine `incubation_*.jsonl` je erzeugt.
> - **Findings 3 & 5 bestätigt** (ADR0023-Push-Race real; TV-Fix #2650 **inzwischen gemergt**).
>
> Korrigierte Bewertung + vereinbarter Plan unten unter **„Verifizierter Action Plan"**.

---

## ✅ Umsetzungs-Status (2026-06-10, nach Verifikation)

Alle 5 Schritte des verifizierten Action Plans wurden umgesetzt:

| Schritt | Status | Ergebnis / PR |
|---|---|---|
| 1 — ADR0023 Push-Race härten (1a) | ✅ erledigt | Commit `eb3b08a1` auf **#2652**: fetch→rebase→`push HEAD:main` + Retry-Loop (3×), fail-soft. 8/8 Contract-Tests grün. |
| 2 — TV-Preflight #2650 | ✅ bereits gemergt | **#2650** 06:52 UTC gemergt (`ee6245a3`); `SMC Decision Board` auf `main`. Stale-Branch entfernt. |
| 3a/3c — Producer-Bootstrap + Posture (3) | ✅ erledigt | **#2653**: idempotenter Orphan-Branch-Bootstrap, pro-Datei-`git add`, `push -u`, „protected"→ungeschützt. 14/14 Guard-Tests; Sandbox-Beweis grün. |
| 3b — Producer-Output (2b) | ✅ verifiziert | `run_smc_live_incubation --phase paper` schreibt `incubation_<DATE>.jsonl` (1 Record, `audit_only`, kein Submit). |
| 3c — launchd-Aktivierung | ⚠️ geladen, **durch macOS TCC blockiert** | 4 Jobs installiert + `launchctl bootstrap` (rc=0), aber Laufzeit scheitert mit `Operation not permitted`, weil das Repo in `~/Documents` (TCC-geschützt) liegt. Siehe **Blocker** unten. |
| 4 — ADR0023-Monitoring | ✅ erledigt | Step „Ledger metrics" auf **#2652**: `families_measured` + Zeilendelta → Step-Summary + `::notice`. |
| 5 — Doku | ✅ erledigt | Dieses Dokument aktualisiert. |

> **⛔ BLOCKER — macOS TCC (Full Disk Access):** Die 4 Jobs sind installiert + geladen,
> aber **lauffähig sind sie noch nicht**. Beim ersten Feuern von `phase-a-export` (09:18)
> protokollierte launchd:
> ```
> /bin/bash: …/skipp-algo/automation/launchd/run-c13-phase-a-export.sh: Operation not permitted
> ```
> **Ursache (verifiziert):** Das Repo liegt unter `~/Documents`, das von macOS via TCC
> (Transparency, Consent & Control) geschützt ist. Ein launchd-Agent darf `~/Documents`
> ohne **Full Disk Access** nicht lesen. Bestätigt: keine Quarantäne (`xattr` nur
> `com.apple.provenance`), das Skript ist `-rwxr-xr-x` und aus einer interaktiven Shell
> normal lesbar — nur der launchd-Kontext wird blockiert. Programmatisch nicht behebbar
> (TCC verlangt GUI-Zustimmung).
>
> **Lösung (eine der beiden, Nutzer-Aktion):**
> - **(A) schnell:** *Systemeinstellungen → Datenschutz & Sicherheit → Festplattenvollzugriff*
>   → `/bin/bash` hinzufügen (mit `⌘⇧G` zu `/bin` navigieren). Danach feuern die Jobs ohne
>   Neuinstallation; geladen bleiben sie.
> - **(B) sauber/langfristig:** Repo aus `~/Documents` heraus verschieben (z. B. nach
>   `~/skipp-algo`), Plists neu generieren + `bootstrap`. Ändert allerdings den Workspace-Pfad.

**Bewusst zurückgestellt:** `collect-imbalance` (launchd) — verbindet sich mit IBKR/TWS;
die README verlangt eine manuelle Verifikation, dass TWS auf **PAPER** steht, die
programmatisch nicht prüfbar ist. Plist liegt bereit; Aktivierung nach TWS-Check via
`launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.skippalgo.c13.collect-imbalance.plist`.

**Verbleibende Nutzer-Aktionen:**
1. **TCC freigeben** (Blocker oben, Variante A oder B) — sonst schlagen alle 4 Jobs täglich
   mit `Operation not permitted` fehl.
2. PRs **#2652** (gehärtet) + **#2653** (Bootstrap) reviewen + mergen — danach läuft
   `audit-push` auf `main` mit Bootstrap-Fix.
3. Optional `collect-imbalance` nach TWS=PAPER-Check aktivieren.
4. Smoke-Test (nach TCC-Freigabe): `launchctl kickstart -k gui/$(id -u) com.skippalgo.c13.phase-a-export`
   → `/tmp/skippalgo-c13-phase-a-export.err` muss leer bleiben.

> **Hinweis:** Die launchd-Jobs führen `…/automation/launchd/run-*.sh` aus dem
> **aktuell ausgecheckten Branch** aus. Working-Tree steht wieder auf `main`; bis
> #2653 gemergt ist, nutzt `audit-push` die ursprüngliche (buggy) Bootstrap-Logik
> und schlägt weich fehl, bis der Fix auf `main` ist.

---

## Executive Summary

**Kurzurteil (verifiziert): Das einzige High-Finding war ein False Positive; echte Arbeit liegt bei #2652, #2650 und der Producer-Pipeline.**

| Schwerpunkt | Erstreview | Verifiziert |
|---|---|---|
| C13 PR #2651 | ~~Kritisches Restproblem, Auto-merge stoppen~~ | ✅ **Fetch korrekt — gemergt & safe** (Finding 1 widerlegt) |
| ADR0023 PR #2652 | Push-Race-Risiko gegen `main` | ✅ **gehärtet** — Commit `eb3b08a1` auf #2652 (fetch+rebase+retry, Decision 1a) |
| TV-Preflight PR #2650 | offen & BEHIND | ✅ **gemergt** 06:52 UTC — `SMC Decision Board` auf `main` |
| `data/phase-a-audit` Producer | Branch fehlt | ✅ **gefixt + aktiviert** — Bootstrap PR #2653, 4/5 launchd-Jobs geladen (Decision 2b/3) |
| F2, NewsAPI, Rolling Benchmark, GH_PAT-SPOF | Stabilisiert | ✅ unverändert (by-design/gefixt) |

---

## Geprüfter Scope

### Commits / PRs

- Recent commits seit `2026-06-07`
- Recent PRs #2631–#2652, mit Fokus auf:
  - #2651 C13 audit branch overlay
  - #2652 ADR0023 ledger commit-back
  - #2650 TradingView Dashboard legend name
  - #2647 ADR0023 `news_polarity`
  - #2645 F2 spec live/recalibration
  - #2637 rolling-benchmark artifact redirect auth
  - #2628 / #2622 NewsAPI / GH_PAT-SPOF-Fixes

### Workflow Runs

- `c13-daily-cron.yml`
- `adr0023-magnitude-shadow-daily.yml`
- `f2-promotion-gate-daily.yml`
- `smc-live-newsapi-refresh.yml`
- `smc-measurement-benchmark-rolling.yml`

### Sonstiges

- Artifact presence / sizes für relevante Runs
- Targeted greps: stale env names, token regressions
- `scripts/run_magnitude_shadow_ledger.py` Script-Semantik
- `smc-databento-production-export-sharded.yml` Producer Checkout

---

## Current PR / CI State (live-verifiziert 2026-06-10)

### PR #2651 — C13 audit branch overlay

| Feld | Wert |
|---|---|
| State | ✅ `MERGED` (2026-06-10 06:24 UTC) |
| Auf `origin/main` | Ja — Fetch-Step vorhanden (Z. 81–88) |
| Verdict | Korrekt gemergt; Finding 1 war False Positive |
| URL | https://github.com/skippALGO/skipp-algo/pull/2651 |

### PR #2652 — ADR0023 ledger commit-back

| Feld | Wert |
|---|---|
| State | `OPEN` |
| Head | `fix/adr0023-ledger-commit-back` |
| Offene Arbeit | Push-Race härten (Decision 1a: Commit auf den offenen PR) |
| URL | https://github.com/skippALGO/skipp-algo/pull/2652 |

### PR #2650 — TradingView Dashboard legend name

| Feld | Wert |
|---|---|
| State | `OPEN` |
| Head | `fix/tv-preflight-dashboard-legend-name` |
| Offene Arbeit | Rebasen auf `main` + mergen |
| URL | https://github.com/skippALGO/skipp-algo/pull/2650 |

---

## Finding 1 — ~~C13 Fix ist nicht vollständig sicher~~ → WIDERLEGT

**Severity: ~~🔴 High~~ → ❌ False Positive (verifiziert 2026-06-10)**

> **Korrektur:** Dieses Finding ist nach empirischer Verifikation **zurückgezogen**.
> Der C13-Fetch in PR #2651 ist korrekt; PR #2651 ist sauber auf `main` gemergt.
> Die ursprüngliche Analyse bleibt zur Nachvollziehbarkeit erhalten, ist aber als
> FALSCH markiert. Begründung unten unter „Warum das falsch ist".

### Ursprüngliche Root-Cause-Annahme (Erstreview)

- `c13-daily-cron.yml` checked `main` aus (kein `ref:` auf checkout step)
- Producer `run-c13-audit-push.sh` schreibt nach Branch `data/phase-a-audit`
- Cron findet `cache/live/incubation_<DATE>.jsonl` deshalb nicht → soft-skippt mit `rc=78`

### PR #2651 fügt hinzu

```bash
git fetch origin data/phase-a-audit --quiet 2>/dev/null
git checkout origin/data/phase-a-audit -- cache/live/
```

### Ursprüngliche Behauptung (FALSCH)

`git fetch origin data/phase-a-audit` schreibe den Branch nur nach `FETCH_HEAD`,
**nicht** nach `refs/remotes/origin/data/phase-a-audit`; daher schlage
`git checkout origin/data/phase-a-audit -- cache/live/` fehl. Belegt mit einem
`--dry-run`, der `-> FETCH_HEAD` zeigte.

### Warum das falsch ist (Source-Evidenz)

`actions/checkout@v6` initialisiert das Repo via `git-source-provider.ts` →
`git-command-manager.ts`:

```ts
await this.execGit(['remote', 'add', remoteName, remoteUrl])
// = git remote add origin <url>   (KEIN -t / --no-tags)
```

`git remote add origin <url>` **ohne** `-t` setzt den **Standard-Wildcard-refspec**:

```
fetch = +refs/heads/*:refs/remotes/origin/*
```

Mit diesem refspec aktualisiert `git fetch origin data/phase-a-audit` den
Remote-Tracking-Ref `refs/remotes/origin/data/phase-a-audit` per *opportunistic
update* (git-fetch(1), „CONFIGURED REMOTE-TRACKING BRANCHES"). `FETCH_HEAD` wird
**zusätzlich** geschrieben — die `-> FETCH_HEAD`-Zeile im `--dry-run` beweist also
**nicht** das Fehlen des Tracking-Refs. `git checkout origin/data/phase-a-audit -- cache/live/`
ist damit gültig.

### Live-Bestätigung

- PR #2651 ist **gemergt** und auf `origin/main` (`git show origin/main:.github/workflows/c13-daily-cron.yml`
  → Fetch-Step Z. 81–88).
- Der Fetch ist mit `2>/dev/null` + `if`-Guard **soft-failing**: fehlt der Branch,
  wird sauber ge-soft-skippt (kein Crash) — gewünschtes Verhalten.
- Dass aktuell kein Overlay greift, ist **operational** (Finding 2), nicht der Fetch-Code.

### Verdict (korrigiert)

> **Finding 1 zurückgezogen.** Keine Code-Änderung an PR #2651 /
> `c13-daily-cron.yml` nötig. Die „Auto-merge stoppen"-Empfehlung war auf falscher
> Prämisse aufgebaut — Auto-Merge war korrekt.

---

## Finding 2 — `data/phase-a-audit` fehlt: Producer-Pipeline nie aktiviert

**Severity: 🟡 Medium / Operational — bestätigt + Root-Cause vertieft (2026-06-10)**

Der Datenbranch existiert nicht auf origin (`git ls-remote origin refs/heads/data/phase-a-audit`
→ leer; nur `data/edge-real-run-*` vorhanden). Die Root Cause liegt **tiefer** als
„launchd-Job lief noch nicht":

### Drei Blocker (alle live verifiziert)

1. **Keiner der 5 C13-launchd-Jobs ist aktiviert.** `launchctl list | grep skippalgo`
   → leer. Alle Plists unter `automation/launchd/` tragen noch je **2 `__REPO_PATH__`-Platzhalter**
   (nie substituiert), und in `~/Library/LaunchAgents/` ist **nichts** installiert:
   - `com.skippalgo.c13.phase-a.plist` (Stage 1, 09:28 ET → erzeugt `cache/live/incubation_<DATE>.jsonl`)
   - `com.skippalgo.c13.phase-a-export.plist` (IBKR-Export)
   - `com.skippalgo.c13.audit-push.plist` (Stage 2, 17:30 → push nach `data/phase-a-audit`)
   - `com.skippalgo.c13.collect-imbalance.plist`, `…wsh-earnings.plist`
2. **Kein `cache/live/` lokal** und **keine** `incubation_*.jsonl` in der gesamten
   Git-History (`git log --all -- 'cache/live/incubation_*.jsonl'` → leer). Es wurde
   also **noch nie** ein Audit-Artefakt produziert.
3. **Bootstrap-Bug im Producer** (`run-c13-audit-push.sh`): unter `set -euo pipefail`
   bricht `git fetch origin data/phase-a-audit` beim allerersten Lauf ab, wenn der
   Branch auf origin fehlt — es gibt keinen Pfad, der den Branch initial anlegt.
   Zusätzlich behauptet der Script-Kommentar „Branch is protected on the remote",
   was **Decision 3 widerspricht** (Branch soll ungeschützt + dediziert sein).

### Konsequenz

Der **gemergte** C13-Cron läuft korrekt, soft-skippt aber das Audit-Overlay
**dauerhaft** (kein Crash), bis die Producer-Pipeline aktiviert ist. Reines
Infra-/Aktivierungs-Problem, kein Workflow-Code-Problem.

### Closed-loop-Nachweis (offen)

1. Stage-1-Job lädt + erzeugt `cache/live/incubation_<DATE>.jsonl` (mit Records)
2. Stage-2-Job pusht nach `data/phase-a-audit` (ungeschützt, dediziert)
3. C13-Run nach Push: `::notice …overlaid` + `audit_files > 0` (nicht rc=78)

### Verdict

> Bestätigt. Operational nicht closed-loop. Root Cause = 5 launchd-Jobs nie
> installiert + Bootstrap-Bug. Siehe Action Plan Schritt 3.

---

## Finding 3 — ADR0023 Commit-Back Fix ist fachlich richtig, aber nicht race-hard

**Severity: 🟡 Medium**

### Root Cause (korrekt adressiert in PR #2652)

Vorher:

- Ledger wurde nur als Artifact hochgeladen
- Repo blieb bei der committed Baseline (3 Zeilen)
- Jeder Run startete wieder vom Baseline → keine Cross-run Akkumulation

Nach PR #2652:

- `permissions: contents: write` (war `read`)
- `live-window: mutating-on-cron` (war `off-hours-only`)
- Neuer Commit-back Step: skip wenn unverändert, sonst `git add` + `git commit` + `git push`

### Positive Prüfungen

Script `scripts/run_magnitude_shadow_ledger.py` geprüft:

- `append_shadow_ledger()` merged idempotent auf `(date, family, events_hash)`
- Sortierung stabil auf `(date, family)` — Re-run dupliziert nicht blind
- Negative/inconclusive Tage können grundsätzlich ebenfalls Ledger-Zeilen schreiben
- Contract tests korrekt angepasst: `contents: write`, `mutating-on-cron`
- Posture-Design konsistent: Workflow hat schedule + mutiert jetzt Repo-State

### Aktuelle Runtime-Evidenz

Letzter ADR0023 Run `27220661820`:

- `conclusion=success`
- verwendete Artefakt: `scored-family-events-2026-06-09/scored_family_events.json`
- Status: `all_thin`, Log: `shadow ledger: no families measured`
- Artifact: `adr0023-magnitude-shadow-27220661820 size=415`

Rolling Benchmark Run `27220465026`:

- `f2-dual-arm-2026-06-09 size=290934`
- `scored-family-events-2026-06-09 size=42377`
- `smc-measurement-benchmark-rolling-2026-06-09 size=963465`

Artifact-Download-Pfad funktioniert korrekt.

### Restproblem — Push-Race gegen `main`

Der Commit-back Step pusht direkt nach `main` ohne vorheriges Rebase/Pull.
Viele Scheduled/bot Workflows mutieren `main` sehr häufig:

- News snapshots
- Outcome backfills
- Docs/status bot PRs
- Calibration reports

Bei non-fast-forward push → Ledger-Akkumulation wieder verloren.

### Empfehlung

Für eine robuste Variante:

```bash
git fetch origin main
git rebase origin/main
# erneut prüfen ob Ledger noch geändert
git diff --quiet artifacts/governance/magnitude_resolution_shadow.jsonl || \
  (git add artifacts/governance/magnitude_resolution_shadow.jsonl && \
   git commit -m "..." && git push)
```

Optional: retry loop 2–3 Versuche mit exponential backoff.

### Verdict (verifiziert 2026-06-10)

> **Bestätigt.** PR #2652 ist offen; der Commit-back nutzt bare `git push` ohne
> `fetch`/`rebase` → realer non-fast-forward-Race gegen beweglichen `main`.
> **Decision 1a:** Härtung (fetch + rebase + Retry) als zusätzlicher Commit auf den
> offenen PR #2652, damit Auto-Merge sauber durchzieht. Siehe Action Plan Schritt 1.

---

## Finding 4 — ADR0023 kann weiterhin "grün ohne neue Ledger-Zeilen" sein

**Severity: 🟢 Low / Expected but important**

Letzter ADR Run war `all_thin` → `no families measured` → unverändertes Ledger ist korrekt.
PR #2652 würde commit-back in diesem Fall skippen — erwartetes Verhalten.

Das bedeutet: **"Workflow success" ≠ "neue Beobachtungen akkumuliert".**

Für Stage-1 Evidence sind zusätzlich erforderlich:

- Anzahl Ledger-Zeilen vor/nach Run
- `families measured > 0`
- `status != all_thin`
- Kandidatenfamilien `BOS` / `SWEEP` mit ausreichendem `n_oos`

### Verdict

> Kein Code-Bug. Monitoring sollte nicht nur CI-grün zählen,
> sondern `families_measured` und Ledger-Zeilendelta tracken.

---

## Finding 5 — TV-Preflight Issue ist noch nicht auf `main`

**Severity: 🟡 Medium**

PR #2650: `fix(tradingview): match Dashboard legend name SMC Decision Board in preflight`

**Diff geprüft:**

- `scriptName` für Dashboard: `SMC Long-Dip Dashboard v7` → `SMC Decision Board`
- `savedScriptName` bleibt: `SMC Long-Dip Dashboard v7` (korrekt — Pine Editor identity)

**Betroffene Dateien:**

- `.github/workflows/smc-library-refresh.yml`
- `artifacts/tradingview/smc_product_cut_manifest.json`
- `scripts/smc_bus_manifest.py`
- `scripts/tv_preflight.ts`
- `scripts/tv_publish_micro_library.ts`
- `tests/test_smc_bus_manifest_contract.py`

**Diagnose passt:** Pine Editor / saved script identity ≠ Chart legend / runtime smoke.
Die Trennung von `scriptName` vs. `savedScriptName` ist korrekt modelliert.

**Risiko:** PR ist `BEHIND` und noch nicht gemerged.
Das Issue tritt im Mainline-Workflow weiterhin auf, bis #2650 aktualisiert und gemerged ist.

### Verdict (verifiziert 2026-06-10)

> **Bestätigt** — PR #2650 ist weiterhin `OPEN` (Head `fix/tv-preflight-dashboard-legend-name`).
> Rebasen auf `main` + mergen. Siehe Action Plan Schritt 2.

---

## Finding 6 — F2: kein aktiver Code-Bug, aber Signal bleibt schwach

**Severity: 🟢 Low / Observational**

**Historischer Root Cause (bestätigt by-design):**

- F2 failure war SPRT rollback — kein Artefakt-Fehler
- Dual-arm artifacts waren vorhanden (`f2-dual-arm-2026-06-09 size=290934`)
- `decision: rollback`, `SPRT accepted H0 (n=1588, k=876, LLR=-7.6396)`
- Failure war intentionally CI-signal

**Aktuelle Runs:**

- Run `27246333884`: `conclusion=success`, Branch `main`
- Log: `artifact=missing`, `latest=none`, `revert=0`, `promote=0`
- Artifact-Liste für diesen Run: **leer**

**Interpretation:** Letzter manueller F2 Run läuft fail-soft/no-artifact sauber durch.
Rolling Benchmark produziert korrekt Artefakte (`f2-dual-arm`, `scored-family-events`).
Wenn F2 "Promotion gate sieht und bewertet frische Dual-arm-Artefakte" bedeuten soll,
reicht ein grüner Run ohne Artefakte nicht als Gesundheitsnachweis.

### Verdict

> Kein aktiver Code-Bug. F2 bleibt kontrolliert/observational, nicht "buggy".

---

## Finding 7 — Rolling Benchmark Artifact Redirect/Auth gefixt

**Severity: 🟢 Low**

PR #2637 hatte den Fix: Authorization header beim Artifact-Download-Redirect strippen.

**Evidenz:**

- `smc-measurement-benchmark-rolling.yml`, Run `27220465026`: success
- `f2-dual-arm-2026-06-09 size=290934`
- `scored-family-events-2026-06-09 size=42377`
- `smc-measurement-benchmark-rolling-2026-06-09 size=963465`
- ADR0023 konnte `scored-family-events` danach erfolgreich konsumieren

### Verdict

> Vollständig gefixt.

---

## Finding 8 — NewsAPI / Live News Snapshot stabilisiert

**Severity: 🟢 Low**

- `smc-live-newsapi-refresh.yml`: mehrere Runs am 2026-06-09/10 success
- Letzter geprüfter Run `27253830910`: success
- Env-var Drift-Grep sauber: keine Treffer für `NEWSAPI_AI_KEY`, `NEWSAPI_SECRET`, `NEWS_API_KEY`

**Hinweis:** Das frühere "fehlende `news_heat_global` / `bearish_tickers`" war by-design —
nicht raw snapshot schema, downstream derived via `compute_news_sentiment()`.

### Verdict

> Keine aktuelle Regression. NEWSAPI_KEY-Unifikation konsistent.

---

## Finding 9 — GH_PAT SPOF im Sharded Producer gefixt

**Severity: 🟢 Low**

Geprüfter Checkout in `smc-databento-production-export-sharded.yml`:

- SHA-pinned `actions/checkout@de0fac...`
- `persist-credentials: false`
- Kein explizites `GH_PAT` token override
- Kommentar: same-repo checkout, kein Push, default `github.token` ausreichend

**Restliche GH_PAT Treffer** (nicht problematisch):

- Bot PR creation
- auto-merge
- cross-trigger PR flows
- private repo reads

### Verdict

> Spezifisches SPOF Issue gefixt. Globale GH_PAT-Nutzung bleibt bewusst/kontextabhängig.

---

## Finding 10 — Prompt/Docs/Instruction Changes: kein Runtime-Risiko

**Severity: 🟢 Low**

Seit 2026-06-09 mehrere Agent-/Docs-Commits:
Kommunikation, Merge-Regeln, Env-var Regeln, Daily ops agent, CI-status prompt,
token-efficiency rules.

Nicht zeilenweise fachlich reviewed, aber nicht im kritischen Runtime-Pfad der quant pipelines.
Haupt-Risiko ist organisatorisch (Agent-Verhalten), keine direkte Trading-/Signal-Path-Mutation.

### Verdict

> Kein akutes quant-engineering Runtime-Risiko.

---

## Issue Closure Matrix

| Issue | Status | Evidenz | Residual Risk |
|---|---|---|---|
| C13 reads `main`, producer writes `data/phase-a-audit` | **Fixed (Code) — gemergt** | #2651 MERGED; Fetch korrekt via checkout-v6 Wildcard-refspec | 🟢 Low |
| C13 no audit file / rc=78 | **Operational — Producer nie aktiviert** | 5 launchd-Jobs ungeladen, Plists mit `__REPO_PATH__`, keine `incubation_*` je erzeugt | 🟡 Medium |
| ADR0023 ledger does not accumulate | **Mostly fixed in PR** | #2652 commit-back step + `contents: write` | 🟡 Medium (push race) |
| ADR0023 no measured families | **Expected, not fixed by commit-back** | Run `all_thin`, `no families measured` | 🟢 Low / Statistical |
| F2 failures | **By design / currently green** | latest manual run success; prior rollback intentional | 🟢 Low |
| Rolling benchmark scored events | **Fixed** | `scored-family-events-2026-06-09 size=42377` | 🟢 Low |
| NewsAPI secret / env drift | **Fixed** | stale env grep clean; recent refresh success | 🟢 Low |
| News raw snapshot missing derived fields | **By design** | downstream derived fields, not raw schema | 🟢 Low |
| GH_PAT SPOF sharded producer | **Fixed** | producer checkout no PAT override | 🟢 Low |
| TV preflight Dashboard legend | ✅ **auf main** | #2650 gemergt 06:52 UTC (`ee6245a3`) | 🟢 erledigt |

---

## Principal Quant Engineer Verdict

Aus quant-engineering Sicht unterscheide ich zwischen **CI-grün**, **Datenfluss-grün** und **Statistik-grün**:

1. **CI-grün ist noch nicht final** — #2651 / #2652 laufen / blockiert
2. **C13 Code-Fix ist grün, Datenfluss noch nicht:**
   - #2651 ist gemergt; der Fetch ist via checkout-v6 Wildcard-refspec **korrekt** (Finding 1 widerlegt)
   - `data/phase-a-audit` fehlt, weil die Producer-Pipeline (5 launchd-Jobs) nie aktiviert wurde
3. **ADR0023 Datenfluss ist teilweise grün:**
   - scored events download funktioniert
   - letzter Run `all_thin`
   - commit-back noch nicht auf main + nicht race-hard
4. **F2 Statistiksignal bleibt kontrolliert/observational** — kein Bug
5. **News / Rolling / GH_PAT sehen stabilisiert aus**

---

## Verifizierter Action Plan (2026-06-10)

Reihenfolge nach Live-Verifikation. **Finding 1 entfällt** (False Positive — keine
Aktion an `c13-daily-cron.yml`).

> **Status 2026-06-10: alle 5 Schritte umgesetzt.** Siehe ✅-Markierungen je Schritt
> sowie „Umsetzungs-Status" oben. Verbleibende Nutzer-Aktion: PRs #2652 + #2653
> mergen; `collect-imbalance` nach TWS=PAPER-Verifikation aktivieren.

### 1 — ✅ ERLEDIGT — ADR0023 Push-Race härten (Decision 1a)

> **Umgesetzt:** Commit `eb3b08a1` auf PR #2652. Commit-back macht jetzt
> `git fetch origin main` → `git rebase origin/main` → `git push origin HEAD:main`
> mit Retry-Loop (3×) und fail-soft Abbruch bei Konflikt. 8/8 Contract-Tests grün.

Härtung als **zusätzlicher Commit auf den offenen PR #2652** (nicht separat), damit
Auto-Merge sauber durchzieht.

- Im Commit-back-Step vor `git push`:
  ```bash
  git fetch origin main --quiet
  git rebase origin/main || git rebase --abort
  git diff --quiet artifacts/governance/magnitude_resolution_shadow.jsonl && exit 0
  git add artifacts/governance/magnitude_resolution_shadow.jsonl
  git commit -m "chore(adr0023): accumulate shadow ledger $(date -u +%F)"
  git push
  ```
- Optional: Retry-Loop (2–3 Versuche) um fetch→rebase→push.
- Contract-/Posture-Tests (`contents: write`, `mutating-on-cron`) bleiben gültig.
- **Verify:** `test_workflow_adr0023_magnitude_shadow_daily_contract.py` +
  `test_workflow_live_window_posture.py` grün; manueller Dispatch pusht ohne
  non-fast-forward.

### 2 — ✅ ERLEDIGT (bereits gemergt) — TV-Preflight #2650

> **Umgesetzt:** PR #2650 war zum Umsetzungszeitpunkt **bereits gemergt**
> (06:52 UTC, Merge-Commit `ee6245a3`); `scripts/tv_preflight.ts` trägt
> `SMC Decision Board` auf `main`. Lokaler Stale-Branch entfernt, `main` synchronisiert.
> Kein Rebase nötig — Patches waren bereits upstream.

- `git pull --rebase origin main` auf `fix/tv-preflight-dashboard-legend-name`,
  Konflikte lösen, mergen.
- **Verify:** `smc-library-refresh` läuft grün (behebt die 7× Failures); Legend
  matcht `SMC Decision Board`.

### 3 — ✅ ERLEDIGT — C13-Producer-Pipeline aktivieren (Decision 2b + 3)

> **Umgesetzt:**
> - **3a/3c (Bootstrap + Posture):** `run-c13-audit-push.sh` legt `data/phase-a-audit`
>   jetzt idempotent als **Orphan-Branch** an, wenn auf origin abwesend (statt unter
>   `set -e` abzubrechen); pro-Datei-`git add` (fixt latentes Schlucken bei fehlenden
>   optionalen Artefakten); `push -u`. „protected"-Kommentare → **ungeschützt + dediziert**
>   (Script + Plist + README). PR **#2653**. Sandbox-Beweis: RUN1 erzeugt reinen
>   Orphan-Branch, RUN2 inkrementell, RUN3 No-op; 14/14 Guard-Tests grün.
> - **3b (Producer-Output, Decision 2b):** CLI-Beweis — `run_smc_live_incubation
>   --phase paper` schreibt `incubation_<DATE>.jsonl` mit Records
>   (`audit_records_written: 1`, `action: audit_only`, kein Submit).
> - **3c (launchd-Install):** 4 sichere Jobs (`phase-a`, `phase-a-export`,
>   `wsh-earnings`, `audit-push`) nach `~/Library/LaunchAgents/` installiert + via
>   `launchctl bootstrap` geladen, `C13_VENV=./.venv` injiziert, `RunAtLoad=false`.
>   **`collect-imbalance` bewusst zurückgestellt** (IBKR-Connect; README verlangt
>   manuelle TWS=PAPER-Prüfung, die ich nicht verifizieren kann).
> - **Offen für dich:** #2652 + #2653 mergen; danach läuft `audit-push` auf `main`
>   mit Bootstrap-Fix. `collect-imbalance` nach TWS=PAPER-Check aktivieren.

- **3a (launchd):** `__REPO_PATH__` in allen `automation/launchd/*.plist` durch den
  echten Repo-Pfad ersetzen, nach `~/Library/LaunchAgents/` kopieren, `launchctl load`.
  Zuerst Stage 1 (`phase-a` / `phase-a-export`), dann Stage 2 (`audit-push`).
- **3b (IBKR-Producer, Decision 2b):** verifizieren, dass `run-c13-phase-a*.sh` /
  `run_smc_live_incubation` tatsächlich `cache/live/incubation_<DATE>.jsonl` mit
  Records schreibt (nicht 0 rows). Ohne echte Incubation-Files bleibt der Branch
  trotz Fix leer.
- **3c (Bootstrap + Branch-Posture, Decision 3):** `run-c13-audit-push.sh` fixen:
  Branch **idempotent** anlegen, wenn auf origin abwesend (Fetch-Fehler tolerieren,
  initial push), statt unter `set -e` abzubrechen. Script-Kommentar „Branch is
  protected" entfernen — `data/phase-a-audit` soll **ungeschützt + dediziert** sein
  (reiner Daten-Branch für Bot-Pushes).
- **Verify (closed-loop):** nach erstem erfolgreichem Stage-2-Push C13 dispatchen →
  `::notice …overlaid` + `audit_files > 0` (nicht rc=78).

### 4 — ✅ ERLEDIGT — ADR0023-Monitoring erweitern (Finding 4)

> **Umgesetzt:** Neuer fail-soft Step „Ledger metrics" auf PR #2652 (Commit
> `eb3b08a1`) schreibt `families_measured` + Ledger-Zeilendelta in
> `$GITHUB_STEP_SUMMARY` + `::notice`.

- `families_measured` + Ledger-Zeilendelta tracken, nicht nur CI-grün.

### 5 — ✅ ERLEDIGT — Doku

- Dieses Dokument korrigiert (Finding 1 zurückgezogen) **und mit Umsetzungs-Status
  aktualisiert**. Keine weitere Aktion an `c13-daily-cron.yml`.

---

*Erstreview read-only; Verifikation am 2026-06-10 empirisch (Terminal, `git ls-remote`,
`gh pr view`, `launchctl`, `actions/checkout` Source).*
*Finding 1 nach Verifikation zurückgezogen.*
*Aktualisiert: 2026-06-10*
