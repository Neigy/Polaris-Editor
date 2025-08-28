# extract/controllers_builder.py
import os
import struct
import json
from shared.constants import (
    CONTROLLER_DATA_ID, CONTROLLER_METADATA_ID, NAME_TABLES_ID, INSTANCE_TYPES_ID,
    INSTANCE_TYPES
)
from shared.utils import (
    read_u32_be, read_u16_be, read_float_be, read_string, sanitize_name, 
    find_next_level_dir, find_section_by_id, parse_sections
)
# Suppression de la collecte de pointeurs

def extract_controllers_from_dat(dat_path):
    """Extrait les données Controller avec leurs métadonnées"""
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
    controller_data_section = sections_data.get(CONTROLLER_DATA_ID)
    controller_metadata_section = sections_data.get(CONTROLLER_METADATA_ID)
    name_tables_section = sections_data.get(NAME_TABLES_ID)
    instance_types_section = sections_data.get(INSTANCE_TYPES_ID)
    
    if not controller_data_section:
        print("Section de données Controller introuvable")
        return None
    
    if not controller_metadata_section:
        print("Section de métadonnées Controller introuvable")
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

    # Extraire les Controllers
    print("Extraction des Controllers...")
    controller_count = 0
    controller_instances = []
    
    for i in range(controller_metadata_section['count']):
        entry_offset = controller_metadata_section['offset'] + i * controller_metadata_section['size']
        
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
        name = "Unknown_Controller"
        if name_offset < len(data):
            name = read_string(data, name_offset) or f"Controller_{i+1}"
        
        # Extraire les données Controller
        if i < controller_data_section['count']:
            data_offset = controller_data_section['offset'] + i * controller_data_section['size']
            
            subfile_offset = read_u32_be(data, data_offset)
            subfile_length = read_u32_be(data, data_offset + 4)
            
            # Collecter le pointeur vers le subfile
            if subfile_offset > 0 and subfile_offset < len(data):
                pass  # Suppression de la collecte de pointeurs
            
            # Position (3 floats)
            pos_x = read_float_be(data, data_offset + 8)
            pos_y = read_float_be(data, data_offset + 12)
            pos_z = read_float_be(data, data_offset + 16)
            
            # Rotation (3 floats)
            rot_x = read_float_be(data, data_offset + 20)
            rot_y = read_float_be(data, data_offset + 24)
            rot_z = read_float_be(data, data_offset + 28)
            
            scale = read_float_be(data, data_offset + 32)
            
            # Scale Y/Z (2x f32) et Padding (4 bytes)
            scale_y = read_float_be(data, data_offset + 36)
            scale_z = read_float_be(data, data_offset + 40)
            padding_data = data[data_offset + 44:data_offset + 48]
            
            controller_instance = {
                'name': name,
                'tuid': tuid,
                'zone': zone_index,  # Utiliser le vrai index de zone (2 bytes)
                'name_offset': name_offset,
                'metadata_padding': padding.hex(),
                'subfile_offset': subfile_offset,
                'subfile_length': subfile_length,
                'position': {'x': pos_x, 'y': pos_y, 'z': pos_z},
                'rotation': {'x': rot_x, 'y': rot_y, 'z': rot_z},
                'scale': scale,
                'scale_y': scale_y,
                'scale_z': scale_z,
                'data_padding': padding_data.hex()
            }
            
            controller_instances.append(controller_instance)
            controller_count += 1
    
    print(f"  {controller_count} Controllers extraits")
    return controller_instances
