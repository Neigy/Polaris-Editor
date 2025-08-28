#!/usr/bin/env python3
"""
Compare les données JSON et les binaires .dat entre une extraction originale et une
extraction de rebuild. Vérifie que l'extraction → rebuild → extraction donne les
mêmes données.

Par défaut, la comparaison JSON est sémantique: elle ignore les champs d'adresses
et d'offset (ex: offset, name_offset, *address, subfile_offset), qui varient
naturellement entre extractions. Utiliser --strict pour comparer tous les champs.
"""

import os
import json
import sys
import hashlib
from pathlib import Path
from typing import Dict, Any, List, Tuple, Optional

IGNORE_SUFFIXES_DEFAULT = {
    # champs top-level courants
    "offset",
    "name_offset",
    "subfile_offset",
    # suffixes génériques (utilisés dans des chemins comme a.b.c.offset_address)
    "offset_address",
    "reference_address",
    "address",
}


def load_json_file(file_path: Path) -> Dict[str, Any]:
    """Charge un fichier JSON avec gestion d'erreur."""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"Erreur lecture {file_path}: {e}")
        return {}

def compare_float_values(val1: float, val2: float, tolerance: float = 1e-6) -> bool:
    """Compare deux valeurs float avec une tolérance."""
    return abs(val1 - val2) < tolerance

def _should_ignore(current_path: str, ignore_suffixes: Optional[set]) -> bool:
    if not ignore_suffixes:
        return False
    for suffix in ignore_suffixes:
        if current_path.endswith(suffix):
            return True
    return False


def compare_dicts(
    dict1: Dict[str, Any],
    dict2: Dict[str, Any],
    path: str = "",
    tolerance: float = 1e-6,
    ignore_suffixes: Optional[set] = None,
) -> List[str]:
    """Compare deux dictionnaires récursivement et retourne les différences.

    Si ignore_suffixes est fourni, les chemins se terminant par l'un de ces suffixes
    sont ignorés dans la comparaison (permet de rendre la comparaison sémantique).
    """
    differences = []
    
    # Vérifier les clés
    keys1 = set(dict1.keys())
    keys2 = set(dict2.keys())
    
    missing_in_2 = keys1 - keys2
    extra_in_2 = keys2 - keys1
    
    for key in missing_in_2:
        differences.append(f"{path}.{key}: manquant dans le second fichier")
    for key in extra_in_2:
        differences.append(f"{path}.{key}: présent uniquement dans le second fichier")
    
    # Comparer les valeurs communes
    for key in keys1 & keys2:
        val1 = dict1[key]
        val2 = dict2[key]
        current_path = f"{path}.{key}" if path else key

        if _should_ignore(current_path, ignore_suffixes):
            continue
        
        if isinstance(val1, dict) and isinstance(val2, dict):
            differences.extend(compare_dicts(val1, val2, current_path, tolerance, ignore_suffixes))
        elif isinstance(val1, list) and isinstance(val2, list):
            if len(val1) != len(val2):
                differences.append(f"{current_path}: longueurs différentes ({len(val1)} vs {len(val2)})")
            else:
                for i, (item1, item2) in enumerate(zip(val1, val2)):
                    if isinstance(item1, dict) and isinstance(item2, dict):
                        differences.extend(compare_dicts(item1, item2, f"{current_path}[{i}]", tolerance, ignore_suffixes))
                    elif isinstance(item1, (int, float)) and isinstance(item2, (int, float)):
                        if not compare_float_values(float(item1), float(item2), tolerance):
                            differences.append(f"{current_path}[{i}]: {item1} vs {item2}")
                    elif item1 != item2:
                        differences.append(f"{current_path}[{i}]: {item1} vs {item2}")
        elif isinstance(val1, (int, float)) and isinstance(val2, (int, float)):
            if not compare_float_values(float(val1), float(val2), tolerance):
                differences.append(f"{current_path}: {val1} vs {val2}")
        elif val1 != val2:
            differences.append(f"{current_path}: {val1} vs {val2}")
    
    return differences

def _get_instance_base_name(json_path: Path, instance_type: str) -> str:
    """Retourne le nom de base de l'instance (sans suffixe .{type}.json)."""
    suffix = f".{instance_type}.json"
    name = json_path.name
    if name.endswith(suffix):
        return name[: -len(suffix)]
    # Fallback robuste si nom inattendu
    # Exemple: Path.stem de "+.moby.json" renvoie "+.moby" → on retire le dernier suffixe '.moby'
    return Path(name).stem.split(".")[0]


