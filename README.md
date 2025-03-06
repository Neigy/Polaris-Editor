# PriusMobyManager Documentation

Ce projet analyse les fichiers `gp_prius.dat` et `region.dat` au format IGHW, utilisés dans certains jeux pour stocker des données de niveau (mobys, volumes, chemins, etc.). Ce README documente les sections connues dans ces fichiers, leurs rôles, et leurs structures.

## Format IGHW

- **Magic** : `IGHW` (big-endian) ou `WHGI` (little-endian), suivi de la version (major/minor, 2 octets chacun).
- **En-tête** :
  - Version 0 : Section count à `0x0A` (2 octets), sections commencent à `0x10`.
  - Version 1 : Section count à `0x0C` (4 octets), sections commencent à `0x20`.
- **Section** : Chaque entrée fait 16 octets (ID, offset, count/size, padding/elem_size).

## Sections Connues

Voici les sections identifiées dans `gp_prius.dat`, organisées par type de données :

### Général
| Offset       | Rôle                        | Structure des données                                      | Notes                                                                 |
|--------------|-----------------------------|-----------------------------------------------------------|----------------------------------------------------------------------|
| `0x00011300` | Tableaux de noms            | Chaînes null-terminated consécutives                      | Indexées par TUID ou position dans d'autres sections.                |
| `0x00025022` | Types des instances         | 16 octets : TUID (8), Type (4), Padding (4)               | Types : 0=Moby, 1=Path, 2=Volume, 3=Clue, 4=Controller, 5=Scent, etc.|

### Mobys
| Offset       | Rôle                        | Structure des données                                      | Notes                                                                 |
|--------------|-----------------------------|-----------------------------------------------------------|----------------------------------------------------------------------|
| `0x00025048` | Instances Mobys             | 80 octets : Index/Group (4), Unk (16), Pos/Rot/Scale (28), Unk (32) | Coordonnées en float, rotation en radians.                  |
| `0x0002504C` | Métadonnées Mobys           | 16 octets : TUID (8), NameOffset (4), Zone (4)            | Zone dans les 4 derniers octets.                                    |

### Cuboids/Volumes/Clues
| Offset       | Rôle                        | Structure des données                                      | Notes                                                                 |
|--------------|-----------------------------|-----------------------------------------------------------|----------------------------------------------------------------------|
| `0x0002505C` | Transformations Cuboids     | 64 octets : Matrice 4x4 (16 floats)                       | Position extraite des floats 12-14 (x, y, z).                       |
| `0x00025060` | Métadonnées Cuboids         | 16 octets : TUID (8), NameOffset (4), Zone (4)            | Inclut Volumes et Clues, type défini par `0x00025022`.              |
| `0x00025064` | Infos Clues                 | 16 octets : TUIDOffset (4), IGHWRef (4), ResLen (4), Class (4) | Pointe vers un TUID dans le fichier.                           |
| `0x00025068` | Métadonnées Clues           | 16 octets : TUID (8), NameOffset (4), Zone (4)            | Zone dans les 4 derniers octets.                                    |

### Controllers
| Offset       | Rôle                        | Structure des données                                      | Notes                                                                 |
|--------------|-----------------------------|-----------------------------------------------------------|----------------------------------------------------------------------|
| `0x0002506C` | Données Controllers         | 48 octets : Offset/Length (8), Pos/Rot/Scale (36), Padding (4) | IGHW imbriqué à l’offset spécifié.                              |
| `0x00025070` | Métadonnées Controllers     | 16 octets : TUID (8), NameOffset (4), Zone (4)            | Zone dans les 4 derniers octets.                                    |
| `0x00025020` | IGHW imbriqué (Controllers) | Sous-fichier IGHW (version 0.2 ou autre)                  | Contient configs (ex. `0x0002501C`).                                |
| `0x00025030` | IGHW imbriqué (Controllers) | Sous-fichier IGHW (version 0.2 ou autre)                  | Similaire à `0x00025020`.                                           |

### Paths
| Offset       | Rôle                        | Structure des données                                      | Notes                                                                 |
|--------------|-----------------------------|-----------------------------------------------------------|----------------------------------------------------------------------|
| `0x00025050` | Métadonnées Paths           | 16 octets : DataOffset (4), TypeID (4), Duration (4), Flags/Points (4) | Duration en frames (float).                                |
| `0x00025054` | TUIDs Paths                 | 16 octets : TUID (8), NameOffset (4), Zone (4)            | Zone dans les 4 derniers octets.                                    |
| `0x00025058` | Points des Paths            | 16 octets par point : X, Y, Z, Timestamp (4 floats)       | Timestamp converti en ms (x1000/30).                                |

