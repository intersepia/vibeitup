# Folio · Bilder, gut sortiert.

Ein lokales **Image Sorting System** mit **FastAPI, Vue 3 und Vite**. Bilder auswählen, ins passende Album verschieben, Duplikate erkennen und Entscheidungen rückgängig machen. Ohne Docker, ohne Cloud und ohne Bild-Uploads.

## Das kann Folio

- Drei Spalten: Quellordner-Baum, responsive Vier-Spalten-Galerie und Ziel-Alben.
- Mehrfachauswahl per Klick, Strg/⌘-Klick und Shift-Klick; Tastenkürzel und Auswahlstatus.
- Suche nach Dateiname/Ordner, Sortierung nach Name/Datum/Größe und alternative Listenansicht.
- EXIF-korrekte, lokal gecachte Thumbnails bis **400 × 400 px**; vergrößerte JPEG-Vorschauen bis 1920 px, auch für TIFF.
- **Inkrementeller SHA-1-Index** mit persistentem JSON-Cache; bytegleiche Bilder im Eingang werden mit vorhandenen Album-Bildern verglichen.
- Batch-Verschiebungen, automatische Namenszähler, reversibler Papierkorb und explizite Duplikat-Ablage.
- Persistentes SQLite-Transaktionsjournal, Undo über Neustarts hinweg, Rollback bei Fehlern und Wiederherstellung unterbrochener Transaktionen.
- Lokale Schriftdateien, responsive Oberfläche, Tastaturbedienung und optional eine offline verfügbare Demo-Bibliothek.

> **Die App verschiebt echte Dateien.** Zum Kennenlernen die Demo verwenden und wichtige Originale zusätzlich sichern. Vorschauen verändern die Originale nicht. Folio hat keinen Endpunkt zum endgültigen Löschen.

## 1. Voraussetzungen

- **Python 3.11 oder neuer**, inklusive `venv` und `pip`.
- **Node.js 22.12+** (empfohlen: aktuelles LTS) oder **20.19+**, inklusive npm, für den Frontend-Build.
- Linux, macOS oder Windows; kein Docker und keine separate Datenbankinstallation.
- Internet nur für die erstmalige Installation der Python-/npm-Pakete. Danach läuft die Anwendung einschließlich Schriften und Demo offline.

Unter Debian/Ubuntu gegebenenfalls zuerst `sudo apt install python3-venv` ausführen. Unter Windows Python inklusive Python Launcher installieren und Node.js zum PATH hinzufügen.

## 2. Schnellstart

### Linux / macOS

```bash
./start.sh
```

Falls das Ausführungsbit beim Kopieren verloren gegangen ist:

```bash
chmod +x start.sh
./start.sh
```

### Windows

In einer Konsole im Projektordner:

```bat
start.bat
```

In PowerShell: `./start.bat`.

Die Skripte erstellen `.venv`, installieren die Abhängigkeiten, bauen Vue und starten **einen** FastAPI-/Uvicorn-Prozess. Backend, API und fertiges Frontend werden über dieselbe Adresse ausgeliefert:

**http://127.0.0.1:8000** · API-Dokumentation: **http://127.0.0.1:8000/docs**

Beenden mit **Strg+C**. Der Standardstart erzeugt eine leere Bibliothek in `data/`, keine Demobilder.

### Erst einmal ausprobieren

```bash
# Nur in einem neuen bzw. vollständig leeren Datenordner:
./start.sh --demo --base-path ./data/demo
```

Windows:

```bat
start.bat --demo --base-path .\data\demo
```

Die Demo enthält 18 Eingangsbilder, fünf Alben und zwei exakte Duplikate. Sie ist in der Oberfläche gekennzeichnet. Vorhandene Bildbibliotheken werden **nicht** mit Demo-Dateien befüllt; eine bereits angelegte Demo wird bei einem erneuten Aufruf nicht zurückgesetzt. Für denselben Demo-Workspace beim nächsten Start wieder `--base-path ./data/demo` verwenden oder den Pfad konfigurieren.

Die kompakten Beispielfotos liegen in `scripts/demo_assets/`; Bildquellen und Lizenzhinweise stehen in [CREDITS.md](scripts/demo_assets/CREDITS.md). Es findet beim Demo-Start kein Download statt.

### Schneller Folgestart / Offline-Start

Nach erfolgreicher Erstinstallation:

```bash
./start.sh --skip-install --no-build
```

