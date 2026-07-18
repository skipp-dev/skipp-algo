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
| Shadow-Evidenz | Scored Parquet-Snapshots plus A0-Journal, Hash-/Leakage-Audit und messbare Promotion-Schwellen |
| Recovery | täglich verifizierender Railway-Cron, isolierter Restore-Drill und PostgreSQL-Rollback-Runbook |
| Monitoring | Railway `/health`, halbstündlicher Registry-/Expiry-Probe und Grafana-PRE-A0-Regeln |

## Umsetzungsstatus des Acht-Punkte-Plans

| Punkt | Ergebnis | Verbleibende operative Schranke |
| --- | --- | --- |
| 1. Migration und Serverhärtung | MLflow 3.14.0 läuft mit serieller Tracking-/Authmigration, Basic Auth, erlaubten Hosts, CORS-Prüfung, PostgreSQL und privatem S3-Artefaktspeicher. Health-, Alias- und Modell-Ladetest sind grün. | Access-Proxy/SSO erst vor einer breiteren oder dauerhaften Internetfreigabe ergänzen. |
| 2. PR-Kette | Die ursprünglichen A0-/MLflow-PRs `#3771` und `#3772` sind gemergt und ausgerollt. | Der aktuelle kleine Betriebs-Folge-Diff muss noch durch CI und Review. |
| 3. Backup und Recovery | Tägliche und wöchentliche PostgreSQL-Backups, separater privater Artefakt-Backup-Bucket und tägliche SHA-256-Prüfung sind aktiv. Der vollständige isolierte Restore-Drill vom 18. Juli ist bestanden. | Drill vierteljährlich und vor migrationsrelevanten Änderungen wiederholen. |
| 4. Monitoring | Railway-Healthcheck, halbstündlicher Candidate-/Expiry-Probe, eigener Read-only-Monitor, Alloy-Scrape und sechs Grafana-PRE-A0-Regeln sind aktiv. | Alarmzustände und Ablaufdatum weiterhin operativ beobachten. |
| 5. Reales Training | Scored Snapshot-Provenienz, kausaler Walk-forward-Builder, Sample-Weights und versiegelter Testpfad sind implementiert. | Erst nach neuen vollständigen Live-Sessions einen echten Run erzeugen; Alt-Snapshots enthalten die nötige Scoreprovenienz nicht. |
| 6. Shadow-Promotion | Messbare Coverage-, Klassen-, Brier-, AP-, ECE-, Audit- und Artifact-ID-Gates sind implementiert. | `shadow` bleibt korrekt blockiert, bis mindestens fünf neue Sessions alle Schwellen belegen. |
| 7. Zugriffsschutz | Getrennte Writer-/Monitor-Rollen sind angewendet. Der Reconciler bleibt bei unbekannten Zusatzrollen fail-closed und akzeptiert nur MLflows synthetische Direktzuweisungsrolle `__user_<id>__`. | Folge-Fix mergen; für breiteren Internetzugriff weiterhin Access-Proxy/SSO ergänzen. |
| 8. Aim/Alternativen | Entscheidung dokumentiert: MLflow bleibt führend, DVC ist die sinnvollste spätere Datensatzergänzung, Aim nur bei messbarem UI-/Skalierungsbedarf. | Keine produktive Aim-Instanz anlegen. |

Damit ist der Codeanteil aller acht Punkte umgesetzt. Externe Rollout- und
Evidenzschritte werden nicht als bestanden bezeichnet, bevor ihr jeweiliger
Health-, CI-, Backup- oder Shadow-Nachweis tatsächlich vorliegt.

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

Fünf qualifizierte vollständige neue Sessions sind dabei nur die
Mindestvoraussetzung für die MLflow-Evaluation und einen möglichen
`shadow`-Alias. Sie sind keine Freigabe für Benachrichtigungen.

### Runtime/Production

MLflow bietet in diesem Pilot keinen `production`- oder `notify`-Alias an.
Eine Registry-Promotion verändert den Railway-Worker nicht. Der Austausch des
lokalen JSON-Vertrags bleibt ein separater, reviewpflichtiger Code-/Deployment-
Vorgang inklusive Worker-Validierung. Damit kann ein kompromittierter oder
fehlbedienter MLflow-Server keine Laufzeitpromotion auslösen.

Der Runtime-Notify-Pfad bleibt zusätzlich fail-closed, bis mindestens 20
vollständige neue Sessions und 200 bestätigte A0-Episoden im validierten
Artefakt nachgewiesen sind. Fehlt eine dieser Metriken, wird sie als 0
behandelt. Offline- und Shadow-Gate müssen ebenfalls bestanden sein.

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

