# extract/mobys_builder.py
import os
import struct
import json
from shared.constants import (
    MOBY_DATA_ID, MOBY_METADATA_ID, NAME_TABLES_ID, INSTANCE_TYPES_ID,
    INSTANCE_TYPES
)
from shared.utils import (
    read_u32_be, read_u16_be, read_float_be, read_string, sanitize_name, 
    find_next_level_dir, find_section_by_id, parse_sections
)
# Suppression de la collecte de pointeurs

def extract_mobys_from_dat(dat_path):
    """Extrait les données Moby avec leurs métadonnées"""
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
    moby_data_section = sections_data.get(MOBY_DATA_ID)
    moby_metadata_section = sections_data.get(MOBY_METADATA_ID)
    name_tables_section = sections_data.get(NAME_TABLES_ID)
    instance_types_section = sections_data.get(INSTANCE_TYPES_ID)
    
    if not moby_data_section:
        print("Section de données Moby introuvable")
        return None
    
    if not moby_metadata_section:
        print("Section de métadonnées Moby introuvable")
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

    # Extraire les Mobys
    print("Extraction des Mobys...")
    moby_count = 0
    moby_instances = []
    
    for i in range(moby_metadata_section['count']):
        entry_offset = moby_metadata_section['offset'] + i * moby_metadata_section['size']
        tuid = struct.unpack(">Q", data[entry_offset:entry_offset+8])[0]
        name_offset = read_u32_be(data, entry_offset + 8)
        zone = read_u32_be(data, entry_offset + 12)
        
        # Collecter le pointeur vers le nom
        if name_offset > 0 and name_offset < len(data):
            pass  # Suppression de la collecte de pointeurs
        
        # Lire le nom
        name = "Unknown_Moby"
        if name_offset < len(data):
            name = read_string(data, name_offset) or f"Moby_{i+1}"
        
        # Extraire les données Moby
        if i < moby_data_section['count']:
            data_offset = moby_data_section['offset'] + i * moby_data_section['size']
            
            model_index = read_u16_be(data, data_offset)
            zone_render_index = read_u16_be(data, data_offset + 2)
            update_dist = read_float_be(data, data_offset + 4)
            display_dist = read_float_be(data, data_offset + 8)
            subfile_offset = read_u32_be(data, data_offset + 12)
            subfile_length = read_u32_be(data, data_offset + 16)
            
            # Collecter le pointeur vers le subfile
            if subfile_offset > 0 and subfile_offset < len(data):
                pass  # Suppression de la collecte de pointeurs
            
            # Position (3 floats)
            pos_x = read_float_be(data, data_offset + 20)
            pos_y = read_float_be(data, data_offset + 24)
            pos_z = read_float_be(data, data_offset + 28)
            
            # Rotation (3 floats)
            rot_x = read_float_be(data, data_offset + 32)
            rot_y = read_float_be(data, data_offset + 36)
            rot_z = read_float_be(data, data_offset + 40)
            
            scale = read_float_be(data, data_offset + 44)
            
            # Flags et autres données
            flags = data[data_offset + 48:data_offset + 56]
            unknown = data[data_offset + 56:data_offset + 60]
            padding = data[data_offset + 60:data_offset + 64]
            
            # Extraire les données de classe si disponible
            class_enum = -1
            if subfile_offset and subfile_length and subfile_offset + subfile_length <= len(data):
                subfile = data[subfile_offset:subfile_offset + subfile_length]
                if subfile[:4] == b"IGHW":
                    sub_version_major = struct.unpack(">H", subfile[4:6])[0]
                    sub_section_count = struct.unpack(">I", subfile[8:12])[0]
                    sub_section_start = 0x20 if sub_version_major >= 2 else 0x10
                    for j in range(sub_section_count):
                        sub_offset = sub_section_start + j * 16
                        if sub_offset + 16 <= len(subfile):
                            sub_id, sub_data_offset = struct.unpack(">II", subfile[sub_offset:sub_offset+8])
                            if sub_id == 0x0002501C:
                                class_offset = subfile_offset + sub_data_offset
                                if class_offset + 4 <= len(data):
                                    class_enum = struct.unpack(">I", data[class_offset:class_offset+4])[0]
                                break
            
            moby_instance = {
                'name': name,
                'tuid': tuid,
                'zone': zone_render_index,  # Utiliser zone_render_index au lieu de zone
                'zone_metadata': zone,  # Garder l'ancien zone pour référence
                'zone_render_index': zone_render_index,
                'model_index': model_index,
                'update_dist': update_dist,
                'display_dist': display_dist,
                'subfile_offset': subfile_offset,
                'subfile_length': subfile_length,
                'position': {'x': pos_x, 'y': pos_y, 'z': pos_z},
                'rotation': {'x': rot_x, 'y': rot_y, 'z': rot_z},
                'scale': scale,
                'flags': flags.hex(),
                'unknown': unknown.hex(),
                'padding': padding.hex(),
                'class_enum': class_enum
            }
            
            moby_instances.append(moby_instance)
            moby_count += 1
    
    print(f"  {moby_count} Mobys extraits")
    return moby_instances
