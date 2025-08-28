import json
import os
import struct
from typing import Dict, Any, List, Tuple

from shared.constants import INSTANCE_TYPES_ID


TYPE_BY_SUFFIX = {
    '.moby.json': 0,
    '.path.json': 1,
    '.volume.json': 2,
    '.clue.json': 3,
    '.controller.json': 4,
    '.scent.json': 5,
    '.area.json': 6,
    '.pod.json': 7,
}


def _collect_instance_types(source_dir: str) -> List[Tuple[int, int]]:
    entries: List[Tuple[int, int]] = []
    seen: set[int] = set()
    
    # Essayer d'abord de lire l'ordre exact depuis extraction_metadata.json
    metadata_path = os.path.join(source_dir, "extraction_metadata.json")
    if os.path.exists(metadata_path):
        try:
            with open(metadata_path, 'r', encoding='utf-8') as f:
                metadata = json.load(f)
            if 'instance_types_entries' in metadata:
                # Utiliser l'ordre exact de l'extraction
                for entry in metadata['instance_types_entries']:
                    tuid = int(entry['tuid']) & 0xFFFFFFFFFFFFFFFF
                    type_id = int(entry['type']) & 0xFFFFFFFF
                    if tuid not in seen:
                        seen.add(tuid)
                        entries.append((tuid, type_id))
                print(f"  ✅ Utilisation de l'ordre exact de l'extraction: {len(entries)} entrées")
                return entries
        except Exception as e:
            print(f"  ⚠️ Erreur lecture extraction_metadata.json: {e}")
    
    # Fallback: collecter dans l'ordre de parcours des fichiers
    for root, _dirs, files in os.walk(source_dir):
        for fn in files:
            for suffix, type_id in TYPE_BY_SUFFIX.items():
                if fn.endswith(suffix):
                    p = os.path.join(root, fn)
                    try:
                        with open(p, 'r', encoding='utf-8') as f:
                            obj = json.load(f)
                        tuid = int(obj.get('tuid', 0xFFFFFFFFFFFFFFFF)) & 0xFFFFFFFFFFFFFFFF
                        if tuid != 0xFFFFFFFFFFFFFFFF and tuid not in seen:
                            seen.add(tuid)
                            entries.append((tuid, type_id))
                    except Exception:
                        pass
                    break
    
    print(f"  ⚠️ Utilisation de l'ordre de parcours des fichiers: {len(entries)} entrées")
    return entries


def build_instance_types_from_extraction(source_dir: str) -> Tuple[Dict[int, Dict[str, Any]], Dict[int, int]]:
    """
    Construit la section 0x00025022 en respectant STRICTEMENT l'ordre original
    extrait depuis `extraction_metadata.json` (clé `instance_types_entries`).

    Fallbacks:
      - si le metadata n'existe pas ou ne contient pas la clé, on utilise
        `_collect_instance_types` (ordre déterministe de parcours de fichiers).

    Retourne: (sections_dict, mapping TUID -> offset relatif dans 0x25022)
    """
    import json as _json
    import os as _os
    import struct as _struct

    entries: List[Tuple[int, int]] = []
    metadata_path = _os.path.join(source_dir, "extraction_metadata.json")
    if _os.path.exists(metadata_path):
        try:
            with open(metadata_path, 'r', encoding='utf-8') as f:
                metadata = _json.load(f)
            if 'instance_types_entries' in metadata:
                for entry in metadata['instance_types_entries']:
                    tuid = int(entry['tuid']) & 0xFFFFFFFFFFFFFFFF
                    type_id = int(entry['type']) & 0xFFFFFFFF
                    entries.append((tuid, type_id))
        except Exception:
            entries = []

    if not entries:
        # Fallback déterministe
        entries = _collect_instance_types(source_dir)

    blob = bytearray()
    mapping: Dict[int, int] = {}
    for i, (tuid, type_id) in enumerate(entries):
        mapping[tuid] = i * 16
        blob.extend(_struct.pack('>QII', tuid, type_id & 0xFFFFFFFF, 0x00000000))

    sections: Dict[int, Dict[str, Any]] = {}
    if len(blob) > 0:
        sections[INSTANCE_TYPES_ID] = {
            'flag': 0x00,
            'count': 1,
            'size': len(blob),
            'data': bytes(blob),
        }

    return sections, mapping


def rebuild_instance_types_for_clues(source_dir: str, clue_volume_tuids: List[int]) -> Tuple[Dict[int, Dict[str, Any]], Dict[int, int]]:
    """Construit la section 0x00025022 limitée aux volumes référencés par les Clues.
    Renvoie (sections, mapping TUID->offset)."""
    # Construire une liste unique de TUID volumes utilisés par les clues
    wanted: List[int] = sorted({int(x) & 0xFFFFFFFFFFFFFFFF for x in clue_volume_tuids if x is not None})
    # Générer directement les entrées (tuid, type_id=2) pour les volumes référencés
    entries = [(tuid, 2) for tuid in wanted]
    blob = bytearray()
    mapping: Dict[int, int] = {}
    for i, (tuid, type_id) in enumerate(entries):
        mapping[tuid] = i * 16
        # Derniers 4 octets = 0x00000000 (padding)
        blob.extend(struct.pack('>QII', tuid, type_id & 0xFFFFFFFF, 0x00000000))

    sections: Dict[int, Dict[str, Any]] = {
        INSTANCE_TYPES_ID: {
            'flag': 0x10,
            'count': len(entries),
            'size': 16,
            'data': bytes(blob),
        }
    }
    return sections, mapping