Windows unterstützt dieselben Optionen. Weitere Argumente:

```text
--demo                  Optionale Demo in einem leeren Basis-Pfad anlegen
--base-path PATH        Anderen Bibliothekspfad für diesen Start verwenden
--host HOST             Bind-Adresse überschreiben
--port PORT             Port überschreiben
--skip-install          Bereits installierte Pakete verwenden
--no-build              Vorhandenes frontend/dist/ verwenden
```

Für einen bestimmten Python-Interpreter: `PYTHON=python3.12 ./start.sh` (Windows: Umgebungsvariable `PYTHON` auf den Interpreterpfad setzen).

## 3. Eigene Bilder und Konfiguration

Die Anwendung lädt zunächst `config.local.yaml`, sofern vorhanden, sonst `config.yaml`. Für eine persönliche Konfiguration:

```bash
cp config.yaml config.local.yaml
```

Windows: `copy config.yaml config.local.yaml`.

```yaml
# Relative Pfade beziehen sich auf den Speicherort der Konfigurationsdatei.
base_path: /home/deinname/Bilder/Folio

server:
  host: 127.0.0.1
  port: 8000

index_on_startup: true
thumbnail_size: 400
```

Windows-Pfade am besten mit `/` oder einfachen YAML-Anführungszeichen schreiben, etwa `base_path: 'D:\Bilder\Folio'`. `~` wird zum Benutzerverzeichnis aufgelöst.

Alternativ sind diese Umgebungsvariablen möglich:

| Variable | Bedeutung |
| --- | --- |
| `IMAGE_SORTER_CONFIG` | Pfad zu einer anderen YAML-Konfiguration |
| `IMAGE_SORTER_BASE_PATH` | Überschreibt `base_path` |
| `HOST` | Überschreibt die Server-Bind-Adresse |
| `PORT` | Überschreibt den Server-Port |

Konfigurationsänderungen erfordern einen Neustart. Ein anderer Basis-Pfad öffnet eine **andere Bibliothek**; bestehende Bilder werden dadurch nicht migriert.

### Verwaltete Verzeichnisse

```text
<Basis-Pfad>/
├── zur_sortieren/              # Eingang, beliebige Unterordner
│   └── Urlaub/
├── alben/                     # Bestehende und neue Alben
│   ├── Reisen/
│   └── Natur/
├── duplikate/                 # Explizit abgelegte, bestätigte Duplikate
├── trash/                     # Aussortierte Bilder, keine endgültige Löschung
├── temp/
│   ├── duplikat/
│   └── trash/
└── .image-sorter/
    ├── index.json             # SHA-1, Dateisignaturen, Abmessungen
    ├── journal.sqlite3        # Transaktionen und Undo-Status
    ├── instance.lock          # Betriebssystem-Sperre für eine App-Instanz
    └── thumbnails/            # Regenerierbare JPEG-Vorschauen
```

Alle Verzeichnisse werden beim Start angelegt. `temp/duplikat` und `temp/trash` stehen für Verarbeitungsergebnisse bereit; Verschiebungen selbst verwenden das Transaktionsjournal und brauchen keine zusätzlichen temporären Originalkopien.

1. Eigene Bilder nach `zur_sortieren/` oder in dessen Unterordner legen.
2. **Ordner neu einlesen** anklicken. Externe Dateiänderungen werden bewusst nicht dauerhaft überwacht.
3. **Eingang** zeigt alle Quellordner zusammen. Ein Unterordner zeigt dessen Bilder einschließlich weiterer Unterordner; ein Klick auf `zur_sortieren` im Baum zeigt nur die Dateien direkt im Eingangsordner.
4. Bilder auswählen und rechts ein Album anklicken. Neue Alben können direkt aus der Oberfläche angelegt werden.
5. Bei Bedarf **Rückgängig** verwenden.

Unterstützte Dateiendungen: JPG/JPEG, PNG, WebP, GIF, BMP, TIFF/TIF und AVIF. Animierte Bilder verwenden für die Vorschau das erste Bild. Beschädigte oder zu große Bilder erhalten einen Vorschau-Hinweis statt eines Galerie-Absturzes. Nicht unterstützte Dateien und versteckte Verzeichnisse bleiben unberührt.

### Album im gewünschten Ordner anlegen

Unter **Neues Album erstellen** wählst du neben dem Namen den **übergeordneten Ordner**:

