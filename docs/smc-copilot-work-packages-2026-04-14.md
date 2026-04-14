# SMC Copilot Work Packages — 2026-04-14

Stand: 2026-04-14  
Repo-Basis: `main` bei `37f5c6d1`  
Referenzreview: [smc-owner-review-2026-04-14.md](smc-owner-review-2026-04-14.md)

## Zweck

Dieses Dokument uebersetzt den Owner-Review in konkrete, fuer einen sehr guten
Coding Agent direkt umsetzbare Arbeitspakete. Die Pakete sind nicht als lose
Ideen formuliert, sondern als klare Execution-Slices.

## Prioritaet 1 — Trust Layer auf Mainline-Surfaces

### Arbeitspaket 1: Live-Trust-Summary in Core und Dashboard

**Ziel**

Die Hauptflaechen sollen nicht nur Signale zeigen, sondern sofort auch
Vertrauensniveau, Hauptblocker und Daten-/Provider-Stabilitaet kommunizieren.

**Fachlicher Grund**

Die Suite misst Qualitaet, Degradation und Provider-Zustand bereits im
Bundle-/Evidence-Pfad, kommuniziert diese Wahrheit aber noch nicht hart genug
auf der Live-Surface.

**Technische Stossrichtung**

- Trust-/Health-relevante Felder aus dem Bundle in Dashboard- und Pine-Payloads
  sichtbar machen
- Core-Hero-Text um `trust_state`, `main_blocker`, `provider_state` erweitern
- Dashboard-Decision-Brief um kompakte Trust-/Data-Integrity-Zeile erweitern

**Betroffene Schichten**

- [smc_integration/service.py](../smc_integration/service.py)
- [SMC_Core_Engine.pine](../SMC_Core_Engine.pine)
- [SMC_Dashboard.pine](../SMC_Dashboard.pine)
- relevante Payload-/Contract-Tests

**Abnahmekriterien**

- Nutzer sieht in Core und Dashboard sofort Hauptaussage, Hauptblocker und
  Vertrauensniveau
- Trust-Anzeige faellt bei fehlenden oder degradierten Inputs nicht still auf
  "gut" zurueck

**Tests / Nachweise**

- Payload-Regressionstests
- [tests/test_tradingview_decision_first_ui.py](../tests/test_tradingview_decision_first_ui.py)
  erweitern
- neue Bundle-/Dashboard-Contract-Assertions

**Erwarteter Produktnutzen**

Mehr Vertrauen, klarere Entscheidung und staerker wahrnehmbare Premium-
Qualitaet.

### Arbeitspaket 2: Trust-Tier aus Measurement- und Runtime-Wahrheit ableiten

**Ziel**

Ein einfaches, bounded Trust-Tier soll Bundle und Mainline-Surfaces speisen.

**Fachlicher Grund**

Die Einzelinformationen zu Scoring, Provider-Zustand, Frische und Evidence sind
vorhanden, aber nicht in eine klare Nutzerwahrheit verdichtet.

**Technische Stossrichtung**

- kleine Python-Seite zur Verdichtung auf `high`, `guarded`, `degraded`,
  `insufficient`
- Inputs aus Measurement-Summary, `meta_domain_diagnostics`, Provider-Health
  und Staleness kombinieren

**Betroffene Schichten**

- [smc_integration/service.py](../smc_integration/service.py)
- ggf. [smc_integration/release_policy.py](../smc_integration/release_policy.py)
- Bundle-/Snapshot-Contract-Tests

**Abnahmekriterien**

- Trust-Tier ist deterministisch, begruendet und ohne Shadow Logic
- degradierte Daten fuehren zu sichtbarer Herabstufung

**Tests / Nachweise**

- neue Unit-Tests fuer Tier-Ableitung
- Integrationstest ueber Snapshot-Bundle

**Erwarteter Produktnutzen**

Klarere Nutzerfuehrung und bessere Uebersetzung interner Reife in sichtbare
Wertigkeit.

## Prioritaet 2 — Setup- und Onboarding-Reibung reduzieren

### Arbeitspaket 3: BUS-Binding-Preflight fuer Companion- und Strategy-Flows

**Ziel**

Fehlverdrahtungen zwischen Core, Dashboard und Strategy sollen vor Live-Nutzung
frueh und klar erkannt werden.

**Fachlicher Grund**

Operator-only Bindings sind sinnvoll, aber fuer Produktwirkung und Supportkosten
zu teuer, wenn Fehler erst spaet sichtbar werden.

**Technische Stossrichtung**

