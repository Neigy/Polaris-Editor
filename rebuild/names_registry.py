import json
import os
from typing import Dict, List, Tuple

from shared.constants import NAME_TABLES_ID


def _encode_utf8z(s: str) -> bytes:
    return s.encode('utf-8') + b'\x00'


def collect_names_from_folder(source_dir: str) -> List[str]:
    """Collecte les noms depuis tous les JSON d'instances, en conservant les doublons.
    L'ordre est celui de la découverte (stable)."""
    names: List[str] = []
    for root, _dirs, files in os.walk(source_dir):
        for fn in files:
            if fn.endswith(('.moby.json', '.controller.json', '.path.json', '.volume.json', '.clue.json', '.area.json', '.pod.json', '.scent.json')):
                path = os.path.join(root, fn)
                try:
                    with open(path, 'r', encoding='utf-8') as f:
                        obj = json.load(f)
                        n = obj.get('name')
                        if n:
                            names.append(n)
                except Exception:
                    pass
    return names


def build_name_tables_section(source_dir: str) -> Tuple[Dict[int, dict], Dict[str, int]]:
    """Construit la section NAME_TABLES_ID et renvoie (sections, name_to_offset)."""
    names = collect_names_from_folder(source_dir)

    blob = bytearray()
    name_to_offset: Dict[str, int] = {}
    current = 0
    for n in names:
        if n not in name_to_offset:
            name_to_offset[n] = current
        enc = _encode_utf8z(n)
        blob.extend(enc)
        current += len(enc)

    sections = {
        NAME_TABLES_ID: {
            'flag': 0x00,
            'count': 1,
            'size': len(blob),
            'data': bytes(blob),
        }
    }
    return sections, name_to_offset