- **Alle Alben (Hauptordner)** legt das Album direkt unter `alben/` an.
- Ein vorhandenes Album wie `Reisen/2026` legt das neue Album darunter an.
- Die Pfadvorschau zeigt das Ziel **relativ zum Album-Hauptordner**. Name `Portugal` und Elternordner `Reisen/2026` ergeben `Reisen/2026/Portugal`, physisch `<Basis-Pfad>/alben/Reisen/2026/Portugal`.
- Der neue Album-Button verwendet denselben vollständigen Pfad. Auch **ausgewählte Bilder direkt hierhin verschieben** schreibt genau dort hin, nicht in ein gleichnamiges Album im Hauptordner.
- Die Ordnerliste wird beim Öffnen frisch geladen und kann über das Aktualisieren-Symbol erneut eingelesen werden. Ist ein gewählter Elternordner verschwunden, wird weder dieser automatisch neu angelegt noch stillschweigend der Hauptordner verwendet.
- Gleiche Albumnamen unter unterschiedlichen Eltern sind erlaubt. Bereits vorhandene bzw. gleichwertige Namen im selben Elternordner werden ohne Überschreiben abgewiesen.

Der physische Album-Hauptordner bleibt `alben/` (die Ansicht **Alle Alben**, auch als `album_all` bezeichnet). Vorhandene Ordner und protokollierte Undo-Pfade werden nicht umbenannt. Unterordner können Schritt für Schritt angelegt und danach als Eltern ausgewählt werden.

## 4. Verschieben, Duplikate und Sicherheit

### Exakte Duplikate

SHA-1 wird mit Python `hashlib` in 1-MiB-Blöcken über den vollständigen Dateiinhalt berechnet. Größe, `mtime_ns` und `ctime_ns` vermeiden erneutes Hashen unveränderter Dateien. Der Index wird per temporärer Datei und `os.replace` atomisch ersetzt; ein beschädigter Index wird neu aufgebaut.

**Nur bytegleiche Eingangsbilder mit einem Treffer in `alben/` werden als Duplikat markiert.** Optisch ähnliche, anders komprimierte oder mit anderen EXIF-Daten gespeicherte Fotos sind keine exakten Duplikate. Zwei identische Eingangsbilder allein zählen ebenfalls noch nicht als Album-Duplikat. SHA-1 dient hier der Dateiidentität, nicht der kryptografischen Authentifizierung.

Folio verschiebt Duplikate nicht ungefragt. Im Filter **Duplikate** lassen sie sich prüfen, auswählen und über **In Duplikate ablegen** verschieben. Vor dieser Aktion wird der Albumindex erneut geprüft.

### Dateisicherheit und Undo

- Die API akzeptiert ausschließlich relative POSIX-Pfade innerhalb der verwalteten Ordner. Absolute Pfade, `..`, versteckte Pfade, Backslashes und symbolische Links werden abgewiesen.
- Verschiebeaktionen dürfen nur in `zur_sortieren/` beginnen. Andere Bereiche sind in der Oberfläche reine Ansichten.
- Namenskollisionen erhalten Zähler wie `bild_001.jpg`, `bild_002.jpg`. Existierende Ziele werden nicht überschrieben, auch bei gleichnamigen Dateien in einem Batch. Groß-/Kleinschreibung und gleichwertige Unicode-Schreibweisen werden vorsorglich als Kollision behandelt, damit die Ablage auf Linux, macOS und Windows konsistent bleibt. Bei sehr langen Zielnamen wird nur der Stamm passend gekürzt; Erweiterung, Zähler und protokollierter Originalpfad bleiben erhalten.
- Dateien werden innerhalb eines Volumes über Hardlink + Unlink verschoben. Falls das nicht möglich ist, erfolgt eine exklusiv angelegte, synchronisierte Kopie. Vor dem Entfernen der Quelle werden Zielinhalt und Dateiidentität geprüft. Bei Fehlern wird eine inzwischen von einem anderen Programm ersetzte Zieldatei nicht als temporäre Kopie gelöscht. Nicht sicher bereinigbare Kopien bleiben zur Prüfung erhalten und werden als `interrupted` protokolliert.
- Jeder Batch wird **vor** dem ersten Dateischritt persistent protokolliert. Bei Fehlern werden bereits ausgeführte Schritte nach Möglichkeit zurückgesetzt.
- Undo setzt den zuletzt erfolgreich abgeschlossenen, noch nicht rückgängig gemachten **gesamten Batch** zurück. Der Originalpfad muss frei sein und die Zieldatei noch denselben Hash haben. Ein Konflikt bricht die Vorprüfung ohne Überschreiben ab.
- Unterbrochene Verschiebungen werden beim Neustart zurückgesetzt; unterbrochenes Undo wird vervollständigt. Mehrdeutige Zustände, etwa zwei vorhandene Kopien, bleiben zur manuellen Prüfung erhalten und erscheinen als **Prüfung nötig** im Protokoll.
- Ein Prozess-Lock verhindert mehrere Folio-Instanzen auf demselben Basis-Pfad. Innerhalb der App serialisiert ein Thread-Lock die Index- und Verschiebeaktionen.
- Neue Alben selbst werden nicht per Undo entfernt. Die Undo-Historie umfasst Dateiverschiebungen, nicht Such-/Filter-/Auswahländerungen.
- Ein fehlgeschlagenes Index-/Cache-Update macht eine bereits abgeschlossene Verschiebung nicht zu einem Fehler. Die Oberfläche zeigt dafür einen separaten Hinweis (`index_warning` in `/api/status`). Nach vollständig gelesenem Scan bleiben die aktuellen Zähler auch bei einem Cache-Schreibfehler im Arbeitsspeicher verfügbar. „Neu einlesen“ wiederholt nur die Indexierung, nicht die Verschiebung.

