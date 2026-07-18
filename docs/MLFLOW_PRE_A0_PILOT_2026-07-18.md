# MLflow-Pilot für PRE-A0

Stand: 18. Juli 2026

## Ergebnis und Zielbild

Der Pilot ergänzt PRE-A0 um nachvollziehbare Runs, reproduzierbare Artefakte,
eine Model Registry und technisch erzwungene Promotion-Gates. Die sichere
Laufzeitarchitektur bleibt unverändert: Der Railway-Worker lädt weiterhin nur
den lokal geprüften JSON-Vertrag. Ein Ausfall, Berechtigungsfehler oder eine
Fehlkonfiguration von MLflow kann deshalb weder A0 noch PRE-A0 im Worker
aktivieren, verändern oder unterdrücken.

```text
Training/Evaluation ──explicit opt-in──> MLflow Tracking + Registry
       │                                  │
       │ canonical JSON                   ├── PostgreSQL: Runs, Tags, Registry
       ▼                                  └── privater S3-Bucket: Artefakte
lokale Validierung
       │
       └──reviewed JSON──> Railway A0/PRE-A0 Shadow Worker
                              (keine MLflow-Abhängigkeit)
```

## Warum nicht direkt den Fork deployen?

`skipp-dev/mlflow` und `skipp-dev/mlflow-docker-compose` sind nützliche
Referenzen. Der Compose-Fork pinnt jedoch MLflow 2.21.1 und kombiniert MySQL
mit MinIO. Für diesen Pilot ist eine kleine, im Hauptrepository versionierte
Deployment-Grenze besser prüfbar: MLflow 3.14.0, Railway PostgreSQL und ein
privater, S3-kompatibler Railway Bucket. MLflow vermittelt den Zugriff, sodass
Clients keine Bucket-Credentials erhalten. Gegenüber einem lokalen Volume
bleibt die Artefaktschicht außerdem unabhängig von einer einzelnen Replik.

## Implementierte Bausteine

| Baustein | Umsetzung |
| --- | --- |
| Optionaler Client | `requirements-mlflow.txt`, nicht in den Worker-Abhängigkeiten |
| Trainingsinstrumentierung | `scripts/train_pre_a0_model.py` loggt bei expliziter Tracking-URI Parameter, Metriken, Input-Hash und JSON-Artefakt |
| Evaluationsübergabe | `scripts/evaluate_pre_a0_model.py` erzeugt Report plus validiertes JSON mit Offline-Gate |
| Bootstrap-Import | `scripts/import_pre_a0_mlflow.py`, Dry-run als Default, Write nur mit `--apply` |
| Registry-Modell | MLflow Model-from-Code mit eingebettetem kanonischem JSON; kein CloudPickle-Artefakt |
| Promotion | `scripts/promote_pre_a0_mlflow.py`, nur `candidate` und `shadow` |
| Policy | `governance/pre_a0_promotion_policy.json` |
| Server | `services/mlflow_tracking`, Basic Auth, PostgreSQL, proxied S3-Artefakte |
| Runtime-Isolation | keine Änderung an `services/a0_fast_detector/requirements.txt`, Dockerfile, Variablen oder Startpfad |

## Erster reproduzierbarer Run

Der Bootstrap ist fest auf das bestehende Artefakt ausgelegt:

| Feld | Wert |
| --- | --- |
| Artifact ID | `71831770afe43bdd424aa7ab` |
| Validated Bundle ID | `079f72f1ba2df389c13c2322` |
| Runtime-Vertrag | `pre-a0-model-v1` / lokales JSON |
| Feature-Vertrag | `pre-a0-features-v1` |
| Split SHA-256 | `36e61186c083572cf32344bda5102641c57d890d3893881d354f2d18d2845343` |
| Testzeilen | 210 |
| Test-Brier | 0,0408881 |
| Base-Rate-Brier | 0,0453515 |
| Average Precision | 0,9573 |
| Test-ECE | 0,0469592 |
| Review spätestens | `2026-08-17T08:53:15.116529Z` |
| Offline-Gate | bestanden |
| Shadow-Gate | nicht bestanden / noch nicht belegt |

