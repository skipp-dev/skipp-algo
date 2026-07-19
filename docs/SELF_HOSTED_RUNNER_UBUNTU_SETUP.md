# Self-hosted Ubuntu Runner für skipp-algo einrichten

Der Laptop kann vollständig als dedizierter Ubuntu-Runner eingerichtet werden. Eine wichtige Besonderheit vorweg: skipp-algo erkennt derzeit nur einen Windows-Self-hosted-Runner, weil der Resolver fest `self-hosted + windows + x64` verlangt. Nach der Hardwareeinrichtung brauchen wir deshalb einen kleinen Repository-PR, der die Runner-Architektur sauber auf Linux umstellt. Siehe [`scripts/resolve_workflow_runner.py`](../scripts/resolve_workflow_runner.py).

Die Einrichtung besteht damit aus vier Etappen:

1. Laptop vollständig mit Ubuntu neu aufsetzen.
2. Docker, Python und GPU vorbereiten.
3. Laptop bei GitHub als Self-hosted Runner registrieren.
4. skipp-algo auf Linux-Routing umstellen und einen kontrollierten Pilotlauf durchführen.

## Phase 1: Vorbereitung

### 1. Daten sichern

Die Ubuntu-Installation wird Windows und sämtliche Daten auf dem Laptop löschen.

Sichere daher vorher:

- persönliche Dateien;
- Browserdaten;
- BitLocker-Wiederherstellungsschlüssel;
- eventuell benötigte Windows-Lizenzen;
- GPU-Modell und Laptop-Modell;
- BIOS-/Herstellerzugangsdaten.

Prüfe außerdem das genaue GPU-Modell. Nur eine NVIDIA-GPU kann den vorhandenen CUDA-Pfad direkt verwenden. Bei AMD oder Intel funktioniert der Rechner weiterhin als schneller CPU-Runner, darf aber zunächst nicht die Labels `gpu` und `priority-gpu` erhalten.

### 2. Ubuntu-Installationsstick erstellen

Benötigt werden:

- USB-Stick mit mindestens 12 GB;
- Ubuntu Desktop 24.04 LTS;
- Rufus oder balenaEtcher.

Ubuntu 24.04 LTS herunterladen:

