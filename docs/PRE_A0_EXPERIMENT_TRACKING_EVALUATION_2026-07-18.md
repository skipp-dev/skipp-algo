# PRE-A0 Experiment-Tracking: Aim und Alternativen

Stand: 18. Juli 2026

## Entscheidung

**MLflow bleibt das führende System für PRE-A0. Aim wird vorerst nicht als
zweiter produktiver Tracker eingeführt.** Aim ist stark bei der interaktiven
Exploration sehr vieler Metrikreihen und Runs, schließt aber die für PRE-A0
entscheidenden Lücken – Model Registry, Aliases, Promotion-Gates und
ressourcenbezogenes RBAC – nicht besser als der bereits laufende MLflow-Pilot.
Ein Parallelbetrieb würde zwei Wahrheiten, zwei Speicher- und Backup-Pfade und
zusätzliche Zugangssicherung erzeugen.

## Was Aim gut kann

- Open Source und selbst hostbar.
- Schnelle UI und Abfragesprache zur Gegenüberstellung vieler Runs und
  Metrikzeitreihen; das Projekt positioniert sich für tausende bis zehntausende
  Runs.
- Remote Tracking über HTTP/WebSocket und S3-Artefaktspeicher.
- Import vorhandener MLflow-Runs ist vorgesehen.
- Das Repository ist aktiv; die jüngste chronologische GitHub-Release ist
  `v3.29.1` vom 8. Mai 2025, während der Hauptbranch auch 2026 weiter gepflegt
  wurde. Die älteren `v4.0.x`-Tags stammen aus 2023 und sind daher kein Beleg
  für eine neuere stabile Produktionslinie.

## Warum Aim jetzt nicht passt

1. **Governance statt nur Visualisierung.** PRE-A0 braucht eine nachvollziehbare
   Modellversion, `candidate`/`shadow`-Aliases, unveränderliche Tags und
   serverseitige Rechte. MLflow stellt Registry, Aliases und ab Version 3.13
   RBAC bereit. Aim ist primär Run-/Metrik-Explorer.
2. **Zugangsschutz.** Die dokumentierten Aim-Serveroptionen bieten TLS, aber
   keinen mit MLflows Experiment-/Model-RBAC vergleichbaren Benutzer- und
   Ressourcenvertrag. Ein zusätzlicher Auth-Proxy wäre Pflicht.
3. **Speicher/Recovery.** Aim nutzt ein eigenes repository-basiertes Storage-
   Modell. Für Railway wäre dafür zusätzlich ein persistentes Volume samt
   konsistentem Backup/Restore nötig; PostgreSQL plus S3 des MLflow-Piloten ist
   bereits eingerichtet und geprüft.
4. **Doppelte Wahrheit.** Ein MLflow-Import nach Aim ist eine Kopie, keine
   Promotion-Autorität. Alias, Gate und Runtime-Identität müssten weiterhin aus
   MLflow gelesen werden.
5. **Noch kein Skalierungsproblem.** PRE-A0 hat aktuell einen validierten Run
   und noch keine große Hyperparameter-Suche. Aims UI-Vorteil wird erst bei
   deutlich mehr Runs/Metrikreihen relevant.

## Vergleich

| Option | Stärken | Lücken für PRE-A0 | Urteil |
| --- | --- | --- | --- |
| **MLflow** | Tracking, PostgreSQL, S3, Registry, Aliases, Tags, RBAC, große Integrationstiefe | Basic Auth benötigt weiterhin Proxy/SSO für breitere Freigabe | **Jetzt verwenden** |
| **Aim** | Sehr gute Run-/Kurvenexploration, einfache SDK, selbst hostbar | Keine gleichwertige Registry-/Promotion-Autorität; eigener Storage; zusätzlicher Auth-Proxy | Späterer read-only UI-Pilot möglich |
| **ClearML** | Experiment Manager, Modellkatalog, Lineage, Data/Agent/Serving | Deutlich größerer Control Plane und mehr Betriebsflächen als benötigt | Erst bei Orchestrierungsbedarf neu prüfen |
| **DVC + DVCLive** | Git-nahe Daten-/Pipeline-Reproduzierbarkeit, lokale Experimente | Kein Ersatz für zentrale Registry und MLflow-RBAC | **Gute Ergänzung für Datensätze**, nicht Ersatz |
| **Kubeflow Hub/Katib** | Registry plus Kubernetes-native HPO/Training | Kubernetes-Control-Plane ist für Railway/PRE-A0 unverhältnismäßig | Derzeit nicht einsetzen |