def _hash_file(path: Path) -> str:
    """Retourne le hash SHA256 d'un fichier (utile pour comparer les binaires)."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _compare_sibling_dat_files(orig_json: Path, rebuilt_json: Path, base_name: str) -> List[str]:
    """Compare les .dat frères d'une instance (dans le même dossier que le JSON).

    Règle: on considère comme .dat associés les fichiers de la forme
    "{base_name}_CLASS.*.dat" (ex: "foo_1_CLASS.host.dat", "bar_2_CLASS.local.dat").
    """
    diffs: List[str] = []

    orig_dir = orig_json.parent
    rebuilt_dir = rebuilt_json.parent

    orig_dats = sorted(orig_dir.glob(f"{base_name}_CLASS.*.dat"))
    rebuilt_dats = sorted(rebuilt_dir.glob(f"{base_name}_CLASS.*.dat"))

    # Comparer l'ensemble des noms (pas les chemins absolus)
    orig_names = {p.name for p in orig_dats}
    rebuilt_names = {p.name for p in rebuilt_dats}

    missing_in_rebuilt = orig_names - rebuilt_names
    extra_in_rebuilt = rebuilt_names - orig_names

    if missing_in_rebuilt:
        diffs.append(f".dat manquants côté rebuild: {sorted(missing_in_rebuilt)}")
    if extra_in_rebuilt:
        diffs.append(f".dat en trop côté rebuild: {sorted(extra_in_rebuilt)}")

    # Pour les .dat communs, comparer le contenu binaire
    for shared_name in sorted(orig_names & rebuilt_names):
        o = orig_dir / shared_name
        r = rebuilt_dir / shared_name
        try:
            # Comparaison taille d'abord pour short-circuit
            o_size = o.stat().st_size
            r_size = r.stat().st_size
            if o_size != r_size:
                diffs.append(f"{shared_name}: taille différente ({o_size} vs {r_size})")
                continue
            # Si tailles identiques, comparer via hash
            if _hash_file(o) != _hash_file(r):
                diffs.append(f"{shared_name}: contenu binaire différent")
        except Exception as e:
            diffs.append(f"{shared_name}: erreur comparaison binaire ({e})")

    return diffs


def compare_instance_files(
    original_dir: Path,
    rebuilt_dir: Path,
    instance_type: str,
    ignore_suffixes: Optional[set],
) -> Tuple[int, List[str]]:
    """Compare tous les fichiers d'un type d'instance entre deux répertoires.

    Pour chaque JSON, compare la structure/valeurs (avec tolérance float) puis
    compare les .dat frères éventuels.
    """
    pattern = f"*.{instance_type}.json"
    original_files = list(original_dir.rglob(pattern))
    rebuilt_files = list(rebuilt_dir.rglob(pattern))
    
    print(f"\n=== {instance_type.upper()} ===")
    print(f"Originaux: {len(original_files)}  |  Rebuild: {len(rebuilt_files)}")
    
    if len(original_files) != len(rebuilt_files):
        print(f"[WARN] Nombre de fichiers différent!")
        return len(original_files), ["Nombre de fichiers différent"]
    
    total_differences = []
    matching_files = 0
    files_with_differences = 0
    
    for orig_file in original_files:
        # Trouver le fichier correspondant dans le rebuild
        rel_path = orig_file.relative_to(original_dir)
        rebuilt_file = rebuilt_dir / rel_path
        
        if not rebuilt_file.exists():
            total_differences.append(f"Fichier manquant: {rebuilt_file}")
            continue
        
        # Charger et comparer JSON
        orig_data = load_json_file(orig_file)
        rebuilt_data = load_json_file(rebuilt_file)
        
        if not orig_data or not rebuilt_data:
            total_differences.append(f"Erreur lecture: {orig_file} ou {rebuilt_file}")
            continue
        
        differences = compare_dicts(orig_data, rebuilt_data, ignore_suffixes=ignore_suffixes)

        # Comparer les .dat frères s'il y en a
        base_name = _get_instance_base_name(orig_file, instance_type)
        dat_diffs = _compare_sibling_dat_files(orig_file, rebuilt_file, base_name)
        differences.extend(dat_diffs)
        
        if differences:
            files_with_differences += 1
            # Affichage concis des différences
            print(f"[DIFF] {rel_path}: {len(differences)} diffs")
            for diff in differences[:5]:
                print(f"    {diff}")
            if len(differences) > 5:
                print(f"    ... +{len(differences) - 5} autres")
            total_differences.extend([f"{rel_path}: {diff}" for diff in differences])
        else:
            matching_files += 1
    
    print(f"  Identiques: {matching_files}/{len(original_files)}  |  Différents: {files_with_differences}")
    return len(original_files), total_differences

def main():
    if len(sys.argv) < 3 or len(sys.argv) > 4:
        print("Usage: python tools/compare_extractions.py <original_extraction_dir> <rebuilt_extraction_dir> [--strict]")
        print("Exemples:")
        print("  python tools/compare_extractions.py gp_prius gp_prius2")
        print("  python tools/compare_extractions.py gp_prius gp_prius2 --strict")
        sys.exit(1)

    original_dir = Path(sys.argv[1])
    rebuilt_dir = Path(sys.argv[2])

    strict = len(sys.argv) == 4 and sys.argv[3] == "--strict"
    ignore_suffixes = None if strict else IGNORE_SUFFIXES_DEFAULT
    
    if not original_dir.exists():
        print(f"Erreur: répertoire original '{original_dir}' n'existe pas")
        sys.exit(1)
    
    if not rebuilt_dir.exists():
        print(f"Erreur: répertoire rebuild '{rebuilt_dir}' n'existe pas")
        sys.exit(1)
    
    print(f"Comparaison entre:")
    print(f"  Original: {original_dir}")
    print(f"  Rebuild:  {rebuilt_dir}")
    
    # Comparer les types d'instances
    instance_types = ['moby', 'controller', 'path', 'volume', 'clue', 'area', 'pod', 'scent']
    all_differences = []
    
    for instance_type in instance_types:
        count, differences = compare_instance_files(original_dir, rebuilt_dir, instance_type, ignore_suffixes)
        all_differences.extend(differences)
    
    # Résumé global
    print(f"\n{'='*50}")
    print("RÉSUMÉ GLOBAL")
    print(f"{'='*50}")
    
    if all_differences:
        print(f"[DIFF] {len(all_differences)} différences trouvées")
        print("\nPremières différences:")
        for i, diff in enumerate(all_differences[:50]):
            print(f"  {i+1}. {diff}")
        if len(all_differences) > 50:
            print(f"  ... et {len(all_differences) - 50} autres")
    else:
        print("[OK] Aucune différence trouvée - extraction → rebuild → extraction parfait!")

if __name__ == "__main__":
    main()
