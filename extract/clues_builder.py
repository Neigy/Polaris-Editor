# extract/clues_builder.py
import os
import struct
import json
from shared.constants import (
    CLUE_INFO_ID, CLUE_METADATA_ID, VOLUME_METADATA_ID, NAME_TABLES_ID, INSTANCE_TYPES_ID,
    INSTANCE_TYPES
)
from shared.utils import (
    read_u32_be, read_u16_be, read_float_be, read_string, sanitize_name, 
    find_next_level_dir, find_section_by_id, parse_sections
)
# Suppression de la collecte de pointeurs

def extract_clues_from_dat(dat_path):
    """Extrait les données Clue avec leurs métadonnées"""
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
    clue_info_section = sections_data.get(CLUE_INFO_ID)
    clue_metadata_section = sections_data.get(CLUE_METADATA_ID)
    volume_metadata_section = sections_data.get(VOLUME_METADATA_ID)
    name_tables_section = sections_data.get(NAME_TABLES_ID)
    instance_types_section = sections_data.get(INSTANCE_TYPES_ID)
    
    print(f"  Sections trouvées:")
    print(f"    CLUE_INFO_ID (0x{CLUE_INFO_ID:08x}): {clue_info_section is not None}")
    print(f"    CLUE_METADATA_ID (0x{CLUE_METADATA_ID:08x}): {clue_metadata_section is not None}")
    print(f"    VOLUME_METADATA_ID (0x{VOLUME_METADATA_ID:08x}): {volume_metadata_section is not None}")
    
    if not clue_info_section:
        print("Section d'infos Clue introuvable")
        return None
    
    if not clue_metadata_section:
        print("Section de métadonnées Clue introuvable")
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

    # Extraire les types d'instances si disponible
    instance_types = {}
    if instance_types_section:
        for i in range(instance_types_section['count']):
            entry_offset = instance_types_section['offset'] + i * instance_types_section['size']
            tuid = struct.unpack(">Q", data[entry_offset:entry_offset+8])[0]
            type_id = read_u32_be(data, entry_offset + 8)
            if tuid != 0xFFFFFFFFFFFFFFFF:
                instance_types[tuid] = type_id

    # Extraire les métadonnées de volume (utilisées par les clues)
    volume_metadata = {}
    if volume_metadata_section:
        for i in range(volume_metadata_section['count']):
            entry_offset = volume_metadata_section['offset'] + i * volume_metadata_section['size']
            tuid = struct.unpack(">Q", data[entry_offset:entry_offset+8])[0]
            name_offset = read_u32_be(data, entry_offset + 8)
            zone = read_u16_be(data, entry_offset + 12)  # Zone sur 2 bytes
            
            # Lire le nom
            name = "Unknown_Volume"
            if name_offset < len(data):
                name = read_string(data, name_offset) or f"Volume_{i+1}"
            
            volume_metadata[tuid] = {
                'index': i,
                'tuid': tuid,
                'name': name,
                'name_offset': name_offset,
                'zone': zone
            }

    # Extraire les Clues
    print("Extraction des Clues...")
    clue_count = 0
    clue_instances = []
    
    for i in range(clue_metadata_section['count']):
        entry_offset = clue_metadata_section['offset'] + i * clue_metadata_section['size']
        
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
        name = "Unknown_Clue"
        if name_offset < len(data):
            name = read_string(data, name_offset) or f"Clue_{i+1}"
        
        # Extraire les données de clue
        if i < clue_info_section['count']:
            info_offset = clue_info_section['offset'] + i * clue_info_section['size']
            
            volume_tuid_offset = read_u32_be(data, info_offset)
            subfile_offset = read_u32_be(data, info_offset + 4)
            subfile_length = read_u32_be(data, info_offset + 8)
            class_id = read_u32_be(data, info_offset + 12)
            
            # Collecter les pointeurs vers volume TUID et subfile
            if volume_tuid_offset > 0 and volume_tuid_offset < len(data):
                pass  # Suppression de la collecte de pointeurs
            
            if subfile_offset > 0 and subfile_offset < len(data):
                pass  # Suppression de la collecte de pointeurs
            
            # Trouver le volume associé
            volume_tuid = None
            volume_name = "No volume"
            if volume_tuid_offset and volume_tuid_offset + 8 <= len(data):
                volume_tuid = struct.unpack(">Q", data[volume_tuid_offset:volume_tuid_offset+8])[0]
                if volume_tuid in volume_metadata:
                    volume_name = volume_metadata[volume_tuid]['name']
            
            clue_instance = {
                'name': name,
                'tuid': tuid,
                'zone': zone_index,  # Utiliser le vrai index de zone (2 bytes)
                'name_offset': name_offset,
                'padding': padding.hex(),
                'volume_tuid_offset': volume_tuid_offset,
                'volume_tuid': volume_tuid,
                'volume_name': volume_name,
                'subfile_offset': subfile_offset,
                'subfile_length': subfile_length,
                'class_id': class_id
            }
            
            clue_instances.append(clue_instance)
            clue_count += 1
    
    print(f"  {clue_count} Clues extraits")
    return clue_instances
