import json
import os
import struct
from typing import Dict, Any, List, Tuple

from shared.constants import POD_METADATA_ID, POD_DATA_ID, POD_OFFSETS_ID, NAME_TABLES_ID, INSTANCE_TYPES_ID
from rebuild.instance_types_collector import collect_instance_types_for_groups


def _collect_pods(source_dir: str) -> List[dict]:
    pods: List[dict] = []
    # Collecter tous les fichiers dans un ordre déterministe
    all_files = []
    for root, _dirs, files in os.walk(source_dir):
        for fn in files:
            all_files.append((root, fn))
    
    # Trier par chemin pour un ordre déterministe
    all_files.sort(key=lambda x: x[0] + '/' + x[1])
    
    for root, fn in all_files:
            if fn.endswith('.pod.json'):
                p = os.path.join(root, fn)
                try:
                    with open(p, 'r', encoding='utf-8') as f:
                        pods.append(json.load(f))
                except Exception:
                    pass
    # Préserver l'ordre original - ne pas trier
    return pods


def _build_pod_metadata(pods: List[dict], name_to_offset: Dict[str, int]) -> bytes:
    blob = bytearray()
    for idx, inst in enumerate(pods):
        tuid = int(inst.get('tuid', 0)) & 0xFFFFFFFFFFFFFFFF
        name = inst.get('name') or f"Pod_{idx+1}"
        name_off = name_to_offset.get(name, 0)
        zone_u16 = int(inst.get('zone', 0)) & 0xFFFF
        entry = bytearray(16)
        struct.pack_into('>Q', entry, 0, tuid)
        struct.pack_into('>I', entry, 8, name_off)
        struct.pack_into('>H', entry, 12, zone_u16)
        struct.pack_into('>H', entry, 14, 0)
        blob.extend(entry)
    return bytes(blob)


def _build_pod_offsets_and_data(pods: List[dict], inst_types_map: Dict[int, int]) -> Tuple[bytes, bytes, List[dict], List[dict]]:
    offsets_blob = bytearray()
    data_blob = bytearray()
    data_patches: List[dict] = []
    offsets_patches: List[dict] = []

    # Construire la zone Offsets (liste d'u32 absolus vers des structures 16B: TUID+Type)
    # et Data (pointer u32 vers offsets + count u32 + padding 8 bytes)
    per_pod_offset_rel: List[int] = []
    ref_records: List[Tuple[int, int]] = []  # (offset_in_offsets_blob, tuid)

    for pod in pods:
        per_pod_offset_rel.append(len(offsets_blob))
        refs = pod.get('instance_references', []) or []
        for ref in refs:
            tuid = int(ref.get('tuid', 0)) & 0xFFFFFFFFFFFFFFFF
            # placeholder 0; patch plus tard vers 0x25022 + inst_types_map[tuid]
            ref_addr_pos = len(offsets_blob)
            offsets_blob.extend(b'\x00\x00\x00\x00')
            ref_records.append((ref_addr_pos, tuid))

    # Construire POD_DATA_ID: pour chaque pod, pointer vers sa liste dans Offsets
    cursor = 0
    for idx, pod in enumerate(pods):
        list_rel = per_pod_offset_rel[idx]
        count = len(pod.get('instance_references', []) or [])
        # Data entry (16 bytes): Offset (u32, absolu, patch), Count (u32), Padding (8 zeros)
        entry = bytearray(16)
        struct.pack_into('>I', entry, 0, 0)  # sera patché absolu vers POD_OFFSETS_ID + list_rel
        struct.pack_into('>I', entry, 4, count & 0xFFFFFFFF)
        # 8 bytes padding zeros par défaut
        data_blob.extend(entry)

        # Patch pour l'u32 d'offset
        if count > 0:
            data_patches.append({
                'at': idx * 16 + 0,
                'target_section_id': POD_OFFSETS_ID,
                'target_relative': list_rel,
                'type': 'absolute_u32',
            })

    # Patches pour chaque adresse d'instance dans Offsets -> 0x25022 (structure 16B)
    for (pos, tuid) in ref_records:
        rel = inst_types_map.get(tuid)
        if rel is not None:
            offsets_patches.append({
                'at': pos,  # relatif à POD_OFFSETS_ID
                'target_section_id': INSTANCE_TYPES_ID,
                'target_relative': rel,
                'type': 'absolute_u32',
            })

    return bytes(offsets_blob), bytes(data_blob), data_patches, offsets_patches


def rebuild_pods_from_folder(source_dir: str, name_to_offset: Dict[str, int], inst_types_map: Dict[int, int] | None = None) -> Dict[int, Dict[str, Any]]:
    pods = _collect_pods(source_dir)
    meta_blob = _build_pod_metadata(pods, name_to_offset)
    # Utiliser le mapping global si fourni, sinon construire localement (minimal)
    if inst_types_map is None:
        _sections, inst_types_map = collect_instance_types_for_groups(source_dir)

    offsets_blob, data_blob, data_patches, offsets_patches = _build_pod_offsets_and_data(pods, inst_types_map)

    sections: Dict[int, Dict[str, Any]] = {}
    sections[POD_OFFSETS_ID] = {
        'flag': 0x00,
        'count': 1,
        'size': len(offsets_blob),
        'data': offsets_blob,
        'patches': offsets_patches,
    }
    sections[POD_DATA_ID] = {
        'flag': 0x10,
        'count': len(pods),
        'size': 16,
        'data': data_blob,
        'patches': data_patches,
    }
    sections[POD_METADATA_ID] = {
        'flag': 0x10,
        'count': len(pods),
        'size': 16,
        'data': meta_blob,
        'patches': [
            {
                'at': i * 16 + 8,
                'target_section_id': NAME_TABLES_ID,
                'target_relative': name_to_offset.get(pods[i].get('name') or f"Pod_{i+1}", 0),
                'type': 'absolute_u32',
            }
            for i in range(len(pods))
        ],
    }

    return sections


