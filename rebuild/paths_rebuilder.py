import json
import os
import struct
from typing import Dict, Any, List

from shared.constants import PATH_DATA_ID, PATH_METADATA_ID, PATH_POINTS_ID


def _collect_paths(source_dir: str) -> List[dict]:
    results: List[dict] = []
    for root, _dirs, files in os.walk(source_dir):
        for fn in files:
            if fn.endswith('.path.json'):
                p = os.path.join(root, fn)
                try:
                    with open(p, 'r', encoding='utf-8') as f:
                        results.append(json.load(f))
                except Exception:
                    pass
    # Préserver l'ordre original - ne pas trier
    return results


def _build_path_metadata(paths: List[dict], name_to_offset: Dict[str, int]) -> bytes:
    # 16 bytes: TUID (u64), NameOffset (u32), ZoneIndex (u16), Padding (u16)
    blob = bytearray()
    for idx, inst in enumerate(paths):
        tuid = int(inst.get('tuid', 0xFFFFFFFFFFFFFFFF)) & 0xFFFFFFFFFFFFFFFF
        name = inst.get('name') or f"Path_{idx+1}"
        name_off = name_to_offset.get(name, 0)
        zone_u16 = int(inst.get('zone', 0)) & 0xFFFF
        entry = bytearray(16)
        struct.pack_into('>Q', entry, 0, tuid)
        struct.pack_into('>I', entry, 8, name_off)
        struct.pack_into('>H', entry, 12, zone_u16)
        struct.pack_into('>H', entry, 14, 0)
        blob.extend(entry)
    return bytes(blob)


def _build_path_points(paths: List[dict]) -> tuple[bytes, List[int]]:
    # Concaténer tous les points; retourner aussi les offsets de début pour chaque path
    points_blob = bytearray()
    offsets: List[int] = []
    for inst in paths:
        offsets.append(len(points_blob))
        for pt in inst.get('points', []) or []:
            x = float(pt.get('position', {}).get('x', 0.0))
            y = float(pt.get('position', {}).get('y', 0.0))
            z = float(pt.get('position', {}).get('z', 0.0))
            t = float(pt.get('timestamp', 0.0))
            points_blob.extend(struct.pack('>ffff', x, y, z, t))
    return bytes(points_blob), offsets


def _build_path_data(paths: List[dict], points_section_id: int, per_path_points_offset: List[int]) -> tuple[bytes, List[dict]]:
    # 16 bytes/entry: PointOffset (u32), Unknown (u32), TotalDuration (f32), Flags (u16), PointCount (u16)
    blob = bytearray()
    patches: List[dict] = []
    for idx, inst in enumerate(paths):
        point_count = int(inst.get('point_count', len(inst.get('points') or []))) & 0xFFFF
        unknown = int(inst.get('unknown', 0)) & 0xFFFFFFFF
        total_duration = float(inst.get('total_duration', 0.0))
        flags = int(inst.get('flags', 0)) & 0xFFFF

        # offset patché en absolu
        struct.pack_into('>I', (buf := bytearray(16)), 0, 0)
        struct.pack_into('>I', buf, 4, unknown)
        struct.pack_into('>f', buf, 8, total_duration)
        struct.pack_into('>H', buf, 12, flags)
        struct.pack_into('>H', buf, 14, point_count)

        blob.extend(buf)

        if point_count > 0:
            patches.append({
                'at': idx * 16 + 0,
                'target_section_id': points_section_id,
                'target_relative': per_path_points_offset[idx],
                'type': 'absolute_u32',
            })

    return bytes(blob), patches


def rebuild_paths_from_folder(source_dir: str, name_to_offset: Dict[str, int]) -> Dict[int, Dict[str, Any]]:
    paths = _collect_paths(source_dir)
    # Préserver l'ordre original - ne pas trier

    meta_blob = _build_path_metadata(paths, name_to_offset)
    points_blob, per_path_offsets = _build_path_points(paths)
    data_blob, data_patches = _build_path_data(paths, PATH_POINTS_ID, per_path_offsets)

    sections: Dict[int, Dict[str, Any]] = {
        PATH_METADATA_ID: {
            'flag': 0x10,
            'count': len(paths),
            'size': 16,
            'data': meta_blob,
            'patches': [
                {
                    'at': i * 16 + 8,
                    'target_section_id': 0x00011300,  # NAME_TABLES_ID
                    'target_relative': name_to_offset.get(paths[i].get('name') or f"Path_{i+1}", 0),
                    'type': 'absolute_u32',
                }
                for i in range(len(paths))
            ],
        },
        PATH_POINTS_ID: {
            'flag': 0x00,
            'count': 1,
            'size': len(points_blob),
            'data': points_blob,
        },
        PATH_DATA_ID: {
            'flag': 0x10,
            'count': len(paths),
            'size': 16,
            'data': data_blob,
            'patches': data_patches,
        },
    }

    return sections



