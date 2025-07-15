# MIDOS to RIS Converter

## Übersicht

Dieses Python-Skript konvertiert MIDOS-Datenbankeinträge (gespeichert in `.wrk`-Dateien) in das RIS-Format, wodurch sie mit Literaturverwaltungsprogrammen wie Zotero, EndNote, Mendeley und anderen kompatibel werden. Der Konverter ordnet MIDOS-Felder intelligent ihren RIS-Äquivalenten zu und berücksichtigt dabei verschiedene Dokumenttypen und Sonderfälle.

## Funktionen

- **Automatische Dateierkennung**: Findet `.wrk`-Dateien im angegebenen Verzeichnis
- **Intelligente Dokumenttyp-Zuordnung**: Bestimmt den korrekten Dokumenttyp anhand mehrerer Felder
- **Umfassende Feldzuordnung**:
  - Autoren, Herausgeber und andere Beteiligte
  - Titel und Untertitel
  - Publikationsdetails (Zeitschrift, Verlag, Jahr)
  - Seitenzahlen und Bandinformationen
  - Abstracts und Schlagwörter
  - ISBN/ISSN-Nummern
- **Spezielle Behandlung für**:
  - Buchkapitel mit Informationen zum übergeordneten Buch
  - Zeitschriftenartikel mit Band- und Heftnummern
  - Konferenzbeiträge
  - Dissertationen und Berichte
- **Volltext-Links**: Erstellt Links zu digitalen Dokumenten, wenn verfügbar
- **Unterstützung mehrerer Zeichenkodierungen**: Verarbeitet UTF-8, Latin-1 und Windows-1252 Kodierungen

## Anforderungen

- Python 3.6 oder höher
- Keine externen Abhängigkeiten (verwendet nur Standardbibliotheksmodule)

## Installation

Keine Installation erforderlich. Laden Sie einfach das Skript herunter und führen Sie es mit Python aus.

```bash
# Repository klonen oder herunterladen
git clone https://github.com/ihrusername/midos-to-ris.git
cd midos-to-ris
```

## Verwendung

### Grundlegende Verwendung

```bash
python midos_to_ris.py
```

Dies sucht nach `.wrk`-Dateien im aktuellen Verzeichnis und fordert Sie auf, eine zur Konvertierung auszuwählen.

### Angabe einer Eingabedatei

```bash
python midos_to_ris.py pfad/zu/ihrer/datei.wrk
```

### Angabe von Eingabe- und Ausgabeverzeichnis

```bash
python midos_to_ris.py pfad/zum/eingabeverzeichnis pfad/zum/ausgabeverzeichnis
```

## Ausgabe

Das Skript generiert eine RIS-Datei mit einem Zeitstempel im Dateinamen (z.B. `midos_to_ris_20230715_123045.ris`). Diese Datei kann direkt in Literaturverwaltungssoftware importiert werden.

## Feldzuordnung

Das Skript ordnet MIDOS-Felder den RIS-Feldern nach folgender Logik zu:

| MIDOS-Feld | RIS-Feld | Beschreibung |
|------------|----------|--------------|
| DTY | TY | Dokumenttyp |
| VER | A1 | Hauptautoren |
| INS | A1/C1 | Institution (als Autor, wenn kein VER vorhanden) |
| PUH | ED | Herausgeber |
| HST | T1 | Titel |
| ZUS | T1 | Untertitel (an Titel angehängt) |
| ZNA | T2/JF | Zeitschriften-/Reihentitel |
| AUS | T2 | Übergeordneter Buchtitel (für Kapitel) |
| ERJ | Y1/PY | Erscheinungsjahr |
| ORT | CY | Erscheinungsort |
| VEL | PB | Verlag |
| SWO, PSW, etc. | KW | Schlagwörter |
| KOL | SP/EP | Seitenzahlen |
| URL | UR | URL |
| OBJ | L1 | Link zur Dokumentdatei |
| ... | ... | ... |

## Beispiele

### Konvertierung einer einzelnen Datei

```bash
python midos_to_ris.py beispiel.wrk
```

### Konvertierung aus einem bestimmten Verzeichnis in ein anderes

```bash
python midos_to_ris.py ~/midos_exporte ~/konvertierte_referenzen
```

## Fehlerbehebung

- **Kodierungsprobleme**: Wenn das Skript auf Kodierungsprobleme stößt, werden automatisch verschiedene Kodierungen ausprobiert.
- **Fehlende Felder**: Das Skript behandelt fehlende Felder elegant und verwendet wenn möglich Fallback-Optionen.

## Lizenz

Dieses Projekt ist unter der MIT-Lizenz lizenziert - siehe die LICENSE-Datei für Details.

