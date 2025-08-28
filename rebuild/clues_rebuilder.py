import json
import os
import struct
from typing import Dict, Any, List

from shared.constants import CLUE_INFO_ID, CLUE_METADATA_ID, VOLUME_METADATA_ID, NAME_TABLES_ID, HOST_CLASS_ID, LOCAL_CLASS_ID, INSTANCE_TYPES_ID
from shared.utils import sanitize_name
from rebuild.classfiles_aggregator import register_host, register_local


def _collect_clues(source_dir: str) -> List[dict]:
    clues: List[dict] = []
    # Collecter tous les fichiers dans un ordre déterministe
    all_files = []
    for root, _dirs, files in os.walk(source_dir):
        for fn in files:
            all_files.append((root, fn))
    
    # Trier par chemin pour un ordre déterministe
    all_files.sort(key=lambda x: x[0] + '/' + x[1])
    
    for root, fn in all_files:
            if fn.endswith('.clue.json'):
                p = os.path.join(root, fn)
                try:
                    with open(p, 'r', encoding='utf-8') as f:
                        obj = json.load(f)
                        obj['__base_dir__'] = root
                        clues.append(obj)
                except Exception:
                    pass
    # Tri par zone ascendante puis TUID pour matcher la structuration par zone
    try:
        clues.sort(key=lambda inst: (int(inst.get('zone', 0)), int(inst.get('tuid', 0xFFFFFFFFFFFFFFFF))))
    except Exception:
        pass
    return clues


def _build_clue_metadata(clues: List[dict], name_to_offset: Dict[str, int]) -> bytes:
    blob = bytearray()
    for idx, inst in enumerate(clues):
        tuid = int(inst.get('tuid', 0xFFFFFFFFFFFFFFFF)) & 0xFFFFFFFFFFFFFFFF
        name = inst.get('name') or f"Clue_{idx+1}"
        name_off = name_to_offset.get(name, 0)
        zone_u16 = int(inst.get('zone', 0)) & 0xFFFF
        entry = bytearray(16)
        struct.pack_into('>Q', entry, 0, tuid)
        struct.pack_into('>I', entry, 8, name_off)
        struct.pack_into('>H', entry, 12, zone_u16)
        struct.pack_into('>H', entry, 14, 0)
        blob.extend(entry)
    return bytes(blob)