Das ist ein fehlertolerantes Dateisystem-Journal, keine hardwareseitig atomare Mehrdatei-Transaktion und **kein Ersatz für ein Backup**. Während des Sortierens dieselben Dateien möglichst nicht gleichzeitig in anderen Programmen bearbeiten. Lokale Fremdprozesse mit Schreibzugriff auf die Bibliothek sind keine isolierte Sicherheitsgrenze. Für Metadaten und SQLite einen lokalen Datenträger verwenden; Netzwerkdateisysteme können andere Sperr-/Durability-Eigenschaften haben.

Die API besitzt **keine Anmeldung**. Standardmäßig lauscht der Server nur auf Loopback. `--host 0.0.0.0` ausschließlich in einem vertrauenswürdigen Netz oder einer geschützten Vorschau verwenden, niemals ungeschützt ins Internet stellen. Fremde Browser-Origins werden für schreibende API-Aufrufe abgewiesen; dies ersetzt keine Authentifizierung. Die normale Anwendung lädt keinerlei externe Ressourcen.

## 5. API

Interaktive Schemata, Eingaben und Antworten: `/docs` beziehungsweise `/openapi.json`. Die optionale Swagger-Oberfläche unter `/docs` lädt ihre UI-Assets standardmäßig von einem CDN; `/openapi.json` und die eigentliche Bildsortier-Oberfläche sind vollständig lokal verfügbar.

| Methode | Endpunkt | Funktion |
| --- | --- | --- |
| GET | `/api/health` | Erreichbarkeit |
| GET | `/api/status` | Bibliotheksstatistik, Basis-Pfad, Undo-Status |
| GET | `/api/folders/source` | Rekursiver Quellbaum mit direkten/rekursiven Bildanzahlen |
| GET | `/api/folders/albums` | Albumbaum |
| POST | `/api/folders/albums` | Album erstellen: `{ "name": "Portugal", "parent": "Reisen/2026" }`; `parent` optional |
| GET | `/api/images?path=zur_sortieren&recursive=true` | Bilder, Größen, Abmessungen, Hash und Duplikat-Treffer |
| GET | `/api/thumb/{path}` | JPEG-Thumbnail, maximal 400 px |
| GET | `/api/preview/{path}` | Browserkompatible Großvorschau, maximal 1920 px |
| GET | `/api/image/{path}` | Unveränderte Originaldatei |
| POST | `/api/index` | Index inkrementell neu einlesen |
| POST | `/api/action/move` | Auswahl in ein existierendes Album verschieben |
| POST | `/api/action/trash` | Auswahl in `trash/` verschieben |
| POST | `/api/action/duplicates` | Bestätigte Duplikate in `duplikate/` ablegen |
| POST | `/api/action/undo` | Letzten abgeschlossenen Batch rückgängig machen |
| GET | `/api/logs?limit=50&offset=0` | Persistente Transaktionen, neueste zuerst |

