import os
import struct
from typing import Dict, Any, List

from rebuild.ighw_header import build_ighw_header_bytes


ALIGNMENT = 0x80


def _align(offset: int, alignment: int = ALIGNMENT) -> int:
    remainder = offset % alignment
    return offset if remainder == 0 else offset + (alignment - remainder)


def _pad_pattern(length: int) -> bytes:
    """Retourne un motif de padding cyclique ASCII 'PAD0'..'PADF' répété."""
    if length <= 0:
        return b''
    base_units = [f"PAD{c}".encode('ascii') for c in "0123456789ABCDEF"]
    pattern = b"".join(base_units)  # b"PAD0PAD1...PADF"
    full, rem = divmod(length, len(pattern))
    if rem == 0:
        return pattern * full
    # Compléter la fin en coupant dans la séquence PAD0..PADF
    out = bytearray()
    out.extend(pattern * full)
    # Ajouter rem octets issus de la séquence
    idx = 0
    while len(out) < length:
        chunk = base_units[idx % len(base_units)]
        take = min(len(chunk), length - len(out))
        out.extend(chunk[:take])
        idx += 1
    return bytes(out)


PREFERRED_SECTION_ORDER = [
    0x00025048, 0x0002504C, 0x00011300,
    0x00025008, 0x0002500C,
    0x00025050, 0x00025054, 0x0002506C, 0x00025070,
    0x00025058, 0x0002505C, 0x00025060, 0x00025064, 0x00025068,
    0x0002508C, 0x00025090,
    0x00025080, 0x00025084,
    0x00025074, 0x00025078,
    0x00025094, 0x00025088, 0x0002507C,
    0x00025022, 0x00025010, 0x00025014, 0x00025020, 0x00025030,
    0x00025005, 0x00025006,
]


