from __future__ import annotations

from typing import Dict, Any, Tuple, List

# Utiliser la collecte exhaustive basée sur les suffixes de fichiers + référencés
from rebuild.instance_types_rebuilder import _collect_instance_types, build_instance_types_from_extraction
from rebuild.instance_types_collector import collect_instance_types_for_groups


def build_instance_types_global(source_dir: str) -> Tuple[Dict[int, Dict[str, Any]], Dict[int, int]]:
    """
    Construit une unique section 0x00025022 (single-block) globale, en incluant
    toutes les instances détectées dans le dossier (par suffixe), afin que toutes
    les références absolues puissent être résolues.

    Retourne: (sections_dict, mapping TUID -> offset relatif dans 0x25022)
    """
    import struct
    from shared.constants import INSTANCE_TYPES_ID

    # 0) Essayer strictement l'ordre d'extraction
    sections_from_meta, mapping_from_meta = build_instance_types_from_extraction(source_dir)
    if sections_from_meta:
        return sections_from_meta, mapping_from_meta

    # 1) Fallback: Tous les TUID d'instances propres (par suffixe)
    base_entries: List[tuple[int, int]] = _collect_instance_types(source_dir)
    # 2) Tous les TUID référencés dans les listes (areas/pods/scents/clues)
    ref_sections, ref_mapping = collect_instance_types_for_groups(source_dir)
    # ref_mapping: tuid -> rel offset; mais nous devons récupérer tuid->type depuis la section
    referenced_entries: List[tuple[int, int]] = []
    if ref_sections:
        from shared.constants import INSTANCE_TYPES_ID
        sec = ref_sections.get(INSTANCE_TYPES_ID)
        if sec and sec.get('data'):
            data = sec['data']
            for i in range(0, len(data), 16):
                tuid = int.from_bytes(data[i:i+8], 'big')
                type_id = int.from_bytes(data[i+8:i+12], 'big')
                referenced_entries.append((tuid, type_id))

    # Fusionner et dédupliquer en conservant le type le plus spécifique (préférence aux types référencés)
    tuid_to_type: Dict[int, int] = {}
    for tuid, type_id in base_entries:
        tuid_to_type[tuid] = type_id & 0xFFFFFFFF
    for tuid, type_id in referenced_entries:
        tuid_to_type[tuid] = type_id & 0xFFFFFFFF

    # Ordonner par TUID croissant (union complète)
    entries: List[tuple[int, int]] = sorted(tuid_to_type.items(), key=lambda kv: kv[0])

    blob = bytearray()
    mapping: Dict[int, int] = {}
    for i, (tuid, type_id) in enumerate(entries):
        mapping[tuid] = i * 16
        blob.extend(struct.pack('>QII', tuid, type_id & 0xFFFFFFFF, 0x00000000))

    sections: Dict[int, Dict[str, Any]] = {}
    if len(blob) > 0:
        sections[INSTANCE_TYPES_ID] = {
            'flag': 0x00,
            'count': 1,
            'size': len(blob),
            'data': bytes(blob),
        }

    return sections, mapping


