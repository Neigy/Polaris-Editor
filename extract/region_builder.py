# extract/region_builder.py
import os
import struct
import json
from shared.constants import (
    REGION_DATA_ID, REGION_POINTERS_ID, ZONE_METADATA_ID, ZONE_OFFSETS_ID, DEFAULT_REGION_NAMES_ID, ZONE_COUNTS_ID,
    NAME_TABLES_ID, INSTANCE_TYPES_ID, INSTANCE_TYPES
)
from shared.utils import (
    read_u32_be, read_u16_be, read_float_be, read_string, sanitize_name, 
    find_next_level_dir, find_section_by_id, parse_sections
)
# Suppression de la collecte de pointeurs
from extract.mobys_builder import extract_mobys_from_dat
from extract.clues_builder import extract_clues_from_dat
from extract.volumes_builder import extract_volumes_from_dat
from extract.controllers_builder import extract_controllers_from_dat
from extract.areas_builder import extract_areas_from_dat
from extract.pods_builder import extract_pods_from_dat
from extract.scents_builder import extract_scents_from_dat
from extract.paths_builder import extract_paths_from_dat
from extract.subfile_builder import extract_all_subfiles_from_instances
from extract.subfile_builder import determine_subfile_type

def extract_regions_from_dat(dat_path, output_dir=None):
    """Extrait toutes les régions et zones avec leurs instances"""
    
    # Utiliser le dossier de sortie spécifié ou le dossier par défaut
    if output_dir is None:
        output_dir = find_next_level_dir()
    
    # Lire le fichier DAT
    with open(dat_path, 'rb') as f:
        data = f.read()

    print("Extraction des instances...")
    
    # Extraire tous les types d'instances
    moby_instances = extract_mobys_from_dat(dat_path) or []
    clue_instances = extract_clues_from_dat(dat_path) or []
    volume_instances = extract_volumes_from_dat(dat_path) or []
    controller_instances = extract_controllers_from_dat(dat_path) or []
    area_instances = extract_areas_from_dat(dat_path) or []
    pod_instances = extract_pods_from_dat(dat_path) or []
    scent_instances = extract_scents_from_dat(dat_path) or []
    path_instances = extract_paths_from_dat(dat_path) or []
    
    # Combiner toutes les instances
    all_instances = []
    all_instances.extend(moby_instances)
    all_instances.extend(clue_instances)
    all_instances.extend(volume_instances)
    all_instances.extend(controller_instances)
    all_instances.extend(area_instances)
    all_instances.extend(pod_instances)
    all_instances.extend(scent_instances)
    all_instances.extend(path_instances)
    
    # Organiser les instances par zone
    zone_instances = {}
    for instance in all_instances:
        zone = instance.get('zone', 0)
        if zone not in zone_instances:
            zone_instances[zone] = []
        zone_instances[zone].append(instance)
    
    # Afficher les statistiques par zone
    zones_used = sorted(zone_instances.keys())
    print(f"Zones utilisées par les instances: {zones_used}")
    
    for zone in zones_used:
        instances = zone_instances[zone]
        moby_count = len([i for i in instances if 'model_index' in i])
        clue_count = len([i for i in instances if 'volume_tuid' in i])
        volume_count = len([i for i in instances if ('transform' in i) or ('transform_matrix' in i)])
        controller_count = len([i for i in instances if 'subfile_offset' in i and 'position' in i and 'model_index' not in i])
        area_count = len([i for i in instances if 'path_offset' in i and 'volume_offset' in i])
        pod_count = len([i for i in instances if 'instance_references' in i and any('type' in ref for ref in i.get('instance_references', []))])
        scent_count = len([i for i in instances if 'instance_references' in i and not any('type' in ref for ref in i.get('instance_references', []))])
        path_count = len([i for i in instances if 'points' in i and 'total_duration' in i])
        
        print(f"  Zone {zone}: {len(instances)} instances ({moby_count} mobys, {clue_count} clues, {volume_count} volumes, {controller_count} controllers, {area_count} areas, {pod_count} pods, {scent_count} scents, {path_count} paths)")
    
    # Parser les sections de régions et zones
    version_major = struct.unpack(">H", data[4:6])[0]
    section_count = struct.unpack(">H" if version_major == 0 else ">I", 
                                 data[0x0A if version_major == 0 else 0x0C:
                                      0x0C if version_major == 0 else 0x10])[0]
    section_start = 0x10 if version_major == 0 else 0x20
    
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
    
    # Trouver les sections de régions et zones
    region_data_section = sections_data.get(REGION_DATA_ID)
    zone_metadata_section = sections_data.get(ZONE_METADATA_ID)
    zone_offsets_section = sections_data.get(ZONE_OFFSETS_ID)
    default_region_names_section = sections_data.get(DEFAULT_REGION_NAMES_ID)
    zone_counts_section = sections_data.get(ZONE_COUNTS_ID)
    name_tables_section = sections_data.get(NAME_TABLES_ID)
    
    if not region_data_section:
        print("Section de données de région introuvable")
        return None
    
    if not zone_metadata_section:
        print("Section de métadonnées de zone introuvable")
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
    
    # Extraire les compteurs de zones
    zone_counts = []
    if zone_counts_section:
        for i in range(zone_counts_section['count']):
            offset = zone_counts_section['offset'] + i * 2
            if offset + 2 <= len(data):
                count = read_u16_be(data, offset)
                zone_counts.append(count)
                
                # Collecter les compteurs de zones (pas vraiment des pointeurs mais des données importantes)
                # Note: Les compteurs de zones ne sont pas des pointeurs mais des données de comptage
                # global_pointer_collector.add_pointer(offset, count, "Zone count", f"0x{ZONE_COUNTS_ID:08X}")
    
    # Collecter les pointeurs de la section des types d'instances (0x00025022)
    instance_types_section = sections_data.get(INSTANCE_TYPES_ID)
    if instance_types_section:
        print(f"Section des types d'instances trouvée: offset={instance_types_section['offset']}, count={instance_types_section['count']}")
        
        # Collecter les pointeurs vers les TUIDs dans la section des types d'instances
        for i in range(instance_types_section['count']):
            entry_offset = instance_types_section['offset'] + i * 16  # 16 bytes par entrée
            if entry_offset + 16 <= len(data):
                # Lire le TUID (8 bytes)
                tuid = read_u32_be(data, entry_offset)  # Première partie du TUID
                tuid2 = read_u32_be(data, entry_offset + 4)  # Deuxième partie du TUID
                
                # Collecter le pointeur vers le TUID si il n'est pas vide
                if tuid != 0xFFFFFFFF and tuid2 != 0xFFFFFFFF:
                    pass  # Suppression de la collecte de pointeurs
    
    # Collecter les pointeurs de la section des noms de régions par défaut (0x00025010)
    default_region_section = sections_data.get(DEFAULT_REGION_NAMES_ID)
    if default_region_section:
        print(f"Section des noms de régions par défaut trouvée: offset={default_region_section['offset']}, count={default_region_section['count']}")
        
        # Lire l'offset vers la liste d'indices
        if default_region_section['offset'] + 0x48 <= len(data):
            # Structure: 0x40 + Offset (4) + Count (4)
            indices_offset = read_u32_be(data, default_region_section['offset'] + 0x40)
            indices_count = read_u32_be(data, default_region_section['offset'] + 0x44)
            
            # Collecter le pointeur vers la liste d'indices
            if indices_offset > 0 and indices_offset < len(data):
                # Collecter le pointeur à l'adresse exacte 0x0004CEC0 (offset + 0x40)
                pointer_address = default_region_section['offset'] + 0x40
                # Suppression de la collecte de pointeurs
            
            # Collecter chaque index dans la liste
            if indices_offset and indices_count:
                for j in range(indices_count):  # Collecter TOUS les indices
                    index_offset = indices_offset + j * 2  # 2 bytes par index (u16)
                    if index_offset + 2 <= len(data):
                        index_value = read_u16_be(data, index_offset)
                        # SUPPRIMÉ : On ne collecte pas les indices, ce ne sont pas des pointeurs
                        # global_pointer_collector.add_pointer(index_offset, index_value, f"Default region index {j}", f"0x{DEFAULT_REGION_NAMES_ID:08X}")
    
    # Collecter les pointeurs de la section des pointeurs de régions (0x00025006)
    region_pointers_section = sections_data.get(REGION_POINTERS_ID)
    if region_pointers_section:
        print(f"Section des pointeurs de régions trouvée: offset={region_pointers_section['offset']}, count={region_pointers_section['count']}")
        
        # Pour chaque région, il y a un pointeur vers la section 0x0002500C
        for i in range(region_pointers_section['count']):
            pointer_offset = region_pointers_section['offset'] + i * 4
            if pointer_offset + 4 <= len(data):
                pointer_value = read_u32_be(data, pointer_offset)
                if pointer_value > 0 and pointer_value < len(data):
                    pass  # Suppression de la collecte de pointeurs
    
    # Collecter les pointeurs de la section des compteurs de zones (0x00025014)
    zone_counts_section = sections_data.get(ZONE_COUNTS_ID)
    if zone_counts_section:
        print(f"Section des compteurs de zones trouvée: offset={zone_counts_section['offset']}, count={zone_counts_section['count']}")
        
        # Collecter les compteurs de zones (9 compteurs de 2 bytes chacun)
        for i in range(min(zone_counts_section['count'], 9)):
            count_offset = zone_counts_section['offset'] + i * 2
            if count_offset + 2 <= len(data):
                count_value = read_u16_be(data, count_offset)
                # Note: Les compteurs ne sont pas des pointeurs mais des données importantes
                # global_pointer_collector.add_pointer(count_offset, count_value, f"Zone count {i}", f"0x{ZONE_COUNTS_ID:08X}")
    
    # Collecter les pointeurs de la section des noms (0x00011300)
    name_tables_section = sections_data.get(NAME_TABLES_ID)
    if name_tables_section:
        print(f"Section des tables de noms trouvée: offset={name_tables_section['offset']}, count={name_tables_section['count']}")
        
        # Parcourir la section des noms pour trouver les pointeurs vers les chaînes
        name_data = data[name_tables_section['offset']:name_tables_section['offset'] + name_tables_section['count']]
        
        # Chercher les pointeurs vers les chaînes de caractères
        # Note: Cette section contient des chaînes de caractères, pas des pointeurs
        # Les pointeurs vers les noms sont dans les sections de métadonnées
        # Pas besoin de collecter de pointeurs ici car ce sont des données directes
    
    print(f"Compteurs de zones trouvés: {zone_counts}")
    
    # Extraire les offsets de zones de rendu
    zone_render_offsets = []
    if zone_offsets_section:
        for i in range(zone_offsets_section['count']):
            offset = zone_offsets_section['offset'] + i * 4
            if offset + 4 <= len(data):
                render_offset = read_u32_be(data, offset)
                zone_render_offsets.append(f"0x{render_offset:x}")
                
                # Collecter les pointeurs vers les zones de rendu
                if render_offset > 0 and render_offset < len(data):
                    # SUPPRIMÉ : On ne collecte pas les offsets relatifs, ce ne sont pas des pointeurs absolus
                    # global_pointer_collector.add_pointer(offset, render_offset, "Zone render offset pointer", f"0x{ZONE_OFFSETS_ID:08X}")
                    pass
    
    print(f"Offsets de zones de rendu trouvés: {zone_render_offsets}")
    
    # Extraire les régions
    regions = []
    for i in range(region_data_section['count']):
        data_offset = region_data_section['offset'] + i * region_data_section['size']
        
        zone_offset = read_u32_be(data, data_offset)
        zone_count = read_u32_be(data, data_offset + 4)
        name_data_offset = read_u32_be(data, data_offset + 8)
        index = read_u32_be(data, data_offset + 12)
        
        # Collecter les pointeurs de région
        # Suppression de la collecte de pointeurs
        
        # Lire le nom de la région
        region_name = "default"
        if name_data_offset and name_data_offset < len(data):
            region_name = read_string(data, name_data_offset) or "default"
        
        # Extraire les zones de cette région
        zones = []
        if zone_offset and zone_count:
            for j in range(zone_count):
                zone_meta_offset = zone_metadata_section['offset'] + j * zone_metadata_section['size']
                
                # Lire le nom de la zone (64 bytes)
                zone_name = "Unknown_Zone"
                if zone_meta_offset + 64 <= len(data):
                    zone_name_bytes = data[zone_meta_offset:zone_meta_offset + 64]
                    null_pos = zone_name_bytes.find(b'\x00')
                    if null_pos != -1:
                        zone_name_bytes = zone_name_bytes[:null_pos]
                    zone_name = zone_name_bytes.decode('utf-8', errors='ignore').strip()
                    if not zone_name:
                        zone_name = f"Zone_{j+1}"
                
                # Collecter les pointeurs des métadonnées de zone (9 types x 2 valeurs = 18 pointeurs)
                if zone_meta_offset + 136 <= len(data):
                    # Lire les 9 paires (offset + count) pour chaque type d'instance
                    type_data = struct.unpack(">IIIIIIIII IIIIIIIII", data[zone_meta_offset+64:zone_meta_offset+136])
                    type_offsets = type_data[::2]  # Les offsets (9 valeurs)
                    type_counts = type_data[1::2]  # Les compteurs (9 valeurs)
                    
                    # Collecter les pointeurs vers les listes d'instances par type
                    for type_idx, (offset, count) in enumerate(zip(type_offsets, type_counts)):
                        if offset > 0 and offset < len(data) and count > 0:
                            pass  # Suppression de la collecte de pointeurs
                
                # Collecter les pointeurs des offsets de zone
                if zone_offsets_section and zone_offsets_section['offset'] + j * 36 + 36 <= len(data):
                    offset_base = zone_offsets_section['offset'] + j * 36
                    data_offsets = struct.unpack(">IIIIIIIII", data[offset_base:offset_base+36])
                    
                    # Collecter les 9 pointeurs vers les listes d'instances par type
                    for type_idx, data_offset in enumerate(data_offsets):
                        if data_offset > 0 and data_offset < len(data):
                            pass  # Suppression de la collecte de pointeurs
                
                # Trouver les instances de cette zone
                zone_instances_list = zone_instances.get(j, [])
                
                zones.append({
                    'name': zone_name,
                    'index': j,
                    'instances': zone_instances_list
                })
        
        regions.append({
            'name': region_name,
            'index': index,
            'zone_offset': zone_offset,
            'zone_count': zone_count,
            'zones': zones
        })
    
    # Créer la structure de dossiers et sauvegarder les instances
    
    for region in regions:
        region_dir = os.path.join(output_dir, region['name'])
        
        # Créer le dossier de la région
        os.makedirs(region_dir, exist_ok=True)
        
        # Sauvegarder toutes les instances de cette région
        for zone in region['zones']:
            # Créer le dossier de la zone
            zone_dir = os.path.join(region_dir, zone['name'])
            os.makedirs(zone_dir, exist_ok=True)
            
            # Triage: par zone index (constant ici), puis TUID
            zone['instances'].sort(key=lambda inst: (int(inst.get('zone', 0)), int(inst.get('tuid', 0))))
            for instance in zone['instances']:
                # Déterminer le type d'instance et l'extension
                if 'model_index' in instance:  # Moby
                    instance_type = 'moby'
                    extension = '.moby.json'
                elif 'volume_tuid' in instance:  # Clue
                    instance_type = 'clue'
                    extension = '.clue.json'
                elif ('transform' in instance) or ('transform_matrix' in instance):  # Volume
                    instance_type = 'volume'
                    extension = '.volume.json'
                elif 'subfile_offset' in instance and 'position' in instance and 'model_index' not in instance:  # Controller
                    instance_type = 'controller'
                    extension = '.controller.json'
                elif 'path_offset' in instance and 'volume_offset' in instance:  # Area
                    instance_type = 'area'
                    extension = '.area.json'
                elif 'points' in instance and 'total_duration' in instance:  # Path
                    instance_type = 'path'
                    extension = '.path.json'
                elif 'instance_references' in instance and 'offset' in instance and 'count' in instance:
                    # Distinguer entre Pods et Scents basé sur la structure des références
                    references = instance.get('instance_references', [])
                    if references and any('type' in ref for ref in references):
                        # Pods ont des références avec type
                        instance_type = 'pod'
                        extension = '.pod.json'
                    else:
                        # Scents ont des références sans type (juste TUID)
                        instance_type = 'scent'
                        extension = '.scent.json'
                else:
                    continue
                
                # Créer le nom de fichier
                sanitized_name = sanitize_name(instance['name'])
                filename = f"{sanitized_name}{extension}"
                filepath = os.path.join(zone_dir, filename)
                
                # Sauvegarder l'instance
                with open(filepath, 'w', encoding='utf-8') as f:
                    json.dump(instance, f, indent=2, ensure_ascii=False)
                
                # Extraire le subfile si l'instance en a un
                if 'subfile_offset' in instance and 'subfile_length' in instance:
                    subfile_offset = instance['subfile_offset']
                    subfile_length = instance['subfile_length']
                    
                    # Vérifier que le subfile existe et est valide
                    if subfile_offset and subfile_length and subfile_offset != 0 and subfile_length != 0:
                        # Extraire le subfile
                        if subfile_offset + subfile_length <= len(data):
                            subfile_data = data[subfile_offset:subfile_offset + subfile_length]
                            
                            # Vérifier l'en-tête IGHW
                            if subfile_data[:4] == b"IGHW":
                                # Déterminer le type de subfile en fonction de sa position
                                subfile_type = determine_subfile_type(subfile_offset, data)
                                
                                # Créer le nom du fichier subfile
                                subfile_filename = f"{sanitized_name}_CLASS.{subfile_type}.dat"
                                subfile_path = os.path.join(zone_dir, subfile_filename)
                                
                                # Sauvegarder le subfile
                                with open(subfile_path, 'wb') as f:
                                    f.write(subfile_data)
                                
                                # print(f"      ✅ Subfile extrait: {subfile_filename} ({len(subfile_data)} bytes)")
        
        print(f"Région '{region['name']}': {len(region['zones'])} zones extraites")
    
    # Lire et enregistrer les 4 u16 inconnus (tails) de 0x00025008 par zone
    zone_tail_u16 = []
    if zone_metadata_section:
        zcount = zone_metadata_section['count']
        zsize = zone_metadata_section['size']
        zbase = zone_metadata_section['offset']
        for j in range(zcount):
            pos = zbase + j * zsize
            tail_pos = pos + 64 + 9 * 8
            if tail_pos + 8 <= len(data):
                t0, t1, t2, t3 = struct.unpack_from('>HHHH', data, tail_pos)
                zone_tail_u16.append([t0, t1, t2, t3])
            else:
                zone_tail_u16.append([0, 0, 0, 0])

    # Lire la section Instance Types (0x00025022) pour colporter l'ordre exact
    instance_types_entries = []
    inst_types_section = sections_data.get(INSTANCE_TYPES_ID)
    if inst_types_section and inst_types_section['flag'] == 0x00 and inst_types_section['size'] % 16 == 0:
        base = inst_types_section['offset']
        n = inst_types_section['size'] // 16
        for i in range(n):
            pos = base + i * 16
            if pos + 16 <= len(data):
                tuid = struct.unpack('>Q', data[pos:pos+8])[0]
                type_id = read_u32_be(data, pos + 8)
                instance_types_entries.append({'tuid': tuid, 'type': type_id})

    # Créer un fichier de métadonnées d'extraction
    extraction_metadata = {
        'total_instances': len(all_instances),
        'mobys': len(moby_instances),
        'clues': len(clue_instances),
        'volumes': len(volume_instances),
        'controllers': len(controller_instances),
        'areas': len(area_instances),
        'pods': len(pod_instances),
        'scents': len(scent_instances),
        'paths': len(path_instances),
        'regions': len(regions),
        'zones_used': zones_used,
        'zone_counts': zone_counts,
        'zone_render_offsets': zone_render_offsets,
        'zone_tail_u16': zone_tail_u16,
        'instance_types_entries': instance_types_entries
    }
    
    metadata_path = os.path.join(output_dir, "extraction_metadata.json")
    with open(metadata_path, 'w', encoding='utf-8') as f:
        json.dump(extraction_metadata, f, indent=2, ensure_ascii=False)
    
    print(f"Extraction des régions terminée dans {output_dir}")
    return regions

def extract_zones_from_regions(dat_path):
    """Fonction de compatibilité - maintenant intégrée dans extract_regions_from_dat"""
    print("L'extraction des zones est maintenant intégrée dans l'extraction des régions")
    extract_regions_from_dat(dat_path)