def assemble_sections(
    sections: Dict[int, Dict[str, Any]],
    output_path: str,
    *,
    version_major: int = 1,
    version_minor: int = 1,
) -> None:
    """Assemble un fichier IGHW à partir de sections prêtes à écrire.

    sections: dict section_id -> {
        'flag': int,
        'count': int,                # utile si flag == 0x10
        'size': int,                 # taille élément (flag 0x10) ou taille totale (flag 0x00)
        'data': bytes|bytearray,     # payload de la section
        'patches': [                 # optionnel: patches à appliquer après placement
            {
                'at': int,                   # offset dans cette section (en octets)
                'target_section_id': int,    # section cible
                'target_relative': int,      # offset relatif dans la section cible
                'type': 'absolute_u32',
                'addend': int (optionnel),   # valeur additionnelle
            }
        ]
    }
    """

    # Ordonner les sections selon un ordre préféré (proche de l'original) et filtrer celles vides
    present = {sid: info for sid, info in sections.items() if len((info.get('data') or b'')) > 0}
    ordered_items: List[tuple[int, Dict[str, Any]]] = []
    # D'abord les sections connues, dans l'ordre
    for sid in PREFERRED_SECTION_ORDER:
        if sid in present:
            ordered_items.append((sid, present.pop(sid)))
    # Puis toutes les autres restantes (stables par id croissant)
    for sid in sorted(present.keys()):
        ordered_items.append((sid, present[sid]))

    # Étape 1: Calcul des offsets de données
    header_length = 0x20 + 16 * len(ordered_items) if version_major >= 1 else 0x10 + 16 * len(ordered_items)
    current_offset = _align(header_length)

    layout = {}
    for section_id, info in ordered_items:
        data_bytes = info.get('data', b'')
        # Aligner le début de la section
        current_offset = _align(current_offset)
        layout[section_id] = {
            'offset': current_offset,
            'length': len(data_bytes),
        }
        current_offset += len(data_bytes)

    # Ne pas réaligner la fin des données avant la table des pointeurs; l'offset peut être non multiple de ALIGNMENT
    end_of_data = current_offset

    # Étape 2: Appliquer les patches dépendant des offsets finaux
    # Convertir 'data' en bytearray pour patcher
    for section_id, info in ordered_items:
        if not isinstance(info['data'], (bytes, bytearray)):
            raise ValueError(f"Section {section_id:08X}: 'data' doit être bytes/bytearray")
        if isinstance(info['data'], bytes):
            info['data'] = bytearray(info['data'])

    for section_id, info in ordered_items:
        patches = info.get('patches') or []
        base_offset = layout[section_id]['offset']
        for p in patches:
            ptype = p.get('type')
            at = p['at']
            target_id = p['target_section_id']
            target_rel = p.get('target_relative', 0)
            addend = p.get('addend', 0)

            if ptype == 'absolute_u32':
                absolute = layout[target_id]['offset'] + target_rel + addend
                # Sécuriser la taille du buffer avant écriture
                needed = at + 4
                if needed > len(info['data']):
                    info['data'].extend(b'\x00' * (needed - len(info['data'])))
                struct.pack_into('>I', info['data'], at, absolute)
            else:
                raise ValueError(f"Patch type non supporté: {ptype}")

    # Étape 3: Construire l'entête
    section_headers = []
    for section_id, info in ordered_items:
        section_headers.append({
            'id': section_id,
            'data_offset': layout[section_id]['offset'],
            'flag': info.get('flag', 0),
            'count': info.get('count', 0),
            'size': info.get('size', 0),
        })

    # La table des pointeurs débute à la fin des données
    pointer_table_offset = end_of_data if version_major >= 1 else 0

    header = build_ighw_header_bytes(
        version_major=version_major,
        version_minor=version_minor,
        sections=section_headers,
        pointer_table_offset=pointer_table_offset,
        pointer_count=0,  # sera mis à jour après avoir écrit la table
    )

    # Étape 4: Écrire le fichier
    with open(output_path, 'wb') as f:
        # Header
        f.write(header)
        # Padding jusqu'au premier offset de section
        pad_len = layout[ordered_items[0][0]]['offset'] - len(header) if ordered_items else 0
        if pad_len > 0:
            f.write(_pad_pattern(pad_len))

        # Sections
        written = len(header) + pad_len
        for section_id, info in ordered_items:
            current_pos = f.tell()
            # Aligner si nécessaire
            if current_pos != layout[section_id]['offset']:
                f.write(_pad_pattern(layout[section_id]['offset'] - current_pos))
            f.write(bytes(info['data']))
            written = layout[section_id]['offset'] + len(info['data'])

        # Écrire la table des pointeurs absolute_u32
        # Collecter les enregistrements: chaque patch 'absolute_u32' génère UNE entrée
        pointer_records: list[int] = []
        for section_id, info in ordered_items:
            for p in (info.get('patches') or []):
                if p.get('type') == 'absolute_u32':
                    ptr_position = layout[section_id]['offset'] + p['at']
                    pointer_records.append(ptr_position)

        # Densifier la table comme l'original:
        # - Ajouter toutes les positions u32 des sections OFFSETS (AREA/POD/SCENT)
        # - Ajouter toutes les positions du champ subfile_offset des MOBY_DATA (+12)
        OFFSETS_SECTIONS = {0x00025088, 0x0002507C, 0x00025094}
        MOBY_DATA_ID = 0x00025048
        for section_id, info in ordered_items:
            # Offsets sections: pas de condition sur la valeur, on enregistre toutes les positions 4B
            if section_id in OFFSETS_SECTIONS:
                base = layout[section_id]['offset']
                length = layout[section_id]['length']
                # L'original semble lister toutes les positions u32 des sections OFFSETS (y compris zéro)
                for rel in range(0, length, 4):
                    pointer_records.append(base + rel)
            # Moby subfile_offset à +12 pour chaque entrée (ajouter seulement si non nul)
            if section_id == MOBY_DATA_ID and info.get('flag') == 0x10 and info.get('size', 0) >= 16:
                base = layout[section_id]['offset']
                count = info.get('count', 0)
                elem = info.get('size', 0)
                buf = info.get('data', b'')
                for i in range(count):
                    rel = i * elem + 12
                    try:
                        val = struct.unpack_from('>I', buf, rel)[0]
                    except Exception:
                        val = 0
                    if val != 0:
                        pointer_records.append(base + rel)

        # Dédupliquer et trier par adresse croissante (comme l'original)
        pointer_records = sorted(set(pointer_records))

        # Aligner la position courante à pointer_table_offset si nécessaire
        current_pos = f.tell()
        if current_pos < pointer_table_offset:
            f.write(_pad_pattern(pointer_table_offset - current_pos))

        # Écrire les positions des pointeurs (u32 big-endian) triées par adresse croissante
        for ptr_pos in pointer_records:
            f.write(struct.pack('>I', ptr_pos))

        # Mettre à jour le header in-file pour pointer_count
        final_pos = f.tell()
        pointer_count = len(pointer_records)
        f.seek(0)
        # Réécrire le header avec pointer_count corrigé (et même pointer_table_offset)
        header2 = build_ighw_header_bytes(
            version_major=version_major,
            version_minor=version_minor,
            sections=section_headers,
            pointer_table_offset=pointer_table_offset,
            pointer_count=pointer_count,
        )
        f.write(header2)
        f.seek(final_pos)


