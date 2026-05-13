# SMC Deep Review v6: Kritische Verifikation und Action Plan

Stand: 2026-04-12
Quelle: `smc_deep_review_v6.md`

## Zweck

Dieses Dokument prueft die wichtigsten Aussagen aus dem Deep Review v6 gegen
den aktuellen Repo-Stand auf `main`, trennt belastbare Befunde von zu starken
oder unpraezisen Schlussfolgerungen und leitet daraus einen umsetzbaren Action
Plan ab.

Es ersetzt den Deep Review nicht. Es ist die verifizierte Arbeitsgrundlage fuer
Code-, Ops- und Release-Entscheidungen.

## Kurzfazit

Der Hauptbefund des Reviews war richtig, der operative Status hat sich seitdem
aber verbessert:

- Der degradierte Enrichment-Zustand war real. Der aktuelle Baseline-Stand auf
  `main` ist jedoch wieder gesund: Die generierte Library zeigt jetzt
  `PROVIDER_COUNT = 3` und `STALE_PROVIDERS = ""`.
- Das Repo belegt, dass die Refresh-Workflow-Generierung die Secrets fuer FMP,
  Benzinga und NewsAPI.ai bereits an den Generator uebergibt. Fehlende oder
  ungueltige GitHub-Secrets bleiben plausibel, sind lokal aber nicht beweisbar.
- Die Review-Empfehlung `TRADINGVIEW_TOKEN setzen` ist in der aktuellen Form
  nicht belegt. Der Repo-Stand nutzt fuer den Technical-Fallback keinen
  TradingView-Token.
- Die Review-Annahme eines separaten NewsAPI-Key-Pfads ist derzeit nicht
  belegt. Sowohl der Live-Refresh als auch der Library-Refresh lesen
  `NEWSAPI_AI_KEY`.
- Zusaetzlich wurde ein echter Codefehler gefunden: Der angebliche
  TradingView-Technical-Fallback in `scripts/smc_provider_policy.py` war nicht
  unabhaengig, sondern rief intern den FMP-Fallback auf. Dieser Fehler wurde in
  diesem Change behoben.
- Der Hosted-Refresh ist inzwischen wieder end-to-end gruen, inklusive
  Readonly-Preflight, Publish und automatischem Push auf `main`.

## Verifizierte Findings

### V-1: Der degradierte Enrichment-Status war operativ belegt, ist aber nicht mehr der aktuelle Baseline-Stand

Historisch belegt durch:

- `pine/generated/smc_micro_profiles_generated.pine`
  - zuvor `PROVIDER_COUNT = 2`
  - zuvor `STALE_PROVIDERS = "benzinga,fmp,newsapi_ai,tradingview"`
  - damals standen Regime-/News-/Event-Risk-nahe Felder auf Default-Werten

Aktueller Stand:

- `pine/generated/smc_micro_profiles_generated.pine`
  - `PROVIDER_COUNT = 3`
  - `STALE_PROVIDERS = ""`
- Hosted-Run `smc-library-refresh` 24302933019 ist erfolgreich durchgelaufen.

Bewertung:

- Dieser Kernbefund des Reviews war zum Review-Zeitpunkt gerechtfertigt.
- Er beschreibt nicht mehr den heutigen Baseline-Zustand auf `main`.
- Der relevante Restpunkt ist jetzt Monitoring gegen Rueckfall, nicht mehr die
  unmittelbare Wiederherstellung der Baseline.

### V-2: Das Library-Workflow-Wiring fuer FMP, Benzinga und NewsAPI.ai ist vorhanden

Belegt durch:

- `.github/workflows/smc-library-refresh.yml`
  - `FMP_API_KEY`
  - `BENZINGA_API_KEY`
  - `NEWSAPI_AI_KEY`
  - `DATABENTO_API_KEY`
  werden im Generationsschritt explizit als `env` gesetzt.

Bewertung:

- Die Aussage `die Keys erreichen die Pipeline vermutlich nicht` ist zu grob.
- Was lokal belastbar ist: Das Workflow-Wiring existiert.
- Was lokal nicht beweisbar ist: Ob die GitHub-Secrets fehlen, leer sind,
  abgelaufen sind oder vom Provider abgewiesen werden.

