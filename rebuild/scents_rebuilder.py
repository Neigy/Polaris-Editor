import json
import os
import struct
from typing import Dict, Any, List, Tuple

from shared.constants import SCENT_METADATA_ID, SCENT_DATA_ID, SCENT_OFFSETS_ID, NAME_TABLES_ID
from rebuild.instance_types_collector import collect_instance_types_for_groups


def _collect_scents(source_dir: str) -> List[dict]:
    scents: List[dict] = []
    # Collecter tous les fichiers dans un ordre déterministe
    all_files = []
    for root, _dirs, files in os.walk(source_dir):
        for fn in files:
            all_files.append((root, fn))
    
    # Trier par chemin pour un ordre déterministe
    all_files.sort(key=lambda x: x[0] + '/' + x[1])
    
    for root, fn in all_files:
            if fn.endswith('.scent.json'):
                p = os.path.join(root, fn)
                try:
                    with open(p, 'r', encoding='utf-8') as f:
                        scents.append(json.load(f))
                except Exception:
                    pass
    # Tri nécessaire: par zone ascendante puis par TUID pour correspondre aux pointeurs de zones
    try:
        scents.sort(key=lambda inst: (int(inst.get('zone', 0)), int(inst.get('tuid', 0))))
    except Exception:
        pass
    return scents


def _build_scent_metadata(scents: List[dict], name_to_offset: Dict[str, int]) -> bytes:
    blob = bytearray()
    for idx, inst in enumerate(scents):
        tuid = int(inst.get('tuid', 0)) & 0xFFFFFFFFFFFFFFFF
        name = inst.get('name') or f"Scent_{idx+1}"
        name_off = name_to_offset.get(name, 0)
        zone_u16 = int(inst.get('zone', 0)) & 0xFFFF
        entry = bytearray(16)
        struct.pack_into('>Q', entry, 0, tuid)
        struct.pack_into('>I', entry, 8, name_off)
        struct.pack_into('>H', entry, 12, zone_u16)
        struct.pack_into('>H', entry, 14, 0)
        blob.extend(entry)
    return bytes(blob)


def _build_scent_offsets_and_data(scents: List[dict], inst_types_map: Dict[int, int]) -> Tuple[bytes, bytes, List[dict], List[dict]]:
    offsets_blob = bytearray()
    data_blob = bytearray()
    data_patches: List[dict] = []
    offsets_patches: List[dict] = []

    # Offsets: liste d'adresses u32 absolues vers 0x25022 (Instance Types),
    # comme pour les PODS. Chaque référence écrit un u32 patché vers 0x25022 + rel.
    per_scent_list_rel: List[int] = []
    ref_records: List[Tuple[int, int]] = []  # (offset_in_offsets_blob, tuid)

    for scent in scents:
        per_scent_list_rel.append(len(offsets_blob))
        refs = scent.get('instance_references', []) or []
        for ref in refs:
            tuid = int(ref.get('tuid', 0)) & 0xFFFFFFFFFFFFFFFF
            pos = len(offsets_blob)
            offsets_blob.extend(b'\x00\x00\x00\x00')
            ref_records.append((pos, tuid))

    # Patches des adresses de références vers 0x25022
    from shared.constants import INSTANCE_TYPES_ID
    for (pos, tuid) in ref_records:
        rel = inst_types_map.get(tuid)
        if rel is not None:
            offsets_patches.append({
                'at': pos,  # relatif à SCENT_OFFSETS_ID
                'target_section_id': INSTANCE_TYPES_ID,
                'target_relative': rel,
                'type': 'absolute_u32',
            })
        else:
            # Avertir si une référence n'est pas résolue dans 0x25022
            try:
                print(f"[WARN] SCENT ref TUID 0x{tuid:016X} absent de 0x25022 – offset restera 0")
            except Exception:
                pass

    # Data: Offset (u32), Count (u32), Padding (8 bytes)
    for idx, scent in enumerate(scents):
        entry = bytearray(16)
        struct.pack_into('>I', entry, 0, 0)
        cnt = len(scent.get('instance_references', []) or [])
        struct.pack_into('>I', entry, 4, cnt)
        data_blob.extend(entry)
        if cnt > 0:
            data_patches.append({'at': idx * 16 + 0, 'target_section_id': SCENT_OFFSETS_ID, 'target_relative': per_scent_list_rel[idx], 'type': 'absolute_u32'})

    return bytes(offsets_blob), bytes(data_blob), data_patches, offsets_patches


def rebuild_scents_from_folder(source_dir: str, name_to_offset: Dict[str, int], inst_types_map: Dict[int, int] | None = None) -> Dict[int, Dict[str, Any]]:
    scents = _collect_scents(source_dir)
    meta_blob = _build_scent_metadata(scents, name_to_offset)
    if inst_types_map is None:
        from rebuild.instance_types_global import build_instance_types_global
        _sections, inst_types_map = build_instance_types_global(source_dir)
    offsets_blob, data_blob, data_patches, offsets_patches = _build_scent_offsets_and_data(scents, inst_types_map)

    sections: Dict[int, Dict[str, Any]] = {}
    sections[SCENT_OFFSETS_ID] = {'flag': 0x00, 'count': 1, 'size': len(offsets_blob), 'data': offsets_blob, 'patches': offsets_patches}
    sections[SCENT_DATA_ID] = {'flag': 0x10, 'count': len(scents), 'size': 16, 'data': data_blob, 'patches': data_patches}
    sections[SCENT_METADATA_ID] = {
        'flag': 0x10, 'count': len(scents), 'size': 16, 'data': meta_blob,
        'patches': [
            {'at': i * 16 + 8, 'target_section_id': NAME_TABLES_ID, 'target_relative': name_to_offset.get(scents[i].get('name') or f"Scent_{i+1}", 0), 'type': 'absolute_u32'}
            for i in range(len(scents))
        ]
    }
    return sections


