# SMC Deep Review v6: Kritische Verifikation und Action Plan

Stand: 2026-04-11
Quelle: `smc_deep_review_v6.md`

## Zweck

Dieses Dokument prueft die wichtigsten Aussagen aus dem Deep Review v6 gegen
den aktuellen Repo-Stand auf `main`, trennt belastbare Befunde von zu starken
oder unpraezisen Schlussfolgerungen und leitet daraus einen umsetzbaren Action
Plan ab.

Es ersetzt den Deep Review nicht. Es ist die verifizierte Arbeitsgrundlage fuer
Code-, Ops- und Release-Entscheidungen.

## Kurzfazit

Der Hauptbefund des Reviews ist richtig, aber die Root-Cause-Ebene muss
praeziser formuliert werden:

- Der degradierte Enrichment-Zustand ist real. Die aktuell generierte Library
  zeigt `STALE_PROVIDERS = "benzinga,fmp,newsapi_ai,tradingview"` und laeuft
  fuer viele Kontexte auf Defaults.
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

## Verifizierte Findings

### V-1: Der degradierte Enrichment-Status ist operativ belegt

Belegt durch:

- `pine/generated/smc_micro_profiles_generated.pine`
  - `PROVIDER_COUNT = 2`
  - `STALE_PROVIDERS = "benzinga,fmp,newsapi_ai,tradingview"`
  - Regime-/News-/Event-Risk-nahe Felder stehen auf Default-Werten

Bewertung:

- Dieser Kernbefund des Reviews ist voll gerechtfertigt.
- Der operative Mehrwert des Systems ist aktuell auf Databento plus den noch
  lebenden Teilpfad reduziert.

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
- Sondern `Library-NewsAPI-Failure-Reason explizit instrumentieren und gegen den
  Live-News-Pfad vergleichen`

### K-3: `TradingView Token setzen` ist kein verifizierter Action Item

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

## Verifizierter Action Plan

## Phase 0: Sofort abgeschlossen

Ziel:

- Offensichtlichen Codefehler im Technical-Fallback beseitigen.

Exit-Kriterien:

- Technical-Policy-Regressionstests sind gruen.
- Provider-Policy weist keinen falschen FMP-Backchannel mehr als
  `tradingview` aus.

## Phase 1: Operative Enrichment-Readiness validieren

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

- `PROVIDER_COUNT` steigt gegenueber dem degradieren Stand.
- `STALE_PROVIDERS` verliert mindestens die durch reale Secrets reparierten
  Domains.

## Phase 2: NewsAPI-Library-Divergenz instrumentieren, falls Phase 1 nicht reicht

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

Ziel:

- Keine neuen Felder oder Regime-Erweiterungen auf einem noch degradieren
  Providerfundament aufbauen.

Gilt insbesondere fuer:

- `MARKET_PE_FORWARD`
- weitere Regime-/Macro-Modifier
- Score-/Vol-Regime-Aktivierung im Produktivpfad

Exit-Kriterien:

- Erst nach stabilem Enrichment und einem frischen erfolgreichen Hosted-Run.

## Priorisierung fuer die naechsten Schritte

1. Hosted-Run mit verifizierten Secrets ausfuehren und `STALE_PROVIDERS` neu
   messen.
2. Wenn `newsapi_ai` weiter stale bleibt, Failure-Reason im Library-Pfad
   explizit instrumentieren.
3. Wenn `fmp` weiter stale bleibt, Provider-Response und Quota/Auth direkt
   gegen den Hosted-Runner-Kontext pruefen.
4. KGV-/Regime-Erweiterungen erst nach gruenem Enrichment-Baseline-Run planen.