## Empfohlene Architektur

```text
Databento / Shadow-Parquet / A0-Journal
              │
              ├── SHA-256 + Splitmanifest ──> reproduzierbarer Trainingsinput
              │
              └── train/evaluate ───────────> MLflow Runs + Registry
                                                   │
                                      candidate/shadow governance only
                                                   │
separat geprüfter JSON-Vertrag <────────────────── Review/Deployment
              │
              └── Railway PRE-A0 Worker (keine MLflow-Laufzeitabhängigkeit)
```

DVC ist die sinnvollste nächste Ergänzung, falls die Databento- und
Shadow-Datensätze zu groß oder zu häufig für den bestehenden Hash-/Manifest-
Ansatz werden. Es sollte dann ausschließlich Dataset-/Pipeline-Versionierung
übernehmen; Run-, Registry- und Promotion-Wahrheit verbleiben in MLflow.

## Messbarer Aim-Revisit-Trigger

Ein zeitlich begrenzter, read-only Aim-Pilot ist erst sinnvoll, wenn mindestens
einer dieser Punkte eintritt:

- mehr als 500 PRE-A0-Runs oder mehr als 50 parallele Kurven pro Vergleich;
- MLflow-UI-Abfragen benötigen wiederholt über fünf Sekunden;
- Analysten können wichtige Slice-/Zeitreihenvergleiche in MLflow nicht ohne
  eigene Notebooks durchführen;
- ein konkreter Aim-Import zeigt mindestens 30 Prozent weniger Analysezeit.

Dann gilt: keine Client-Doppelinstrumentierung. Runs werden einseitig aus
MLflow in eine isolierte, read-only Aim-Instanz gespiegelt. Aim darf weder
Alias noch Promotion oder Worker-Deployment steuern. Nach vier Wochen werden
Analysezeit, Query-Latenz, Betriebskosten und Sicherheitsaufwand gemessen;
ohne klaren Nutzen wird die Instanz wieder entfernt.

## Quellen

- [Aim Repository und Produktumfang](https://github.com/aimhubio/aim)
- [Aim Remote Tracking und TLS](https://aimstack.readthedocs.io/en/latest/using/remote_tracking.html)
- [Aim Storage-/Komponentenübersicht](https://aimstack.readthedocs.io/en/latest/understanding/overview.html)
- [Aim CLI 3.29.1](https://aimstack.readthedocs.io/en/latest/refs/cli.html)
- [Aim v3.29.1 Release](https://github.com/aimhubio/aim/releases/tag/v3.29.1)
- [MLflow Self-Hosting](https://mlflow.org/docs/latest/self-hosting/)
- [MLflow Registry-Aliases](https://mlflow.org/docs/latest/ml/model-registry/workflow/)
- [MLflow Auth und RBAC](https://mlflow.org/docs/latest/self-hosting/security/basic-http-auth/)
- [ClearML Model Registry](https://clear.ml/docs/latest/docs/model_registry/)
- [ClearML Architektur](https://clear.ml/docs/latest/docs/getting_started/architecture/)
- [DVC Experimente](https://dvc.org/doc/user-guide/experiment-management/)
- [Kubeflow Hub](https://www.kubeflow.org/docs/components/hub/overview/)
- [Kubeflow Katib](https://www.kubeflow.org/docs/components/katib/overview/)
