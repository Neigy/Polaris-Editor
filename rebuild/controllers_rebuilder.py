import json
import os
import struct
from typing import Dict, Any, List, Tuple

from shared.constants import (
    CONTROLLER_DATA_ID, CONTROLLER_METADATA_ID, HOST_CLASS_ID, LOCAL_CLASS_ID, NAME_TABLES_ID
)
from shared.utils import sanitize_name
from rebuild.classfiles_aggregator import register_host, register_local


def _collect_controllers(source_dir: str) -> List[Tuple[dict, str]]:
    results: List[Tuple[dict, str]] = []
    for root, _dirs, files in os.walk(source_dir):
        for fn in files:
            if fn.endswith('.controller.json'):
                p = os.path.join(root, fn)
                try:
                    with open(p, 'r', encoding='utf-8') as f:
                        results.append((json.load(f), root))
                except Exception:
                    pass
    return results


def _build_controller_metadata(controllers: List[dict], name_to_offset: Dict[str, int]) -> bytes:
    # 16 bytes/entry: TUID (u64), NameOffset (u32), ZoneIndex (u16), Padding (u16)
    blob = bytearray()
    for idx, inst in enumerate(controllers):
        tuid = int(inst.get('tuid', 0xFFFFFFFFFFFFFFFF)) & 0xFFFFFFFFFFFFFFFF
        name = inst.get('name') or f"Controller_{idx+1}"
        name_off = name_to_offset.get(name, 0)
        zone_u16 = int(inst.get('zone', 0)) & 0xFFFF
        entry = bytearray(16)
        struct.pack_into('>Q', entry, 0, tuid)
        struct.pack_into('>I', entry, 8, name_off)
        struct.pack_into('>H', entry, 12, zone_u16)
        # Metadata padding (2 bytes) – réutiliser si présent dans le JSON
        meta_pad_hex = inst.get('metadata_padding')
        if isinstance(meta_pad_hex, str):
            try:
                meta_pad = bytes.fromhex(meta_pad_hex)
                if len(meta_pad) != 2:
                    meta_pad = meta_pad.ljust(2, b'\x00')[:2]
            except Exception:
                meta_pad = b'\x00\x00'
        else:
            meta_pad = b'\x00\x00'
        entry[14:16] = meta_pad
        blob.extend(entry)
    return bytes(blob)


def _build_controller_data_and_patches(collected: List[Tuple[dict, str]]) -> tuple[bytes, List[dict], bytes, bytes]:
    data_blob = bytearray()
    patches: List[dict] = []
    # agrégation centrale

    for idx, (inst, base_dir) in enumerate(collected):
        # Structure (48 bytes): SubfileOffset (u32), Length (u32), Pos (3x f32), Rot (3x f32), Scale X/Y/Z (3x f32), Padding (4)
        buf = bytearray(48)

        # Subfile
        name = inst.get('name') or f"Controller_{idx+1}"
        sname = sanitize_name(name)
        host_path = os.path.join(base_dir, f"{sname}_CLASS.host.dat")
        local_path = os.path.join(base_dir, f"{sname}_CLASS.local.dat")

        chosen_section = None
        chosen_rel = 0
        sub_len = 0
        if os.path.isfile(host_path):
            with open(host_path, 'rb') as f:
                d = f.read()
            chosen_section = HOST_CLASS_ID
            chosen_rel = register_host(d)
            sub_len = len(d)
        elif os.path.isfile(local_path):
            with open(local_path, 'rb') as f:
                d = f.read()
            chosen_section = LOCAL_CLASS_ID
            chosen_rel = register_local(d)
            sub_len = len(d)

        # Offsets: patchés plus tard
        struct.pack_into('>I', buf, 0, 0)
        struct.pack_into('>I', buf, 4, sub_len & 0xFFFFFFFF)

        pos = inst.get('position', {})
        rot = inst.get('rotation', {})
        scale = float(inst.get('scale', 1.0))
        struct.pack_into('>f', buf, 8, float(pos.get('x', 0.0)))
        struct.pack_into('>f', buf, 12, float(pos.get('y', 0.0)))
        struct.pack_into('>f', buf, 16, float(pos.get('z', 0.0)))
        struct.pack_into('>f', buf, 20, float(rot.get('x', 0.0)))
        struct.pack_into('>f', buf, 24, float(rot.get('y', 0.0)))
        struct.pack_into('>f', buf, 28, float(rot.get('z', 0.0)))
        struct.pack_into('>f', buf, 32, scale)
        # +36..+43: Scale Y/Z (2x f32) - par défaut 1.0 si absents
        scale_y = float(inst.get('scale_y', 1.0))
        scale_z = float(inst.get('scale_z', 1.0))
        struct.pack_into('>f', buf, 36, scale_y)
        struct.pack_into('>f', buf, 40, scale_z)
        # +44..+47: padding 4B
        data_pad_hex = inst.get('datapadding', inst.get('data_padding'))
        if isinstance(data_pad_hex, str):
            try:
                data_pad = bytes.fromhex(data_pad_hex)
                if len(data_pad) != 4:
                    data_pad = data_pad.ljust(4, b'\x00')[:4]
            except Exception:
                data_pad = b'\x00' * 4
        else:
            data_pad = b'\x00' * 4
        buf[44:48] = data_pad

        if chosen_section is not None and sub_len > 0:
            patches.append({
                'at': idx * 48 + 0,
                'target_section_id': chosen_section,
                'target_relative': chosen_rel,
                'type': 'absolute_u32',
            })

        data_blob.extend(buf)

    return bytes(data_blob), patches


def rebuild_controllers_from_folder(source_dir: str) -> Dict[int, Dict[str, Any]]:
    collected = _collect_controllers(source_dir)
    # Tri: zone index puis TUID puis nom
    collected.sort(key=lambda t: (int(t[0].get('zone', 0)), int(t[0].get('tuid', 0))))
    instances = [inst for inst, _ in collected]

    # Reutiliser/étendre la section des noms depuis le dossier (commune à tout le fichier)
    # Ici on ne l'écrit pas, c'est géré globalement par le premier rebuilder qui la produit
    # mais on a besoin de name_to_offset pour patcher/écrire les metadata.
    # On reconstruit localement la map (sans ajouter la section dupliquée si déjà présente).
    from rebuild.names_registry import collect_names_from_folder
    names = collect_names_from_folder(source_dir)
    name_to_offset = {n: sum(len(x.encode('utf-8')) + 1 for x in names[:i]) for i, n in enumerate(names)}

    meta_blob = _build_controller_metadata(instances, name_to_offset)
    data_blob, patches = _build_controller_data_and_patches(collected)

    sections: Dict[int, Dict[str, Any]] = {
        CONTROLLER_METADATA_ID: {
            'flag': 0x10,
            'count': len(instances),
            'size': 16,
            'data': meta_blob,
            # NameOffset champs (u32) à 8: enregistrés dans la table des pointeurs par le rebuilder des noms
            'patches': [
                {
                    'at': i * 16 + 8,
                    'target_section_id': NAME_TABLES_ID,
                    'target_relative': name_to_offset.get(instances[i].get('name') or f"Controller_{i+1}", 0),
                    'type': 'absolute_u32',
                }
                for i in range(len(instances))
            ],
        },
        CONTROLLER_DATA_ID: {
            'flag': 0x10,
            'count': len(instances),
            'size': 48,
            'data': data_blob,
            'patches': patches,
        },
    }

    # sections host/local ajoutées globalement

    return sections


