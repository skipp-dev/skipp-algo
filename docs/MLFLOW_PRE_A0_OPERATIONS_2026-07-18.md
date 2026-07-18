# MLflow/PRE-A0 Betriebs- und Recovery-Runbook

Stand: 18. Juli 2026

## Betriebsziel

MLflow ist die Governance- und Nachweisschicht, nicht der PRE-A0-Runtime-Pfad.
Ein Ausfall von MLflow darf Training, Import oder Promotion blockieren, aber
niemals bestätigtes A0 oder das lokale PRE-A0-Scoring verändern. Der Worker
behält seinen geprüften JSON-Vertrag und läuft bei MLflow-Ausfall unverändert
weiter.

| Komponente | Schutz | Ziel-RPO | Ziel-RTO |
| --- | --- | --- | --- |
| PostgreSQL | Railway-Volume-Backups: täglich plus wöchentlich, vor jedem Upgrade manuell | 24 h, vor Migration 0 h | 60 min |
| Artefakte | tägliche, SHA-256-verifizierte Kopie in getrennten privaten Bucket | 24 h | 60 min |
| Konfiguration | Git, Railway-Referenzvariablen, lokaler Secret-Inventar-Nachweis ohne Secretwerte | letzter geprüfter Commit | 30 min |
| Worker-Vertrag | versioniertes, lokal geprüftes JSON im Worker-Image | 0 h | Railway-Rollback-Zeit |

## Backup

### PostgreSQL

1. Auf dem PostgreSQL-Volume tägliche und wöchentliche Railway-Backups
   aktivieren.
2. Vor MLflow-, Auth- oder PostgreSQL-Upgrades ein manuelles Backup auslösen.
3. Backup-ID, Zeitpunkt, Quell-Deployment und auslösende Änderung im
   Deployment-Nachweis festhalten.
4. Niemals gleichzeitig zwei MLflow-Repliken mit Schema-Migrationen starten.
   Der Launcher führt Tracking- und Auth-Migration seriell aus, bevor zwei
   Worker-Prozesse Traffic annehmen.

### Artefakte

Railway Buckets bieten derzeit weder Versionierung noch Object Lock oder
native Backup-Zeitpläne. Deshalb wird `mlflow/` in einen getrennten privaten
Bucket kopiert. `scripts/mlflow_artifact_backup.py` ist standardmäßig Dry-run,
liest keine Credentials aus Argumenten und schreibt erst mit `--apply`.

```bash
python -m scripts.mlflow_artifact_backup backup
python -m scripts.mlflow_artifact_backup backup --backup-id 20260718T120000Z --apply
python -m scripts.mlflow_artifact_backup verify --backup-id 20260718T120000Z
python -m scripts.mlflow_artifact_backup backup-verify --backup-id 20260718T120000Z --apply
```

Jedes Objekt erhält einen SHA-256-Wert; das Werkzeug verweigert eine bereits
belegte Manifest-ID und bindet Backup-ID, Quellschlüssel, Zielschlüssel, Größe
und Hash. Das ist ein anwendungsseitiger Überschreibschutz, kein Object Lock.
Der Ziel-Bucket darf nicht dieselben Credentials wie der operative Bucket
verwenden.

Der Railway-Cron-Service `mlflow-artifact-backup` führt täglich um `03:17 UTC`
`backup-verify --apply` aus. Er beendet sich nach dem Lauf; ein erfolgreicher
Job bedeutet deshalb, dass jedes neu kopierte Objekt unmittelbar aus dem
Backup-Bucket zurückgelesen und gegen Größe und SHA-256 geprüft wurde.

## Restore-Drill

Der Restore überschreibt absichtlich nie `mlflow/`. Er akzeptiert nur einen
isolierten Präfix `restore-drills/.../` in einem separaten Restore-Bucket und
prüft alle Zielschlüssel vor dem ersten Schreibvorgang auf Kollisionen:

```bash
python -m scripts.mlflow_artifact_backup restore \
  --backup-id 20260718T120000Z \
  --destination-prefix restore-drills/20260718/ \
  --apply
```

Vollständiger vierteljährlicher Drill:

1. Temporären PostgreSQL-Restore aus dem gewählten Railway-Backup erzeugen.
2. Artefaktbackup verifizieren und in den isolierten Restore-Bucket kopieren.
3. Temporären, nicht öffentlich erreichbaren MLflow-Service mit Restore-DB und
   Restore-Bucket starten.
