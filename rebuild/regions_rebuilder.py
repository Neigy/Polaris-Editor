import os
import json
import struct
from typing import Dict, Any, List, Tuple

from shared.constants import DEFAULT_REGION_NAMES_ID, ZONE_COUNTS_ID


def _collect_region_name(source_dir: str) -> str:
    # Prendre le dossier de région juste sous la racine (ex: gp_prius/default/<RegionName>)
    # Si plusieurs, prendre le premier par ordre lexical
    try:
        root_entries = sorted([d for d in os.listdir(source_dir) if os.path.isdir(os.path.join(source_dir, d))])
        # Chercher un niveau sous 'default' si présent
        if 'default' in root_entries:
            sub = os.path.join(source_dir, 'default')
            regions = sorted([d for d in os.listdir(sub) if os.path.isdir(os.path.join(sub, d))])
            if regions:
                return regions[0]
        # Sinon, prendre le premier dossier
        if root_entries:
            return root_entries[0]
    except Exception:
        pass
    return 'default'


def rebuild_default_region_from_folder(source_dir: str) -> Dict[int, Dict[str, Any]]:
    region_name = _collect_region_name(source_dir)
    name_bytes = region_name.encode('utf-8')[:64]
    name_bytes = name_bytes + b'\x00' * (64 - len(name_bytes))

    blob = bytearray()
    blob.extend(name_bytes)
    blob.extend(struct.pack('>I', 0))  # indices_offset (patch vers ZONE_COUNTS_ID)
    # indices_count = nombre d'indices dans 0x25014; on mettra la vraie valeur depuis zones_rebuilder
    # Ici on met 0, zones_rebuilder écrira la vraie section 0x25010; on garde ce module pour fallback si désiré
    blob.extend(struct.pack('>I', 0))

    sections: Dict[int, Dict[str, Any]] = {
        DEFAULT_REGION_NAMES_ID: {
            'flag': 0x00,
            'count': 1,
            'size': len(blob),
            'data': bytes(blob),
        }
    }
    return sections