- Manifest-gestuetzte Erwartungslisten fuer Bindings nutzen
- Preflight um explizite Companion-/Strategy-Binding-Pruefung erweitern
- Reports mit klaren Fehlstellen statt generischem Failure ausgeben

**Betroffene Schichten**

- [scripts/smc_bus_manifest.py](../scripts/smc_bus_manifest.py)
- TradingView-Preflight-Skripte
- Workflow-/Preflight-Tests

**Abnahmekriterien**

- Binding-Drift wird als klarer, lokalisierbarer Fehler gemeldet
- Dashboard und Strategy koennen nicht still halbverdrahtet gruen wirken

**Tests / Nachweise**

- Preflight-Tests
- Manifest-Contract-Tests

**Erwarteter Produktnutzen**

Weniger Onboarding-Reibung, weniger Supportstress, hoehere Reproduzierbarkeit.

### Arbeitspaket 4: Mainline-Install-/Setup-Runbook auf echten Standardpfad reduzieren

**Ziel**

Ein einziges klares Setup fuer Core + Dashboard + Strategy statt verteiltem
Operatorwissen.

**Fachlicher Grund**

Ein Premium-Produkt darf im Kernpfad nicht wie ein Expertensetup wirken.

**Technische Stossrichtung**

- Doku und Manifest auf einen kanonischen Mainline-Setup-Pfad zuspitzen
- optional standardisierte Export-/Import-Snippets fuer Bindings ableiten

**Betroffene Schichten**

- Docs
- Manifest
- Runbook-/Validation-Doku

**Abnahmekriterien**

- ein neuer Operator findet genau einen empfohlenen Setup-Pfad
- Companion-/Legacy-Wissen verunreinigt den Mainline-Einstieg nicht

**Tests / Nachweise**

- Doku-Konsistenzpruefung
- evtl. README-/Runbook-Index-Update

**Erwarteter Produktnutzen**

Mehr Wertigkeit und geringere mentale Einstiegskosten.

## Prioritaet 3 — Measurement von soft zu relevanterer Governance entwickeln

### Arbeitspaket 5: Erste harte Measurement-Shadow-Schwellen

**Ziel**

Ein kleiner Satz klarer Qualitaetsregressionen soll Releases kuenftig blockieren
koennen.

**Fachlicher Grund**

Die Measurement-Lane ist zu wichtig, um dauerhaft nur advisory zu bleiben.

**Technische Stossrichtung**

- wenige Kernmetriken identifizieren: z. B. Event-Coverage, kalibrierte
  Brier-/ECE-Verschlechterung, fehlende Family-Coverage
- Optionalitaet beibehalten, aber Promotion-Pfad zu blocking sauber einziehen

**Betroffene Schichten**

- [smc_integration/release_policy.py](../smc_integration/release_policy.py)
- [scripts/run_smc_release_gates.py](../scripts/run_smc_release_gates.py)
- Gate-Evidence-/Release-Tests

**Abnahmekriterien**

- klar definierte Degradationsarten koennen blocking werden
- keine Promotion von Messrauschen zu hartem Gate

**Tests / Nachweise**

- Regressionstests mit Baseline-Vergleich
- Release-Gate-Script-Tests

**Erwarteter Produktnutzen**

Mehr Signaldisziplin und weniger falsche Sicherheit im Release-Prozess.

### Arbeitspaket 6: Measurement-Empfehlung sichtbar in Release- und Bundle-Wahrheit

**Ziel**

Measurement soll nicht nur Artefakt sein, sondern eine klare Empfehlung liefern,
ob ein Pair/Regime als vertrauenswuerdig oder nur beobachtbar gilt.

**Fachlicher Grund**

Es fehlt noch die direkte Uebersetzung von empirischer Bewertung in eine
sichtbare Betriebs- und Produktwahrheit.

**Technische Stossrichtung**

- kompakte `quality_recommendation` oder `quality_guardrail`-Felder ableiten
- Release-Reports und Snapshot-Bundle um diese Kurzentscheidung anreichern

**Betroffene Schichten**

- Measurement-Evidence
- Release-Gates
- Integration-Service

**Abnahmekriterien**

- Empfehlung ist maschinenlesbar, begruendet und konsistent
- keine neue Shadow Logic zwischen Evidence und Nutzerflaechen

**Tests / Nachweise**

- Unit- und Integrationstests fuer Empfehungsableitung

**Erwarteter Produktnutzen**

Messbare Qualitaet wird zu sichtbarer Produktwahrheit.

## Prioritaet 4 — Publish-/Recovery-Kette weiter entdramatisieren

### Arbeitspaket 7: Publish-Recovery-State explizit modellieren

**Ziel**