### V-3: Die NewsAPI.ai-Divergenz ist real, aber der Review begruendet sie zu eng

Belegt durch:

- `.github/workflows/smc-live-newsapi-refresh.yml`
  exportiert `NEWSAPI_AI_KEY` explizit und erzwingt Nicht-Leere.
- `.github/workflows/smc-library-refresh.yml`
  setzt denselben Secret-Namen fuer die Library-Generierung.
- `scripts/generate_smc_micro_base_from_databento.py`
  uebergibt `newsapi_ai_key` in `resolve_domain("news", ...)`.

Bewertung:

- Die reine Secret-Pfad-Hypothese ist nicht belegt.
- Wahrscheinlicher ist eine Differenz im Codepfad, Timing, Cursor-State,
  Providerverhalten oder der Datenqualitaet zwischen Live-News-Bus und
  Library-Enrichment.

### V-4: Die TradingView-Secret-Empfehlung im Review ist falsch oder mindestens unbelegt

Belegt durch:

- `README.md` beschreibt TradingView fuer Technicals als `none — scraper`.
- Die Refresh-Workflow-Datei referenziert fuer Publish nur `TV_STORAGE_STATE`.
- `scripts/smc_provider_policy.py` referenziert fuer den Technical-Fallback
  keinen TradingView-Token.

Bewertung:

- `TRADINGVIEW_TOKEN` ist kein nachgewiesener Blocker im aktuellen Repo-Stand.
- Dieser Punkt sollte aus dem unmittelbaren Ops-Plan entfernt werden.

### V-5: Der Technical-Fallback war tatsaechlich falsch verdrahtet

Belegt durch:

- `scripts/smc_provider_policy.py`
  - `fetch_technical_tradingview()` verwendete vor diesem Change
    `terminal_fmp_technicals.fetch_fmp_technicals`
  - damit war der angebliche TradingView-Fallback weiterhin indirekt von
    `FMP_API_KEY` abhaengig

Bewertung:

- Das ist ein echter Codefehler, kein reines Ops-Problem.
- Er erklaert zwar nicht den gesamten Stale-Zustand, macht aber den
  Technical-Fallback objektiv schlechter als im Review beschrieben.

## Findings mit Korrekturbedarf

### K-1: `Nur ein naechster Schritt: Keys setzen` ist zu eng

Korrektur:

- Das Setzen der Keys bleibt Prioritaet 1.
- Es ist aber nicht die einzige sinnvolle Massnahme, weil mindestens ein
  echter Codefehler im Fallback-Pfad vorlag und behoben werden musste.

### K-2: `NewsAPI.ai Key-Pfad vereinheitlichen` ist aktuell nicht belegt

Korrektur:

- Nicht `Key-Pfad vereinheitlichen`
- Sondern `Library-NewsAPI-Failure-Reason explizit instrumentieren und gegen den Live-News-Pfad vergleichen` ### K-3: `TradingView Token setzen` ist kein verifizierter Action Item

Korrektur:

- Fuer Publish bleibt `TV_STORAGE_STATE` relevant.
- Fuer Technical-Fallback ist stattdessen der reale TradingView-Adapterpfad und
  dessen Verfuegbarkeit relevant.

## Bereits umgesetzt in diesem Change

### C-1: Technical-Fallback auf den echten TradingView-Adapter umgestellt

Geaendert in:

- `scripts/smc_provider_policy.py`

Wirkung:

- `fetch_technical_tradingview()` nutzt jetzt den echten
  `terminal_technicals.fetch_technicals`-Pfad.
- Wenn der TradingView-Adapter nicht verfuegbar ist, wird der Provider sauber
  als unavailable behandelt, statt still wieder auf FMP zurueckzufallen.

### C-2: Regressionstests fuer die Provider-Policy ergaenzt

Geaendert in:

- `tests/test_enrichment_provider_policy.py`

Abgesichert wird jetzt:

- realer TradingView-Adapterpfad fuer Technicals
- kein falscher FMP-Rueckkanal bei deaktiviertem TradingView-Adapter
- harter Fehlerpfad bei TradingView-Adapter-Error

