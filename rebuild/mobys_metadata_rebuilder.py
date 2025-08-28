import struct
from typing import Dict, Any, List

from shared.constants import MOBY_METADATA_ID, NAME_TABLES_ID


def rebuild_mobys_metadata(instances: List[Dict[str, Any]], name_to_offset: Dict[str, int]) -> Dict[int, Dict[str, Any]]:
    """Construit la section MOBY_METADATA_ID en utilisant le mapping global name_to_offset.

    - MOBY_METADATA_ID (0x0002504C): 16 octets/entrée
      TUID (u64), NameOffset (u32), ZoneIndex (u16), Padding (u16)
    - Patches 'absolute_u32' vers NAME_TABLES_ID pour chaque NameOffset
    """
    # Construire la table de métadonnées Moby
    # Format: TUID (u64), NameOffset (u32), ZoneIndex (u16), Padding (u16)
    moby_meta = bytearray()
    for idx, inst in enumerate(instances):
        tuid = int(inst.get('tuid', 0xFFFFFFFFFFFFFFFF)) & 0xFFFFFFFFFFFFFFFF
        name = inst.get('name') or f"Moby_{idx+1}"
        name_offset = name_to_offset.get(name, 0)
        zone_index = int(inst.get('zone', 0)) & 0xFFFF
        entry = bytearray(16)
        struct.pack_into('>Q', entry, 0, tuid)
        struct.pack_into('>I', entry, 8, name_offset)
        struct.pack_into('>H', entry, 12, zone_index)
        struct.pack_into('>H', entry, 14, 0)
        moby_meta.extend(entry)

    # Emballer en définition de section pour l'assembler
    sections: Dict[int, Dict[str, Any]] = {
        MOBY_METADATA_ID: {
            'flag': 0x10,              # multi-items
            'count': len(instances),
            'size': 16,                # 16 bytes par entrée
            'data': bytes(moby_meta),
            # Déclarer les positions de pointeurs absolus (NameOffset) pour la table des pointeurs
            'patches': [
                {
                    'at': i * 16 + 8,                 # offset du champ NameOffset dans l'entrée i
                    'target_section_id': NAME_TABLES_ID,  # pointer logical target (base)
                    'target_relative': name_to_offset.get(instances[i].get('name') or f"Moby_{i+1}", 0),
                    'type': 'absolute_u32',
                }
                for i in range(len(instances))
            ],
        },
    }

    return sections