Teilfehler im TradingView-Publish sollen noch klarer in wiederaufsetzbare
Zustaende zerlegt werden.

**Fachlicher Grund**

Der groesste operative Choke Point der Suite bleibt der externe Publish-/Auth-/
UI-Zustand.

**Technische Stossrichtung**

- klarere Recovery-Statuscodes fuer Preflight, Publish, Post-Release
- Reports so strukturieren, dass Wiederaufnahme ohne Log-Forensik moeglich ist

**Betroffene Schichten**

- Publish-Guard
- Preflight-/Post-Release-Skripte
- Workflow-Reports

**Abnahmekriterien**

- Teilfehler fuehren zu klaren `resume_from`-faehigen Zustandsbildern
- Operator muss weniger Rohlogs lesen

**Tests / Nachweise**

- Script- und Workflow-Tests fuer partielle Fehlpfade

**Erwarteter Produktnutzen**

Hoehere Betriebssicherheit und geringere operative Spannung.

### Arbeitspaket 8: Drift-sichere Artifact-Restore-/Stage-Politik

**Ziel**

Tracked Runtime-/Artifact-Churn soll den Publish-/Commit-Pfad seltener stoeren.

**Fachlicher Grund**

Die Statusdoku zeigt bereits, dass genau solche Artefakt-Churn-Faelle zu
Folgefehlern fuehren koennen.

**Technische Stossrichtung**

- Restore-/Stage-Policy fuer bekannte volatile Artefakte weiter schaerfen
- Drift explizit klassifizieren statt nur summarisch melden

**Betroffene Schichten**

- Refresh-Workflow
- Release-Gates
- Status-/Recovery-Doku

**Abnahmekriterien**

- bekannte volatile Artefakte erzeugen weniger falsche Commit-/Push-Probleme
- verbleibender Drift ist klar klassifiziert

**Tests / Nachweise**

- Workflow-Tests
- Report-Assertions

**Erwarteter Produktnutzen**

Stabilerer automatisierter Betrieb.

## Prioritaet 5 — Produktfokus schaerfen

### Arbeitspaket 9: Surface-Sprawl kuratieren und Mainline-Hierarchie haerten

**Ziel**

Die Produktfamilie soll klarer zwischen Mainline, Companion, Internal und
Legacy unterscheiden.

**Fachlicher Grund**

Zu viele halb-prominente Flaechen verwaessern den wahrgenommenen Produktkern.

**Technische Stossrichtung**

- Surface-Definitionen und Validation-Targets pruefen
- Companion-Flaechen dokumentarisch und operativ staerker entkoppeln

**Betroffene Schichten**

- [scripts/smc_bus_manifest.py](../scripts/smc_bus_manifest.py)
- Product-Cut-Artefakte
- Docs/Runbooks

**Abnahmekriterien**

- die drei Mainline-Flaechen sind unmissverstaendlich priorisiert
- Companion-Flaechen werden nicht mehr wie gleichrangige Produktzentren gelesen

**Tests / Nachweise**

- Manifest-/Product-Cut-Tests

**Erwarteter Produktnutzen**

Schaerfere Marktposition und hoehere wahrgenommene Wertigkeit.

### Arbeitspaket 10: Richtungswahrheit des Produkts explizit machen

**Ziel**

Long-Spezialisierung oder Richtungsparitaet sollen keine implizite Grauzone
mehr sein.

**Fachlicher Grund**

Ein Spitzenprodukt darf in seinem Kernversprechen nicht doppeldeutig sein.

**Technische Stossrichtung**

- Produkt- und Surface-Texte auf reale Mainline-Wahrheit ziehen
- falls gewollt: separaten Short-Parity-Track als explizites Vorhaben
  definieren, nicht als stilles Versprechen

**Betroffene Schichten**

- Pine-Kopfkommentare
- Product-Cut-/Guide-Doku
- Validierungs- und Runbook-Doku

**Abnahmekriterien**

- Produktnarrativ und produktive Mainline widersprechen sich nicht mehr

**Tests / Nachweise**

- Doku-/Manifest-Konsistenz
- ggf. UI-Contract-Tests

**Erwarteter Produktnutzen**

Mehr Vertrauen, klareres Marktbild, weniger Erwartungsdrift.

## Empfohlene Reihenfolge fuer Copilot

1. Arbeitspaket 1
2. Arbeitspaket 2
3. Arbeitspaket 3
4. Arbeitspaket 5
5. Arbeitspaket 7
6. Arbeitspaket 9
7. Arbeitspaket 10
8. Arbeitspaket 4
9. Arbeitspaket 6
10. Arbeitspaket 8
