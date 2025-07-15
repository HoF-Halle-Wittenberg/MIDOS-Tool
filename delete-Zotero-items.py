"""
Zotero Group Cleanup Script

Dieses Skript ermöglicht das vollständige Löschen aller Items einer Zotero-Gruppe über die Zotero Web API.

Funktionen:
- Abrufen aller Item-Keys einer Zotero-Gruppe (get_all_item_keys)
- Ermitteln der aktuellen Library-Version zur Synchronisierung (get_library_version)
- Batchweises Löschen aller Items unter Berücksichtigung von Versionskontrolle (delete_all_items)

Voraussetzungen:
- Gültiger API-Key mit Schreibrechten für die Gruppe
- Group-ID der Zielgruppe

Hinweis:
- Löscht unwiderruflich alle Items der Gruppe
- Beachtet API-Rate-Limits durch kurze Pausen zwischen den Requests

Verwendung:
- API-Key und group_id oben eintragen
- Skript ausführen, um alle Items zu löschen
"""

import requests
import time

group_id = "000000000" # Zotero Group
api_key = "APIKEY"  # Ihren API-Key einsetzen

def get_all_item_keys():
    """Alle Item-Keys der Gruppe abrufen"""
    url = f"https://api.zotero.org/groups/{group_id}/items"
    headers = {"Zotero-API-Key": api_key}

    all_keys = []
    start = 0
    limit = 100

    while True:
        params = {"format": "keys", "start": start, "limit": limit}
        response = requests.get(url, headers=headers, params=params)

        if response.status_code == 200:
            keys = response.text.strip().split('\n')
            if not keys or keys == ['']:
                break
            all_keys.extend(keys)
            start += limit
            print(f"Abgerufen: {len(keys)} Keys (Total: {len(all_keys)})")
        else:
            print(f"Fehler: {response.status_code}")
            break

        time.sleep(0.1)  # Rate limiting vermeiden

    return all_keys

def get_library_version():
    """Aktuelle Library-Version abrufen"""
    url = f"https://api.zotero.org/groups/{group_id}/items"
    headers = {"Zotero-API-Key": api_key}
    response = requests.get(url, headers=headers, params={"limit": 1})
    return response.headers.get('Last-Modified-Version')

def delete_all_items():
    """Alle Items der Gruppe löschen"""
    print("Lade alle Item-Keys...")
    all_keys = get_all_item_keys()

    if not all_keys:
        print("Keine Items gefunden.")
        return

    print(f"Gefunden: {len(all_keys)} Items")
    print("Beginne mit dem Löschen...")

    library_version = get_library_version()
    batch_size = 50
    deleted_count = 0

    for i in range(0, len(all_keys), batch_size):
        batch = all_keys[i:i+batch_size]

        print(f"Lösche Batch {i//batch_size + 1}: {len(batch)} Items...")

        url = f"https://api.zotero.org/groups/{group_id}/items"
        headers = {
            "Zotero-API-Key": api_key,
            "If-Unmodified-Since-Version": library_version
        }
        params = {"itemKey": ",".join(batch)}

        response = requests.delete(url, headers=headers, params=params)

        if response.status_code == 204:
            deleted_count += len(batch)
            print(f"✓ Erfolgreich. Total gelöscht: {deleted_count}")

            # Neue Version für nächsten Batch
            new_version = response.headers.get('Last-Modified-Version')
            if new_version:
                library_version = new_version

        elif response.status_code == 412:
            print("Version veraltet, hole neue...")
            library_version = get_library_version()
            # Nochmal versuchen...

        else:
            print(f"Fehler: {response.status_code} - {response.text}")
            break

        time.sleep(0.1)  # Rate limiting

    print(f"Fertig! {deleted_count} von {len(all_keys)} Items gelöscht.")

# Ausführen
delete_all_items()
