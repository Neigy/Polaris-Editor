import json
import os
import struct
from typing import Dict, Any, List, Tuple

from shared.constants import (
    ZONE_METADATA_ID, ZONE_OFFSETS_ID, ZONE_COUNTS_ID, DEFAULT_REGION_NAMES_ID,
    REGION_DATA_ID, REGION_POINTERS_ID,
    MOBY_DATA_ID, MOBY_METADATA_ID,
    PATH_DATA_ID, PATH_METADATA_ID,
    VOLUME_TRANSFORM_ID, VOLUME_METADATA_ID,
    CLUE_INFO_ID, CLUE_METADATA_ID,
    CONTROLLER_DATA_ID, CONTROLLER_METADATA_ID,
    AREA_DATA_ID, AREA_METADATA_ID,
    POD_DATA_ID, POD_METADATA_ID,
    SCENT_DATA_ID, SCENT_METADATA_ID,
)


TYPE_INDEX_BY_SUFFIX = {
    '.moby.json': 0,
    '.path.json': 1,
    '.volume.json': 2,
    '.clue.json': 3,
    '.controller.json': 4,
    '.area.json': 5,
    '.pod.json': 6,
    '.scent.json': 7,
}


def _detect_type_index(filename: str) -> int:
    for suffix, idx in TYPE_INDEX_BY_SUFFIX.items():
        if filename.endswith(suffix):
            return idx
    return 8  # Unused


def _collect_zones(source_dir: str) -> Tuple[str, Dict[int, str], Dict[int, List[int]]]:
    zone_index_to_name: Dict[int, str] = {}
    # counts_per_zone[zone] = [count per type index 0..8]
    counts_per_zone: Dict[int, List[int]] = {}
    detected_region_name: str | None = None

    for root, _dirs, files in os.walk(source_dir):
        for fn in files:
            if not any(fn.endswith(s) for s in TYPE_INDEX_BY_SUFFIX.keys()):
                continue
            path = os.path.join(root, fn)
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    obj = json.load(f)
                zone = int(obj.get('zone', 0))
            except Exception:
                continue

            # Try to infer region/zone names from folder path
            parts = root.replace('\\', '/').split('/')
            zone_name = parts[-1] if parts else f"Zone_{zone}"
            if detected_region_name is None:
                detected_region_name = parts[-2] if len(parts) >= 2 else 'default'
            if zone not in zone_index_to_name:
                zone_index_to_name[zone] = zone_name or f"Zone_{zone}"

            type_idx = _detect_type_index(fn)
            if zone not in counts_per_zone:
                counts_per_zone[zone] = [0] * 9
            counts_per_zone[zone][type_idx] += 1

    return (detected_region_name or 'default'), zone_index_to_name, counts_per_zone