`parent` beim Anlegen und `target_album` beim Verschieben sind relativ zu `alben/`, ohne den Hauptordner-Präfix. `parent: ""` oder ein weggelassenes `parent` wählt den Hauptordner; andere Eltern müssen bereits existieren. Name und Elternpfad bleiben getrennte Felder. Der vollständige relative Album-Pfad darf maximal 500 Zeichen haben.

`path` und `files` sind relativ zum Basis-Pfad, beispielsweise `zur_sortieren/Urlaub/bild.jpg`. `target_album` ist relativ zu `alben/`, beispielsweise `Reisen` oder ein bestehendes `Reisen/2025`. Pfadsegmente in URLs korrekt URL-encodieren. Ohne `recursive=true` listet `/api/images` nur den angegebenen Ordner.

```bash
curl -X POST http://127.0.0.1:8000/api/folders/albums \
  -H 'Content-Type: application/json' \
  -d '{"name":"Reisen"}'

curl -X POST http://127.0.0.1:8000/api/folders/albums \
  -H 'Content-Type: application/json' \
  -d '{"name":"Portugal","parent":"Reisen"}'

curl -X POST http://127.0.0.1:8000/api/action/move \
  -H 'Content-Type: application/json' \
  -d '{"files":["zur_sortieren/Urlaub/bild.jpg"],"target_album":"Reisen"}'

curl -X POST http://127.0.0.1:8000/api/action/undo
```

Pro Aktion 1–500 unterschiedliche Dateien. Fehler verwenden `{"detail": "…"}`: 400 ungültiger Pfad/Aktion, 403 fremde Origin, 404 Datei fehlt, 409 Dateikonflikt/Undo-Konflikt, 415 nicht unterstützter Dateityp, 422 ungültige Eingabe oder nicht erzeugbare Vorschau. Python `logging` schreibt technische Details in die Serverkonsole; Dateitransaktionen bleiben zusätzlich in SQLite erhalten.

## 6. Entwicklung und Tests

### Backend separat

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
```

Windows: `py -3 -m venv .venv`, danach `.venv\Scripts\activate` in cmd oder `.venv\Scripts\Activate.ps1` in PowerShell; anschließend dieselben `pip`-/`python`-Befehle. Eine aktivierte Umgebung ist optional, wenn der Interpreter direkt als `.venv/bin/python` bzw. `.venv\Scripts\python.exe` aufgerufen wird.

### Vue separat

```bash
cd frontend
npm ci
npm run dev
```

Frontend: **http://localhost:5173**. Vite lauscht auf `0.0.0.0`, erlaubt lokale Hosts und `*.e2b.app` und leitet relative `/api`-Anfragen zum Backend weiter. Browser-Code enthält keine Backend-`localhost`-URL. Bei abweichendem Backend-Port `API_PROXY_TARGET` für den Vite-Prozess setzen, beispielsweise `http://127.0.0.1:8001`.

### Automatisierte Prüfungen

Im aktivierten Python-venv:

```bash
python -m pytest -q
ruff check backend scripts tests
ruff format --check backend scripts tests

cd frontend
npm ci
npm run build
npx playwright install chromium
npm run test:e2e
```

Die Backend-Tests verwenden ausschließlich temporäre Bibliotheken. Die Browser-Suite startet auf Port **8010** automatisch eine **separate, temporäre Demo-Bibliothek**, die nach dem Testlauf entfernt wird. Die konfigurierte Bildbibliothek wird nicht verändert. Eine bereits belegte Testadresse wird standardmäßig nicht wiederverwendet. Browser-Abhängigkeiten können unter Linux zusätzlich mit `npx playwright install --with-deps chromium` installiert werden.

Abgedeckt sind unter anderem Traversal, Symlinks, Cache-Wiederverwendung, Duplikate, transparente/EXIF-korrigierte Thumbnails, TIFF-Vorschauen, Kollisionen, Cross-Volume-Fallback, Batch-Rollback, konkurrierende Requests, Prozess-Locks, Undo nach Neustart, Recovery und responsive Bedienabläufe.

Die zusätzlichen Integritätstests vergleichen echte Dateien unabhängig vom App-Index per SHA-256: gleichnamige Batches bis 500 Dateien, belegte Originalpfade, extrem lange Namen, externe Dateiersetzungen, harte Prozessabbrüche und echte Laufwerksgrenzen unter Linux. Auch die Browser-Tests prüfen Dateiinhalt und Originalpfad, nicht nur die Zahl der Galerie-Karten. Details und Grenzen: [Validierungsbericht](docs/VALIDIERUNG.md).

