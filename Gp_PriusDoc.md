# Gp_Prius Documentation

This project digs into the `gp_prius.dat` files, which use the IGHW format to stash level data for *Ratchet & Clank* games on the PS3. We’re talking mobys, volumes, paths—the works. This README spells out the known sections in these files, what they’re for, and how they’re laid out.

## IGHW Format

- **Magic**: Starts with `IGHW` (big-endian), followed by the version (major/minor, 2 bytes each).
- **Header**:
  - Version 0: Section count at `0x0A` (2 bytes), sections start at `0x10`.
  - Version 1: Section count at `0x0C` (4 bytes), sections start at `0x20`.
- **Section**: Each entry is 16 bytes—ID, offset, count/size, and padding/elem_size.

## Known Sections

Here’s what we’ve figured out about the sections in `gp_prius.dat`, grouped by data type:

### General
| Offset       | Role                | Data Structure                              | Notes                                                                         |
|--------------|---------------------|---------------------------------------------|-------------------------------------------------------------------------------|
| `0x00011300` | Name Tables         | Consecutive null-terminated strings         | Indexed by TUID or position in other sections.                                |
| `0x00025022` | Instance Types      | 16 bytes: TUID (8), Type (4), Padding (4)   | Types: 0=Moby, 1=Path, 2=Volume, 3=Clue, 4=Controller, 5=Scent, 6=Area, 7=Pod |

### Mobys
| Offset       | Role                | Data Structure                                      | Notes                                                                |
|--------------|---------------------|-----------------------------------------------------|----------------------------------------------------------------------|
| `0x00025048` | Moby Instances      | 80 bytes: Index/Group (4), Unknown (16), Pos/Rot/Scale (28), Unknown (32) | Coordinates as floats, rotation in radians.    |
| `0x0002504C` | Moby Metadata       | 16 bytes: TUID (8), NameOffset (4), Zone (4)                              | Zone’s in the last 4 bytes.                    |

### Cuboids (Volumes/Clues)
| Offset       | Role                  | Data Structure                                      | Notes                                                               |
|--------------|-----------------------|-----------------------------------------------------|---------------------------------------------------------------------|
| `0x0002505C` | Cuboid Transformations| 64 bytes: 4x4 Matrix (16 floats)                    | Position pulled from floats 12-14 (x, y, z).                        |
| `0x00025060` | Cuboid Metadata       | 16 bytes: TUID (8), NameOffset (4), Zone (4)        | Covers Volumes and Clues; type set by `0x00025022`.                 |
| `0x00025064` | Clue Info             | 16 bytes: TUIDOffset (4), IGHWRef (4), IGHWLength (4), Class (4) | Points to a Cuboid TUID in `0x00025022`, links to an IGHW for class setup, and gives class length. |
| `0x00025068` | Clue Metadata         | 16 bytes: TUID (8), NameOffset (4), Zone (4)        | Zone’s in the last 4 bytes.                                         |

### Controllers
| Offset       | Role                  | Data Structure                                      | Notes                                                                |
|--------------|-----------------------|-----------------------------------------------------|----------------------------------------------------------------------|
| `0x0002506C` | Controller Data       | 48 bytes: IGHWOffset (4), Length (4), Pos/Rot/Scale (36), Padding (4) | Nested IGHW at the listed offset.                  |
| `0x00025070` | Controller Metadata   | 16 bytes: TUID (8), NameOffset (4), Zone (4)        | Zone’s in the last 4 bytes.                                          |

### Paths
| Offset       | Role                  | Data Structure                                      | Notes                                                                |
|--------------|-----------------------|-----------------------------------------------------|----------------------------------------------------------------------|
| `0x00025050` | Path Metadata         | 16 bytes: PathPointOffset (4), Unknown value "07 04 17 76" for all paths (4), Total Duration (4), IntroPATH flag (2) (`01 01` for intro paths, `00 00` otherwise—maybe enemies use firepoints with intro paths), PointNum (2) Int16 (how many lines from PathPointOffset, each line is `0x10`) | |
| `0x00025054` | Path TUIDs            | 16 bytes: TUID (8), NameOffset (4), Zone (4)        | Zone’s in the last 4 bytes.                                         |
| `0x00025058` | Path Points           | 16 bytes per point: X, Y, Z, Timestamp (4 floats)   | Timestamp converted to ms (x1000/30).                               |

