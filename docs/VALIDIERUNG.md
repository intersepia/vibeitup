# Validierung: Undo und sichere Dateiablage

**Stand: 05.09.2026 · Ergebnis: 132 Backend-Tests und 27 Browser-Tests bestanden.**

Zusätzlich erfolgreich: Frontend-Produktionsbuild, Ruff-Codeprüfung, Ruff-Formatprüfung und Prettier-Formatprüfung.

## Wie wurde geprüft?

Nicht nur die Galerie-Anzeige: Die Tests vergleichen **tatsächliche Dateiinhalte unabhängig vom Folio-Index per SHA-256**. Sie prüfen Zielpfade, Originalnamen, Änderungszeitpunkte und die Anzahl der vorhandenen Kopien. Folio selbst verwendet weiterhin den geforderten SHA-1-Index.

Alle schreibenden Tests laufen in separaten temporären Bibliotheken. Die Browser-Dateitests verweigern Schreibzugriffe, wenn der Server nicht auf die eigens angelegte `folio-e2e-*`-Testbibliothek zeigt. Die laufende Benutzerbibliothek wird nicht für Testverschiebungen verwendet.

## Prüfergebnisse

| Fall | Ergebnis |
| --- | --- |
| Drei Bilder aus unterschiedlichen Quellen heißen `bild.jpg`; Ziel enthält schon `bild.jpg` und `bild_001.jpg` | Neue Dateien werden als `bild_002.jpg`, `bild_003.jpg`, `bild_004.jpg` abgelegt. Die vorhandenen Bilder bleiben unverändert. |
| Gleicher Name **und** identischer Inhalt | Jede ausgewählte Datei bleibt als eigene Kopie erhalten; kein stilles Zusammenführen oder Löschen. |
| Gleichnamige Bilder in Alben, Papierkorb und Duplikat-Ablage | Alle drei Aktionen einschließlich Undo geprüft. |
| Undo eines gesamten Batches nach einem Neustart | Originalordner, Originalnamen, Dateiinhalte und Änderungszeitpunkte werden wiederhergestellt. |
| Ursprünglicher Dateiname ist inzwischen neu belegt | Undo bricht mit einem Konflikthinweis ab. Weder die neue Datei noch ein Teil des ursprünglichen Batches wird überschrieben. Nach Beseitigung des Konflikts ist dieselbe Transaktion erneut rückgängig machbar. |
| Zielbild nachträglich verändert oder entfernt | Sichere Vorprüfung; keine teilweise Wiederherstellung und kein Überschreiben. |
| Umlaute, Unicode, Leerzeichen, `#`, `%`, unterschiedliche Groß-/Kleinschreibung | Sichere Zielnamen und Rückkehr zum unveränderten Originalpfad geprüft. |
| Dateinamen nahe der maximalen Komponentenlänge | Zähler und Dateiendung bleiben erhalten; der Zielnamen-Stamm wird nur soweit nötig gekürzt. |
| Zielname wird bereits von einem Ordner oder ungültigen Symlink belegt | Name wird übersprungen, nächste freie Nummer wird verwendet. |
| Acht gleichzeitige Verschiebungen gleichnamiger Dateien und paralleles Undo | Eindeutige Ziele; keine verlorene, überschriebene oder doppelt rückgängig gemachte Datei. |
| Maximal erlaubter Batch: **500 gleichnamige Dateien** | Alle Dateien erhalten eigene Zielnamen bis `bild_500.jpg`; vollständiges Undo mit Inhaltsvergleich bestanden. |
| 60 reproduzierbar zufällige Move-/Trash-/Undo-Schritte | Dateiinhalte und Anzahl aller Kopien nach jedem Schritt geprüft; abschließendes Undo stellt den Ausgangsbestand her. |
| Echter Prozessabbruch mitten in Move bzw. Undo | Testprozess beendet sich unmittelbar nach einem Dateischritt mit `os._exit()`. Neustart stellt den korrekten Bestand wieder her und kann den Prozess-Lock wieder erwerben. |
| Echte Laufwerksgrenze unter Linux | Verschieben und Rückweg zwischen unterschiedlichen Dateisystemen, inklusive Inhalt und Änderungszeit, bestanden. |
| Fehler beim Kopieren, Löschen oder Schreiben des Transaktionsabschlusses | Rollback bzw. ausdrücklich als `interrupted` gekennzeichneter Zustand; unsicher bereinigbare Kopien bleiben erhalten. |
| Anderes Programm ersetzt Quelle oder Ziel während der Operation | Dateiidentität wird zusätzlich zum Hash geprüft. Eine fremde Zielersetzung wird bei der Fehlerbereinigung nicht gelöscht; eine mögliche letzte gute Kopie bleibt erhalten. |
| Index-/Cache-Update schlägt **nach** erfolgreicher Verschiebung fehl | Die erfolgreiche Transaktion bleibt erfolgreich. Separater Indexhinweis statt irreführendem Move-Fehler; neuer Indexversuch wiederholt nicht die Verschiebung. |
| Bedienung im echten Browser | Mehrfachauswahl, Namenszähler, Dateiinhalte, Undo nach Neuladen, belegte Originalpfade, mobile Ansicht und automatisierte Barrierefreiheitsprüfungen bestanden. |

