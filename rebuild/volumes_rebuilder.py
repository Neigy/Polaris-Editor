import json
import os
import struct
from typing import Dict, Any, List, Tuple

from shared.constants import VOLUME_TRANSFORM_ID, VOLUME_METADATA_ID, NAME_TABLES_ID


def _collect_volumes(source_dir: str) -> List[dict]:
    volumes: List[dict] = []
    # Collecter tous les fichiers dans un ordre déterministe
    all_files = []
    for root, _dirs, files in os.walk(source_dir):
        for fn in files:
            all_files.append((root, fn))
    
    # Trier par chemin pour un ordre déterministe
    all_files.sort(key=lambda x: x[0] + '/' + x[1])
    
    for root, fn in all_files:
            if fn.endswith('.volume.json'):
                p = os.path.join(root, fn)
                try:
                    with open(p, 'r', encoding='utf-8') as f:
                        volumes.append(json.load(f))
                except Exception:
                    pass
    # Préserver l'ordre original - ne pas trier
    return volumes


def _build_volume_metadata(volumes: List[dict], name_to_offset: Dict[str, int]) -> bytes:
    blob = bytearray()
    for idx, inst in enumerate(volumes):
        tuid = int(inst.get('tuid', 0xFFFFFFFFFFFFFFFF)) & 0xFFFFFFFFFFFFFFFF
        name = inst.get('name') or f"Volume_{idx+1}"
        name_off = name_to_offset.get(name, 0)
        zone_u16 = int(inst.get('zone', 0)) & 0xFFFF
        entry = bytearray(16)
        struct.pack_into('>Q', entry, 0, tuid)
        struct.pack_into('>I', entry, 8, name_off)
        struct.pack_into('>H', entry, 12, zone_u16)
        struct.pack_into('>H', entry, 14, 0)
        blob.extend(entry)
    return bytes(blob)


def _build_volume_transforms(volumes: List[dict]) -> bytes:
    blob = bytearray()
    for inst in volumes:
        matrix = inst.get('transform_matrix') or [[1.0, 0.0, 0.0, 0.0],
                                                  [0.0, 1.0, 0.0, 0.0],
                                                  [0.0, 0.0, 1.0, 0.0],
                                                  [0.0, 0.0, 0.0, 1.0]]
        # 16 floats en big-endian, rangées par lignes
        for row in range(4):
            for col in range(4):
                struct.pack_into('>f', (buf := bytearray(4)), 0, float(matrix[row][col]))
                blob.extend(buf)
    return bytes(blob)


def rebuild_volumes_from_folder(source_dir: str, name_to_offset: Dict[str, int]) -> Dict[int, Dict[str, Any]]:
    volumes = _collect_volumes(source_dir)

    meta_blob = _build_volume_metadata(volumes, name_to_offset)
    xform_blob = _build_volume_transforms(volumes)

    sections: Dict[int, Dict[str, Any]] = {
        VOLUME_METADATA_ID: {
            'flag': 0x10,
            'count': len(volumes),
            'size': 16,
            'data': meta_blob,
            'patches': [
                {
                    'at': i * 16 + 8,
                    'target_section_id': NAME_TABLES_ID,
                    'target_relative': name_to_offset.get(volumes[i].get('name') or f"Volume_{i+1}", 0),
                    'type': 'absolute_u32',
                }
                for i in range(len(volumes))
            ],
        },
        VOLUME_TRANSFORM_ID: {
            'flag': 0x10,
            'count': len(volumes),
            'size': 64,  # 16 floats
            'data': xform_blob,
        },
    }

    return sections


def compute_volume_meta_mapping(source_dir: str) -> Dict[int, int]:
    """Calcule un mapping TUID (u64) -> offset d'entrée dans VOLUME_METADATA_ID.
    L'ordre doit être strictement le même que celui utilisé par rebuild_volumes_from_folder.
    """
    volumes = _collect_volumes(source_dir)
    entry_size = 16
    mapping: Dict[int, int] = {}
    for i, inst in enumerate(volumes):
        tuid = int(inst.get('tuid', 0)) & 0xFFFFFFFFFFFFFFFF
        mapping[tuid] = i * entry_size
    return mapping