Vor jedem Import wird die Artifact ID aus Modellinhalt, Kalibrierung,
Feature-/Schema-Version und Split-Hash neu berechnet. Zusätzlich müssen
Artifact ID, Split und sämtliche gespeicherten Metriken exakt zum
Validierungsreport passen. Eine nachträgliche Veränderung an JSON oder Report
blockiert den Import.

## Promotion-Gates

### `candidate`

Ein Modell erhält den Alias `candidate` nur, wenn alle Bedingungen erfüllt
sind:

1. Die inhaltlich neu berechnete Artifact ID stimmt.
2. Validierungsreport, Split und Metriken sind mit dem Artefakt verknüpft.
3. `review_after` liegt nicht in der Vergangenheit.
4. Artefakt und Report bestätigen die Offline-Evaluation.
5. Eine Kalibrierung ist vorhanden.
6. Der versiegelte Testsplit enthält mindestens 200 Zeilen.
7. Der Modell-Brier ist strikt besser als der Base-Rate-Brier.
8. Test-ECE ist höchstens 0,05.
9. Average Precision ist mindestens 0,80.

Das aktuelle Artefakt erfüllt diese Bedingungen.

### `shadow`

`shadow` verlangt zusätzlich ein bestandenes Candidate-Gate sowie zwei
unabhängige Bestätigungen: `artifact.gates.shadow_evaluated=true` und
`validation_report.shadow_gate_passed=true`. Das aktuelle Artefakt erfüllt
diese Bedingung absichtlich noch nicht. Ein lokaler Negativtest bestätigt,
dass die Promotion mit `shadow_evaluation_missing` abgewiesen wird.

### Runtime/Production

MLflow bietet in diesem Pilot keinen `production`- oder `notify`-Alias an.
Eine Registry-Promotion verändert den Railway-Worker nicht. Der Austausch des
lokalen JSON-Vertrags bleibt ein separater, reviewpflichtiger Code-/Deployment-
Vorgang inklusive Worker-Validierung. Damit kann ein kompromittierter oder
fehlbedienter MLflow-Server keine Laufzeitpromotion auslösen.

## Lokale Nutzung

Optionalen Client installieren:

```bash
python -m pip install -r requirements-mlflow.txt
```

Nur prüfen, noch nichts in MLflow schreiben:

```bash
python -m scripts.import_pre_a0_mlflow \
  --expected-artifact-id 71831770afe43bdd424aa7ab
```

Der erwartete Dry-run meldet `candidate_eligible=true` und
`shadow_eligible=false`.

Nach Deployment und bewusst gesetzten Client-Credentials:

```bash
export MLFLOW_TRACKING_URI='https://<mlflow-host>'
export MLFLOW_TRACKING_USERNAME='<pilot-user>'
export MLFLOW_TRACKING_PASSWORD='<secret>'

python -m scripts.import_pre_a0_mlflow \
  --expected-artifact-id 71831770afe43bdd424aa7ab \
  --run-name bootstrap-71831770afe43bdd424aa7ab \
  --apply
```

Das Skript verweigert einen zweiten Import derselben Artifact ID im Experiment
`pre-a0`, sofern auch Report und Policy identisch sind. Technisch wird dafür
eine zusätzliche Bundle ID über Modell, Report und Policy verwendet. Neue
Shadow-Evidenz zum unveränderten Modell darf dadurch als neue, nachvollziehbare
Bundle-Version importiert werden. Der erste erfolgreiche Import erzeugt den
Registered Model Name `skipp-pre-a0`, Version 1 und Alias `candidate`.

Künftige Trainingsläufe werden nur bei expliziter URI instrumentiert:

```bash
python -m scripts.train_pre_a0_model INPUT.json OUTPUT.json \
  --split-hash '<sha256>' \
  --review-after '<ISO-8601-Zeitpunkt>' \
  --mlflow-tracking-uri "$MLFLOW_TRACKING_URI" \
  --mlflow-experiment-name pre-a0 \
  --mlflow-run-name '<eindeutiger Name>'
```

Der Trainingsinput selbst wird nicht hochgeladen. MLflow erhält nur SHA-256,
Zeilenzahlen, Fenster, Parameter, Metriken und das resultierende JSON.

Nach der versiegelten Evaluation wird ein mit Testmetriken und Offline-Gate
angereichertes, weiterhin inhaltsidentisches Runtime-Artefakt erzeugt:

