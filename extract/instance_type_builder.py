# extract/instance_type_builder.py
import os
import struct
import json
from shared.constants import (
    INSTANCE_TYPES_ID, SCENT_DATA_ID, SCENT_OFFSETS_ID, POD_DATA_ID, POD_OFFSETS_ID,
    AREA_DATA_ID, AREA_OFFSETS_ID, CLUE_INFO_ID, VOLUME_METADATA_ID,
    INSTANCE_TYPES
)
from shared.utils import (
    read_u32_be, read_u16_be, read_float_be, read_string, sanitize_name, 
    find_next_level_dir, find_section_by_id, parse_sections
)
# Suppression de la collecte de pointeurs

class InstanceTypeManager:
    """Gestionnaire central pour les types d'instances et la collecte de pointeurs"""
    
    def __init__(self):
        self.instance_types = {}  # TUID -> Type mapping
        self.instance_entries = []  # Liste des entrées dans la section Instance Types
        self.hierarchical_pointers = {}  # Collecte des pointeurs hiérarchiques
        
    def extract_instance_types_from_dat(self, dat_path):
        """Extrait la section Instance Types et initialise le gestionnaire"""
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

        # Trouver la section Instance Types
        instance_types_section = sections_data.get(INSTANCE_TYPES_ID)
        
        if not instance_types_section:
            print("Section Instance Types introuvable")
            return None

        print(f"Extraction de la section Instance Types (0x{INSTANCE_TYPES_ID:08x})...")
        
        # Extraire les entrées Instance Types
        for i in range(instance_types_section['count']):
            entry_offset = instance_types_section['offset'] + i * instance_types_section['size']
            
            # Structure: TUID (8) + Type (4) + Padding (4)
            tuid = struct.unpack(">Q", data[entry_offset:entry_offset+8])[0]
            type_id = read_u32_be(data, entry_offset + 8)
            padding = data[entry_offset + 12:entry_offset + 16]
            
            if tuid != 0xFFFFFFFFFFFFFFFF:
                type_name = INSTANCE_TYPES.get(type_id, f"Unknown_{type_id}")
                
                instance_entry = {
                    'index': i,
                    'tuid': tuid,
                    'type_id': type_id,
                    'type_name': type_name,
                    'padding': padding.hex(),
                    'address': entry_offset
                }
                
                self.instance_types[tuid] = type_id
                self.instance_entries.append(instance_entry)
                
                # Collecter le pointeur vers cette entrée
                global_pointer_collector.add_pointer(
                    entry_offset, 
                    entry_offset, 
                    f"Instance Type entry - {type_name}", 
                    f"0x{INSTANCE_TYPES_ID:08X}"
                )
        
        print(f"  {len(self.instance_entries)} types d'instances extraits")
        return self.instance_entries

    def collect_hierarchical_pointers(self, dat_path):
        """Collecte tous les pointeurs hiérarchiques depuis les sections Data vers Instance Types"""
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

        print("Collecte des pointeurs hiérarchiques...")
        
        # Collecter les pointeurs pour chaque type de section
        self._collect_scent_pointers(data, sections_data)
        self._collect_pod_pointers(data, sections_data)
        self._collect_area_pointers(data, sections_data)
        self._collect_clue_pointers(data, sections_data)
        
        return self.hierarchical_pointers

    def _collect_scent_pointers(self, data, sections_data):
        """Collecte les pointeurs hiérarchiques pour les Scents"""
        scent_data_section = sections_data.get(SCENT_DATA_ID)
        scent_offsets_section = sections_data.get(SCENT_OFFSETS_ID)
        
        if not scent_data_section or not scent_offsets_section:
            return
        
        print("  Collecte des pointeurs Scent...")
        
        for i in range(scent_data_section['count']):
            data_offset = scent_data_section['offset'] + i * scent_data_section['size']
            
            # Structure des données Scent: Offset (4) + Count (4) + Padding (8)
            offset = read_u32_be(data, data_offset)
            count = read_u32_be(data, data_offset + 4)
            
            # Pointeur de niveau 1: Scent Data -> Scent Offsets
            if offset > 0 and offset < len(data):
                global_pointer_collector.add_pointer(
                    data_offset, 
                    offset, 
                    "Scent Data -> Scent Offsets", 
                    f"0x{SCENT_DATA_ID:08X}"
                )
                
                # Pointeurs de niveau 2: Scent Offsets -> Instance Types
                for j in range(count):
                    offset_addr = offset + j * 8  # 8 bytes par référence (TUID seulement)
                    if offset_addr + 8 <= len(data):
                        instance_tuid = struct.unpack(">Q", data[offset_addr:offset_addr+8])[0]
                        
                        if instance_tuid != 0xFFFFFFFFFFFFFFFF:
                            # Trouver l'entrée correspondante dans Instance Types
                            if instance_tuid in self.instance_types:
                                type_id = self.instance_types[instance_tuid]
                                type_name = INSTANCE_TYPES.get(type_id, f"Unknown_{type_id}")
                                
                                global_pointer_collector.add_pointer(
                                    offset_addr, 
                                    instance_tuid, 
                                    f"Scent Offset -> {type_name} Instance", 
                                    f"0x{SCENT_OFFSETS_ID:08X}"
                                )
                                
                                # Enregistrer dans la hiérarchie
                                self.hierarchical_pointers[f"scent_{i}_{j}"] = {
                                    'data_section': SCENT_DATA_ID,
                                    'offsets_section': SCENT_OFFSETS_ID,
                                    'instance_tuid': instance_tuid,
                                    'type_id': type_id,
                                    'type_name': type_name,
                                    'level1_pointer': (data_offset, offset),
                                    'level2_pointer': (offset_addr, instance_tuid)
                                }

    def _collect_pod_pointers(self, data, sections_data):
        """Collecte les pointeurs hiérarchiques pour les Pods"""
        pod_data_section = sections_data.get(POD_DATA_ID)
        pod_offsets_section = sections_data.get(POD_OFFSETS_ID)
        
        if not pod_data_section or not pod_offsets_section:
            return
        
        print("  Collecte des pointeurs Pod...")
        
        for i in range(pod_data_section['count']):
            data_offset = pod_data_section['offset'] + i * pod_data_section['size']
            
            # Structure des données Pod: Offset (4) + Count (4) + Padding (8)
            offset = read_u32_be(data, data_offset)
            count = read_u32_be(data, data_offset + 4)
            
            # Pointeur de niveau 1: Pod Data -> Pod Offsets
            if offset > 0 and offset < len(data):
                global_pointer_collector.add_pointer(
                    data_offset, 
                    offset, 
                    "Pod Data -> Pod Offsets", 
                    f"0x{POD_DATA_ID:08X}"
                )
                
                # Pointeurs de niveau 2: Pod Offsets -> Instance Types
                for j in range(count):
                    offset_addr = offset + j * 4  # 4 bytes par offset
                    if offset_addr + 4 <= len(data):
                        ref_addr = read_u32_be(data, offset_addr)
                        if ref_addr + 16 <= len(data):
                            # Structure: TUID (8) + Type (4) + Padding (4)
                            instance_tuid = struct.unpack(">Q", data[ref_addr:ref_addr+8])[0]
                            instance_type = read_u32_be(data, ref_addr + 8)
                            
                            if instance_tuid != 0xFFFFFFFFFFFFFFFF:
                                type_name = INSTANCE_TYPES.get(instance_type, f"Unknown_{instance_type}")
                                
                                global_pointer_collector.add_pointer(
                                    offset_addr, 
                                    ref_addr, 
                                    f"Pod Offset -> {type_name} Reference", 
                                    f"0x{POD_OFFSETS_ID:08X}"
                                )
                                
                                # Enregistrer dans la hiérarchie
                                self.hierarchical_pointers[f"pod_{i}_{j}"] = {
                                    'data_section': POD_DATA_ID,
                                    'offsets_section': POD_OFFSETS_ID,
                                    'instance_tuid': instance_tuid,
                                    'type_id': instance_type,
                                    'type_name': type_name,
                                    'level1_pointer': (data_offset, offset),
                                    'level2_pointer': (offset_addr, ref_addr)
                                }

    def _collect_area_pointers(self, data, sections_data):
        """Collecte les pointeurs hiérarchiques pour les Areas"""
        area_data_section = sections_data.get(AREA_DATA_ID)
        area_offsets_section = sections_data.get(AREA_OFFSETS_ID)
        
        if not area_data_section or not area_offsets_section:
            return
        
        print("  Collecte des pointeurs Area...")
        
        for i in range(area_data_section['count']):
            data_offset = area_data_section['offset'] + i * area_data_section['size']
            
            # Structure des données Area: Path Offset (4) + Volume Offset (4) + Path Count (2) + Volume Count (2) + Padding (4)
            path_offset = read_u32_be(data, data_offset)
            volume_offset = read_u32_be(data, data_offset + 4)
            path_count = read_u16_be(data, data_offset + 8)
            volume_count = read_u16_be(data, data_offset + 10)
            
            # Pointeurs vers les paths
            if path_offset > 0 and path_offset < len(data):
                global_pointer_collector.add_pointer(
                    data_offset, 
                    path_offset, 
                    "Area Data -> Path References", 
                    f"0x{AREA_DATA_ID:08X}"
                )
                
                for j in range(min(path_count, 100)):
                    offset_addr = path_offset + j * 4
                    if offset_addr + 4 <= len(data):
                        addr = read_u32_be(data, offset_addr)
                        if addr + 8 <= len(data):
                            path_tuid = struct.unpack(">Q", data[addr:addr+8])[0]
                            
                            if path_tuid != 0xFFFFFFFFFFFFFFFF:
                                global_pointer_collector.add_pointer(
                                    offset_addr, 
                                    addr, 
                                    "Area Path Offset -> Path TUID", 
                                    f"0x{AREA_OFFSETS_ID:08X}"
                                )
                                
                                self.hierarchical_pointers[f"area_path_{i}_{j}"] = {
                                    'data_section': AREA_DATA_ID,
                                    'offsets_section': AREA_OFFSETS_ID,
                                    'instance_tuid': path_tuid,
                                    'type_id': 1,  # Path
                                    'type_name': "Path",
                                    'level1_pointer': (data_offset, path_offset),
                                    'level2_pointer': (offset_addr, addr)
                                }
            
            # Pointeurs vers les volumes
            if volume_offset > 0 and volume_offset < len(data):
                global_pointer_collector.add_pointer(
                    data_offset + 4, 
                    volume_offset, 
                    "Area Data -> Volume References", 
                    f"0x{AREA_DATA_ID:08X}"
                )
                
                for j in range(min(volume_count, 100)):
                    offset_addr = volume_offset + j * 4
                    if offset_addr + 4 <= len(data):
                        addr = read_u32_be(data, offset_addr)
                        if addr + 8 <= len(data):
                            volume_tuid = struct.unpack(">Q", data[addr:addr+8])[0]
                            
                            if volume_tuid != 0xFFFFFFFFFFFFFFFF:
                                global_pointer_collector.add_pointer(
                                    offset_addr, 
                                    addr, 
                                    "Area Volume Offset -> Volume TUID", 
                                    f"0x{AREA_OFFSETS_ID:08X}"
                                )
                                
                                self.hierarchical_pointers[f"area_volume_{i}_{j}"] = {
                                    'data_section': AREA_DATA_ID,
                                    'offsets_section': AREA_OFFSETS_ID,
                                    'instance_tuid': volume_tuid,
                                    'type_id': 2,  # Volume
                                    'type_name': "Volume",
                                    'level1_pointer': (data_offset + 4, volume_offset),
                                    'level2_pointer': (offset_addr, addr)
                                }

    def _collect_clue_pointers(self, data, sections_data):
        """Collecte les pointeurs hiérarchiques pour les Clues"""
        clue_info_section = sections_data.get(CLUE_INFO_ID)
        volume_metadata_section = sections_data.get(VOLUME_METADATA_ID)
        
        if not clue_info_section or not volume_metadata_section:
            return
        
        print("  Collecte des pointeurs Clue...")
        
        for i in range(clue_info_section['count']):
            info_offset = clue_info_section['offset'] + i * clue_info_section['size']
            
            # Structure des données Clue: Volume TUID Offset (4) + Subfile Offset (4) + Subfile Length (4) + Class ID (4)
            volume_tuid_offset = read_u32_be(data, info_offset)
            subfile_offset = read_u32_be(data, info_offset + 4)
            
            # Pointeur vers le volume TUID
            if volume_tuid_offset > 0 and volume_tuid_offset < len(data):
                global_pointer_collector.add_pointer(
                    info_offset, 
                    volume_tuid_offset, 
                    "Clue Info -> Volume TUID", 
                    f"0x{CLUE_INFO_ID:08X}"
                )
                
                if volume_tuid_offset + 8 <= len(data):
                    volume_tuid = struct.unpack(">Q", data[volume_tuid_offset:volume_tuid_offset+8])[0]
                    
                    if volume_tuid != 0xFFFFFFFFFFFFFFFF:
                        self.hierarchical_pointers[f"clue_volume_{i}"] = {
                            'data_section': CLUE_INFO_ID,
                            'volume_section': VOLUME_METADATA_ID,
                            'instance_tuid': volume_tuid,
                            'type_id': 2,  # Volume
                            'type_name': "Volume",
                            'level1_pointer': (info_offset, volume_tuid_offset),
                            'subfile_pointer': (info_offset + 4, subfile_offset)
                        }
            
            # Pointeur vers les données subfile
            if subfile_offset > 0 and subfile_offset < len(data):
                global_pointer_collector.add_pointer(
                    info_offset + 4, 
                    subfile_offset, 
                    "Clue Info -> Subfile Data", 
                    f"0x{CLUE_INFO_ID:08X}"
                )

    def get_instance_type_info(self, tuid):
        """Récupère les informations d'un type d'instance par TUID"""
        if tuid in self.instance_types:
            type_id = self.instance_types[tuid]
            return {
                'tuid': tuid,
                'type_id': type_id,
                'type_name': INSTANCE_TYPES.get(type_id, f"Unknown_{type_id}")
            }
        return None

    def get_hierarchical_pointers_summary(self):
        """Retourne un résumé des pointeurs hiérarchiques collectés"""
        summary = {
            'total_pointers': len(self.hierarchical_pointers),
            'by_type': {},
            'by_section': {}
        }
        
        for key, pointer_info in self.hierarchical_pointers.items():
            type_name = pointer_info['type_name']
            data_section = pointer_info['data_section']
            
            if type_name not in summary['by_type']:
                summary['by_type'][type_name] = 0
            summary['by_type'][type_name] += 1
            
            if data_section not in summary['by_section']:
                summary['by_section'][data_section] = 0
            summary['by_section'][data_section] += 1
        
        return summary

# Instance globale du gestionnaire
instance_type_manager = InstanceTypeManager()