def _build_clue_info(
    clues: List[dict],
    per_clue_inst_type_rel: List[int | None],
    host_blob: bytearray,
    local_blob: bytearray,
) -> tuple[bytes, List[dict]]:
    blob = bytearray()
    patches: List[dict] = []

    for idx, inst in enumerate(clues):
        # 16 bytes: VolumeTuidOffset (u32), SubfileOffset (u32), SubfileLength (u32), ClassID (u32)
        buf = bytearray(16)

        # Volume TUID pointer → vers VOLUME_METADATA_ID: adresse d'une entrée contenant le TUID
        # Pointeur vers 0x00025022 (Instance Types), entrée du volume pour CE clue
        inst_type_rel = per_clue_inst_type_rel[idx]
        struct.pack_into('>I', buf, 0, 0)  # patch absolu (vers 0x00025022)

        # Subfile
        name = inst.get('name') or f"Clue_{idx+1}"
        sname = sanitize_name(name)
        sub_len = 0
        chosen_section = None
        chosen_rel = 0
        # host/local exclusifs, comme pour moby/controllers
        base_dir = inst.get('__base_dir__')  # optionnel si on veut la source exacte
        # Fallback: on cherchera plus haut pendant l'assemblage si base_dir absent

        # Ces chemins seront renseignés par l'appelant si besoin; ici on ne dépend pas du base_dir
        # Cette implémentation suppose que les .clue.json sont dans le même dossier que les subfiles
        # Essai: recherche locale
        # Ne rechercher les subfiles que dans le dossier source de l'instance
        for search_dir in [inst.get('__base_dir__')]:
            if not search_dir:
                continue
            host_path = os.path.join(search_dir, f"{sname}_CLASS.host.dat")
            local_path = os.path.join(search_dir, f"{sname}_CLASS.local.dat")
            if os.path.isfile(host_path):
                with open(host_path, 'rb') as f:
                    data = f.read()
                chosen_section = HOST_CLASS_ID
                chosen_rel = register_host(data)
                sub_len = len(data)
                break
            if os.path.isfile(local_path):
                with open(local_path, 'rb') as f:
                    data = f.read()
                chosen_section = LOCAL_CLASS_ID
                chosen_rel = register_local(data)
                sub_len = len(data)
                break

        struct.pack_into('>I', buf, 4, 0)  # subfile_offset patché
        struct.pack_into('>I', buf, 8, sub_len & 0xFFFFFFFF)

        class_id = int(inst.get('class_id', 0)) & 0xFFFFFFFF
        struct.pack_into('>I', buf, 12, class_id)

        blob.extend(buf)

        # Patches absolus
        if inst_type_rel is not None:
            patches.append({
                'at': idx * 16 + 0,
                'target_section_id': INSTANCE_TYPES_ID,
                'target_relative': inst_type_rel,
                'type': 'absolute_u32',
            })
        else:
            # Avertir si volume_tuid manquant ou non résolu
            try:
                vraw = inst.get('volume_tuid')
                vprint = f"0x{int(vraw,0):016X}" if isinstance(vraw, str) else f"0x{int(vraw):016X}" if vraw is not None else "<None>"
            except Exception:
                vprint = str(inst.get('volume_tuid'))
            try:
                print(f"[WARN] CLUE volume_tuid {vprint} absent de 0x25022 – pointeur restera 0")
            except Exception:
                pass
        if chosen_section is not None and sub_len > 0:
            patches.append({
                'at': idx * 16 + 4,
                'target_section_id': chosen_section,
                'target_relative': chosen_rel,
                'type': 'absolute_u32',
            })

    return bytes(blob), patches


def rebuild_clues_from_folder(
    source_dir: str,
    name_to_offset: Dict[str, int],
    inst_types_map: Dict[int, int],
) -> Dict[int, Dict[str, Any]]:
    clues = _collect_clues(source_dir)

    meta_blob = _build_clue_metadata(clues, name_to_offset)

    # Utiliser le mapping global 0x25022 fourni (incluant Clue TUID et Volume TUID)
    per_clue_inst_type_rel: List[int | None] = []
    for idx, inst in enumerate(clues):
        vol_tuid_raw = inst.get('volume_tuid')
        try:
            vol_tuid = int(vol_tuid_raw, 0) if isinstance(vol_tuid_raw, str) else int(vol_tuid_raw)
        except Exception:
            vol_tuid = None
        if vol_tuid is None:
            per_clue_inst_type_rel.append(None)
        else:
            per_clue_inst_type_rel.append(inst_types_map.get(vol_tuid & 0xFFFFFFFFFFFFFFFF))

    host_blob = bytearray()
    local_blob = bytearray()
    info_blob, info_patches = _build_clue_info(
        clues,
        per_clue_inst_type_rel,
        host_blob,
        local_blob,
    )

    sections: Dict[int, Dict[str, Any]] = {
        CLUE_METADATA_ID: {
            'flag': 0x10,
            'count': len(clues),
            'size': 16,
            'data': meta_blob,
            'patches': [
                {
                    'at': i * 16 + 8,
                    'target_section_id': NAME_TABLES_ID,
                    'target_relative': name_to_offset.get(clues[i].get('name') or f"Clue_{i+1}", 0),
                    'type': 'absolute_u32',
                }
                for i in range(len(clues))
            ],
        },
        CLUE_INFO_ID: {
            'flag': 0x10,
            'count': len(clues),
            'size': 16,
            'data': info_blob,
            'patches': info_patches,
        },
    }

    # sections host/local seront ajoutées globalement via l'agrégateur

    return sections


