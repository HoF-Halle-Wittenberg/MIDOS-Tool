#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MIDOS to RIS Converter
======================

Dieses Skript konvertiert MIDOS-Datenbankeinträge (.wrk-Dateien) in das RIS-Format für den Import in 
Referenzverwaltungssoftware wie Zotero, EndNote oder Mendeley.

Merkmale:
- Automatische Erkennung von .wrk-Dateien im aktuellen Verzeichnis
- Intelligentes Mapping von MIDOS-Feldern in das RIS-Format
- Spezielle Handhabung für verschiedene Dokumenttypen
- Unterstützung für mehrere Autoren, Bearbeiter und Mitwirkende
- Extraktion von Zusammenfassungen, Schlüsselwörtern und Seitenzahlen
- Generierung von Links zu Volltextdokumenten

Verwendung:
 python midos_to_ris.py [input_file.wrk oder Verzeichnis] [output_directory]
    
    Wenn keine Argumente angegeben werden, sucht das Skript nach .wrk-Dateien im aktuellen Verzeichnis.
    
Author: Hof Halle-Wittenberg
Version: 1.0
Date: 2023-07-15
License: MIT
"""

import re
import os
import sys
from datetime import datetime
import glob

# Wechsle zum Verzeichnis des Skripts, um relative Pfade zu vereinfachen
script_dir = os.path.dirname(os.path.abspath(__file__))
os.chdir(script_dir)

def find_wrk_files(directory=None):
    """
    Findet alle .wrk-Dateien im angegebenen Verzeichnis oder im aktuellen Verzeichnis.
    """
    if directory is None:
        directory = os.getcwd()
    
    # Suche nach .wrk-Dateien im angegebenen Verzeichnis
    wrk_files = glob.glob(os.path.join(directory, "*.wrk"))
    
    return wrk_files

def select_wrk_file():
    """
    Lässt den Benutzer eine .wrk-Datei aus dem aktuellen Verzeichnis auswählen.
    Wenn keine .wrk-Dateien gefunden werden, wird None zurückgegeben.
    """
    wrk_files = find_wrk_files()
    
    if not wrk_files:
        print("Keine .wrk-Dateien im aktuellen Verzeichnis gefunden.")
        return None
    
    print("\nGefundene .wrk-Dateien:")
    for idx, file_path in enumerate(wrk_files, 1):
        print(f"{idx}. {os.path.basename(file_path)}")
    
    while True:
        try:
            choice = input("\nBitte wähle eine Datei (Nummer oder 'q' zum Beenden): ")
            if choice.lower() == 'q':
                return None
            
            choice_idx = int(choice) - 1
            if 0 <= choice_idx < len(wrk_files):
                return wrk_files[choice_idx]
            else:
                print(f"Ungültige Auswahl. Bitte wähle eine Zahl zwischen 1 und {len(wrk_files)}.")
        except ValueError:
            print("Ungültige Eingabe. Bitte gib eine Zahl oder 'q' ein.")

def parse_midos_records(content):
    """
    Parst die MIDOS-Datenbankeinträge aus dem Inhalt
    und gibt eine Liste von Einträgen zurück.
    """
    # Trenner für Datensätze ist &&&
    records = content.split('&&&')
    parsed_records = []
    
    for record in records:
        if record.strip():  # Überspringe leere Einträge
            record_dict = {}
            lines = record.strip().split('\n')
            
            for line in lines:
                if line.strip() and ':' in line:
                    field_key, field_value = line.split(':', 1)
                    record_dict[field_key.strip()] = field_value.strip()
            
            if record_dict:  # Nur nicht-leere Datensätze hinzufügen
                parsed_records.append(record_dict)
    
    return parsed_records

def map_complete_title(record):
    """
    Kombiniert HST und ZUS zu einem vollständigen Titel.
    ZUS wird an HST angehängt, wobei spitze Klammern entfernt und " : " durch ". " ersetzt wird.
    """
    title_parts = []
    
    if 'HST' in record and record['HST'].strip():
        title_parts.append(record['HST'].strip())
    
    if 'ZUS' in record and record['ZUS'].strip():
        zus = record['ZUS'].strip()
        # Entferne spitze Klammern und deren Inhalt
        zus = re.sub(r'<[^>]*>', '', zus).strip()
        # Ersetze " : " durch ". "
        zus = zus.replace(' : ', '. ')
        # WICHTIG: Führende Punkte nur entfernen, wenn sie alleine stehen
        # Behalte "..." am Anfang, aber entferne einzelne Punkte
        zus = re.sub(r'^\.(?!\.)', '', zus).strip()
        if zus:
            title_parts.append(zus)
    
    if title_parts:
        return '. '.join(title_parts)
    return None

def map_obj_link(record):
    """
    Erstellt den Link zu Objektdateien basierend auf OBJ und URH.
    Nur wenn URH = "j" wird ein Link erstellt.
    """
    if 'URH' in record and record['URH'] == 'j' and 'OBJ' in record and record['OBJ'].strip():
        obj_file = record['OBJ'].strip()
        return f"https://www.hof.uni-halle.de/documents/{obj_file}"
    return None

def map_extra_info(record):
    """
    Erstellt Extra-Informationen aus VERAM und OBJ (wenn URH != "j").
    """
    extra_parts = []
    
    # VERAM Autoren formatieren
    if 'VERAM' in record and record['VERAM'].strip():
        veram_authors = _split_multiple_values(record['VERAM'])
        if veram_authors:
            formatted_authors = ', '.join(veram_authors)
            extra_parts.append(f"Verfasser: {formatted_authors}")
    
    # OBJ hinzufügen wenn URH != "j"
    if 'OBJ' in record and record['OBJ'].strip():
        urh = record.get('URH', '')
        if urh != 'j':
            obj_file = record['OBJ'].strip()
            # Entferne .pdf-Endung falls vorhanden
            obj_file = re.sub(r'\.pdf$', '', obj_file, flags=re.IGNORECASE)
            extra_parts.append(f"OBJ: {obj_file}")
    
    if extra_parts:
        return ' | '.join(extra_parts)
    return None


def map_midos_to_ris(midos_record):
    """
    Konvertiert einen MIDOS-Datensatz in RIS-Format.
    """
    ris_map = {
        # RIS-Tag: (MIDOS-Feld, Transformationsfunktion oder None)
        'TY': map_document_type,  # Spezielle Funktion für den Dokumenttyp
        'ID': ('INN', None),      # Interne Nachweis-Nr.
        'T1': map_complete_title, # Hauptsachtitel mit ZUS kombiniert
        'T2': ('ZNA', None),      # Zeitschriftentitel (oft auch für Paralleltitel PTI verwendet)
        'T3': ('RHE', None),      # Reihe/Serien (Serientitel)
        # 'A1': map_authors,      # Wird direkt behandelt
        # 'ED': map_editors,      # Wird direkt behandelt
        'A3': map_other_contributors, # Spezielle Funktion für andere Beteiligte (BET)
        # 'C1': map_corporations, # Wird bedingt direkt in der Schleife behandelt
        'Y1': ('ERJ', None),      # Erscheinungsjahr
        'PY': ('ERJ', None),      # Erscheinungsjahr (alternativ)
        'CN': ('SIG', None),      # Signatur als Call Number
        'N2': map_abstracts,      # Abstract
        'AB': map_abstracts,      # Abstract (alternativ)
        'CY': ('ORT', None),      # Verlagsort
        'PB': ('VEL', None),      # Verlag
        'KW': map_keywords,       # Spezielle Funktion für Schlagwörter
        'SP': map_pages,          # Spezielle Funktion für komplette Seitenangaben
        'EP': map_pages_end,      # Ende der Seitenangaben
        'C3': map_volume_info,    # Bandangaben aus KOL als Custom Field
        'JF': ('ZNA', None),      # Zeitschriftentitel
        'JO': ('ZNA', None),      # Zeitschriftentitel (alternativ)
        'JA': ('ZNA', None),      # Zeitschriftentitel (Abkürzung)
        'VL': ('ZJG', None),      # Zeitschriften-Jahrgang
        'IS': ('ZHE', None),      # Zeitschriften-Heft
        'SN': map_isbn_issn,      # ISBN/ISSN
        'UR': ('URL', None),      # Internet-Adresse Volltext
        'L1': map_obj_link,       # Link zu Datei/Objekt (bedingt)
        'L2': ('URLV', None),     # Verwandte URL
        'LA': map_language,       # Sprache des Dokuments
        'C2': ('KON', None),      # Konferenzvermerke
        'C4': ('MTY', None),      # Medientyp
        'C5': ('GLA', None),      # Länderangaben
        'C6': ('BND', None),      # Bandangaben
        'C7': ('GOR', None),      # Ortsangaben
        'C8': ('FEO', None),      # Kennung
        'AD': ('ORT', None),      # Adresse (hier Verlagsort)
        'SE': ('ESL', None),      # Erscheinungsland
        'DA': ('ADA', None),      # Datum der letzten Änderung
        'DB': ('TDB', None),      # Teil-DB Zuordnung
        'M1': ('LIE', None),      # Lieferant/Fremddatenbank
        'M3': map_extra_info,     # Extra-Feld für VERAM und OBJ (wenn URH != "j")
    }
    
    ris_entries = []
    
    # Bestimme den Dokumenttyp zuerst, da er die weitere Logik beeinflusst
    document_type = map_document_type(midos_record)
    ris_entries.append("TY  - " + document_type)
    
    # Bestimme die Liste der Autoren (A1). Diese Funktion enthält nun die Fallback-Logik.
    authors = map_authors(midos_record)
    
    # Füge Autoren hinzu
    if authors:
        for author in authors:
            if author:
                ris_entries.append(f"A1  - {author}")
    
    # Sammle alle Körperschaften (INS, UHE), die NICHT als A1 verwendet wurden
    corporations_for_c1 = []
    if 'INS' in midos_record and midos_record['INS'].strip():
        ins_values = _split_multiple_values(midos_record['INS'])
        
        ver_exists = 'VER' in midos_record and midos_record['VER'].strip()
        
        if ver_exists: # Wenn VER existiert, dann ist INS definitiv eine separate Körperschaft
            corporations_for_c1.extend(ins_values)
        else: # Wenn VER nicht existiert, müssen wir prüfen, ob INS der A1-Autor ist.
            # Vergleiche, ob die einzigen Autoren die INS-Werte sind.
            is_ins_author = True
            if authors and ins_values:
                # Prüfe, ob jeder INS-Wert in den Autoren ist und umgekehrt
                for ins_val in ins_values:
                    if ins_val not in authors:
                        is_ins_author = False
                        break
                for author_val in authors:
                    if author_val not in ins_values:
                        is_ins_author = False
                        break
                if len(authors) != len(ins_values):
                    is_ins_author = False
            elif authors or ins_values:
                is_ins_author = False
            else:
                is_ins_author = False
                
            if not is_ins_author: # Wenn INS NICHT als A1 dient, dann ist es C1
                corporations_for_c1.extend(ins_values)

    if 'UHE' in midos_record and midos_record['UHE'].strip():
        corporations_for_c1.extend(_split_multiple_values(midos_record['UHE']))

    if corporations_for_c1:
        for corp in set(corporations_for_c1): # Verwende Set für eindeutige Einträge
            if corp:
                ris_entries.append(f"C1  - {corp}")
    
    # Herausgeber (ED)
    editors = map_editors(midos_record)
    if editors:
        for editor in editors:
            if editor:
                ris_entries.append(f"ED  - {editor}")

    # Spezielle Behandlung für Buchteile (DTY:AM -> TY:CHAP)
    if document_type == 'CHAP':
        parent_title, parent_editors = map_parent_book_info(midos_record)
        if parent_title:
            ris_entries.append(f"T2  - {parent_title}") # Buchtitel
        if parent_editors:
            for editor in parent_editors:
                if editor:
                    ris_entries.append(f"ED  - {editor}") # Buchherausgeber (werden zu den anderen Herausgebern hinzugefügt)
    
    # Alle anderen Felder mappen
    for ris_tag, midos_mapping in ris_map.items():
        if ris_tag in ['TY', 'A1', 'ED', 'C1', 'T2']:  # Diese Tags wurden bereits behandelt
            continue
            
        if midos_mapping is None:  # Überspringe None-Mappings
            continue
            
        if callable(midos_mapping):
            mapped_values = midos_mapping(midos_record)
            if mapped_values:
                if isinstance(mapped_values, list):
                    for value in mapped_values:
                        if value:  # Nur nicht-leere Werte hinzufügen
                            ris_entries.append(f"{ris_tag}  - {value}")
                else:
                    ris_entries.append(f"{ris_tag}  - {mapped_values}")
        else:
            # Sonst einfaches Mapping von Feldnamen
            midos_field, transform_func = midos_mapping
            if midos_field in midos_record and midos_record[midos_field]:
                value = midos_record[midos_field]
                if transform_func:
                    value = transform_func(value)
                ris_entries.append(f"{ris_tag}  - {value}")
    
    # Abschluss des Datensatzes
    ris_entries.append("ER  - ")
    
    return "\n".join(ris_entries)

def map_document_type(record):
    """
    Mappt den MIDOS-Dokumenttyp auf RIS-Dokumenttyp.
    Erweiterte Logik für bessere Zuordnung, mit spezieller Behandlung für Sammelwerke.
    """
    dty = record.get('DTY', '')
    
    # Prüfe auf mehrere DTY-Werte (durch | getrennt)
    dty_values = [dt.strip() for dt in dty.split('|') if dt.strip()]
    
    # NEUE LOGIK: Spezialfall für Sammelwerke mit Herausgebern
    # Wenn SW (Sammelwerk) vorhanden ist UND es Herausgeber (PUH) gibt,
    # dann ist es ein herausgegebenes Buch (EDBOOK in EndNote, wird zu BOOK in Zotero)
    if 'SW' in dty_values:
        # Prüfe auf Herausgeber-Indikatoren
        has_editors = (
            (record.get('PUH') and record['PUH'].strip()) or  # Explizite Herausgeber
            (record.get('RHE') and ';' in record.get('RHE', ''))  # Reihen-Herausgeber
        )
        
        # Prüfe auch auf AUS-Feld, das bei Buchteilen den Sammelwerktitel enthält
        # Wenn kein AUS vorhanden ist, ist es wahrscheinlich das Sammelwerk selbst
        has_aus = record.get('AUS') and record['AUS'].strip()
        
        if has_editors and not has_aus:
            # Es ist ein herausgegebenes Sammelwerk
            return 'BOOK'  # Zotero verwendet BOOK für herausgegebene Bücher
    
    # Spezialfall: Themenheft einer Zeitschrift
    if 'ZS' in dty_values and 'SW' in dty_values:
        # Ein Themenheft ist im Grunde eine spezielle Ausgabe einer Zeitschrift
        # Prüfe, ob es Einzelbeiträge gibt (durch VERAM oder Hinweise im ZUS)
        zus = record.get('ZUS', '')
        if 'Themenheft' in zus or 'Einzelbeiträge' in zus:
            # Themenheft mit mehreren Beiträgen -> als BOOK behandeln
            return 'BOOK'
        else:
            # Normale Zeitschriftenausgabe
            return 'JOUR'
    
    # Spezialfall: Statistik/Report mit ISSN
    # Wenn ST (Statistik) vorhanden ist UND eine ISSN existiert, ist es ein regelmäßiger Report
    if 'ST' in dty_values and (record.get('ISSN') or record.get('ISN')):
        return 'RPRT'
    
    # Spezialfall: Forschungsbericht
    if 'FO' in dty_values:
        return 'RPRT'
    
    # Mapping von einzelnen MIDOS DTY auf RIS-Typen
    type_mapping = {
        'MO': 'BOOK',   # Monographie
        'AM': 'CHAP',   # Aufsatz in Monographie
        'ZA': 'JOUR',   # Zeitschriftenaufsatz
        'ZS': 'JOUR',   # Zeitschrift
        'SW': 'BOOK',   # Sammelwerk (Fallback, falls obige Logik nicht greift)
        'EM': 'ELEC',   # Elektronisches Medium
        'DS': 'THES',   # Dissertation
        'ST': 'RPRT',   # Statistik/Report
        'KO': 'CONF',   # Konferenzband/Konferenzbeitrag
        'GR': 'RPRT',   # Graue Literatur
        'FO': 'RPRT',   # Forschungsbericht
        'ZE': 'NEWS',   # Zeitung
        'ZT': 'NEWS',   # Zeitungsartikel
    }
    
    # Bei mehreren DTY-Werten: Intelligente Priorisierung
    if len(dty_values) > 1:
        # Priorisiere bestimmte Typen bei Konflikten
        priority_order = ['ST', 'FO', 'ZA', 'AM', 'DS', 'KO', 'ZS', 'SW', 'MO', 'EM']
        
        for priority_type in priority_order:
            if priority_type in dty_values and priority_type in type_mapping:
                # Zusätzliche Prüfung für MO: Wenn MO mit ST kombiniert ist und ISSN vorhanden, nutze ST
                if priority_type == 'MO' and 'ST' in dty_values and (record.get('ISSN') or record.get('ISN')):
                    continue
                return type_mapping[priority_type]
    
    # Gehe durch die DTY-Werte und finde den ersten passenden (wenn nur einer vorhanden)
    for dty_val in dty_values:
        if dty_val in type_mapping:
            return type_mapping[dty_val]
    
    # Erweiterte Fallback-Logik basierend auf anderen Feldern
    # Nur verwenden, wenn wirklich kein passender DTY gefunden wurde
    
    # Hat es eine ISSN? -> wahrscheinlich Journal
    if record.get('ISSN') or record.get('ZNA'):
        return 'JOUR'
    
    # Hat es eine ISBN? -> wahrscheinlich Buch
    if record.get('ISBN') or record.get('ISB'):
        return 'BOOK'
    
    # Ist es eine Dissertation?
    if record.get('HSS') or 'Diss' in record.get('HST', ''):
        return 'THES'
    
    # Ist es ein Konferenzbeitrag?
    if record.get('KON'):
        return 'CONF'
    
    # Wirklich nur als letzter Ausweg GEN verwenden
    return 'GEN'

def _clean_name(name):
    """
    Entfernt Klammerzusätze wie '(Interviewter)' und trimmt Leerzeichen.
    """
    if not name:
        return ""
    # Entfernt alles in Klammern und trimmt Leerzeichen
    cleaned_name = re.sub(r'\s*\(.*?\)\s*', '', name).strip()
    return cleaned_name

def _split_names_and_clean(field_value):
    """
    Hilfsfunktion zum Splitten von Namen, die durch '|' oder ';' getrennt sind,
    und behandelt Kommas in "Nachname, Vorname" als Teil eines Namens.
    Entfernt außerdem Klammerzusätze aus den Namen.
    """
    if not field_value:
        return []

    # Priorisiere '|' und ';', da dies klare Trenner für mehrere Autoren sind
    if '|' in field_value:
        split_char = '|'
    elif ';' in field_value:
        split_char = ';'
    else:
        # Wenn keine expliziten Trennzeichen für MEHRERE Namen vorhanden sind,
        # betrachten wir den gesamten String als einen einzelnen Namen,
        # selbst wenn er ein Komma enthält (z.B. "Nachname, Vorname").
        return [_clean_name(field_value)]

    # Splitten nach dem gefundenen Trennzeichen
    names = [item.strip() for item in field_value.split(split_char) if item.strip()]
    
    # Bereinige jeden Namen von Klammerzusätzen
    cleaned_names = [_clean_name(name) for name in names]
    return [name for name in cleaned_names if name] # Filtere leere Strings

def map_authors(record):
    """
    Extrahiert die Autoren aus dem MIDOS-Datensatz (VER).
    Wenn VER leer ist, wird versucht, INS als Autoren zu verwenden.
    Wenn INS auch leer ist, wird BET als Autoren verwendet.
    """
    authors = []
    
    # 1. Hauptautoren aus VER
    if 'VER' in record and record['VER'].strip():
        authors.extend(_split_names_and_clean(record['VER']))
    
    # 2. Fallback-Logik: Wenn keine VER-Autoren gefunden wurden,
    # und INS vorhanden ist, wird INS als Autor verwendet.
    if not authors and 'INS' in record and record['INS'].strip():
        authors.extend(_split_names_and_clean(record['INS'])) 
    
    # 3. Zweiter Fallback: Wenn weder VER noch INS Autoren liefern,
    # und BET vorhanden ist, wird BET als Autor verwendet.
    if not authors and 'BET' in record and record['BET'].strip():
        authors.extend(_split_names_and_clean(record['BET']))

    return authors

def map_editors(record):
    """
    Extrahiert die Herausgeber aus den MIDOS-Datensätzen (PUH) und (RHE).
    Berücksichtigt die neue Namenssplittung und -bereinigung.
    """
    editors = []
    if 'PUH' in record:
        editors.extend(_split_names_and_clean(record['PUH']))
    
    # Prüfen, ob RHE einen Reihen-Herausgeber enthält
    if 'RHE' in record:
        rhe_content = record['RHE']
        # Suche nach einem Semikolon, das einen Herausgeber abtrennen könnte
        if ';' in rhe_content:
            parts = rhe_content.split(';', 1) # Nur einmal splitten
            potential_editor = parts[1].strip()
            # Wenn der zweite Teil existiert und nicht leer ist,
            # behandle ihn als potenziellen Herausgeber und reinige ihn.
            if potential_editor:
                editors.extend(_split_names_and_clean(potential_editor))
    return editors

def map_other_contributors(record):
    """
    Mappt Beteiligte Personen (BET) auf RIS A3 (Tertiary Author).
    ACHTUNG: BET wird hier NUR gemappt, wenn es NICHT bereits in A1 gelandet ist.
    Die Entscheidung darüber findet in map_midos_to_ris statt.
    Diese Funktion liefert einfach die bereinigten BET-Werte.
    """
    if 'BET' in record and record['BET'].strip():
        return _split_names_and_clean(record['BET'])
    return []

def _split_multiple_values(field_value):
    """Hilfsfunktion zum Splitten von Mehrfachwerten für NICHT-NAMENS-Felder."""
    if not field_value:
        return []
    # Versuche, nach verschiedenen Trennzeichen zu splitten
    if '|' in field_value:
        return [item.strip() for item in field_value.split('|') if item.strip()]
    elif ';' in field_value:
        return [item.strip() for item in field_value.split(';') if item.strip()]
    elif ',' in field_value and len(field_value.split(',')) > 1: # Nur splitten, wenn mehr als ein Element
        return [item.strip() for item in field_value.split(',') if item.strip()]
    else:
        return [field_value.strip()]

def map_abstracts(record):
    """
    Mappt Abstract (ABS), Übersetzung Abstract (GAB) auf RIS N2/AB.
    """
    abstract_content = []
    if 'ABS' in record and record['ABS'].strip():
        abstract_content.append(record['ABS'].strip())
    if 'GAB' in record and record['GAB'].strip():
        abstract_content.append(f"Übersetzung Abstract: {record['GAB'].strip()}")
    return "\n".join(abstract_content) if abstract_content else None

def map_keywords(record):
    """
    Extrahiert Schlagwörter aus verschiedenen MIDOS-Feldern.
    """
    keywords = []
    
    for field in ['SWO', 'PSW', 'GSW', 'FSW', 'OSW', 'FISSWO', 'GEO', 'GLA', 'GOR']:
        if field in record and record[field]:
            # Hier verwenden wir _split_multiple_values, da es sich um Keywords handelt,
            # die einfach durch Trennzeichen gelistet sind und keine spezielle Namenslogik benötigen.
            kw_list = _split_multiple_values(record[field])
            for kw in kw_list:
                if kw.strip():
                    # Entferne eventuelle Kommentare in Klammern
                    kw_cleaned = re.sub(r'\(.*?\)', '', kw).strip()
                    if kw_cleaned:
                        keywords.append(kw_cleaned)
    
    return keywords

def map_pages(record):
    """
    Extrahiert die Seitenangaben aus dem KOL-Feld.
    Erkennt sowohl arabische als auch römische Seitenzahlen.
    Für bessere Zotero-Kompatibilität werden komplette Seitenangaben beibehalten.
    """
    if 'KOL' in record and record['KOL'].strip():
        kol = record['KOL'].strip()
        
        # Regex-Pattern für römische Ziffern
        roman_pattern = r'[IVXLCDM]+'
        
        # Pattern für verschiedene Seitenformate:
        # - "XVI, 198 S." (römisch + arabisch)
        # - "S. 1-22" (nur arabisch)
        # - "24-26 S." (arabisch mit Bindestrich)
        # - "XVI S." (nur römisch)
        
        # 1. Komplexe Formate mit römischen und arabischen Zahlen
        # Format: "XVI, 198 S." -> "XVI, 198"
        roman_arabic_match = re.search(rf'({roman_pattern}),?\s*(\d+(?:\s*-\s*\d+)?)\s*S\.?', kol, re.IGNORECASE)
        if roman_arabic_match:
            roman_part = roman_arabic_match.group(1)
            arabic_part = roman_arabic_match.group(2)
            return f"{roman_part}, {arabic_part}"
        
        # 2. Nur römische Seitenzahlen
        # Format: "XVI S." -> "XVI"
        roman_only_match = re.search(rf'({roman_pattern})\s*S\.?', kol, re.IGNORECASE)
        if roman_only_match:
            return roman_only_match.group(1)
        
        # 3. Normale arabische Seitenangaben mit "S."
        page_match = re.search(r'S\.\s*([\d\-,\s]+)', kol)
        if page_match:
            return page_match.group(1).strip()
        
        # 4. Arabische Seitenangaben ohne "S." aber mit Zahlen und Bindestrichen
        page_match = re.search(r'([\d\-,\s]+)\s*S\.', kol)
        if page_match:
            return page_match.group(1).strip()
        
        # 5. Extrahiere Seitenzahlen aus komplexeren Formaten wie "B 3.9, S. 1-22"
        # Suche nach dem letzten Komma gefolgt von optionalem "S." und Seitenzahlen
        complex_match = re.search(r',\s*(?:S\.\s*)?([\d\-]+)\s*$', kol)
        if complex_match:
            return complex_match.group(1).strip()
        
        # 6. Fallback: Versuche Zahlen-Bindestrich-Zahlen Pattern am Ende
        page_match = re.search(r'(\d+(?:\s*-\s*\d+)?)(?:\s*S\.)?$', kol)
        if page_match:
            return page_match.group(1).strip()
    
    return None

def map_volume_info(record):
    """
    Extrahiert Bandangaben aus dem KOL-Feld für bessere Strukturierung.
    Dies wird als separates Feld behandelt.
    """
    if 'KOL' in record and record['KOL'].strip():
        kol = record['KOL'].strip()
        
        # Extrahiere Bandangaben wie "B 3.9" aus "B 3.9, S. 1-22"
        volume_match = re.search(r'^([A-Z]\s*[\d\.]+)', kol)
        if volume_match:
            return volume_match.group(1).strip()
        
        # Weitere Bandformate können hier hinzugefügt werden
        # z.B. "Band 3", "Vol. 2", etc.
        
    return None

def map_pages_end(record):
    """
    Extrahiert die Endseite aus dem KOL-Feld (Seitenangaben).
    Da die kompletten Seitenangaben jetzt in SP stehen, ist EP oft nicht nötig.
    """
    if 'KOL' in record:
        kol = record['KOL']
        # Suche nach Endseite in Formaten wie S. 24-26 oder 24-26 S.
        page_match = re.search(r'S\.\s*\d+\s*-\s*(\d+)', kol) or \
                     re.search(r'\d+\s*-\s*(\d+)\s*S\.', kol)
        
        if page_match:
            return page_match.group(1)
    return None

def map_isbn_issn(record):
    """
    Extrahiert ISBN oder ISSN.
    """
    if 'ISBN' in record and record['ISBN']:
        return record['ISBN']
    elif 'ISSN' in record and record['ISSN']:
        return record['ISSN']
    elif 'ISB' in record and record['ISB']:
        return record['ISB']
    return None

def map_language(record):
    """
    Extrahiert die Sprache des Dokuments.
    """
    if 'LAN' in record:
        # Extrahiere nur den Sprachcode. MIDOS-LAN kann z.B. "pres.:ger | orig.:lat" sein
        lang_match = re.search(r'pres\.:(.*?)(?:$|\s*\|)', record['LAN'])
        if lang_match:
            # RIS bevorzugt 2- oder 3-stellige Codes (z.B. ger -> de)
            lang_code = lang_match.group(1).strip().lower()
            if lang_code == 'ger':
                return 'de'
            elif lang_code == 'eng':
                return 'en'
            elif lang_code == 'fre':
                return 'fr'
            elif lang_code == 'lat':
                return 'la'
            return lang_code # Fallback für andere Sprachen
    return None

def map_parent_book_info(record):
    """
    Extrahiert den kompletten Buchtitel aus dem AUS-Feld für Buchteile (DTY:AM).
    Der komplette Titel bis zum "/" wird übernommen, aber " : " wird durch ". " ersetzt.
    """
    parent_title = None
    parent_editors = []

    if 'AUS' in record and record['AUS'].strip():
        aus_content = record['AUS'].strip()

        # Muster: Titel [ : Untertitel] / Herausgeber (Hrsg.)
        # Extrahiere den Titel vor dem ersten '/'
        title_match = re.match(r'^(.*?)\s*(?:/\s*(.*))?$', aus_content)
        if title_match:
            title_part = title_match.group(1).strip()
            
            # Ersetze " : " durch ". " im kompletten Titel
            parent_title = title_part.replace(' : ', '. ')

            editor_part = title_match.group(2)
            if editor_part:
                # Extrahiere den Herausgeber und entferne "(Hrsg.)" oder ähnliches
                editor_name_match = re.match(r'^(.*?)\s*\(Hrsg\.\)', editor_part)
                if editor_name_match:
                    parent_editors.extend(_split_names_and_clean(editor_name_match.group(1)))
                else:
                    # Fallback, wenn (Hrsg.) nicht gefunden wird, aber es ein Name ist
                    parent_editors.extend(_split_names_and_clean(editor_part))
    
    return parent_title, parent_editors

def process_midos_content(content, output_dir='.'):
    """
    Verarbeitet den MIDOS-Inhalt und erstellt RIS-Dateien.
    """
    records = parse_midos_records(content)
    print(f"Gefundene Datensätze: {len(records)}")
    
    # Erstelle einen einzigartigen Dateinamen basierend auf Datum und Uhrzeit
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = os.path.join(output_dir, f"midos_to_ris_{timestamp}.ris")
    
    with open(output_file, 'w', encoding='utf-8') as f:
        for idx, record in enumerate(records, 1):
            ris_content = map_midos_to_ris(record)
            f.write(ris_content + "\n")
            print(f"Datensatz {idx} konvertiert: {record.get('HST', 'Kein Titel')[:50]}...")
    
    print(f"\nKonvertierung abgeschlossen. RIS-Datei gespeichert unter: {output_file}")
    return output_file

# Beispiel für den direkten Aufruf
if __name__ == "__main__":
    # Skript-Verzeichnis wurde bereits am Anfang gesetzt
    print(f"Arbeite im Verzeichnis: {os.getcwd()}")
    
    input_file = None
    output_dir = script_dir  # Standardmäßig im Skriptverzeichnis speichern
    
    # Verarbeite Kommandozeilenargumente
    if len(sys.argv) > 1:
        # Wenn eine Datei angegeben wurde
        input_arg = sys.argv[1]
        
        # Prüfe, ob es sich um eine Datei oder ein Verzeichnis handelt
        if os.path.isfile(input_arg) or input_arg.endswith('.wrk'):
            input_file = input_arg
            if not os.path.isabs(input_file):
                input_file = os.path.join(script_dir, input_arg) 
        elif os.path.isdir(input_arg):
            # Wenn ein Verzeichnis angegeben wurde, suche dort nach .wrk-Dateien
            wrk_files = find_wrk_files(input_arg)
            if wrk_files:
                print(f"\nGefundene .wrk-Dateien in {input_arg}:")
                for idx, file_path in enumerate(wrk_files, 1):
                    print(f"{idx}. {os.path.basename(file_path)}")
                
                while True:
                    try:
                        choice = input("\nBitte wähle eine Datei (Nummer oder 'q' zum Beenden): ")
                        if choice.lower() == 'q':
                            sys.exit(0)
                        
                        choice_idx = int(choice) - 1
                        if 0 <= choice_idx < len(wrk_files):
                            input_file = wrk_files[choice_idx]
                            break
                        else:
                            print(f"Ungültige Auswahl. Bitte wähle eine Zahl zwischen 1 und {len(wrk_files)}.")
                    except ValueError:
                        print("Ungültige Eingabe. Bitte gib eine Zahl oder 'q' ein.")
            else:
                print(f"Keine .wrk-Dateien im Verzeichnis {input_arg} gefunden.")
                sys.exit(1)
        
        # Prüfe, ob ein Ausgabeverzeichnis angegeben wurde
        if len(sys.argv) > 2:
            output_dir = sys.argv[2]
            if not os.path.isabs(output_dir):
                output_dir = os.path.join(script_dir, output_dir)
    else:
        # Keine Argumente angegeben, suche nach .wrk-Dateien im aktuellen Verzeichnis
        input_file = select_wrk_file()
        if not input_file:
            print("Keine Datei ausgewählt. Beende.")
            sys.exit(0)
    
    # Überprüfe, ob wir eine gültige Eingabedatei haben
    if input_file and os.path.exists(input_file):
        print(f"Lese Datei: {input_file}")
        
        # Erstelle das Ausgabeverzeichnis, falls es nicht existiert
        os.makedirs(output_dir, exist_ok=True)
        
        try:
            with open(input_file, 'r', encoding='utf-8') as f:
                content = f.read()
            
            output_file = process_midos_content(content, output_dir)
            print(f"\nKonvertierung erfolgreich! Die RIS-Datei wurde unter {output_file} gespeichert.")
        except UnicodeDecodeError:
            print("Die Datei konnte nicht im UTF-8-Format gelesen werden. Versuche andere Kodierungen...")
            
            # Versuche andere Kodierungen
            encodings = ['latin1', 'windows-1252', 'iso-8859-1']
            for encoding in encodings:
                try:
                    with open(input_file, 'r', encoding=encoding) as f:
                        content = f.read()
                    
                    print(f"Erfolgreich mit Kodierung {encoding} gelesen.")
                    output_file = process_midos_content(content, output_dir)
                    print(f"\nKonvertierung erfolgreich! Die RIS-Datei wurde unter {output_file} gespeichert.")
                    break
                except Exception as e:
                    print(f"Fehler beim Lesen mit Kodierung {encoding}: {str(e)}")
            else:
                print("Die Datei konnte mit keiner der verfügbaren Kodierungen gelesen werden.")
        except Exception as e:
            print(f"Fehler bei der Verarbeitung: {str(e)}")
    else:
        if input_file:
            print(f"Fehler: Die Datei '{input_file}' wurde nicht gefunden.")
        print("\nVerwendung: python midos_to_ris.py [input_file.wrk oder Verzeichnis] [output_directory]")
        print("Wenn keine Argumente angegeben werden, werden .wrk-Dateien im aktuellen Verzeichnis gesucht.")