## Was wurde bei dieser Prüfung verbessert?

1. **Portable Namensvergabe:** Groß-/Kleinschreibung und kanonisch gleichwertige Unicode-Schreibweisen werden auch unter Linux vorsorglich als Kollision reserviert. Dadurch gibt es keine überraschenden gleichwertigen Zielnamen auf macOS-/Windows-Dateisystemen. Zu lange Namen erhalten einen passend gekürzten Stamm statt eines Dateisystemfehlers.
2. **Zusätzliche Dateiidentitäts-Prüfung:** Quelle wird bereits vor dem Hashen erfasst. Angelegte Kopien werden über ihre Dateikennung zugeordnet, nicht allein über den Pfadnamen. Fehlerbereinigung entfernt keine inzwischen an diesem Pfad vorhandene fremde Datei.
3. **Ehrliches Transaktionsprotokoll:** Bleibt eine nicht sicher bereinigbare Kopie zurück, wird die Aktion als `interrupted` statt als vollständig zurückgesetzt protokolliert.
4. **Indexfehler von Dateiaktionen getrennt:** Ein Cachefehler kann eine bereits gespeicherte Verschiebung nicht mehr als fehlgeschlagen ausgeben. Nach einem abgeschlossenen Scan bleibt der Arbeitsspeicher-Index aktuell, selbst wenn das Speichern der Cachedatei fehlschlägt. `/api/status` meldet einen separaten `index_warning`.
5. **Aktuelle Fehleransicht:** Nach einem vom Server beantworteten Aktionsfehler werden Galerie und Protokoll erneut geladen. Eine weiterhin gültige Auswahl bleibt erhalten.

6. **Wählbarer Album-Speicherort:** Neue Alben können direkt im Hauptordner oder unter beliebig verschachtelten vorhandenen Alben angelegt werden. Der Button und die direkte Bildzuordnung verwenden den vollständigen zurückgegebenen Pfad, nicht nur den möglicherweise mehrfach vorkommenden Albumnamen.

Die Galerie nutzt eine kompakte gemeinsame Werkzeugleiste für Überschrift, Filter, Suche und Raster-/Listenansicht; die früheren Einleitungstexte entfallen. Der Album-Dialog enthält zusätzlich die Elternordner-Auswahl und eine relative Pfadvorschau; die Liste lässt sich aktualisieren. Ein verschwundener Elternordner führt nicht zu einem stillen Ausweichen auf den Hauptordner.

### Zusätzliche Prüfung der Elternordner-Auswahl

- 31 Backend-Testfälle zu Root-/Unteralbum-Erstellung, identischen Namen unter unterschiedlichen Eltern, Pfad-Traversal, Symlinks, verschwundenen Eltern, Pfadlängen und konkurrierendem Anlegen.
- Fünf neue Browser-Tests: direktes Verschieben in ein tiefes Unteralbum trotz gleichnamigem Root-Album samt Undo, Aktualisieren der Ordnerliste, explizite Root-Auswahl nach einem entfernten Elternordner, Wiederholen fehlgeschlagener Listenabfragen und mobile Tastatur-/Barrierefreiheitsprüfung.
- Die bestehende Live-Bibliothek und Undo-Historie wurden beim Server-Update zusätzlich unverändert per Dateipfad und SHA-256 bzw. Protokollvergleich bestätigt. Testverschiebungen fanden ausschließlich in temporären Bibliotheken statt.

### Kompakte Galerieleiste

- Überschrift, „Alle Bilder“, Duplikatfilter, Suche und Ansichtsschalter liegen in einer gemeinsamen Leiste. Der überflüssige zweite Bildzähler und die Marketing-Überschriften sind entfernt.
- Drei zusätzliche Browser-Tests prüfen alle Sammlungsansichten, die Anordnung bei zwölf Bildschirmbreiten von 320 bis 1920 px sowie lange Ordnernamen. Kein horizontales Überlaufen und keine überlappenden Bedienelemente.
- Die Leiste reagiert auf die tatsächliche Breite des Bildbereichs: eine Zeile auf breiten Ansichten, kompakte Umbrüche auf kleinen Geräten. Suche, Filter, Sortierung und Ansichtswechsel bleiben bedienbar.
- Bei 1440 px Bildschirmbreite sinkt der Galeriekopf von rund 250 auf 101 CSS-Pixel. Es stehen damit rund 149 zusätzliche vertikale Pixel für die Bilder zur Verfügung.