Für neue reale Runs wird der Trainingsinput deterministisch aus den
hash-geprüften Shadow-Parquets und dem A0-Journal erstellt. Der Builder trennt
tageweise in Train/Calibration/Test, prüft Episode-Leakage und versiegelt den
Testsplit:

```bash
python -m scripts.prepare_pre_a0_training_data \
  services/a0_fast_detector/bootstrap/pre-a0-model.json \
  /volume/pre-a0-snapshots \
  /tmp/pre-a0-training.json \
  /tmp/pre-a0-test.json \
  /tmp/pre-a0-provenance.json \
  /volume/a0-parity/a0_shadow_databento_*.jsonl \
  --code-revision "$GIT_COMMIT"
```

Neue Snapshots enthalten deshalb neben den kausalen Merkmalen auch
Modell-ID, ausgegebene Wahrscheinlichkeit, Scorestatus und Fehlerursache pro
Horizont. Alt-Snapshots ohne diese Provenienz können das Shadow-Gate nicht
erfüllen.

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
- Für den Pilot eine Service-Replik und zwei Worker-Prozesse verwenden. Der
  Launcher migriert Tracking- und Auth-Schema seriell, bevor er die Worker
  startet; dadurch bleibt auch der allererste Start auf einer leeren Datenbank
  frei von konkurrierenden Auth-Migrationen.
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
- `scripts/configure_pre_a0_mlflow_rbac.py` legt idempotent zwei getrennte
  Rollen an: Writer mit `EDIT` nur auf Experiment `1` und Modell
  `skipp-pre-a0`, Monitor mit `READ` auf denselben Ressourcen. Beide erhalten
  lediglich das technisch erforderliche Workspace-`USE`; unbekannte
  Zusatzrechte lassen den Lauf fail-closed abbrechen.
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

RBAC wird zuerst nur geplant und anschließend bewusst angewendet:

```bash
python -m scripts.configure_pre_a0_mlflow_rbac \
  --tracking-uri "$MLFLOW_TRACKING_URI" \
  --experiment-id 1

python -m scripts.configure_pre_a0_mlflow_rbac \
  --tracking-uri "$MLFLOW_TRACKING_URI" \
  --experiment-id 1 \
  --apply
```

Admin-Credentials kommen über `MLFLOW_TRACKING_USERNAME` und
`MLFLOW_TRACKING_PASSWORD`; Writer-/Monitor-Passwörter ausschließlich über
`PRE_A0_MLFLOW_WRITER_PASSWORD` beziehungsweise
`PRE_A0_MLFLOW_MONITOR_PASSWORD`. Kein Secret wird als Argument ausgegeben.

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

Das vollständige Betriebsrunbook inklusive RPO/RTO, Backup, isoliertem
Restore-Drill und Credential-Incident-Ablauf steht in
[`MLFLOW_PRE_A0_OPERATIONS_2026-07-18.md`](MLFLOW_PRE_A0_OPERATIONS_2026-07-18.md).
Die Aim-/Alternativen-Entscheidung steht in
[`PRE_A0_EXPERIMENT_TRACKING_EVALUATION_2026-07-18.md`](PRE_A0_EXPERIMENT_TRACKING_EVALUATION_2026-07-18.md).

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

## Externer Ist-Stand und nächste Schritte

PostgreSQL, operativer Artefakt-Bucket, MLflow-Service, öffentliche Domain und
der reproduzierbare Bootstrap-Import existieren bereits. Der importierte
Candidate ist Run `44dd712b9bd84c35a41e8ab9d1a87cb3`, Modellversion 1 und
Artifact ID `71831770afe43bdd424aa7ab`; der Railway-Worker verwendet weiterhin
seinen lokal validierten JSON-Vertrag. RBAC, Read-only-Monitor, sechs
Grafana-Regeln, PostgreSQL-Zeitpläne und der getrennte Artefakt-Backup-Pfad
sind aktiv. Der Restore-Drill vom 18. Juli 2026 hat Datenbank, Alias,
Modell-Ladevorgang und sämtliche 77 Backupobjekte unabhängig verifiziert.

Operativ offen ist ausschließlich echte Evidenz: ab der nächsten vollständigen
US-Handelssitzung Snapshots und Journale sammeln, nach fünf qualifizierten
Sessions das Shadow-Gate auswerten und erst bei bestandenem Gate einen neuen
Trainingsrun beziehungsweise `shadow`-Alias erzeugen. Notify bleibt bis 20
Sessions und 200 bestätigten A0-Episoden gesperrt. Es wurde keine Evidenz
simuliert oder umgangen.

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