### Areas
| Offset       | Role                  | Data Structure                                      | Notes                                                               |
|--------------|-----------------------|-----------------------------------------------------|---------------------------------------------------------------------|
| `0x00025080` | Area Data             | 16 bytes: (Path) Offset/Count (8) or (Volume) Offset/Count (8) | Type depends on `0x00025022` (1=Path, 6=Area).           |
| `0x00025084` | Area Metadata         | 16 bytes: TUID (8), NameOffset (4), Zone (4)        | Zone’s in the last 4 bytes.                                         |
| `0x00025088` | Area Offsets          | 4 bytes per offset: Address to list of TUIDs        | Points to elements (TUID, Type, Zone).                              |

### Pods
| Offset       | Role                  | Data Structure                                      | Notes                                                               |
|--------------|-----------------------|-----------------------------------------------------|---------------------------------------------------------------------|
| `0x00025074` | Pod Data              | 16 bytes: Offset (4), Count (4), Padding (8)        | Offset points to a list in `0x0002507C`.                            |
| `0x00025078` | Pod Metadata          | 16 bytes: TUID (8), NameOffset (4), Zone (4)        | Zone’s in the last 4 bytes.                                         |
| `0x0002507C` | Pod Offsets           | 4 bytes per offset: Address to elements             | Elements: TUID (8), Type (4), Padding/Zone (4).                     |

### Scents
| Offset       | Role                  | Data Structure                                      | Notes                                                               |
|--------------|-----------------------|-----------------------------------------------------|---------------------------------------------------------------------|
| `0x0002508C` | Scent Data            | 16 bytes: Pointer (4), Count (4), Padding (8)       | Pointer leads to offsets in `0x00025094`.                           |
| `0x00025090` | Scent Metadata        | 16 bytes: TUID (8), NameOffset (4), Zone (4)        | Zone’s in the last 4 bytes.                                         |
| `0x00025094` | Scent Offsets         | 4 bytes per offset: Address to instances            | Instances pointed to: TUID (8).                                     |

### Regions and Zones
| Offset       | Role                        | Data Structure                                      | Notes                                                               |
|--------------|-----------------------------|-----------------------------------------------------|---------------------------------------------------------------------|
| `0x00025005` | Regions                     | 16 bytes: ZoneOffset (4), ZoneCount (4), DataOffset (4), Index (4) | Name at `DataOffset` (64 bytes).                     |
| `0x00025008` | Rendering Zones (names)     | 144 bytes: Name (64), Counts per type (9x8)         | Types: Moby, Path, Volume, etc.                                     |
| `0x0002500C` | Rendering Zones (offsets)   | 36 bytes: 9 offsets (4 each)                        | Points to TUID lists by type.                                       |
| `0x00025010` | Default Region              | Name "default" + Offset (4), Count (4)              | List of indices at the offset (e.g., 9 elements).                   |
| `0x00025014` | List tied to `0x00025010`   | Indices (4 bytes each)                              | Example: 18 bytes for 4 elements. Used in places like `0x00025054`. |

### Nested IGHW Sections
| Offset       | Role                        | Data Structure                                      | Notes                                                                |
|--------------|-----------------------------|-----------------------------------------------------|----------------------------------------------------------------------|
| `0x00025020` | Nested IGHW (Class Setup)   | Sub-IGHW file (version 0.2)                         | Instance info can redirecte to a subfile for class configuration     |
| `0x00025030` | Nested IGHW (Class Setup)         | Sub-IGHW file (version 0.2)                   | Similar to `0x00025020`.                                             |

### Unused Data
| Offset       | Role                        | Data Structure                                      | Notes                                                                 |
|--------------|-----------------------------|-----------------------------------------------------|----------------------------------------------------------------------|
| `0x00025006` | Offset                      | Variable (e.g., offsets or raw data)                | No clear references in the file.                                    |

## Extra Notes
- **Zones**: In sections with TUID and NameOffset (e.g., `0x0002504C`, `0x00025060`), the last 4 bytes mark the rendering zone (e.g., `0x00000001`).
- **TUIDs**: 8-byte unique IDs, often tied to a name in `0x00011300` or kept local.
- **Types**: Defined in `0x00025022`, essential for sorting out Mobys, Paths, Volumes, and more.

For more details, poke around the source code or jump in and help out!

