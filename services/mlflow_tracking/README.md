# MLflow Tracking Pilot

Dieser Service betreibt MLflow 3.14.0 als getrennte Governance-Schicht für
PRE-A0. Er verwendet PostgreSQL für Tracking- und Registry-Metadaten, Basic
Auth für UI und API sowie einen privaten, S3-kompatiblen Railway Bucket als
serverseitig vermittelten Artefaktspeicher.

## Harte Sicherheitsgrenzen

- Der Start schlägt fehl, sobald Datenbank, Admin-Zugang, Flask-Secret oder
  Allowed-Hosts fehlen.
- Der von MLflow mitgelieferte Standard-Adminzugang wird nie verwendet.
- Neue Benutzer erhalten standardmäßig `NO_PERMISSIONS`.
- Writer und Monitor sind getrennte, nicht-administrative Rollen; der Monitor
  erhält nur `READ` auf PRE-A0-Experiment und Modell.
- Adminname, Adminpasswort, Flask-Secret, S3-Endpoint, CORS-Origin und
  Allowed-Hosts werden fail-closed validiert; Wildcard-Hosts, HTTP-CORS und
  gemeinsame Secrets sind unzulässig.
- MLflow setzt `X-Frame-Options: DENY`; CORS ist auf die exakte öffentliche
  HTTPS-Origin beschränkt.
- Clients sehen nur die MLflow-API; Bucket-Credentials verbleiben im Server.
- Tracking- und Auth-Schemamigrationen laufen seriell vor dem Start mehrerer
  Worker und müssen erfolgreich sein. Das verhindert konkurrierende
  `alembic_version_auth`-Initialisierungen auf einer neuen Datenbank.
- Der A0-/PRE-A0-Worker hängt weder beim Start noch beim Scoring von diesem
  Service ab.

## Railway-Konfiguration

Pflichtvariablen:

| Variable | Wert/Quelle |
| --- | --- |
| `DATABASE_URL` | private Referenz auf Railway PostgreSQL |
| `MLFLOW_ADMIN_USERNAME` | nicht standardmäßiger Adminname |
| `MLFLOW_ADMIN_PASSWORD` | zufällig erzeugtes Secret |
| `MLFLOW_FLASK_SERVER_SECRET_KEY` | unabhängiges zufälliges Secret |
| `MLFLOW_SERVER_ALLOWED_HOSTS` | exakte öffentliche und private Hostnamen |
| `MLFLOW_SERVER_CORS_ALLOWED_ORIGINS` | exakte öffentliche HTTPS-Origin |
| `MLFLOW_ARTIFACTS_DESTINATION` | `s3://${{mlflow-artifacts.BUCKET}}/mlflow` |
| `MLFLOW_S3_ENDPOINT_URL` | `${{mlflow-artifacts.ENDPOINT}}` |
| `AWS_ACCESS_KEY_ID` | `${{mlflow-artifacts.ACCESS_KEY_ID}}` |
| `AWS_SECRET_ACCESS_KEY` | `${{mlflow-artifacts.SECRET_ACCESS_KEY}}` |
| `AWS_DEFAULT_REGION` | `${{mlflow-artifacts.REGION}}` |

Optionale Variablen:

| Variable | Default |
| --- | --- |
| `MLFLOW_WORKERS` | `2` |

Der Bucket `mlflow-artifacts` wird in `ams` (EU West) angelegt. Zugriffsschlüssel
werden ausschließlich als Railway-Referenzvariablen an den MLflow-Service
gereicht und nicht in Git oder Client-Konfigurationen kopiert.

Der vollständige Runbook- und Promotion-Ablauf steht in
[`docs/MLFLOW_PRE_A0_PILOT_2026-07-18.md`](../../docs/MLFLOW_PRE_A0_PILOT_2026-07-18.md).
Backup, Restore, Restart und Rollback stehen in
[`docs/MLFLOW_PRE_A0_OPERATIONS_2026-07-18.md`](../../docs/MLFLOW_PRE_A0_OPERATIONS_2026-07-18.md).

`backup.railway.toml` definiert den getrennten täglichen Cron-Service. Er
benötigt ausschließlich die Variablenfamilien `MLFLOW_SOURCE_*` und
`MLFLOW_BACKUP_*` und führt `backup-verify --apply` aus; die Webanwendung
erhält keine Credentials des Backup-Buckets.