def rebuild_zones_from_folder(source_dir: str) -> Dict[int, Dict[str, Any]]:
    region_name, zone_names, counts_per_zone = _collect_zones(source_dir)
    zones_sorted = sorted(counts_per_zone.keys())

    # Build Zone Metadata (0x00025008): 144 bytes/zone
    # Layout: 64 bytes name + for t in 0..8: (u32 offset=0, u32 count) => 64 + 72 = 136, then 8 bytes = 4x u16 (inconnus)
    zone_meta_blob = bytearray()
    for zone in zones_sorted:
        name = zone_names.get(zone) or f"Zone_{zone}"
        name_bytes = (name[:64]).encode('utf-8', errors='ignore')
        name_bytes = name_bytes[:64]
        name_bytes = name_bytes + b'\x00' * (64 - len(name_bytes))
        zone_meta_blob.extend(name_bytes)
        counts = counts_per_zone.get(zone, [0] * 9)
        for t in range(9):
            zone_meta_blob.extend(struct.pack('>I', 0))  # offset placeholder (list to be defined plus tard)
            zone_meta_blob.extend(struct.pack('>I', counts[t] & 0xFFFFFFFF))
        # 8 derniers octets = 4x u16 (inconnus). Injecter depuis extraction_metadata.json si présent.
        zone_meta_blob.extend(b'\x00' * 8)

    # Build Zone Offsets (0x0002500C): 36 bytes/zone = 9 * u32 zeros (placeholders)
    zone_offsets_blob = bytearray()
    for _zone in zones_sorted:
        for _t in range(9):
            zone_offsets_blob.extend(struct.pack('>I', 0))

    # Build Zone Counts (0x00025014): liste d'indices de zones (u16) référencée par 0x00025010
    zone_counts_blob = bytearray()
    for zone in zones_sorted:
        zone_counts_blob.extend(struct.pack('>H', zone & 0xFFFF))

    sections: Dict[int, Dict[str, Any]] = {
        ZONE_METADATA_ID: {
            'flag': 0x10,
            'count': len(zones_sorted),
            'size': 144,
            'data': bytes(zone_meta_blob),
        },
        ZONE_OFFSETS_ID: {
            'flag': 0x10,
            'count': len(zones_sorted),
            'size': 36,
            'data': bytes(zone_offsets_blob),
        },
        ZONE_COUNTS_ID: {
            'flag': 0x00,
            'count': 1,
            'size': len(zone_counts_blob),
            'data': bytes(zone_counts_blob),
        },
    }

    # Essayer de charger extraction_metadata.json pour réinjecter les 4x u16 inconnus
    try:
        import os, json
        meta_path = os.path.join(source_dir, 'extraction_metadata.json')
        if os.path.isfile(meta_path):
            with open(meta_path, 'r', encoding='utf-8') as f:
                meta = json.load(f)
            tails = meta.get('zone_tail_u16') or []
            if isinstance(tails, list) and len(tails) >= len(zones_sorted):
                zb = bytearray(sections[ZONE_METADATA_ID]['data'])
                for zi, zone in enumerate(zones_sorted):
                    t = tails[zi]
                    if not (isinstance(t, list) and len(t) == 4):
                        continue
                    base = zi * 144 + 64 + 9 * 8
                    import struct as _s
                    _s.pack_into('>HHHH', zb, base, int(t[0]) & 0xFFFF, int(t[1]) & 0xFFFF, int(t[2]) & 0xFFFF, int(t[3]) & 0xFFFF)
                sections[ZONE_METADATA_ID]['data'] = bytes(zb)
    except Exception:
        pass

    # Patcher les pointeurs de 0x25008 (vers DATA par type) et 0x2500C (vers METADATA par type)
    # Mapping type index -> (data_section_id, data_elem_size, meta_section_id, meta_elem_size)
    TYPE_SECTIONS = {
        0: (MOBY_DATA_ID, 80, MOBY_METADATA_ID, 16),
        1: (PATH_DATA_ID, 16, PATH_METADATA_ID, 16),
        2: (VOLUME_TRANSFORM_ID, 64, VOLUME_METADATA_ID, 16),
        3: (CLUE_INFO_ID, 16, CLUE_METADATA_ID, 16),
        4: (CONTROLLER_DATA_ID, 48, CONTROLLER_METADATA_ID, 16),
        5: (AREA_DATA_ID, 16, AREA_METADATA_ID, 16),
        6: (POD_DATA_ID, 16, POD_METADATA_ID, 16),
        7: (SCENT_DATA_ID, 16, SCENT_METADATA_ID, 16),
        8: (0, 0, 0, 0),
    }

    # Préfixes cumulés par type pour calculer l'adresse de départ de chaque zone
    # zones_sorted est l'ordre; pour chaque type, calculer cumul avant zone
    prefix_by_type: Dict[int, Dict[int, int]] = {t: {} for t in range(9)}
    running = [0] * 9
    for zone in zones_sorted:
        counts = counts_per_zone.get(zone, [0] * 9)
        for t in range(9):
            prefix_by_type[t][zone] = running[t]
            running[t] += counts[t]

    # Patches pour Zone Metadata (offsets vers DATA)
    zone_meta_patches: List[dict] = []
    for zi, zone in enumerate(zones_sorted):
        base = zi * 144
        counts = counts_per_zone.get(zone, [0] * 9)
        for t in range(9):
            data_sec, data_size, _, _ = TYPE_SECTIONS[t]
            if data_sec == 0:
                continue
            if counts[t] > 0:
                rel = prefix_by_type[t][zone] * data_size
                at = base + 64 + t * 8  # position de l'offset dans l'entrée
                zone_meta_patches.append({
                    'at': at,
                    'target_section_id': data_sec,
                    'target_relative': rel,
                    'type': 'absolute_u32',
                })

    # Patches pour Zone Offsets (offsets vers METADATA)
    zone_off_patches: List[dict] = []
    for zi, zone in enumerate(zones_sorted):
        counts = counts_per_zone.get(zone, [0] * 9)
        for t in range(9):
            _, _, meta_sec, meta_size = TYPE_SECTIONS[t]
            if meta_sec == 0:
                continue
            if counts[t] > 0:
                rel = prefix_by_type[t][zone] * meta_size
                at = zi * 36 + t * 4
                zone_off_patches.append({
                    'at': at,
                    'target_section_id': meta_sec,
                    'target_relative': rel,
                    'type': 'absolute_u32',
                })

    if zone_meta_patches:
        sections[ZONE_METADATA_ID]['patches'] = zone_meta_patches
    if zone_off_patches:
        sections[ZONE_OFFSETS_ID]['patches'] = zone_off_patches

    # Build Default Region Names (0x00025010): 64 bytes name + u32 indices_offset + u32 indices_count
    region_name_bytes = region_name.encode('utf-8')
    region_name_bytes = region_name_bytes[:64] + b'\x00' * (64 - len(region_name_bytes))
    default_region_blob = bytearray()
    default_region_blob.extend(region_name_bytes)
    # placeholders for pointer + count
    default_region_blob.extend(struct.pack('>I', 0))  # indices_offset
    default_region_blob.extend(struct.pack('>I', len(zones_sorted) & 0xFFFFFFFF))  # indices_count

    sections[DEFAULT_REGION_NAMES_ID] = {
        'flag': 0x10,
        'count': 1,
        'size': 0x48,
        'data': bytes(default_region_blob),
        'patches': [
            {
                'at': 64,  # offset du champ indices_offset
                'target_section_id': ZONE_COUNTS_ID,
                'target_relative': 0,
                'type': 'absolute_u32',
            }
        ],
    }

    # Region Data (0x00025005): single item 16 octets
    # [u32 zone_meta_offset, u32 zone_count, u32 default_region_names_offset, u32 region_count]
    region_data_blob = bytearray(16)
    # zone_meta_offset (patch vers ZONE_METADATA_ID)
    # zone_count
    struct.pack_into('>I', region_data_blob, 4, len(zones_sorted) & 0xFFFFFFFF)
    # default_region_names_offset (patch vers DEFAULT_REGION_NAMES_ID)
    # region_count (ici 1)
    struct.pack_into('>I', region_data_blob, 12, 1)

    sections[REGION_DATA_ID] = {
        'flag': 0x00,
        'count': 1,
        'size': 16,
        'data': bytes(region_data_blob),
        'patches': [
            {
                'at': 0,
                'target_section_id': ZONE_METADATA_ID,
                'target_relative': 0,
                'type': 'absolute_u32',
            },
            {
                'at': 8,
                'target_section_id': DEFAULT_REGION_NAMES_ID,
                'target_relative': 0,
                'type': 'absolute_u32',
            },
        ],
    }

    # Region Pointers (0x00025006): u32 par région, pointe vers Zone Offsets
    region_ptrs_blob = bytearray()
    # Une seule région -> une entrée
    region_ptrs_blob.extend(struct.pack('>I', 0))  # patch vers ZONE_OFFSETS_ID

    sections[REGION_POINTERS_ID] = {
        'flag': 0x00,
        'count': 1,
        'size': 4,
        'data': bytes(region_ptrs_blob),
        'patches': [
            {
                'at': 0,
                'target_section_id': ZONE_OFFSETS_ID,
                'target_relative': 0,
                'type': 'absolute_u32',
            }
        ],
    }

    return sections


