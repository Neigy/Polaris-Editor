# extract/paths_builder.py
import os
import struct
import json
from shared.constants import (
    PATH_DATA_ID, PATH_METADATA_ID, PATH_POINTS_ID, NAME_TABLES_ID, INSTANCE_TYPES_ID,
    INSTANCE_TYPES
)
from shared.utils import (
    read_u32_be, read_u16_be, read_float_be, read_string, sanitize_name, 
    find_next_level_dir, find_section_by_id, parse_sections
)
# Suppression de la collecte de pointeurs

def extract_paths_from_dat(dat_path):
    """Extrait les données Path avec leurs métadonnées"""
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
    path_data_section = sections_data.get(PATH_DATA_ID)
    path_metadata_section = sections_data.get(PATH_METADATA_ID)
    path_points_section = sections_data.get(PATH_POINTS_ID)
    name_tables_section = sections_data.get(NAME_TABLES_ID)
    instance_types_section = sections_data.get(INSTANCE_TYPES_ID)
    
    print(f"  Sections trouvées:")
    print(f"    PATH_DATA_ID (0x{PATH_DATA_ID:08x}): {path_data_section is not None}")
    print(f"    PATH_METADATA_ID (0x{PATH_METADATA_ID:08x}): {path_metadata_section is not None}")
    print(f"    PATH_POINTS_ID (0x{PATH_POINTS_ID:08x}): {path_points_section is not None}")
    
    if not path_data_section:
        print("Section de données Path introuvable")
        return None
    
    if not path_metadata_section:
        print("Section de métadonnées Path introuvable")
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

    # Extraire les Paths
    print("Extraction des Paths...")
    path_count = 0
    path_instances = []
    
    for i in range(path_metadata_section['count']):
        entry_offset = path_metadata_section['offset'] + i * path_metadata_section['size']
        
        # Structure des métadonnées (16 bytes):
        # TUID (8) + NameOffset (4) + ZoneIndex (2) + Padding (2)
        tuid = struct.unpack(">Q", data[entry_offset:entry_offset+8])[0]
        name_offset = read_u32_be(data, entry_offset + 8)
        zone_index = read_u16_be(data, entry_offset + 12)  # Zone sur 2 bytes big-endian
        padding = data[entry_offset + 14:entry_offset + 16]
        
        # Collecter le pointeur vers le nom
        if name_offset < len(data):  # Supprimé la condition > 0
            pass  # Suppression de la collecte de pointeurs
        
        # Lire le nom
        name = "Unknown_Path"
        if name_offset < len(data):
            name = read_string(data, name_offset) or f"Path_{i+1}"
        
        # Extraire les données Path
        if i < path_data_section['count']:
            data_offset = path_data_section['offset'] + i * path_data_section['size']
            
            # Structure des données Path (16 bytes):
            # Point Offset (4) + Unknown (4) + Total Duration (4) + Flags (2) + Point Count (2)
            point_offset = read_u32_be(data, data_offset)
            unknown = read_u32_be(data, data_offset + 4)
            total_duration = read_float_be(data, data_offset + 8)
            flags = read_u16_be(data, data_offset + 12)
            point_count = read_u16_be(data, data_offset + 14)
            
            # Collecter le pointeur vers les points du path
            if point_offset < len(data):  # Supprimé la condition > 0
                pass  # Suppression de la collecte de pointeurs
            
            # Convertir la durée en millisecondes
            duration_ms = int(total_duration * 1000 / 30)
            
            # Extraire les points du path
            points = []
            if point_offset and point_count and path_points_section:
                for j in range(point_count):
                    point_addr = point_offset + j * 16  # 16 bytes par point (X, Y, Z, Timestamp)
                    if point_addr + 16 <= len(data):
                        x = read_float_be(data, point_addr)
                        y = read_float_be(data, point_addr + 4)
                        z = read_float_be(data, point_addr + 8)
                        timestamp = read_float_be(data, point_addr + 12)
                        
                        # Convertir le timestamp en millisecondes
                        timestamp_ms = int(timestamp * 1000 / 30)
                        
                        points.append({
                            'index': j,
                            'address': point_addr,
                            'position': {'x': x, 'y': y, 'z': z},
                            'timestamp': timestamp,
                            'timestamp_ms': timestamp_ms
                        })
            
            path_instance = {
                'name': name,
                'tuid': tuid,
                'zone': zone_index,  # Utiliser le vrai index de zone (2 bytes)
                'name_offset': name_offset,
                'metadata_padding': padding.hex(),
                'point_offset': point_offset,
                'unknown': unknown,
                'total_duration': total_duration,
                'duration_ms': duration_ms,
                'flags': flags,
                'point_count': point_count,
                'points': points
            }
            
            path_instances.append(path_instance)
            path_count += 1
    
    print(f"  {path_count} Paths extraits")
    return path_instances