### C-3: Hosted Refresh-, TradingView- und Push-Pfad wieder gruen

Geaendert in:

- `.github/workflows/smc-library-refresh.yml`
- `scripts/tv_preflight.ts`
- `automation/tradingview/lib/tv_shared.ts`

Verifiziert durch:

- Hosted-Run `smc-library-refresh` 24302933019

Wirkung:

- Readonly-Preflight findet gespeicherte TradingView-Skripte wieder stabil.
- Publish laeuft wieder durch.
- Der automatische Commit/PUSH-Pfad auf `main` funktioniert wieder reproduzierbar.

## Verifizierter Action Plan

## Phase 0: Sofort abgeschlossen

Ziel:

- Offensichtlichen Codefehler im Technical-Fallback beseitigen.

Exit-Kriterien:

- Technical-Policy-Regressionstests sind gruen.
- Provider-Policy weist keinen falschen FMP-Backchannel mehr als
  `tradingview` aus.

## Phase 1: Operative Enrichment-Readiness validieren

Status:

- Abgeschlossen am 2026-04-12.

Ziel:

- Die reale Ursache fuer `fmp`, `benzinga` und `newsapi_ai` als stale im
  Hosted-Run verifizieren.

Arbeitspakete:

- GitHub-Repository-Secrets fuer
  - `FMP_API_KEY`
  - `BENZINGA_API_KEY`
  - `NEWSAPI_AI_KEY`
  gegen echte Provider-Requests validieren.
- Einen manuellen `smc-library-refresh`-Run auf `main` starten.
- Das generierte Artefakt und `smc_refresh_evidence_summary.json` gegen
  `STALE_PROVIDERS` und Providerdiagnostik pruefen.

Exit-Kriterien:

- `PROVIDER_COUNT` ist gegenueber dem degradieren Stand gestiegen.
- `STALE_PROVIDERS` ist aktuell leer.
- Hosted-Run 24302933019 ist mit erfolgreicher Generierung, Readonly-Preflight,
  Publish und Push abgeschlossen.

## Phase 2: NewsAPI-Library-Divergenz nur bei Rueckfall instrumentieren

Status:

- Derzeit nicht erforderlich.

Ziel:

- Klar unterscheiden, ob NewsAPI.ai im Library-Pfad an Auth, Cursor-State,
  Datenqualitaet oder Laufzeitbedingungen scheitert.

Arbeitspakete:

- Providerfehler fuer den Library-Run maschinenlesbar in ein CI-Artefakt
  schreiben.
- Failure-Reason des NewsAPI-Library-Pfads mit dem Live-News-Workflow
  vergleichen.

Exit-Kriterien:

- Kein pauschales `stale`, sondern eine konkrete Failure-Class pro Domain.

## Phase 3: Enrichment erst nach stabiler Datenbasis erweitern

Status:

- Nicht blockiert, aber weiterhin als separater Folge-Track behandeln.

Ziel:

- Keine neuen Felder oder Regime-Erweiterungen auf einem noch degradieren
  Providerfundament aufbauen.

Gilt insbesondere fuer:

- `MARKET_PE_FORWARD`
- weitere Regime-/Macro-Modifier
- Score-/Vol-Regime-Aktivierung im Produktivpfad

Exit-Kriterien:

- Vorbedingung erreicht: stabiles Enrichment und frischer erfolgreicher Hosted-Run liegen vor.
- Neue Erweiterungen sollen trotzdem separat und nicht implizit aus diesem Incident heraus geplant werden.

## Priorisierung fuer die naechsten Schritte

1. Gruene Enrichment-Baseline ueber weitere Hosted-Runs beobachten und nur bei Rueckfall neu eroertern.
2. Wenn `newsapi_ai` erneut stale wird, Failure-Reason im Library-Pfad explizit instrumentieren.
3. Wenn `fmp` oder `benzinga` erneut stale werden, Provider-Response und Quota/Auth direkt im Hosted-Runner-Kontext pruefen.
4. KGV-/Regime-Erweiterungen jetzt als normalen Folge-Track planen, nicht mehr als Blocker-Rest aus diesem Incident.
