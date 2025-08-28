import json
import os
import struct
from typing import Dict, Any, List, Tuple

from shared.constants import INSTANCE_TYPES_ID


def _safe_int(v):
    if isinstance(v, int):
        return v
    if isinstance(v, str):
        v = v.strip()
        try:
            return int(v, 0)
        except Exception:
            try:
                return int(v, 16)
            except Exception:
                return None
    return None


def collect_instance_types_for_groups(source_dir: str) -> Tuple[Dict[int, Dict[str, Any]], Dict[int, int]]:
    tuid_to_type: Dict[int, int] = {}
    # Conserver l'ordre runtime avec doublons
    entries_raw: List[Tuple[int, int]] = []

    # Collecter tous les fichiers dans un ordre déterministe
    all_files = []
    for root, _dirs, files in os.walk(source_dir):
        for fn in files:
            all_files.append((root, fn))
    
    # Trier par chemin pour un ordre déterministe
    all_files.sort(key=lambda x: x[0] + '/' + x[1])
    
    for root, fn in all_files:
            path = os.path.join(root, fn)
            try:
                if fn.endswith('.clue.json'):
                    with open(path, 'r', encoding='utf-8') as f:
                        obj = json.load(f)
                    # Runtime-only: ne pas ajouter systématiquement le TUID de la Clue
                    # Ajouter seulement le Volume référencé par la Clue (utilisé par CLUE_INFO)
                    vol_tuid = _safe_int(obj.get('volume_tuid'))
                    if vol_tuid is not None:
                        entries_raw.append((vol_tuid & 0xFFFFFFFFFFFFFFFF, 2))
                        tuid_to_type[vol_tuid & 0xFFFFFFFFFFFFFFFF] = 2
                elif fn.endswith('.pod.json'):
                    with open(path, 'r', encoding='utf-8') as f:
                        obj = json.load(f)
                    for ref in obj.get('instance_references', []) or []:
                        t = _safe_int(ref.get('type'))
                        tuid = _safe_int(ref.get('tuid'))
                        if tuid is not None and t is not None:
                            entries_raw.append((tuid & 0xFFFFFFFFFFFFFFFF, t & 0xFFFFFFFF))
                            tuid_to_type[tuid & 0xFFFFFFFFFFFFFFFF] = t & 0xFFFFFFFF
                elif fn.endswith('.area.json'):
                    with open(path, 'r', encoding='utf-8') as f:
                        obj = json.load(f)
                    for ref in obj.get('path_references', []) or []:
                        tuid = _safe_int(ref.get('tuid'))
                        if tuid is not None:
                            entries_raw.append((tuid & 0xFFFFFFFFFFFFFFFF, 1))
                            tuid_to_type[tuid & 0xFFFFFFFFFFFFFFFF] = 1
                    for ref in obj.get('volume_references', []) or []:
                        tuid = _safe_int(ref.get('tuid'))
                        if tuid is not None:
                            entries_raw.append((tuid & 0xFFFFFFFFFFFFFFFF, 2))
                            tuid_to_type[tuid & 0xFFFFFFFFFFFFFFFF] = 2
                elif fn.endswith('.scent.json'):
                    with open(path, 'r', encoding='utf-8') as f:
                        obj = json.load(f)
                    for ref in obj.get('instance_references', []) or []:
                        tuid = _safe_int(ref.get('tuid'))
                        if tuid is not None:
                            entries_raw.append((tuid & 0xFFFFFFFFFFFFFFFF, 3))
                            tuid_to_type[tuid & 0xFFFFFFFFFFFFFFFF] = 3
            except Exception:
                continue

    sections: Dict[int, Dict[str, Any]] = {}
    mapping: Dict[int, int] = {}

    if entries_raw:
        blob = bytearray()
        for i, (tuid, type_id) in enumerate(entries_raw):
            if tuid not in mapping:
                mapping[tuid] = i * 16
            blob.extend(struct.pack('>QII', tuid, type_id & 0xFFFFFFFF, 0))
        sections[INSTANCE_TYPES_ID] = {
            'flag': 0x00,
            'count': 1,
            'size': len(blob),
            'data': bytes(blob),
        }
    else:
        # Fallback (unique trié) si aucune entrée runtime collectée
        entries = sorted(tuid_to_type.items(), key=lambda kv: kv[0])
        blob = bytearray()
        for i, (tuid, type_id) in enumerate(entries):
            mapping[tuid] = i * 16
            blob.extend(struct.pack('>QII', tuid, type_id & 0xFFFFFFFF, 0))
        if len(blob) > 0:
            sections[INSTANCE_TYPES_ID] = {
                'flag': 0x00,
                'count': 1,
                'size': len(blob),
                'data': bytes(blob),
            }

    return sections, mapping


