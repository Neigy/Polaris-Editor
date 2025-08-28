# shared/utils.py
import os
import struct

def read_u32_be(data: bytes, offset: int) -> int:
    return struct.unpack_from('>I', data, offset)[0]

def read_u64_be(data: bytes, offset: int) -> int:
    return struct.unpack_from('>Q', data, offset)[0]

def read_u16_be(data: bytes, offset: int) -> int:
    return struct.unpack_from('>H', data, offset)[0]

def read_float_be(data: bytes, offset: int) -> float:
    return struct.unpack_from('>f', data, offset)[0]

def read_string(data: bytes, offset: int, max_length: int = 64) -> str:
    """Lit une chaîne null-terminée depuis les données"""
    string_bytes = b""
    for i in range(max_length):
        if offset + i >= len(data) or data[offset + i] == 0:
            break
        string_bytes += bytes([data[offset + i]])
    return string_bytes.decode('utf-8', errors='ignore')

def sanitize_name(name: str) -> str:
    return name.replace(" ", "_").replace("/", "_").replace("\\", "_")

def find_next_level_dir(base: str = "gp_prius") -> str:
    """Trouve le prochain nom de dossier disponible pour l'extraction"""
    i = 1
    while True:
        if i == 1:
            level_name = base
        else:
            level_name = f"{base}{i}"
        
        if not os.path.exists(level_name):
            return level_name
        i += 1

def find_section_by_id(sections: list, section_id: int):
    """Trouve une section par son ID"""
    return next((s for s in sections if s['id'] == section_id), None)

def parse_sections(data: bytes) -> list:
    """Parse les en-têtes de sections du fichier IGHW"""
    section_count = struct.unpack_from('>I', data, 0x08)[0]
    sections = []
    offset = 0x20
    
    for _ in range(section_count):
        section_id, section_offset, flag = struct.unpack_from('>IIB', data, offset)
        item_count = int.from_bytes(data[offset+9:offset+12], 'big')
        elem_size = struct.unpack_from('>I', data, offset+12)[0]
        sections.append({
            'id': section_id,
            'offset': section_offset,
            'flag': flag,
            'count': item_count,
            'size': elem_size
        })
        offset += 0x10
    
    return sections
