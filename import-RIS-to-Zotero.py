#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Zotero RIS Import Script
------------------------
Dieses Skript importiert RIS-Dateien in eine Zotero-Gruppensammlung.

Features:
- Robuste Fehlerbehandlung und Retry-Logik
- Intelligenter Fallback-Parser bei Zotero-Server-Überlastung
- Automatische Erkennung und korrekte Verarbeitung von Sammelbänden
- Detaillierte Logging und Fortschrittsanzeige
- Batch-Upload mit konfigurierbarer Größe

Version: 1.0
Datum: 2025-07-15
Lizenz: MIT
"""

import requests
import json
import time
import logging
from typing import List, Dict, Optional, Tuple
from datetime import datetime
import os

# Wechsle zum Verzeichnis des Skripts, um relative Pfade zu vereinfachen
script_dir = os.path.dirname(os.path.abspath(__file__))
os.chdir(script_dir)

# Robustes Logging konfigurieren
def setup_logging():
    """Logging sicher konfigurieren mit Fehlerbehandlung"""
    
    # Logger erstellen
    logger = logging.getLogger(__name__)
    
    # Vermeide doppelte Handler
    if logger.handlers:
        return logger
        
    logger.setLevel(logging.INFO)
    
    # Formatter
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    
    # Console Handler (immer funktionierend)
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    
    # File Handler mit Fehlerbehandlung
    try:
        log_filename = f'zotero_import_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log'
        file_handler = logging.FileHandler(log_filename, mode='w', encoding='utf-8')
        file_handler.setLevel(logging.INFO)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
        
        # Test-Schreibung
        logger.info(f"📝 Log-Datei erstellt: {log_filename}")
        file_handler.flush()  # Sofort schreiben
        
    except (PermissionError, OSError) as e:
        logger.warning(f"⚠️  Konnte Log-Datei nicht erstellen: {e}")
        logger.warning("📺 Ausgabe nur in Konsole")
    
    return logger

# Logger initialisieren
logger = setup_logging()

class ZoteroImporter:
    def __init__(self, group_id: str, api_key: str):
        self.group_id = group_id
        self.api_key = api_key
        self.translation_servers = [
            "https://translate.zotero.org/web",
            "https://translate.zotero.org/web",  # Backup (same server, but for retry)
        ]
        self.chunk_size = 100  # Anzahl RIS-Einträge pro Translation-Request
        self.use_fallback_parser = True  # Manuellen Parser bei Server-Problemen verwenden
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'ZoteroImporter/1.0 (Python)'
        })
        self.skip_translation_server = True  
        
    def validate_ris_content(self, ris_content: str) -> Tuple[bool, str]:
        """RIS-Inhalt validieren"""
        if not ris_content.strip():
            return False, "RIS-Datei ist leer"
        
        if not any(line.startswith('TY  -') for line in ris_content.split('\n')):
            return False, "Keine gültigen RIS-Einträge gefunden (TY-Tag fehlt)"
        
        # Zähle Einträge
        entries = ris_content.count('TY  -')
        if entries == 0:
            return False, "Keine RIS-Einträge gefunden"
        
        logger.info(f"✓ RIS-Datei validiert: {entries} Einträge gefunden")
        return True, f"{entries} Einträge gefunden"

    def split_ris_content(self, ris_content: str, chunk_size: int = 100) -> List[str]:
        """RIS-Content in kleinere Chunks aufteilen"""
        entries = []
        current_entry = []
        
        for line in ris_content.split('\n'):
            if line.startswith('TY  -') and current_entry:
                entries.append('\n'.join(current_entry))
                current_entry = [line]
            else:
                current_entry.append(line)
        
        if current_entry:
            entries.append('\n'.join(current_entry))
        
        # Entries in Chunks aufteilen
        chunks = []
        for i in range(0, len(entries), chunk_size):
            chunk = entries[i:i+chunk_size]
            chunks.append('\n'.join(chunk))
        
        logger.info(f"RIS aufgeteilt in {len(chunks)} Chunks à max. {chunk_size} Einträge")
        return chunks

    def parse_ris_manually(self, ris_content: str) -> List[Dict]:
        """
        Vollständiger manueller RIS-Parser mit umfassendem Logging
        Jetzt mit Sammelband-Unterstützung
        """
        logger.info("🔧 FALLBACK PARSER AKTIVIERT")
        logger.info("=" * 50)
        
        # Eingabe-Statistiken
        lines = ris_content.split('\n')
        entry_count = ris_content.count('TY  -')
        logger.info(f"📄 Analysiere {len(lines)} Zeilen")
        logger.info(f"📚 Erkannte RIS-Einträge: {entry_count}")
        logger.info(f"⚡ Beginne manuelles Parsing...")
        logger.info("-" * 50)
        
        items = []
        current_item = None
        processed_entries = 0
        
        # Statistiken
        item_types = {}
        creator_stats = {'authors': 0, 'editors': 0, 'contributors': 0}
        field_stats = {}
        
        # Zotero Item-Type spezifische Felder (erweitert mit book für Sammelbände)
        valid_fields = {
            'journalArticle': ['title', 'creators', 'publicationTitle', 'volume', 'issue', 'pages', 'date', 'ISSN', 'url', 'abstractNote', 'tags', 'DOI', 'language', 'extra', 'callNumber'],
            'book': ['title', 'creators', 'publisher', 'place', 'date', 'ISBN', 'url', 'abstractNote', 'tags', 'language', 'numPages', 'series', 'seriesNumber', 'edition', 'extra', 'callNumber'],
            'bookSection': ['title', 'creators', 'bookTitle', 'publisher', 'place', 'date', 'pages', 'ISBN', 'url', 'abstractNote', 'tags', 'language', 'series', 'seriesNumber', 'edition', 'extra', 'callNumber'],
            'conferencePaper': ['title', 'creators', 'proceedingsTitle', 'place', 'date', 'pages', 'url', 'abstractNote', 'tags', 'DOI', 'language', 'conferenceName', 'extra', 'callNumber'],
            'thesis': ['title', 'creators', 'university', 'place', 'date', 'thesisType', 'url', 'abstractNote', 'tags', 'language', 'extra', 'callNumber'],
            'report': ['title', 'creators', 'institution', 'place', 'date', 'reportNumber', 'url', 'abstractNote', 'tags', 'language', 'reportType', 'extra', 'callNumber'],
            'webpage': ['title', 'creators', 'websiteTitle', 'url', 'accessDate', 'abstractNote', 'tags', 'language', 'extra'],
            'newspaperArticle': ['title', 'creators', 'publicationTitle', 'place', 'date', 'pages', 'url', 'abstractNote', 'tags', 'language', 'section', 'edition', 'extra', 'callNumber'],
            'magazineArticle': ['title', 'creators', 'publicationTitle', 'date', 'pages', 'ISSN', 'url', 'abstractNote', 'tags', 'language', 'extra', 'callNumber'],
            'document': ['title', 'creators', 'publisher', 'date', 'url', 'abstractNote', 'tags', 'language', 'extra', 'callNumber'],
            'manuscript': ['title', 'creators', 'place', 'date', 'manuscriptType', 'url', 'abstractNote', 'tags', 'language', 'extra', 'callNumber'],
            'presentation': ['title', 'creators', 'presentationType', 'place', 'date', 'url', 'abstractNote', 'tags', 'language', 'extra'],
            'patent': ['title', 'creators', 'country', 'assignee', 'patentNumber', 'priorityNumbers', 'date', 'url', 'abstractNote', 'tags', 'language', 'extra'],
            'computerProgram': ['title', 'creators', 'company', 'place', 'date', 'programmingLanguage', 'system', 'url', 'abstractNote', 'tags', 'language', 'extra'],
            'audioRecording': ['title', 'creators', 'label', 'place', 'date', 'runningTime', 'url', 'abstractNote', 'tags', 'language', 'extra'],
            'videoRecording': ['title', 'creators', 'studio', 'place', 'date', 'runningTime', 'url', 'abstractNote', 'tags', 'language', 'extra']
        }
        
        # Erweiterte RIS zu Zotero Feld-Mapping (mit T4 und H2)
        field_mapping = {
            # Standard Felder
            'TY': 'itemType',
            'TI': 'title', 
            'T1': 'title',
            'T2': 'publicationTitle',  # Journal/Book title
            'T3': 'series',           # Series title
            'T4': 'subtitle',         # Untertitel (wird mit Titel zusammengeführt)
            'AU': 'creators',         # Author
            'A1': 'creators',         # Primary Author
            'A2': 'creators',         # Secondary Author (Editor)
            'A3': 'creators',         # Tertiary Author
            'ED': 'creators',         # Editor
            'PY': 'date',
            'Y1': 'date',
            'DA': 'date',
            'JO': 'publicationTitle', # Journal abbreviation
            'JF': 'publicationTitle', # Journal full name
            'JA': 'publicationTitle', # Journal abbreviation
            'VL': 'volume',
            'IS': 'issue',
            'SP': 'start_page',       # Start page (wird später kombiniert)
            'EP': 'end_page',         # End page (wird später kombiniert)
            'PB': 'publisher',
            'CY': 'place',
            'SN': 'ISSN',             # ISSN/ISBN
            'BN': 'ISBN',             # ISBN
            'UR': 'url',
            'L1': 'url',              # Link to PDF
            'L2': 'url',              # Link to Full Text
            'AB': 'abstractNote',
            'N2': 'abstractNote',
            'N1': 'extra',            # Notes/Extra info
            'KW': 'tags',
            'DO': 'DOI',
            'LA': 'language',
            'CN': 'callNumber',       # Call Number/Signatur
            'H2': 'callNumber',       # Zusätzliche Signatur (Alternative zu CN)
            'M1': 'extra',            # Miscellaneous 1
            'M2': 'extra',            # Miscellaneous 2
            'M3': 'extra',            # Miscellaneous 3
            'AD': 'extra',            # Author Address
            'AN': 'extra',            # Accession Number
            'AV': 'extra',            # Availability
            'C1': 'extra',            # Custom 1
            'C2': 'extra',            # Custom 2
            'C3': 'extra',            # Custom 3
            'CA': 'extra',            # Caption
            'DB': 'extra',            # Database
            'DP': 'extra',            # Database Provider
            'ET': 'edition',          # Edition
            'ID': 'extra',            # Reference ID
            'IP': 'issue',            # Issue
            'NV': 'seriesNumber',     # Number of Volumes
            'OP': 'extra',            # Original Publication
            'PP': 'place',            # Place Published
            'RP': 'extra',            # Reprint Edition
            'SE': 'section',          # Section
            'ST': 'shortTitle',       # Short Title
            'TA': 'extra',            # Translated Author
            'TT': 'extra',            # Translated Title
            'U1': 'extra',            # User definable 1
            'U2': 'extra',            # User definable 2
            'U3': 'extra',            # User definable 3
            'U4': 'extra',            # User definable 4
            'U5': 'extra',            # User definable 5
            'Y2': 'accessDate',       # Access Date
        }
        
        # Item-Type Mapping (erweitert mit SAMMELBAND)
        type_mapping = {
            'JOUR': 'journalArticle',
            'BOOK': 'book',
            'CHAP': 'bookSection',
            'CONF': 'conferencePaper',
            'THES': 'thesis',
            'RPRT': 'report',
            'WEB': 'webpage',
            'NEWS': 'newspaperArticle',
            'MGZN': 'magazineArticle',
            'ABST': 'journalArticle',
            'ADVS': 'audiovisualMaterial',
            'AGGR': 'journalArticle',
            'ANCIENT': 'manuscript',
            'ART': 'artwork',
            'BILL': 'bill',
            'BLOG': 'blogPost',
            'CASE': 'case',
            'CTLG': 'catalog',
            'DATA': 'dataset',
            'DBASE': 'computerProgram',
            'DICT': 'dictionaryEntry',
            'EBOOK': 'book',
            'ECHAP': 'bookSection',
            'EDBOOK': 'book',
            'EJOUR': 'journalArticle',
            'ELEC': 'document',
            'ENCYC': 'encyclopediaArticle',
            'EQUA': 'equation',
            'FIGURE': 'figure',
            'GEN': 'report',          
            'GOVDOC': 'report',       
            'GRANT': 'document',
            'HEAR': 'hearing',
            'ICOMM': 'document',
            'INPR': 'document',
            'JFULL': 'journalArticle',
            'LEGAL': 'document',
            'MANSCPT': 'manuscript',
            'MAP': 'map',
            'MULTI': 'document',
            'MUSIC': 'audioRecording',
            'PAMP': 'document',
            'PAT': 'patent',
            'PCOMM': 'letter',
            'SLIDE': 'presentation',
            'SOUND': 'audioRecording',
            'STAND': 'document',
            'STAT': 'statute',
            'UNBILL': 'bill',
            'UNPB': 'document',
            'VIDEO': 'videoRecording',
            # NEUE SAMMELBÄNDE
            'SAMMELBAND': 'book',     # Sammelband -> book (herausgegebenes Buch)
            'SAMMLUNG': 'book',       # Alternative deutsche Bezeichnung
            'EDITED': 'book',         # Alternative englische Bezeichnung
            'ANTHOLOGY': 'book'       # Anthologie/Sammelwerk
        }
        
        for line_num, line in enumerate(lines):
            line = line.strip()
            
            if line.startswith('TY  -'):
                # Neuer Eintrag
                if current_item:
                    items.append(self._finalize_item(current_item, valid_fields))
                    
                processed_entries += 1
                
                # Progress-Updates
                if processed_entries % 50 == 0:
                    logger.info(f"⏳ Fallback Progress: {processed_entries}/{entry_count} Einträge verarbeitet...")
                elif processed_entries % 10 == 0:
                    # Kürzere Updates für kleine Dateien
                    if entry_count < 100:
                        logger.info(f"⏳ Parsing: {processed_entries}/{entry_count}")
                
                # Item initialisieren
                current_item = {
                    'creators': [], 
                    'tags': [], 
                    'extra_info': [],
                    'subtitle': None,  # Für T4 Untertitel
                    'is_sammelband': False  # Flag für Sammelband-Erkennung
                }
                
                # Item Type setzen
                ris_type = line.split('TY  - ', 1)[1].strip()
                zotero_type = type_mapping.get(ris_type, 'journalArticle')
                current_item['itemType'] = zotero_type
                
                # Sammelband-Flag setzen
                if ris_type in ['SAMMELBAND', 'SAMMLUNG', 'EDITED', 'ANTHOLOGY']:
                    current_item['is_sammelband'] = True
                    logger.debug(f"🔖 Sammelband erkannt: {ris_type}")
                
                # Statistiken
                item_types[zotero_type] = item_types.get(zotero_type, 0) + 1
                
            elif line.startswith('ER  -'):
                # Eintrag Ende
                if current_item:
                    items.append(self._finalize_item(current_item, valid_fields))
                    current_item = None
                    
            elif '  - ' in line and current_item is not None:
                # Feld parsen
                try:
                    tag, value = line.split('  - ', 1)
                    value = value.strip()
                    
                    if not value:
                        continue
                    
                    # Statistiken
                    field_stats[tag] = field_stats.get(tag, 0) + 1

                    # C3 direkt für Pages-Verarbeitung speichern
                    if tag == 'C3':
                        current_item['C3'] = value
                        continue
                        
                    zotero_field = field_mapping.get(tag)
                    if not zotero_field:
                        # Unbekannte Felder in Extra sammeln
                        current_item['extra_info'].append(f"{tag}: {value}")
                        continue
                        
                    if zotero_field == 'creators':
                        # Creator-Type basierend auf RIS-Tag bestimmen
                        # Bei Sammelbänden: A2/ED werden standardmäßig als Herausgeber behandelt
                        creator_type = 'author'
                        if tag in ['A2', 'ED']:
                            creator_type = 'editor'
                            creator_stats['editors'] += 1
                        elif tag == 'A3':
                            creator_type = 'contributor'
                            creator_stats['contributors'] += 1
                        else:
                            # Bei Sammelbänden: AU/A1 können auch Herausgeber sein
                            if current_item.get('is_sammelband', False):
                                # Für Sammelbände: erste Creators als Herausgeber behandeln
                                # es sei denn, es sind schon explizite Herausgeber vorhanden
                                existing_editors = [c for c in current_item['creators'] if c.get('creatorType') == 'editor']
                                if not existing_editors:
                                    creator_type = 'editor'
                                    creator_stats['editors'] += 1
                                else:
                                    creator_stats['authors'] += 1
                            else:
                                creator_stats['authors'] += 1
                        
                        # Name parsen (LastName, FirstName Format)
                        if ',' in value:
                            parts = value.split(',', 1)
                            lastName = parts[0].strip()
                            firstName = parts[1].strip() if len(parts) > 1 else ''
                            current_item['creators'].append({
                                'creatorType': creator_type,
                                'lastName': lastName,
                                'firstName': firstName
                            })
                        else:
                            current_item['creators'].append({
                                'creatorType': creator_type,
                                'name': value
                            })
                            
                    elif zotero_field == 'tags':
                        # Tag hinzufügen
                        current_item['tags'].append({'tag': value})
                        
                    elif zotero_field == 'extra':
                        # Extra-Info sammeln
                        current_item['extra_info'].append(value)
                        
                    elif zotero_field == 'title':
                        # Titel-Behandlung: T1/TI mit eventuell vorhandenem T4 zusammenführen
                        existing_subtitle = current_item.get('subtitle')
                        if existing_subtitle:
                            # T4 war bereits da, zusammenführen
                            current_item['title'] = f"{value}. {existing_subtitle}"
                            current_item.pop('subtitle', None)  # Subtitle nicht mehr nötig
                        else:
                            # Normaler Titel ohne Untertitel
                            current_item['title'] = value
                            
                    elif zotero_field == 'subtitle':
                        # T4 Untertitel für späteren Merge mit Titel
                        existing_title = current_item.get('title')
                        if existing_title:
                            # T1/TI war bereits da, zusammenführen
                            current_item['title'] = f"{existing_title}. {value}"
                            # Subtitle wird nicht gesetzt, da bereits zusammengeführt
                        else:
                            # T4 kommt vor T1, zwischenspeichern
                            current_item['subtitle'] = value
                        
                    elif zotero_field == 'start_page':
                        current_item['start_page'] = value
                    elif zotero_field == 'end_page':
                        current_item['end_page'] = value
                        
                    elif zotero_field == 'date':
                        # Datum normalisieren (YYYY/MM/DD oder YYYY)
                        if value and not current_item.get('date'):
                            # Nur Jahr extrahieren falls komplexes Datum
                            import re
                            year_match = re.search(r'\b(19|20)\d{2}\b', value)
                            if year_match:
                                current_item['date'] = year_match.group()
                            else:
                                current_item['date'] = value
                                
                    else:
                        # Normales Feld
                        current_item[zotero_field] = value
                        
                except Exception as e:
                    logger.warning(f"Fehler beim Parsen der Zeile {line_num}: '{line}' - {e}")
                    continue
        
        # Letzten Eintrag hinzufügen
        if current_item:
            items.append(self._finalize_item(current_item, valid_fields))
        
        # Detaillierte Abschluss-Statistiken
        sammelbände_count = sum(1 for item in items if item.get('_was_sammelband', False))
        
        logger.info("-" * 50)
        logger.info("🎯 FALLBACK PARSER ABGESCHLOSSEN")
        logger.info(f"✅ Erfolgreich geparst: {len(items)} Items")
        logger.info(f"📚 Davon Sammelbände: {sammelbände_count}")
        logger.info(f"📊 Item-Typen: {dict(sorted(item_types.items()))}")
        logger.info(f"👥 Creators: Autoren={creator_stats['authors']}, Herausgeber={creator_stats['editors']}, Mitwirkende={creator_stats['contributors']}")
        
        # Top 10 häufigste RIS-Felder
        top_fields = sorted(field_stats.items(), key=lambda x: x[1], reverse=True)[:10]
        logger.info(f"🏷️  Häufigste RIS-Felder: {dict(top_fields)}")
        
        logger.info("=" * 50)
        
        return items

    def _finalize_item(self, item: Dict, valid_fields: Dict) -> Dict:
        """Item finalisieren und für Zotero validieren - mit Sammelband-Behandlung"""
        item_type = item.get('itemType', 'journalArticle')
        allowed_fields = valid_fields.get(item_type, valid_fields['journalArticle'])
        is_sammelband = item.pop('is_sammelband', False)
        
        # Titel mit Untertitel zusammenführen (T4)
        title = item.get('title', '')
        subtitle = item.pop('subtitle', None)
        if title and subtitle:
            # Format: "Titel. Untertitel"
            item['title'] = f"{title}. {subtitle}"
        elif subtitle and not title:
            # Falls nur Untertitel vorhanden
            item['title'] = subtitle
        
        # Seiten korrekt zusammenfügen
        start_page = item.pop('start_page', None)
        end_page = item.pop('end_page', None)
        c3_info = item.pop('C3', None)  # C3 für erweiterte Seiten-Info

        if 'pages' in allowed_fields or 'numPages' in allowed_fields:
            page_parts = []
            
            # SP analysieren: unterscheiden zwischen "XVI, 198" und "1-22"
            if start_page:
                if ',' in start_page:
                    # Format "XVI, 198" -> komplett in numPages
                    if 'numPages' in allowed_fields:
                        item['numPages'] = start_page  # Komplette Angabe "XVI, 198"
                        
                    # C3 zu pages hinzufügen falls vorhanden
                    if c3_info and 'pages' in allowed_fields:
                        item['pages'] = c3_info
                else:
                    # Normale Seitenangabe "1-22"
                    if c3_info:
                        page_parts.append(c3_info)
                    page_parts.append(start_page)
                    
                    if 'pages' in allowed_fields and page_parts:
                        item['pages'] = ', '.join(page_parts)
            
            elif end_page and 'pages' in allowed_fields:
                if c3_info:
                    item['pages'] = f"{c3_info}, {end_page}"
                else:
                    item['pages'] = end_page
        
    
        # Extra-Informationen zusammenfassen
        extra_info = item.pop('extra_info', [])
        
        # Sammelband-Info zu Extra hinzufügen
        if is_sammelband:
            extra_info.insert(0, "Type: Sammelband")
            item['_was_sammelband'] = True  # Flag für Statistiken
        
        if extra_info and 'extra' in allowed_fields:
            unique_parts = list(dict.fromkeys(extra_info))  # Deduplizieren
            existing_extra = item.get('extra', '')
            if existing_extra:
                unique_parts.insert(0, existing_extra)
            
            # " | " zu Zeilenumbrüchen konvertieren für bessere Lesbarkeit
            combined_extra = '\n'.join(unique_parts)
            combined_extra = combined_extra.replace(' | ', '\n')
            item['extra'] = combined_extra
        
        # Feld-Anpassungen basierend auf Item-Type
        if item_type == 'bookSection':
            if 'publicationTitle' in item:
                item['bookTitle'] = item.pop('publicationTitle')
            item.pop('ISSN', None)
            item.pop('volume', None)
            item.pop('issue', None)
            
        elif item_type == 'book':
            # Für Sammelbände: spezielle Behandlung
            if is_sammelband:
                # Bei Sammelbänden: sicherstellen, dass Herausgeber korrekt gesetzt sind
                creators = item.get('creators', [])
                has_editors = any(c.get('creatorType') == 'editor' for c in creators)
                
                # Falls keine expliziten Herausgeber: erste Creators zu Herausgebern machen
                if not has_editors and creators:
                    for creator in creators:
                        if creator.get('creatorType') == 'author':
                            creator['creatorType'] = 'editor'
                            logger.debug(f"📝 Autor zu Herausgeber geändert: {creator.get('lastName', creator.get('name', ''))}")
            
            if 'ISSN' in item:
                item['ISBN'] = item.pop('ISSN')
            item.pop('publicationTitle', None)
            item.pop('volume', None)
            item.pop('issue', None)
            item.pop('pages', None)
            
        elif item_type == 'journalArticle':
            item.pop('place', None)
            item.pop('publisher', None)
            
        elif item_type in ['document', 'report']:
            # Für document/report: ungültige Felder in Extra verschieben
            invalid_fields = ['place', 'series', 'seriesNumber', 'pages', 'volume', 'issue', 'ISSN', 'ISBN', 'DOI']
            extra_additions = []
            
            for field in invalid_fields:
                if field in item:
                    value = item.pop(field)
                    if field == 'place':
                        extra_additions.append(f"Place: {value}")
                    elif field == 'series':
                        extra_additions.append(f"Series: {value}")
                    elif field == 'pages':
                        extra_additions.append(f"Pages: {value}")
                    elif field == 'DOI':
                        extra_additions.append(f"DOI: {value}")
                    else:
                        extra_additions.append(f"{field}: {value}")
            
            if extra_additions:
                existing_extra = item.get('extra', '')
                if existing_extra:
                    extra_additions.insert(0, existing_extra)
                item['extra'] = '\n'.join(extra_additions)
            
        elif item_type == 'conferencePaper':
            if 'publicationTitle' in item:
                item['proceedingsTitle'] = item.pop('publicationTitle')
            item.pop('ISSN', None)
            item.pop('volume', None)
            item.pop('issue', None)
        
        # Nur erlaubte Felder behalten
        cleaned_item = {}
        for key, value in item.items():
            if key in allowed_fields or key in ['itemType', 'creators', 'tags', '_was_sammelband']:
                cleaned_item[key] = value
        
        # Leere Arrays entfernen
        if not cleaned_item.get('creators'):
            cleaned_item.pop('creators', None)
        if not cleaned_item.get('tags'):
            cleaned_item.pop('tags', None)
            
        return cleaned_item

    def convert_ris_with_fallback(self, ris_content: str) -> Optional[List[Dict]]:
        """RIS konvertieren mit intelligentem Fallback-System - SOFORT FALLBACK"""
        
        # SOFORT FALLBACK: Server sind oft überlastet
        if self.use_fallback_parser:
            logger.info("⚡ DIREKTER FALLBACK aktiviert - überspringe Translation Server")
            logger.info("🔧 Verwende sofort den manuellen Parser (zuverlässiger)")
            logger.info("📊 Sie erhalten detaillierte Progress-Updates...")
            
            try:
                return self.parse_ris_manually(ris_content)
            except Exception as e:
                logger.error(f"❌ Fallback-Parser fehlgeschlagen: {e}")
                return None
        
        # Optional: Translation Server nur wenn explizit gewünscht
        logger.info("🌐 Versuche Zotero Translation Server (oft überlastet)...")
        items = self.convert_ris_with_retry(ris_content, max_retries=1)
        
        if items:
            logger.info(f"✅ Translation Server erfolgreich: {len(items)} Items")
            return items
        else:
            logger.error("❌ Translation Server fehlgeschlagen und Fallback deaktiviert")
            return None

    def convert_ris_with_retry(self, ris_content: str, max_retries: int = 5) -> Optional[List[Dict]]:
        """RIS zu Zotero-JSON mit Retry-Logik und intelligentem Fallback"""
        
        # Erst versuchen, alles auf einmal zu konvertieren
        logger.info("Versuche vollständige Translation...")
        result = self._convert_single_chunk(ris_content, max_retries=2)
        if result:
            return result
        
        # Falls das fehlschlägt, in kleinere Chunks aufteilen
        logger.warning("Vollständige Translation fehlgeschlagen. Teile in Chunks auf...")
        chunks = self.split_ris_content(ris_content, self.chunk_size)
        
        all_items = []
        failed_chunks = 0
        fallback_used = False  # Flag um Schleife zu vermeiden
        
        for i, chunk in enumerate(chunks):
            logger.info(f"Chunk {i+1}/{len(chunks)} ({chunk.count('TY  -')} Einträge)...")
            
            chunk_items = self._convert_single_chunk(chunk, max_retries)
            if chunk_items:
                all_items.extend(chunk_items)
                logger.info(f"✓ Chunk {i+1} erfolgreich: {len(chunk_items)} Items")
                failed_chunks = 0  # Reset bei Erfolg
            else:
                failed_chunks += 1
                logger.error(f"❌ Chunk {i+1} fehlgeschlagen")
                
                # Schneller Fallback: Nach 2 aufeinanderfolgenden Fehlern
                if failed_chunks >= 2 and not fallback_used:
                    logger.warning("⚡ 2 Chunks hintereinander fehlgeschlagen - aktiviere sofort Fallback-Parser!")
                    fallback_used = True  # Verhindert weitere Fallback-Versuche
                    
                    remaining_chunks = chunks[max(0, i-1):]  # Sichere Index-Berechnung
                    remaining_content = '\n'.join(remaining_chunks)
                    
                    if self.use_fallback_parser:
                        try:
                            fallback_items = self.parse_ris_manually(remaining_content)
                            if fallback_items:
                                # Entferne bereits erfolgreich verarbeitete Items
                                successful_entries = sum(chunk.count('TY  -') for chunk in chunks[:max(0, i-1)])
                                if successful_entries > 0 and successful_entries < len(fallback_items):
                                    fallback_items = fallback_items[successful_entries:]
                                
                                all_items.extend(fallback_items)
                                logger.info(f"🔧 Fallback erfolgreich: {len(fallback_items)} Items hinzugefügt")
                                logger.info("✅ Stoppe Chunk-Verarbeitung - Fallback komplett")
                                break
                            else:
                                logger.error("❌ Fallback-Parser gab keine Items zurück")
                        except Exception as e:
                            logger.error(f"❌ Fallback-Parser fehlgeschlagen: {e}")
                            logger.error("⚠️  Setze Chunk-Verarbeitung fort...")
            
            # Pause zwischen Chunks bei Server-Überlastung
            if i < len(chunks) - 1 and not fallback_used:
                time.sleep(2)
        
        if failed_chunks > 0 and not all_items:
            logger.warning(f"⚠️  Alle Chunks fehlgeschlagen")
        
        return all_items if all_items else None

    def _convert_single_chunk(self, ris_content: str, max_retries: int = 5) -> Optional[List[Dict]]:
        """Einzelnen RIS-Chunk konvertieren"""
        
        for attempt in range(max_retries):
            for server_idx, server_url in enumerate(self.translation_servers):
                try:
                    wait_time_503 = min(60, 5 * (2 ** attempt))  # Max 60s warten
                    
                    response = self.session.post(
                        server_url,
                        data=ris_content.encode('utf-8'),
                        headers={'Content-Type': 'text/plain'},
                        timeout=120  # Längerer Timeout
                    )
                    
                    if response.status_code == 200:
                        try:
                            items = response.json()
                            if isinstance(items, list) and len(items) > 0:
                                return items
                            else:
                                logger.warning("Translation gab leere Antwort zurück")
                                continue
                        except json.JSONDecodeError as e:
                            logger.error(f"JSON-Parse-Fehler: {e}")
                            continue
                    
                    elif response.status_code == 503:
                        logger.warning(f"Server überlastet (503). Warte {wait_time_503}s... (Versuch {attempt+1})")
                        time.sleep(wait_time_503)
                        continue
                    
                    elif response.status_code == 429:
                        retry_after = int(response.headers.get('Retry-After', 120))
                        logger.warning(f"Rate limit erreicht. Warte {retry_after}s...")
                        time.sleep(retry_after)
                        continue
                    
                    else:
                        logger.error(f"Translation Server Fehler: {response.status_code}")
                        continue
                        
                except requests.exceptions.Timeout:
                    logger.warning(f"Timeout bei Server {server_idx + 1}")
                    continue
                except requests.exceptions.ConnectionError:
                    logger.warning(f"Verbindungsfehler zu Server {server_idx + 1}")
                    time.sleep(5)
                    continue
                except Exception as e:
                    logger.error(f"Unerwarteter Fehler: {e}")
                    continue
            
            # Längere Pause zwischen Versuchen
            if attempt < max_retries - 1:
                wait_time = min(300, 30 * (attempt + 1))  # Max 5 Minuten
                logger.info(f"Alle Server fehlgeschlagen. Warte {wait_time}s vor nächstem Versuch...")
                time.sleep(wait_time)
        
        return None

    def get_library_version(self) -> Optional[str]:
        """Aktuelle Library-Version abrufen mit Retry"""
        for attempt in range(3):
            try:
                url = f"https://api.zotero.org/groups/{self.group_id}/items"
                response = self.session.get(
                    url, 
                    headers={"Zotero-API-Key": self.api_key},
                    params={"limit": 1},
                    timeout=30
                )
                
                if response.status_code == 200:
                    version = response.headers.get('Last-Modified-Version')
                    logger.info(f"✓ Library-Version abgerufen: {version}")
                    return version
                else:
                    logger.warning(f"Fehler beim Abrufen der Library-Version: {response.status_code}")
                    
            except Exception as e:
                logger.warning(f"Versuch {attempt + 1}: {e}")
                time.sleep(2)
        
        logger.error("Konnte Library-Version nicht abrufen")
        return None

    def get_existing_items(self) -> List[Dict]:
        """Alle existierenden Items aus der Zotero-Bibliothek abrufen für Duplikatsprüfung"""
        logger.info("📚 Lade existierende Items für Duplikatsprüfung...")
        all_items = []
        start = 0
        limit = 100
        
        while True:
            try:
                url = f"https://api.zotero.org/groups/{self.group_id}/items"
                params = {
                    "start": start,
                    "limit": limit,
                    "format": "json",
                    "include": "data"
                }
                
                response = self.session.get(
                    url,
                    headers={"Zotero-API-Key": self.api_key},
                    params=params,
                    timeout=60
                )
                
                if response.status_code == 200:
                    items = response.json()
                    if not items:
                        break
                    
                    # Items im vollständigen Format für besseren Vergleich speichern
                    for item in items:
                        data = item.get('data', {})
                        # Vollständiges Item-Objekt für normalize_item_for_comparison
                        full_item = {
                            'key': data.get('key'),
                            'title': data.get('title', ''),
                            'DOI': data.get('DOI', ''),
                            'ISBN': data.get('ISBN', ''),
                            'ISSN': data.get('ISSN', ''),
                            'creators': data.get('creators', []),
                            'date': data.get('date', ''),
                            'publicationTitle': data.get('publicationTitle', ''),
                            'bookTitle': data.get('bookTitle', ''),  # Für bookSections
                            'volume': data.get('volume', ''),
                            'issue': data.get('issue', ''),
                            'pages': data.get('pages', ''),
                            'itemType': data.get('itemType', ''),
                            'publisher': data.get('publisher', ''),
                            'place': data.get('place', ''),
                            'abstractNote': data.get('abstractNote', ''),
                            'url': data.get('url', ''),
                            'extra': data.get('extra', '')
                        }
                        all_items.append(full_item)
                    
                    start += limit
                    if start % 500 == 0:
                        logger.info(f"   📖 {start} Items geladen...")
                else:
                    logger.error(f"Fehler beim Laden existierender Items: {response.status_code}")
                    break
                    
            except Exception as e:
                logger.error(f"Fehler beim Laden existierender Items: {e}")
                break
        
        logger.info(f"✅ {len(all_items)} existierende Items geladen")
        return all_items

    def normalize_item_for_comparison(self, item: Dict) -> Dict:
        """Normalisiert ein Item für den Duplikatsvergleich
        Konvertiert sowohl neue Upload-Items als auch existierende Zotero-Items in ein einheitliches Format"""
        
        # Titel normalisieren
        title = item.get('title', '').lower().strip()
        # Entferne häufige Variationen
        title = title.replace('  ', ' ').replace('\n', ' ').replace('\t', ' ')
        
        # DOI normalisieren
        doi = item.get('DOI', '').lower().strip()
        if doi.startswith('doi:'):
            doi = doi[4:]
        if doi.startswith('http://dx.doi.org/'):
            doi = doi[18:]
        if doi.startswith('https://doi.org/'):
            doi = doi[16:]
        
        # Creators normalisieren
        creators = []
        for creator in item.get('creators', []):
            if 'lastName' in creator:
                name = f"{creator.get('lastName', '')}, {creator.get('firstName', '')}".lower().strip()
            else:
                name = creator.get('name', '').lower().strip()
            # Entferne überflüssige Leerzeichen und Kommas
            name = name.replace('  ', ' ').strip(' ,')
            if name:
                creators.append(name)
        
        # Datum normalisieren - nur Jahr extrahieren
        date = item.get('date', '').strip()
        year = ''
        if date:
            import re
            year_match = re.search(r'\b(19|20)\d{2}\b', date)
            if year_match:
                year = year_match.group()
        
        # Publikationstitel normalisieren
        pub_title = item.get('publicationTitle', '').lower().strip()
        # Auch bookTitle für bookSections berücksichtigen
        if not pub_title:
            pub_title = item.get('bookTitle', '').lower().strip()
        
        # ISBN/ISSN normalisieren
        isbn = item.get('ISBN', '').replace('-', '').replace(' ', '').lower()
        issn = item.get('ISSN', '').replace('-', '').replace(' ', '').lower()
        
        # Volume und Issue normalisieren
        volume = item.get('volume', '').strip()
        issue = item.get('issue', '').strip()
        
        # Pages normalisieren
        pages = item.get('pages', '').strip()
        
        return {
            'title': title,
            'doi': doi,
            'creators': creators,
            'year': year,
            'publicationTitle': pub_title,
            'isbn': isbn,
            'issn': issn,
            'volume': volume,
            'issue': issue,
            'pages': pages,
            'itemType': item.get('itemType', '')
        }

    def is_duplicate(self, new_item: Dict, existing_items: List[Dict]) -> Tuple[bool, str]:
        """Verbesserte Duplikatserkennung mit normalisiertem Vergleich
        Konvertiert beide Items in das gleiche Format für besseren Vergleich"""
        
        # Beide Items normalisieren
        new_normalized = self.normalize_item_for_comparison(new_item)
        
        for existing in existing_items:
            existing_normalized = self.normalize_item_for_comparison(existing)
            
            # 1. DOI-Match (stärkster Indikator)
            if (new_normalized['doi'] and existing_normalized['doi'] and 
                new_normalized['doi'] == existing_normalized['doi']):
                return True, f"DOI-Match: {new_normalized['doi']}"
            
            # 2. ISBN-Match (für Bücher)
            if (new_normalized['isbn'] and existing_normalized['isbn'] and 
                new_normalized['isbn'] == existing_normalized['isbn']):
                return True, f"ISBN-Match: {new_normalized['isbn']}"
            
            # 3. Exakter Titel + Jahr + mindestens ein Autor
            if (new_normalized['title'] and existing_normalized['title'] and 
                new_normalized['title'] == existing_normalized['title'] and
                new_normalized['year'] and existing_normalized['year'] and
                new_normalized['year'] == existing_normalized['year']):
                # Prüfe Autor-Überschneidung
                if new_normalized['creators'] and existing_normalized['creators']:
                    common_creators = set(new_normalized['creators']) & set(existing_normalized['creators'])
                    if common_creators:
                        return True, f"Titel+Jahr+Autor-Match: {new_normalized['title'][:50]}..."
            
            # 4. Sehr ähnlicher Titel + gleiche Publikation + Jahr
            if (new_normalized['title'] and existing_normalized['title'] and
                new_normalized['publicationTitle'] and existing_normalized['publicationTitle'] and
                new_normalized['publicationTitle'] == existing_normalized['publicationTitle'] and
                new_normalized['year'] and existing_normalized['year'] and
                new_normalized['year'] == existing_normalized['year']):
                title_similarity = self._calculate_similarity(new_normalized['title'], existing_normalized['title'])
                if title_similarity > 0.85:  # 85% Ähnlichkeit
                    return True, f"Ähnlicher Titel in gleicher Publikation+Jahr: {title_similarity:.1%}"
            
            # 5. Zeitschriftenartikel: Titel + Publikation + Volume + Issue + Pages
            if (new_normalized['itemType'] == 'journalArticle' and existing_normalized['itemType'] == 'journalArticle' and
                new_normalized['title'] and existing_normalized['title'] and
                new_normalized['publicationTitle'] and existing_normalized['publicationTitle'] and
                new_normalized['publicationTitle'] == existing_normalized['publicationTitle']):
                # Prüfe verschiedene Kombinationen
                matches = []
                
                # Exakter Titel
                if new_normalized['title'] == existing_normalized['title']:
                    matches.append("title")
                
                # Volume + Issue
                if (new_normalized['volume'] and existing_normalized['volume'] and
                    new_normalized['volume'] == existing_normalized['volume'] and
                    new_normalized['issue'] and existing_normalized['issue'] and
                    new_normalized['issue'] == existing_normalized['issue']):
                    matches.append("vol+issue")
                
                # Pages
                if (new_normalized['pages'] and existing_normalized['pages'] and
                    new_normalized['pages'] == existing_normalized['pages']):
                    matches.append("pages")
                
                # Jahr
                if (new_normalized['year'] and existing_normalized['year'] and
                    new_normalized['year'] == existing_normalized['year']):
                    matches.append("year")
                
                # Wenn mindestens 2 starke Indikatoren übereinstimmen
                if len(matches) >= 2 and "title" in matches:
                    return True, f"Journal-Match ({'+'.join(matches)}): {new_normalized['title'][:50]}..."
            
            # 6. Buchkapitel: Titel + Buchtitel + Jahr
            if (new_normalized['itemType'] == 'bookSection' and existing_normalized['itemType'] == 'bookSection' and
                new_normalized['title'] and existing_normalized['title'] and
                new_normalized['title'] == existing_normalized['title'] and
                new_normalized['publicationTitle'] and existing_normalized['publicationTitle'] and
                new_normalized['publicationTitle'] == existing_normalized['publicationTitle'] and
                new_normalized['year'] and existing_normalized['year'] and
                new_normalized['year'] == existing_normalized['year']):
                return True, f"Buchkapitel-Match: {new_normalized['title'][:50]}..."
        
        return False, ""

    def _calculate_similarity(self, str1: str, str2: str) -> float:
        """Einfache Ähnlichkeitsberechnung basierend auf gemeinsamen Wörtern"""
        if not str1 or not str2:
            return 0.0
        
        words1 = set(str1.lower().split())
        words2 = set(str2.lower().split())
        
        if not words1 or not words2:
            return 0.0
        
        intersection = words1.intersection(words2)
        union = words1.union(words2)
        
        return len(intersection) / len(union) if union else 0.0

    def filter_duplicates(self, items: List[Dict], existing_items: List[Dict]) -> Tuple[List[Dict], List[Dict]]:
        """Filtert Duplikate aus der Item-Liste mit verbesserter Erkennung
        Returns: (unique_items, duplicate_items)"""
        
        logger.info("🔍 Prüfe auf Duplikate mit verbesserter Erkennung...")
        logger.info("🔧 Verwende normalisierte Feldvergleiche für bessere Genauigkeit...")
        
        unique_items = []
        duplicate_items = []
        
        # Statistiken für verschiedene Match-Typen
        match_stats = {
            'DOI-Match': 0,
            'ISBN-Match': 0,
            'Titel+Jahr+Autor-Match': 0,
            'Ähnlicher Titel in gleicher Publikation+Jahr': 0,
            'Journal-Match': 0,
            'Buchkapitel-Match': 0
        }
        
        for i, item in enumerate(items):
            is_dup, reason = self.is_duplicate(item, existing_items)
            
            if is_dup:
                duplicate_items.append({
                    'item': item,
                    'reason': reason
                })
                
                # Statistiken aktualisieren
                for match_type in match_stats:
                    if match_type in reason:
                        match_stats[match_type] += 1
                        break
                
                logger.debug(f"   🔄 Duplikat gefunden: {reason}")
            else:
                unique_items.append(item)
            
            # Progress für große Listen
            if (i + 1) % 100 == 0:
                logger.info(f"   📊 {i + 1}/{len(items)} Items geprüft...")
        
        logger.info(f"✅ Duplikatsprüfung abgeschlossen:")
        logger.info(f"   📝 Neue Items: {len(unique_items)}")
        logger.info(f"   🔄 Duplikate gefunden: {len(duplicate_items)}")
        
        # Detaillierte Match-Statistiken
        if duplicate_items:
            logger.info("📊 Duplikat-Typen:")
            for match_type, count in match_stats.items():
                if count > 0:
                    logger.info(f"   - {match_type}: {count}")
        
        # Duplikate-Details loggen
        if duplicate_items:
            logger.info("🔄 Gefundene Duplikate (erste 10):")
            for i, dup in enumerate(duplicate_items[:10]):
                title = dup['item'].get('title', 'Ohne Titel')[:50]
                logger.info(f"   {i+1}. {title}... ({dup['reason']})")
            if len(duplicate_items) > 10:
                logger.info(f"   ... und {len(duplicate_items) - 10} weitere")
        
        return unique_items, duplicate_items

    def _save_duplicates_report(self, duplicates: List[Dict]):
        """Speichert einen detaillierten Bericht über gefundene Duplikate"""
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"duplicates_report_{timestamp}.txt"
            
            with open(filename, 'w', encoding='utf-8') as f:
                f.write(f"DUPLIKATE-BERICHT (Verbesserte Erkennung) - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write("=" * 80 + "\n\n")
                f.write("VERBESSERUNGEN:\n")
                f.write("- Normalisierte Feldvergleiche (Titel, DOI, ISBN, Autoren)\n")
                f.write("- Bessere Behandlung von Zeitschriftenartikeln (Volume, Issue, Pages)\n")
                f.write("- Spezielle Erkennung für Buchkapitel\n")
                f.write("- Robuste DOI/ISBN-Normalisierung\n")
                f.write("- Jahresextraktion aus verschiedenen Datumsformaten\n\n")
                f.write(f"Anzahl gefundener Duplikate: {len(duplicates)}\n\n")
                
                # Statistiken nach Match-Typ
                match_types = {}
                for dup in duplicates:
                    reason = dup['reason']
                    match_type = reason.split(':')[0] if ':' in reason else reason
                    match_types[match_type] = match_types.get(match_type, 0) + 1
                
                f.write("DUPLIKAT-TYPEN:\n")
                for match_type, count in sorted(match_types.items()):
                    f.write(f"- {match_type}: {count}\n")
                f.write("\n")
                
                f.write("DETAILLIERTE LISTE:\n")
                f.write("-" * 80 + "\n")
                
                for i, dup in enumerate(duplicates, 1):
                    item = dup['item']
                    reason = dup['reason']
                    
                    f.write(f"\n{i}. {item.get('title', 'Ohne Titel')}\n")
                    f.write(f"   🔍 Erkennungsgrund: {reason}\n")
                    f.write(f"   📚 Typ: {item.get('itemType', 'unbekannt')}\n")
                    
                    creators = item.get('creators', [])
                    if creators:
                        author_names = []
                        for c in creators[:3]:
                            if 'lastName' in c:
                                author_names.append(f"{c.get('lastName', '')}, {c.get('firstName', '')}")
                            else:
                                author_names.append(c.get('name', ''))
                        f.write(f"   👥 Autoren: {'; '.join(author_names)}\n")
                    
                    if item.get('date'):
                        f.write(f"   📅 Jahr: {item.get('date')}\n")
                    if item.get('DOI'):
                        f.write(f"   🔗 DOI: {item.get('DOI')}\n")
                    if item.get('ISBN'):
                        f.write(f"   📖 ISBN: {item.get('ISBN')}\n")
                    if item.get('publicationTitle'):
                        f.write(f"   📰 Publikation: {item.get('publicationTitle')}\n")
                    if item.get('volume') or item.get('issue'):
                        vol_issue = f"Vol. {item.get('volume', '')}" if item.get('volume') else ""
                        if item.get('issue'):
                            vol_issue += f", Issue {item.get('issue')}"
                        if vol_issue:
                            f.write(f"   📊 {vol_issue.strip(', ')}\n")
                    if item.get('pages'):
                        f.write(f"   📄 Seiten: {item.get('pages')}\n")
                    
                    f.write("\n")
            
            logger.info(f"📄 Detaillierter Duplikate-Bericht gespeichert: {filename}")
        except Exception as e:
            logger.warning(f"⚠️  Konnte Duplikate-Bericht nicht speichern: {e}")

    def test_duplicate_detection(self, ris_content: str) -> Dict:
        """Testet die Duplikatserkennung ohne Upload
        Zeigt detaillierte Statistiken über potenzielle Duplikate"""
        
        logger.info("🧪 DUPLIKAT-TEST GESTARTET")
        logger.info("=" * 50)
        
        # 1. RIS konvertieren
        logger.info("🔄 Konvertiere RIS-Daten...")
        items = self.convert_ris_with_fallback(ris_content)
        if not items:
            logger.error("❌ RIS-Konvertierung fehlgeschlagen")
            return {'success': False, 'error': 'Konvertierung fehlgeschlagen'}
        
        logger.info(f"✅ {len(items)} Items konvertiert")
        
        # 2. Existierende Items laden
        logger.info("📚 Lade existierende Items...")
        existing_items = self.get_existing_items()
        if not existing_items:
            logger.warning("⚠️  Keine existierenden Items gefunden")
            return {'success': True, 'new_items': len(items), 'duplicates': 0, 'match_rate': 0}
        
        logger.info(f"📖 {len(existing_items)} existierende Items geladen")
        
        # 3. Duplikatsprüfung
        logger.info("🔍 Führe Duplikatsprüfung durch...")
        unique_items, duplicate_items = self.filter_duplicates(items, existing_items)
        
        # 4. Detaillierte Analyse
        total_items = len(items)
        duplicates_found = len(duplicate_items)
        match_rate = (duplicates_found / total_items * 100) if total_items > 0 else 0
        
        logger.info("=" * 50)
        logger.info("🎯 TEST-ERGEBNISSE:")
        logger.info(f"   📊 Gesamt Items: {total_items}")
        logger.info(f"   🔄 Duplikate gefunden: {duplicates_found}")
        logger.info(f"   📝 Neue Items: {len(unique_items)}")
        logger.info(f"   🎯 Match-Rate: {match_rate:.1f}%")
        
        if match_rate == 100:
            logger.info("🎉 PERFEKT! Alle Items als Duplikate erkannt!")
        elif match_rate >= 95:
            logger.info("✅ SEHR GUT! Fast alle Items erkannt!")
        elif match_rate >= 80:
            logger.info("⚠️  GUT: Meiste Items erkannt, aber Verbesserung möglich")
        else:
            logger.info("🚨 PROBLEMATISCH: Viele Items nicht als Duplikate erkannt")
        
        # 5. Beispiele für nicht erkannte Items
        if unique_items:
            logger.info("❓ NICHT ERKANNTE ITEMS (erste 5):")
            for i, item in enumerate(unique_items[:5]):
                title = item.get('title', 'Ohne Titel')[:60]
                item_type = item.get('itemType', 'unknown')
                logger.info(f"   {i+1}. [{item_type}] {title}...")
                
                # Zeige verfügbare Felder für Debugging
                fields = []
                if item.get('DOI'): fields.append(f"DOI: {item['DOI']}")
                if item.get('date'): fields.append(f"Jahr: {item['date']}")
                if item.get('creators'): fields.append(f"Autoren: {len(item['creators'])}")
                if fields:
                    logger.info(f"      {' | '.join(fields)}")
        
        logger.info("=" * 50)
        
        return {
            'success': True,
            'total_items': total_items,
            'duplicates_found': duplicates_found,
            'new_items': len(unique_items),
            'match_rate': match_rate,
            'duplicate_details': duplicate_items[:10]  # Erste 10 für Details
        }

    def test_ris_file_duplicates(self, file_path: str) -> bool:
        """Testet Duplikatserkennung für eine RIS-Datei ohne Upload"""
        if not os.path.exists(file_path):
            logger.error(f"❌ Datei nicht gefunden: {file_path}")
            return False
        
        logger.info(f"🧪 Teste Duplikatserkennung für: {file_path}")
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                ris_content = f.read()
            
            result = self.test_duplicate_detection(ris_content)
            return result.get('success', False)
        except Exception as e:
            logger.error(f"❌ Fehler beim Testen: {e}")
            return False

    def upload_items_batch(self, items: List[Dict], library_version: str, batch_index: int = 0) -> Tuple[bool, str, Optional[str]]:
        """Items-Batch hochladen mit detailliertem Fehlerhandling"""
        
        url = f"https://api.zotero.org/groups/{self.group_id}/items"
        headers = {
            "Zotero-API-Key": self.api_key,
            "Content-Type": "application/json",
            "If-Unmodified-Since-Version": library_version
        }
        
        try:
            response = self.session.post(
                url,
                headers=headers,
                data=json.dumps(items),
                timeout=120  # Längerer Timeout für Upload
            )
            
            if response.status_code == 200:
                result = response.json()
                new_version = response.headers.get('Last-Modified-Version')
                
                # Erfolgreiche und fehlgeschlagene Items analysieren
                successful = result.get('successful', {})
                unchanged = result.get('unchanged', {})
                failed = result.get('failed', {})
                
                success_count = len(successful) + len(unchanged)
                fail_count = len(failed)
                
                # Fehlgeschlagene Items speichern
                if failed:
                    for item_index, error_info in failed.items():
                        try:
                            item_idx = int(item_index)
                            if item_idx < len(items):
                                failed_item = items[item_idx].copy()
                                failed_item['_error'] = error_info
                                failed_item['_batch_index'] = batch_index
                                failed_item['_item_index'] = item_idx
                                self.failed_items.append(failed_item)
                        except (ValueError, IndexError) as e:
                            logger.warning(f"Konnte fehlgeschlagenes Item nicht zuordnen: {e}")
                
                message = f"✓ Batch Upload: {success_count} erfolgreich"
                if fail_count > 0:
                    message += f", {fail_count} fehlgeschlagen"
                    logger.warning(f"Fehlgeschlagene Items: {failed}")
                
                return True, message, new_version
                
            elif response.status_code == 412:
                return False, "Library-Version veraltet (412)", None
                
            elif response.status_code == 413:
                return False, "Request zu groß (413) - verkleinern Sie die Batch-Größe", None
                
            elif response.status_code == 429:
                retry_after = int(response.headers.get('Retry-After', 60))
                return False, f"Rate limit (429) - warten Sie {retry_after}s", None
                
            else:
                error_msg = f"Upload fehlgeschlagen: {response.status_code}"
                try:
                    error_detail = response.json()
                    error_msg += f" - {error_detail}"
                except:
                    error_msg += f" - {response.text[:200]}"
                
                # Bei komplettem Batch-Fehler alle Items als fehlgeschlagen markieren
                for idx, item in enumerate(items):
                    failed_item = item.copy()
                    failed_item['_error'] = error_msg
                    failed_item['_batch_index'] = batch_index
                    failed_item['_item_index'] = idx
                    self.failed_items.append(failed_item)
                
                return False, error_msg, None
                
        except requests.exceptions.Timeout:
            error_msg = "Upload Timeout - versuchen Sie kleinere Batches"
            # Bei Timeout alle Items als fehlgeschlagen markieren
            for idx, item in enumerate(items):
                failed_item = item.copy()
                failed_item['_error'] = error_msg
                failed_item['_batch_index'] = batch_index
                failed_item['_item_index'] = idx
                self.failed_items.append(failed_item)
            return False, error_msg, None
        except Exception as e:
            error_msg = f"Upload Fehler: {str(e)}"
            # Bei Exception alle Items als fehlgeschlagen markieren
            for idx, item in enumerate(items):
                failed_item = item.copy()
                failed_item['_error'] = error_msg
                failed_item['_batch_index'] = batch_index
                failed_item['_item_index'] = idx
                self.failed_items.append(failed_item)
            return False, error_msg, None

    def import_ris_to_group(self, ris_content: str, batch_size: int = 25, check_duplicates: bool = True) -> bool:
        """Hauptfunktion für RIS-Import mit umfassendem Fehlerhandling und Duplikatsprüfung"""
        
        # Erstelle Zeitstempel für Error-Log
        self.error_log_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.failed_items = []  # Liste für fehlgeschlagene Items
        
        logger.info("=" * 60)
        logger.info("🚀 ZOTERO RIS IMPORT GESTARTET")
        logger.info("=" * 60)
        
        # Log-Datei Status prüfen
        log_handlers = [h for h in logger.handlers if isinstance(h, logging.FileHandler)]
        if log_handlers:
            log_file = log_handlers[0].baseFilename
            logger.info(f"📝 Logs werden gespeichert in: {log_file}")
            # Sofort flushen
            for handler in log_handlers:
                handler.flush()
        else:
            logger.warning("⚠️  Keine Log-Datei aktiv - nur Konsolen-Ausgabe")
        
        # 1. RIS-Inhalt validieren
        logger.info("📋 Schritt 1/5: RIS-Datei validieren...")
        is_valid, validation_msg = self.validate_ris_content(ris_content)
        if not is_valid:
            logger.error(f"❌ Validierung fehlgeschlagen: {validation_msg}")
            return False
        logger.info(f"✅ {validation_msg}")
        
        # Zwischenspeichern in Log
        for handler in logger.handlers:
            if isinstance(handler, logging.FileHandler):
                handler.flush()
        
        # 2. RIS zu Zotero-JSON konvertieren
        logger.info("🔄 Schritt 2/5: RIS zu Zotero-Format konvertieren...")
        logger.info("⚡ Bei Server-Überlastung wird automatisch Fallback-Parser verwendet...")
        logger.info("📚 Sammelbände werden automatisch erkannt und korrekt verarbeitet...")
        
        conversion_start = time.time()
        items = self.convert_ris_with_fallback(ris_content)
        conversion_time = time.time() - conversion_start
        
        if not items:
            logger.error("❌ RIS-Konvertierung fehlgeschlagen")
            return False
        
        # Detaillierte Item-Analyse mit Sammelband-Erkennung
        item_types = {}
        has_abstracts = 0
        has_dois = 0
        has_creators = 0
        sammelbände_count = 0
        
        for item in items:
            item_type = item.get('itemType', 'unknown')
            item_types[item_type] = item_types.get(item_type, 0) + 1
            
            if item.get('abstractNote'):
                has_abstracts += 1
            if item.get('DOI'):
                has_dois += 1
            if item.get('creators'):
                has_creators += 1
            if item.get('_was_sammelband', False):
                sammelbände_count += 1
        
        logger.info(f"⏱️  Konvertierung dauerte: {conversion_time:.1f} Sekunden")
        logger.info(f"✅ {len(items)} Items erfolgreich konvertiert")
        logger.info(f"📚 Davon Sammelbände: {sammelbände_count}")
        logger.info(f"📊 Item-Verteilung: {dict(sorted(item_types.items()))}")
        logger.info(f"📈 Qualitäts-Check: {has_abstracts} mit Abstract, {has_dois} mit DOI, {has_creators} mit Autoren")
        
        # Log flushen nach wichtigen Infos
        for handler in logger.handlers:
            if isinstance(handler, logging.FileHandler):
                handler.flush()
        
        # 3. Duplikatsprüfung (optional)
        if check_duplicates:
            logger.info("� Schritt 3/5: Duplikatsprüfung...")
            existing_items = self.get_existing_items()
            if existing_items is not None:
                items, duplicates = self.filter_duplicates(items, existing_items)
                if duplicates:
                    logger.info(f"🔄 {len(duplicates)} Duplikate übersprungen")
                    # Duplikate in separater Datei speichern
                    self._save_duplicates_report(duplicates)
                
                if not items:
                    logger.info("✅ Alle Items waren bereits vorhanden - nichts zu importieren")
                    return True
            else:
                logger.warning("⚠️  Duplikatsprüfung fehlgeschlagen - fahre ohne Prüfung fort")
        else:
            logger.info("⏭️  Schritt 3/5: Duplikatsprüfung übersprungen (deaktiviert)")
        
        # 4. Library-Version abrufen
        logger.info("🔗 Schritt 4/5: Library-Version abrufen...")
        library_version = self.get_library_version()
        if not library_version:
            logger.error("❌ Konnte Library-Version nicht abrufen")
            return False
        logger.info(f"✅ Library-Version: {library_version}")
        
        # 5. Items in Batches hochladen
        total_batches = (len(items) + batch_size - 1) // batch_size
        logger.info("📤 Schritt 5/5: Items zu Zotero hochladen...")
        logger.info(f"📊 Plane Upload: {len(items)} Items in {total_batches} Batches (à {batch_size} Items)")
        logger.info("-" * 50)
        
        uploaded_count = 0
        failed_count = 0
        start_time = time.time()
        
        for i in range(0, len(items), batch_size):
            batch = items[i:i+batch_size]
            batch_num = (i // batch_size) + 1
            
            logger.info(f"📦 Batch {batch_num}/{total_batches}: Uploading {len(batch)} Items...")
            
            # Progress indicator
            progress = f"[{'█' * (batch_num * 20 // total_batches)}{'░' * (20 - batch_num * 20 // total_batches)}] {batch_num}/{total_batches}"
            logger.info(f"📈 Progress: {progress}")
            
            # Batch hochladen mit Retry
            batch_success = False
            for attempt in range(3):
                success, message, new_version = self.upload_items_batch(batch, library_version, batch_num)
                
                if success:
                    uploaded_count += len(batch)
                    logger.info(f"   ✅ {message}")
                    if new_version:
                        library_version = new_version
                    batch_success = True
                    break
                else:
                    if "412" in message:  # Version veraltet
                        logger.warning(f"   ⚠️  Versuch {attempt + 1}: {message}")
                        library_version = self.get_library_version()
                        if not library_version:
                            logger.error("   ❌ Konnte neue Library-Version nicht abrufen")
                            break
                    elif "429" in message:  # Rate limit
                        retry_after = 60
                        logger.warning(f"   ⏳ Versuch {attempt + 1}: {message}")
                        time.sleep(retry_after)
                    else:
                        logger.error(f"   ❌ Versuch {attempt + 1}: {message}")
                        if attempt == 2:  # Letzter Versuch
                            break
                        else:
                            time.sleep(5)
            
            if not batch_success:
                failed_count += len(batch)
                logger.error(f"   ❌ Batch {batch_num} komplett fehlgeschlagen")
            
            # Log nach jedem Batch flushen
            for handler in logger.handlers:
                if isinstance(handler, logging.FileHandler):
                    handler.flush()
            
            # Rate limiting zwischen Batches
            if i + batch_size < len(items):
                time.sleep(0.5)
            
            # Zwischenbericht alle 5 Batches
            if batch_num % 5 == 0 or batch_num == total_batches:
                elapsed = time.time() - start_time
                rate = uploaded_count / elapsed if elapsed > 0 else 0
                logger.info(f"🔄 Zwischenbericht: {uploaded_count} hochgeladen, {failed_count} fehlgeschlagen ({rate:.1f} Items/s)")
        
        # 5. Finale Zusammenfassung
        total_time = time.time() - start_time
        success_rate = (uploaded_count / (uploaded_count + failed_count) * 100) if (uploaded_count + failed_count) > 0 else 0
        
        logger.info("=" * 60)
        logger.info("🎉 IMPORT ABGESCHLOSSEN!")
        logger.info("=" * 60)
        logger.info(f"📊 STATISTIKEN:")
        logger.info(f"   ✅ Erfolgreich hochgeladen: {uploaded_count} Items")
        logger.info(f"   📚 Davon Sammelbände: {sammelbände_count}")
        logger.info(f"   ❌ Fehlgeschlagen: {failed_count} Items")
        if check_duplicates and 'duplicates' in locals():
            logger.info(f"   🔄 Duplikate übersprungen: {len(duplicates)} Items")
        logger.info(f"   📈 Erfolgsrate: {success_rate:.1f}%")
        logger.info(f"   ⏱️  Gesamtzeit: {total_time:.1f} Sekunden")
        logger.info(f"   🚀 Durchschnitt: {(uploaded_count / total_time):.1f} Items/Sekunde")
        
        # 6. Error-Log schreiben wenn es Fehler gab
        if self.failed_items:
            error_log_file = f"zotero_import_{self.error_log_timestamp}_errors.log"
            try:
                with open(error_log_file, 'w', encoding='utf-8') as error_log:
                    error_log.write(f"Fehlerprotokoll des Zotero-Imports\n")
                    error_log.write(f"Zeitstempel: {self.error_log_timestamp}\n")
                    error_log.write(f"Gesamt: {len(items)} Items\n")
                    error_log.write(f"Erfolgreich: {uploaded_count}\n")
                    error_log.write(f"Fehlgeschlagen: {len(self.failed_items)}\n")
                    error_log.write("=" * 80 + "\n\n")
                    
                    for idx, failed_item in enumerate(self.failed_items, 1):
                        error_log.write(f"Fehlgeschlagenes Item #{idx}\n")
                        error_log.write(f"Batch: {failed_item.get('_batch_index', 'unbekannt')}\n")
                        error_log.write(f"Item-Index: {failed_item.get('_item_index', 'unbekannt')}\n")
                        error_log.write(f"Fehler: {failed_item.get('_error', 'Unbekannter Fehler')}\n")
                        error_log.write(f"Titel: {failed_item.get('title', 'Kein Titel')}\n")
                        error_log.write(f"Item-Typ: {failed_item.get('itemType', 'unbekannt')}\n")
                        
                        # Creators anzeigen
                        creators = failed_item.get('creators', [])
                        if creators:
                            error_log.write(f"Autoren/Herausgeber:\n")
                            for creator in creators[:3]:  # Nur erste 3
                                creator_name = creator.get('name') or f"{creator.get('lastName', '')}, {creator.get('firstName', '')}"
                                creator_type = creator.get('creatorType', 'unknown')
                                error_log.write(f"  - {creator_name} ({creator_type})\n")
                        
                        error_log.write("\nVollständiges Item (JSON):\n")
                        # Entferne interne Felder für saubere Ausgabe
                        clean_item = {k: v for k, v in failed_item.items() if not k.startswith('_')}
                        error_log.write(json.dumps(clean_item, indent=2, ensure_ascii=False))
                        error_log.write("\n\n" + "-" * 80 + "\n\n")
                
                logger.info(f"📝 Fehlerprotokoll gespeichert: {error_log_file}")
            except Exception as e:
                logger.error(f"❌ Konnte Fehlerprotokoll nicht schreiben: {e}")
        
        if failed_count == 0:
            logger.info("🎊 PERFEKT! Alle Items erfolgreich importiert!")
        elif success_rate >= 90:
            logger.info("🎯 SEHR GUT! Import größtenteils erfolgreich!")
        elif success_rate >= 70:
            logger.info("⚠️  AKZEPTABEL: Import teilweise erfolgreich!")
        else:
            logger.warning("🚨 PROBLEMATISCH: Viele Fehler beim Import!")
        
        logger.info("=" * 60)
        
        # Finale Log-Speicherung
        for handler in logger.handlers:
            if isinstance(handler, logging.FileHandler):
                handler.flush()
        
        return failed_count == 0

    def import_ris_file(self, file_path: str, batch_size: int = 25, check_duplicates: bool = True) -> bool:
        """RIS-Datei laden und importieren mit Duplikatsprüfung"""
        
        if not os.path.exists(file_path):
            logger.error(f"❌ Datei nicht gefunden: {file_path}")
            return False
        
        # Dateigröße prüfen
        file_size = os.path.getsize(file_path)
        logger.info(f"RIS-Datei: {file_path} ({file_size/1024/1024:.1f} MB)")
        
        if file_size > 50 * 1024 * 1024:  # 50 MB
            logger.warning("⚠️  Sehr große Datei - erwägen Sie eine Aufteilung")
        
        # Verschiedene Encodings versuchen
        encodings = ['utf-8', 'latin-1', 'cp1252', 'iso-8859-1']
        
        for encoding in encodings:
            try:
                with open(file_path, 'r', encoding=encoding) as f:
                    ris_content = f.read()
                logger.info(f"✓ Datei geladen mit Encoding: {encoding}")
                break
            except UnicodeDecodeError:
                logger.warning(f"Encoding {encoding} fehlgeschlagen")
                continue
        else:
            logger.error("❌ Konnte Datei mit keinem Encoding lesen")
            return False
        
        return self.import_ris_to_group(ris_content, batch_size, check_duplicates)


# Verwendungsbeispiel
def main():
    # Konfiguration
    GROUP_ID = "00000000" # Group ID
    API_KEY = "APIKEY"  # Hier API-Key einfügen
    RIS_FILE = "FILENAME"
    BATCH_SIZE = 15  # Noch kleinere Batches bei Server-Problemen
    CHUNK_SIZE = 50  # RIS-Einträge pro Translation-Request
    CHECK_DUPLICATES = True  # Duplikatsprüfung aktivieren
    
    # TEST-MODUS: Setze auf True um nur Duplikatserkennung zu testen
    TEST_MODE = False  # ← Hier auf True setzen für Test ohne Upload
    
    # Importer erstellen
    importer = ZoteroImporter(GROUP_ID, API_KEY)
    importer.chunk_size = CHUNK_SIZE  # RIS-Chunk-Größe anpassen
    importer.use_fallback_parser = True  # Fallback-Parser aktivieren
    
    print("🔧 Fallback-Parser ist aktiviert")
    print("⚡ Intelligenter Fallback: Nach 2 fehlgeschlagenen Chunks wird sofort auf manuellen Parser umgeschaltet")
    print("📊 Erweiterte Logging: Detaillierte Progress-Updates und Statistiken")
    print(f"🔍 Duplikatsprüfung: {'AKTIVIERT' if CHECK_DUPLICATES else 'DEAKTIVIERT'}")
    
    if CHECK_DUPLICATES:
        print("   - Normalisierte Feldvergleiche (Titel, DOI, ISBN, Autoren)")
        print("   - Prüft auf DOI/ISBN-Matches")
        print("   - Prüft auf Titel+Autor+Jahr-Matches")
        print("   - Spezielle Behandlung für Zeitschriftenartikel und Buchkapitel")
        print("   - Erstellt detaillierten Duplikate-Bericht")
    
    if TEST_MODE:
        print("\n🧪 TEST-MODUS AKTIVIERT")
        print("=" * 50)
        print("Führe nur Duplikatserkennung durch (kein Upload)")
        print("Perfekt um zu testen ob identische Daten 100% erkannt werden")
        print("=" * 50)
        
        success = importer.test_ris_file_duplicates(RIS_FILE)
        
        if success:
            print("\n✅ Duplikat-Test abgeschlossen! Siehe Log für Details.")
        else:
            print("\n❌ Duplikat-Test fehlgeschlagen. Siehe Log für Details.")
    else:
        print("\n🚀 IMPORT-MODUS")
        print("Führe vollständigen Import durch")
        
        # Import ausführen
        success = importer.import_ris_file(RIS_FILE, BATCH_SIZE, CHECK_DUPLICATES)
        
        if success:
            print("\n🎉 Import erfolgreich abgeschlossen!")
        else:
            print("\n❌ Import mit Fehlern beendet. Siehe Log für Details.")

# Script ausführen
if __name__ == "__main__":
    main()
