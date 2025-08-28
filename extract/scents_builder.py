# extract/scents_builder.py
import os
import struct
import json
from shared.constants import (
    SCENT_DATA_ID, SCENT_METADATA_ID, SCENT_OFFSETS_ID, NAME_TABLES_ID, INSTANCE_TYPES_ID,
    INSTANCE_TYPES
)
from shared.utils import (
    read_u32_be, read_u16_be, read_float_be, read_string, sanitize_name, 
    find_next_level_dir, find_section_by_id, parse_sections
)
# Suppression de la collecte de pointeurs

def extract_scents_from_dat(dat_path):
    """Extrait les données Scent avec leurs métadonnées"""
    with open(dat_path, 'rb') as f:
        data = f.read()

    # Vérifier la version du fichier
    version_major = struct.unpack(">H", data[4:6])[0]
    section_count = struct.unpack(">H" if version_major == 0 else ">I", 
                                 data[0x0A if version_major == 0 else 0x0C:
                                      0x0C if version_major == 0 else 0x10])[0]
    section_start = 0x10 if version_major == 0 else 0x20
    
    # Parser toutes les sections
    sections_data = {}
    for i in range(section_count):
        offset = section_start + i * 16
        section_id, data_offset, flag, item_count = struct.unpack(">IIB3s", data[offset:offset+12])
        item_count = int.from_bytes(item_count, "big")
        size = struct.unpack(">I", data[offset+12:offset+16])[0]
        
        sections_data[section_id] = {
            "offset": data_offset,
            "count": item_count if flag == 0x10 else 1,
            "size": size,
            "flag": flag
        }

    # Trouver les sections nécessaires
    scent_data_section = sections_data.get(SCENT_DATA_ID)
    scent_metadata_section = sections_data.get(SCENT_METADATA_ID)
    scent_offsets_section = sections_data.get(SCENT_OFFSETS_ID)
    name_tables_section = sections_data.get(NAME_TABLES_ID)
    instance_types_section = sections_data.get(INSTANCE_TYPES_ID)
    
    print(f"  Sections trouvées:")
    print(f"    SCENT_DATA_ID (0x{SCENT_DATA_ID:08x}): {scent_data_section is not None}")
    print(f"    SCENT_METADATA_ID (0x{SCENT_METADATA_ID:08x}): {scent_metadata_section is not None}")
    print(f"    SCENT_OFFSETS_ID (0x{SCENT_OFFSETS_ID:08x}): {scent_offsets_section is not None}")
    
    if not scent_data_section:
        print("Section de données Scent introuvable")
        return None
    
    if not scent_metadata_section:
        print("Section de métadonnées Scent introuvable")
        return None

    # Extraire les noms si disponible
    names = {}
    if name_tables_section:
        name_data = data[name_tables_section["offset"]:name_tables_section["offset"] + name_tables_section["size"]]
        current_offset = 0
        name_index = 0
        while current_offset < len(name_data):
            name = read_string(name_data, current_offset)
            if name:
                names[name_index] = name
                name_index += 1
            current_offset += len(name) + 1

    # Préparer les bornes de 0x25022 (pour lire TUID à partir d'adresses u32)
    inst_start = None
    inst_end = None
    if instance_types_section:
        inst_start = instance_types_section['offset']
        inst_end = instance_types_section['offset'] + instance_types_section['size'] * instance_types_section['count']

    # Extraire les Scents
    print("Extraction des Scents...")
    scent_count = 0
    scent_instances = []
    
    for i in range(scent_metadata_section['count']):
        entry_offset = scent_metadata_section['offset'] + i * scent_metadata_section['size']
        
        # Structure des métadonnées (16 bytes):
        # TUID (8) + NameOffset (4) + ZoneIndex (2) + Padding (2)
        tuid = struct.unpack(">Q", data[entry_offset:entry_offset+8])[0]
        name_offset = read_u32_be(data, entry_offset + 8)
        zone_index = read_u16_be(data, entry_offset + 12)  # Zone sur 2 bytes big-endian
        padding = data[entry_offset + 14:entry_offset + 16]
        
        # Collecter le pointeur vers le nom
        if name_offset > 0 and name_offset < len(data):
            pass  # Suppression de la collecte de pointeurs
        
        # Lire le nom
        name = "Unknown_Scent"
        if name_offset < len(data):
            name = read_string(data, name_offset) or f"Scent_{i+1}"
        
        # Extraire les données Scent
        if i < scent_data_section['count']:
            data_offset = scent_data_section['offset'] + i * scent_data_section['size']
            
            # Structure des données Scent (16 bytes):
            # Offset (4) + Count (4) + Padding (8)
            offsets_list_addr = read_u32_be(data, data_offset)
            count = read_u32_be(data, data_offset + 4)
            padding_data = data[data_offset + 8:data_offset + 16]

            # Extraire les références (détection auto):
            # 1) Essayer u32 adresse -> TUID (format 0x25022)
            # 2) Si échec, fallback u64 TUID direct (format legacy)
            instance_references = []
            if offsets_list_addr and count and scent_offsets_section:
                for j in range(count):
                    ptr_pos = offsets_list_addr + j * 4
                    tuid_val = 0
                    # Essai u32 adresse -> TUID (normaliser à l'alignement 16B des entrées 0x25022)
                    if inst_start is not None and ptr_pos + 4 <= len(data):
                        addr = read_u32_be(data, ptr_pos)
                        def read_tuid_at(a: int) -> int:
                            if inst_start <= a < inst_end:
                                rel = a - inst_start
                                base = a - (rel % 16)
                                if inst_start <= base < inst_end and base + 8 <= len(data):
                                    return struct.unpack(">Q", data[base:base+8])[0]
                            return 0
                        # 1) Adresse absolue vers 0x25022
                        tuid_val = read_tuid_at(addr)
                        # 2) Si pas valide, interpréter la valeur comme offset relatif à 0x25022
                        if tuid_val == 0:
                            tuid_val = read_tuid_at(inst_start + addr)
                        # 3) Si toujours pas valide, interpréter comme index (val * 16)
                        if tuid_val == 0:
                            tuid_val = read_tuid_at(inst_start + (addr * 16))
                    # Fallback u64 direct
                    if tuid_val == 0:
                        q_addr = offsets_list_addr + j * 8
                        if q_addr + 8 <= len(data):
                            tuid_val = struct.unpack(">Q", data[q_addr:q_addr+8])[0]
                    instance_references.append({
                        'index': j,
                        'address': ptr_pos,
                        'tuid': tuid_val
                    })

            scent_instance = {
                'name': name,
                'tuid': tuid,
                'zone': zone_index,  # Utiliser le vrai index de zone (2 bytes)
                'name_offset': name_offset,
                'metadata_padding': padding.hex(),
                'offset': offsets_list_addr,
                'count': count,
                'data_padding': padding_data.hex(),
                'instance_references': instance_references
            }
            
            scent_instances.append(scent_instance)
            scent_count += 1
    
    print(f"  {scent_count} Scents extraits")
    return scent_instances
