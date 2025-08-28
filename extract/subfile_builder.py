# extract/subfile_extractor.py
import os
import struct
import json
from shared.constants import (
    HOST_CLASS_ID, LOCAL_CLASS_ID, CLASS_ENUM_ID
)
from shared.utils import (
    read_u32_be, read_u16_be, read_float_be, read_string, sanitize_name
)

def find_subfile_section_addresses(data):
    """Trouve les adresses de départ des sections de subfiles dans le fichier principal"""
    
    # Parser le fichier principal gp_prius.dat
    if len(data) < 32:
        return None, None
    
    # Vérifier l'en-tête IGHW
    if data[:4] != b"IGHW":
        return None, None
    
    # Parser l'en-tête selon la version
    version_major = struct.unpack(">H", data[4:6])[0]
    version_minor = struct.unpack(">H", data[6:8])[0]
    
    # Lire le nombre de sections selon la version
    if version_major == 0:
        section_count = struct.unpack(">H", data[8:10])[0]
        section_start = 16
    else:
        section_count = struct.unpack(">I", data[12:16])[0]
        section_start = 32
    
    host_section_address = None
    local_section_address = None
    
    # Parser toutes les sections pour trouver les sections de subfiles
    for i in range(section_count):
        offset = section_start + i * 16
        if offset + 16 <= len(data):
            section_id, data_offset, flag, item_count = struct.unpack(">IIB3s", data[offset:offset+12])
            item_count = int.from_bytes(item_count, "big")
            size = struct.unpack(">I", data[offset+12:offset+16])[0]
            
            # Chercher les sections de subfiles
            if section_id == HOST_CLASS_ID:
                host_section_address = data_offset
            elif section_id == LOCAL_CLASS_ID:
                local_section_address = data_offset
    
    return host_section_address, local_section_address

def determine_subfile_type(subfile_offset, data):
    """Détermine si un subfile est .host ou .local en fonction de sa position"""
    
    # Trouver dynamiquement les adresses des sections host/local dans ce fichier
    host_section_address, local_section_address = find_subfile_section_addresses(data)
    
    if host_section_address is None and local_section_address is None:
        print(f"    ⚠️  Aucune section host/local trouvée, assume host")
        return 'host'
    
    # Déterminer le type en fonction de l'offset du subfile
    if host_section_address is not None and local_section_address is not None:
        # Comparer les adresses de départ pour déterminer l'ordre
        if local_section_address < host_section_address:
            # Section local est avant section host
            if subfile_offset >= local_section_address and subfile_offset < host_section_address:
                return 'local'
            elif subfile_offset >= host_section_address:
                return 'host'
            else:
                # Avant les deux sections, assume host
                print(f"    ⚠️  Offset {subfile_offset:08X} avant sections host/local, assume host")
                return 'host'
        else:
            # Section host est avant section local
            if subfile_offset >= host_section_address and subfile_offset < local_section_address:
                return 'host'
            elif subfile_offset >= local_section_address:
                return 'local'
            else:
                # Avant les deux sections, assume host
                print(f"    ⚠️  Offset {subfile_offset:08X} avant sections host/local, assume host")
                return 'host'
    elif host_section_address is not None:
        # Si on n'a que la section host
        if subfile_offset >= host_section_address:
            return 'host'
        else:
            print(f"    ⚠️  Offset {subfile_offset:08X} avant section host ({host_section_address:08X}), assume host")
            return 'host'
    elif local_section_address is not None:
        # Si on n'a que la section local
        if subfile_offset >= local_section_address:
            return 'local'
        else:
            print(f"    ⚠️  Offset {subfile_offset:08X} avant section local ({local_section_address:08X}), assume host")
            return 'host'
    else:
        return 'host'  # Par défaut

def extract_subfile_from_instance(instance, data, instance_name, output_dir):
    """Extrait un subfile IGHW d'une instance et le sauvegarde"""
    
    # Déterminer le type de subfile (host ou local)
    subfile_offset = None
    subfile_length = None
    
    # Mobys
    if 'subfile_offset' in instance and 'subfile_length' in instance:
        subfile_offset = instance['subfile_offset']
        subfile_length = instance['subfile_length']
    
    # Clues
    elif 'subfile_offset' in instance and 'subfile_length' in instance:
        subfile_offset = instance['subfile_offset']
        subfile_length = instance['subfile_length']
    
    # Controllers
    elif 'subfile_offset' in instance and 'subfile_length' in instance:
        subfile_offset = instance['subfile_offset']
        subfile_length = instance['subfile_length']
    
    # Vérifier que le subfile existe et est valide
    if not subfile_offset or not subfile_length:
        return None
    
    # Créer un fichier .dat même pour les subfiles vides (selon les règles)
    if subfile_offset == 0 or subfile_length == 0:
        # Créer un fichier vide
        filename = f"{instance_name}_CLASS.{subfile_type}.dat"
        subfile_path = os.path.join(output_dir, filename)
        with open(subfile_path, 'wb') as f:
            f.write(b'')  # Fichier vide
        return True
    
    # Vérifier que le subfile est valide
    if subfile_offset + subfile_length > len(data):
        print(f"    ⚠️  Subfile invalide pour {instance_name}: offset={subfile_offset}, length={subfile_length}")
        return None
    
    # Extraire le subfile
    subfile_data = data[subfile_offset:subfile_offset + subfile_length]
    
    # Vérifier l'en-tête IGHW
    if subfile_data[:4] != b"IGHW":
        print(f"    ⚠️  En-tête IGHW invalide pour {instance_name}")
        return None
    
    # Déterminer le type de subfile (host ou local)
    subfile_type = determine_subfile_type(subfile_offset, data)
    
    # Déterminer le nom du fichier
    filename = f"{instance_name}_CLASS.{subfile_type}.dat"
    
    # Créer le répertoire de sortie
    os.makedirs(output_dir, exist_ok=True)
    
    # Sauvegarder le subfile brut
    subfile_path = os.path.join(output_dir, filename)
    with open(subfile_path, 'wb') as f:
        f.write(subfile_data)
    
            # print(f"    ✅ Subfile extrait: {filename} ({len(subfile_data)} bytes)")
    return True

def extract_all_subfiles_from_instances(instances, data, output_dir):
    """Extrait tous les subfiles des instances fournies"""
    
    extracted_count = 0
    
    for instance in instances:
        instance_name = instance.get('name', 'Unknown')
        sanitized_name = sanitize_name(instance_name)
        
        subfile_extracted = extract_subfile_from_instance(instance, data, sanitized_name, output_dir)
        if subfile_extracted:
            extracted_count += 1
    
    print(f"  {extracted_count} subfiles extraits")
    return extracted_count 