# main.py
import sys
import os
from extract.region_builder import extract_regions_from_dat
from shared.utils import find_next_level_dir

def rebuild_dat_from_folder(source_dir, output_path):
    from rebuild.mobys_rebuilder import rebuild_mobys_from_folder
    from rebuild.controllers_rebuilder import rebuild_controllers_from_folder
    from rebuild.names_registry import build_name_tables_section
    from rebuild.paths_rebuilder import rebuild_paths_from_folder
    from rebuild.volumes_rebuilder import rebuild_volumes_from_folder
    from rebuild.clues_rebuilder import rebuild_clues_from_folder
    from rebuild.pods_rebuilder import rebuild_pods_from_folder
    from rebuild.areas_rebuilder import rebuild_areas_from_folder
    from rebuild.scents_rebuilder import rebuild_scents_from_folder
    from rebuild.zones_rebuilder import rebuild_zones_from_folder
    # TODO: Import other rebuilders
    
    all_sections = {}
    # Réinitialiser l’agrégateur host/local
    from rebuild.classfiles_aggregator import reset, build_sections
    reset()
    
    # Name tables d'abord (communes)
    name_sections, name_to_offset = build_name_tables_section(source_dir)
    all_sections.update(name_sections)

    # Rebuild each type
    all_sections.update(rebuild_mobys_from_folder(source_dir, name_to_offset))
    all_sections.update(rebuild_controllers_from_folder(source_dir))
    all_sections.update(rebuild_paths_from_folder(source_dir, name_to_offset))

    # Volumes (métadonnées + matrices)
    vol_sections = rebuild_volumes_from_folder(source_dir, name_to_offset)
    all_sections.update(vol_sections)

    # Mapping TUID Volume -> offset d'entrée, aligné au même ordre
    from rebuild.volumes_rebuilder import compute_volume_meta_mapping
    volume_meta_tuid_to_offset = compute_volume_meta_mapping(source_dir)

    # Instance Types (0x00025022): construire une table GLOBALE couvrant toutes les références
    from rebuild.instance_types_global import build_instance_types_global
    inst_sections, inst_types_map = build_instance_types_global(source_dir)
    all_sections.update(inst_sections)

    # Clues (metadata + info + subfiles) – utilisent 0x25022 global
    all_sections.update(rebuild_clues_from_folder(source_dir, name_to_offset, inst_types_map))

    # Areas, Pods, Scents
    all_sections.update(rebuild_areas_from_folder(source_dir, name_to_offset, inst_types_map))
    all_sections.update(rebuild_pods_from_folder(source_dir, name_to_offset, inst_types_map))
    all_sections.update(rebuild_scents_from_folder(source_dir, name_to_offset, inst_types_map))

    # Zones (metadata, offsets, counts) – on laisse les "Region" pour plus tard
    all_sections.update(rebuild_zones_from_folder(source_dir))
    
    # Ajouter les sections host/local globales agrégées
    all_sections.update(build_sections())

    # Assemble
    from rebuild.sections_assembler import assemble_sections
    assemble_sections(all_sections, output_path, version_major=1, version_minor=1)

def main():
    # Support drag-and-drop: if only one argument (the file path), assume extraction
    if len(sys.argv) == 2 and os.path.isfile(sys.argv[1]):
        dat_path = sys.argv[1]
        print(f"[INFO] Fichier détecté via drag-and-drop: {dat_path}")
        
        # Utiliser un nom de dossier automatique basé sur le nom du fichier
        output_dir = find_next_level_dir()
        os.makedirs(output_dir, exist_ok=True)
        
        # Extraction simple des régions
        extract_regions_from_dat(dat_path, output_dir)
        return
    
    if len(sys.argv) < 3:
        print("Usage: python main.py <extract|repack|mkheader> <path_to_gpprius.dat or folder|output_file> [output_dir]")
        print("Exemples:")
        print("  python main.py extract gp_prius.dat")
        print("  python main.py extract gp_prius.dat my_level")
        print("  python main.py extract gp_prius.dat gp_prius2")
        print("  python main.py mkheader empty.dat")
        return
    
    command = sys.argv[1].lower()
    target = sys.argv[2]
    
    # Nom du niveau (optionnel, par défaut automatique)
    level_name = sys.argv[3] if len(sys.argv) > 3 else None
    
    if command == "extract":
        if not os.path.isfile(target):
            print(f"❌ Erreur: Le fichier {target} n'existe pas")
            return
        
        print(f"[INFO] Extraction complète...")
        
        # Créer le dossier de sortie
        if level_name:
            output_dir = level_name
        else:
            output_dir = find_next_level_dir()
        
        os.makedirs(output_dir, exist_ok=True)
        print(f"[INFO] Dossier de sortie: {output_dir}")
        
        # Extraction simple des régions
        extract_regions_from_dat(target, output_dir)
        
        print(f"✅ Extraction terminée dans {output_dir}")
        print(f"📁 Structure: {output_dir}/default/[zones]")
        
    elif command == "repack":
        if not os.path.isdir(target):
            print(f"❌ Erreur: Le dossier {target} n'existe pas")
            return
        
        print(f"[INFO] Repackage...")
        print(f"[INFO] Dossier source: {target}")
        
        # Définir le fichier de sortie
        output_path = sys.argv[3] if len(sys.argv) > 3 else f"{os.path.basename(target)}_rebuilt.dat"
        print(f"[INFO] Fichier de sortie: {output_path}")
        
        # Appel à la fonction de rebuild (à implémenter)
        rebuild_dat_from_folder(target, output_path)
        
        print(f"✅ Repackage terminé dans {output_path}")
    
    elif command == "mkheader":
        # Créer un fichier IGHW vide (juste l'entête)
        from rebuild.ighw_header import write_empty_ighw_file
        output_path = target
        version_major = int(sys.argv[3]) if len(sys.argv) > 3 else 1
        version_minor = int(sys.argv[4]) if len(sys.argv) > 4 else 0
        write_empty_ighw_file(output_path, version_major=version_major, version_minor=version_minor)
        print(f"✅ En-tête IGHW écrit dans {output_path} (v{version_major}.{version_minor})")
        
    elif command == "genlua":
        # Génère un fichier instances.lua depuis un dossier d'extraction
        extraction_dir = target
        if not os.path.isdir(extraction_dir):
            print(f"❌ Erreur: Le dossier {extraction_dir} n'existe pas")
            return
        out_path = sys.argv[3] if len(sys.argv) > 3 else None
        from tools.generate_instances_lua import generate_instances_lua
        produced = generate_instances_lua(extraction_dir, out_path)
        print(f"✅ instances.lua généré: {produced}")

    elif command == "genhandles":
        # Génère un fichier instance.lua (variables + handle:new(a,b,c,d))
        extraction_dir = target
        if not os.path.isdir(extraction_dir):
            print(f"❌ Erreur: Le dossier {extraction_dir} n'existe pas")
            return
        out_path = sys.argv[3] if len(sys.argv) > 3 else None
        from tools.generate_instance_handles_lua import generate_instance_handles_lua
        produced = generate_instance_handles_lua(extraction_dir, out_path)
        print(f"✅ instance.lua généré: {produced}")

    elif command == "gui":
        # Lance une GUI minimale pour éditer rapidement les instances JSON
        initial_dir = target if os.path.isdir(target) else None
        from gui.editor import launch
        launch(initial_dir)

    else:
        print(f"❌ Commande inconnue: {command}")
        print("Commandes disponibles: extract, repack, mkheader, genlua, genhandles, gui")

if __name__ == "__main__":
    print("[LOG] Lancement du script principal...")
    main()