### Areas
| Offset       | Rôle                        | Structure des données                                      | Notes                                                                 |
|--------------|-----------------------------|-----------------------------------------------------------|----------------------------------------------------------------------|
| `0x00025080` | Données Areas               | 16 octets : (Path) Offset (4) ou (Volume) Offset/Count (8) | Type dépend de `0x00025022` (1=Path, 6=Area).                      |
| `0x00025084` | Métadonnées Areas           | 16 octets : TUID (8), NameOffset (4), Zone (4)            | Zone dans les 4 derniers octets.                                    |
| `0x00025088` | Offsets Areas               | 4 octets par offset : Adresse vers liste de TUIDs         | Pointe vers des éléments (TUID, Type, Zone).                        |

### Pods
| Offset       | Rôle                        | Structure des données                                      | Notes                                                                 |
|--------------|-----------------------------|-----------------------------------------------------------|----------------------------------------------------------------------|
| `0x00025074` | Données Pods                | 16 octets : Offset (4), Count (4), Padding (8)            | Offset vers liste dans `0x0002507C`.                                |
| `0x00025078` | Métadonnées Pods            | 16 octets : TUID (8), NameOffset (4), Zone (4)            | Zone dans les 4 derniers octets.                                    |
| `0x0002507C` | Offsets Pods                | 4 octets par offset : Adresse vers éléments               | Éléments : TUID (8), Type (4), Padding/Zone (4).                    |

### Scents
| Offset       | Rôle                        | Structure des données                                      | Notes                                                                 |
|--------------|-----------------------------|-----------------------------------------------------------|----------------------------------------------------------------------|
| `0x0002508C` | Données Scents              | 16 octets : Pointer (4), Count (4), Padding (8)           | Pointer vers offsets dans `0x00025094`.                             |
| `0x00025090` | Métadonnées Scents          | 16 octets : TUID (8), NameOffset (4), Zone (4)            | Zone dans les 4 derniers octets.                                    |
| `0x00025094` | Offsets Scents              | 4 octets par offset : Adresse vers instances              | Instances pointées : TUID (8).                                      |

### Régions et Zones
| Offset       | Rôle                        | Structure des données                                      | Notes                                                                 |
|--------------|-----------------------------|-----------------------------------------------------------|----------------------------------------------------------------------|
| `0x00025005` | Régions                     | 16 octets : ZoneOffset (4), ZoneCount (4), DataOffset (4), Index (4) | Nom à `DataOffset` (64 octets).                            |
| `0x00025008` | Rendering Zones (noms)      | 144 octets : Nom (64), Counts par type (9x8)              | Types : Moby, Path, Volume, etc.                                    |
| `0x0002500C` | Rendering Zones (offsets)   | 36 octets : 9 offsets (4 chacun)                          | Pointe vers listes de TUIDs par type.                               |
| `0x00025010` | Région par défaut           | Nom "default" + Offset (4), Count (4)                     | Liste d’indices à l’offset (ex. 9 éléments).                        |
| `0x00025014` | Liste liée à `0x00025010`  | Indices (4 octets chacun)                                 | Exemple : 18 octets pour 4 éléments.                                |

### Données non utilisées
| Offset       | Rôle                        | Structure des données                                      | Notes                                                                 |
|--------------|-----------------------------|-----------------------------------------------------------|----------------------------------------------------------------------|
| `0x00025006` | Adresses/Données inutilisées| Variable (ex. offsets ou données brutes)                  | Pas de références claires dans le fichier.                          |

## Notes Supplémentaires
- **Zones** : Dans les sections avec TUID et NameOffset (ex. `0x0002504C`, `0x00025060`), les 4 derniers octets représentent la zone de rendu (ex. `0x00000001`).
- **TUIDs** : Identifiants uniques sur 8 octets, souvent liés à un nom dans `0x00011300` ou localement.
- **Types** : Définis dans `0x00025022`, essentiels pour différencier Mobys, Paths, Volumes, etc.

## Utilisation
Le script `PriusMobyManager.py` charge ces sections et permet de :
- Lister les données par type (Mobys, Clues, etc.).
- Exporter en CSV (ex. cuboids, controllers).
- Afficher des détails par TUID.

Pour plus d’infos, voir le code source ou contribuer !

---