```bash
python -m scripts.evaluate_pre_a0_model OUTPUT.json TEST_SPLIT.json REPORT.json \
  --validated-artifact-output VALIDATED_MODEL.json
```

`VALIDATED_MODEL.json`, `REPORT.json` und die Promotion-Policy bilden gemeinsam
das unveränderliche Bundle für den Import. Ein nicht bestandener Offline-Test
setzt das Gate nicht und wird vom Import abgewiesen.

Eine spätere Promotion wird standardmäßig nur angekündigt:

```bash
python -m scripts.promote_pre_a0_mlflow 1 shadow
```

Erst `--apply` lädt JSON und Evidenz erneut vom Server, prüft alle Gates neu
und schreibt den Alias.

## Railway-Deploymentplan

### 1. Code bereitstellen

- Gestapelten Draft-PR oberhalb des bestehenden A0-PR erstellen.
- CI, Ledger-Drift-Guard und Ruff müssen grün sein.
- Erst nach Review mergen; der A0-PR bleibt die fachliche Voraussetzung.

### 2. PostgreSQL anlegen

- Im vorhandenen Railway-Projekt einen PostgreSQL-Service für MLflow anlegen.
- Nur private Service-Kommunikation verwenden.
- `DATABASE_URL` im MLflow-Service per Railway-Service-Reference setzen; der
  Klartextwert wird nicht in Git abgelegt.
- Vor MLflow-Upgrades ein Datenbankbackup erzeugen, weil Schema-Migrationen
  explizit vor dem Serverstart laufen.

### 3. MLflow-Service und Artefaktspeicher anlegen

- Service `mlflow-tracking` aus `services/mlflow_tracking/railway.toml` bauen.
- Privaten Bucket `mlflow-artifacts` in `ams` (EU West) anlegen.
- Bucket-Ziel, Endpoint, Region und Credentials ausschließlich über Railway-
  Referenzvariablen an `mlflow-tracking` geben.
- MLflow proxied sämtliche Uploads und Downloads; Clients erhalten keine
  direkten S3-Zugangsdaten.
- Für den Pilot eine Service-Replik und zwei Worker-Prozesse verwenden.
- Exakten öffentlichen Railway-Host und privaten Service-Host in
  `MLFLOW_SERVER_ALLOWED_HOSTS` eintragen.

Railway-Referenzvariablen für den Artefaktspeicher:

| Variable | Referenzwert |
| --- | --- |
| `DATABASE_URL` | `${{Postgres.DATABASE_URL}}` |
| `MLFLOW_ARTIFACTS_DESTINATION` | `s3://${{mlflow-artifacts.BUCKET}}/mlflow` |
| `MLFLOW_S3_ENDPOINT_URL` | `${{mlflow-artifacts.ENDPOINT}}` |
| `AWS_ACCESS_KEY_ID` | `${{mlflow-artifacts.ACCESS_KEY_ID}}` |
| `AWS_SECRET_ACCESS_KEY` | `${{mlflow-artifacts.SECRET_ACCESS_KEY}}` |
| `AWS_DEFAULT_REGION` | `${{mlflow-artifacts.REGION}}` |

### 4. Zugriff absichern

- `MLFLOW_ADMIN_USERNAME` auf einen nicht standardmäßigen Namen setzen.
- Für `MLFLOW_ADMIN_PASSWORD` und `MLFLOW_FLASK_SERVER_SECRET_KEY` zwei
  unabhängige, URL-sichere Zufallswerte mit mindestens 32 Byte Entropie setzen.
- Öffentliche Domain erst nach aktiver Basic-Auth-Prüfung verwenden.
- Unauthentifizierter API-/UI-Zugriff muss 401 liefern.
- Den einmaligen Bootstrap mit dem starken Pilot-Admin ausführen. Danach einen
  eigenen nicht-administrativen Import-Benutzer erzeugen und ihm nur die
  erforderlichen Rechte auf das dann vorhandene Experiment `pre-a0` und Modell
  `skipp-pre-a0` geben. Neue Benutzer erhalten ansonsten `NO_PERMISSIONS`.
- Der eingebaute Basic-Auth-Login besitzt keine belastbare Brute-Force-
  Drosselung. Vor einer breiteren oder dauerhaften Internetfreigabe deshalb
  einen vorgeschalteten Access-Proxy mit Rate Limit/SSO ergänzen; bis dahin
  starken Zufallszugang verwenden und den öffentlichen Zugriff auf den Pilot
  begrenzen.

