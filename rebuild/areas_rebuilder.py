import json
import os
import struct
from typing import Dict, Any, List, Tuple

from shared.constants import AREA_METADATA_ID, AREA_DATA_ID, AREA_OFFSETS_ID, NAME_TABLES_ID
from rebuild.instance_types_collector import collect_instance_types_for_groups


def _collect_areas(source_dir: str) -> List[dict]:
    areas: List[dict] = []
    # Collecter tous les fichiers dans un ordre déterministe
    all_files = []
    for root, _dirs, files in os.walk(source_dir):
        for fn in files:
            all_files.append((root, fn))
    
    # Trier par chemin pour un ordre déterministe
    all_files.sort(key=lambda x: x[0] + '/' + x[1])
    
    for root, fn in all_files:
            if fn.endswith('.area.json'):
                p = os.path.join(root, fn)
                try:
                    with open(p, 'r', encoding='utf-8') as f:
                        areas.append(json.load(f))
                except Exception:
                    pass
    # Préserver l'ordre original - ne pas trier
    return areas


def _build_area_metadata(areas: List[dict], name_to_offset: Dict[str, int]) -> bytes:
    blob = bytearray()
    for idx, inst in enumerate(areas):
        tuid = int(inst.get('tuid', 0)) & 0xFFFFFFFFFFFFFFFF
        name = inst.get('name') or f"Area_{idx+1}"
        name_off = name_to_offset.get(name, 0)
        zone_u16 = int(inst.get('zone', 0)) & 0xFFFF
        entry = bytearray(16)
        struct.pack_into('>Q', entry, 0, tuid)
        struct.pack_into('>I', entry, 8, name_off)
        struct.pack_into('>H', entry, 12, zone_u16)
        struct.pack_into('>H', entry, 14, 0)
        blob.extend(entry)
    return bytes(blob)


def _build_area_offsets_and_data(areas: List[dict], inst_types_map: Dict[int, int]) -> Tuple[bytes, bytes, List[dict], List[dict]]:
    offsets_blob = bytearray()
    data_blob = bytearray()
    data_patches: List[dict] = []
    offsets_patches: List[dict] = []

    per_area_path_list_rel: List[int] = []
    per_area_volume_list_rel: List[int] = []
    ref_records: List[Tuple[int, int]] = []  # (offset_in_offsets_blob, tuid)

    # Concaténer 2 listes par Area. Si l'Area n'utilise qu'un type, l'autre liste reste vide.
    for area in areas:
        # Paths
        per_area_path_list_rel.append(len(offsets_blob))
        for ref in (area.get('path_references') or []):
            tuid = int(ref.get('tuid', 0)) & 0xFFFFFFFFFFFFFFFF
            pos = len(offsets_blob)
            offsets_blob.extend(b'\x00\x00\x00\x00')
            ref_records.append((pos, tuid))
        # Volumes
        per_area_volume_list_rel.append(len(offsets_blob))
        for ref in (area.get('volume_references') or []):
            tuid = int(ref.get('tuid', 0)) & 0xFFFFFFFFFFFFFFFF
            pos = len(offsets_blob)
            offsets_blob.extend(b'\x00\x00\x00\x00')
            ref_records.append((pos, tuid))

    # Construire les entrées AREA_DATA: PathOffset (u32), VolumeOffset (u32), PathCount (u16), VolumeCount (u16), Padding (u32)
    for idx, area in enumerate(areas):
        path_refs = area.get('path_references') or []
        vol_refs = area.get('volume_references') or []
        entry = bytearray(16)
        struct.pack_into('>I', entry, 0, 0)
        struct.pack_into('>I', entry, 4, 0)
        struct.pack_into('>H', entry, 8, len(path_refs) & 0xFFFF)
        struct.pack_into('>H', entry, 10, len(vol_refs) & 0xFFFF)
        # padding 4 bytes zeros
        data_blob.extend(entry)
        # Patches d'offsets (dans AREA_DATA -> vers AREA_OFFSETS)
        if len(path_refs) > 0:
            data_patches.append({'at': idx * 16 + 0, 'target_section_id': AREA_OFFSETS_ID, 'target_relative': per_area_path_list_rel[idx], 'type': 'absolute_u32'})
        if len(vol_refs) > 0:
            data_patches.append({'at': idx * 16 + 4, 'target_section_id': AREA_OFFSETS_ID, 'target_relative': per_area_volume_list_rel[idx], 'type': 'absolute_u32'})

    # Patches vers 0x25022 pour chaque u32 d'offset
    from shared.constants import INSTANCE_TYPES_ID
    for (pos, tuid) in ref_records:
        rel = inst_types_map.get(tuid)
        if rel is not None:
            offsets_patches.append({'at': pos, 'target_section_id': INSTANCE_TYPES_ID, 'target_relative': rel, 'type': 'absolute_u32'})

    return bytes(offsets_blob), bytes(data_blob), data_patches, offsets_patches


def rebuild_areas_from_folder(source_dir: str, name_to_offset: Dict[str, int], inst_types_map: Dict[int, int] | None = None) -> Dict[int, Dict[str, Any]]:
    areas = _collect_areas(source_dir)
    meta_blob = _build_area_metadata(areas, name_to_offset)
    # Utiliser le mapping fourni, sinon construire minimalement
    if inst_types_map is None:
        _sections, inst_types_map = collect_instance_types_for_groups(source_dir)
    offsets_blob, data_blob, data_patches, offsets_patches = _build_area_offsets_and_data(areas, inst_types_map)

    sections: Dict[int, Dict[str, Any]] = {}
    sections[AREA_OFFSETS_ID] = {'flag': 0x00, 'count': 1, 'size': len(offsets_blob), 'data': offsets_blob, 'patches': offsets_patches}
    sections[AREA_DATA_ID] = {'flag': 0x10, 'count': len(areas), 'size': 16, 'data': data_blob, 'patches': data_patches}
    sections[AREA_METADATA_ID] = {
        'flag': 0x10, 'count': len(areas), 'size': 16, 'data': meta_blob,
        'patches': [
            {'at': i * 16 + 8, 'target_section_id': NAME_TABLES_ID, 'target_relative': name_to_offset.get(areas[i].get('name') or f"Area_{i+1}", 0), 'type': 'absolute_u32'}
            for i in range(len(areas))
        ]
    }
    return sections


