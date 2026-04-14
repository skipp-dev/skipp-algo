# SMC Residual Program Completion

Stand: 2026-04-14
Repository-Basis: `main` bis `8c6652db`

## Zweck

Dieses Dokument ueberfuehrt den extern gepflegten Residual-Programm-Stand in ein
getracktes Repo-Dokument. Es ist kein neuer Implementierungsplan. Es fixiert den
abgeschlossenen Zustand nach dem verifizierten Senior-Review und den danach
umgesetzten Folgehaertungen.

## Executive Summary

Das fruehere Residualprogramm ist abgeschlossen. Die offenen Restthemen wurden
nicht entlang der alten Pakete A bis C umgesetzt, sondern entlang von drei
sauberen Schnitten:

1. kanonischer Databento-End-to-End-Volume-Vertrag
2. gemeinsame Terminal-Outbound-Policy plus Coverage auf echten Dispatch-Pfaden
3. Release-Gate-Forensik mit getrennten Pre-/Post-Publish-Reports

Im anschliessenden Senior-Review blieb noch genau ein echter Delta-Schnitt
uebrig: Die provider-spezifische Databento-Traceability durfte nicht dauerhaft
im kanonischen Snapshot-Vertrag landen. Dieser Nachschnitt ist inzwischen
ebenfalls umgesetzt und nach `origin/main` publiziert.

## Publizierter Abschlussstand

- urspruenglicher Residualprogramm-Abschluss auf `origin/main`: `0d01d27a38dfc2fc8fdb539c857741944b522e2a`
- publizierte Folgehaertung aus dem Senior-Review: `8c6652db`
- verbleibender bewusst optionaler Rest: Teil-Publish-Sentinel nur bei
  operativem Bedarf

## Abschluss der drei Hauptschnitte

### 1. Databento Volume Contract

Der Databento-Volume-Vertrag bleibt end-to-end sichtbar, aber der kanonische
Snapshot bleibt schmal.

- `snapshot.meta.volume.value` ist wieder bewusst auf `regime` und
  `thin_fraction` begrenzt
- provider-spezifische Databento-Traceability wird additiv als
  `volume_provenance` im Delivery-Bundle transportiert
- Source-, Adapter-, Bundle- und Schema-Tests fixieren dieselbe Boundary

Betroffene Kernflaechen:

- [smc_core/types.py](../smc_core/types.py)
- [smc_adapters/ingest.py](../smc_adapters/ingest.py)
- [smc_integration/service.py](../smc_integration/service.py)
- [spec/smc_delivery_bundle.schema.json](../spec/smc_delivery_bundle.schema.json)
- [smc-snapshot-target-architecture.md](smc-snapshot-target-architecture.md)

### 2. Terminal Outbound Policy And Dispatch Coverage

Alle operator-konfigurierbaren Outbound-Ziele folgen derselben URL-Policy, und
das Fast-Gate misst echte Dispatch-Pfade statt nur Hilfsschichten.

- gemeinsame URL-Policy fuer Streamlit-, Export- und Notification-Pfade
- HTTPS-only, keine Credentials, keine privaten/lokalen Ziele, keine Redirects
- Fast-Gate-Coverage an realen Dispatch-Pfaden statt nur an Helfermodulen

### 3. Release-Gate Forensics

Vor- und Nach-Publish-Wahrheit bleiben fuer Operatoren getrennt nachvollziehbar.

- Pre- und Post-Release-Gates schreiben getrennte Artefakte
- Evidence-Aggregation kann beide Phasen getrennt gegenueberstellen
- Forensik und optionaler Teil-Publish-Sentinel sind sauber getrennt

## Folgehaertung aus dem Senior-Review

Der verifizierte Review gegen den damaligen `main`-Stand zeigte keinen breiten
neuen Residualscope, sondern genau eine harte Boundary-Drift:

- neue Databento-Traceability-Felder waren in den Snapshot-Meta-Pfad gerutscht
- das strikte Delivery-Bundle-Schema wies diese Drift zurecht zurueck

Die umgesetzte Korrektur war bewusst kein Schema-Aufweichen, sondern eine
Boundary-Klaerung:

- kanonischer Snapshot bleibt schmal
- provider-spezifische Transparenz bleibt erhalten
- Delivery-Bundle traegt `volume_provenance` additiv
- der Bundle-Service wurde in kleinere Projektionsbausteine zerlegt

## Validierungsstand

Die relevanten Schnitte sind gruen validiert:

- urspruengliche residualprogrammbezogene Suite: `102 passed in 1.24s`
- direkte Folgehaertung aus dem Senior-Review: `69 passed in 2.21s`
- breitere Architektur-Stichprobe nach der Folgehaertung: `114 passed in 1.38s`

## Was explizit nicht offen ist

- kein neues 5-PR-Programm fuer bereits gelandete Grundimplementierung
- kein separates Source-Hardening-Paket fuer Databento jenseits des jetzt
  fixierten Vertrags
- kein eigener Coverage-/Refactor-Block fuer Terminal-Module ausserhalb der
  realen Dispatch- und Policy-Pfade
- keine Vermischung des optionalen Teil-Publish-Sentinels mit der
  Forensik-Grundarbeit

## Read This Next

- [smc-validation-status.md](smc-validation-status.md)
- [smc-snapshot-target-architecture.md](smc-snapshot-target-architecture.md)
- [smc_deep_review_v9_verified_action_plan.md](smc_deep_review_v9_verified_action_plan.md)