### Tastenkürzel

| Taste | Aktion |
| --- | --- |
| Klick / Strg- oder ⌘-Klick | Bild zur Mehrfachauswahl hinzufügen/entfernen |
| Shift-Klick | Bereich auswählen |
| Strg/⌘ + A | Gefilterte Bilder auswählen, maximal 500 |
| 1–9 | Auswahl ins entsprechende Album in der rechten Liste verschieben |
| Entf | Papierkorb-Dialog öffnen |
| Strg/⌘ + Z | Letzten Batch rückgängig machen |
| Esc | Dialog schließen bzw. Auswahl aufheben |
| `/` | Suche fokussieren |
| `←` / `→` | In der großen Vorschau navigieren |
| `?` | Tastenkürzel anzeigen |

Große Galerien rendern zunächst 80 Karten, weitere Bilder lassen sich nachladen. Thumbnails laden bedarfsgesteuert. Suche und Sortierung beziehen sich auf alle Bilder im geladenen Ordner, nicht nur auf die bereits gerenderten Karten.

## Projektstruktur

```text
├── README.md
├── config.yaml
├── requirements.txt
├── requirements-dev.txt
├── pyproject.toml
├── start.sh / start.bat
├── backend/
│   ├── main.py                # FastAPI, Lifecycle, Fehlerbehandlung, SPA
│   ├── __main__.py            # Nativer Uvicorn-Start
│   ├── config.py
│   ├── models/schemas.py      # Pydantic-Modelle
│   ├── routers/api.py
│   └── services/
│       ├── filenames.py       # Portable Namenskollisionen und Längenbegrenzung
│       ├── indexer.py
│       ├── journal.py
│       ├── library.py
│       ├── process_lock.py
│       ├── security.py
│       └── thumbnails.py
├── frontend/
│   ├── package.json / package-lock.json
│   ├── vite.config.js
│   ├── playwright.config.js
│   ├── src/
│   │   ├── main.js / App.vue / api.js / styles.css
│   │   ├── components/        # Galerie, Baum, Alben, Dialog, Protokoll
│   │   ├── composables/useLibrary.js
│   │   └── views/WorkspaceView.vue
│   └── tests/                 # UI-, Datei-Integritäts- und Barrierefreiheitstests
├── scripts/
│   ├── start.py
│   ├── seed_demo.py
│   ├── serve_e2e.py
│   └── demo_assets/           # Optimierte, optionale Beispielfotos + Credits
└── tests/                    # Backend-, Konfigurations- und Sicherheitstests
```

`data/`, `config.local.yaml`, virtuelle Umgebungen, Builds, Caches und Testartefakte sind Git-ignoriert. Eigene Bibliotheken außerhalb von `data/` ebenfalls nicht ins Repository aufnehmen.

## Häufige Fragen

- **Neue Bilder fehlen:** „Ordner neu einlesen“ oder `POST /api/index`. Dateisystemänderungen werden nicht automatisch beobachtet.
- **Rückgängig ist blockiert:** Originalpfad oder Zieldatei wurde extern verändert. Nichts überschreiben; Dateipfade und Fehler im Protokoll prüfen. Bei `interrupted` die betroffenen Dateien anhand des Journals und eines Backups manuell abgleichen.
- **Bibliothek bereits geöffnet:** Den anderen Folio-Prozess stoppen. Das Betriebssystem gibt den Lock beim Prozessende frei; eine zurückbleibende `instance.lock`-Datei ist unproblematisch.
- **Cache wird groß:** Bei gestoppter App nur `.image-sorter/thumbnails/` leeren. Vorschauen werden neu erzeugt. `journal.sqlite3` nicht löschen, wenn Undo-Historie erhalten bleiben soll.
- **Keine AVIF-Vorschau:** Die installierte Pillow-Version bzw. der Plattform-Build muss AVIF unterstützen. Andere Dateien bleiben verwendbar.
- **Frontend nicht verfügbar:** `npm run build` in `frontend/` ausführen oder ohne `--no-build` starten.
- **403 im Entwicklungsbetrieb:** Frontend über Vite und dessen relative `/api`-Proxy verwenden, nicht per Browser-Fetch direkt auf einen anderen Port zugreifen.
