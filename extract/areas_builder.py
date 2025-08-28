# extract/areas_builder.py
import os
import struct
import json
from shared.constants import (
    AREA_DATA_ID, AREA_METADATA_ID, AREA_OFFSETS_ID, NAME_TABLES_ID, INSTANCE_TYPES_ID,
    INSTANCE_TYPES
)
from shared.utils import (
    read_u32_be, read_u16_be, read_float_be, read_string, sanitize_name, 
    find_next_level_dir, find_section_by_id, parse_sections
)
# Suppression de la collecte de pointeurs

def extract_areas_from_dat(dat_path):
    """Extrait les données Area avec leurs métadonnées"""
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
    area_data_section = sections_data.get(AREA_DATA_ID)
    area_metadata_section = sections_data.get(AREA_METADATA_ID)
    area_offsets_section = sections_data.get(AREA_OFFSETS_ID)
    name_tables_section = sections_data.get(NAME_TABLES_ID)
    instance_types_section = sections_data.get(INSTANCE_TYPES_ID)
    
    print(f"  Sections trouvées:")
    print(f"    AREA_DATA_ID (0x{AREA_DATA_ID:08x}): {area_data_section is not None}")
    print(f"    AREA_METADATA_ID (0x{AREA_METADATA_ID:08x}): {area_metadata_section is not None}")
    print(f"    AREA_OFFSETS_ID (0x{AREA_OFFSETS_ID:08x}): {area_offsets_section is not None}")
    
    if not area_data_section:
        print("Section de données Area introuvable")
        return None
    
    if not area_metadata_section:
        print("Section de métadonnées Area introuvable")
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

    # Extraire les Areas
    print("Extraction des Areas...")
    area_count = 0
    area_instances = []

    for i in range(area_metadata_section['count']):
        entry_offset = area_metadata_section['offset'] + i * area_metadata_section['size']

        # Métadonnées (16 bytes)
        tuid = struct.unpack(">Q", data[entry_offset:entry_offset+8])[0]
        name_offset = read_u32_be(data, entry_offset + 8)
        zone_index = read_u16_be(data, entry_offset + 12)
        padding = data[entry_offset + 14:entry_offset + 16]

        name = "Unknown_Area"
        if 0 < name_offset < len(data):
            name = read_string(data, name_offset) or f"Area_{i+1}"

        # Données Area (16 bytes)
        if i < area_data_section['count']:
            data_offset = area_data_section['offset'] + i * area_data_section['size']
            path_offset = read_u32_be(data, data_offset)
            volume_offset = read_u32_be(data, data_offset + 4)
            path_count = read_u16_be(data, data_offset + 8)
            volume_count = read_u16_be(data, data_offset + 10)
            padding_data = data[data_offset + 12:data_offset + 16]

            # Références paths
            path_references = []
            if path_offset and path_count:
                for j in range(path_count):
                    offset_addr = path_offset + j * 4
                    if offset_addr + 4 <= len(data):
                        addr = read_u32_be(data, offset_addr)
                        if 0 < addr + 8 <= len(data):
                            path_tuid = struct.unpack(">Q", data[addr:addr+8])[0]
                            path_references.append({'index': j, 'address': addr, 'tuid': path_tuid})

            # Références volumes
            volume_references = []
            if volume_offset and volume_count:
                for j in range(volume_count):
                    offset_addr = volume_offset + j * 4
                    if offset_addr + 4 <= len(data):
                        addr = read_u32_be(data, offset_addr)
                        if 0 < addr + 8 <= len(data):
                            volume_tuid = struct.unpack(">Q", data[addr:addr+8])[0]
                            volume_references.append({'index': j, 'address': addr, 'tuid': volume_tuid})

            area_instance = {
                'name': name,
                'tuid': tuid,
                'zone': zone_index,
                'name_offset': name_offset,
                'metadata_padding': padding.hex(),
                'path_offset': path_offset,
                'path_count': path_count,
                'volume_offset': volume_offset,
                'volume_count': volume_count,
                'data_padding': padding_data.hex(),
                'path_references': path_references,
                'volume_references': volume_references,
            }

            area_instances.append(area_instance)
            area_count += 1

    print(f"  {area_count} Areas extraits")
    return area_instances