### 5. Bootstrap importieren

- Dry-run lokal erneut ausführen.
- Ablaufdatum `2026-08-17T08:53:15.116529Z` prüfen.
- Importkommando mit `--apply` genau einmal ausführen.
- Run-ID, Modellversion, Alias und Artifact ID in der Deployment-Evidenz
  erfassen.
- Modell `models:/skipp-pre-a0@candidate` laden und einen bekannten Snapshot
  scoren; Ergebnis muss endlich und zwischen 0 und 1 sein.
- Anschließend den nicht-administrativen Import-Benutzer berechtigen und den
  Adminzugang nicht mehr für normale Trainings-/Importläufe verwenden.

### 6. Betrieb beobachten

- PostgreSQL-, Bucket- und Service-Restart testen.
- Artifact-Download nur über authentifizierte MLflow-API testen.
- Speicherbelegung sowie Export-/Wiederherstellungsverfahren des Buckets
  dokumentieren.
- Keine Variable und kein Paket im A0-Worker ändern.

### 7. Shadow-Gate erarbeiten

- Mehrere vollständige Live-Sessions sammeln.
- Coverage, Missingness, Out-of-range-Anteil, Kalibrierung, Brier und
  Fehlalarme gegen die dokumentierte Shadow-Policy bewerten.
- Neuen, unveränderlichen Validierungsreport erzeugen.
- Nur bei bestandenem Review beide Shadow-Bestätigungen setzen und eine neue
  validierte Bundle-Version/einen neuen Run erzeugen. Bleibt der eigentliche
  Modellinhalt gleich, bleibt auch seine inhaltsbasierte Artifact ID gleich.
- `shadow` per Promotion-Skript setzen; Worker bleibt weiterhin am lokalen
  JSON-Vertrag.

## Verifikation und Rollback

Lokale Implementierungsprüfung:

- Bootstrap-Dry-run: Candidate bestanden, Shadow blockiert.
- Isolierter SQLite-Registry-Smoke-Test: Run, Modellversion 1 und
  `candidate`-Alias erfolgreich.
- Registry-Modell wieder geladen und gültige Wahrscheinlichkeit erzeugt.
- `shadow`-Promotion desselben Modells korrekt verweigert.

Rollback des Piloten ist unabhängig vom A0-Betrieb:

1. MLflow-Service stoppen oder öffentliche Domain entfernen.
2. PostgreSQL und Bucket unverändert behalten, damit keine Evidenz verloren
   geht.
3. Client-Tracking-Flags aus Trainingskommandos entfernen.
4. A0-/PRE-A0-Worker nicht neu deployen; dessen lokaler JSON-Vertrag läuft
   unverändert weiter.

## Noch ausstehende externe Schritte

Die lokale Implementierung und der isolierte Registry-Test sind abgeschlossen.
Push, Draft-PR, Railway PostgreSQL/Bucket/Service, öffentliche Domain und der
dauerhafte Bootstrap-Import sind externe Änderungen. Sie werden erst nach
einer separaten, unmittelbar vorher gezeigten Vorschau mit Empfänger, Kanal,
Inhalt und konkreten Railway-Mutationen ausgeführt.

## Technische Referenzen

- [MLflow 3.14.0 Release](https://github.com/mlflow/mlflow/releases/tag/v3.14.0)
- [MLflow Tracking Server und proxied artifacts](https://mlflow.org/docs/latest/self-hosting/architecture/tracking-server/)
- [MLflow Basic Auth und RBAC](https://mlflow.org/docs/latest/self-hosting/security/basic-http-auth/)
- [MLflow Model Registry, Aliases und Tags](https://mlflow.org/docs/latest/ml/model-registry/workflow/)
- [MLflow Models from Code](https://mlflow.org/docs/latest/ml/model/models-from-code/)
- [MLflow Netzwerk-Schutz](https://mlflow.org/docs/latest/self-hosting/security/network/)
- [Railway Buckets](https://docs.railway.com/storage-buckets)
- [Railway Referenzvariablen](https://docs.railway.com/variables/reference)
- [skipp-dev MLflow-Forks](https://github.com/skipp-dev)
