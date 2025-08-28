import json
import os
import struct
from typing import Dict, Any, List, Tuple

from rebuild.mobys_metadata_rebuilder import rebuild_mobys_metadata
from shared.constants import MOBY_DATA_ID, HOST_CLASS_ID, LOCAL_CLASS_ID
from rebuild.classfiles_aggregator import register_host, register_local
from shared.utils import sanitize_name


def _collect_moby_instances_from_folder(source_dir: str) -> List[Tuple[dict, str]]:
    """Lit les fichiers *.moby.json sous source_dir.
    Retourne une liste de tuples (instance_dict, base_dir_du_fichier)."""
    results: List[Tuple[dict, str]] = []
    for root, _dirs, files in os.walk(source_dir):
        for fn in files:
            if fn.endswith('.moby.json'):
                path = os.path.join(root, fn)
                try:
                    with open(path, 'r', encoding='utf-8') as f:
                        inst = json.load(f)
                        results.append((inst, root))
                except Exception:
                    # Ignorer les JSON invalides
                    pass
    return results


def _pack_moby_data_entry(inst: dict, subfile_length: int) -> bytes:
    """Construit une entrée Moby Data (80 octets), avec subfile_offset=0 (patché ensuite)."""
    model_index = int(inst.get('model_index', 0)) & 0xFFFF
    zone_render_index = int(inst.get('zone_render_index', inst.get('zone', 0))) & 0xFFFF
    update_dist = float(inst.get('update_dist', -1.0))
    display_dist = float(inst.get('display_dist', -1.0))
    subfile_offset_placeholder = 0
    subfile_length_val = int(subfile_length) & 0xFFFFFFFF
    pos = inst.get('position', {})
    rot = inst.get('rotation', {})
    pos_x = float(pos.get('x', 0.0))
    pos_y = float(pos.get('y', 0.0))
    pos_z = float(pos.get('z', 0.0))
    rot_x = float(rot.get('x', 0.0))
    rot_y = float(rot.get('y', 0.0))
    rot_z = float(rot.get('z', 0.0))
    scale = float(inst.get('scale', 1.0))
    flags_hex = inst.get('flags', '0000000000000000')
    try:
        flags_bytes = bytes.fromhex(flags_hex)
        if len(flags_bytes) != 8:
            flags_bytes = flags_bytes.ljust(8, b'\x00')[:8]
    except Exception:
        flags_bytes = b'\x00' * 8
    unknown_hex = inst.get('unknown', '00000000')
    try:
        unknown_bytes = bytes.fromhex(unknown_hex)
        if len(unknown_bytes) != 4:
            unknown_bytes = unknown_bytes.ljust(4, b'\x00')[:4]
    except Exception:
        unknown_bytes = b'\x00' * 4
    # Utiliser le padding exact extrait de l'original
    padding_hex = inst.get('padding')
    if padding_hex is None:
        # Si pas de padding dans le JSON, utiliser 0xFFFFFFFF par défaut
        padding_bytes = b'\xFF' * 4
    else:
        try:
            padding_bytes = bytes.fromhex(padding_hex)
            if len(padding_bytes) != 4:
                padding_bytes = padding_bytes.ljust(4, b'\x00')[:4]
        except Exception:
            padding_bytes = b'\xFF' * 4

    buf = bytearray(80)
    struct.pack_into('>H', buf, 0, model_index)
    struct.pack_into('>H', buf, 2, zone_render_index)
    struct.pack_into('>f', buf, 4, update_dist)
    struct.pack_into('>f', buf, 8, display_dist)
    struct.pack_into('>I', buf, 12, subfile_offset_placeholder)
    struct.pack_into('>I', buf, 16, subfile_length_val)
    struct.pack_into('>f', buf, 20, pos_x)
    struct.pack_into('>f', buf, 24, pos_y)
    struct.pack_into('>f', buf, 28, pos_z)
    struct.pack_into('>f', buf, 32, rot_x)
    struct.pack_into('>f', buf, 36, rot_y)
    struct.pack_into('>f', buf, 40, rot_z)
    struct.pack_into('>f', buf, 44, scale)
    buf[48:56] = flags_bytes
    buf[56:60] = unknown_bytes
    buf[60:64] = padding_bytes
    # 64..79 reserved/unused per current script; leave zeros
    return bytes(buf)


def rebuild_mobys_from_folder(source_dir: str, name_to_offset: Dict[str, int] | None = None) -> Dict[int, Dict[str, Any]]:
    """Reconstruit les sections Mobys depuis le dossier extrait (JSON et subfiles .dat).

    Produit:
    - 0x00011300: Name Tables
    - 0x0002504C: Moby Metadata
    - 0x00025048: Moby Data (avec subfile_offset patché absolu + enregistré dans la table de pointeurs)
    - 0x00025020: Host Class Files (blob concaténé)
    - 0x00025030: Local Class Files (blob concaténé)
    """
    collected = _collect_moby_instances_from_folder(source_dir)

    # La section des noms est désormais produite en amont; on reçoit le mapping
    if name_to_offset is None:
        from rebuild.names_registry import build_name_tables_section
        name_sections, name_to_offset = build_name_tables_section(source_dir)
    else:
        name_sections = {}

    # Tri demandé: par ZoneIndex, puis TUID uniquement (ensuite nom pour stabilité)
    collected.sort(
        key=lambda t: (
            int(t[0].get('zone', t[0].get('zone_render_index', 0))),
            int(t[0].get('tuid', 0))
        )
    )

    instances_only = [inst for inst, _ in collected]

    sections = {}
    sections.update(name_sections)
    sections.update(rebuild_mobys_metadata(instances_only, name_to_offset))

    # Agrégation host/local centralisée via aggregator

    # Pour chaque instance, déterminer le subfile à utiliser et construire l'entrée Moby Data
    moby_data_bytes = bytearray()
    moby_patches: List[dict] = []

    for idx, (inst, base_dir) in enumerate(collected):
        name = inst.get('name') or f"Moby_{idx+1}"
        sname = sanitize_name(name)
        host_path = os.path.join(base_dir, f"{sname}_CLASS.host.dat")
        local_path = os.path.join(base_dir, f"{sname}_CLASS.local.dat")

        chosen_section_id = None
        chosen_rel_offset = 0
        sub_len = 0

        if os.path.isfile(host_path):
            with open(host_path, 'rb') as f:
                data = f.read()
            chosen_section_id = HOST_CLASS_ID
            chosen_rel_offset = register_host(data)
            sub_len = len(data)
        elif os.path.isfile(local_path):
            with open(local_path, 'rb') as f:
                data = f.read()
            chosen_section_id = LOCAL_CLASS_ID
            chosen_rel_offset = register_local(data)
            sub_len = len(data)
        else:
            # Pas de subfile
            chosen_section_id = None
            chosen_rel_offset = 0
            sub_len = 0

        entry = _pack_moby_data_entry(inst, sub_len)
        moby_data_bytes.extend(entry)

        # Ajouter un patch absolu sur le champ subfile_offset si un subfile existe
        if chosen_section_id is not None and sub_len > 0:
            moby_patches.append({
                'at': idx * 80 + 12,  # champ subfile_offset
                'target_section_id': chosen_section_id,
                'target_relative': chosen_rel_offset,
                'type': 'absolute_u32',
            })

    # Définir la section Moby Data
    sections[MOBY_DATA_ID] = {
        'flag': 0x10,
        'count': len(collected),
        'size': 80,
        'data': bytes(moby_data_bytes),
        'patches': moby_patches,
    }

    # Sections host/local seront ajoutées globalement par l'assembleur principal

    return sections


