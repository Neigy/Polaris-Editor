# shared/constants.py

# Section IDs pour les données principales
REGION_DATA_ID = 0x00025005
REGION_POINTERS_ID = 0x00025006  # Pointeurs vers les régions
ZONE_METADATA_ID = 0x00025008
ZONE_OFFSETS_ID = 0x0002500C
DEFAULT_REGION_NAMES_ID = 0x00025010
ZONE_COUNTS_ID = 0x00025014
NAME_TABLES_ID = 0x00011300
NAMES_ID = 0x00011300  # Alias pour la section des noms
INSTANCE_TYPES_ID = 0x00025022

# Section IDs pour les Mobys
MOBY_DATA_ID = 0x00025048
MOBY_METADATA_ID = 0x0002504C

# Section IDs pour les Clues
CLUE_INFO_ID = 0x00025064
CLUE_METADATA_ID = 0x00025068

# Section IDs pour les Volumes
VOLUME_TRANSFORM_ID = 0x0002505C
VOLUME_METADATA_ID = 0x00025060

# Section IDs pour les Controllers
CONTROLLER_DATA_ID = 0x0002506C
CONTROLLER_METADATA_ID = 0x00025070

# Section IDs pour les Areas
AREA_DATA_ID = 0x00025080
AREA_METADATA_ID = 0x00025084
AREA_OFFSETS_ID = 0x00025088

# Section IDs pour les Pods
POD_DATA_ID = 0x00025074
POD_METADATA_ID = 0x00025078
POD_OFFSETS_ID = 0x0002507C

# Section IDs pour les Scents
SCENT_DATA_ID = 0x0002508C
SCENT_METADATA_ID = 0x00025090
SCENT_OFFSETS_ID = 0x00025094

# Section IDs pour les Paths
PATH_DATA_ID = 0x00025050
PATH_METADATA_ID = 0x00025054
PATH_POINTS_ID = 0x00025058

# Section IDs pour les Subfiles IGHW
HOST_CLASS_ID = 0x00025020
LOCAL_CLASS_ID = 0x00025030
CLASS_ENUM_ID = 0x0002501C

# Types d'instances
INSTANCE_TYPES = {
    0: "Moby",
    1: "Path", 
    2: "Volume",
    3: "Clue",
    4: "Controller",
    5: "Scent",
    6: "Area",
    7: "Pod"
}

# Structure pour les zones de rendu
ZONE_RENDERING_STRUCTURE = {
    "name_size": 64,
    "type_count": 9,
    "type_entry_size": 8  # Offset (4) + Count (4)
}