### Arbeitsfläche ohne globalen Header

- Das Folio-Logo steht oberhalb von „Deine Bibliothek“ in der Quell-Navigation. Es gibt keinen oberen Header und keinen leeren Platzhalter mehr.
- Rückgängig und Einstellungen stehen gemeinsam rechts direkt oberhalb von „In Album verschieben“. Die Funktionen und das Tastenkürzel Strg/⌘+Z bleiben erhalten.
- Auf dem Handy öffnen die Symbole in der Galerieleiste die Quell-Navigation bzw. springen zu den Album-Aktionen. Die Navigation beginnt am oberen Bildschirmrand, sperrt den Hintergrund, hält den Tastaturfokus und lässt sich mit Escape schließen. Eine bestehende Auswahl bleibt dabei erhalten.
- Vier zusätzliche Browser-Tests prüfen Anordnung, funktionsfähiges Undo, Einstellungen, Tastenkürzel, mobile Navigation, Fokus-Rückgabe, Bildschirmgrößenwechsel und Barrierefreiheit einschließlich aktiver Undo-Schaltflächen.
- Bei 1440 px Bildschirmbreite beginnt das erste Bild jetzt bei rund 103 statt 188 CSS-Pixeln: weitere 85 Pixel zusätzliche Bildfläche gegenüber der bereits kompakten Werkzeugleiste.

### Bildzähler „Alle Alben“

Der Zähler in der linken Navigation verwendet `album_images` statt `album_count`. Er zählt Bilder einschließlich aller Unteralben genau einmal, nicht die Zahl der Ordner. Ein eigener Browser-Test prüft leere neu angelegte Alben, verschachtelte Bildablage und Undo sowie die Übereinstimmung mit der Galerie.

## Reproduzieren

Einrichtung und plattformspezifische Aktivierung des Python-venv stehen in der [README](../README.md#6-entwicklung-und-tests).

```bash
# Im aktivierten Python-venv, im Projektordner:
pip install -r requirements-dev.txt
python -m pytest -q

# Nur die vertieften Datei-Integritätstests:
python -m pytest tests/test_move_integrity.py -v

# Browser-Tests gegen eine automatisch angelegte Wegwerf-Bibliothek:
cd frontend
npm ci
npm run build
npx playwright install chromium
npm run test:e2e
```

Relevante Dateien:
- `tests/test_api.py`: bestehende API-, Undo-, Sicherheits- und Recovery-Prüfungen.
- `tests/test_move_integrity.py`: 30 zusätzliche Integritäts-, Kollisions-, Parallelitäts- und Fehlertests.
- `tests/test_album_creation.py`: 31 Testfälle zur sicheren Album-Erstellung unter einem gewählten Elternordner.
- `frontend/tests/album-parents.spec.js`: Elternordner-Dialog, reale verschachtelte Zuordnung, Fehlerfälle und Bedienbarkeit.
- `frontend/tests/file-safety.spec.js`: echte Dateioperationen per Oberfläche mit unabhängigem Inhaltsvergleich.
- `frontend/tests/workspace.spec.js`: allgemeine Bedienabläufe und Barrierefreiheit.
- `frontend/tests/toolbar.spec.js`: kompakte Werkzeugleiste, Ansichtswechsel und responsive Geometrie.
- `frontend/tests/album-count.spec.js`: Bildanzahl in der Navigation statt Ordneranzahl.
- `frontend/tests/headerless.spec.js`: Logo in der Navigation, Aktionen im Album-Bereich und mobile Bedienung ohne oberen Header.

## Grenzen und Empfehlung

- Ausgeführt unter **Linux mit Python 3.11 und Chromium**. Windows-/macOS-relevante Namensregeln werden geprüft; ein nativer Testlauf auf diesen beiden Betriebssystemen wurde hier nicht durchgeführt.
- Harte **Prozessabbrüche** und gezielt injizierte Dateisystemfehler wurden getestet, kein physischer Stromausfall, beschädigter Datenträger oder beliebiges Netzwerkdateisystem.
- Dateisystemoperationen über mehrere Dateien sind keine unteilbare Hardware-Transaktion. Bei einem nicht eindeutig lösbaren Konflikt bleiben Dateien zur manuellen Prüfung erhalten.
- Die Bibliothek ist keine Sicherheitsisolation gegen bösartige lokale Programme mit Schreibrechten. Dieselben Bilder möglichst nicht gleichzeitig in anderen Programmen bearbeiten.
- **Für wertvolle Originalbilder zusätzlich ein Backup behalten. Undo ersetzt kein Backup.**
- Der Backend-Testlauf meldet zwei Deprecation-Warnungen aus den installierten HTTP-/Testbibliotheken; keine fehlgeschlagenen Tests.