4. Run `44dd712b9bd84c35a41e8ab9d1a87cb3`, Modell
   `skipp-pre-a0` Version 1, Alias `candidate` und Artifact ID
   `71831770afe43bdd424aa7ab` abrufen.
5. `models:/skipp-pre-a0@candidate` laden und eine endliche Wahrscheinlichkeit
   im Intervall `[0,1]` berechnen.
6. Objektzahl und Gesamtbytes mit dem Backupmanifest vergleichen.
7. Drill-Ergebnis und Zeiten dokumentieren; temporäre Ressourcen erst danach
   entfernen. Produktionsdaten werden zu keinem Zeitpunkt überschrieben.

## Restart und Upgrade

1. Vorher DB-Backup plus verifiziertes Artefaktbackup erstellen.
2. Nur eine Service-Replik verwenden; `MLFLOW_WORKERS=2` sind Prozesse in
   derselben Replik.
3. Deployment starten. Railway prüft `/health` für höchstens 60 Sekunden.
4. Erwartete Reihenfolge in den Logs: Tracking-Migration, Auth-Migration,
   Serverstart. Jeder Fehler beendet den Container fail-closed.
5. Danach ausführen:

```bash
python -m scripts.check_pre_a0_mlflow_health \
  --tracking-uri https://mlflow-tracking-production-f8ba.up.railway.app \
  --username "$PRE_A0_MLFLOW_MONITOR_USERNAME" \
  --password "$PRE_A0_MLFLOW_MONITOR_PASSWORD" \
  --output /tmp/pre-a0-mlflow-health.json
```

6. Unauthentifiziert muss `/health` `200`, die Alias-API dagegen `401`
   liefern. Authentifiziert müssen Candidate-Alias, Run, Artifact ID,
   Runtime-Vertrag und Ablaufdatum stimmen.

## Rollback

### Code-/Containerfehler ohne Migration

1. Railway auf das letzte grüne MLflow-Deployment zurückrollen.
2. Health-Check erneut ausführen.
3. Keine A0-/PRE-A0-Worker-Variable verändern.

### Fehlgeschlagene oder inkompatible Datenbankmigration

1. MLflow-Service stoppen, damit keine weiteren Writes erfolgen.
2. PostgreSQL auf das unmittelbar vor dem Upgrade erstellte Backup
   wiederherstellen.
3. Das vorherige MLflow-Image mit der wiederhergestellten DB starten.
4. Health-, Alias-, Run- und Modell-Ladetest durchführen.
5. Erst nach belegter Konsistenz die Domain wieder freigeben.

### Verdacht auf Credential-Kompromittierung

1. Öffentliche Domain entfernen oder Access-Proxy sperren.
2. Pilot-, Monitor- und Admin-Passwörter sowie Flask-Secret rotieren.
3. Bucket-Zugriffsschlüssel rotieren und Referenzvariablen aktualisieren.
4. Auth-/Auditdaten auf unbekannte Benutzer, Rollen, Runs und Aliasänderungen
   prüfen.
5. Aus sauberem Backup wiederherstellen, wenn Integrität nicht belegbar ist.

## Monitoring und Eskalation

- Railway: `/health`, Restart-Status und Deployment-Logs.
- GitHub Actions: halbstündlicher, fail-closed Candidate-/Expiry-Check mit
  einem ausschließlich lesenden MLflow-Benutzer.
- Grafana Cloud: PRE-A0-Scrape, Modellbereitschaft, Kalibrierung,
  Runtimefehler, Input-Drift und fehlende Shadow-Snapshots.
- Ablaufwarnung ab 14 Tagen; ab `review_after` kritisch und keine Promotion.
- `candidate` oder `shadow` in MLflow verändern niemals automatisch den
  Worker-Vertrag.

## Noch auszuführende externe Drill-Aktionen

Die Backup-Zeitpläne, der zweite Bucket, dessen eingeschränkte Credentials und
der erste Restore-Drill werden nach einer exakten Änderungsvorschau gesetzt.
Bis der erste Drill bestanden ist, gilt der Recovery-Nachweis als
**implementiert, aber operativ noch nicht verifiziert**.