[Ubuntu Desktop herunterladen](https://ubuntu.com/download/desktop)

Dann unter Windows:

1. Rufus oder balenaEtcher starten.
2. Ubuntu-ISO auswählen.
3. Den korrekten USB-Stick auswählen.
4. Image schreiben.
5. Warten, bis die Verifikation abgeschlossen ist.

Das bloße Kopieren der ISO-Datei auf den Stick reicht nicht. Ubuntu beschreibt den Vorgang hier: [Ubuntu-Installationsstick erstellen](https://ubuntu.com/desktop/docs/en/latest/how-to/create-a-bootable-usb-stick/).

### 3. BIOS konfigurieren

Laptop neu starten und das Bootmenü öffnen. Übliche Tasten sind:

- `F12`
- `F2`
- `Esc`
- `F10`

Im BIOS nach Möglichkeit einstellen:

- UEFI aktiviert;
- USB-Boot erlaubt;
- Virtualisierung aktiviert, etwa `Intel VT-x` oder `AMD-V`;
- automatisches Einschalten nach Stromausfall aktiviert, falls vorhanden;
- Secure Boot zunächst aktiviert lassen.

Secure Boot kann mit Ubuntu und signierten NVIDIA-Treibern funktionieren. Nur wenn der NVIDIA-Treiber später trotz korrekter Installation nicht geladen wird, sollten wir diesen Punkt erneut prüfen.

## Phase 2: Ubuntu installieren

### 4. Ubuntu vollständig neu installieren

Vom USB-Stick booten und „Install Ubuntu“ wählen.

Empfohlene Auswahl:

- Ubuntu 24.04 LTS;
- normale oder minimale Installation;
- Updates während der Installation herunterladen;
- Drittanbieter-Treiber installieren;
- „Festplatte löschen und Ubuntu installieren“;
- Zeitzone `Europe/Berlin`;
- Administrationskonto beispielsweise `runner-admin`;
- Rechnername später `skipp-runner-01`.

Ubuntu führt durch den vollständigen Installationsprozess: [Ubuntu Desktop installieren](https://ubuntu.com/download/help/install-desktop-latest).

#### Festplattenverschlüsselung

Vollverschlüsselung schützt bei Diebstahl, verlangt aber normalerweise nach jedem Neustart eine manuelle Passphrase. Für einen unbeaufsichtigten Dauerläufer ist das ein Zielkonflikt.

Meine Empfehlung für diesen dedizierten Laptop:

- Verschlüsselung verwenden, wenn du bei Neustarts physisch eingreifen kannst.
- Andernfalls zunächst keine Vollverschlüsselung verwenden, dafür keinerlei dauerhafte Produktions-Secrets auf dem Rechner speichern.

Eine TPM-gestützte automatische Entschlüsselung wäre später möglich, ist aber kein sinnvoller Bestandteil des ersten Piloten.

### 5. System aktualisieren

Nach dem ersten Login ein Terminal öffnen:

```bash
sudo apt update
sudo apt full-upgrade -y
sudo reboot
```

Nach dem Neustart:

```bash
sudo apt install -y \
  git \
  curl \
  ca-certificates \
  jq \
  unzip \
  zip \
  build-essential \
  python3 \
  python3-venv \
  python3-pip \
  python-is-python3 \
  pipx \
  ubuntu-drivers-common \
  ufw \
  unattended-upgrades
```

Prüfen:

```bash
python --version
git --version
curl --version
```

Erwartet wird Python 3.12 unter Ubuntu 24.04.

### 6. Rechnernamen setzen

```bash
sudo hostnamectl set-hostname skipp-runner-01
sudo timedatectl set-timezone Europe/Berlin
timedatectl
```

Der Runner selbst arbeitet intern weiterhin korrekt mit UTC-Zeitstempeln. Die lokale Zeitzone dient primär verständlichen Systemprotokollen.

### 7. Dedizierten Runner-Benutzer anlegen

GitHub-Jobs sollen nicht unter deinem Administrationskonto und nicht als `root` laufen:

```bash
sudo adduser --disabled-password --gecos "" skipp-runner
```

Arbeitsverzeichnisse vorbereiten:

```bash
sudo mkdir -p /home/skipp-runner/actions-runner
sudo mkdir -p /opt/runner-venvs/skipp-algo
sudo chown -R skipp-runner:skipp-runner /home/skipp-runner
sudo chown -R skipp-runner:skipp-runner /opt/runner-venvs
```

### 8. Standby deaktivieren

Ein geschlossener Deckel oder längere Inaktivität darf den Runner nicht stoppen:

```bash
sudo systemctl mask \
  sleep.target \
  suspend.target \
  hibernate.target \
  hybrid-sleep.target
```

Prüfen:

```bash
systemctl status sleep.target
systemctl status suspend.target
```

Beide sollten als `masked` erscheinen.

Am Laptop zusätzlich:

- Netzteil dauerhaft anschließen;
- falls unterstützt, Batterielimit auf etwa 70–80 % setzen;
- gute Belüftung sicherstellen;
- bevorzugt Ethernet verwenden.

### 9. Firewall aktivieren

Der GitHub Runner benötigt ausgehende HTTPS-Verbindungen, aber keine eingehenden offenen Ports:

```bash
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw enable
sudo ufw status verbose
```

Kein Router-Portforwarding einrichten.

Falls später SSH benötigt wird, sollte es nur aus deinem lokalen Netzwerk oder über eine abgesicherte VPN-Lösung erlaubt werden.

## Phase 3: Docker installieren

Einige skipp-algo-Gates führen `docker build` aus. GitHub verlangt Linux für Docker-Container-Actions und Service-Container. [GitHub Self-hosted Runner Reference](https://docs.github.com/en/actions/reference/runners/self-hosted-runners)

### 10. Offizielles Docker-Repository einrichten

```bash
sudo apt update
sudo apt install -y ca-certificates curl
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
  -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
```

Repository hinzufügen:

```bash
sudo tee /etc/apt/sources.list.d/docker.sources >/dev/null <<EOF
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: $(. /etc/os-release && echo "${UBUNTU_CODENAME:-$VERSION_CODENAME}")
Components: stable
Architectures: $(dpkg --print-architecture)
Signed-By: /etc/apt/keyrings/docker.asc
EOF
```

Docker installieren:

```bash
sudo apt update
sudo apt install -y \
  docker-ce \
  docker-ce-cli \
  containerd.io \
  docker-buildx-plugin \
  docker-compose-plugin
```

Dienst aktivieren:

```bash
sudo systemctl enable --now docker
sudo systemctl status docker
```

Runner-Benutzer berechtigen:

```bash
sudo usermod -aG docker skipp-runner
```

Test zunächst als Administrator:

```bash
sudo docker run --rm hello-world
```

Dann als Runner-Benutzer:

```bash
sudo -iu skipp-runner
docker version
docker run --rm hello-world
exit
```

Die Mitgliedschaft in der Docker-Gruppe entspricht praktisch weitreichenden Systemrechten. Deshalb darf dieser Rechner ausschließlich CI-Aufgaben ausführen. Offizielle Anleitung: [Docker Engine unter Ubuntu](https://docs.docker.com/engine/install/ubuntu/).

## Phase 4: NVIDIA-GPU einrichten

Diesen Abschnitt nur durchführen, wenn tatsächlich eine NVIDIA-GPU vorhanden ist.

### 11. GPU erkennen

```bash
lspci | grep -Ei 'vga|3d|nvidia|amd|intel'
```

Bei NVIDIA:

```bash
sudo ubuntu-drivers list --gpgpu
sudo ubuntu-drivers install --gpgpu
sudo reboot
```

Nach dem Neustart:

```bash
nvidia-smi
```

Die Ausgabe muss die GPU, Treiberversion und eine unterstützte CUDA-Version anzeigen. Ubuntu empfiehlt `ubuntu-drivers` insbesondere auch wegen signierter, Secure-Boot-kompatibler Treiber. [Ubuntu: NVIDIA-Treiber installieren](https://documentation.ubuntu.com/server/how-to/graphics/install-nvidia-drivers/)

Für den vorhandenen PyTorch-Build muss der Treiber CUDA 12.9 unterstützen. Die Anzeige von `nvidia-smi` sollte daher bei `CUDA Version` mindestens `12.9` nennen.

Der vollständige CUDA-Compiler ist zunächst nicht nötig. Der PyTorch-Wheel aus `requirements-rl-gpu.txt` bringt seine benötigten CUDA-Laufzeitkomponenten mit; der Host benötigt primär einen hinreichend neuen NVIDIA-Treiber.

### 12. CUDA-PyTorch isoliert testen

Als Runner-Benutzer:

```bash
sudo -iu skipp-runner
python -m venv ~/gpu-check
source ~/gpu-check/bin/activate
python -m pip install --upgrade pip
python -m pip install \
  --index-url https://download.pytorch.org/whl/cu129 \
  'torch==2.12.1+cu129'
```

Dann:

```bash
python -c "
import torch
print('torch:', torch.__version__)
print('cuda available:', torch.cuda.is_available())
print('device count:', torch.cuda.device_count())
print('device:', torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'none')
"
```

Erwartet:

```text
torch: 2.12.1+cu129
cuda available: True
device count: 1
device: <Name deiner GPU>
```

Danach:

```bash
deactivate
exit
```

Falls `cuda available: False` erscheint, den Runner zunächst ohne `gpu`-Labels registrieren.

## Phase 5: Repository privat machen

### 13. Vor der Runner-Anbindung auf privat umstellen

Der Self-hosted Runner sollte nicht produktiv mit einem öffentlichen Repository verbunden werden. GitHub warnt ausdrücklich davor, weil öffentlich ausgelöster Workflow-Code den Rechner kompromittieren kann. [GitHub: Sichere Verwendung von Self-hosted Runnern](https://docs.github.com/en/actions/reference/security/secure-use)

In GitHub:

1. Repository `skipp-dev/skipp-algo` öffnen.
2. `Settings`.
3. `General`.
4. Ganz nach unten zu `Danger Zone`.
5. `Change repository visibility`.
6. `Make private`.
7. Repository-Namen zur Bestätigung eingeben.

Wichtig: Bereits bestehende öffentliche Forks oder lokale Kopien werden dadurch nicht zurückgerufen.

## Phase 6: Runner bei GitHub registrieren

### 14. Registrierungsseite öffnen

Im nun privaten Repository:

1. `Settings`
2. `Actions`
3. `Runners`
4. `New self-hosted runner`
5. Betriebssystem `Linux`
6. Architektur `x64`

GitHub zeigt anschließend aktuelle Downloadbefehle und einen kurzlebigen Registrierungstoken. Verwende exakt die dort angezeigte Runner-Version; keine Versionsnummer aus einer älteren Anleitung übernehmen.

### 15. Runner herunterladen

Auf dem Laptop:

```bash
sudo -iu skipp-runner
cd ~/actions-runner
```

Jetzt die von GitHub angezeigten Befehle ausführen. Sie sehen ungefähr so aus:

```bash
curl -o actions-runner-linux-x64-<VERSION>.tar.gz -L \
  https://github.com/actions/runner/releases/download/v<VERSION>/actions-runner-linux-x64-<VERSION>.tar.gz
```

Danach den von GitHub angezeigten SHA-256-Check ausführen und erst anschließend entpacken:

```bash
tar xzf actions-runner-linux-x64-<VERSION>.tar.gz
```

### 16. Runner konfigurieren

Der GitHub-Befehl sieht grundsätzlich so aus:

```bash
./config.sh \
  --url https://github.com/skipp-dev/skipp-algo \
  --token <KURZLEBIGER_REGISTRIERUNGSTOKEN>
```

Bei den Rückfragen folgende Werte verwenden:

- Runner group: `Default`
- Runner name: `skipp-linux-gpu-01`
- Additional labels bei NVIDIA:

```text
priority-cron,priority-gpu,gpu
```

- Additional labels ohne funktionierende NVIDIA-GPU:

```text
priority-cron
```

- Work folder: `_work`

GitHub fügt automatisch hinzu:

```text
self-hosted
Linux
X64
```

Den Registrierungstoken nicht speichern, nicht in eine Datei schreiben und nicht ins Repository übernehmen.

Konfiguration beenden:

```bash
exit
```

### 17. Runner als Systemdienst installieren

Als Administrationsbenutzer:

```bash
cd /home/skipp-runner/actions-runner
sudo ./svc.sh install skipp-runner
sudo ./svc.sh start
sudo ./svc.sh status
```

Zusätzlich:

```bash
systemctl list-units --type=service | grep actions.runner
```

Protokolle ansehen:

```bash
sudo journalctl -u 'actions.runner*' -n 100 --no-pager
```

GitHub unterstützt den automatischen Betrieb als `systemd`-Dienst offiziell. [GitHub: Runner als Dienst konfigurieren](https://docs.github.com/en/actions/how-tos/manage-runners/self-hosted-runners/configure-the-application)

### 18. GitHub-Anzeige prüfen

Unter:

```text
Repository
→ Settings
→ Actions
→ Runners
```

muss erscheinen:

```text
skipp-linux-gpu-01
Status: Idle
Labels:
- self-hosted
- Linux
- X64
- priority-cron
- priority-gpu
- gpu
```

Damit ist der Laptop technisch als Self-hosted Runner erkannt.

Er wird aber noch nicht von skipp-algo ausgewählt, weil das Repository momentan Windows-Labels verlangt.

## Phase 7: skipp-algo sicher auf Linux umstellen

### 19. Während der Migration Hosted-only erzwingen

In GitHub:

```text
Settings
→ Secrets and variables
→ Actions
→ Variables
```

Repository-Variable setzen:

```text
SMC_FORCE_GH_HOSTED=true
```

Damit können wir den Runner registrieren und prüfen, ohne dass bestehende Workflows versehentlich auf die noch nicht vollständig unterstützte Linux-Maschine wechseln.

`SMC_GH_HOSTED_RUNNER` sollte weiterhin `ubuntu-latest` bleiben. Diese Variable ist der GitHub-hosted Fallback und darf nicht auf den Self-hosted Runnernamen gesetzt werden.

### 20. Notwendiger Repository-PR

Aktuell steht in [`scripts/resolve_workflow_runner.py`](../scripts/resolve_workflow_runner.py):

```python
_DEFAULT_SELF_HOSTED_LABELS = ["self-hosted", "windows", "x64"]
```

Das muss zu folgendem Vertrag migriert werden:

```python
_DEFAULT_SELF_HOSTED_LABELS = ["self-hosted", "linux", "x64"]
```

Der PR muss außerdem aktualisieren:

- alle Resolver-Tests;
- Windows-spezifische Workflow-Annahmen;
- Python-Auflösung auf dem Linux-Runner;
- Runner-Dokumentation;
- Persistent-Venv-Pfade;
- Kommentare und Guards, die heute ausdrücklich Windows voraussetzen;
- einen kontrollierten Linux-Runner-Smoke-Workflow.

Nur die eine Python-Zeile zu ändern wäre zu wenig, weil mehrere Tests den alten Windows-Vertrag absichtlich festschreiben.

Diesen PR sollte Codex übernehmen, sobald der Runner in GitHub als `Idle` sichtbar ist.

### 21. Repository-Variablen konfigurieren

Nach dem Linux-Migrations-PR:

```text
SMC_SELF_HOSTED_LABEL=generic-hosted-only
SMC_PRIORITY_CRON_SELF_HOSTED_LABEL=priority-cron
SMC_PRIORITY_CRON_GPU_SELF_HOSTED_LABEL=priority-gpu
SMC_CI_SELF_HOSTED_LABEL=<nicht gesetzt>
SMC_PERSISTENT_VENV_ROOT=/opt/runner-venvs/skipp-algo
SMC_GH_HOSTED_RUNNER=ubuntu-latest
```

Das entspricht dem vorhandenen Ein-Runner-Modell in [`docs/self_hosted_runner_reservation_runbook.md`](self_hosted_runner_reservation_runbook.md).

`generic-hosted-only` darf nicht als echtes Runner-Label hinzugefügt werden. Es ist absichtlich ein Nicht-Treffer, damit gewöhnliche Jobs auf GitHub-hosted zurückfallen.

### 22. Runner-Inventarzugriff ermöglichen

Der vorhandene Resolver fragt über die GitHub API ab, ob der Runner:

- online;
- nicht beschäftigt;
- mit den erforderlichen Labels versehen ist.

Für diesen API-Aufruf benötigt er Zugriff auf das Runner-Inventar. GitHub verlangt für einen Fine-grained Token:

```text
Repository access:
- Only selected repositories
- skipp-algo

Repository permissions:
- Administration: Read-only
```

[GitHub REST API: Self-hosted Runner eines Repositorys auflisten](https://docs.github.com/en/rest/actions/self-hosted-runners)

Den Token als Repository-Secret speichern:

```text
GH_PAT
```

Der Token gehört ausschließlich in GitHub Secrets, niemals auf die Runner-Festplatte oder in `.env`.

### 23. Smoke-Test durchführen

Der Linux-Migrations-PR sollte einen manuellen Testjob enthalten, der ausdrücklich verlangt:

```yaml
runs-on: [self-hosted, linux, x64, priority-cron]
```

Der Job sollte ohne Produktions-Secrets prüfen:

```bash
hostname
uname -a
python --version
git --version
docker version
nvidia-smi
```

Erfolgskriterien:

- GitHub zeigt `Running on skipp-linux-gpu-01`;
- Betriebssystem ist Linux;
- Python ist 3.12;
- Docker ist erreichbar;
- bei NVIDIA wird die GPU angezeigt;
- der Job endet grün.

### 24. Produktiven Pilot aktivieren

Erst nach grünem Smoke-Test:

1. `SMC_FORCE_GH_HOSTED` löschen oder auf `false` setzen.
2. `rl-research-training` manuell mit wenigen Schritten starten.
3. `prefer_gpu=true` auswählen.
4. Im `select-runner`-Job prüfen:

```text
runner_environment=self-hosted
resolution_reason=matched_idle_self_hosted_runner
matched_runner_name=skipp-linux-gpu-01
```

5. Im GPU-Probe-Schritt prüfen:

```text
cuda_available=true
cuda_device_count=1
```

6. Erst danach weitere Batch-/Cron-Workflows freigeben.

## Phase 8: Neustart- und Fallback-Test

### 25. Neustartbeständigkeit prüfen

Laptop neu starten:

```bash
sudo reboot
```

Nach einigen Minuten in GitHub prüfen:

```text
skipp-linux-gpu-01
Status: Idle
```

Lokal:

```bash
sudo systemctl status 'actions.runner*'
docker version
nvidia-smi
```

### 26. Hosted-Fallback prüfen

Runner bewusst stoppen:

```bash
cd /home/skipp-runner/actions-runner
sudo ./svc.sh stop
```

Einen dafür vorgesehenen Workflow starten. Der Resolver sollte melden:

```text
runner_environment=github-hosted
resolution_reason=no_idle_matching_self_hosted_runner
```

Danach Runner wieder starten:

```bash
sudo ./svc.sh start
```

Damit ist bewiesen, dass ein ausgeschalteter Laptop die zulässigen Workflows nicht dauerhaft blockiert.

## Abschlusskriterien

Die Einrichtung ist erst abgeschlossen, wenn alle Punkte erfüllt sind:

- Repository ist privat.
- Ubuntu 24.04 LTS läuft stabil.
- Standby und Ruhezustand sind deaktiviert.
- Docker funktioniert unter `skipp-runner`.
- NVIDIA-GPU funktioniert gegebenenfalls mit PyTorch CUDA.
- GitHub zeigt `skipp-linux-gpu-01` als `Idle`.
- Runner startet nach einem Reboot automatisch.
- Linux-Migrations-PR ist gemergt.
- Repository-Variablen und `GH_PAT` sind gesetzt.
- Smoke-Test lief tatsächlich auf `skipp-linux-gpu-01`.
- GPU-Pilot lief mit `cuda_available=true`.
- Hosted-Fallback wurde erfolgreich geprüft.

Realistisch solltest du für Neuinstallation und Downloads etwa zwei bis vier Stunden einplanen. Sobald Schritt 18 erreicht ist und der Runner in GitHub als `Idle` angezeigt wird, kann Codex die notwendige Linux-Migration im Repository vollständig übernehmen und bis zum getesteten PR führen.
