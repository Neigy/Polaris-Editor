# extract/pods_builder.py
import os
import struct
import json
from shared.constants import (
    POD_DATA_ID, POD_METADATA_ID, POD_OFFSETS_ID, NAME_TABLES_ID, INSTANCE_TYPES_ID,
    INSTANCE_TYPES
)
from shared.utils import (
    read_u32_be, read_u16_be, read_float_be, read_string, sanitize_name, 
    find_next_level_dir, find_section_by_id, parse_sections
)
# Suppression de la collecte de pointeurs

def extract_pods_from_dat(dat_path):
    """Extrait les données Pod avec leurs métadonnées"""
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
    pod_data_section = sections_data.get(POD_DATA_ID)
    pod_metadata_section = sections_data.get(POD_METADATA_ID)
    pod_offsets_section = sections_data.get(POD_OFFSETS_ID)
    name_tables_section = sections_data.get(NAME_TABLES_ID)
    instance_types_section = sections_data.get(INSTANCE_TYPES_ID)
    
    print(f"  Sections trouvées:")
    print(f"    POD_DATA_ID (0x{POD_DATA_ID:08x}): {pod_data_section is not None}")
    print(f"    POD_METADATA_ID (0x{POD_METADATA_ID:08x}): {pod_metadata_section is not None}")
    print(f"    POD_OFFSETS_ID (0x{POD_OFFSETS_ID:08x}): {pod_offsets_section is not None}")
    
    if not pod_data_section:
        print("Section de données Pod introuvable")
        return None
    
    if not pod_metadata_section:
        print("Section de métadonnées Pod introuvable")
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

    # Extraire les Pods
    print("Extraction des Pods...")
    pod_count = 0
    pod_instances = []
    
    for i in range(pod_metadata_section['count']):
        entry_offset = pod_metadata_section['offset'] + i * pod_metadata_section['size']
        
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
        name = "Unknown_Pod"
        if name_offset < len(data):
            name = read_string(data, name_offset) or f"Pod_{i+1}"
        
        # Extraire les données Pod
        if i < pod_data_section['count']:
            data_offset = pod_data_section['offset'] + i * pod_data_section['size']
            
            # Structure des données Pod (16 bytes):
            # Offset (4) + Count (4) + Padding (8)
            offset = read_u32_be(data, data_offset)
            count = read_u32_be(data, data_offset + 4)
            padding_data = data[data_offset + 8:data_offset + 16]
            
            # Collecter le pointeur vers les références d'instances
            if offset > 0 and offset < len(data):
                pass  # Suppression de la collecte de pointeurs
            
            # Collecter les pointeurs de niveau 2 dans la section d'offsets
            if offset and count:
                for j in range(count):  # Collecter TOUTES les références
                    offset_addr = offset + j * 4  # 4 bytes par offset
                    if offset_addr + 4 <= len(data):
                        ref_addr = read_u32_be(data, offset_addr)
                        if ref_addr > 0 and ref_addr < len(data):
                            pass  # Suppression de la collecte de pointeurs
            
            # Extraire les références aux instances
            instance_references = []
            if offset and count:
                for j in range(count):  # Extraire TOUTES les références
                    # Lire l'offset vers la référence (4 bytes)
                    offset_addr = offset + j * 4  # 4 bytes par offset
                    if offset_addr + 4 <= len(data):
                        ref_addr = read_u32_be(data, offset_addr)
                        if ref_addr + 16 <= len(data):
                            # Lire la référence (16 bytes: TUID + Type + Padding)
                            instance_tuid = struct.unpack(">Q", data[ref_addr:ref_addr+8])[0]
                            instance_type = read_u32_be(data, ref_addr + 8)
                            instance_padding = data[ref_addr + 12:ref_addr + 16]
                            
                            # Mapper le type à un nom connu
                            type_name = INSTANCE_TYPES.get(instance_type, f"Unknown_{instance_type}")
                            
                            instance_references.append({
                                'index': j,
                                'offset_address': offset_addr,
                                'reference_address': ref_addr,
                                'tuid': instance_tuid,
                                'type': instance_type,
                                'type_name': type_name,
                                'padding': instance_padding.hex()
                            })
            
            pod_instance = {
                'name': name,
                'tuid': tuid,
                'zone': zone_index,  # Utiliser le vrai index de zone (2 bytes)
                'name_offset': name_offset,
                'metadata_padding': padding.hex(),
                'offset': offset,
                'count': count,
                'data_padding': padding_data.hex(),
                'instance_references': instance_references
            }
            
            pod_instances.append(pod_instance)
            pod_count += 1
    
    print(f"  {pod_count} Pods extraits")
    return pod_instances
